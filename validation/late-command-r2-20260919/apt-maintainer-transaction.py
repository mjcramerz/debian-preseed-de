#!/usr/bin/env python3
"""Supplemental native target frontend/maintainer round-trip in disposable chroots.
Run from this repository's root; no host configuration or databases are modified.
"""
from pathlib import Path
import json
import shutil
import sys
import subprocess

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
    # Real apt/dpkg; install only one generated, dependency-free test package
    # inside the disposable target chroot. Never touch host package state.
    for binary in ('/usr/bin/apt-get', '/usr/bin/dpkg', '/usr/bin/dpkg-deb',
                   '/usr/bin/dpkg-split', '/usr/bin/diff', '/usr/bin/tar', '/sbin/ldconfig',
                   '/sbin/start-stop-daemon', '/usr/lib/apt/methods/file',
                   '/usr/lib/apt/methods/store', '/usr/lib/apt/methods/copy'):
        destination = case.target.root/binary.lstrip('/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            destination.unlink()
        case.target.copy_executable(Path(binary), binary)
    shutil.copytree('/usr/share/dpkg', case.target.root/'usr/share/dpkg', dirs_exist_ok=True)
    for directory in ('var/lib/dpkg/updates', 'var/lib/apt/lists/partial',
                      'var/cache/apt/archives/partial', 'var/log/apt', 'etc/apt/apt.conf.d',
                      'etc/apt/sources.list.d', 'etc/apt/preferences.d'):
        (case.target.root/directory).mkdir(parents=True, exist_ok=True)
    (case.target.root/'var/lib/dpkg/status').write_text('')
    (case.target.root/'etc/apt/sources.list').write_text('')
    case.write('target/etc/passwd', 'root:x:0:0:root:/root:/bin/sh\n')
    stage=case.base/'package'
    (stage/'DEBIAN').mkdir(parents=True)
    (stage/'DEBIAN/control').write_text('Package: private-bridge-fixture\nVersion: 1.0\nArchitecture: all\nMaintainer: Test <test@example.invalid>\nDescription: Disposable target boundary test\n')
    shutil.copyfile(case.target.root/'bin/maintainer-probe.templates', stage/'DEBIAN/templates')
    shutil.copyfile(case.target.root/'bin/maintainer-probe', stage/'DEBIAN/postinst')
    (stage/'DEBIAN/postinst').chmod(0o755)
    package=case.target.root/'tmp/private-bridge-fixture.deb'
    subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(stage), str(package)],
                   capture_output=True, text=True, check=True, timeout=10)
    result, requests = case.assert_ok('capture_in_target fixture /usr/bin/env DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true /usr/bin/apt-get -y -o DPkg::Use-Pty=0 -o APT::Sandbox::User=root --no-install-recommends install /tmp/private-bridge-fixture.deb', timeout=20)
    case.assertIn('maintainer-frontend-ok', result.stdout+result.stderr)
    status=(case.target.root/'var/lib/dpkg/status').read_text()
    case.assertIn('Status: install ok installed', status)
    saved=(case.target.root/'tmp/target-config.dat').read_text()
    case.assertIn('Value: changed', saved)
    print(json.dumps({'success': True, 'target_stdout': result.stdout,
                      'target_stderr': result.stderr,
                      'frontend_requests': [request.decode('utf-8') for request in requests],
                      'fixture_package_installed': True, 'target_database_saved': True,
                      'scope': 'Native apt-get, dpkg and Perl Debconf configure one generated dependency-free test package in a disposable target chroot; explicit noninteractive invocation matches repository package calls. No host packages or production packages are installed.'}, indent=2))
finally:
    case.doCleanups()
