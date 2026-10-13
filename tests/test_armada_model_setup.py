"""Offline setup lifecycle tests using synthetic files in explicit D: fixtures.

No provider/model/shader assets, downloads, GPU execution or device access.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
import armada_model_setup as setup


class FixtureManager:
    def __init__(self, root):
        self.home = root / 'home'
        self.home.mkdir()
        self.root = root / 'companion'
        self.source_config = root / 'settings/source.json'
        self.game = {'id': 'fixture-game', 'folder': str(root / 'game')}
        self.eligible = True
        self.registered = []
        self.registration_error = None

    def get_game(self, gid):
        if gid != self.game['id']:
            raise ValueError('Unknown fixture game')
        return self.game

    def assess_safe(self, game, executable=None):
        return {'compatibility': 'candidate' if self.eligible else 'blocked',
                'dx12_detected': self.eligible, 'reasons': ['Fixture no longer eligible']}

    def companion(self, game):
        return self.root

    def source_status(self):
        if not self.source_config.is_file():
            return {'ready': False}
        value = json.loads(self.source_config.read_text())
        source = value.get('source')
        return {'ready': bool(source and Path(source).is_dir()), 'source': source}

    def register_source(self, source, files):
        self.registered.append((source, files))
        setup.atomic_json(self.source_config, {'source': source, 'files': files})
        if self.registration_error:
            raise self.registration_error
        return self.source_status()


class FixtureThread:
    """Immediate deterministic shutdown fixture; never starts or sleeps."""
    def __init__(self, on_join=None):
        self.alive = True
        self.join_timeouts = []
        self.on_join = on_join

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.join_timeouts.append(timeout)
        if self.on_join:
            self.on_join(self)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        # Never use the system temporary directory, which can reside on C:.
        self.temp = tempfile.TemporaryDirectory(prefix='armada-job-test-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.settings = self.base / 'settings'
        self.settings.mkdir()
        self.plugin = self.base / 'plugin'
        (self.plugin / 'bin').mkdir(parents=True)
        helper = b'synthetic helper fixture, not a PE executable'
        (self.plugin / 'bin/armada_model_probe.exe').write_bytes(helper)
        (self.plugin / 'model_setup').mkdir()
        assets = {name: {'url': setup.ASSET_URLS[name], 'size': setup.ASSET_SIZES[name],
                         'sha256': digest} for name, digest in setup.ASSET_PINS.items()}
        (self.plugin / 'model_setup/assets.json').write_text(json.dumps(assets))
        self.manager = FixtureManager(self.base)
        self.host = SimpleNamespace(snapshot=lambda: {})
        self.subject = setup.ArmadaModelSetup(self.manager, self.host, self.plugin, self.settings)
        self.runtime = self.base / 'runtime'
        self.runtime.mkdir()
        self.patch(setup, 'PROBE_SHA', hashlib.sha256(helper).hexdigest())
        # Replace hardware-facing checks only; keep game assessments, disk checks,
        # consent, nonce handling, persistence, activation and cleanup real.
        proxy_os = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
        proxy_os.name = 'posix'
        proxy_os.geteuid = lambda: 1000
        self.patch(setup, 'os', proxy_os)
        self.patch(setup, '_host_eligible', Mock(return_value=True))
        self.patch(setup, 'windows_path', lambda path: 'Z:' + str(path))
        self.patch(self.subject, '_runtime', Mock(return_value=(self.manager.home, self.runtime)))
        # All tests fail immediately if they accidentally cross execution/network boundaries.
        self.fetch = self.patch(setup, 'fetch_asset', Mock(side_effect=AssertionError('Network prohibited')))
        self.patch(setup.subprocess, 'Popen', Mock(side_effect=AssertionError('Native tools prohibited')))
        self.patch(setup.subprocess, 'run', Mock(side_effect=AssertionError('Native tools prohibited')))
        self.built_work = []
        self.patch(self.subject, '_build', Mock(side_effect=self.synthetic_build))
        self.addCleanup(self.stop_worker)

    def patch(self, target, name, value):
        context = patch.object(target, name, value)
        result = context.start()
        self.addCleanup(context.stop)
        return result

    def stop_worker(self):
        self.subject._cancel.set()
        thread = self.subject._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), 'Owned fixture worker did not stop')

    def synthetic_build(self, game, work, logfile):
        self.built_work.append(work)
        source = work / 'verified-source'
        source.mkdir()
        data = b'ordinary synthetic lifecycle fixture'
        (source / 'fixture.txt').write_bytes(data)
        return source, {'fixture.txt': hashlib.sha256(data).hexdigest()}, {'fixture': True}

    def seed_prior(self):
        prior = self.base / 'prior-source'
        prior.mkdir()
        (prior / 'keep.txt').write_bytes(b'unique prior source fixture')
        # Deliberately unusual whitespace: rollback must preserve exact bytes.
        raw = ('{ "source" : ' + json.dumps(str(prior)) + ', "files" : {} }\n\n').encode()
        self.manager.source_config.write_bytes(raw)
        return raw, prior

    def start_and_wait(self):
        plan = self.subject.plan(self.manager.game['id'])
        self.assertTrue(plan['can_start'], plan)
        self.subject.start(plan['token'], accepted=True)
        self.subject._thread.join(timeout=5)
        self.assertFalse(self.subject._thread.is_alive(), 'Fixture setup did not finish')
        return self.subject.status()

    def assert_owned_staging_removed(self):
        self.assertTrue(self.built_work)
        self.assertTrue(all(not path.exists() for path in self.built_work))

    def test_rejected_terms_never_spawn_worker_or_acquire(self):
        plan = self.subject.plan(self.manager.game['id'])
        with patch.object(setup.threading, 'Thread') as worker:
            for accepted in (False, 1, 'yes', None):
                # Each rejected token is consumed; a fresh review is required.
                if accepted is not False:
                    plan = self.subject.plan(self.manager.game['id'])
                with self.assertRaisesRegex(ValueError, 'explicitly agree'):
                    self.subject.start(plan['token'], accepted=accepted)
            worker.assert_not_called()
        self.fetch.assert_not_called()
        self.subject._build.assert_not_called()
        self.assertEqual(self.subject.status()['state'], 'idle')
        self.assertFalse((self.settings / 'armada-model-terms.json').exists())

    def test_expired_nonce_never_spawns_worker(self):
        plan = self.subject.plan(self.manager.game['id'])
        self.subject._plans[plan['token']]['expires'] = 0
        with patch.object(setup.threading, 'Thread') as worker:
            with self.assertRaisesRegex(ValueError, 'expired'):
                self.subject.start(plan['token'], accepted=True)
            worker.assert_not_called()
        self.fetch.assert_not_called()

    def test_start_rechecks_game_eligibility_after_review(self):
        plan = self.subject.plan(self.manager.game['id'])
        self.manager.eligible = False
        with patch.object(setup.threading, 'Thread') as worker:
            with self.assertRaisesRegex(ValueError, 'no longer eligible'):
                self.subject.start(plan['token'], accepted=True)
            worker.assert_not_called()
        self.fetch.assert_not_called()

    def test_start_rechecks_helper_bytes_after_review(self):
        plan = self.subject.plan(self.manager.game['id'])
        (self.plugin / 'bin/armada_model_probe.exe').write_bytes(b'changed fixture helper')
        with patch.object(setup.threading, 'Thread') as worker:
            with self.assertRaisesRegex(ValueError, 'helper is missing or changed'):
                self.subject.start(plan['token'], accepted=True)
            worker.assert_not_called()

    def test_success_registers_existing_payload_and_persists_completed(self):
        raw, prior = self.seed_prior()
        status = self.start_and_wait()
        self.assertEqual(status['state'], 'completed')
        self.assertFalse(status['result']['game_files_changed'])
        self.assertFalse(status['result']['gameplay_tested'])
        self.assertTrue(Path(status['result']['source']).is_dir())
        self.assertEqual((prior / 'keep.txt').read_bytes(), b'unique prior source fixture')
        persisted = json.loads(self.subject.record_path.read_text())
        self.assertEqual(persisted['state'], 'completed')
        self.assertEqual(persisted['result'], status['result'])
        self.assert_owned_staging_removed()
        self.fetch.assert_not_called()

    def test_register_failure_after_mutation_restores_exact_prior_bytes(self):
        raw, prior = self.seed_prior()
        self.manager.registration_error = OSError('fixture registration failure after mutation')
        status = self.start_and_wait()
        self.assertEqual(status['state'], 'failed')
        self.assertEqual(self.manager.source_config.read_bytes(), raw)
        self.assertTrue((prior / 'keep.txt').is_file())
        self.assertEqual(list((self.manager.root / 'packages').iterdir()), [])
        self.assert_owned_staging_removed()

    def test_completion_persistence_failure_rolls_back_registration(self):
        raw, prior = self.seed_prior()
        real_save = self.subject._save

        def fail_completed_only():
            if self.subject.job['state'] == 'completed':
                raise OSError('fixture status persistence failure')
            return real_save()

        self.subject._save = Mock(side_effect=fail_completed_only)
        status = self.start_and_wait()
        self.assertEqual(status['state'], 'failed')
        self.assertEqual(len(self.manager.registered), 1)
        self.assertEqual(self.manager.source_config.read_bytes(), raw)
        self.assertTrue(prior.is_dir())
        self.assertEqual(list((self.manager.root / 'packages').iterdir()), [])
        self.assertEqual(json.loads(self.subject.record_path.read_text())['state'], 'failed')

    def test_changed_source_during_build_is_preserved(self):
        self.seed_prior()
        changed = b'{"source":"a separately selected fixture source","files":{}}\n'

        def change_during_build(game, work, logfile):
            result = self.synthetic_build(game, work, logfile)
            self.manager.source_config.write_bytes(changed)
            return result

        self.subject._build.side_effect = change_during_build
        status = self.start_and_wait()
        self.assertEqual(status['state'], 'failed')
        self.assertIn('source changed during setup', status['message'])
        self.assertEqual(self.manager.source_config.read_bytes(), changed)
        self.assertEqual(self.manager.registered, [])
        self.assert_owned_staging_removed()

    def test_public_cancel_before_activation_preserves_source(self):
        raw, prior = self.seed_prior()
        entered, released = threading.Event(), threading.Event()

        def pause_build(game, work, logfile):
            result = self.synthetic_build(game, work, logfile)
            entered.set()
            if not released.wait(5):
                raise RuntimeError('Fixture test did not release build')
            return result

        self.subject._build.side_effect = pause_build
        plan = self.subject.plan(self.manager.game['id'])
        state = self.subject.start(plan['token'], accepted=True)
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.subject.cancel(state['id'])['state'], 'running')
        finally:
            released.set()
        self.subject._thread.join(timeout=5)
        self.assertFalse(self.subject._thread.is_alive())
        self.assertEqual(self.subject.status()['state'], 'cancelled')
        self.assertEqual(self.manager.source_config.read_bytes(), raw)
        self.assertEqual(self.manager.registered, [])
        self.assertTrue(prior.is_dir())
        self.assert_owned_staging_removed()

    def test_cleanup_removes_only_owned_staging(self):
        unrelated = self.manager.root / 'staging/another-active-task'
        unrelated.mkdir(parents=True)
        (unrelated / 'keep.txt').write_bytes(b'active work fixture')
        installed = self.manager.root / 'dependencies/existing-installed-dependency'
        installed.mkdir(parents=True)
        (installed / 'keep.txt').write_bytes(b'installed fixture')
        self.start_and_wait()
        self.assert_owned_staging_removed()
        self.assertEqual((unrelated / 'keep.txt').read_bytes(), b'active work fixture')
        self.assertEqual((installed / 'keep.txt').read_bytes(), b'installed fixture')

    def test_dependency_reuse_checks_hash_and_never_downloads(self):
        name = 'numpy'
        key = name + '-' + setup.ASSET_PINS[name][:12]
        destination = self.manager.root / 'dependencies' / key
        destination.mkdir(parents=True)
        payload = destination / 'ordinary-fixture.txt'
        payload.write_bytes(b'synthetic installed dependency')
        receipt = self.manager.root / 'records' / ('dependency-' + key + '.json')
        setup.atomic_json(receipt, {'asset_sha256': setup.ASSET_PINS[name],
                                   'files': {payload.name: setup.sha(payload)}})
        self.assertEqual(self.subject._dependency(name, self.manager.root), destination)
        payload.write_bytes(b'changed dependency fixture')
        with self.assertRaisesRegex(ValueError, 'hash check'):
            self.subject._dependency(name, self.manager.root)
        self.fetch.assert_not_called()
        self.assertTrue(payload.is_file(), 'Changed installed dependency must be retained for review')

    def test_dependency_reuse_rejects_unlisted_files(self):
        name = 'dxc'
        key = name + '-' + setup.ASSET_PINS[name][:12]
        destination = self.manager.root / 'dependencies' / key
        destination.mkdir(parents=True)
        payload = destination / 'fixture.txt'
        payload.write_bytes(b'fixture')
        setup.atomic_json(self.manager.root / 'records' / ('dependency-' + key + '.json'),
                          {'asset_sha256': setup.ASSET_PINS[name], 'files': {payload.name: setup.sha(payload)}})
        (destination / 'unexpected.txt').write_bytes(b'changed inventory')
        with self.assertRaisesRegex(ValueError, 'extra files'):
            self.subject._dependency(name, self.manager.root)
        self.fetch.assert_not_called()

    def test_build_acquisition_skips_all_verified_installed_dependencies(self):
        for name in ('python', 'numpy', 'dxc'):
            key = name + '-' + setup.ASSET_PINS[name][:12]
            destination = self.manager.root / 'dependencies' / key
            destination.mkdir(parents=True)
            payload = destination / 'ordinary-fixture.txt'
            payload.write_bytes(('synthetic ' + name + ' installed fixture').encode())
            setup.atomic_json(self.manager.root / 'records' / ('dependency-' + key + '.json'),
                              {'asset_sha256': setup.ASSET_PINS[name],
                               'files': {payload.name: setup.sha(payload)}})
        work = self.base / 'owned-acquisition-work'
        work.mkdir()

        def fake_download(spec, path, cancel):
            path.write_bytes(b'ordinary acquisition fixture, not an archive')

        self.fetch.side_effect = fake_download
        # Stop before recipe execution; the real acquisition loop and cache checks ran.
        with patch.object(setup, 'extract_zip', side_effect=ValueError('Fixture stop before conversion')):
            with self.assertRaisesRegex(ValueError, 'Fixture stop before conversion'):
                setup.ArmadaModelSetup._build(self.subject, self.manager.game, work, self.base / 'unused.log')
        self.assertEqual([call.args[1].name for call in self.fetch.call_args_list],
                         ['upstream.download', 'dlss.download'])

    def test_plan_reports_helper_path_blocker_before_worker_or_acquisition(self):
        with patch.object(setup, 'windows_path', side_effect=ValueError('Fixture helper path is too long')):
            plan = self.subject.plan(self.manager.game['id'])
        self.assertFalse(plan['can_start'])
        self.assertIn('path is too long', plan['blockers'][0])
        self.assertEqual(self.subject._plans, {})
        self.subject._build.assert_not_called()
        self.fetch.assert_not_called()

    def test_status_is_copy_and_rechecks_completed_source(self):
        self.start_and_wait()
        status = self.subject.status()
        status['result']['ready'] = False
        self.assertTrue(self.subject.status()['result']['ready'])
        self.manager.source_config.unlink()
        current = self.subject.status()
        self.assertEqual(current['state'], 'interrupted')
        self.assertIsNone(current['result'])

    def test_restart_marks_running_record_interrupted(self):
        setup.atomic_json(self.subject.record_path,
                          {'state': 'running', 'id': 'a' * 32, 'gid': self.manager.game['id'],
                           'result': {'ready': True}, 'phase': 'build'})
        recovered = setup.ArmadaModelSetup(self.manager, self.host, self.plugin, self.settings)
        self.assertEqual(recovered.status()['state'], 'interrupted')
        self.assertIsNone(recovered.status()['result'])
        self.assertEqual(json.loads(recovered.record_path.read_text())['state'], 'interrupted')

    def test_terminal_worker_still_alive_rejects_new_plan_and_start(self):
        for terminal in ('completed', 'failed', 'cancelled'):
            with self.subTest(state=terminal):
                plan = self.subject.plan(self.manager.game['id'])
                self.assertTrue(plan['can_start'])
                prior = {'state': terminal, 'id': 'b' * 32, 'gid': self.manager.game['id']}
                self.subject.job = prior.copy()
                thread = FixtureThread()
                with patch.object(self.subject, '_thread', thread):
                    self.assertTrue(self.subject.busy())
                    rejected = self.subject.plan(self.manager.game['id'])
                    self.assertFalse(rejected['can_start'])
                    self.assertIn('already running', rejected['blockers'][0])
                    with self.assertRaisesRegex(ValueError, 'another setup is running'):
                        self.subject.start(plan['token'], accepted=True)
                    self.assertEqual(self.subject.job, prior)
                self.subject._build.assert_not_called()
                self.fetch.assert_not_called()
                self.assertEqual(self.manager.registered, [])

    def test_rpc_mutation_gate_uses_live_terminal_worker_busy_state(self):
        # Import the actual RPC surface with only Decky's logging integration stubbed.
        spec = importlib.util.spec_from_file_location('armada_lifecycle_rpc_fixture', ROOT / 'armada_main.py')
        backend = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'decky': SimpleNamespace(logger=Mock())}):
            spec.loader.exec_module(backend)
        plugin = backend.Plugin()
        plugin.model_setup = self.subject
        self.subject.job = {'state': 'failed', 'id': 'c' * 32, 'gid': self.manager.game['id']}
        with patch.object(self.subject, '_thread', FixtureThread()):
            self.assertTrue(self.subject.busy())
            with self.assertRaisesRegex(ValueError, 'Model setup is running'):
                plugin._setup_idle()
        plugin._setup_idle()  # Release only after the worker has stopped.

    def test_status_exposes_cleanup_until_terminal_worker_stops(self):
        terminal = {'state': 'completed', 'id': 'd' * 32, 'gid': self.manager.game['id'],
                    'phase': 'completed', 'message': 'Fixture completed'}
        self.subject.job = terminal.copy()
        thread = FixtureThread()
        with patch.object(self.subject, '_thread', thread):
            status = self.subject.status()
            self.assertEqual(status['state'], 'running')
            self.assertEqual(status['phase'], 'cleanup')
            self.assertIn('cleanup', status['message'])
            self.assertEqual(self.subject.job, terminal, 'Public projection must not mutate persisted job state')
            self.assertTrue(self.subject.busy())
            thread.alive = False
            self.assertFalse(self.subject.busy())
            # Missing prepared source is detected once cleanup has really finished.
            self.assertEqual(self.subject.status()['state'], 'interrupted')

    def test_close_raises_if_bounded_join_leaves_worker_alive(self):
        self.subject.job = {'state': 'completed', 'id': 'e' * 32, 'gid': self.manager.game['id']}
        thread = FixtureThread()
        with patch.object(self.subject, '_thread', thread):
            with self.assertRaisesRegex(RuntimeError, 'cleanup is still active'):
                self.subject.close()
            self.assertTrue(self.subject._cancel.is_set())
            self.assertEqual(thread.join_timeouts, [60])
            self.assertTrue(self.subject.busy())
            self.assertEqual(self.subject.status()['state'], 'running')
            self.assertEqual(self.subject.status()['phase'], 'cleanup')

    def test_close_sets_cancellation_before_cooperative_join(self):
        self.subject.job = {'state': 'cancelled', 'id': 'f' * 32, 'gid': self.manager.game['id']}

        def finish_on_join(thread):
            self.assertTrue(self.subject._cancel.is_set(), 'Cancellation must precede worker join')
            thread.alive = False

        thread = FixtureThread(on_join=finish_on_join)
        with patch.object(self.subject, '_thread', thread):
            self.subject.close()
            self.assertEqual(thread.join_timeouts, [60])
            self.assertFalse(self.subject.busy())
            self.assertEqual(self.subject.status()['state'], 'cancelled')


class WindowsPathTests(unittest.TestCase):
    def test_valid_posix_path_becomes_bounded_windows_path(self):
        self.assertEqual(setup.windows_path(PurePosixPath('/home/user/Steam Library/probe.exe')),
                         'Z:/home/user/Steam Library/probe.exe')

    def test_invalid_windows_helper_paths_fail_before_execution(self):
        cases = ('relative/probe.exe', '/home/CON/file', '/home/com1.txt/file',
                 '/home/trailing./file', '/home/trailing /file', '/home/colon:name/file',
                 '/home/question?/file', '/home/quote"/file', '/home/' + 'x' * 240,
                 '/home/' + '\U0001f600' * 120)
        for path in cases:
            with self.subTest(path=path), self.assertRaises(ValueError):
                setup.windows_path(PurePosixPath(path))


if __name__ == '__main__':
    unittest.main()
