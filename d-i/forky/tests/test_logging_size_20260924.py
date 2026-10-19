"""Size-driven logging and prerequisite-order regressions. No live host services.

Only the optional packaged-rsyslog test starts a private foreground instance,
using a disposable /run fixture and a private socket, never /dev/log or a journal.
"""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import fcntl
import grp
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from payload_fixture import installed_script, logging_text, read_text, source_path

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
APP = '/var/log/managed/apps/apps.log'


def load_rotation():
    loader = importlib.machinery.SourceFileLoader('managed_size_rotation',
        str(installed_script(TARGET / 'usr/local/libexec/rsyslog-size-rotate')))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


rotation = load_rotation()


@unittest.skipUnless(os.geteuid() == 0, 'root-owned path fixtures require root')
class SizeRotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.active = self.root / APP.lstrip('/')
        self.active.parent.mkdir(parents=True, mode=0o750)
        self.gid = grp.getgrnam('adm').gr_gid

    def write(self, data: bytes, path: Path | None = None):
        path = self.active if path is None else path
        path.write_bytes(data)
        path.chmod(0o640)
        os.chown(path, 0, self.gid)
        return path

    def full(self, value: bytes = b'A'):
        return self.write(value * rotation.LIMIT)

    def test_callback_makes_room_for_next_record_below_threshold(self):
        self.write(b'a' * (rotation.LIMIT - 1))
        inode = self.active.stat().st_ino
        self.assertTrue(rotation.rotate(APP, root=self.root))
        self.assertFalse(self.active.exists())
        self.assertEqual(self.active.with_name('apps.log.1').stat().st_ino, inode)

    def test_empty_callback_is_noop(self):
        self.write(b'')
        self.assertFalse(rotation.rotate(APP, root=self.root))
        self.assertTrue(self.active.exists())

    def test_exact_threshold_renames_without_inventing_or_copying_records(self):
        self.full()
        before = self.active.stat()
        self.assertTrue(rotation.rotate(APP, root=self.root))
        archive = self.active.with_name('apps.log.1')
        self.assertFalse(self.active.exists())  # omfile, not the helper, reopens it
        self.assertEqual(archive.stat().st_ino, before.st_ino)
        self.assertEqual(archive.read_bytes(), b'A' * rotation.LIMIT)
        self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o640)
        self.assertEqual(archive.stat().st_gid, self.gid)

    def test_oversized_record_is_preserved_whole(self):
        data = b'complete record: ' + b'x' * (rotation.LIMIT + 65536) + b'\n'
        self.write(data)
        rotation.rotate(APP, root=self.root)
        self.assertEqual(self.active.with_name('apps.log.1').read_bytes(), data)

    def test_four_archives_remain_in_order_across_repeated_rotations(self):
        for index in range(7):
            self.full(bytes([65 + index]))
            rotation.rotate(APP, root=self.root)
        for index in range(1, 5):
            path = self.active.with_name(f'apps.log.{index}')
            self.assertEqual(path.read_bytes(), bytes([72 - index]) * rotation.LIMIT)
        self.assertFalse(self.active.with_name('apps.log.5').exists())
        self.assertEqual(len(list(self.active.parent.glob('apps.log.*'))), 4)

    def test_missing_active_is_idempotent(self):
        self.assertFalse(rotation.rotate(APP, root=self.root))

    def test_unknown_relative_normalized_and_traversal_paths_are_rejected(self):
        for bad in ('apps.log', '/etc/passwd', APP + '.1', APP.replace('/apps/', '/apps/../apps/'),
                    APP.replace('/apps/', '//apps/'), APP.replace('/apps/', '/apps/./')):
            with self.subTest(path=bad), self.assertRaises(rotation.RotationError):
                rotation.rotate(bad, root=self.root)

    def test_active_symlink_is_rejected_without_touching_target(self):
        other = self.write(b'untouched', self.active.with_name('other'))
        self.active.symlink_to(other.name)
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)
        self.assertEqual(other.read_bytes(), b'untouched')

    def test_active_hardlink_is_rejected(self):
        self.full()
        os.link(self.active, self.active.with_name('other'))
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)
        self.assertTrue(self.active.exists())

    def test_archive_symlink_preflight_happens_before_any_rename(self):
        self.full()
        first = self.write(b'first', self.active.with_name('apps.log.1'))
        self.active.with_name('apps.log.4').symlink_to(first.name)
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)
        self.assertEqual(first.read_bytes(), b'first')
        self.assertTrue(self.active.exists())

    def test_archive_hardlink_is_rejected_before_any_rename(self):
        self.full()
        self.write(b'old', self.active.with_name('apps.log.2'))
        os.link(self.active.with_name('apps.log.2'), self.active.with_name('elsewhere'))
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)
        self.assertTrue(self.active.exists())

    def test_writable_or_non_root_parent_is_rejected(self):
        self.full()
        for mode, uid in ((0o770, 0), (0o750, 65534)):
            self.active.parent.chmod(mode)
            os.chown(self.active.parent, uid, self.gid)
            with self.subTest(mode=mode, uid=uid), self.assertRaises(rotation.RotationError):
                rotation.rotate(APP, root=self.root)
        os.chown(self.active.parent, 0, self.gid)

    def test_parent_symlink_is_rejected(self):
        self.full()
        saved = self.active.parent.with_name('saved')
        self.active.parent.rename(saved)
        self.active.parent.symlink_to(saved.name)
        with self.assertRaises(OSError):
            rotation.rotate(APP, root=self.root)
        self.assertTrue((saved / 'apps.log').exists())

    def test_incorrect_file_owner_group_or_mode_is_rejected(self):
        self.full()
        for mode, uid, gid in ((0o666, 0, self.gid), (0o640, 65534, self.gid), (0o640, 0, 0)):
            self.active.chmod(mode)
            os.chown(self.active, uid, gid)
            with self.subTest(mode=mode, uid=uid, gid=gid), self.assertRaises(rotation.RotationError):
                rotation.rotate(APP, root=self.root)

    def test_fifo_active_and_fifo_lock_are_rejected_without_reading(self):
        os.mkfifo(self.active, 0o640)
        os.chown(self.active, 0, self.gid)
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)
        self.active.unlink()
        lock = self.active.with_name('.apps.log.rotate.lock')
        lock.unlink()  # first rejected invocation legitimately created its lock
        os.mkfifo(lock, 0o600)
        self.full()
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)

    def test_lock_symlink_and_hardlink_are_rejected(self):
        self.full()
        lock = self.active.with_name('.apps.log.rotate.lock')
        other = self.active.with_name('other.lock')
        other.write_bytes(b''); other.chmod(0o600)
        lock.symlink_to(other.name)
        with self.assertRaises(OSError):
            rotation.rotate(APP, root=self.root)
        lock.unlink(); os.link(other, lock)
        with self.assertRaises(rotation.RotationError):
            rotation.rotate(APP, root=self.root)

    def test_concurrent_lock_refuses_instead_of_waiting(self):
        self.full()
        lock = os.open(self.active.with_name('.apps.log.rotate.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, lock)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with self.assertRaises(BlockingIOError):
            rotation.rotate(APP, root=self.root)
        self.assertTrue(self.active.exists())

    def test_cli_requires_root_and_exactly_one_argument(self):
        with patch.object(rotation.os, 'geteuid', return_value=65534):
            self.assertEqual(rotation.main([APP]), 1)
        self.assertEqual(rotation.main([]), 1)
        self.assertEqual(rotation.main([APP, '/etc/passwd']), 1)


class LoggingWiringTests(unittest.TestCase):
    def test_only_private_app_ruleset_writes_application_log(self):
        writers = []
        for path in (TARGET / 'etc/rsyslog.d').glob('*.conf*'):
            for action in re.findall(r'action\([^)]*\)', logging_text(path.read_text())):
                if 'type="omfile"' in action and f'file="{APP}"' in action:
                    writers.append(path.name)
        self.assertEqual(writers, ['21-apps.conf.tmpl'])

    def test_unverified_auth_has_a_protected_separate_sink_and_no_security_consumer(self):
        unverified = '/var/log/managed/security/auth/unverified.log'
        auth = read_text(TARGET / 'etc/rsyslog.d/20-auth.conf')
        self.assertEqual(re.findall(r'\bfile="([^"]+)"', auth), [
            unverified, '/var/log/managed/security/auth/auth.log',
            '/var/lib/labwc-notifications/security/auth.signal'])
        self.assertIn('f ' + unverified + ' 0640 root adm - -',
                      read_text(TARGET / 'etc/tmpfiles.d/59-log-layout.conf'))
        self.assertIn(unverified, rotation.OUTPUTS)
        for relative in ('etc/crowdsec/acquis.d/20-sshd.yaml', 'etc/fail2ban/jail.d/10-sshd.local'):
            consumer = read_text(TARGET / relative)
            self.assertIn('/var/log/managed/security/auth/auth.log', consumer)
            self.assertNotIn(unverified, consumer)
            self.assertNotIn('/auth/*', consumer)

    def test_each_omfile_action_has_one_allowlisted_size_callback(self):
        found = set()
        for path in (TARGET / 'etc/rsyslog.d').glob('*.conf*'):
            for action in re.findall(r'action\([^)]*\)', logging_text(path.read_text())):
                if 'type="omfile"' not in action:
                    continue
                sink = re.search(r'\bfile="([^"]+)"', action)
                self.assertIsNotNone(sink, path.name)
                self.assertIn(sink[1], rotation.OUTPUTS, path.name)
                self.assertEqual(action.count('rotation.sizeLimit="2097152"'), 1)
                self.assertIn('rotation.sizeLimitCommand="/usr/local/libexec/rsyslog-size-rotate"', action)
                self.assertIn('rotation.sizeLimitCommandPassFileName="on"', action)
                self.assertNotIn(sink[1], found, 'competing collector writers: ' + sink[1])
                found.add(sink[1])
        self.assertEqual(found, set(rotation.OUTPUTS))

    def test_apps_have_no_per_application_directories_or_fake_catalog(self):
        layout = read_text(TARGET / 'etc/tmpfiles.d/59-log-layout.conf')
        self.assertIn('f ' + APP + ' ', layout)
        self.assertEqual(re.findall(r'^d (/var/log/managed/apps\S*) ', layout, re.M), ['/var/log/managed/apps'])
        env = (SEED / 'hosts/logging/observability.env').read_text()
        for name in ('BRAVE', 'LIBREWOLF', 'FLOORP', 'ZEN', 'VIVALDI', 'CHROMIUM', 'FEATHERPAD'):
            self.assertNotIn('LOG_' + name + '_', env)
        for number in ('21-apps.conf', '44-components.conf'):
            active = read_text(TARGET / 'etc/rsyslog.d' / number)
            self.assertNotIn('re_match(', active)
            self.assertNotIn('dynaFile=', active)
            self.assertNotIn('format="jsonf"', active)

    def test_no_competing_logrotate_or_fifteen_minute_timer(self):
        text = '\n'.join(logging_text(p.read_text()) for p in (TARGET / 'etc/logrotate.d').iterdir())
        active = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
        for sink in rotation.OUTPUTS:
            self.assertNotIn(sink, active)
        self.assertNotIn('rsyslog-rotate', active)
        timer = read_text(TARGET / 'etc/systemd/system/logrotate.timer.d/override.conf')
        self.assertIn('OnCalendar=daily\n', timer)
        self.assertNotIn('*:00/', timer)
        for name in ('fail2ban', 'codex', 'chatgpt-runtime'):
            policy = read_text(TARGET / 'etc/logrotate.d' / name)
            self.assertRegex(policy, r'(?m)^\s*size 2M$')
            self.assertNotRegex(policy, r'(?m)^\s*(daily|maxsize)\b')

    def test_both_journal_validators_agree_with_input_transport(self):
        native = read_text(TARGET / 'etc/systemd/journald.conf.d/10-storage.conf')
        self.assertIn('ForwardToSyslog=no', native)
        self.assertIn('ReadKMsg=no', native)
        shell = (SEED / 'scripts/late/storage-maintenance.sh').read_text()
        self.assertIn("'ForwardToSyslog=no'", shell)
        self.assertNotIn("'ForwardToSyslog=yes'", shell)
        route = read_text(TARGET / 'etc/rsyslog.d/15-audit.conf')
        self.assertIn('$!uid == "0"', route)
        self.assertIn('$!exe == "/usr/sbin/audisp-syslog"', route)
        self.assertNotIn('$programname ==', route)

    def test_foundation_is_staged_before_selected_helpers_in_every_family(self):
        dispatch = (SEED / 'scripts/late/dispatch.sh').read_text()
        for family in ('btrfs', 'f2fs'):
            text = (SEED / 'scripts/late' / (family + '-family.sh')).read_text()
            self.assertIn('stage_target_logging_foundation || return $?', text)
            self.assertLess(text.index('prepare_target_volatile_mountpoints_for_first_boot\nstage_target_logging_foundation'),
                            text.rindex('installer_archive_logs_to_target'))
            self.assertLess(dispatch.index('run_' + family + '_family_late_command'),
                            dispatch.index('\nrun_selected_class_helpers\n'))
        for helper, label in (('software', 'ChatGPT'), ('devops', 'Codex')):
            text = read_text(SEED / 'scripts/late' / (helper + '.sh'))
            self.assertIn('preflight shared logging paths before ' + label + ' tmpfiles', text)
            self.assertIn('/usr/local/libexec/log-layout --preflight || return $?', text)

    @unittest.skipUnless(os.geteuid() == 0, 'staging ownership requires disposable fixture root')
    def test_foundation_stager_uses_exact_assets_and_propagates_failures(self):
        source = shlex.quote(str(SEED / 'scripts/late/target-assets.sh'))
        lifecycle = shlex.quote(str(SEED / 'scripts/common/lifecycle.sh'))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root / 'bin'; bindir.mkdir()
            # Only these image utilities are visible. In particular, no stat,
            # target helper, systemd manager or package command is available.
            for name in ('awk', 'chmod', 'chown', 'ln', 'ls', 'mkdir', 'mv', 'rm'):
                command = shutil.which(name, path='/usr/bin:/bin')
                self.assertIsNotNone(command, f'disposable image lacks {name}')
                (bindir / name).symlink_to(command)
            home = root / 'home'; home.mkdir(mode=0o700)
            destinations = (
                '/etc/systemd/journald.conf.d/syslog.conf',
                '/usr/local/libexec/journal-check',
                '/usr/local/libexec/journal-forwarding',
                '/etc/systemd/system/rsyslog-journal-forwarding.service',
                '/etc/systemd/system/rsyslog.service.d/40-journal-forwarding.conf',
                '/etc/tmpfiles.d/59-log-layout.conf',
                '/etc/tmpfiles.d/65-audit-syslog.conf',
                '/usr/local/libexec/log-layout',
                '/usr/local/libexec/rsyslog-size-rotate',
                '/etc/rsyslog.conf',
            )
            unsafe_cases = ('mode', 'special-mode', 'uid', 'gid', 'hardlink',
                            'symlink', 'missing', 'ls-error', 'awk-error', 'token')
            cases = [('', failure) for failure in ('', *destinations)]
            cases.extend((unsafe, '') for unsafe in unsafe_cases)
            for index, (unsafe, failure) in enumerate(cases):
                work = root / str(index); work.mkdir()
                trace = work / 'trace'
                target = work / 'target with spaces'; target.mkdir()
                code = f'''. {lifecycle}
. {source}
installer_repo_join_var() {{ shift; printf '%s\\n' "$*"; }}
installer_fatal() {{ printf '%s\\n' "$*" >&2; return 1; }}
target_asset_assert_no_unresolved_installer_placeholders() {{
  [ "$UNSAFE:$2" != token:usr/local/libexec/journal-check ] || return 74
}}
if [ "$UNSAFE" = ls-error ]; then ls() {{ return 91; }}; fi
if [ "$UNSAFE" = awk-error ]; then awk() {{ return 92; }}; fi
stage_target_asset() {{
  printf '%s|%s|%s\\n' "$1" "$2" "$3" >> "$TRACE"
  [ "$2" != "$FAIL" ] || return 73
  staged=$INSTALLER_TARGET_DIR$2
  mkdir -p "${{staged%/*}}" || return 1
  printf '%s\\n' fixture >"$staged" || return 1
  chmod "$3" "$staged" || return 1
  if [ "$2" = /usr/local/libexec/journal-check ]; then
    case "$UNSAFE" in
      mode) chmod 0777 "$staged" ;;
      special-mode) chmod 4755 "$staged" ;;
      uid) chown 65534:0 "$staged" ;;
      gid) chown 0:65534 "$staged" ;;
      hardlink) ln "$staged" "$staged.alias" ;;
      symlink) mv "$staged" "$staged.original"; ln -s "$staged.original" "$staged" ;;
      missing) rm "$staged" ;;
    esac
  fi
  return 0
}}
if stage_target_logging_foundation; then exit 0; else exit $?; fi
'''
                result = subprocess.run(['/bin/sh', '-eu', '-c', code],
                    env={'PATH': str(bindir), 'HOME': str(home), 'TMPDIR': tmp,
                         'LC_ALL': 'C', 'TRACE': str(trace), 'FAIL': failure,
                         'UNSAFE': unsafe, 'INSTALLER_TARGET_DIR': str(target)},
                    text=True, capture_output=True, timeout=10)
                expected = 73 if failure else 74 if unsafe == 'token' else 1 if unsafe else 0
                self.assertEqual(result.returncode, expected, result.stderr)
                entries = trace.read_text().splitlines()
                count = destinations.index(failure) + 1 if failure else 5 if unsafe else len(destinations)
                self.assertEqual(len(entries), count)
                self.assertEqual(tuple(entry.split('|')[1] for entry in entries), destinations[:len(entries)])
                for entry in entries:
                    asset, destination, mode = entry.split('|')
                    self.assertEqual(asset, destination.lstrip('/'))
                    self.assertEqual(mode, '0755' if destination.startswith('/usr/local/libexec/') else '0644')
                if unsafe and unsafe != 'token':
                    self.assertIn('unsafe staged journal forwarding asset:', result.stderr)

    def test_informational_paths_follow_the_actual_system_collector(self):
        for helper in ('tailscale', 'crowdsec'):
            text = (SEED / 'scripts/late' / (helper + '.sh')).read_text()
            self.assertIn('log_file=$LOG_SYSTEM_SERVICES_FILE', text)
            self.assertNotIn('LOG_NETWORK_FILE', text)
            self.assertNotIn('LOG_CROWDSEC_SERVICE_FILE', text)


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('rsyslogd', path='/usr/sbin:/usr/bin:/sbin:/bin'),
                     'packaged rsyslogd and namespace root required')
class AuthenticationRoutingTests(unittest.TestCase):
    """Native rules, synthetic origin metadata; disposable image execution only."""

    def test_missing_identity_is_retained_without_app_or_security_input_contamination(self):
        with tempfile.TemporaryDirectory(prefix='auth-routing-') as temporary:
            root = Path(temporary)
            paths = {name: root / 'logs/security/auth' / name for name in ('auth.log', 'unverified.log')}
            paths['apps.log'] = root / 'logs/apps/apps.log'
            paths['signal'] = root / 'signals/auth.signal'
            for path in paths.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch(mode=0o640)
            spool = root / 'spool'
            spool.mkdir()
            callback = root / 'unexpected-rotation'
            callback.write_text('#!/bin/sh\nexit 97\n')
            callback.chmod(0o700)
            group = grp.getgrgid(os.getgid()).gr_name

            def private(text):
                return (text.replace('/var/log/managed', str(root / 'logs'))
                        .replace('/var/lib/labwc-notifications/security/auth.signal', str(paths['signal']))
                        .replace('/usr/local/libexec/rsyslog-size-rotate', str(callback))
                        .replace('fileGroup="adm"', f'fileGroup="{group}"')
                        .replace('fileGroup="logreader"', f'fileGroup="{group}"')
                        .replace('dirGroup="logreader"', f'dirGroup="{group}"'))

            auth = private(read_text(TARGET / 'etc/rsyslog.d/20-auth.conf'))
            declarations, auth_rule = auth.split('\nif (', 1)
            app_policy = private(read_text(TARGET / 'etc/rsyslog.d/21-apps.conf'))
            boundary = app_policy.index('\n# No call from the journal-forwarding ruleset:')
            apps, journal_stop = app_policy[:boundary], app_policy[boundary:]
            # Only origin metadata is simulated. This never invokes sudo, PAM,
            # a journal, a real security engine or an installed managed helper.
            origin = '''set $!uid = "1000";
set $!pid = "123";
unset $!exe;
if ($programname == "fixture-sudo") then { set $!exe = "/usr/bin/sudo"; }
if ($programname == "fixture-root") then { set $!uid = "0"; }
if ($programname == "fixture-logger") then { set $!exe = "/usr/bin/logger"; }
if ($programname == "fixture-missing-uid") then { unset $!uid; }
'''
            auth_socket, app_socket = root / 'auth.sock', root / 'app.sock'
            configuration = (f'global(workDirectory="{spool}")\n'
                f'$FileOwner root\n$FileGroup {group}\n$FileCreateMode 0640\n'
                'module(load="imuxsock" SysSock.Use="off")\n' + declarations + '\n' + apps + '\n'
                'ruleset(name="fixture_auth") {\n' + origin + '\nif (' + auth_rule + '\n'
                + journal_stop + '\n}\n'
                'ruleset(name="fixture_app") {\nset $!uid = "1000";\ncall managed_application_output\n}\n'
                f'input(type="imuxsock" Socket="{auth_socket}" CreatePath="off" Ruleset="fixture_auth" RateLimit.Interval="0")\n'
                f'input(type="imuxsock" Socket="{app_socket}" CreatePath="off" Ruleset="fixture_app" RateLimit.Interval="0")\n')
            self.assertNotIn('/var/log/managed', configuration)
            self.assertNotIn('/var/lib/labwc-notifications', configuration)
            self.assertNotIn('/usr/local/', configuration)
            config = root / 'rsyslog.conf'
            config.write_text(configuration)
            records = [
                ('sudo', 86, 'report-command COMMAND=/usr/bin/journalctl', 'unverified.log'),
                ('sudo', 86, 'report-open pam_unix(sudo:session): session opened', 'unverified.log'),
                ('sudo', 86, 'report-close pam_unix(sudo:session): session closed', 'unverified.log'),
                ('sudo', 83, 'rejected-sudo-failure authentication failure', 'unverified.log'),
                ('fixture-logger', 38, 'forged-failure Failed password', 'unverified.log'),
                ('fixture-missing-uid', 38, 'missing-uid authentication failure', 'unverified.log'),
                ('fixture-sudo', 86, 'verified-command COMMAND=/usr/bin/journalctl', 'auth.log'),
                ('fixture-sudo', 38, 'accepted-sudo-failure authentication failure', 'auth.log'),
                ('fixture-root', 86, 'root-failure Failed password', 'auth.log'),
            ]
            with (root / 'stderr').open('w+') as diagnostics:
                process = subprocess.Popen([
                    shutil.which('rsyslogd', path='/usr/sbin:/usr/bin:/sbin:/bin'),
                    '-n', '-i', str(root / 'pid'), '-f', str(config)], cwd=root,
                    env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': str(root), 'LC_ALL': 'C'},
                    stdin=subprocess.DEVNULL, stdout=diagnostics, stderr=diagnostics)

                def wait_for(predicate):
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline and process.poll() is None:
                        if predicate():
                            return
                        time.sleep(0.025)
                    diagnostics.flush()
                    diagnostics.seek(0)
                    self.fail('private rsyslog did not reach expected state: ' + diagnostics.read(16384))

                try:
                    wait_for(lambda: auth_socket.exists() and app_socket.exists())
                    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
                        for program, priority, message, _destination in records:
                            sender.sendto(f'<{priority}>{program}[123]: {message}'.encode(), str(auth_socket))
                        sender.sendto(b'<86>sudo[123]: private-app authentication failure', str(app_socket))
                    wait_for(lambda: all(message in paths[destination].read_text()
                                         for _program, _priority, message, destination in records)
                             and 'private-app' in paths['apps.log'].read_text())
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
            for program, _priority, message, destination in records:
                for name in ('auth.log', 'unverified.log', 'apps.log'):
                    self.assertEqual(message in paths[name].read_text(), name == destination,
                                     (program, message, name))
            unverified = paths['unverified.log'].read_text().splitlines()
            self.assertEqual(len(unverified), 6)
            self.assertTrue(all('origin=unverified-auth' in line for line in unverified))
            self.assertNotIn('origin=unverified-auth', paths['auth.log'].read_text())
            self.assertEqual(paths['signal'].read_text(), 'auth\nauth\n')
            self.assertEqual(len(paths['apps.log'].read_text().splitlines()), 1)


def exercise_native_rsyslog(case: unittest.TestCase) -> None:
    """Real credentials, native omfile callback, restart, and line-injection probe."""
    if not shutil.which('rsyslogd') or os.geteuid() != 0:
        case.skipTest('packaged rsyslogd and root required for native socket fixture')
    with tempfile.TemporaryDirectory(prefix='managed-rsyslog-test-', dir='/run') as tmp:
        root = Path(tmp); root.chmod(0o755)
        (root / 'spool').mkdir()
        app = root / 'logs/apps/apps.log'
        system = root / 'logs/system/system.log'
        kernel = root / 'logs/system/kernel.log'
        for path in (app, system, kernel):
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            path.touch(mode=0o640)
            os.chown(path, 0, grp.getgrnam('adm').gr_gid)
        # Only fixture paths change; all production rotation logic is exercised.
        helper = root / 'rotate'
        helper.write_text(read_text(TARGET / 'usr/local/libexec/rsyslog-size-rotate').replace(
            '/var/log/managed', str(root / 'logs')))
        helper.chmod(0o700)
        routes = '\n'.join(read_text(TARGET / 'etc/rsyslog.d' / name)
            for name in ('21-apps.conf', '44-components.conf'))
        routes = routes.replace('/var/log/managed', str(root / 'logs')).replace(
            '/usr/local/libexec/rsyslog-size-rotate', str(helper))
        sock = root / 'input.sock'
        system_sock = root / 'system.sock'
        config = root / 'rsyslog.conf'
        config.write_text(f'global(workDirectory="{root / "spool"}" maxMessageSize="64k")\n'
            '$FileOwner root\n$FileGroup adm\n$FileCreateMode 0640\n'
            'module(load="imuxsock" SysSock.Use="off")\n'
            + routes + '\n' +
            f'input(type="imuxsock" Socket="{sock}" CreatePath="off" RateLimit.Interval="0" '
            'Ruleset="managed_application_output" Annotate="on" ParseTrusted="on" UsePIDFromSystem="on")\n'
            f'input(type="imuxsock" Socket="{system_sock}" CreatePath="off" RateLimit.Interval="0" '
            'Annotate="on" ParseTrusted="on" UsePIDFromSystem="on")\n')
        stderr = (root / 'stderr').open('w+')
        process = None
        def wait_for(predicate, description):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if predicate(): return
                if process is not None and process.poll() is not None: break
                time.sleep(.025)
            stderr.flush(); stderr.seek(0)
            case.fail(description + '\n' + stderr.read())
        def start():
            nonlocal process
            process = subprocess.Popen(['rsyslogd', '-n', '-i', str(root / 'pid'), '-f', str(config)],
                stdout=stderr, stderr=stderr)
            wait_for(sock.exists, 'private socket did not start')
            sock.chmod(0o666)
        def stop():
            if process is not None and process.poll() is None:
                process.terminate(); process.wait(timeout=15)
        def send_user(count, prefix):
            code = '''import os,socket,sys,time
os.setgroups([]); os.setgid(2000); os.setuid(2000)
s=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
for i in range(int(sys.argv[2])):
 s.sendto(('<14>tuta[123]: '+sys.argv[3]+':'+str(i)+':'+('x'*8192)).encode(),sys.argv[1]); time.sleep(.003)
time.sleep(.2)
'''
            subprocess.run([sys.executable, '-I', '-c', code, str(sock), str(count), prefix],
                check=True, timeout=15)
        try:
            start(); send_user(280, 'before-restart')
            archive = app.with_name('apps.log.1')
            wait_for(archive.exists, 'native size callback did not rotate the 2 MiB output')
            case.assertGreaterEqual(archive.stat().st_size, 2 * 1024 * 1024)
            case.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o640)
            case.assertNotIn('before-restart', system.read_text())
            # A literal newline in a real input record must not create a forged
            # second line, and a spoofed program tag must not select a filename.
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                probe.sendto(b'<11>audisp-syslog[1]: injection-probe\nforged-line', str(system_sock))
            finally:
                probe.close()
            wait_for(lambda: 'injection-probe' in system.read_text(), 'root fallback did not receive input')
            case.assertFalse(any(line.startswith('forged-line') for line in system.read_text().splitlines()))
            stop(); start(); send_user(1, 'after-restart')
            wait_for(lambda: app.exists() and 'after-restart' in app.read_text(), 'input was not delivered after restart')
            case.assertEqual({p.name for p in app.parent.iterdir()},
                             {'apps.log', 'apps.log.1', '.apps.log.rotate.lock'})
        finally:
            stop(); stderr.close()


if __name__ == '__main__':
    unittest.main()
