import asyncio
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'py_modules'))
sys.modules.setdefault('decky',types.SimpleNamespace())
import armada_main

class RpcLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_start_and_idle_unload_do_not_start_wine_or_scan_games(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as temp:
            decky=types.SimpleNamespace(DECKY_USER_HOME=temp,DECKY_PLUGIN_SETTINGS_DIR=str(Path(temp)/'settings'),logger=types.SimpleNamespace(info=lambda *a:None))
            with patch.object(armada_main,'decky',decky), patch.object(armada_main.ArmadaHost,'refresh',side_effect=AssertionError('unexpected probe')), patch.object(armada_main.ArmadaManager,'refresh',side_effect=AssertionError('unexpected scan')):
                plugin=armada_main.Plugin()
                await asyncio.wait_for(plugin._main(),2)
                await asyncio.wait_for(plugin._unload(),2)
                with self.assertRaisesRegex(ValueError,'unloading'):
                    await plugin.helix2_execute('unused')

    async def test_metadata_discovery_does_not_assess_every_game(self):
        plugin=armada_main.Plugin()
        plugin.manager=types.SimpleNamespace(home=Path('/fixture'),entries={})
        plugin.helix2=types.SimpleNamespace(source_status=lambda:{'ready':False})
        games=[{'id':'steam:1','appid':'3357650','name':'PRAGMATA','folder':'/fixture/game'}, {'id':'steam:2','appid':'2','name':'Other','folder':'/fixture/other'}]
        with patch.object(armada_main,'discover',return_value=(games,[])):
            result=plugin._h2_library()
        self.assertEqual([g['id'] for g in result['games']],['steam:1'])

    async def test_h2_rpcs_run_on_event_loop_thread_without_executor(self):
        plugin = armada_main.Plugin()
        plugin.lock = asyncio.Lock()
        plugin.stopping = False
        current = threading.get_ident()
        def operation(*args):
            self.assertTrue(plugin.lock.locked())
            self.assertEqual(threading.get_ident(), current)
            return args
        plugin._h2_library = operation
        plugin.helix2 = types.SimpleNamespace(status=operation, register_source=operation,
            preview=operation, execute=operation, recover=operation)
        with patch.object(plugin, '_io', side_effect=AssertionError('H2 must not start a worker')):
            self.assertEqual(await plugin.helix2_library(), ())
            self.assertEqual(await plugin.helix2_status('game'), ('game',))
            self.assertEqual(await plugin.helix2_register_source('source'), ('source',))
            self.assertEqual(await plugin.helix2_preview('game', 'settings', {'Int8':'on'}),
                             ('game', 'settings', {'Int8':'on'}))
            self.assertEqual(await plugin.helix2_execute('token'), ('token',))
            self.assertEqual(await plugin.helix2_recover('game'), ('game',))
        self.assertFalse(any(t.name.startswith('helixsr-rpc') for t in threading.enumerate()))

    async def test_h2_exception_releases_lock(self):
        plugin = armada_main.Plugin()
        plugin.lock = asyncio.Lock()
        plugin.stopping = False
        def fail(token):
            self.assertTrue(plugin.lock.locked())
            raise ValueError('injected failure')
        plugin.helix2 = types.SimpleNamespace(execute=fail)
        with self.assertRaisesRegex(ValueError, 'injected failure'):
            await plugin.helix2_execute('token')
        self.assertFalse(plugin.lock.locked())

    async def test_cancelled_legacy_call_holds_lock_until_worker_ends(self):
        plugin = armada_main.Plugin()
        plugin.lock = asyncio.Lock()
        plugin.stopping = False
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        lock_held_at_completion = []
        def refresh():
            started.set()
            if not release.wait(3):
                raise TimeoutError('worker was not released')
            lock_held_at_completion.append(plugin.lock.locked())
            finished.set()
        plugin.manager = types.SimpleNamespace(refresh=refresh)
        task = asyncio.create_task(plugin.library())
        while not started.is_set():
            await asyncio.sleep(0.005)
        self.assertTrue(plugin.lock.locked())
        timer = threading.Timer(0.1, release.set)
        timer.start()
        try:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            timer.join()
        self.assertTrue(finished.is_set())
        self.assertEqual(lock_held_at_completion, [True])
        self.assertFalse(plugin.lock.locked())
        self.assertFalse(any(t.name.startswith('helixsr-rpc') for t in threading.enumerate()))

if __name__=='__main__':unittest.main()
