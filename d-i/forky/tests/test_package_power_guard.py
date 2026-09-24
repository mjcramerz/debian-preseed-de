#!/usr/bin/env python3
"""Package/power safety regressions. Never invoke host systemctl or logind.

Kernel-lock tests use root-owned temporary files and disposable child processes.
All power, session, and readiness endpoints are intercepted at explicit test
boundaries; the actual production lock implementation is executed unchanged.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_is_file as payload_source_is_file
from payload_fixture import installed_script
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

import ast
import contextlib
import errno
import fcntl
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
WORKER = TARGET / 'usr/local/libexec/labwc-admin-action-worker'
ROOT = TARGET.parents[3]


def module():
    loader = importlib.machinery.SourceFileLoader('package_power_test', str(installed_script(WORKER)))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


HOLDER = r'''
import fcntl,os,sys
fd=os.open(sys.argv[1],os.O_RDWR)
fcntl.lockf(fd,fcntl.LOCK_EX,0,0,os.SEEK_SET)
print('LOCKED',flush=True)
sys.stdin.readline()
os.close(fd)
print('RELEASED',flush=True)
'''
PROBE = r'''
import errno,fcntl,os,sys
fd=os.open(sys.argv[1],os.O_RDWR)
try:
    fcntl.lockf(fd,fcntl.LOCK_EX|fcntl.LOCK_NB,0,0,os.SEEK_SET)
except OSError as exc:
    if exc.errno not in (errno.EACCES,errno.EAGAIN): raise
    sys.exit(73)
finally:
    os.close(fd)
'''


@unittest.skipUnless(os.geteuid() == 0, 'root-owned temporary dpkg lock fixtures require root')
class LockFixture(unittest.TestCase):
    def setUp(self):
        self.power = module()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='package-power-')))
        self.action_directory = self.directory / 'power'
        self.action_directory.mkdir(mode=0o700)
        self.stack.enter_context(mock.patch.object(self.power, 'ACTION_LOCK_DIRECTORY', self.action_directory))
        self.paths = tuple(self.directory / name for name in ('lock-frontend', 'lock'))
        for path in self.paths:
            path.write_bytes(b'')
            path.chmod(0o640)
        self.stack.enter_context(mock.patch.object(self.power, 'PACKAGE_LOCK_PATHS', self.paths))
        self.stack.enter_context(mock.patch.object(self.power, 'status'))
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.real_sleep = time.sleep
        self.stack.enter_context(mock.patch.object(self.power, 'time', SimpleNamespace(
            sleep=lambda _: self.real_sleep(.01), monotonic=time.monotonic)))
        # This trap is intentionally present for every kernel-level test.
        self.stack.enter_context(mock.patch.object(self.power, 'run', side_effect=AssertionError('real power command forbidden')))

    def holder(self, path, *, action_lock=False):
        program = HOLDER.replace('fcntl.lockf(fd,fcntl.LOCK_EX,0,0,os.SEEK_SET)',
                                 'fcntl.flock(fd,fcntl.LOCK_EX)') if action_lock else HOLDER
        child = subprocess.Popen(payload_installed_argv([sys.executable, '-c', program, str(path)]),
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, close_fds=True)
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            child.stdin.close(); child.stdout.close(); child.stderr.close()
        self.addCleanup(cleanup)
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(5), 'fixture writer did not acquire its lock')
        self.assertEqual(child.stdout.readline().strip(), 'LOCKED')
        return child

    def release(self, child):
        child.stdin.write('release\n'); child.stdin.flush()
        self.assertEqual(child.stdout.readline().strip(), 'RELEASED')
        self.assertEqual(child.wait(timeout=5), 0)

    def assert_writer(self, path, *, blocked):
        result = subprocess.run(payload_installed_argv([sys.executable, '-c', PROBE, str(path)]),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 73 if blocked else 0, result.stderr)


class KernelLockTests(LockFixture):
    def test_existing_unlocked_files_do_not_cause_a_wait(self):
        wait = mock.Mock()
        with self.power.PackageLocks(wait) as guard:
            guard.verify()
            for path in self.paths:
                self.assert_writer(path, blocked=True)
        wait.assert_not_called()
        for path in self.paths:
            self.assert_writer(path, blocked=False)
            self.assertEqual(payload_read_bytes(path), b'')

    def test_frontend_writer_finishes_before_readiness(self):
        child = self.holder(self.paths[0])
        def wait():
            self.assertIsNone(child.poll())
            self.release(child)
        with self.power.PackageLocks(wait) as guard:
            guard.verify()
        self.assertEqual(child.returncode, 0)

    def test_backend_writer_also_blocks_even_with_free_frontend(self):
        child = self.holder(self.paths[1])
        seen = []
        def wait():
            seen.append('waiting')
            # Partial frontend reservation MUST be dropped while backend waits.
            self.assert_writer(self.paths[0], blocked=False)
            self.release(child)
        with self.power.PackageLocks(wait):
            self.assertEqual(seen, ['waiting'])
            for path in self.paths:
                self.assert_writer(path, blocked=True)

    def test_both_writers_are_waited_for_not_just_frontend(self):
        first = self.holder(self.paths[0]); second = self.holder(self.paths[1])
        waits = []
        def sleep(_):
            waits.append(len(waits))
            if len(waits) == 1:
                self.release(first)
            elif len(waits) == 2:
                self.release(second)
            else:
                self.fail('locks not released after writers completed')
        with mock.patch.object(self.power.time, 'sleep', side_effect=sleep):
            with self.power.PackageLocks():
                self.assertEqual(len(waits), 2)

    def test_busy_lock_has_no_elapsed_time_cutoff(self):
        child = self.holder(self.paths[0]); polls = []
        def sleep(_):
            polls.append(1)
            if len(polls) == 4:
                self.release(child)
        with mock.patch.object(self.power.time, 'monotonic', side_effect=[0, 10000, 100000, 1000000]), \
             mock.patch.object(self.power.time, 'sleep', side_effect=sleep):
            with self.power.PackageLocks():
                self.assertEqual(len(polls), 4)

    def test_missing_lock_fails_closed_without_creating_it(self):
        self.paths[0].unlink()
        with self.assertRaises(FileNotFoundError):
            with self.power.PackageLocks():
                self.fail('missing lock accepted')
        self.assertFalse(payload_source_exists(self.paths[0]))

    def test_symlink_fifo_directory_hardlink_and_writable_lock_fail_closed(self):
        first = self.paths[0]
        first.unlink(); first.symlink_to(self.paths[1])
        with self.assertRaises(OSError):
            with self.power.PackageLocks(): pass
        first.unlink(); os.mkfifo(first, 0o600)
        with self.assertRaises(self.power.Error):
            with self.power.PackageLocks(): pass
        first.unlink(); first.mkdir()
        with self.assertRaises(self.power.Error):
            with self.power.PackageLocks(): pass
        first.rmdir(); os.link(self.paths[1], first)
        with self.assertRaises(self.power.Error):
            with self.power.PackageLocks(): pass
        first.unlink(); first.touch(mode=0o666); first.chmod(0o666)
        with self.assertRaises(self.power.Error):
            with self.power.PackageLocks(): pass
        self.assert_writer(self.paths[1], blocked=False)

    def test_nonroot_owned_lock_is_rejected(self):
        os.chown(self.paths[0], 65534, 65534)
        with self.assertRaises(self.power.Error):
            with self.power.PackageLocks(): pass

    def test_missing_second_lock_releases_the_first(self):
        self.paths[1].unlink()
        with self.assertRaises(FileNotFoundError):
            with self.power.PackageLocks(): pass
        self.assert_writer(self.paths[0], blocked=False)

    def test_changed_inode_is_detected_before_handoff(self):
        with self.power.PackageLocks() as guard:
            self.paths[1].unlink(); self.paths[1].touch(mode=0o600)
            with self.assertRaisesRegex(self.power.Error, 'changed'):
                guard.verify()

    def test_unexpected_fcntl_error_does_not_become_a_wait_or_success(self):
        with mock.patch.object(self.power.fcntl, 'lockf', side_effect=OSError(errno.EBADF, 'injected')):
            with self.assertRaises(OSError):
                with self.power.PackageLocks(): pass
        self.assert_writer(self.paths[0], blocked=False)

    def test_interrupted_lock_acquisition_retries_without_leaking_partial_locks(self):
        actual = fcntl.lockf; seen = []
        def lock(*args):
            seen.append(1)
            if len(seen) == 1:
                raise OSError(errno.EINTR, 'interrupted')
            return actual(*args)
        with mock.patch.object(self.power.fcntl, 'lockf', side_effect=lock):
            with self.power.PackageLocks():
                self.assertEqual(len(seen), 3)
        self.assert_writer(self.paths[0], blocked=False)

    def test_exception_cancellation_releases_both_reservations(self):
        with self.assertRaisesRegex(RuntimeError, 'cancel'):
            with self.power.PackageLocks():
                raise RuntimeError('cancel')
        for path in self.paths:
            self.assert_writer(path, blocked=False)

    def test_descriptors_are_readonly_and_close_on_exec(self):
        with self.power.PackageLocks() as guard:
            for _, fd in guard.fds:
                self.assertEqual(fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE, os.O_RDONLY)
                self.assertTrue(fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)

    def test_sigterm_releases_child_reservation_without_touching_lock_files(self):
        code = '''import pathlib,runpy,sys
m=runpy.run_path(sys.argv[1],run_name='fixture')
g=m['PackageLocks'].__enter__.__globals__
g['PACKAGE_LOCK_PATHS']=tuple(pathlib.Path(p) for p in sys.argv[2:])
with m['PackageLocks']():
 print('LOCKED',flush=True)
 m['hold_reservation']()
'''
        proc = subprocess.Popen(payload_installed_argv([sys.executable, '-c', code, str(WORKER), *map(str,self.paths)]),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(5))
            self.assertEqual(proc.stdout.readline().strip(), 'LOCKED')
            for path in self.paths: self.assert_writer(path, blocked=True)
            proc.terminate(); proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, -signal.SIGTERM)
            for path in self.paths: self.assert_writer(path, blocked=False)
        finally:
            if proc.poll() is None: proc.kill()
            proc.communicate(timeout=5)


class WorkerFlowTests(LockFixture):
    # Power endpoints are mocked; the underlying package locks remain real.
    def worker(self, action, *, greeter=False):
        worker = self.power.Worker(1000, 'desktop', action, greeter=greeter)
        self.events = []
        self.stack.enter_context(mock.patch.object(self.power, 'check_shutdown_inhibitors',
            side_effect=lambda: self.events.append(('inhibitors', ()))))
        for name in ('lock', 'protect_other_sessions', 'helper', 'terminate_user',
                     'quiesce_desktop', 'stop_optional_guests', 'final_power_action'):
            self.stack.enter_context(mock.patch.object(worker, name,
                side_effect=lambda *a, _name=name, **kw: self.events.append((_name, a))))
        self.stack.enter_context(mock.patch.object(worker, 'session_identity', return_value='a'*32))
        self.stack.enter_context(mock.patch.object(self.power, 'ready', side_effect=lambda: self.events.append(('ready', ()))))
        self.stack.enter_context(mock.patch.object(self.power, 'hold_reservation', side_effect=lambda: self.events.append(('hold', ()))))
        return worker

    def test_every_requested_desktop_action_waits_before_destructive_work(self):
        for action in ('poweroff', 'reboot', 'logout', 'suspend'):
            with self.subTest(action=action):
                worker = self.worker(action)
                child = self.holder(self.paths[0])
                def wait():
                    self.assertIsNone(child.poll())
                    self.assertIn(('ready', ()), self.events)
                    forbidden = {'terminate_user', 'quiesce_desktop', 'final_power_action', 'run'}
                    self.assertFalse(any(e[0] in forbidden or e == ('helper', ('prepare',)) for e in self.events))
                    self.release(child)
                def action_run(argv, **kwargs):
                    self.events.append(('run', (tuple(argv),)))
                    for path in self.paths: self.assert_writer(path, blocked=True)
                    return ''
                with mock.patch.object(worker, 'package_waiting', side_effect=wait), \
                     mock.patch.object(self.power, 'run', side_effect=action_run):
                    worker.execute()
                self.assertIsNone(worker.package_locks)
                for path in self.paths: self.assert_writer(path, blocked=False)
                if action == 'suspend':
                    self.assertNotIn(('helper', ('prepare',)), self.events)
                    self.assertIn(('helper', ('locked',)), self.events)
                else:
                    self.assertIn(('helper', ('prepare',)), self.events)

    def test_greeter_waits_without_touching_any_desktop(self):
        for action in ('poweroff','reboot'):
            worker = self.worker(action, greeter=True)
            child = self.holder(self.paths[0])
            with mock.patch.object(worker, 'package_waiting', side_effect=lambda: self.release(child)), \
                 mock.patch.object(self.power, 'run', return_value='') as run:
                worker.execute()
            worker.helper.assert_not_called(); worker.quiesce_desktop.assert_not_called()
            worker.terminate_user.assert_not_called(); worker.session_identity.assert_not_called()
            run.assert_not_called()  # Guest/final helpers are boundary mocks here.
            worker.stop_optional_guests.assert_called_once_with()
            worker.final_power_action.assert_called_once_with()
            self.assertLess(self.events.index(('inhibitors', ())),
                            self.events.index(('stop_optional_guests', ())))
            self.assertLess(self.events.index(('stop_optional_guests', ())),
                            self.events.index(('final_power_action', ())))
            self.assertEqual(self.events[-1], ('hold', ()))

    def test_session_replacement_during_wait_cancels_without_closing_new_session(self):
        worker = self.worker('logout')
        worker.session_identity.side_effect=['a'*32,'b'*32]
        with self.assertRaisesRegex(self.power.Error, 'session changed'):
            worker.execute()
        worker.helper.assert_not_called(); worker.terminate_user.assert_not_called()

    def test_prepare_cancel_releases_locks_and_prevents_teardown(self):
        worker = self.worker('reboot')
        worker.helper.side_effect=self.power.Error('unsaved document')
        with self.assertRaises(self.power.Error): worker.execute()
        worker.quiesce_desktop.assert_not_called(); worker.final_power_action.assert_not_called()
        for path in self.paths: self.assert_writer(path, blocked=False)

    def test_missing_package_lock_never_prepares_suspends_or_tears_down(self):
        worker = self.worker('reboot'); self.paths[0].unlink()
        with self.assertRaises(FileNotFoundError): worker.execute()
        worker.helper.assert_not_called(); worker.final_power_action.assert_not_called()

    def test_destructive_methods_cannot_be_called_without_reservation(self):
        worker = self.power.Worker(1000,'desktop','logout')
        for method in (worker.terminate_user, worker.quiesce_desktop, worker.final_power_action):
            worker.action = 'logout' if method == worker.terminate_user else 'reboot'
            worker.quiesced = True
            with self.assertRaisesRegex(self.power.Error, 'reservation'):
                method()
        self.power.run.assert_not_called()

    def test_sleep_guard_readiness_is_after_release_and_locks_stay_held(self):
        child=self.holder(self.paths[0]); events=[]
        def status(_):
            if child.poll() is None: self.release(child)
        def ready():
            for path in self.paths: self.assert_writer(path,blocked=True)
            events.append('ready')
        def hold():
            for path in self.paths: self.assert_writer(path,blocked=True)
            events.append('hold')
        with mock.patch.object(self.power, 'status', side_effect=status), \
             mock.patch.object(self.power, 'ready', side_effect=ready), \
             mock.patch.object(self.power, 'hold_reservation', side_effect=hold):
            self.assertEqual(self.power.sleep_guard(), 0)
        self.assertEqual(events,['ready','hold'])

    def test_sleep_waits_for_desktop_action_without_holding_package_locks(self):
        path = self.action_directory / 'action.lock'
        path.touch(mode=0o600)
        child = self.holder(path, action_lock=True)
        events = []
        def status(message):
            if message.startswith('Waiting for the existing'):
                for package in self.paths: self.assert_writer(package, blocked=False)
                self.assertIsNone(child.poll())
                self.release(child)
                events.append('desktop-finished')
        def ready():
            for package in self.paths: self.assert_writer(package, blocked=True)
            events.append('ready')
        def hold():
            with self.assertRaisesRegex(self.power.Error, 'another managed power'):
                with self.power.action_lock(): self.fail('concurrent desktop action accepted')
            events.append('hold')
        with mock.patch.object(self.power, 'status', side_effect=status), \
             mock.patch.object(self.power, 'ready', side_effect=ready), \
             mock.patch.object(self.power, 'hold_reservation', side_effect=hold):
            self.assertEqual(self.power.sleep_guard(), 0)
        self.assertEqual(events, ['desktop-finished', 'ready', 'hold'])
        # Resume/service completion releases action serialization too.
        with self.power.action_lock(): pass

    def test_serialization_lock_is_validated_and_released_on_failure(self):
        path = self.action_directory / 'action.lock'
        with self.assertRaisesRegex(RuntimeError, 'cancel'):
            with self.power.action_lock(): raise RuntimeError('cancel')
        with self.power.action_lock(): pass
        path.chmod(0o666)
        with self.assertRaisesRegex(self.power.Error, 'unsafe system power'):
            with self.power.action_lock(): pass
        path.unlink(); path.symlink_to(self.paths[0])
        with self.assertRaises(OSError):
            with self.power.action_lock(): pass

    def test_invalid_sleep_lock_never_acknowledges_readiness(self):
        self.paths[1].unlink()
        with mock.patch.object(self.power, 'ready') as ready, \
             mock.patch.object(self.power, 'hold_reservation') as hold:
            with self.assertRaises(FileNotFoundError): self.power.sleep_guard()
            ready.assert_not_called(); hold.assert_not_called()


class GreeterUITests(unittest.TestCase):
    """Exercise actual UI methods without importing GTK or starting a display."""
    def setUp(self):
        source = payload_read_text(TARGET/'usr/local/bin/labwc-greeter-power')
        tree = ast.parse(source)
        definition = next(node for node in tree.body
                          if isinstance(node, ast.ClassDef) and node.name == 'GreeterPower')
        self.glib = SimpleNamespace(SOURCE_REMOVE=False, SOURCE_CONTINUE=True,
                                    timeout_add=mock.Mock(), timeout_add_seconds=mock.Mock())
        self.process_api = mock.Mock(DEVNULL=subprocess.DEVNULL)
        namespace = {'GLib': self.glib, 'subprocess': self.process_api,
                     'ACTION_HELPER': '/usr/local/sbin/greetd-power-action'}
        exec(compile(ast.Module(body=[definition], type_ignores=[]), '<greeter-ui>', 'exec'), namespace)
        cls = namespace['GreeterPower']
        self.ui = cls.__new__(cls)
        self.ui.pending_action = None
        self.ui.action_process = None
        self.ui.buttons = {name: (mock.Mock(), label)
                           for name, label in (('reboot', 'Reboot'), ('poweroff', 'Shutdown'))}
        self.button = self.ui.buttons['poweroff'][0]

    def queue(self):
        self.ui.request_action(self.button, 'poweroff')
        self.process_api.Popen.assert_not_called()
        self.ui.request_action(self.button, 'poweroff')
        self.process_api.Popen.assert_called_once()
        return self.ui.action_process

    def test_confirmation_timer_does_not_reenable_queued_action(self):
        child = self.queue()
        for button, _ in self.ui.buttons.values(): button.reset_mock()
        self.ui.reset_pending('poweroff')
        self.assertIs(self.ui.action_process, child)
        for button, _ in self.ui.buttons.values(): button.set_sensitive.assert_not_called()

    def test_duplicate_click_while_waiting_does_not_spawn_second_request(self):
        self.queue()
        self.ui.request_action(self.button, 'poweroff')
        self.ui.request_action(self.ui.buttons['reboot'][0], 'reboot')
        self.process_api.Popen.assert_called_once()

    def test_pending_process_keeps_ui_queued(self):
        child = self.queue(); child.poll.return_value = None
        self.assertTrue(self.ui.check_action())
        self.assertIs(self.ui.action_process, child)
        self.assertEqual(self.ui.pending_action, 'poweroff')

    def test_failed_request_restores_buttons(self):
        child = self.queue(); child.poll.return_value = 1
        self.assertFalse(self.ui.check_action())
        self.assertIsNone(self.ui.action_process)
        self.assertIsNone(self.ui.pending_action)
        for button, label in self.ui.buttons.values():
            button.set_sensitive.assert_called_with(True)
            button.set_label.assert_called_with(label)

    def test_cleanly_cancelled_unit_restores_buttons(self):
        child = self.queue(); child.poll.return_value = 0
        self.assertFalse(self.ui.check_action())
        self.assertIsNone(self.ui.pending_action)
        for button, _ in self.ui.buttons.values(): button.set_sensitive.assert_called_with(True)

    def test_spawn_failure_restores_buttons(self):
        self.process_api.Popen.side_effect = OSError('not executable')
        self.ui.request_action(self.button, 'poweroff')
        self.ui.request_action(self.button, 'poweroff')
        self.assertIsNone(self.ui.action_process)
        self.assertIsNone(self.ui.pending_action)
        for button, _ in self.ui.buttons.values(): button.set_sensitive.assert_called_with(True)


class WiringTests(unittest.TestCase):
    def test_required_sleep_guard_is_before_sleep_and_retained_until_resume(self):
        unit=payload_read_text(TARGET/'etc/systemd/system/labwc-package-sleep-guard.service')
        dropin=payload_read_text(TARGET/'etc/systemd/system/sleep.target.d/50-package-lock-guard.conf')
        for text in ('Type=notify','Before=sleep.target','StopWhenUnneeded=yes',
                     'TimeoutStartSec=infinity','RuntimeMaxSec=infinity','--sleep-guard',
                     'ProtectSystem=strict','CapabilityBoundingSet=','NoNewPrivileges=yes',
                     'RuntimeDirectory=labwc-power','RuntimeDirectoryMode=0700'):
            self.assertIn(text,unit)
        self.assertIn('Requires=labwc-package-sleep-guard.service',dropin)
        self.assertNotIn('Wants=',dropin)
        self.assertNotIn('ConditionPathExists',unit)

    def test_power_unit_has_no_upgrade_wait_deadline(self):
        text=payload_read_text(TARGET/'etc/systemd/system/labwc-admin-action@.service')
        self.assertIn('RuntimeMaxSec=infinity',text)
        self.assertIn('TimeoutStartSec=60s',text)
        self.assertIn('KillMode=control-group',text)
        self.assertIn('ProtectSystem=strict',text)

    def test_readonly_record_lock_permission_not_database_write(self):
        text=payload_read_text(TARGET/'etc/apparmor.d/desktop-wrappers')
        profile=text.split('profile labwc-admin-action-worker ',1)[1].split('\n}',1)[0]
        self.assertIn('/var/lib/dpkg/{lock,lock-frontend} rk,',profile)
        self.assertNotIn('/var/lib/dpkg/**',profile)
        self.assertNotIn('capability dac_override',profile)

    def test_all_new_assets_are_staged_and_verified(self):
        seed=TARGET.parents[1]
        stage=payload_read_text(seed/'scripts/desktop/components.sh')
        verify=payload_read_text(seed/'scripts/desktop/verify.sh')
        firstboot=payload_read_text(seed/'scripts/firstboot/04-validation.sh')
        for path in ('usr/local/libexec/greetd-power-action-root',
                     'etc/systemd/system/labwc-package-sleep-guard.service',
                     'etc/systemd/system/sleep.target.d/50-package-lock-guard.conf'):
            self.assertTrue(payload_source_is_file(TARGET/path))
            self.assertIn(path,stage); self.assertIn('/'+path,verify); self.assertIn('/'+path,firstboot)

    def test_greeter_only_gets_exact_fixed_helper_not_raw_power_or_inhibitor_bypass(self):
        text=payload_read_text(TARGET/'etc/polkit-1/rules.d/10-greetd-power.rules.tmpl')
        self.assertIn('/usr/local/libexec/greetd-power-action-root',text)
        self.assertIn('action.lookup("program") === POWER_HELPER',text)
        self.assertIn('subject.active !== true || subject.local !== true',text)
        self.assertNotIn('command_line',text)
        public=payload_read_text(TARGET/'usr/local/sbin/greetd-power-action')
        root=payload_read_text(TARGET/'usr/local/libexec/greetd-power-action-root')
        self.assertIn('pkexec --disable-internal-agent',public)
        self.assertNotIn('busctl',public)
        self.assertIn('[ "$#" -eq 1 ]',root)
        self.assertIn('poweroff|reboot)',root)
        self.assertNotIn('eval',root)

    def test_shutdown_alias_normalizes_before_service_instance(self):
        for leaf in ('usr/local/bin/labwc-admin-action','usr/local/libexec/labwc-admin-action-root',
                     'usr/local/sbin/greetd-power-action'):
            self.assertIn('shutdown) action=poweroff', payload_read_text(TARGET/leaf))
        self.assertIn('suspend|reboot|poweroff|shutdown)',payload_read_text(TARGET/'usr/local/bin/labwc-power-settings'))

    def test_root_entry_rejects_unsafe_or_greeter_logout_instances(self):
        power=module()
        for value in ('0-poweroff','01000-reboot','1000-reboot;id','1000-greeter-logout',
                      '1000-greeter-suspend','../reboot','1000-suspend-extra'):
            with mock.patch.object(power.os,'geteuid',return_value=0), self.subTest(value=value):
                with self.assertRaises(power.Error): power.main([value])


if __name__ == '__main__':
    unittest.main()
