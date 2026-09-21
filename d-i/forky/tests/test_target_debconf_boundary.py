"""Late-command regression: real d-i shell clients and a private frontend.

Two disposable chroots, no devices, mounts, service starts or package changes.
The Debian in-target/confmodule/debconf-get clients are real; chroot-setup is an
explicitly reduced protocol fixture and log-output a descriptor-preserving shim.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

from debconf_fixture import DebconfSandbox, PrivateDebconf, ProtocolSession
from test_bootstrap_portability import InstallerShellSandbox

SEED = Path(__file__).resolve().parents[1]
FIXTURE = SEED / 'tests/fixtures/debian-in-target'
Q = shlex.quote
SETUP = '''
. /tmp/lifecycle.sh
installer_lifecycle_arm late
# Individual command status is checked by the Python test, not a fatal hold.
trap - 0 HUP INT TERM
. /tmp/debconf.sh
. /tmp/target.sh
installer_runtime_temp_log_path() { printf '/tmp/%s\\n' "$1"; }
installer_info() { :; }
installer_error() { :; }
installer_warn() { :; }
target_log_command_start() { TARGET_LOG_CATEGORY=late; TARGET_LOG_STAGE=late_command; }
target_log_command_complete() { :; }
target_log_command_failure() { :; }
target_log_should_emit() { return 0; }
installer_log_target_command_output() { :; }
installer_append_log_category() { :; }
target_record_command_failure() { printf '%s\\n' "$2" >/tmp/target-failure; }
filter_in_target_noise() { cat; }
'''

class TargetDebconfBoundaryTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() != 0 or not shutil.which('busybox'):
            self.skipTest('requires root/CAP_SYS_CHROOT and BusyBox for isolated protocol tests')
        self.tmp = tempfile.TemporaryDirectory(prefix='target-debconf-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.box = DebconfSandbox(self.base/'installer')
        self.root = self.box.root
        self.target = InstallerShellSandbox(self.root/'target')
        self.backend = PrivateDebconf(self.base/'private-db')
        self.addCleanup(self.backend.close)
        for question, value in [('mirror/protocol', 'http'),
                                ('mirror/http/proxy', 'http://proxy.fixture.invalid:3142'),
                                ('debconf/priority', 'critical'),
                                ('debian-installer/locale', 'invalid_DI.UTF-8')]:
            reply = self.backend.exchange(f'REGISTER debian-installer/dummy {question}'.encode())
            self.assertEqual(reply.split(b' ', 1)[0], b'0', reply)
            self.assertEqual(self.backend.exchange(f'SET {question} {value}'.encode()).split(b' ', 1)[0], b'0')
        for name in ('lifecycle', 'target', 'debconf'):
            shutil.copyfile(SEED/f'scripts/common/{name}.sh', self.root/f'tmp/{name}.sh')
        for src, dest in [('in-target', 'bin/in-target'), ('debconf-get', 'bin/debconf-get'),
                          ('chroot-setup-protocol.sh', 'lib/chroot-setup.sh')]:
            self.write(dest, (FIXTURE/src).read_text())
        self.write('bin/log-output', '#!/bin/sh\n[ "$1" != -t ] || shift 2\n[ "$1" != --pass-stdout ] || shift\n"$@"\n')
        self.box.copy_executable(Path(shutil.which('chroot')), '/bin/chroot')
        self.target.copy_executable(Path('/usr/bin/env'), '/usr/bin/env')
        self.box.copy_executable(Path('/bin/dash'), '/bin/dash')
        self.target.copy_executable(Path('/bin/dash'), '/bin/dash')
        self.write('target/bin/probe', '''#!/bin/sh
printf 'target-started\\n' >>/tmp/target-progress
printf '%s\\n' "$@"
''')

    def write(self, path, text):
        dest = self.root/path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
        dest.chmod(0o755)

    def run_code(self, code, *, setup=SETUP, raw=False, timeout=8, env=None):
        session = ProtocolSession(self.box, self.backend, setup + '\n' + code, raw=raw, env=env)
        try:
            result, timed_out = session.finish(timeout=timeout)
            return result, timed_out, list(session.requests)
        finally:
            session.close()

    def assert_ok(self, code, **kw):
        result, timed_out, requests = self.run_code(code, **kw)
        self.assertFalse(timed_out, result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'GET mirror/protocol', requests)
        self.assertIn(b'GET mirror/http/proxy', requests)
        self.assertIn(b'GET debconf/priority', requests)
        return result, requests

    def progress(self):
        path = self.root/'var/log/target-protocol-progress'
        return path.read_text().splitlines() if path.exists() else []

    def test_upstream_fixture_sizes_and_local_checksums(self):
        self.assertEqual((FIXTURE/'in-target').stat().st_size, 498)
        self.assertEqual((FIXTURE/'debconf-get').stat().st_size, 111)
        for line in (FIXTURE/'SHA256SUMS').read_text().splitlines():
            digest, path = line.split('  ', 1)
            self.assertEqual(hashlib.sha256((FIXTURE/path).read_bytes()).hexdigest(), digest)

    def test_negative_control_unsetting_redir_reproduces_reported_hang(self):
        path = self.root/'tmp/target.sh'
        text = path.read_text()
        anchor = '        in-target --pass-stdout /usr/bin/env '
        self.assertEqual(text.count(anchor), 1)
        path.write_text(text.replace(anchor, '        unset DEBCONF_REDIR\n'+anchor))
        result, timed_out, requests = self.run_code('target_exec /bin/probe never', timeout=2)
        self.assertTrue(timed_out, result.stderr)
        self.assertEqual(self.progress(), ['setup-entered'])
        self.assertEqual(requests, [])
        self.assertFalse((self.root/'target/tmp/target-progress').exists())

    def test_direct_native_style_call_completes_under_busybox_and_dash(self):
        for shell in ('busybox', 'dash'):
            with self.subTest(shell=shell):
                for box in (self.box, self.target):
                    (box.root/'bin/sh').unlink()
                    (box.root/'bin/sh').symlink_to(shell)
                result, _ = self.assert_ok('target_exec /bin/probe reached')
                self.assertEqual(result.stdout, 'reached\n')
                self.assertEqual(self.progress()[-3:], ['setup-entered', 'setup-completed', 'cleanup-completed'])

    def test_raw_frontend_is_initialized_before_saved_input_and_capture(self):
        result, _ = self.assert_ok('target_exec /bin/probe raw', raw=True)
        self.assertEqual(result.stdout, 'raw\n')

    def test_installer_state_is_preserved_but_target_state_is_sanitized(self):
        env = {'DEBCONF_DB_REPLACE':'installer-db', 'DEBCONF_SYSTEMRC':'/installer-only.conf',
               'DEBCONF_PIPE':'/installer-only.sock', 'DEBCONF_DEBUG':'', 'LANG':'C', 'LC_ALL':'C'}
        result, requests = self.assert_ok('''target_exec /usr/bin/env -0
[ "$DEBCONF_REDIR" = 1 ] && [ "$DEBCONF_USE_CDEBCONF" = 1 ] &&
[ "$DEBIAN_HAS_FRONTEND" = 1 ] && [ "$INSTALLER_DEBCONF_STDIN_SAVED" = 1 ]
''', env=env)
        child = dict(line.split('=', 1) for line in result.stdout.split('\0') if '=' in line)
        for key in ('DEBCONF_DB_REPLACE', 'DEBCONF_SYSTEMRC', 'DEBCONF_PIPE',
                    'DEBCONF_REDIR', 'DEBCONF_USE_CDEBCONF', 'DEBIAN_HAS_FRONTEND',
                    'INSTALLER_DEBCONF_STDIN_SAVED'):
            self.assertNotIn(key, child)
        self.assertEqual(child['DEBIAN_FRONTEND'], 'passthrough')
        self.assertEqual(child['DEBCONF_READFD'], '8')
        self.assertEqual(child['DEBCONF_WRITEFD'], '3')
        self.assertEqual(child['LANG'], 'C.UTF-8')
        self.assertEqual(child['LC_ALL'], 'C.UTF-8')
        self.assertEqual(child['http_proxy'], 'http://proxy.fixture.invalid:3142')
        self.assertNotIn(b'GET debian-installer/locale', requests)

    def test_all_noninteractive_wrappers_keep_protocol_and_null_data_input(self):
        self.write('target/bin/null-stdin', '#!/bin/sh\nif IFS= read -r line; then exit 81; fi\nprintf "null-data-ok\\n"\n')
        for wrapper in ('run_in_target', 'attempt_in_target', 'run_in_target_quiet',
                        'capture_in_target', 'test_in_target'):
            with self.subTest(wrapper=wrapper):
                args = '/bin/null-stdin' if wrapper == 'test_in_target' else 'fixture /bin/null-stdin'
                self.assert_ok(f'{wrapper} {args}')
                self.assertEqual(self.progress()[-1], 'cleanup-completed')

    def test_capture_does_not_mix_protocol_requests_with_stdout(self):
        result, _ = self.assert_ok('value=$(capture_in_target fixture /bin/probe captured); printf "<%s>\\n" "$value"')
        self.assertEqual(result.stdout, '<captured>\n')

    def test_explicit_data_stdin_and_literal_arguments_survive(self):
        self.write('tmp/data', 'stdin data ; $HOME *\n')
        literal = 'argument ; $HOME * spaced'
        command = "target_exec /bin/sh -c 'IFS= read -r line; printf \"%s|%s\\n\" \"$line\" \"$1\"' sh " + Q(literal) + ' </tmp/data'
        result, _ = self.assert_ok(command)
        self.assertEqual(result.stdout, 'stdin data ; $HOME *|'+literal+'\n')

    def test_pipe_data_stdin_survives(self):
        result, _ = self.assert_ok("printf 'pipe-data\\n' | target_exec /bin/cat")
        self.assertEqual(result.stdout, 'pipe-data\n')

    def test_child_can_query_passthrough_without_reading_data_stdin(self):
        self.write('target/bin/protocol-probe', '''#!/bin/sh
[ "$DEBIAN_FRONTEND:$DEBCONF_READFD:$DEBCONF_WRITEFD" = passthrough:8:3 ] || exit 81
if IFS= read -r data; then exit 82; fi
printf 'GET mirror/protocol\\n' >&3
IFS= read -r reply <&8 || exit 83
[ "$reply" = '0 http' ] || exit 84
if ( : <&9 ) 2>/dev/null; then exit 85; fi
printf 'passthrough-ok\\n'
''')
        result, requests = self.assert_ok('capture_in_target fixture /bin/protocol-probe')
        self.assertEqual(result.stdout, 'passthrough-ok\n')
        self.assertEqual(requests.count(b'GET mirror/protocol'), 2)

    def test_command_failure_keeps_exit_status_and_runs_cleanup(self):
        for command in ('target_exec /bin/sh -c "exit 37"',
                        'attempt_in_target fixture /bin/sh -c "exit 37"',
                        'run_in_target fixture /bin/sh -c "exit 37"',
                        'capture_in_target fixture /bin/sh -c "exit 37"'):
            with self.subTest(command=command):
                result, timed_out, _ = self.run_code(command)
                self.assertFalse(timed_out, result.stderr)
                self.assertEqual(result.returncode, 37, result.stderr)
                self.assertEqual(self.progress()[-1], 'cleanup-completed')

    def test_phase_snapshot_survives_nested_helpers_and_log_pipeline(self):
        self.write('tmp/helper', '#!/bin/sh\n. /tmp/target.sh\ntarget_exec /bin/probe helper </dev/null\n')
        code = '''
installer_run_supervised /bin/sh -c '/tmp/helper </dev/null' | cat
installer_run_bounded 5 /tmp/helper </dev/null
'''
        result, _ = self.assert_ok(code)
        self.assertEqual(result.stdout, 'helper\nhelper\n')

    def test_record_loop_does_not_feed_records_to_debconf_or_lose_rows(self):
        self.write('tmp/rows', 'first\nsecond\n')
        result, requests = self.assert_ok('''while IFS= read -r row; do
value=$(installer_debconf_request GET mirror/protocol) || exit "$?"
[ "$value" = http ] || exit 81
target_exec /bin/probe "$row" </dev/null || exit "$?"
done </tmp/rows
''')
        self.assertEqual(result.stdout, 'first\nsecond\n')
        self.assertEqual(requests.count(b'GET mirror/protocol'), 4)

    def test_answer_publication_uses_protocol_not_redirected_stdin(self):
        self.write('tmp/answers', 'd-i fixture/late string value with spaces\n')
        result, timed_out, requests = self.run_code('installer_debconf_apply_file /tmp/answers </dev/null')
        self.assertFalse(timed_out, result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(requests)
        self.assertEqual(self.backend.value('fixture/late'), 'value with spaces')

    def test_parent_fd9_and_protocol_are_unchanged_after_target_call(self):
        self.write('tmp/parent-data', 'parent-fd9\n')
        result, _ = self.assert_ok('''exec 9</tmp/parent-data
target_exec /bin/probe child </dev/null
IFS= read -r line <&9
printf '%s\\n' "$line"
installer_debconf_request GET mirror/protocol
''')
        self.assertEqual(result.stdout, 'child\nparent-fd9\nhttp\n')

    def test_missing_saved_descriptor_fails_before_bridge_or_protocol_write(self):
        result, timed_out, requests = self.run_code('exec 8<&-; target_exec /bin/probe never')
        self.assertFalse(timed_out, result.stderr)
        self.assertEqual(result.returncode, 125)
        self.assertIn('frontend descriptors are not initialized', result.stderr)
        self.assertFalse(self.progress())
        self.assertEqual(requests, [])

    def test_missing_protocol_write_descriptor_fails_before_bridge(self):
        result, timed_out, requests = self.run_code('exec 3>&-; target_exec /bin/probe never')
        self.assertFalse(timed_out, result.stderr)
        self.assertEqual(result.returncode, 125)
        self.assertFalse(self.progress())
        self.assertEqual(requests, [])

    def test_unarmed_frontend_is_rejected_instead_of_opening_second_writer(self):
        result, timed_out, requests = self.run_code('target_exec /bin/probe never', setup='. /tmp/target.sh')
        self.assertFalse(timed_out, result.stderr)
        self.assertEqual(result.returncode, 125)
        self.assertFalse(self.progress())
        self.assertEqual(requests, [])

    def test_snapshot_collision_is_not_silently_overwritten(self):
        result, timed_out, requests = self.run_code('''
. /tmp/lifecycle.sh
installer_lifecycle_abort() { printf '%s\\n' "$3" >&2; exit "$1"; }
exec 8</dev/null
installer_lifecycle_arm late
''', setup='')
        self.assertFalse(timed_out, result.stderr)
        self.assertEqual(result.returncode, 125)
        self.assertIn('already in use', result.stderr)
        self.assertEqual(requests, [])

    def test_installed_perl_passthrough_frontend_reads_saved_descriptor(self):
        perl = Path(shutil.which('perl') or '/unavailable')
        if not perl.is_file() or not Path('/usr/share/perl5/Debconf').is_dir():
            self.skipTest('installed Perl Debconf frontend unavailable')
        self.target.copy_executable(perl, '/usr/bin/perl')
        self.target.copy_executable(Path('/usr/bin/locale'), '/usr/bin/locale')
        paths = subprocess.run([str(perl), '-MConfig', '-e',
                                'print "$Config{privlibexp}\\n$Config{archlibexp}\\n$Config{vendorarchexp}\\n";'],
                               capture_output=True, text=True, check=True).stdout.splitlines()
        paths.extend(['/usr/lib/x86_64-linux-gnu/perl-base', '/usr/share/perl5/Debconf',
                      '/usr/share/perl5/Text'])
        for name in dict.fromkeys(paths):
            source = Path(name)
            if source.is_dir():
                shutil.copytree(source, self.target.root/name.lstrip('/'), dirs_exist_ok=True)
        self.write('target/bin/perl-passthrough-probe', '''#!/usr/bin/perl
use strict;
use warnings;
use Debconf::Config;
use Debconf::FrontEnd::Passthrough;
my $frontend = Debconf::FrontEnd::Passthrough->new;
die "data stdin is not closed" if defined(<STDIN>);
my ($status, $value) = $frontend->talk_with_timeout(2, 'GET', 'mirror/protocol');
die "passthrough failed" unless defined($status) && $status eq '0' && $value eq 'http';
print "perl-passthrough-ok\\n";
''')
        result, _ = self.assert_ok('capture_in_target fixture /bin/perl-passthrough-probe')
        self.assertEqual(result.stdout, 'perl-passthrough-ok\n')

    def test_enabled_profile_native_iocost_transaction_through_real_bridge(self):
        from test_iocost_20260919 import ASSETS, STOCK_NATIVE, profile
        for binary in ('/usr/bin/systemd-hwdb', '/usr/lib/udev/iocost'):
            if not Path(binary).is_file():
                self.skipTest('native systemd IOCost tools unavailable')
            (self.target.root/binary.lstrip('/')).parent.mkdir(parents=True, exist_ok=True)
            self.target.copy_executable(Path(binary), binary)
        for source, dest in [('scripts/common/lib.sh', '/tmp/lib.sh'),
                             ('scripts/common/source.sh', '/tmp/source.sh'),
                             ('scripts/late/target-assets.sh', '/tmp/target-assets.sh'),
                             ('scripts/late/iocost.sh', '/tmp/iocost.sh')]:
            self.write(dest.lstrip('/'), (SEED/source).read_text())
        for asset in ASSETS:
            path = 'hooks/target/'+asset+'.tmpl'
            self.write('seed/'+path, (SEED/path).read_text())
        defaults = self.target.root/'etc/udev/iocost.conf'
        defaults.parent.mkdir(parents=True, exist_ok=True)
        defaults.write_bytes(STOCK_NATIVE.read_bytes())
        defaults.chmod(0o644)
        # The original dual-disk profile disables calibration; use the
        # enabled single-disk policy to exercise a real target transaction.
        env = profile('btrfs-de-flex')
        self.write('seed/repo.env', (SEED/'repo.env').read_text())
        env.update(INSTALLER_SOURCE_LIBRARY='/tmp/source.sh', INSTALLER_SOURCE_ROOT='/seed',
                   DIR_HOOKS_TARGET='hooks/target')
        result, requests = self.assert_ok('''
. /tmp/lib.sh
. /tmp/target-assets.sh
. /tmp/iocost.sh
fetch_hook() { cp -- "/seed/$1" "$2"; }
stage_target_iocost
''', env=env, timeout=15)
        self.assertGreaterEqual(requests.count(b'GET mirror/protocol'), 4)
        self.assertTrue((self.target.root/'etc/udev/hwdb.bin').is_file())
        for asset in ASSETS:
            self.assertTrue((self.target.root/asset).is_file(), asset)
        self.assertIn('TargetSolution=isolated-bandwidth', defaults.read_text())
        self.assertFalse(list(self.target.root.glob('.installer-iocost*')))

    def test_real_native_hwdb_enters_target_without_deadlock(self):
        binary = Path('/usr/bin/systemd-hwdb')
        if not binary.exists():
            self.skipTest('native systemd-hwdb is not installed in validation environment')
        self.target.copy_executable(binary, '/usr/bin/systemd-hwdb')
        shutil.copyfile(SEED/'scripts/late/iocost.sh', self.root/'tmp/iocost.sh')
        result, _ = self.assert_ok('. /tmp/iocost.sh; iocost_native_hwdb --version')
        self.assertIn('systemd', result.stdout)

if __name__ == '__main__':
    unittest.main()
