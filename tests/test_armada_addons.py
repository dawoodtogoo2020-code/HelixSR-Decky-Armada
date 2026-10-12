"""Offline checks for the narrowly scoped combined-launch receipt."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
import armada_manager as armada
import launch_addons
import manager
from test_backend import pe


class AddonSafety(unittest.TestCase):
    def setUp(self):
        work = ROOT.parent / 'armada-test-work'
        work.mkdir(exist_ok=True)
        tmp = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.game_root = self.base / 'games' / 'PRAGMATA'
        self.game_root.mkdir(parents=True)
        self.game = {'id': 'steam:3357650', 'source': 'Steam', 'appid': '3357650',
                     'name': 'PRAGMATA', 'folder': str(self.game_root)}
        self.m = armada.ArmadaManager(self.home, self.base / 'settings')
        self.m.entries[self.game['id']] = self.game
        self.m.host_eligible = lambda: True
        self.helper = launch_addons.helper_path(self.game)
        self.helper.parent.mkdir(parents=True)
        self.helper.write_bytes(b'private synthetic helper')
        self.helper_hash = hashlib.sha256(self.helper.read_bytes()).hexdigest()
        pin = patch.object(launch_addons, 'HELPER_SHA256', self.helper_hash)
        pin.start()
        self.addCleanup(pin.stop)
        self.options = ("ENABLE_GAMESCOPE_WSI=0 /usr/bin/python3 '" + str(self.helper) +
                        "' /usr/libexec/armada/armada-game-launch /usr/bin/env "
                        "PROTON_USE_ARM64=1 %command%")
        manager.atomic_json(self.m.record_path(self.game), {'enabled': True})

    def test_capture_only_pinned_pragmata_helper_and_no_full_options(self):
        self.assertTrue(self.m.remember_launch_addon(self.game['id'], self.options)['remembered'])
        self.assertEqual(self.m.launch_addon(self.game)['environment'], {'ENABLE_GAMESCOPE_WSI': '0'})
        raw = launch_addons.record_path(self.m.companion(self.game)).read_text()
        self.assertNotIn('%command%', raw)
        self.assertNotIn('PROTON_USE_ARM64', raw)
        self.assertFalse(self.m.remember_launch_addon(self.game['id'], 'PROTON_USE_ARM64=1 %command%')['remembered'])
        self.assertIsNone(self.m.launch_addon(self.game))
        other = dict(self.game, id='steam:1', appid='1', name='Other')
        self.m.entries[other['id']] = other
        manager.atomic_json(self.m.record_path(other), {'enabled': True})
        self.assertFalse(self.m.remember_launch_addon(other['id'], self.options)['remembered'])
        self.assertIsNone(self.m.launch_addon(other))

    def test_changed_or_missing_helper_does_not_prevent_capture_but_blocks_reenable(self):
        self.helper.write_bytes(b'changed')
        self.assertTrue(self.m.remember_launch_addon(self.game['id'], self.options)['remembered'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.m.launch_addon(self.game)
        self.helper.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.m.launch_addon(self.game)

    def test_duplicate_nonleading_wsi_and_wrapper_are_rejected(self):
        cases = [
            'ENABLE_GAMESCOPE_WSI=0 ' + self.options,
            self.options.replace('/usr/libexec/armada/armada-game-launch',
                                 '/usr/libexec/armada/armada-game-launch ENABLE_GAMESCOPE_WSI=0'),
            self.options.replace('/usr/libexec/armada/armada-game-launch',
                                 '/usr/libexec/armada/armada-game-launch /usr/libexec/armada/armada-game-launch'),
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.m.remember_launch_addon(self.game['id'], value)
        self.assertFalse(launch_addons.record_path(self.m.companion(self.game)).exists())

    def test_unowned_helper_alias_and_interpreter_are_rejected(self):
        alias = self.base / 'unowned-helper.py'
        try:
            alias.symlink_to(self.helper)
        except OSError:
            self.skipTest('Symlinks unavailable')
        with self.assertRaisesRegex(ValueError, 'Unrecognized Python launcher'):
            self.m.remember_launch_addon(self.game['id'],
                self.options.replace(str(self.helper), str(alias)))
        with self.assertRaisesRegex(ValueError, 'interpreter'):
            self.m.remember_launch_addon(self.game['id'],
                self.options.replace('/usr/bin/python3', '/bin/python3'))

    def test_record_and_helper_link_tamper_are_rejected(self):
        self.m.remember_launch_addon(self.game['id'], self.options)
        receipt = launch_addons.record_path(self.m.companion(self.game))
        receipt.write_text(receipt.read_text().replace('"wsi": "0"', '"wsi": "1"'))
        with self.assertRaisesRegex(ValueError, 'receipt changed'):
            self.m.launch_addon(self.game)
        self.m.remember_launch_addon(self.game['id'], self.options)
        linked = self.base / 'hardlink-helper'
        try:
            linked.hardlink_to(self.helper)
        except OSError:
            self.skipTest('Hardlinks unavailable')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.m.launch_addon(self.game)
        linked.unlink()
        real = self.base / 'real-helper'
        self.helper.replace(real)
        try:
            self.helper.symlink_to(real)
        except OSError:
            self.skipTest('Symlinks unavailable')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.m.launch_addon(self.game)

    def test_preview_execute_rechecks_helper_before_game_file_write(self):
        # Give this fixture a genuine direct-game install and synthetic package.
        self.m.record_path(self.game).unlink()
        native = self.game_root / 'amd_fidelityfx_upscaler_dx12.dll'
        native.write_bytes(pe(ffx=True))
        (self.game_root / 'PRAGMATA.exe').write_bytes(pe(dx12=True))
        source = self.base / 'source'
        source.mkdir()
        payloads = {armada.DLL: pe(ffx=True, helix=True),
                    'helixsr_kernels.pak': b'pack', 'helixsr_weights.bin': b'weights',
                    'helixsr.ini': b'[HelixSR]\n'}
        payloads.update({'shader-override/' + n: n.encode() for n in armada.OVERRIDES})
        for name, body in payloads.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        hashes = {n: hashlib.sha256(body).hexdigest() for n, body in payloads.items()}
        with patch.dict(armada.PINNED, hashes, clear=True), \
             patch.object(armada, 'active_processes', return_value=[]), \
             patch('manager.active_processes', return_value=[]):
            self.m.register_source(str(source), hashes)
            self.m.prepare_private(self.game['id'])
            self.m.execute(self.m.preview(self.game['id'], 'install')['token'])
            self.m.remember_launch_addon(self.game['id'], self.options)
            preview = self.m.preview(self.game['id'], 'update')
            self.assertEqual(preview['launch_addon']['sha256'], self.helper_hash)
            before = manager.sha(native)
            self.helper.write_bytes(b'changed between preview and execute')
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.m.execute(preview['token'])
            self.assertEqual(manager.sha(native), before)
            pending = len(self.m.previews)
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.m.preview(self.game['id'], 'update')
            self.assertEqual(len(self.m.previews), pending)
            self.m.execute(self.m.preview(self.game['id'], 'disable')['token'])
            self.assertNotEqual(manager.sha(native), before)
            self.m.execute(self.m.preview(self.game['id'], 'remove')['token'])
            self.assertFalse(launch_addons.record_path(self.m.companion(self.game)).exists())

    def test_remove_clears_corrupt_owned_addon_receipt(self):
        self.m.remember_launch_addon(self.game['id'], self.options)
        receipt = launch_addons.record_path(self.m.companion(self.game))
        receipt.write_text('{"corrupt":true}')
        launch_addons.write_record(self.m.companion(self.game), self.game, None)
        self.assertFalse(receipt.exists())


if __name__ == '__main__':
    unittest.main()
