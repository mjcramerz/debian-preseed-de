"""Run non-destructive selected source regressions; no native compilation."""
import json
from pathlib import Path
import sys
import unittest

root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2])
sys.path.insert(0, str(root / 'd-i/forky/tests'))
modules = ['test_installation_fixes_20260912', 'test_installed_failures_20260911',
           'test_lifecycle', 'test_repository_integrity', 'test_installer_hardening',
           'test_dbus_broker', 'test_desktop_sandbox']
if (root / 'd-i/forky/tests/test_power_keyboard_20260913.py').exists():
    modules.append('test_power_keyboard_20260913')
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
output.write_text(json.dumps({
    'modules': modules, 'tests_run': result.testsRun,
    'failures': [{'test': t.id(), 'traceback': detail} for t, detail in result.failures],
    'errors': [{'test': t.id(), 'traceback': detail} for t, detail in result.errors],
    'skipped': [{'test': t.id(), 'reason': reason} for t, reason in result.skipped],
    'successful': result.wasSuccessful(),
}, indent=2) + '\n')
sys.exit(not result.wasSuccessful())
