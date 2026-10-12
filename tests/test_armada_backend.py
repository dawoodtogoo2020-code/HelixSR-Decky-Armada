"""Offline private V762 safety checks. Synthetic files prove policy, not gameplay."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
import armada_manager as armada
import manager
from operation_lock import operation_lock
from test_backend import pe


class ArmadaSafety(unittest.TestCase):
    def setUp(self):
        self.work = ROOT.parent / 'armada-test-work'
        self.work.mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=self.work)
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.settings = self.base / 'settings'
        self.source = self.base / 'private-source'
        self.source.mkdir()
        files = {armada.DLL: pe(ffx=True, helix=True),
                 'helixsr_kernels.pak': b'private pack',
                 'helixsr_weights.bin': b'private weights',
                 'helixsr.ini': b'[HelixSR]\n'}
        files.update({'shader-override/' + name: b'\x03\x02\x23\x07' + name.encode()
                      for name in armada.OVERRIDES})
        for name, data in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.hashes = {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
        p = patch.dict(armada.PINNED, self.hashes, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.manager = armada.ArmadaManager(self.home, self.settings)

    def test_registered_source_rejects_unlisted_and_changed_bytes(self):
        status = self.manager.register_source(str(self.source), self.hashes)
        self.assertTrue(status['ready'])
        (self.source / 'unknown.bin').write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError, 'unlisted'):
            self.manager.register_source(str(self.source), self.hashes)
        (self.source / 'unknown.bin').unlink()
        (self.source / 'helixsr.ini').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.manager.register_source(str(self.source), self.hashes)

    def test_register_same_verified_source_retains_original_only_for_that_source(self):
        original = {'path': str(self.base / 'genuine.dll'), 'sha256': 'a' * 64,
                    'game_folder': str(self.base / 'games' / 'Example')}
        self.manager.register_source(str(self.source), self.hashes, original)
        self.manager.register_source(str(self.source), dict(self.hashes))
        self.assertEqual(json.loads(self.manager.source_config.read_text())['original'], original)
        second = self.base / 'different-private-source'
        shutil.copytree(self.source, second)
        self.manager.register_source(str(second), dict(self.hashes))
        self.assertNotIn('original', json.loads(self.manager.source_config.read_text()))
        self.manager.register_source(str(self.source), self.hashes, original)
        expanded = dict(self.hashes)
        for name in armada.PACKAGE_FILES:
            if name in expanded:
                continue
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = b'private optional bytes'
            path.write_bytes(payload)
            expanded[name] = hashlib.sha256(payload).hexdigest()
        self.manager.register_source(str(self.source), expanded)
        self.assertNotIn('original', json.loads(self.manager.source_config.read_text()))

    def test_prepare_uses_selected_optiscaler_executable(self):
        game_root = self.base / 'games' / 'Selected'
        game_root.mkdir(parents=True)
        (game_root / 'nvngx_dlss.dll').write_bytes(pe())
        (game_root / 'Wrong.exe').write_bytes(pe(machine=0x14c) + b'padding' * 2048)
        selected = 'DX12/Right.exe'
        (game_root / 'DX12').mkdir()
        (game_root / selected).write_bytes(pe(dx12=True))
        game = {'id': 'fixture:selection', 'name': 'Selected', 'folder': str(game_root), 'source': 'Imported'}
        self.manager.entries[game['id']] = game
        self.manager.host_eligible = lambda: True
        for name in armada.PACKAGE_FILES:
            if name in self.hashes:
                continue
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = pe(ffx=True) if name.endswith('.dll') else b'private OptiScaler configuration'
            path.write_bytes(payload)
            self.hashes[name] = hashlib.sha256(payload).hexdigest()
        self.manager.register_source(str(self.source), self.hashes)
        with patch.object(armada, 'active_processes', return_value=[]), \
             patch('manager.active_processes', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'Main executable is not x64'):
                self.manager.prepare_private(game['id'])
            self.assertTrue(self.manager.prepare_private(game['id'], executable=selected)['ready'])

    def test_dx12_discovery_uses_pe_evidence_and_preserves_full_library(self):
        self.manager.host_eligible = lambda: True
        def assess(name, exe, provider=None, appid='3357650'):
            root = self.base / 'games' / name
            root.mkdir(parents=True)
            (root / 'Game.exe').write_bytes(exe)
            (root / ('amd_fidelityfx_upscaler_dx12.dll' if provider else 'nvngx_dlss.dll')).write_bytes(
                provider if provider is not None else pe())
            game = {'id': 'steam:' + name, 'appid': appid, 'name': name,
                    'folder': str(root), 'source': 'Steam'}
            self.manager.entries[game['id']] = game
            return self.manager.assess(game, detailed=False)
        with patch('manager.active_processes', return_value=[]):
            self.assertFalse(assess('DX12 in title only', pe())['dx12_detected'])
            self.assertFalse(assess('32 bit', pe(dx12=True, machine=0x14c))['dx12_detected'])
            self.assertFalse(assess('Filename only', pe(), pe())['dx12_detected'])
            self.assertTrue(assess('Imported DX12', pe(dx12=True))['dx12_detected'])
            self.assertTrue(assess('Native FidelityFX', pe(), pe(ffx=True))['dx12_detected'])
            self.assertFalse(assess('Known DX11 only', pe(dx12=True), appid='1593500')['dx12_detected'])
        # Frontend filtering must not remove access to backend restoration records.
        self.assertEqual(len(self.manager.entries), 6)

    def test_dx12_discovery_ignores_launcher_and_accepts_scanned_x64_choice(self):
        root = self.base / 'games' / 'Choices'
        root.mkdir(parents=True)
        (root / 'nvngx_dlss.dll').write_bytes(pe())
        (root / 'Launcher.exe').write_bytes(pe(dx12=True))
        (root / 'LargeWrong.exe').write_bytes(pe(machine=0x14c) + b'padding' * 2048)
        (root / 'Game.exe').write_bytes(pe())
        game = {'id': 'steam:choices', 'appid': '42', 'name': 'Choices',
                'folder': str(root), 'source': 'Steam'}
        self.manager.host_eligible = lambda: True
        with patch('manager.active_processes', return_value=[]):
            self.assertFalse(self.manager.assess(game, detailed=False)['dx12_detected'])
            (root / 'DX12.exe').write_bytes(pe(dx12=True))
            data = self.manager.assess(game, detailed=False)
            self.assertTrue(data['dx12_detected'])
            self.assertNotIn('Launcher.exe', [item['path'] for item in data['executable_choices']])

    def test_symlinked_source_file_rejected(self):
        path = self.source / 'helixsr.ini'
        target = self.base / 'ini-target'
        path.replace(target)
        try:
            path.symlink_to(target)
        except OSError:
            self.skipTest('Host does not permit symlink creation')
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.manager.register_source(str(self.source), self.hashes)

    def test_arm_host_requires_wave64_and_vkd3d(self):
        with patch.object(armada.platform, 'system', return_value='Linux'), \
             patch.object(armada.platform, 'machine', return_value='aarch64'):
            self.assertFalse(armada._host_eligible())
            self.assertFalse(armada._host_eligible(lambda: {'subgroup_min': 64, 'subgroup_max': 64}))
            self.assertFalse(armada._host_eligible(lambda: {'subgroup_min': 32, 'subgroup_max': 64, 'vkd3d': True}))
            self.assertTrue(armada._host_eligible(lambda: {'subgroup_min': 64, 'subgroup_max': 64, 'vkd3d': True}))
        with patch.object(armada.platform, 'system', return_value='Linux'), \
             patch.object(armada.platform, 'machine', return_value='x86_64'):
            wave = {'subgroup_min': 64, 'subgroup_max': 64, 'vkd3d': True}
            self.assertTrue(armada._host_eligible(lambda: dict(wave, native_arch='aarch64')))
            self.assertFalse(armada._host_eligible(lambda: dict(wave, native_arch='x86_64')))
            self.assertFalse(armada._host_eligible(lambda: wave))

    def test_companion_isolated_from_upstream_records_and_lock(self):
        game_root = self.base / 'games' / 'Companion'
        game_root.mkdir(parents=True)
        game = {'folder': str(game_root)}
        upstream = manager.Manager(self.home, self.base / 'upstream-settings').companion(game)
        private = self.manager.companion(game)
        self.assertNotEqual(private, upstream)
        self.assertEqual(private.name, 'HelixSR-Decky-Armada')
        upstream.mkdir(parents=True)
        (upstream / 'records').mkdir()
        (upstream / 'records/install.json').write_text('{"owner":"upstream"}')
        with operation_lock(upstream):
            with operation_lock(private):
                self.assertNotEqual(upstream / '.operation.lock', private / '.operation.lock')
        self.assertEqual((upstream / 'records/install.json').read_text(), '{"owner":"upstream"}')

    def test_direct_prepare_install_disable_enable_restores_original(self):
        game_root = self.base / 'games' / 'Example'
        game_root.mkdir(parents=True)
        original = pe(ffx=True)
        native = game_root / 'amd_fidelityfx_upscaler_dx12.dll'
        native.write_bytes(original)
        (game_root / 'Example.exe').write_bytes(pe(dx12=True))
        game = {'id': 'fixture:arm', 'name': 'Example', 'folder': str(game_root), 'source': 'Imported'}
        self.manager.entries[game['id']] = game
        self.manager.host_eligible = lambda: True
        self.manager.register_source(str(self.source), self.hashes)
        with patch.object(armada, 'active_processes', return_value=[]), \
             patch('manager.active_processes', return_value=[]):
            self.assertTrue(self.manager.prepare_private(game['id'])['ready'])
            preview = self.manager.preview(game['id'], 'install')
            self.assertEqual(preview['backend'], armada.BACKEND)
            self.manager.execute(preview['token'])
            self.assertEqual(armada.sha(native), self.hashes[armada.DLL])
            self.assertEqual(self.manager.record(game)['version'], armada.VERSION)
            self.assertEqual(self.manager.status(game['id'])['launch_environment']['PROTON_USE_ARM64'], '1')
            self.manager.execute(self.manager.preview(game['id'], 'disable')['token'])
            self.assertEqual(native.read_bytes(), original)
            self.manager.execute(self.manager.preview(game['id'], 'enable')['token'])
            self.assertEqual(armada.sha(native), self.hashes[armada.DLL])

    def test_adopt_requires_independent_original_then_can_disable(self):
        game_root = self.base / 'games' / 'Existing'
        game_root.mkdir(parents=True)
        native = game_root / 'amd_fidelityfx_upscaler_dx12.dll'
        native.write_bytes((self.source / armada.DLL).read_bytes())
        for name in (*armada.NETWORK, 'helixsr.ini'):
            (game_root / name).write_bytes((self.source / name).read_bytes())
        (game_root / 'Existing.exe').write_bytes(pe(dx12=True))
        original_bytes = pe(ffx=True)
        old_folder = self.base / 'HelixSR-170-recovery'
        old_folder.mkdir()
        original_path = old_folder / 'original.dll'
        original_path.write_bytes(original_bytes)
        original = {'path': str(original_path), 'sha256': hashlib.sha256(original_bytes).hexdigest(),
                    'game_folder': str(game_root)}
        game = {'id': 'fixture:existing', 'name': 'Existing', 'folder': str(game_root), 'source': 'Imported'}
        self.manager.entries[game['id']] = game
        self.manager.host_eligible = lambda: True
        other_game = self.base / 'games' / 'Other'
        other_game.mkdir()
        wrong = dict(original, game_folder=str(other_game))
        self.manager.register_source(str(self.source), self.hashes, wrong)
        with patch.object(armada, 'active_processes', return_value=[]), \
             patch('manager.active_processes', return_value=[]):
            self.manager.prepare_private(game['id'])
            with self.assertRaisesRegex(ValueError, 'different game folder'):
                self.manager.preview(game['id'], 'adopt')
            self.manager.register_source(str(self.source), self.hashes, original)
            token = self.manager.preview(game['id'], 'adopt')['token']
            with self.assertRaisesRegex(ValueError, 'launch environment'):
                self.manager.execute(token)
            source_ini = self.source / 'helixsr.ini'
            source_ini.write_bytes(b'changed after preview')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                self.manager.execute(token, launch_environment_verified=True)
            source_ini.write_bytes(b'[HelixSR]\n')
            token = self.manager.preview(game['id'], 'adopt')['token']
            staged_override = self.manager.companion(game) / 'packages/v762/shader-override/1ad412dd861a9c17.spv'
            staged_bytes = staged_override.read_bytes()
            staged_override.write_bytes(b'changed staged override')
            with self.assertRaises(ValueError):
                self.manager.execute(token, launch_environment_verified=True)
            staged_override.write_bytes(staged_bytes)
            token = self.manager.preview(game['id'], 'adopt')['token']
            self.assertTrue(self.manager.execute(token, launch_environment_verified=True)['enabled'])
            self.assertTrue(self.manager.status(game['id'])['adopted'])
            self.manager.execute(self.manager.preview(game['id'], 'disable')['token'])
            self.assertEqual(native.read_bytes(), original_bytes)


if __name__ == '__main__':
    unittest.main()
