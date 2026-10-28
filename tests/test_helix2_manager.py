import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import helix2_manager as h

class FakeManager:
    def __init__(self, root):
        self.root = root
        self.settings = root.parent / 'settings'
        self.settings.mkdir()
    def get_game(self, gid):
        return {'appid': '3357650', 'name': 'PRAGMATA', 'folder': str(self.root)}
    def assess(self, game):
        return {'targets': [str(self.root / h.DLL)]}
    def companion(self, game):
        return self.root.parent / 'legacy-lock'
    @staticmethod
    def _symlink_in_path(path):
        return any(p.is_symlink() for p in (Path(path), *Path(path).parents))

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.game = self.base / 'game'
        self.game.mkdir()
        self.source = self.base / 'source'
        self.source.mkdir()
        (self.game / h.DLL).write_bytes(b'stock')
        (self.game / 'helixsr.ini').write_bytes(b'[Upscaling]\nInt8=auto ; note\n[Log]\nEnabled=true\n')
        (self.source / h.DLL).write_bytes(b'provider')
        (self.source / 'helixsr.ini').write_bytes(b'[Upscaling]\nInt8=auto\n')
        self.patches = [patch.object(h, 'STOCK', hashlib.sha256(b'stock').hexdigest()),
                        patch.object(h, 'PROVIDER', hashlib.sha256(b'provider').hexdigest()),
                        patch('manager.active_processes', return_value=[])]
        for p in self.patches: p.start()
        self.m = h.Helix2Manager(FakeManager(self.game))
        self.m.register_source(str(self.source))
    def tearDown(self):
        for p in self.patches: p.stop()
        self.temp.cleanup()
    def act(self, action, options=None):
        return self.m.execute(self.m.preview('3357650', action, options)['token'])
    def test_cycle(self):
        self.act('install')
        self.assertEqual((self.game / h.DLL).read_bytes(), b'provider')
        self.act('settings', {'Int8': 'on', 'WaveSize': '64'})
        self.assertIn(b'Int8=on ; note', (self.game / 'helixsr.ini').read_bytes())
        self.act('disable')
        self.assertEqual((self.game / h.DLL).read_bytes(), b'stock')
        self.act('enable')
        self.act('remove')
        self.assertEqual((self.game / h.DLL).read_bytes(), b'stock')
        self.assertEqual((self.game / h.ORIGINAL).read_bytes(), b'stock')
    def test_adopt(self):
        (self.game / h.DLL).write_bytes(b'provider')
        (self.game / h.ORIGINAL).write_bytes(b'stock')
        self.act('adopt')
        self.assertTrue(self.m.status('3357650')['managed'])
    def test_changed_since_preview(self):
        token = self.m.preview('3357650', 'install')['token']
        (self.game / 'helixsr.ini').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.m.execute(token)
    def test_mixed_and_unknown_fail(self):
        (self.game / 'helixsr_weights.bin').write_bytes(b'x')
        with self.assertRaises(ValueError): self.m.preview('3357650', 'install')
        (self.game / 'helixsr_weights.bin').unlink()
        (self.game / h.DLL).write_bytes(b'unknown')
        with self.assertRaises(ValueError): self.m.preview('3357650', 'install')
    def test_failure_rolls_back(self):
        real_replace = self.m._atomic_replace
        def fail_provider(dst, **kwargs):
            if kwargs.get('source') == self.source / h.DLL:
                raise OSError('injected failure')
            return real_replace(dst, **kwargs)
        with patch.object(self.m, '_atomic_replace', side_effect=fail_provider):
            with self.assertRaises(OSError): self.act('install')
        self.assertEqual((self.game / h.DLL).read_bytes(), b'stock')
        self.assertFalse((self.game / h.ORIGINAL).exists())
        self.assertFalse((self.base / 'game Mod Files' / 'HelixSR-Decky-Adreno-2' / 'transaction').exists())

    def test_short_write_leaves_original_and_cleans_temp(self):
        target = self.game / h.DLL
        def short_write(stream, chunk):
            stream.write(chunk[:2])
            raise OSError('disk full')
        with patch.object(self.m, '_write_chunk', side_effect=short_write):
            with self.assertRaises(OSError):
                self.m._atomic_replace(target, source=self.source / h.DLL)
        self.assertEqual(target.read_bytes(), b'stock')
        self.assertEqual(list(self.game.glob('.helix2-*.tmp')), [])

    def test_hardlink_rejected(self):
        import os
        os.link(self.game / h.DLL, self.base / 'hardlink')
        with self.assertRaises(ValueError): self.m.preview('3357650', 'install')

    def test_hash_cache_invalidates(self):
        path = self.game / h.DLL
        first = self.m._hash(path)
        path.write_bytes(b'other')
        self.assertNotEqual(first, self.m._hash(path))

    def test_running_rejected(self):
        with patch('manager.active_processes', return_value=[{'pid': 1}]):
            with self.assertRaises(ValueError): self.m.preview('3357650', 'install')

    def test_source_ini_added_when_missing(self):
        (self.game / 'helixsr.ini').unlink()
        self.act('install')
        self.assertEqual((self.game / 'helixsr.ini').read_bytes(), (self.source / 'helixsr.ini').read_bytes())

    def test_official_source_without_ini_uses_default(self):
        import json
        (self.source / 'helixsr.ini').unlink()
        self.assertTrue(self.m.register_source(str(self.source))['ready'])
        cfg = json.loads((self.m.manager.settings / 'helix2-source.json').read_text(encoding='utf-8'))
        default = self.m.manager.settings / 'helix2-default.ini'
        self.assertEqual(cfg['ini_source'], str(default))
        self.assertEqual(default.read_bytes(), h.DEFAULT_INI)
        (self.game / 'helixsr.ini').unlink()
        self.act('install')
        self.assertEqual((self.game / 'helixsr.ini').read_bytes(), h.DEFAULT_INI)

    def test_enable_preserves_edited_game_ini(self):
        (self.source / 'helixsr.ini').unlink()
        self.m.register_source(str(self.source))
        self.act('install')
        self.act('disable')
        custom = b'[Upscaling]\nInt8=off ; user setting\n[Other]\nValue=unchanged\n'
        (self.game / 'helixsr.ini').write_bytes(custom)
        self.act('enable')
        self.assertEqual((self.game / 'helixsr.ini').read_bytes(), custom)

    def test_cache_reuses_unchanged_hash(self):
        path = self.game / h.DLL
        first = self.m._hash(path)
        with patch.object(Path, 'open', side_effect=AssertionError('unexpected rehash')):
            self.assertEqual(first, self.m._hash(path))

    def test_recovery_and_conflict(self):
        real_replace = self.m._atomic_replace
        def fail_writes(dst, **kwargs):
            source = kwargs.get('source')
            if source == self.source / h.DLL or (source is not None and Path(source).parent.name == 'transaction'):
                raise OSError('injected failure')
            return real_replace(dst, **kwargs)
        with patch.object(self.m, '_atomic_replace', side_effect=fail_writes):
            with self.assertRaises(OSError): self.act('install')
        tx = self.base / 'game Mod Files' / 'HelixSR-Decky-Adreno-2' / 'transaction'
        self.assertTrue(tx.exists())
        (self.game / h.DLL).write_bytes(b'external change')
        with self.assertRaises(ValueError): self.m.recover('3357650')
        (self.game / h.DLL).write_bytes(b'stock')
        self.m.recover('3357650')
        self.assertFalse(tx.exists())
        self.assertFalse((self.game / h.ORIGINAL).exists())

    def test_committed_recovery_finalizes(self):
        import shutil
        real_rmtree = shutil.rmtree
        def fail_once(path, *args, **kwargs):
            if Path(path).name == 'transaction':
                raise OSError('injected cleanup failure')
            return real_rmtree(path, *args, **kwargs)
        with patch('shutil.rmtree', side_effect=fail_once):
            with self.assertRaises(OSError): self.act('install')
        self.assertEqual((self.game / h.DLL).read_bytes(), b'provider')
        status = self.m.status('3357650')
        self.assertEqual(status['actions'], ['recover'])
        with patch('manager.active_processes', return_value=[{'pid': 1}]):
            self.assertFalse(self.m.status('3357650')['can_modify'])
        self.m.recover('3357650')
        self.assertEqual((self.game / h.DLL).read_bytes(), b'provider')
        self.assertTrue(self.m.status('3357650')['managed'])

    def test_real_manager_ignores_legacy_receipt(self):
        from manager import Manager
        manager = Manager(self.base, self.base / 'realsettings')
        manager.entries['3357650'] = manager.get_game('3357650') if '3357650' in manager.entries else {'appid':'3357650', 'name':'PRAGMATA', 'folder':str(self.game)}
        legacy = manager.companion(manager.entries['3357650']) / 'records' / 'install.json'
        legacy.parent.mkdir(parents=True)
        legacy.write_text('{"backend":"armada-v762"}', encoding='utf-8')
        self.assertEqual(h.Helix2Manager(manager).status('3357650')['state'], 'stock')
        self.assertEqual(legacy.read_text(encoding='utf-8'), '{"backend":"armada-v762"}')

    def test_symlink_rejected(self):
        import os
        target = self.game / h.DLL
        target.unlink()
        try:
            os.symlink(self.source / h.DLL, target)
        except OSError:
            self.skipTest('Creating symlinks is not available')
        with self.assertRaises(ValueError): self.m.preview('3357650', 'install')

    def test_duplicates_fail(self):
        with self.assertRaises(ValueError): h.edit_ini(b'[Upscaling]\nInt8=on\nInt8=off\n', {'Int8':'auto'})

if __name__ == '__main__': unittest.main()
