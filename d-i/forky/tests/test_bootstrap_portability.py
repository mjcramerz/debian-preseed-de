"""Execute the shipped bootstrap, including the shell used by nested scripts.

All downloads are loopback-only. The chroot contains no host disks, no real
/proc or /sys, no package manager and no destructive tools. It uses the installed
BusyBox binary with a restricted applet PATH, not an asserted busybox-udeb binary.
Failure waits are killed from the test parent, never by a production bypass.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import sys
import subprocess
import tempfile
import time
import unittest

from process_fixture import stop_test_tree, wait_file
from test_environment import skip_unless_loopback_inet, skip_unless_process_tree_visibility
from test_repository_transport import Endpoint, FORKY, RAW_PREFIX, SOURCE

LC = FORKY / 'scripts/common/lifecycle.sh'
Q = shlex.quote
BUSYBOX = shutil.which('busybox')
sys.path.insert(0, str(FORKY.parents[1] / 'tools'))
from check_preseeds import readback_commands
SHELLS = [('dash', ['/bin/dash'])]
if BUSYBOX:
    SHELLS.append(('busybox', [BUSYBOX, 'sh']))


def generated_commands() -> dict[str, str]:
    result = {}
    for line in (FORKY / 'preseed.cfg').read_text().splitlines():
        fields = line.split(None, 3)
        if len(fields) == 4 and fields[1].endswith('_command'):
            result[fields[1]] = fields[3]
    return result


class TimeoutPortabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='bootstrap-portability-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {**os.environ, 'INSTALLER_CMDLINE': '',
                    'INSTALLER_RUNTIME_DIR': str(self.root / 'runtime')}

    def run_shell(self, shell, code, *, env=None, timeout=15):
        command = [*shell, '-eu', '-c', f'. {Q(str(SOURCE))}; {code}']
        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env={**self.env, **(env or {})})
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_test_tree(p)
            self.fail('bootstrap helper did not terminate within its test budget')
        return subprocess.CompletedProcess(command, p.returncode, out, err)

    def test_busybox_runtime_is_required_not_silently_skipped(self):
        self.assertIsNotNone(BUSYBOX, 'install busybox to run the installer shell tests')

    def test_decimal_timeouts_normalize_without_octal_or_overflow(self):
        values = {'1': '1', '0001': '1', '08': '8', '09': '9',
                  '0180': '180', '00900': '900', '0' * 100 + '45': '45'}
        for name, shell in SHELLS:
            for value, expected in values.items():
                with self.subTest(shell=name, value=value):
                    result = self.run_shell(shell, 'installer_bounded_seconds ' + Q(value))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)

    def test_malformed_timeouts_fail_before_launching_a_child(self):
        values = ('', '0', '0000', '901', '100000000000000000000000000',
                  '-1', '+1', '1.5', '1s', '1 2', '1\n2', '1+1', '$(touch UNSAFE)')
        for name, shell in SHELLS:
            for value in values:
                with self.subTest(shell=name, value=value):
                    unsafe = self.root / 'UNSAFE'
                    result = self.run_shell(shell, f'installer_run_bounded {Q(value)} touch {Q(str(unsafe))}')
                    self.assertEqual(result.returncode, 125, result.stderr)
                    self.assertNotIn('arithmetic syntax', result.stderr)
                    self.assertFalse(unsafe.exists())

    @skip_unless_loopback_inet
    def test_reported_arithmetic_failure_is_removed_from_actual_fetch(self):
        web = Endpoint(FORKY)
        self.addCleanup(web.close)
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                dest = self.root / (name + '-seed.document')
                result = self.run_shell(shell,
                    f'source_http_get {Q(web.base + "/preseed.cfg")} {Q(str(dest))}',
                    env={'INSTALLER_FETCH_WALL_TIMEOUT': '0180', 'INSTALLER_FETCH_TIMEOUT': '09'})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(dest.read_bytes(), (FORKY / 'preseed.cfg').read_bytes())
                self.assertFalse(Path(str(dest) + '.fetch-error').exists())

    @skip_unless_loopback_inet
    def test_invalid_fetch_configuration_is_not_retried(self):
        web = Endpoint(FORKY)
        self.addCleanup(web.close)
        for name, shell in SHELLS:
            for variable in ('INSTALLER_FETCH_WALL_TIMEOUT', 'INSTALLER_FETCH_TIMEOUT'):
                with self.subTest(shell=name, variable=variable):
                    result = self.run_shell(shell,
                        f'source_http_get {Q(web.base + "/preseed.cfg")} {Q(str(self.root / "out"))}',
                        env={variable: 'one'})
                    self.assertEqual(result.returncode, 125, result.stderr)
                    self.assertIn(variable, result.stderr)
        self.assertEqual(sum(web.counts.values()), 0)

    def test_no_arithmetic_or_fractional_sleep_in_embedded_bootstrap(self):
        # This protects the generated copy, not just the readable implementation.
        for question, command in generated_commands().items():
            with self.subTest(question=question):
                body = shlex.split(command)[2]
                self.assertNotIn('$((', body)
                self.assertNotIn(r'\n', command)
                self.assertNotRegex(body, r'\bsleep\s+[0-9]+\.')
                self.assertIn('installer_bounded_seconds()', body)
                self.assertIn('for lc_interval in $lc_intervals', body)
        canonical = LC.read_text()
        for path in (SOURCE, FORKY / 'scripts/common/lib.sh'):
            embedded = path.read_text().split('# BEGIN EMBEDDED LIFECYCLE\n', 1)[1].split('# END EMBEDDED LIFECYCLE\n', 1)[0]
            self.assertEqual(embedded, canonical)

    def test_bounded_command_preserves_status_with_leading_zero_budget(self):
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                result = self.run_shell(shell, 'installer_run_bounded 0180 /bin/sh -c "exit 37"')
                self.assertEqual(result.returncode, 37, result.stderr)

    @skip_unless_process_tree_visibility
    def test_integer_only_sleep_and_no_optional_timeout_applet(self):
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                code = '''sleep() { case "$1" in *[!0-9]*) return 93;; esac; command sleep "$@"; }
stat() { return 94; }; setsid() { return 95; }; timeout() { return 96; }
installer_run_bounded 001 /bin/sh -c 'sleep 30'
'''
                started = time.monotonic()
                result = self.run_shell(shell, code)
                self.assertEqual(result.returncode, 124, result.stderr)
                self.assertLess(time.monotonic() - started, 6)

    @skip_unless_process_tree_visibility
    def test_timeout_stops_descendants_not_just_the_waiting_shell(self):
        for name, shell in SHELLS:
            with self.subTest(shell=name):
                unsafe = self.root / ('UNSAFE-' + name)
                command = f'(sleep 2; touch {Q(str(unsafe))}) & wait'
                result = self.run_shell(shell, f'installer_run_bounded 1 /bin/sh -c {Q(command)}')
                self.assertEqual(result.returncode, 124, result.stderr)
                time.sleep(1.2)
                self.assertFalse(unsafe.exists())

    def test_failed_counter_preparation_never_starts_a_child(self):
        for name, shell in SHELLS:
            unsafe = self.root / ('UNSAFE-' + name)
            result = self.run_shell(shell, f'seq() {{ return 75; }}; installer_run_bounded 2 touch {Q(str(unsafe))}')
            self.assertEqual(result.returncode, 125, result.stderr)
            self.assertFalse(unsafe.exists())

    def test_downloader_error_record_keeps_status_and_mode(self):
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        script = bin_dir / 'wget'
        script.write_text('#!/bin/sh\n[ "$1" != --help ] || exit 0\necho attempted >>"$ATTEMPTS"\necho download-error >&2\nexit 6\n')
        script.chmod(0o755)
        for name, shell in SHELLS:
            dest = self.root / ('seed.document-' + name)
            attempts = self.root / ('attempts-' + name)
            dest.write_text('keep existing document')
            result = self.run_shell(shell, f'source_http_get https://example.invalid/seed {Q(str(dest))}',
                env={'PATH': str(bin_dir) + ':' + os.environ['PATH'], 'ATTEMPTS': str(attempts)})
            self.assertEqual(result.returncode, 6, result.stderr)
            self.assertEqual(attempts.read_text().splitlines(), ['attempted'])
            self.assertEqual(dest.read_text(), 'keep existing document')
            error = Path(str(dest) + '.fetch-error')
            self.assertIn('status=6\nattempts=1\n', error.read_text())
            self.assertEqual(stat.S_IMODE(error.stat().st_mode), 0o600)


# Commands known to be present in busybox-udeb. In particular stat, setsid,
# timeout, findmnt and Bash are not available in this PATH.
APPLETS = ('[', 'awk', 'basename', 'cat', 'chmod', 'chown', 'cmp', 'cp', 'cut', 'date',
           'dd', 'dirname', 'echo', 'env', 'expr', 'false', 'grep', 'gunzip',
           'head', 'id', 'install', 'ln', 'logger', 'ls', 'mkdir', 'mktemp', 'mv', 'printf',
           'pwd', 'readlink', 'rm', 'rmdir', 'sed', 'seq', 'sha256sum', 'sh',
           'sleep', 'sort', 'sync', 'tail', 'tar', 'test', 'touch', 'tr', 'true',
           'uname', 'uniq', 'wc', 'zcat')


class InstallerShellSandbox:
    def __init__(self, root: Path):
        self.root = root
        for path in ('bin', 'lib', 'lib64', 'usr/bin', 'tmp', 'dev', 'etc', 'root',
                     'proc', 'sys/block/nvme0n1', 'sys/bus/pci/devices', 'var/log'):
            (root / path).mkdir(parents=True, exist_ok=True)
        self.copy_executable(Path(BUSYBOX), '/bin/busybox')
        self.copy_executable(Path(shutil.which('wget')), '/bin/wget')
        for applet in APPLETS:
            (root / 'bin' / applet).symlink_to('busybox')
        # Integer-only sleep models images without fractional-duration support.
        # The actual BusyBox implementation still performs the sleep.
        (root / 'bin/sleep').unlink()
        (root / 'bin/sleep').write_text('#!/bin/sh\ncase "${1-}" in ""|*[!0-9]*) exit 93;; esac\nexec /bin/busybox sleep "$@"\n')
        (root / 'bin/sleep').chmod(0o755)
        (root / 'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
        (root / 'etc/group').write_text('root:x:0:\n')
        (root / 'proc/cmdline').write_text('\n')
        (root / 'proc/cpuinfo').write_text('vendor_id : GenuineIntel\nmodel name : test-only cpu\n')
        (root / 'proc/mounts').write_text('')
        (root / 'sys/block/nvme0n1/removable').write_text('0\n')
        (root / 'sys/block/nvme0n1/size').write_text('1000000000\n')
        (root / 'proc/meminfo').write_text('MemTotal:        8388608 kB\n')
        try:
            os.mknod(root / 'dev/null', stat.S_IFCHR | 0o666, os.makedev(1, 3))
        except PermissionError:
            # No devices are accessed by bootstrap; only /dev/null redirection.
            (root / 'dev/null').touch()
        (root / 'tmp').chmod(0o1777)
        self.env = {'PATH': '/bin:/usr/bin', 'LC_ALL': 'C', 'HOME': '/root', 'TERM': 'linux'}

    def copy_executable(self, source: Path, destination: str):
        target = self.root / destination.lstrip('/')
        shutil.copy2(source, target)
        # ldd is run only on trusted, installed system executables, never on a
        # repository or downloaded binary.
        result = subprocess.run(['ldd', str(source)], capture_output=True, text=True, check=True)
        for name in re.findall(r'(/[^\s()]+)', result.stdout):
            path = Path(name)
            if path.is_file():
                dest = self.root / name.lstrip('/')
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)

    def command(self, value: str) -> list[str]:
        return [shutil.which('chroot'), str(self.root), '/bin/sh', '-c', value]

    @property
    def runtime(self) -> Path:
        return self.root / 'tmp/install-runtime'


class GeneratedInstallerShellTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() != 0:
            self.skipTest('root/CAP_SYS_CHROOT required for the isolated installer-shell test')
        self.assertIsNotNone(BUSYBOX)
        self.tmp = tempfile.TemporaryDirectory(prefix='installer-shell-sandbox-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'root'
        self.box = InstallerShellSandbox(self.root)
        probe = subprocess.run(self.box.command('test "$(readlink /bin/sh)" = busybox'),
                               capture_output=True, text=True)
        self.assertEqual(probe.returncode, 0, 'chroot must actually run BusyBox: ' + probe.stderr)
        self.commands = generated_commands()

    def endpoint(self):
        web = Endpoint(FORKY)
        self.addCleanup(web.close)
        return web

    def include(self, cmdline: str, **env):
        command = self.box.command(self.commands['preseed/include_command'])
        p = subprocess.Popen(command, env={**self.box.env, 'INSTALLER_CMDLINE': cmdline, **env},
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 60
        failure = self.box.runtime / 'state/first-failure'
        while p.poll() is None and time.monotonic() < deadline:
            if failure.is_file():
                stop_test_tree(p)
                out, err = p.communicate()
                self.fail('Generated bootstrap entered fatal hold: ' + failure.read_text() + '\n' + err)
            time.sleep(.05)
        if p.poll() is None:
            stop_test_tree(p)
            out, err = p.communicate()
            self.fail('Generated bootstrap timed out: ' + err)
        out, err = p.communicate()
        return subprocess.CompletedProcess(command, p.returncode, out, err)

    def assert_bootstrapped(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        includes = result.stdout.splitlines()
        self.assertEqual(len(includes), 5, result.stdout)
        for uri in includes:
            self.assertTrue(uri.startswith('file:///'))
            path = self.root / uri.removeprefix('file:///')
            self.assertTrue(path.is_file(), uri)
        self.assertTrue((self.box.runtime / 'bootstrap/preflight.ok').is_file())
        self.assertTrue((self.box.runtime / 'state/prepare-context.done').is_file())
        self.assertFalse((self.box.runtime / 'state/first-failure').exists())
        self.assertFalse((self.box.runtime / 'state/installation.success').exists())

    def test_commands_roundtripped_through_debconf_execute_under_busybox(self):
        # This is real debconf File-driver serialization, not a mocked GET. It
        # catches escaped-newline truncation which sh -n cannot detect.
        base = self.root.parent / 'debconf'
        base.mkdir()
        config = base / 'debconf.conf'
        config.write_text('Config: portable_config\nTemplates: portable_templates\n\n'
                          'Name: portable_config\nDriver: File\nMode: 600\n'
                          f'Filename: {base}/config.dat\n\n'
                          'Name: portable_templates\nDriver: File\nMode: 600\n'
                          f'Filename: {base}/templates.dat\n')
        env = {**os.environ, 'DEBCONF_SYSTEMRC': str(config), 'DEBIAN_FRONTEND': 'noninteractive'}
        for key in ('DEBCONF_DB_REPLACE', 'DEBCONF_DB_FALLBACK', 'DEBCONF_DB_OVERRIDE'):
            env.pop(key, None)
        self.commands = readback_commands(FORKY / 'preseed.cfg', env)
        web = self.endpoint()
        result = self.include(f'url={web.url}/short classes=prod;desktop;standard;dhcp;ssh')
        self.assert_bootstrapped(result)

    def test_hardware_detection_failure_is_recorded_before_class_merge(self):
        shutil.copytree(FORKY, self.root / 'seed', ignore=shutil.ignore_patterns('tests', '__pycache__'))
        shutil.rmtree(self.root / 'sys/block/nvme0n1')
        p = subprocess.Popen(self.box.command(self.commands['preseed/include_command']),
            env={**self.box.env, 'INSTALLER_CMDLINE': 'file=/seed/preseed.cfg classes=prod;desktop;standard;dhcp;ssh'},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(stop_test_tree, p)
        failure = self.box.runtime / 'state/first-failure'
        self.assertTrue(wait_file(failure))
        self.assertIn('component=class-auto', failure.read_text())
        self.assertNotIn('required class group', failure.read_text())
        self.assertFalse((self.box.runtime / 'bootstrap/preflight.ok').exists())

    def test_actual_generated_http_bootstrap_under_busybox_at_every_boundary(self):
        web = self.endpoint()
        result = self.include(f'url={web.url}/short classes=prod;desktop;standard;dhcp;ssh')
        self.assert_bootstrapped(result)
        self.assertEqual(web.counts[RAW_PREFIX + '/scripts/common/source.sh'], 1)
        self.assertEqual(web.counts[RAW_PREFIX + '/payload.tar.gz'], 1)
        self.assertEqual(web.counts[RAW_PREFIX + '/payload.manifest'], 1)
        self.assertEqual(sum(web.counts.values()), 5)

    def test_generated_http_bootstrap_handles_decimal_padded_timeouts(self):
        web = self.endpoint()
        result = self.include(f'url={web.url}/short classes=prod;desktop;standard;dhcp;ssh',
                              INSTALLER_FETCH_WALL_TIMEOUT='0180', INSTALLER_FETCH_TIMEOUT='09')
        self.assert_bootstrapped(result)
        self.assertFalse(list(self.box.runtime.rglob('*.fetch-error')))

    def test_actual_generated_local_bootstrap_under_busybox_at_every_boundary(self):
        shutil.copytree(FORKY, self.root / 'seed', ignore=shutil.ignore_patterns('tests', '__pycache__'))
        result = self.include('file=/seed/preseed.cfg classes=prod;desktop;standard;dhcp;ssh')
        self.assert_bootstrapped(result)

    def test_generated_phase_entrypoints_use_valid_embedded_core_and_child_status(self):
        boot = self.box.runtime / 'bootstrap'
        boot.mkdir(parents=True)
        (boot / 'preflight.ok').touch()
        entry = boot / 'preseed-bootstrap-entry.sh'
        entry.write_text('#!/bin/sh\nset -eu\nprintf "%s\\n" "$1" >>/tmp/visited\n')
        entry.chmod(0o700)
        for question in ('preseed/early_command', 'partman/early_command', 'preseed/late_command'):
            result = subprocess.run(self.box.command(self.commands[question]), env=self.box.env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'tmp/visited').read_text().splitlines(), ['early', 'partman', 'late'])
        entry.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >>/tmp/visited\nexit 41\n')
        p = subprocess.Popen(self.box.command(self.commands['preseed/late_command']), env=self.box.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(stop_test_tree, p)
        failure = self.box.runtime / 'state/first-failure'
        self.assertTrue(wait_file(failure))
        self.assertIn('status=41', failure.read_text())
        self.assertIsNone(p.poll())
        # The same generated entry must hold, not run the late child again.
        again = subprocess.Popen(self.box.command(self.commands['preseed/late_command']), env=self.box.env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(stop_test_tree, again)
        time.sleep(.15)
        self.assertIsNone(again.poll())
        self.assertEqual((self.root / 'tmp/visited').read_text().splitlines(), ['early', 'partman', 'late', 'late'])

    def test_generated_first_fetch_failure_reaches_fatal_hold_not_syntax_error(self):
        web = self.endpoint()
        p = subprocess.Popen(self.box.command(self.commands['preseed/include_command']),
            env={**self.box.env, 'INSTALLER_CMDLINE': f'url={web.base}/missing.cfg'},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(stop_test_tree, p)
        failure = self.box.runtime / 'state/first-failure'
        self.assertTrue(wait_file(failure))
        self.assertIsNone(p.poll())
        self.assertFalse((self.box.runtime / 'bootstrap/preflight.ok').exists())
        error = self.box.runtime / 'bootstrap/seed.document.fetch-error'
        self.assertTrue(error.is_file())
        self.assertNotIn('arithmetic syntax', error.read_text())
        self.assertIn('attempts=1', error.read_text())
        self.assertEqual(web.counts[RAW_PREFIX + '/missing.cfg'], 1)
        self.assertFalse((self.box.runtime / 'state/installation.success').exists())


if __name__ == '__main__':
    unittest.main()
