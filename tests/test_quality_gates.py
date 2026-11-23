"""The release policy is executable, not only documentation."""
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class QualityGateTests(unittest.TestCase):
    def test_quality_contract_and_device_evidence(self):
        spec = importlib.util.spec_from_file_location('quality_contract', ROOT / 'scripts/check_quality_gates.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.main()

    def test_every_budget_has_target_and_hard_limit(self):
        config = json.loads((ROOT / 'quality-gates.json').read_text(encoding='utf8'))
        self.assertGreaterEqual(len(config['latency']), 10)
        for name, budget in config['latency'].items():
            with self.subTest(name=name):
                self.assertGreater(budget['target'], 0)
                self.assertGreaterEqual(budget['maximum'], budget['target'])

    def test_minimum_test_count_is_not_silently_reduced(self):
        config = json.loads((ROOT / 'quality-gates.json').read_text(encoding='utf8'))
        discovered = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
        self.assertGreaterEqual(discovered.countTestCases(), config['release']['minimum_unit_tests'])


if __name__ == '__main__':
    unittest.main()
