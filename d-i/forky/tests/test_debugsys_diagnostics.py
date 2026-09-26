"""Diagnostics security, user-manager isolation and actual terminal navigation."""
from __future__ import annotations
import contextlib
import fcntl
import gzip
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import pty
import pwd
import select
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest import mock
from payload_fixture import installed_script

TARGET = Path(__file__).resolve().parents[1]/'hooks/target'
SCRIPT = installed_script(TARGET/'usr/local/libexec/debugsys.py')
loader = importlib.machinery.SourceFileLoader('debugsys_diagnostics_tests', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
debug = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = debug
loader.exec_module(debug)
USER = pwd.struct_passwd(('desktop-fixture', 'x', 1000, 1000, '', '/home/desktop-fixture', '/bin/sh'))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='debugsys-test-', dir='/root' if os.geteuid() == 0 else None)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)


class EvidenceTests(Fixture):
    def test_all_categories_have_bounded_fixed_probes(self):
        self.assertEqual(set(debug.CATEGORIES), debug.PROBES.keys())
        self.assertEqual(set(debug.CATEGORIES), debug.FILES.keys())
        self.assertEqual(debug.PROBES['codex'], [])
        self.assertEqual(debug.PROBES['chatgpt'], [])
        self.assertNotIn('Environment', debug.UNIT_PROPERTIES)
        self.assertNotIn('ExecStart', debug.UNIT_PROPERTIES)
        for probes in debug.PROBES.values():
            self.assertTrue(all(isinstance(argv, list) for _, argv in probes))
        all_probes = repr(debug.PROBES)
        self.assertNotIn('--setup-keys', all_probes)
        self.assertNotIn('--verify-key', all_probes)
        self.assertIn('dmesg', all_probes)
        self.assertIn('atomic', debug.GPU_PATTERN)

    def test_redaction_headers_json_private_keys_and_terminal_controls(self):
        text = ('Authorization: Bearer xyz.header.signature\nAuthorization: Basic dXNlcjpwYXNz\n'
                '{"api_key":"sensitive quoted value", "refresh_token":"secret-value"}\n'
                'Cookie: session=opaque; other=private\nhttps://user:password@example.invalid\n'
                '\x1b]52;c;clipboard\x07\u202efake\n'
                '-----BEGIN PRIVATE KEY-----\ntruncated-private-key')
        result = debug.redact(text)
        for secret in ('xyz.header.signature', 'dXNlcjpwYXNz', 'sensitive quoted value', 'secret-value',
                       'opaque', 'other=private', 'user:password', 'truncated-private-key', '\x1b', '\u202e'):
            self.assertNotIn(secret, result)
        self.assertIn('\\u001b', result)
        self.assertIn('[PRIVATE KEY REDACTED]', result)

    def test_current_log_tail_is_bounded_and_redacted(self):
        path = self.root/'app.log'
        path.write_bytes(b'x'*(debug.MAX_LOG+64)+b'\napi_key=private-value\n')
        text, meta = debug.log_text(path)
        self.assertEqual(meta['status'], 'output-limit')
        self.assertEqual(meta['capture'], 'tail')
        self.assertNotIn('private-value', text)
        self.assertLessEqual(len(text), debug.MAX_LOG)

    def test_gzip_bomb_and_corruption_are_bounded(self):
        path = self.root/'app.log.1.gz'
        with gzip.open(path, 'wb') as stream:
            stream.write(b'x'*(debug.MAX_LOG*3))
        text, meta = debug.log_text(path)
        self.assertEqual(len(text), debug.MAX_LOG)
        self.assertEqual(meta['status'], 'output-limit')
        path.write_bytes(b'not gzip')
        self.assertEqual(debug.log_text(path)[1]['status'], 'unavailable')
        with path.open('wb') as stream:
            stream.truncate(8*debug.MAX_LOG+1)
        self.assertEqual(debug.log_text(path)[1]['status'], 'compressed-input-limit')

    def test_logs_reject_links_fifo_and_linked_ancestors(self):
        path = self.root/'app.log'
        path.write_text('private')
        link = self.root/'alias.log'
        link.symlink_to(path)
        self.assertEqual(debug.log_text(link)[0], '')
        link.unlink()
        os.link(path, link)
        self.assertEqual(debug.log_text(link)[1]['status'], 'unsafe-log')
        link.unlink()
        os.mkfifo(link)
        self.assertEqual(debug.log_text(link)[1]['status'], 'unsafe-log')
        directory = self.root/'alias'
        directory.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(debug.log_text(directory/'app.log')[0], '')
        with self.assertRaises(debug.DebugError):
            with debug.input_directory(self.root/'..'):
                pass

    @unittest.skipUnless(os.geteuid() == 0, 'administrator-owned log fixture')
    def test_root_log_reader_requires_administrator_control(self):
        path = self.root/'app.log'
        path.write_text('safe')
        self.assertEqual(debug.log_text(path, trusted=True)[0], 'safe')
        path.chmod(0o666)
        self.assertEqual(debug.log_text(path, trusted=True)[0], '')
        path.chmod(0o600)
        os.chown(path, 1000, 1000)
        self.assertEqual(debug.log_text(path, trusted=True)[0], '')
        os.chown(path, 0, 0)
        self.root.chmod(0o777)
        self.assertEqual(debug.log_text(path, trusted=True)[0], '')
        self.root.chmod(0o700)

    def test_rotations_only_accept_fixed_basenames_and_count_limits(self):
        path = self.root/'app.log'
        path.write_text('current')
        for index in range(1, 8):
            rotated = self.root/f'app.log.{index}'
            rotated.write_text(str(index))
            os.utime(rotated, (index, index))
        for name in ('app.log.secret', 'app.log.1.secret', 'unrelated.log', 'app.log.20260926.tar.gz'):
            (self.root/name).write_text('not evidence')
        paths, limited = debug.log_paths(path)
        self.assertTrue(limited)
        self.assertEqual(paths, [path, *(self.root/f'app.log.{index}' for index in (7, 6, 5, 4, 3))])
        with mock.patch.object(debug, 'MAX_LOG_DIRECTORY', 2):
            self.assertTrue(debug.log_paths(path)[1])

    def test_internal_user_helpers_refuse_root_and_invalid_identity(self):
        with mock.patch.object(debug.os, 'geteuid', return_value=0):
            for action, args in ((debug.user_evidence, ('codex',)), (debug.user_log, ('codex', 0))):
                with self.assertRaises(debug.DebugError):
                    action(*args)
        with mock.patch.object(debug.os, 'getuid', return_value=1000), mock.patch.object(debug.os, 'geteuid', return_value=1000):
            for category, index in (('other', 0), ('codex', -1), ('codex', 999)):
                with self.assertRaises(debug.DebugError):
                    debug.user_log(category, index)

    def test_explicit_user_rejects_root_unknown_and_relative_home(self):
        for user in (pwd.getpwnam('root'), pwd.struct_passwd(('u', 'x', 1000, 1000, '', 'relative', '/bin/sh'))):
            with mock.patch.object(debug.pwd, 'getpwnam', return_value=user), self.assertRaises(debug.DebugError):
                debug.desktop_account('chosen')
        with mock.patch.object(debug.pwd, 'getpwnam', side_effect=KeyError), self.assertRaises(debug.DebugError):
            debug.desktop_account('unknown')
        with mock.patch.object(debug.pwd, 'getpwnam', return_value=USER):
            self.assertEqual(debug.desktop_account('chosen'), USER)

    def test_ambiguous_active_sessions_never_choose_arbitrarily(self):
        second = pwd.struct_passwd(('other', 'x', 1001, 1001, '', '/home/other', '/bin/sh'))
        with mock.patch.dict(debug.os.environ, {}, clear=True), mock.patch.object(debug.pwd, 'getpwall', return_value=[USER, second]), mock.patch.object(debug.Path, 'exists', return_value=True):
            self.assertIsNone(debug.desktop_account())

    def test_user_argv_has_clean_environment_and_no_root_fallback(self):
        with mock.patch.object(debug.Path, 'lstat', side_effect=FileNotFoundError):
            self.assertIsNone(debug.user_command(USER, ['id']))
            command = debug.user_command(USER, ['id'], bus_required=False)
        self.assertEqual(command[:6], ['/usr/sbin/runuser', '-u', USER.pw_name, '--', '/usr/bin/env', '-i'])
        self.assertIn('--chdir='+USER.pw_dir, command)
        self.assertIn('HOME='+USER.pw_dir, command)
        self.assertFalse(any(x.startswith(('DISPLAY=', 'DBUS_SESSION_BUS_ADDRESS=', 'LD_PRELOAD=')) for x in command))
        self.assertIsNone(debug.user_command(None, ['id'], bus_required=False))

    def test_safe_bus_requires_owner_mode_and_socket_type(self):
        directory = os.stat_result((stat.S_IFDIR|0o700, 1, 1, 1, 1000, 1000, 0, 0, 0, 0))
        bus = os.stat_result((stat.S_IFSOCK|0o600, 1, 1, 1, 1000, 1000, 0, 0, 0, 0))
        with mock.patch.object(debug.Path, 'lstat', side_effect=[directory, bus]):
            self.assertIsNotNone(debug.user_command(USER, ['id']))
        bad = os.stat_result((stat.S_IFLNK|0o777, 1, 1, 1, 1000, 1000, 0, 0, 0, 0))
        with mock.patch.object(debug.Path, 'lstat', side_effect=[directory, bad]):
            self.assertIsNone(debug.user_command(USER, ['id']))

    @unittest.skipUnless(os.geteuid() == 0 and shutil.which('runuser'), 'real privilege drop needs root/runuser')
    def test_real_privilege_drop_and_environment_scrubbing(self):
        users = [u for u in pwd.getpwall() if 1000 <= u.pw_uid < 65534 and Path(u.pw_dir).is_dir()]
        if not users:
            self.skipTest('no ordinary local account')
        user = users[0]
        with mock.patch.object(debug.Path, 'lstat', side_effect=FileNotFoundError):
            command = debug.user_command(user, ['/usr/bin/python3', '-I', '-c',
                'import json,os; print(json.dumps([os.getuid(),os.geteuid(),os.getcwd(),os.getenv("HOME"),os.getenv("ROOT_SECRET")]))'], bus_required=False)
        with mock.patch.dict(debug.ENV, {'ROOT_SECRET': 'must not reach child'}):
            text, meta = debug.run(command)
        self.assertEqual(meta['status'], 'ok', text)
        self.assertEqual(json.loads(text), [user.pw_uid, user.pw_uid, user.pw_dir, user.pw_dir, None])


class ReportTests(Fixture):
    def report(self):
        if os.geteuid() != 0:
            self.skipTest('root-owned report fixture')
        with mock.patch.object(debug, 'LOGROOT', self.root/'reports'), mock.patch.object(debug, 'desktop_account', return_value=USER):
            return debug.Report(['codex'])

    def test_app_probes_never_execute_as_root(self):
        report = self.report()
        with mock.patch.object(report, 'user_probe', return_value=('', {'status': 'ok'})) as probe, mock.patch.object(report, 'codex_probe', return_value=('Commands:\n  doctor  Check installation\n', {'status': 'ok'})) as codex, mock.patch.object(report, 'command') as root_command:
            report.application('codex')
            report.application('chatgpt')
        root_command.assert_not_called()
        self.assertTrue(any(call.args[1] == ['doctor'] for call in codex.call_args_list))
        commands = [call.args[2] for call in probe.call_args_list]
        self.assertTrue(all('--user' in command for command in commands if command[0] == 'systemctl'))
        self.assertTrue(any('user-log' in command for command in commands))
        self.assertFalse(any(command[0] == '/usr/local/bin/chatgpt' for command in commands))

    def test_unknown_doctor_is_not_sent_as_prompt(self):
        report = self.report()
        with mock.patch.object(report, 'user_probe', return_value=('', {'status': 'ok'})), mock.patch.object(report, 'codex_probe', return_value=('Commands:\n  login  Authenticate\n', {'status': 'ok'})) as codex:
            report.application('codex')
        self.assertFalse(any(call.args[1] == ['doctor'] for call in codex.call_args_list))
        self.assertEqual(report.records[-1]['status'], 'unsupported-or-unavailable')

    def test_codex_cgroup_lifetime_and_cleanup_on_interrupt(self):
        report = self.report()
        def dropped(user, argv, *args, **kwargs):
            return ['runuser-fixture', *argv]
        with mock.patch.object(debug, 'user_command', side_effect=dropped), mock.patch.object(report, 'user_probe', side_effect=KeyboardInterrupt) as probe, mock.patch.object(debug, 'run') as run:
            with self.assertRaises(KeyboardInterrupt):
                report.codex_probe('codex-doctor', ['doctor'], timeout=60)
        argv = probe.call_args.args[2]
        for value in ('--user', '--collect', '--pipe', '--property=RuntimeMaxSec=60s', '--property=TimeoutStopSec=5s', '--property=KillMode=control-group', '--property=SendSIGKILL=yes'):
            self.assertIn(value, argv)
        self.assertIn(debug.CODEX, argv)
        unit = next(value.removeprefix('--unit=') for value in argv if value.startswith('--unit='))
        self.assertEqual(run.call_args.args[0][-4:], ['--user', '--no-block', 'stop', unit])

    def test_no_safe_session_records_absence_without_root_command(self):
        report = self.report()
        with mock.patch.object(debug, 'user_command', return_value=None), mock.patch.object(report, 'command') as command:
            report.user_probe('codex', 'state', ['systemctl', '--user', 'status'])
            report.codex_probe('version', ['--version'])
        command.assert_not_called()
        self.assertTrue(all(record['status'] == 'no-session' for record in report.records))

    def test_failed_unit_enumeration_is_bounded_and_explicit(self):
        report = self.report()
        lines = 'failed.service loaded failed failed Test\n--malicious invalid\n'
        with mock.patch.object(report, 'command', return_value=(lines, {'status': 'ok'})) as command:
            report.failed_units()
        self.assertIn('list-units', command.call_args_list[0].args[2])
        self.assertEqual(command.call_args.args[2][-2:], ['--', 'failed.service'])
        self.assertNotIn('--state=failed', command.call_args.args[2])
        lines = ''.join(f'unit{i}.service loaded failed failed Test\n' for i in range(70))
        with mock.patch.object(report, 'user_probe', return_value=(lines, {'status': 'ok'})) as command:
            report.failed_units(user=True)
        self.assertEqual(len(command.call_args.args[2][5:]), debug.MAX_FAILED_UNITS)
        self.assertEqual(report.records[-1]['status'], 'unit-count-limit')

    def test_protected_app_fallback_only_uses_trusted_fixed_log_paths(self):
        report = self.report()
        with mock.patch.object(report, 'user_probe', return_value=('', {'status': 'nonzero'})), mock.patch.object(report, 'codex_probe', return_value=None), mock.patch.object(debug, 'log_paths', side_effect=lambda path, **kw: ([path], False)) as paths, mock.patch.object(debug, 'log_text', return_value=('', {'status': 'unavailable'})) as read:
            report.application('codex')
        self.assertEqual(paths.call_count, 2)
        self.assertEqual(read.call_count, 2)
        self.assertTrue(all(call.kwargs == {'trusted': True} for call in read.call_args_list))
        self.assertEqual([str(call.args[0]) for call in read.call_args_list], list(debug.USER_LOGS['codex'][:2]))

    def test_boot_snapshots_select_three_latest_and_reject_symlink(self):
        report = self.report()
        boot = self.root/'boot'
        boot.mkdir()
        for index in range(1, 5):
            (boot/f'boot-{index}-2026-09-26-19-00-{index:032x}.log').write_text(f'snapshot {index}')
        (boot/'fss').write_text('never-read-seed')
        latest = boot/f'boot-5-2026-09-26-19-00-{5:032x}.log'
        latest.symlink_to(boot/'fss')
        with mock.patch.object(debug, 'BOOT_LOGS', boot):
            report.boot_logs('journal')
        text = '\n'.join(report.contents.values())
        self.assertIn('snapshot 4', text)
        self.assertIn('snapshot 3', text)
        self.assertNotIn('snapshot 2', text)
        self.assertNotIn('never-read-seed', text)
        self.assertEqual(report.records[0]['status'], 'snapshot-count-limit')

    def test_drm_debugfs_reads_are_isolated_bounded_and_cannot_escape(self):
        report = self.report()
        name = '/sys/kernel/debug/dri/0/state'
        with mock.patch.object(debug.Path, 'resolve', return_value=Path(name)), mock.patch.object(debug.Path, 'is_file', return_value=True), mock.patch.object(report, 'command') as command, mock.patch.object(debug, 'direct_text') as direct:
            report.file_evidence('gpu', name)
        command.assert_called_once_with('gpu', name, ['cat', '--', name], timeout=5, cap=debug.MAX_FILE)
        direct.assert_not_called()
        with mock.patch.object(debug.Path, 'resolve', return_value=Path('/etc/shadow')), mock.patch.object(report, 'command') as command:
            report.file_evidence('gpu', name)
        command.assert_not_called()
        self.assertEqual(report.records[-1]['status'], 'unsafe-debugfs-path')

    def test_shared_root_logs_preserve_coverage_without_duplicate_payload(self):
        report = self.report()
        path = self.root/'kernel.log'
        with mock.patch.object(debug, 'log_text', return_value=('atomic commit failed\n', {'status': 'output-limit'})) as read:
            report.root_log('hardware', path, 'kernel')
            report.root_log('gpu', path, 'kernel')
        read.assert_called_once_with(path, trusted=True)
        first, second = report.records
        self.assertEqual(second['status'], 'output-limit')
        self.assertEqual(second['reference_evidence'], first['evidence'])
        self.assertIn('atomic commit failed', (report.path/first['evidence']).read_text())
        self.assertIn(first['evidence'], (report.path/second['evidence']).read_text())

    def test_report_records_identity_and_redacts_all_evidence(self):
        report = self.report()
        with mock.patch.object(debug, 'user_command', return_value=['id']), mock.patch.object(debug, 'run', return_value=('api_key=opaque\n', {'status': 'ok'})):
            report.user_probe('codex', 'identity', ['id'])
        self.assertEqual(report.records[-1]['run_as_uid'], USER.pw_uid)
        evidence = report.path/report.records[-1]['evidence']
        self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o600)
        self.assertNotIn('opaque', evidence.read_text())


class MenuTests(unittest.TestCase):
    def test_plain_picker_retries_invalid_input(self):
        with mock.patch('builtins.input', side_effect=['9'*5000, 'bogus', '2']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(debug.terminal_choice('Fixture', ['A', 'B'], plain=True), 1)

    def test_comprehensive_menu_never_changes_boot_hooks(self):
        with mock.patch.object(debug, 'desktop_account', return_value=USER), mock.patch.object(debug, 'terminal_choice', side_effect=[0, None]), mock.patch.object(debug, 'lock', side_effect=contextlib.nullcontext), mock.patch.object(debug, 'collect') as collect, mock.patch.object(debug, 'change_hooks') as hooks, mock.patch('builtins.input', return_value=''):
            debug.menu()
        hooks.assert_not_called()
        self.assertEqual(collect.call_args.args[0], list(debug.CATEGORIES))
        self.assertEqual(collect.call_args.kwargs['user_name'], USER.pw_name)

    @unittest.skipUnless(shutil.which('infocmp'), 'terminal database is required')
    def test_real_arrow_navigation_and_escape_restore_terminal(self):
        for keys, expected in ((b'\x1bOB\r', b'SELECTED=1'), (b'\x1b', b'SELECTED=None')):
            master, slave = pty.openpty()
            before = termios.tcgetattr(slave)
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 100, 0, 0))
            code = ('import runpy; m=runpy.run_path('+repr(str(SCRIPT))+'); '
                    'print("SELECTED="+str(m["terminal_choice"]("fixture",["first","second"])), flush=True)')
            proc = subprocess.Popen([sys.executable, '-I', '-B', '-c', code], stdin=slave, stdout=slave, stderr=slave,
                                    env={**os.environ, 'TERM': 'xterm-256color'}, start_new_session=True)
            output = bytearray()
            try:
                deadline = time.monotonic()+8
                while b'No action runs' not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], .2)[0]:
                        output.extend(os.read(master, 65536))
                self.assertIn(b'No action runs', output)
                os.write(master, keys)
                while proc.poll() is None and time.monotonic() < deadline:
                    if select.select([master], [], [], .2)[0]:
                        output.extend(os.read(master, 65536))
                proc.wait(timeout=2)
                while select.select([master], [], [], .1)[0]:
                    output.extend(os.read(master, 65536))
                self.assertEqual(proc.returncode, 0, bytes(output))
                self.assertIn(expected, output)
                self.assertEqual(termios.tcgetattr(slave), before)
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=2)
                os.close(master)
                os.close(slave)


if __name__ == '__main__':
    unittest.main()
