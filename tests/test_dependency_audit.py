import copy
import datetime
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_dependency_audit as audit


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'package.json').write_text(json.dumps({'devDependencies': {'@rollup/plugin-node-resolve': '15.2.3'}}))
        self.source = self.root / 'node_modules/@rollup/plugin-node-resolve/dist/es/index.js'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'reviewed source')
        self.patcher = patch.object(audit, 'SOURCE_SHA', hashlib.sha256(b'reviewed source').hexdigest())
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.finding = {'version': '4.3.1', 'paths': [audit.PATH], 'dev': True, 'bundled': False}
        self.report = {'advisories': {'1': {'github_advisory_id': audit.GHSA, 'module_name': 'deepmerge', 'severity': 'low', 'patched_versions': None, 'findings': [self.finding]}}, 'metadata': {'vulnerabilities': {'info': 0, 'low': 1, 'moderate': 0, 'high': 0, 'critical': 0}}}
        self.today = datetime.date(2026, 11, 28)

    def check(self, report=None, code=1, today=None):
        return audit.check(self.report if report is None else report, code, self.root, today or self.today)

    def test_exact_exception_and_empty_result(self):
        self.assertIn('build-only exception', self.check())
        empty = {'advisories': {}, 'metadata': {'vulnerabilities': dict.fromkeys(('info', 'low', 'moderate', 'high', 'critical'), 0)}}
        self.assertIn('No audit advisories', self.check(empty, 0))

    def test_wrong_path_runtime_and_version_fail(self):
        for key, value in [('paths', ['.>other>deepmerge']), ('dev', False), ('bundled', True), ('version', '4.4.0')]:
            with self.subTest(key=key):
                report = copy.deepcopy(self.report)
                report['advisories']['1']['findings'][0][key] = value
                with self.assertRaises(ValueError): self.check(report)

    def test_unknown_or_patched_advisory_and_errors_fail(self):
        for key, value in [('github_advisory_id', 'GHSA-other'), ('patched_versions', '>=4.4.0'), ('severity', 'high')]:
            with self.subTest(key=key):
                report = copy.deepcopy(self.report)
                report['advisories']['1'][key] = value
                with self.assertRaises(ValueError): self.check(report)
        with self.assertRaises(ValueError): self.check({'error': 'failed'})
        with self.assertRaises(ValueError): self.check(self.report, 2)

    def test_source_declaration_and_expiry_fail(self):
        self.source.write_bytes(b'changed source')
        with self.assertRaises(ValueError): self.check()
        self.source.write_bytes(b'reviewed source')
        (self.root / 'package.json').write_text(json.dumps({'devDependencies': {'@rollup/plugin-node-resolve': '16.0.3'}}))
        with self.assertRaises(ValueError): self.check()
        with self.assertRaises(ValueError): self.check(today=datetime.date(2026, 11, 29))


if __name__ == '__main__': unittest.main()
