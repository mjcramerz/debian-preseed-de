"""Focused regressions; no host power, user-manager, or mount operations."""
from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock
import test_desktop_sandbox as desktop
import test_power_runtime_20260920 as power_tests
from payload_fixture import read_text


class WrapperRegressionTests(unittest.TestCase):
    def setUp(self):
        self.c = desktop.load_script(desktop.DESKTOP / 'data/codex/lib/codex', 'codex_regression')

    def test_wrapper_flags_are_only_a_prefix(self):
        for argv in (['exec', '--no-bwrap'], ['--', '--isolated-network'],
                     ['exec', '--', '--no-bwrap'], ['a prompt', '--isolated-network']):
            with self.subTest(argv=argv):
                enabled, actual = self.c.codex_parse_arguments(argv)
                self.assertTrue(enabled)
                self.assertEqual(actual, argv)
                self.assertFalse(self.c.CODEX_ISOLATED_NETWORK)

    def test_default_and_explicit_isolated_network(self):
        enabled, actual = self.c.codex_parse_arguments(['--isolated-network', 'exec', 'hello'])
        self.assertTrue(enabled and self.c.CODEX_ISOLATED_NETWORK)
        self.assertEqual(actual, ['exec', 'hello'])
        self.c.codex_parse_arguments([])
        self.assertFalse(self.c.CODEX_ISOLATED_NETWORK)

    def test_incompatible_modes_are_rejected(self):
        for argv in (['--isolated-network', '--no-bwrap'],
                     ['--no-bwrap', '--isolated-network'],
                     ['--no-bwrap', *self.c.CODEX_APP_SERVER_ARGUMENTS]):
            with self.subTest(argv=argv), self.assertRaises(self.c.CodexError):
                self.c.codex_parse_arguments(argv)

    def test_mount_plan_keeps_isolation_without_default_network_namespace(self):
        fixture = desktop.CodexTests()
        fixture.codex = self.c
        for isolated in (False, True):
            self.c.CODEX_ISOLATED_NETWORK = isolated
            args = fixture.bwrap_arguments()
            self.assertEqual(args.count('--unshare-net'), int(isolated))
            for flag in ('--unshare-user', '--unshare-pid', '--unshare-ipc', '--unshare-uts'):
                self.assertIn(flag, args)
            self.assertFalse(any('installation_id' in value for value in args))

    def test_both_network_modes_release_payload_and_reap_supervision(self):
        for isolated in (False, True):
            with self.subTest(isolated=isolated), tempfile.TemporaryDirectory() as tmp:
                self.c.CODEX_CONTROL_DIR = tmp
                self.c.CODEX_ISOLATED_NETWORK = isolated
                self.c.CODEX_ARGS = ['exec', 'hello']
                processes = [mock.Mock(), mock.Mock()]
                for process in processes:
                    process.poll.return_value = None
                    process.wait.return_value = 0
                pidfd = os.open('/dev/null', os.O_RDONLY)
                with mock.patch.object(self.c, 'codex_prepare_control_state'), \
                     mock.patch.object(self.c, 'codex_prepare_identity_files'), \
                     mock.patch.object(self.c, 'codex_build_bwrap_args', return_value=['bwrap']), \
                     mock.patch.object(self.c, 'codex_clear_app_server_environment') as clear, \
                     mock.patch.object(self.c, '_read_json_fd', return_value=b'{"child-pid":4321}'), \
                     mock.patch.object(self.c, '_pid_alive', return_value=True), \
                     mock.patch.object(self.c.os, 'pidfd_open', return_value=pidfd), \
                     mock.patch.object(self.c.os, 'write', return_value=1) as release, \
                     mock.patch.object(self.c, '_read_ready_byte', return_value=b'1') as ready, \
                     mock.patch.object(self.c.subprocess, 'Popen', side_effect=processes) as spawn:
                    self.assertEqual(self.c.codex_run_sandboxed(), 0)
                    self.assertEqual(spawn.call_count, 2 if isolated else 1)
                    self.assertEqual(ready.call_count, int(isolated))
                    clear.assert_called_once()
                    release.assert_called_once()
                    self.assertEqual(release.call_args.args[1], b'1')
                    self.assertEqual(spawn.call_args_list[0].args[0][-2:], ['exec', 'hello'])
                self.assertIsNone(self.c.CODEX_BWRAP_PROCESS)
                self.assertIsNone(self.c.CODEX_SLIRP_PROCESS)
                self.assertIsNone(self.c.CODEX_SANDBOX_PIDFD)
                with self.assertRaises(OSError): os.fstat(pidfd)

    def test_client_environment_is_explicit_bounded_and_not_loader_environment(self):
        allowed = {'RUST_LOG': 'debug', 'TERM': 'xterm-256color',
                   'HTTPS_PROXY': 'http://127.0.0.1:3128', 'NO_PROXY': 'localhost'}
        with mock.patch.dict(os.environ, {**allowed, 'LD_PRELOAD': '/tmp/bad.so',
                                         'PYTHONPATH': '/tmp', 'UNRELATED': 'secret'}, clear=True):
            self.assertEqual(self.c.codex_client_environment(), allowed)
        for value in ('x' * 65537, 'debug\nsecret', 'debug\rsecret', '\udcff'):
            with mock.patch.dict(os.environ, {'RUST_LOG': value}, clear=True), \
                 self.assertRaises(self.c.CodexError):
                self.c.codex_client_environment()

    def test_total_client_environment_size_is_bounded(self):
        values = {name: 'x' * 65536 for name in sorted(self.c.CLIENT_ENVIRONMENT_NAMES)[:5]}
        with mock.patch.dict(os.environ, values, clear=True), self.assertRaises(self.c.CodexError):
            self.c.codex_client_environment()

    def test_client_environment_survives_managed_profile_reconstruction(self):
        def profile():
            os.environ.clear()
            os.environ.update(HOME='/home/desktop', USER='desktop', PATH='/usr/bin:/bin')
        with mock.patch.dict(os.environ, {'RUST_LOG': 'debug', 'TERM': 'screen'}, clear=True), \
             mock.patch.object(self.c, 'codex_activate_devops_environment', side_effect=profile), \
             mock.patch.object(self.c, 'codex_sanitize_path'):
            self.c.codex_prepare_environment()
            self.assertEqual(os.environ['RUST_LOG'], 'debug')
            self.assertEqual(os.environ['TERM'], 'screen')
            self.assertEqual(os.environ['CODEX_HOME'], self.c.CODEX_RUNTIME_HOME)

    def test_client_values_do_not_enter_bubblewrap_argv(self):
        with mock.patch.dict(os.environ, {'RUST_LOG': 'debug', 'HTTPS_PROXY': 'secret-proxy'}, clear=True):
            self.assertEqual(self.c._managed_environment_names(dict(os.environ)), [])

    def test_resolver_uses_host_snapshot_only_for_host_network(self):
        for isolated in (False, True):
            with self.subTest(isolated=isolated), tempfile.TemporaryDirectory() as tmp, \
                 mock.patch.object(self.c, 'codex_control_root', return_value=tmp), \
                 mock.patch.dict(os.environ, HOME='/home/desktop'), \
                 mock.patch.object(self.c, 'codex_generate_uuid', return_value='12345678-1234-1234-1234-123456789abc'), \
                 mock.patch.object(self.c, '_read_bounded_text', return_value='nameserver 127.0.0.53') as read:
                self.c.CODEX_ISOLATED_NETWORK = isolated
                directory = Path(self.c.codex_prepare_identity_files(os.getuid(), os.getgid()))
                expected = self.c.CODEX_RESOLVER_CONFIGURATION if isolated else b'nameserver 127.0.0.53\n'
                self.assertEqual((directory/'resolv.conf').read_bytes(), expected)
                self.assertFalse((directory/'installation_id').exists())
                self.assertEqual(read.call_count, int(not isolated))


class BackendReadinessTests(unittest.TestCase):
    def setUp(self):
        self.ready = desktop.load_script(desktop.DESKTOP/'usr/local/libexec/codex-app-server-wait-ready', 'ready_regression')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'backend.sock'
        self.ready.BACKEND_SOCKET = str(self.path)
        self.ready.READY_TIMEOUT_SECONDS = 0.025
        self.ready.POLL_INTERVAL_SECONDS = 0.005

    def test_bound_but_not_listening_endpoint_is_not_ready(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(self.path)); self.path.chmod(0o600)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.ready.main([]), 1)

    def test_owned_private_listening_endpoint_is_ready(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(self.path)); self.path.chmod(0o600); listener.listen(1)
            self.assertEqual(self.ready.main([]), 0)

    def test_symlinks_and_public_sockets_are_not_ready(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(self.path)); listener.listen(1); self.path.chmod(0o666)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.ready.main([]), 1)
            self.path.chmod(0o600)
            link = self.path.with_name('link'); link.symlink_to(self.path)
            self.ready.BACKEND_SOCKET = str(link)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.ready.main([]), 1)


class PowerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.p = power_tests.module()

    def test_typed_session_list_and_exact_transport(self):
        raw = json.dumps({'type': 'a(susso)', 'data': [[['c1', 1000, 'desktop', 'seat0',
                          '/org/freedesktop/login1/session/c1']]]})
        with mock.patch.object(self.p, 'run', return_value=raw) as run:
            self.assertEqual(self.p.login_sessions(), [('c1', 1000)])
        self.assertEqual(run.call_args.args[0][-1], 'ListSessions')
        self.assertEqual(run.call_args.kwargs['max_output'], 131072)

    def test_session_parser_rejects_malformed_or_ambiguous_records(self):
        good = ['c1', 1000, 'desktop', 'seat0', '/org/freedesktop/login1/session/c1']
        malformed = ['null', '{', '[]', json.dumps({'type':'s','data':[[]]})]
        for row in ([True, *good[1:]], [good[0], True, *good[2:]],
                    [good[0], -1, *good[2:]], [*good[:4], '/wrong/path'],
                    ['bad;id', *good[1:]], good[:-1]):
            malformed.append(json.dumps({'type':'a(susso)', 'data':[[row]]}))
        malformed.append(json.dumps({'type':'a(susso)', 'data':[[good, good]]}))
        malformed.append(' ' * 131073)
        for raw in malformed:
            with self.subTest(raw=raw[:80]), mock.patch.object(self.p, 'run', return_value=raw), \
                 self.assertRaises(self.p.Error):
                self.p.login_sessions()

    def test_force_occurs_only_after_sync_and_reservation_recheck(self):
        events = []
        w = self.p.Worker(1000, 'desktop', 'reboot'); w.quiesced = True
        w.package_locks = mock.Mock()
        w.package_locks.verify.side_effect = lambda: events.append('verify')
        with mock.patch.object(w, 'protect_other_sessions', side_effect=lambda: events.append('accounts')), \
             mock.patch.object(self.p, 'check_shutdown_inhibitors', side_effect=lambda **kw: events.append(('inhibitors',kw))), \
             mock.patch.object(self.p.os, 'sync', side_effect=lambda: events.append('sync')), \
             mock.patch.object(self.p, 'run', side_effect=lambda argv, **kw: events.append(argv)), \
             contextlib.redirect_stderr(io.StringIO()):
            w.final_power_action()
            self.assertEqual(events[-1], ['/usr/bin/systemctl','--force','--no-ask-password','reboot'])
            self.assertIn(('inhibitors', {'force':True}), events)
            self.assertEqual(events[events.index('sync')+1], 'verify')
            with self.assertRaises(self.p.Error): w.final_power_action()
        self.assertEqual(sum(isinstance(e,list) and '--force' in e for e in events), 1)

    def test_sync_failure_never_submits_force(self):
        w = self.p.Worker(1000, 'desktop', 'poweroff'); w.quiesced = True
        w.package_locks = mock.Mock()
        with mock.patch.object(w, 'protect_other_sessions'), \
             mock.patch.object(self.p, 'check_shutdown_inhibitors'), \
             mock.patch.object(self.p.os, 'sync', side_effect=OSError('sync failed')), \
             mock.patch.object(self.p, 'run') as run:
            with self.assertRaises(OSError): w.final_power_action()
            run.assert_not_called()
            self.assertFalse(w.handoff_attempted)

    def test_preflight_failure_diagnostics_are_in_journal(self):
        unit = read_text(desktop.DESKTOP/'etc/systemd/system/labwc-admin-action@.service')
        self.assertIn('StandardError=journal', unit)
        self.assertNotIn('StandardError=inherit', unit)


if __name__ == '__main__':
    unittest.main()
