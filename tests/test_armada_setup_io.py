"""Offline setup I/O boundary tests; all fixtures live beside this project on D:."""
import hashlib
from email.message import Message
import io
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.response
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py_modules'))
import armada_setup_io as setup_io


class Response(io.BytesIO):
    def __init__(self, body, url='https://github.com/example/project/releases/download/v1/asset', headers=None):
        super().__init__(body)
        self.url = url
        self.headers = {'Content-Length': str(len(body))} if headers is None else headers
        self.status = 200
        self.read_sizes = []

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def read(self, size=-1):
        self.read_sizes.append(size)
        if size < 0:
            raise AssertionError('download reads must be bounded')
        return super().read(size)


class Opener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, request, *args, **kwargs):
        self.requests.append(request)
        return self.response


class SetupFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='armada-io-test-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.rejection_index = 0

    def zip(self, entries, name='fixture.zip'):
        archive = self.base / name
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as handle:
            for entry, contents in entries:
                if isinstance(entry, str):
                    # ZipInfo's constructor normalizes Windows separators; an
                    # adversarial archive can preserve them in its on-disk name.
                    member = zipfile.ZipInfo(entry)
                    member.filename = entry
                    member.orig_filename = entry
                    member.compress_type = zipfile.ZIP_DEFLATED
                else:
                    member = entry
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore', message='Duplicate name:', category=UserWarning)
                    handle.writestr(member, contents)
        return archive

    def tar(self, entries, name='fixture.tar'):
        archive = self.base / name
        with tarfile.open(archive, 'w') as handle:
            for member, contents in entries:
                handle.addfile(member, io.BytesIO(contents) if contents is not None else None)
        return archive

    def assert_rejected_extraction(self, method, archive, **kwargs):
        self.rejection_index += 1
        destination = self.base / f'output{self.rejection_index}'
        with self.assertRaises((ValueError, OSError, RuntimeError)):
            method(archive, destination, **kwargs)
        self.assertFalse(destination.exists(), 'failed extraction must roll back its owned output')
        self.assertTrue(archive.is_file(), 'source archive must survive failure')


class SafePaths(SetupFixtures):
    def test_new_nested_path_is_absolute_and_canonical(self):
        target = self.base / 'new' / 'nested' / 'file'
        result = setup_io.safe_path(target)
        self.assertIsInstance(result, Path)
        self.assertTrue(result.is_absolute())
        self.assertEqual(result, target.resolve())
        self.assertFalse(target.exists())

    def test_existing_directory_and_single_link_regular_file_are_allowed(self):
        regular = self.base / 'regular'
        regular.write_bytes(b'original')
        self.assertEqual(setup_io.safe_path(regular), regular.resolve())
        self.assertEqual(setup_io.safe_path(self.base), self.base.resolve())

    def test_symlink_ancestor_and_final_symlink_are_rejected(self):
        actual = self.base / 'actual'
        actual.mkdir()
        alias = self.base / 'alias'
        try:
            alias.symlink_to(actual, target_is_directory=True)
        except OSError as error:
            self.skipTest('symlink creation unavailable: ' + str(error))
        for target in (alias, alias / 'new' / 'file'):
            with self.subTest(target=target), self.assertRaises((ValueError, OSError)):
                setup_io.safe_path(target)

    def test_regular_hardlink_is_rejected(self):
        source = self.base / 'source'
        source.write_bytes(b'keep')
        alias = self.base / 'alias'
        os.link(source, alias)
        for target in (source, alias):
            with self.subTest(target=target), self.assertRaises((ValueError, OSError)):
                setup_io.safe_path(target)
        self.assertEqual(source.read_bytes(), b'keep')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO is unavailable on this platform')
    def test_fifo_is_rejected_without_opening_it(self):
        fifo = self.base / 'pipe'
        try:
            os.mkfifo(fifo)
        except OSError as error:
            import errno
            if error.errno in (errno.ENOSYS, errno.ENOTSUP):
                self.skipTest('Fixture filesystem does not support FIFO creation')
            raise
        with self.assertRaises((ValueError, OSError)):
            setup_io.safe_path(fifo)


class FetchAssets(SetupFixtures):
    body = b'fixture payload' * 10000
    url = 'https://github.com/example/project/releases/download/v1/asset'

    def spec(self, **updates):
        result = {'url': self.url, 'size': len(self.body), 'sha256': hashlib.sha256(self.body).hexdigest()}
        result.update(updates)
        return result

    def fetch(self, spec=None, body=None, cancel=None, progress=None, headers=None):
        response = Response(self.body if body is None else body, headers=headers)
        opener = Opener(response)
        with patch.object(setup_io.urllib.request, 'build_opener', return_value=opener):
            result = setup_io.fetch_asset(spec or self.spec(), self.base / 'asset', cancel or threading.Event(), progress)
        return result, response, opener

    def test_verified_download_and_progress(self):
        progress = []
        _, response, opener = self.fetch(progress=lambda done, total: progress.append((done, total)))
        self.assertEqual((self.base / 'asset').read_bytes(), self.body)
        self.assertEqual(set(self.base.iterdir()), {self.base / 'asset'})
        self.assertEqual(len(opener.requests), 1)
        self.assertTrue(response.read_sizes)
        self.assertTrue(all(0 < size <= 1024 * 1024 for size in response.read_sizes))
        self.assertTrue(progress)
        self.assertEqual(progress[-1], (len(self.body), len(self.body)))
        self.assertEqual([done for done, _ in progress], sorted(done for done, _ in progress))

    def test_invalid_spec_is_rejected_before_network_or_file_creation(self):
        cases = [
            {'url': 'http://github.com/a'}, {'url': 'https://evil.example/a'},
            {'url': 'https://github.com.evil.example/a'}, {'url': 'https://user@github.com/a'},
            {'url': 'https://github.com:443/a'}, {'url': self.url + '?token=x'},
            {'url': self.url + '#fragment'}, {'size': 0}, {'size': -1},
            {'size': True}, {'size': 1.5},
            {'size': 512 * 1024 * 1024 + 1}, {'sha256': 'f' * 63},
            {'sha256': 'G' * 64}, {'sha256': 'A' * 64},
        ]
        for updates in cases:
            with self.subTest(updates=updates), patch.object(setup_io.urllib.request, 'build_opener') as network:
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    setup_io.fetch_asset(self.spec(**updates), self.base / 'asset', threading.Event())
                network.assert_not_called()
                self.assertEqual(list(self.base.iterdir()), [])

    def test_other_trusted_sources_download_without_redirect(self):
        for host in ('raw.githubusercontent.com', 'files.pythonhosted.org'):
            with self.subTest(host=host):
                self.fetch(self.spec(url=f'https://{host}/fixture/asset'))
                target = self.base / 'asset'
                self.assertEqual(target.read_bytes(), self.body)
                target.unlink()

    def test_size_and_hash_mismatch_remove_partial_downloads(self):
        for updates, body in [({}, self.body[:-1]), ({}, self.body + b'extra'),
                              ({'sha256': '0' * 64}, self.body)]:
            with self.subTest(updates=updates, size=len(body)):
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    self.fetch(self.spec(**updates), body, headers={})
                self.assertEqual(list(self.base.iterdir()), [])

    def test_existing_destination_is_preserved(self):
        destination = self.base / 'asset'
        destination.write_bytes(b'keep existing')
        with self.assertRaises((ValueError, OSError, RuntimeError)):
            self.fetch()
        self.assertEqual(destination.read_bytes(), b'keep existing')
        self.assertEqual(list(self.base.iterdir()), [destination])

    def test_destination_created_during_download_is_not_overwritten(self):
        destination = self.base / 'asset'
        def competing_writer(done, total):
            if not destination.exists():
                destination.write_bytes(b'other writer')
        with self.assertRaises((ValueError, OSError, RuntimeError)):
            self.fetch(progress=competing_writer)
        self.assertEqual(destination.read_bytes(), b'other writer')
        self.assertEqual(list(self.base.iterdir()), [destination])

    def test_cancellation_before_download_leaves_no_files(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises((ValueError, OSError, RuntimeError, InterruptedError)):
            self.fetch(cancel=cancel)
        self.assertEqual(list(self.base.iterdir()), [])

    def test_cancellation_during_stream_leaves_no_files(self):
        cancel = threading.Event()
        def progress(done, total):
            if done:
                cancel.set()
        with self.assertRaises((ValueError, OSError, RuntimeError, InterruptedError)):
            self.fetch(cancel=cancel, progress=progress)
        self.assertEqual(list(self.base.iterdir()), [])

    def redirect_fetch(self, redirected, initial=None):
        requests = []
        body = self.body
        class OfflineHTTPS(urllib.request.HTTPSHandler):
            def https_open(self, request):
                requests.append(request.full_url)
                headers = Message()
                if len(requests) == 1:
                    headers['Location'] = redirected
                    response = urllib.response.addinfourl(io.BytesIO(b''), headers, request.full_url, 302)
                else:
                    headers['Content-Length'] = str(len(body))
                    response = urllib.response.addinfourl(io.BytesIO(body), headers, request.full_url, 200)
                response.msg = 'offline fixture'
                return response
        builder = urllib.request.build_opener
        def offline_builder(*handlers):
            return builder(*(handler for handler in handlers if not isinstance(handler, urllib.request.HTTPSHandler)), OfflineHTTPS())
        try:
            with patch.object(setup_io.urllib.request, 'build_opener', side_effect=offline_builder):
                setup_io.fetch_asset(self.spec(url=initial or self.url), self.base / 'asset', threading.Event())
        finally:
            self.redirect_requests = requests

    def test_untrusted_redirects_are_rejected_before_second_request(self):
        for redirected in ('https://evil.example/asset', 'http://github.com/asset',
                           'https://user@objects.githubusercontent.com/asset',
                           'https://objects.githubusercontent.com:443/asset',
                           'https://objects.githubusercontent.com/asset#fragment'):
            with self.subTest(redirected=redirected):
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    self.redirect_fetch(redirected)
                self.assertEqual(self.redirect_requests, [self.url])
                self.assertEqual(list(self.base.iterdir()), [])

    def test_official_signed_github_redirect_is_allowed(self):
        redirected = 'https://release-assets.githubusercontent.com/asset?signature=fixture'
        self.redirect_fetch(redirected)
        self.assertEqual(self.redirect_requests, [self.url, redirected])
        self.assertEqual((self.base / 'asset').read_bytes(), self.body)

    def test_other_initial_sources_cannot_redirect(self):
        for initial in ('https://raw.githubusercontent.com/example/project/v1/asset',
                        'https://files.pythonhosted.org/packages/asset.whl'):
            with self.subTest(initial=initial):
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    self.redirect_fetch('https://github.com/asset', initial=initial)
                self.assertEqual(self.redirect_requests, [initial])
                self.assertEqual(list(self.base.iterdir()), [])


class ZipExtraction(SetupFixtures):
    def test_regular_files_and_directories_extract(self):
        archive = self.zip([('pkg/', b''), ('pkg/config.txt', b'config'), ('readme', b'readme')])
        destination = self.base / 'output'
        setup_io.extract_zip(archive, destination)
        self.assertEqual((destination / 'pkg/config.txt').read_bytes(), b'config')
        self.assertEqual((destination / 'readme').read_bytes(), b'readme')

    def test_invalid_names_cannot_escape_or_create_output(self):
        for name in ('../outside', '/absolute', 'C:/drive', 'a\\b', 'a/../b', 'a//b', './file', 'a/./b'):
            with self.subTest(name=name):
                archive = self.zip([('safe', b'safe'), (name, b'bad')])
                self.assert_rejected_extraction(setup_io.extract_zip, archive)
                self.assertFalse((self.base / 'outside').exists())

    def test_duplicates_and_file_directory_conflicts_are_rejected(self):
        for entries in [[('same', b'a'), ('same', b'b')], [('parent', b'a'), ('parent/child', b'b')]]:
            with self.subTest(entries=entries):
                archive = self.zip(entries)
                self.assert_rejected_extraction(setup_io.extract_zip, archive)

    def test_symlink_and_fifo_members_are_rejected(self):
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600):
            member = zipfile.ZipInfo('special')
            member.create_system = 3
            member.external_attr = mode << 16
            archive = self.zip([(member, b'target')])
            with self.subTest(mode=mode):
                self.assert_rejected_extraction(setup_io.extract_zip, archive)

    def test_total_size_and_compression_ratio_are_bounded(self):
        archive = self.zip([('first', b'1234'), ('second', b'5678')])
        self.assert_rejected_extraction(setup_io.extract_zip, archive, max_bytes=7)
        bomb = self.zip([('compressed', b'0' * 1024 * 1024)], name='ratio.zip')
        self.assert_rejected_extraction(setup_io.extract_zip, bomb)

    def test_inventory_entry_count_is_bounded(self):
        archive = self.zip([(f'file{i}', b'') for i in range(10001)])
        self.assert_rejected_extraction(setup_io.extract_zip, archive)

    def test_crc_failure_rolls_back_already_extracted_members(self):
        archive = self.base / 'corrupt.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as handle:
            handle.writestr('first', b'valid first member')
            handle.writestr('second', b'unique payload to corrupt')
        encoded = archive.read_bytes()
        self.assertIn(b'unique payload to corrupt', encoded)
        archive.write_bytes(encoded.replace(b'unique payload to corrupt', b'broken payload to corrupt'))
        self.rejection_index += 1
        destination = self.base / f'output{self.rejection_index}'
        with self.assertRaises((ValueError, OSError, RuntimeError, zipfile.BadZipFile)):
            setup_io.extract_zip(archive, destination)
        self.assertFalse(destination.exists())
        self.assertTrue(archive.is_file())

    def test_existing_output_is_never_overwritten_or_removed(self):
        archive = self.zip([('sentinel', b'new')])
        destination = self.base / 'output'
        destination.mkdir()
        sentinel = destination / 'sentinel'
        sentinel.write_bytes(b'keep')
        with self.assertRaises((ValueError, OSError, RuntimeError)):
            setup_io.extract_zip(archive, destination)
        self.assertEqual(sentinel.read_bytes(), b'keep')


class TarExtraction(SetupFixtures):
    def regular(self, name, contents=b'payload', mode=0o644):
        member = tarfile.TarInfo(name)
        member.size = len(contents)
        member.mode = mode
        return member, contents

    def test_executable_regular_file_extracts_and_symlink_is_skipped(self):
        alias = tarfile.TarInfo('pkg/alias')
        alias.type = tarfile.SYMTYPE
        alias.linkname = 'run'
        archive = self.tar([self.regular('pkg/run', b'#!/bin/sh\n', 0o755), (alias, None)])
        destination = self.base / 'output'
        setup_io.extract_tar(archive, destination)
        executable = destination / 'pkg/run'
        self.assertEqual(executable.read_bytes(), b'#!/bin/sh\n')
        self.assertFalse((destination / 'pkg/alias').exists())
        self.assertFalse((destination / 'pkg/alias').is_symlink())
        if os.name != 'nt':
            self.assertEqual(executable.stat().st_mode & 0o111, 0o111)

    def test_invalid_names_are_rejected_before_output(self):
        for name in ('../outside', '/absolute', 'C:/drive', 'a\\b', 'a/../b', 'a//b', './file', 'a/./b'):
            with self.subTest(name=name):
                archive = self.tar([self.regular('safe'), self.regular(name)])
                self.assert_rejected_extraction(setup_io.extract_tar, archive)

    def test_duplicate_files_are_rejected(self):
        archive = self.tar([self.regular('same', b'a'), self.regular('same', b'b')])
        self.assert_rejected_extraction(setup_io.extract_tar, archive)

    def test_hardlinks_devices_and_fifo_are_rejected(self):
        for kind in (tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE):
            special = tarfile.TarInfo('special')
            special.type = kind
            special.linkname = 'regular'
            with self.subTest(kind=kind):
                archive = self.tar([self.regular('regular'), (special, None)])
                self.assert_rejected_extraction(setup_io.extract_tar, archive)

    def test_total_bytes_and_entry_count_are_bounded(self):
        archive = self.tar([self.regular('a', b'1234'), self.regular('b', b'5678')])
        self.assert_rejected_extraction(setup_io.extract_tar, archive, max_bytes=7)
        archive = self.tar([self.regular(f'file{i}', b'') for i in range(10001)], 'count.tar')
        self.assert_rejected_extraction(setup_io.extract_tar, archive)

    def test_existing_output_survives_rejection(self):
        archive = self.tar([self.regular('sentinel', b'new')])
        destination = self.base / 'output'
        destination.mkdir()
        sentinel = destination / 'sentinel'
        sentinel.write_bytes(b'keep')
        with self.assertRaises((ValueError, OSError, RuntimeError)):
            setup_io.extract_tar(archive, destination)
        self.assertEqual(sentinel.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
