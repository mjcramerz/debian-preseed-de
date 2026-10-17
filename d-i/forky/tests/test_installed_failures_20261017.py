"""Installed-log regressions; execute only in the prepared disposable image.

Fake delegates verify imports and result propagation. The audit-header fixture
models routing only; it is not native CrowdSec or systemd acceptance.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': '/nonexistent'}


class SoftwareNotifierImportTests(unittest.TestCase):
    def test_entrypoint_only_loads_notifier_and_propagates_its_result(self):
        source = (TARGET / 'usr/local/libexec/apt-repo-local-software-notify').read_text()
        with tempfile.TemporaryDirectory(prefix='notifier-import-') as temporary:
            root = Path(temporary)
            library = root / 'lib'
            servicing = library / 'APTRepoLocal/Servicing'
            servicing.mkdir(parents=True)
            (servicing / 'Notifier.pm').write_text('''package APTRepoLocal::Servicing::Notifier;
use strict;
use warnings;
sub new { bless {}, shift }
sub run { print "notifier-ran\\n"; return 0 + $ENV{FIXTURE_STATUS}; }
1;
''')
            # Fail at import time if the entrypoint pulls privileged updater
            # modules back into the confined desktop notifier.
            for name in ('CLI', 'ChatGPT', 'Repository'):
                (servicing / f'{name}.pm').write_text('BEGIN { die "forbidden updater import\\n"; }\n')
            installed_library = "use lib '/usr/local/lib/perl5/site_perl/apt-repo-local';"
            self.assertEqual(source.count(installed_library), 1)
            wrapper = root / 'notify'
            wrapper.write_text(source.replace(installed_library, f'use lib q{{{library}}};'))
            for status in (0, 17):
                result = subprocess.run(['/usr/bin/perl', str(wrapper)], cwd=root,
                    env={**ENV, 'FIXTURE_STATUS': str(status)}, stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(result.stdout, 'notifier-ran\n')
            result = subprocess.run(['/usr/bin/perl', str(wrapper), 'unexpected'], cwd=root,
                env={**ENV, 'FIXTURE_STATUS': '0'}, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn('usage: apt-repo-local-software-notify', result.stderr)

    def test_real_notifier_dependency_closure_excludes_updater_runtime(self):
        with tempfile.TemporaryDirectory(prefix='notifier-modules-') as temporary:
            root = Path(temporary)
            modules = root / 'APTRepoLocal/Servicing'
            modules.mkdir(parents=True)
            source = TARGET / 'usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing'
            for name in ('Notifier', 'Atomic', 'ArtifactLimits'):
                path = source / (name + ('.pm.tmpl' if name == 'Notifier' else '.pm'))
                (modules / f'{name}.pm').write_bytes(path.read_bytes())
            program = '''use strict; use warnings;
use APTRepoLocal::Servicing::Notifier;
APTRepoLocal::Servicing::Notifier->new();
for my $name (keys %INC) {
  die "updater dependency imported\\n" if $name =~ m{\\A(?:Managed/|APTRepoLocal/Servicing/(?:CLI|ChatGPT|Repository)\\.pm)};
}
print "notifier-loaded\\n";
'''
            result = subprocess.run(['/usr/bin/perl', '-I', str(root), '-e', program],
                cwd=root, env=ENV, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'notifier-loaded\n')


class SecondbootImageVerificationTests(unittest.TestCase):
    def verify(self, images, failure='none'):
        source = (FORKY / 'scripts/firstboot/assets/var/lib/firstboot/bin/secondboot-cleanup').read_text()
        start = source.index('    verified_images=0\n')
        block = source[start:source.index('\n  fi\n  # The final PCR-bound token', start)]
        with tempfile.TemporaryDirectory(prefix='secondboot-images-') as temporary:
            root = Path(temporary)
            boot, runtime = root / 'boot', root / 'run'
            boot.mkdir()
            runtime.mkdir()
            for name in images:
                self.assertRegex(name, r'\Ainitrd\.img-[A-Za-z0-9.-]+\Z')
                (boot / name).write_text('fixture bytes\n')
            pending = root / 'pending'
            pending.write_text('verification pending\n')
            calls = root / 'calls'
            listing = root / 'lsinitramfs'
            listing.write_text('''#!/bin/dash
printf '%s\\n' "${1##*/}" >>"$CALLS"
case "$1" in *.sig) exit 97 ;; esac
case "$FAILURE" in
  corrupt) exit 2 ;;
  hook) printf '%s\\n' 'scripts/init-top/90-installer-health' ;;
  *) printf '%s\\n' 'scripts/init-top/udev' ;;
esac
''')
            listing.chmod(0o700)
            block = block.replace('/boot/initrd.img-*', shlex.quote(str(boot)) + '/initrd.img-*')
            block = block.replace('/run/secondboot-initramfs', str(runtime / 'secondboot-initramfs'))
            block = block.replace('/usr/bin/lsinitramfs', shlex.quote(str(listing)))
            result = subprocess.run(['/bin/dash', '-eu', '-c', block + '\nrm -- "$PENDING"\n'],
                cwd=root, env={**ENV, 'CALLS': str(calls), 'FAILURE': failure, 'PENDING': str(pending)},
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
            return result, calls.read_text().splitlines() if calls.exists() else [], pending.exists()

    def test_detached_signatures_are_never_read_as_initramfs(self):
        result, calls, pending = self.verify(('initrd.img-7.2.11', 'initrd.img-7.2.11.sig'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['initrd.img-7.2.11'])
        self.assertFalse(pending)

    def test_real_image_failure_or_remaining_hook_retains_pending_work(self):
        for failure in ('corrupt', 'hook'):
            with self.subTest(failure=failure):
                result, calls, pending = self.verify(('initrd.img-7.2.11', 'initrd.img-7.2.11.sig'), failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, ['initrd.img-7.2.11'])
                self.assertTrue(pending)

    def test_signatures_alone_do_not_count_as_verified_images(self):
        result, calls, pending = self.verify(('initrd.img-7.2.11.sig',))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertTrue(pending)
        self.assertIn('no rebuilt initramfs was available', result.stderr)


class AuditDaemonRoutingSpecificationTests(unittest.TestCase):
    def test_header_guard_preserves_native_records_and_separates_notices(self):
        source = (TARGET / 'etc/crowdsec/parsers/s01-parse/00-auditd-daemon.yaml').read_text()
        expression = json.loads(next(line.removeprefix('filter: ') for line in source.splitlines()
                                     if line.startswith('filter: ')))
        match = re.fullmatch(r"evt\.Parsed\.program == 'auditd' and not \(evt\.Parsed\.message matches '([^']+)'\)", expression)
        self.assertIsNotNone(match)
        header = re.compile(match[1])
        for record_type in ('SYSCALL', 'AVC', '1400', 'ANOM_ABEND', 'USER_CMD', 'UNKNOWN[1700]'):
            for prefix in ('', 'node=fixture '):
                with self.subTest(record_type=record_type, prefix=prefix):
                    self.assertIsNotNone(header.match(f'{prefix}type={record_type} msg=audit(1.2:3): uid=1000'))
        for notice in ('Audit daemon rotating log files', 'No space left on device', '', 'auditd started'):
            self.assertIsNone(header.match(notice))
        self.assertIn('onsuccess: next_stage\n', source)
        self.assertIn('    value: auditd-daemon\n', source)


if __name__ == '__main__':
    unittest.main()
