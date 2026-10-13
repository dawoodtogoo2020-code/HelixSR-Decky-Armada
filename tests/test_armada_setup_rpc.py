"""Offline RPC forwarding and mutation exclusion for Armada model setup."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
spec = importlib.util.spec_from_file_location('armada_setup_rpc_fixture', ROOT / 'armada_main.py')
backend = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'decky': SimpleNamespace(logger=MagicMock())}):
    spec.loader.exec_module(backend)


class ArmadaSetupRPC(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin = backend.Plugin()
        self.plugin.lock = asyncio.Lock()
        self.plugin.manager = MagicMock()
        self.plugin.host = SimpleNamespace(snapshot=MagicMock(return_value={'host': 'synthetic'}),
                                           refresh=MagicMock(return_value={'host': 'refreshed'}))
        self.setup = SimpleNamespace(
            busy=MagicMock(return_value=False), plan=MagicMock(return_value={'token': 'plan-token'}),
            start=MagicMock(return_value={'job_id': 'setup-job'}),
            status=MagicMock(return_value={'state': 'running', 'job_id': 'setup-job'}),
            cancel=MagicMock(return_value={'cancelled': True}), close=MagicMock())
        self.plugin.model_setup = self.setup

    async def test_plan_forwards_selected_game_and_executable(self):
        result = await self.plugin.armada_model_plan('steam:42', 'Binaries/Game.exe')
        self.assertEqual(result, {'token': 'plan-token'})
        self.setup.plan.assert_called_once_with('steam:42', 'Binaries/Game.exe')
        self.plugin.manager.assert_not_called()

    async def test_plan_default_executable_is_none(self):
        await self.plugin.armada_model_plan('steam:42')
        self.setup.plan.assert_called_once_with('steam:42', None)

    async def test_start_requires_explicit_acceptance_by_default(self):
        result = await self.plugin.armada_model_start('plan-token')
        self.assertEqual(result, {'job_id': 'setup-job'})
        self.setup.start.assert_called_once_with('plan-token', False)
        self.assertIs(self.setup.start.call_args.args[1], False)

    async def test_start_forwards_explicit_boolean_acceptance(self):
        await self.plugin.armada_model_start('plan-token', accepted=True)
        self.setup.start.assert_called_once_with('plan-token', True)
        self.assertIs(self.setup.start.call_args.args[1], True)

    async def test_start_does_not_coerce_untrusted_acceptance_values(self):
        # The setup service owns strict acceptance validation. RPC forwarding
        # must not turn a caller's string or number into boolean consent.
        for accepted in ('false', 'true', 1, None):
            with self.subTest(accepted=accepted):
                self.setup.start.reset_mock()
                await self.plugin.armada_model_start('plan-token', accepted=accepted)
                self.assertIs(self.setup.start.call_args.args[1], accepted)

    async def test_status_and_cancel_forward_exact_job_identity(self):
        self.assertEqual(await self.plugin.armada_model_status(), {'state': 'running', 'job_id': 'setup-job'})
        self.setup.status.assert_called_once_with()
        self.assertEqual(await self.plugin.armada_model_cancel('setup-job'), {'cancelled': True})
        self.setup.cancel.assert_called_once_with('setup-job')

    async def test_running_setup_rejects_every_installation_mutation_before_side_effects(self):
        self.setup.busy.return_value = True
        calls = [
            ('armada_register_source', ('untrusted-source',)),
            ('armada_prepare', ('steam:42', 'Game.exe')),
            ('armada_preview', ('steam:42', 'install', True, 'Game.exe')),
            ('armada_execute', ('preview-token', 'options')),
            ('prepare_launch_options', ('steam:42', 'before', 'after', False)),
            ('remember_launch_addon', ('steam:42', 'options')),
        ]
        with patch.object(backend, 'Path', side_effect=AssertionError('filesystem reached')) as paths, \
             patch.object(backend, 'active_processes', side_effect=AssertionError('process probe reached')) as processes, \
             patch.object(backend, 'LaunchReceipts', side_effect=AssertionError('launch files reached')) as receipts:
            for name, args in calls:
                with self.subTest(route=name):
                    with self.assertRaisesRegex(ValueError, 'Model setup is running'):
                        await getattr(self.plugin, name)(*args)
                    self.assertFalse(self.plugin.lock.locked(), 'failed RPC must release the shared lock')
            paths.assert_not_called()
            processes.assert_not_called()
            receipts.assert_not_called()
        self.assertEqual(self.plugin.manager.mock_calls, [])
        self.assertEqual(self.setup.busy.call_count, len(calls))

    async def test_read_only_status_routes_remain_available_during_setup(self):
        self.setup.busy.return_value = True
        self.plugin.manager.status.return_value = {'installed': False}
        self.plugin.manager.source_status.return_value = {'ready': False}
        self.assertEqual(await self.plugin.armada_status('steam:42'), {'installed': False})
        self.assertEqual(await self.plugin.armada_source_status(), {'ready': False})
        self.assertEqual(await self.plugin.armada_capabilities(), {'host': 'synthetic'})
        self.assertEqual(await self.plugin.armada_model_status(), {'state': 'running', 'job_id': 'setup-job'})
        self.plugin.manager.status.assert_called_once_with('steam:42')
        self.plugin.manager.source_status.assert_called_once_with()
        self.plugin.host.snapshot.assert_called_once_with()
        self.setup.busy.assert_not_called()

    async def test_capability_refresh_is_blocked_during_setup(self):
        self.setup.busy.return_value = True
        with self.assertRaisesRegex(ValueError, 'Model setup is running'):
            await self.plugin.armada_capabilities(refresh=True)
        self.plugin.host.refresh.assert_not_called()
        self.plugin.host.snapshot.assert_not_called()

    async def test_idle_prepare_and_preview_forward_exact_options(self):
        self.plugin.manager.prepare_private.return_value = {'ready': True}
        self.plugin.manager.preview.return_value = {'token': 'preview-token'}
        self.assertEqual(await self.plugin.armada_prepare('steam:42', 'Game.exe'), {'ready': True})
        self.plugin.manager.prepare_private.assert_called_once_with('steam:42', 'Game.exe')
        self.assertEqual(await self.plugin.armada_preview('steam:42', 'install', True, 'Game.exe'),
                         {'token': 'preview-token'})
        self.plugin.manager.preview.assert_called_once_with('steam:42', 'install', True, 'Game.exe')

    async def test_plan_error_is_propagated_and_releases_shared_lock(self):
        self.setup.plan.side_effect = ValueError('synthetic plan failure')
        with self.assertRaisesRegex(ValueError, 'synthetic plan failure'):
            await self.plugin.armada_model_plan('steam:42')
        self.assertFalse(self.plugin.lock.locked())
        self.assertEqual(await self.plugin.armada_model_cancel('setup-job'), {'cancelled': True})

    async def test_status_worker_does_not_block_event_loop(self):
        started, release = threading.Event(), threading.Event()
        def blocking_status():
            started.set()
            if not release.wait(3):
                raise AssertionError('event loop failed to release background status worker')
            return {'state': 'running'}
        self.setup.status.side_effect = blocking_status
        pending = asyncio.create_task(self.plugin.armada_model_status())
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            await asyncio.sleep(0)
            self.assertFalse(pending.done())
        finally:
            release.set()
        self.assertEqual(await pending, {'state': 'running'})

    async def test_unload_closes_setup_worker(self):
        await self.plugin._unload()
        self.setup.close.assert_called_once_with()
        self.assertEqual(self.plugin.manager.mock_calls, [])

    async def test_unload_before_main_initialization_is_safe(self):
        await backend.Plugin()._unload()


if __name__ == '__main__':
    unittest.main()
