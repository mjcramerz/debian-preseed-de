#!/usr/bin/env python3
"""Record actual unittest outcomes; never convert skips or failures into passes."""
from pathlib import Path
import argparse
import json
import sys
import time
import unittest

parser = argparse.ArgumentParser()
parser.add_argument('--suite', choices=('full', 'tools', 'focused', 'independence'), required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
output = Path(__file__).resolve().parent
start = root / ('tools/tests' if args.suite == 'tools' else 'd-i/forky/tests')
sys.path.insert(0, str(start))
loader = unittest.TestLoader()
if args.suite in ('focused', 'independence'):
    names = ['test_profile_pin_independence_20260920']
    if args.suite == 'focused':
        names += ['test_resctl_bench_20260916', 'test_resctl_bench_release_20260917',
                  'test_resctl_bench_docs_20260917', 'test_resctl_bench_noexec_20260917',
                  'test_tomat_release_pins_20260920', 'test_systemd_resource_policy',
                  'test_repository_integrity']
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in names)
else:
    suite = loader.discover(str(start), pattern='test_*.py')
begin = time.monotonic()
with (output / (args.suite + '-tests.log')).open('w') as log:
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
summary = {
    'suite': args.suite, 'tests_run': result.testsRun,
    'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
    'failures': [{'test': str(test), 'traceback': text} for test, text in result.failures],
    'errors': [{'test': str(test), 'traceback': text} for test, text in result.errors],
    'skipped': [{'test': str(test), 'reason': reason} for test, reason in result.skipped],
    'seconds': round(time.monotonic() - begin, 3),
    'python': sys.version, 'python_executable': sys.executable,
}
(output / (args.suite + '-tests.json')).write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps({k: len(v) if isinstance(v, list) else v for k, v in summary.items()}, indent=2))
sys.exit(0 if result.wasSuccessful() else 1)
