#!/usr/bin/env python3
"""Supplemental native target frontend/maintainer round-trip in disposable chroots.
Run from this repository's root; no host configuration or databases are modified.
"""
from pathlib import Path
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'d-i/forky/tests'))
from test_target_debconf_boundary import TargetDebconfBoundaryTests

case = TargetDebconfBoundaryTests()
case.setUp()
try:
    # Provision native Perl libraries and first verify the passthrough frontend.
    case.test_installed_perl_passthrough_frontend_reads_saved_descriptor()
    shutil.copytree('/usr/share/debconf', case.target.root/'usr/share/debconf', dirs_exist_ok=True)
    # The minimal chroot has libc but not its C.UTF-8 locale data by default.
    shutil.copytree('/usr/lib/locale/C.utf8', case.target.root/'usr/lib/locale/C.utf8', dirs_exist_ok=True)
    case.write('target/etc/debconf.conf', '''Config: config
Templates: templates

Name: config
Driver: File
Filename: /tmp/target-config.dat
Mode: 600

Name: templates
Driver: File
Filename: /tmp/target-templates.dat
Mode: 600
''')
    case.write('target/bin/maintainer-probe.templates', '''Template: fixture/target-value
Type: string
Default: staged
Description: Private target frontend test
 This is not an installed package.
''')
    case.write('target/bin/maintainer-probe', '''#!/bin/sh
set -eu
. /usr/share/debconf/confmodule
db_version 2.0
db_capb backup
db_get fixture/target-value
[ "$RET" = staged ]
db_set fixture/target-value changed
db_get fixture/target-value
[ "$RET" = changed ]
printf 'maintainer-frontend-ok\\n'
''')
    result, requests = case.assert_ok('capture_in_target fixture /usr/share/debconf/frontend /bin/maintainer-probe', timeout=10)
    # Native confmodule deliberately redirects ordinary stdout to stderr.
    case.assertIn('maintainer-frontend-ok', result.stderr)
    case.assertTrue(any(request.startswith(b'CAPB') for request in requests), requests)
    saved = (case.target.root/'tmp/target-config.dat').read_text()
    case.assertIn('Name: fixture/target-value', saved)
    case.assertIn('Value: changed', saved)
    print(json.dumps({'success': True, 'target_stdout': result.stdout,
                      'target_stderr': result.stderr,
                      'frontend_requests': [request.decode('utf-8') for request in requests],
                      'target_database_saved': True,
                      'scope': 'Native Perl debconf/frontend drives native target shell confmodule; private target File databases and private installer frontend; reduced chroot setup, not a booted installer.'}, indent=2))
finally:
    case.doCleanups()
