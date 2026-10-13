"""Offline progressive capture integration using only synthetic D: fixtures.

No downloads, provider calls, native processes, device access or model assets.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
import armada_model_setup as setup


class CaptureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='armada-capture-test-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.work = self.base / 'work'
        self.source = self.work / 'source'
        self.source.mkdir(parents=True)
        self.settings = self.base / 'settings'
        self.settings.mkdir()
        self.plugin = self.base / 'plugin'
        self.plugin.mkdir()
        self.steam = self.base / 'steam'
        self.runtime = self.steam / 'runtime'
        self.logfile = self.base / 'capture.log'
        self.shader_ids = tuple(f'{number:016x}' for number in range(1, 5))
        self.raw = {name: ('synthetic-original-' + name).encode() for name in self.shader_ids}
        self.output = {name: ('synthetic-transformed-' + name).encode() for name in self.shader_ids}
        pins = {'shader-override/' + name + '.spv': hashlib.sha256(data).hexdigest()
                for name, data in self.output.items()}
        self.manager = SimpleNamespace(refresh=Mock(return_value={
            'games': [{'folder': str(self.base / 'game'), 'appid': 'fixture'}]}))
        self.subject = setup.ArmadaModelSetup(
            self.manager, SimpleNamespace(snapshot={}), self.plugin, self.settings)
        self.subject._cancel = threading.Event()
        self.calls = []
        self.pending_prefixes = []
        self.closed_prefixes = []
        self.report_mode = 'normal'
        self.numeric = {'rgb_validation_passed': True, 'rgb_frames_checked': 2, 'exposure': 'unit'}
        self.process_error = None
        self.cancel_after_process = False
        self.cleanup_failure = False
        self.patch(setup, 'PINNED', pins)
        self.patch(setup, '_host_eligible', Mock(return_value=True))
        self.active = self.patch(setup, 'active_processes', Mock(return_value=[]))
        self.environment = self.patch(self.subject, '_environment', Mock(side_effect=self.fake_environment))
        self.process = self.patch(self.subject, '_process', Mock(side_effect=self.fake_process))
        self.close = self.patch(self.subject, '_close_prefixes', Mock(side_effect=self.fake_close))
        self.transform = self.patch(setup, 'transform_dumps', Mock(side_effect=self.fake_transform))
        self.patch(setup, 'fetch_asset', Mock(side_effect=AssertionError('Network prohibited')))
        self.patch(setup.subprocess, 'Popen', Mock(side_effect=AssertionError('Native process prohibited')))
        self.patch(setup.subprocess, 'run', Mock(side_effect=AssertionError('Native process prohibited')))

    def patch(self, target, name, replacement):
        context = patch.object(target, name, replacement)
        result = context.start()
        self.addCleanup(context.stop)
        return result

    def fake_environment(self, steam, runtime, prefix):
        self.assertEqual(steam, self.steam)
        self.assertEqual(runtime, self.runtime)
        self.assertFalse(prefix.exists(), 'Each attempt must start with a fresh prefix')
        prefix.mkdir()
        self.pending_prefixes.append(prefix)
        return {'FIXTURE_ONLY': '1'}

    def fake_close(self, work):
        self.assertEqual(work, self.work)
        if self.cleanup_failure:
            return ['Synthetic owned-prefix cleanup failure']
        self.closed_prefixes.extend(self.pending_prefixes)
        self.pending_prefixes.clear()
        return []

    def fake_process(self, command, folder, env, logfile, timeout, allowed_exit_codes):
        self.assertEqual(logfile, self.logfile)
        self.assertEqual(timeout, 180)
        self.assertEqual(tuple(allowed_exit_codes), (0, 1))
        self.assertEqual(env['VKD3D_SHADER_CACHE_PATH'], '0')
        self.assertEqual(env['VKD3D_FILTER_DEVICE_NAME'], 'Adreno')
        self.assertTrue(self.pending_prefixes, 'Process requires its owned prefix')
        self.assertEqual(self.pending_prefixes[-1], folder / 'prefix')
        report = Path(command[-1][2:])
        dumps = Path(env['VKD3D_SHADER_DUMP_PATH'][2:])
        self.assertEqual(report.parent, folder)
        self.assertEqual(dumps, folder / 'dumps')
        self.assertFalse(report.exists(), 'Reports cannot be reused across attempts')
        overrides = self.source / 'shader-override'
        accepted = {path.stem for path in overrides.glob('*.spv')}
        for name in accepted:
            self.assertEqual((overrides / (name + '.spv')).read_bytes(), self.output[name])
        self.calls.append({'folder': folder, 'report': report, 'env': dict(env), 'accepted': accepted})
        if self.process_error:
            raise self.process_error
        final = accepted == set(self.shader_ids)
        if final:
            result = {'event': 'result', 'passed': True, 'stage': 'completed', 'code': 0,
                      'dispatches_completed': 2, 'error_callbacks': 0, 'warning_callbacks': 0,
                      'destroy_ok': True, 'destroy_code': 0, 'device_healthy': True,
                      'cleanup_wait_ok': True, **self.numeric}
        else:
            name = next(name for name in self.shader_ids if name not in accepted)
            (dumps / (name + '.spv')).write_bytes(self.raw[name])
            result = {'event': 'result', 'passed': False, 'stage': 'context_create', 'code': -1,
                      'dispatches_completed': 0, 'error_callbacks': 0, 'warning_callbacks': 0,
                      'destroy_ok': True, 'destroy_code': 0, 'device_healthy': True,
                      'cleanup_wait_ok': True}
        if self.report_mode != 'missing':
            events = [{'schema': 1, 'event': 'probe', 'provider': 'HelixSR'}, result]
            if self.report_mode == 'ambiguous':
                events.append(dict(result))
            report.write_text('\n'.join(json.dumps(event) for event in events), encoding='utf-8')
        if self.cancel_after_process:
            self.subject._cancel.set()
        return 0 if final else 1

    def fake_transform(self, recipe, dumps, destination, cancelled, shader_ids):
        self.assertEqual(recipe, self.plugin / 'model_setup/v762')
        self.assertIs(cancelled, self.subject._cancel)
        self.assertFalse(destination.exists())
        destination.mkdir()
        modules = []
        for name in sorted(shader_ids):
            self.assertIn(name, self.shader_ids)
            original = (dumps / (name + '.spv')).read_bytes()
            if original != self.raw[name]:
                raise ValueError('Synthetic input pin mismatch')
            data = self.output[name]
            (destination / (name + '.spv')).write_bytes(data)
            modules.append({'name': name + '.spv', 'sha256': hashlib.sha256(data).hexdigest()})
        return {'modules': modules}

    def capture(self):
        return self.subject._capture(self.source, self.work, self.steam, self.runtime, self.logfile)

    def test_progressive_capture_uses_fresh_attempts_and_validates_all_four(self):
        result = self.capture()
        self.assertEqual(len(self.calls), 5)
        self.assertEqual([len(call['accepted']) for call in self.calls], [0, 1, 2, 3, 4])
        self.assertNotIn('VKD3D_SHADER_OVERRIDE', self.calls[0]['env'])
        for call in self.calls[1:]:
            self.assertEqual(call['env']['VKD3D_SHADER_OVERRIDE'], 'Z:' + str(self.source / 'shader-override'))
        self.assertEqual(len({call['folder'] for call in self.calls}), 5)
        self.assertEqual(len({call['report'] for call in self.calls}), 5)
        self.assertEqual(len(set(self.closed_prefixes)), 5)
        self.assertEqual(self.pending_prefixes, [])
        self.assertEqual(self.close.call_count, 5)
        self.assertEqual(self.transform.call_count, 4)
        self.assertEqual({item['name'] for item in result['modules']},
                         {name + '.spv' for name in self.shader_ids})
        self.assertTrue(result['analytic_unit_exposure_rgb_checked'])
        self.assertTrue(result['matches_previously_independently_validated_bytes'])
        self.assertFalse(result['gameplay_tested'])
        self.assertFalse(result['quality_tested'])

    def test_api_success_with_failed_red_or_black_rgb_validation_is_rejected(self):
        # The scene validator supplies the numeric verdict; orchestration must not
        # mistake two successful API dispatches for a passing scene.
        for scene in ('red', 'black'):
            with self.subTest(scene=scene):
                self.numeric['rgb_validation_passed'] = False
                with self.assertRaisesRegex(ValueError, 'RGB validation'):
                    self.capture()
                self.assertEqual(len(self.calls), 5)
                self.assertEqual(len(self.calls[-1]['accepted']), 4)
                # Reset only owned synthetic capture directories for the next case.
                if scene == 'red':
                    self.tear_down_capture_fixture()

    def tear_down_capture_fixture(self):
        import shutil
        for path in self.work.iterdir():
            if path == self.source:
                shutil.rmtree(path / 'shader-override')
            else:
                shutil.rmtree(path)
        self.calls.clear()
        self.closed_prefixes.clear()

    def test_numeric_contract_requires_integer_two_frames_and_unit_exposure(self):
        cases = ({'rgb_frames_checked': True}, {'rgb_frames_checked': 1}, {'exposure': 'zero'})
        for index, invalid in enumerate(cases):
            with self.subTest(invalid=invalid):
                self.numeric = {'rgb_validation_passed': True, 'rgb_frames_checked': 2,
                                'exposure': 'unit', **invalid}
                with self.assertRaisesRegex(ValueError, 'RGB validation'):
                    self.capture()
                self.assertEqual(len(self.calls), 5)
                if index < len(cases) - 1:
                    self.tear_down_capture_fixture()

    def test_active_game_blocks_before_any_process_or_prefix(self):
        self.active.return_value = [{'pid': 123, 'fixture': True}]
        with self.assertRaisesRegex(ValueError, 'Close running games'):
            self.capture()
        self.process.assert_not_called()
        self.environment.assert_not_called()

    def test_missing_report_rejects_even_when_new_raw_input_exists(self):
        self.report_mode = 'missing'
        with self.assertRaisesRegex(ValueError, 'bounded report'):
            self.capture()
        self.assertEqual(len(self.calls), 1)
        self.transform.assert_not_called()
        self.assertEqual(len(self.closed_prefixes), 1)

    def test_ambiguous_report_rejects_before_transformation(self):
        self.report_mode = 'ambiguous'
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous'):
            self.capture()
        self.assertEqual(len(self.calls), 1)
        self.transform.assert_not_called()
        self.assertEqual(len(self.closed_prefixes), 1)

    def test_transformation_pin_mismatch_aborts_before_next_spawn(self):
        self.transform.side_effect = ValueError('Synthetic output pin mismatch')
        with self.assertRaisesRegex(ValueError, 'pin mismatch'):
            self.capture()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(list((self.source / 'shader-override').iterdir()), [])
        self.assertEqual(len(self.closed_prefixes), 1)

    def test_timeout_propagates_after_owned_prefix_cleanup(self):
        self.process_error = RuntimeError('Synthetic model preparation timed out')
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            self.capture()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.closed_prefixes), 1)
        self.assertEqual(self.pending_prefixes, [])
        self.transform.assert_not_called()

    def test_cleanup_failure_retains_owned_work_and_forbids_next_attempt(self):
        self.cleanup_failure = True
        with self.assertRaisesRegex(RuntimeError, 'did not stop safely'):
            self.capture()
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.work.is_dir())
        self.assertTrue(self.calls[0]['folder'].is_dir())
        self.assertEqual(len(self.pending_prefixes), 1)
        self.transform.assert_not_called()

    def test_cancellation_before_capture_never_spawns(self):
        self.subject._cancel.set()
        with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
            self.capture()
        self.process.assert_not_called()
        self.environment.assert_not_called()

    def test_cancellation_after_discovery_never_spawns_next_attempt(self):
        self.cancel_after_process = True
        with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
            self.capture()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.closed_prefixes), 1)
        self.assertEqual(self.pending_prefixes, [])


if __name__ == '__main__':
    unittest.main()
