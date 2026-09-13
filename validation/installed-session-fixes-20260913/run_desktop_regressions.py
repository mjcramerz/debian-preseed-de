#!/usr/bin/env python3
"""Run desktop regressions; explicitly omit two unavailable historical inputs.

No current incident file is substituted for a different historical incident.
No compiler or live system service is invoked by this selection.
"""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'd-i/forky/tests'))
MISSING = {
    'test_installed_failures_20260911.RecordedAppArmorCoverageTests.test_fixture_exactly_matches_the_supplied_raw_audit_events': 'todo/managed/apparmor/apparmor.log is absent from the original ZIP',
    'test_desktop_sandbox.InstalledFailureRegressionTests.test_apparmor_complain_incident_is_fully_mapped': 'todo/apparmor.log is absent from the original ZIP',
}
names = ['test_desktop_sandbox', 'test_installation_fixes_20260912',
         'test_installed_failures_20260911', 'test_dbus_broker', 'test_process_capture']
def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item
selected = []
for case in cases(unittest.defaultTestLoader.loadTestsFromNames(names)):
    if case.id() in MISSING:
        print('EXCLUDED: ' + case.id() + ': ' + MISSING[case.id()], flush=True)
    else:
        selected.append(case)
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
sys.exit(not result.wasSuccessful())
