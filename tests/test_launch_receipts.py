import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
from launch_receipts import LaunchReceipts


class LaunchReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'game-HelixSR'
        self.store = LaunchReceipts(self.root)
        self.original = 'FOO="two words" -dx12'
        self.managed = 'WINEDLLOVERRIDES="dxgi=n,b" FOO="two words" %command% -dx12'

    def prepare(self):
        return self.store.prepare(self.original, self.managed)

    def test_pending_written_before_steam_and_retry_after_reload_preserves_nonce(self):
        intent = self.prepare()
        disk = json.loads((self.root / 'records/launch-options.json').read_text())
        self.assertEqual(disk['before'], self.original)
        self.assertEqual(disk['pending'], intent)
        reopened = LaunchReceipts(self.root)
        self.assertEqual(reopened.owned(self.original)['pending'], intent)
        self.assertEqual(reopened.prepare(self.original, self.managed), intent)
        self.assertEqual(reopened.owned(self.managed), {'before': self.original, 'after': self.managed})

    def test_finalize_only_verified_target_and_nonce(self):
        intent = self.prepare()
        for nonce, actual in [('a' * 32, self.managed), (intent['nonce'], self.original), (intent['nonce'], 'third-party')]:
            with self.assertRaises(ValueError):
                self.store.finalize(nonce, actual)
            self.assertEqual(self.store.owned()['pending'], intent)
        self.assertEqual(self.store.finalize(intent['nonce'], self.managed), {'before': self.original, 'after': self.managed})

    def test_retry_or_extension_preserves_first_original(self):
        intent = self.prepare()
        self.store.finalize(intent['nonce'], self.managed)
        changed = self.managed + ' -novid'
        new = self.store.prepare(self.managed, changed)
        self.assertEqual(self.store.finalize(new['nonce'], changed)['before'], self.original)
        with patch.object(self.store, '_write', side_effect=AssertionError('unnecessary write')):
            self.assertTrue(self.store.remember(self.managed, changed))
            self.assertTrue(self.store.remember(changed, changed))

    def test_interrupted_restore_reconciles_without_losing_original(self):
        self.prepare()
        self.store.owned(self.managed)
        restore = self.store.prepare(self.managed, self.original, True)
        self.assertEqual(self.store.owned(self.managed)['pending'], restore)
        self.assertEqual(self.store.prepare(self.managed, self.original, True), restore)
        self.assertIsNone(self.store.finalize(restore['nonce'], self.original))
        self.assertIsNone(self.store.owned())
        self.assertFalse((self.root / 'records/launch-options.json').exists())

    def test_restore_after_crash_reconciles_live_original(self):
        self.prepare()
        self.store.owned(self.managed)
        self.store.prepare(self.managed, self.original, True)
        self.assertIsNone(LaunchReceipts(self.root).owned(self.original))

    def test_third_party_divergence_never_discards_or_restores_receipt(self):
        self.prepare()
        path = self.root / 'records/launch-options.json'
        original_bytes = path.read_bytes()
        for operation in [lambda: self.store.owned('third-party'), lambda: self.store.prepare('third-party', self.original, True), lambda: self.store.prepare(self.original, 'other')]:
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual(path.read_bytes(), original_bytes)
        self.store.owned(self.managed)
        with self.assertRaises(ValueError):
            self.store.prepare(self.managed, 'other', True)
        with self.assertRaises(ValueError):
            self.store.owned('third-party')

    def test_legacy_receipt_and_invalid_data(self):
        self.root.mkdir()
        directory = self.root / 'records'
        directory.mkdir()
        path = directory / 'launch-options.json'
        path.write_text(json.dumps({'before': self.original, 'after': self.managed}))
        self.assertEqual(self.store.owned(self.managed)['before'], self.original)
        invalid = [[], {'before': [], 'after': 'x'}, {'before': 'x', 'after': 'x' * 16385},
                   {'before': 'x', 'after': 'y', 'pending': {'nonce': 'bad'}}, {'before': 'x', 'after': 'y', 'extra': True}]
        for record in invalid:
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                self.store.owned()
        path.write_text('{"before":"x","before":"z","after":"y"}')
        with self.assertRaises(ValueError):
            self.store.owned()
        for before, after in [(None, 'x'), ('x', 123), ('x\0', 'y'), ('x', 'x')]:
            with self.assertRaises(ValueError):
                self.store.prepare(before, after)

    def test_failed_atomic_replace_keeps_receipt_and_removes_temp(self):
        intent = self.prepare()
        path = self.root / 'records/launch-options.json'
        original_bytes = path.read_bytes()
        with patch('launch_receipts.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.store.finalize(intent['nonce'], self.managed)
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertEqual(list(path.parent.glob('*.tmp-*')), [])
        self.assertEqual(self.store.finalize(intent['nonce'], self.managed)['before'], self.original)

    def test_symlink_and_hardlink_receipts_refused(self):
        self.prepare()
        path = self.root / 'records/launch-options.json'
        external = Path(self.temp.name) / 'external.json'
        path.rename(external)
        try:
            path.symlink_to(external)
        except OSError:
            self.skipTest('Host cannot create symlinks')
        with self.assertRaises(ValueError):
            self.store.owned()
        path.unlink()
        os.link(external, path)
        with self.assertRaises(ValueError):
            self.store.owned()

    def test_maximum_unicode_roundtrip(self):
        before, after = '\U0001f680' * 16383, '\U0001f680' * 16384
        intent = self.store.prepare(before, after)
        self.assertEqual(self.store.finalize(intent['nonce'], after)['before'], before)

    def test_receipt_open_is_nonblocking_before_regular_file_check(self):
        self.prepare()
        real_open = os.open
        calls = []
        def tracked_open(path, flags, *args, **kwargs):
            if str(path).endswith('launch-options.json'):
                calls.append(flags)
            return real_open(path, flags, *args, **kwargs)
        # Supply POSIX's flag on Windows too, so this regression stays executable.
        with patch.object(os, 'O_NONBLOCK', getattr(os, 'O_NONBLOCK', 0x800), create=True):
            expected = os.O_NONBLOCK
            with patch('launch_receipts.os.open', side_effect=tracked_open), patch('launch_receipts.stat.S_ISREG', return_value=False):
                with self.assertRaisesRegex(ValueError, 'Invalid launch ownership receipt file'):
                    self.store._read()
            self.assertTrue(calls)
            self.assertTrue(all(flags & expected for flags in calls))

    def test_hardlinked_receipt_refused_without_mutating_external_file(self):
        self.prepare()
        path = self.root / 'records/launch-options.json'
        external = Path(self.temp.name) / 'external.json'
        os.link(path, external)
        payload = external.read_bytes()
        with self.assertRaises(ValueError):
            self.store.prepare(self.original, self.managed)
        self.assertEqual(external.read_bytes(), payload)

class LaunchApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncio
        import importlib.util
        from types import SimpleNamespace
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.companion = Path(self.temp.name) / 'companion'
        spec = importlib.util.spec_from_file_location('launch_test_plugin', Path(__file__).resolve().parents[1] / 'main.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'decky': SimpleNamespace()}):
            spec.loader.exec_module(module)
        self.plugin = module.Plugin()
        self.plugin.lock = asyncio.Lock()
        self.plugin.manager = SimpleNamespace(get_game=lambda gid: {'id': gid,'folder':self.temp.name}, companion=lambda game: self.companion,record=lambda game:{'enabled':True}, guard_newer_runtime=lambda game:None)

    async def test_restore_refuses_enabled_game(self):
        with patch.dict(self.plugin.prepare_launch_options.__func__.__globals__,{'active_processes':lambda *args:[]}):
            with self.assertRaisesRegex(ValueError,'stock upscaler'):
                await self.plugin.prepare_launch_options('1', 'new', '',True)
        self.assertFalse(self.companion.exists())

    async def test_rpc_lock_serializes_prepare_and_reconcile(self):
        import asyncio
        async with self.plugin.lock:
            task = asyncio.create_task(self.plugin.prepare_launch_options('1', '', 'new'))
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertFalse(self.companion.exists())
        intent = await task
        self.assertEqual((await self.plugin.owned_launch_options('1', ''))['pending'], intent)
        self.assertEqual(await self.plugin.finalize_launch_options('1', intent['nonce'], 'new'), {'before': '', 'after': 'new'})

    async def test_addon_capture_requires_closed_enabled_finalized_owned_options(self):
        from unittest.mock import Mock
        capture=Mock(return_value={'remembered':True})
        self.plugin.manager.remember_launch_addon=capture
        store=LaunchReceipts(self.companion)
        intent=store.prepare('stock','owned')
        globals_=self.plugin.remember_launch_addon.__func__.__globals__
        with patch.dict(globals_,{'active_processes':lambda *args:[]}):
            with self.assertRaisesRegex(ValueError,'finalized'):
                await self.plugin.remember_launch_addon('1','stock')
            capture.assert_not_called()
            store.finalize(intent['nonce'],'owned')
            self.assertEqual(await self.plugin.remember_launch_addon('1','owned'),{'remembered':True})
            capture.assert_called_once_with('1','owned')
            capture.reset_mock()
            with self.assertRaises(ValueError):await self.plugin.remember_launch_addon('1','edited')
            capture.assert_not_called()
        with patch.dict(globals_,{'active_processes':lambda *args:['running']}):
            with self.assertRaisesRegex(ValueError,'Close the game'):await self.plugin.remember_launch_addon('1','owned')
        self.plugin.manager.record=lambda game:{'enabled':False}
        with patch.dict(globals_,{'active_processes':lambda *args:[]}):
            with self.assertRaisesRegex(ValueError,'enabled'):await self.plugin.remember_launch_addon('1','owned')
        capture.assert_not_called()

    async def test_no_owned_receipt_does_not_block_stock_toggle_or_capture_unowned_options(self):
        from unittest.mock import Mock
        self.plugin.manager.remember_launch_addon=Mock()
        with patch.dict(self.plugin.remember_launch_addon.__func__.__globals__,{'active_processes':lambda *args:[]}):
            self.assertEqual(await self.plugin.remember_launch_addon('1','unowned'),{'remembered':False})
        self.plugin.manager.remember_launch_addon.assert_not_called()

    async def test_newer_runtime_guard_blocks_launch_changes_and_addon_capture(self):
        from unittest.mock import Mock
        store = LaunchReceipts(self.companion)
        intent = store.prepare('stock', 'owned')
        store.finalize(intent['nonce'], 'owned')
        path = self.companion / 'records' / 'launch-options.json'
        before = path.read_bytes()
        guard = Mock(side_effect=ValueError('Newer HelixSR runtime'))
        capture = Mock()
        self.plugin.manager.guard_newer_runtime = guard
        self.plugin.manager.remember_launch_addon = capture
        with patch.dict(self.plugin.prepare_launch_options.__func__.__globals__, {'active_processes': lambda *args: []}):
            with self.assertRaisesRegex(ValueError, 'Newer HelixSR'):
                await self.plugin.prepare_launch_options('1', 'owned', 'changed')
            with self.assertRaisesRegex(ValueError, 'Newer HelixSR'):
                await self.plugin.remember_launch_addon('1', 'owned')
        self.assertEqual(guard.call_count, 2)
        capture.assert_not_called()
        self.assertEqual(path.read_bytes(), before)

    async def test_execute_refuses_missing_combined_wrapper_before_game_file_changes(self):
        from unittest.mock import Mock
        env={'PROTON_USE_ARM64':'1','VKD3D_SHADER_OVERRIDE':'Z:/game/shader-override'}
        helper='/games/PRAGMATA Mod Files/Combined-Helix-LSFG-20261012/pragmata-combined-launch.py'
        addon={'helper':helper,'sha256':'pinned','environment':{'ENABLE_GAMESCOPE_WSI':'0'}}
        self.plugin.manager.previews={'token':{'game':'1','action':'enable','launch_addon':addon}}
        self.plugin.manager.launch_environment=lambda game:env
        self.plugin.manager.execute=Mock(return_value={'message':'enabled'})
        outer='PROTON_USE_ARM64=1 VKD3D_SHADER_OVERRIDE=Z:/game/shader-override '
        inner='/usr/libexec/armada/armada-game-launch /usr/bin/env PROTON_USE_ARM64=1 VKD3D_SHADER_OVERRIDE=Z:/game/shader-override %command%'
        for actual in [outer+inner,'ENABLE_GAMESCOPE_WSI=0 '+outer+inner,
                       outer+f"/usr/bin/python3 '{helper}' "+inner]:
            with self.assertRaisesRegex(ValueError,'Steam launch settings'):
                await self.plugin.armada_execute('token',actual)
        self.plugin.manager.execute.assert_not_called()
        actual='ENABLE_GAMESCOPE_WSI=0 '+outer+f"/usr/bin/python3 '{helper}' "+inner
        self.assertEqual(await self.plugin.armada_execute('token',actual),{'message':'enabled'})
        self.plugin.manager.execute.assert_called_once_with('token',launch_environment_verified=True)


if __name__ == '__main__':
    unittest.main()
