"""Fail closed on pnpm audit results, with one time-limited build exception."""
import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GHSA = 'GHSA-gcqx-w48m-w2h4'
SOURCE_SHA = '4a22ca701bbf469e8e84dcb4fd6a182eb8678b74979242c95b41db215f00394c'
EXPIRES = datetime.date(2026, 11, 28)
PATH = '.>@rollup/plugin-node-resolve>deepmerge'


def check(report, exit_code, root=ROOT, today=None):
    if not isinstance(report, dict) or 'error' in report:
        raise ValueError('Audit response is invalid or reports an error')
    advisories = report.get('advisories')
    metadata = report.get('metadata')
    if not isinstance(advisories, dict) or not isinstance(metadata, dict):
        raise ValueError('Audit response lacks advisories or metadata')
    counts = metadata.get('vulnerabilities')
    levels = ('info', 'low', 'moderate', 'high', 'critical')
    if not isinstance(counts, dict) or set(counts) != set(levels) or any(type(counts[x]) is not int or counts[x] < 0 for x in levels):
        raise ValueError('Invalid vulnerability counts')
    if not advisories:
        if exit_code != 0 or any(counts.values()):
            raise ValueError('Inconsistent empty audit result')
        return 'No audit advisories reported.'
    if exit_code != 1 or len(advisories) != 1 or counts != dict.fromkeys(levels, 0) | {'low': 1}:
        raise ValueError('Unexpected audit findings or exit status')
    advisory = next(iter(advisories.values()))
    if not isinstance(advisory, dict) or advisory.get('github_advisory_id') != GHSA or advisory.get('module_name') != 'deepmerge' or advisory.get('severity') != 'low':
        raise ValueError('Unexpected advisory')
    if advisory.get('patched_versions', 'missing') is not None:
        raise ValueError('Reassess exception: patched version or missing field')
    findings = advisory.get('findings')
    if not isinstance(findings, list) or not findings:
        raise ValueError('Missing findings')
    for finding in findings:
        if not isinstance(finding, dict) or finding.get('version') != '4.3.1' or finding.get('dev') is not True or finding.get('bundled') is not False or finding.get('paths') != [PATH]:
            raise ValueError('Unexpected dependency version, scope, or path')
    if (today or datetime.date.today()) > EXPIRES:
        raise ValueError('Build dependency exception expired')
    package = json.loads((root / 'package.json').read_text(encoding='utf-8'))
    if package.get('devDependencies', {}).get('@rollup/plugin-node-resolve') != '15.2.3':
        raise ValueError('Resolver declaration changed')
    source = root / 'node_modules/@rollup/plugin-node-resolve/dist/es/index.js'
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError('Reviewed resolver source changed')
    return 'Accepted time-limited build-only exception: ' + GHSA + ' (deepmerge 4.3.1).'


def main():
    try:
        if len(sys.argv) != 3:
            raise ValueError('Usage: check_dependency_audit.py AUDIT_JSON EXIT_CODE')
        report = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        print(check(report, int(sys.argv[2])))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print('Dependency audit failed: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
