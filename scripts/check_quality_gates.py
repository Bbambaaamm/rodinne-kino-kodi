"""Fail CI when the declared quality contract or device evidence is broken."""
import ast
import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'quality-gates.json').read_text(encoding='utf8'))
EVIDENCE = json.loads((ROOT / 'quality/device-latest.json').read_text(encoding='utf8'))
PROVIDER = ROOT / 'addons/plugin.video.webshare.available'


def assignment(path, name):
    tree = ast.parse(path.read_text(encoding='utf8'))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError('{} is missing from {}'.format(name, path))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    paging = CONFIG['paging']
    assert paging['initial_items'] == paging['increment_items'] == assignment(PROVIDER / 'paging.py', 'BATCH')
    assert paging['max_parallel_requests'] == assignment(PROVIDER / 'core.py', 'MAX_WORKERS')
    for name, budget in CONFIG['latency'].items():
        assert 0 < budget['target'] <= budget['maximum'], name
    assert CONFIG['release']['previous_versions_kept'] == 3
    assert assignment(ROOT / 'build.py', 'INSTALLER_HISTORY') == 3
    assert CONFIG['release']['explicit_user_approval_required'] is True
    assert CONFIG['release']['device_evidence_required'] is True
    discovered = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    test_count = discovered.countTestCases()
    assert test_count >= CONFIG['release']['minimum_unit_tests'], (
        '{} tests is below the required {}'.format(
            test_count, CONFIG['release']['minimum_unit_tests']))

    assert EVIDENCE['result'] == 'pass'
    assert EVIDENCE['paging']['initial_items'] == paging['initial_items']
    assert EVIDENCE['paging']['increment_items'] == paging['increment_items']
    for relative, expected in EVIDENCE['source_sha256'].items():
        assert digest(ROOT / relative) == expected, relative
    for assertion, value in EVIDENCE['assertions'].items():
        assert value is True, assertion
    limits = CONFIG['latency']
    warnings = []
    for metric, value in EVIDENCE['measured'].items():
        assert value <= limits[metric]['maximum'], '{}={} exceeds {}'.format(metric, value, limits[metric]['maximum'])
        if value > limits[metric]['target']:
            warnings.append('{}={} (target {})'.format(metric, value, limits[metric]['target']))
    for warning in warnings:
        print('WARNING: ' + warning)
    print('Quality contract passed: {} tests, {} source files, {} measured latencies, {} target warnings'.format(
        test_count, len(EVIDENCE['source_sha256']), len(EVIDENCE['measured']), len(warnings)))


if __name__ == '__main__':
    main()
