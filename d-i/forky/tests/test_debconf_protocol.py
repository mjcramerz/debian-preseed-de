"""Regressions for the real installer shell API and inherited frontend pipe."""
from __future__ import annotations
import os
from pathlib import Path
import shlex
import shutil
import stat
import tempfile
import unittest

from debconf_fixture import DebconfSandbox, PrivateDebconf, ProtocolSession, FIXTURES
from test_repository_transport import FORKY, Endpoint
from test_bootstrap_portability import generated_commands

Q = shlex.quote


class DebconfProtocolTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.geteuid(), 0, 'isolated d-i protocol tests require chroot privileges')
        self.tmp = tempfile.TemporaryDirectory(prefix='di-protocol-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.box = DebconfSandbox(self.root / 'root')
        self.db = PrivateDebconf(self.root / 'database')
        self.addCleanup(self.db.close)
        for name in ('lifecycle', 'debconf'):
            shutil.copyfile(FORKY / f'scripts/common/{name}.sh', self.box.root / f'tmp/{name}.sh')
        shutil.copyfile(FORKY / 'scripts/runtime/common.sh', self.box.root / 'tmp/runtime.sh')

    def run_code(self, code, *, env=None, raw=False, override=None, timeout=25):
        session = ProtocolSession(self.box, self.db, code, env=env, raw=raw, override=override)
        self.addCleanup(session.close)
        result, timed_out = session.finish(timeout, self.box.runtime / 'state/first-failure')
        self.assertFalse(timed_out, 'protocol deadlock or fatal hold: ' + result.stderr +
                         self.failure_details())
        self.assertEqual(session.errors, [])
        return result, session

    def failure_details(self):
        parts = []
        for path in (self.box.runtime / 'state/first-failure',
                     self.box.root / 'tmp/installer.log', self.box.root / 'var/log/fixture-child.log'):
            if path.is_file():
                parts.append(path.read_text()[-2500:])
        return '\n'.join(parts)

    def answers(self, text):
        path = self.box.root / 'tmp/answers'
        path.write_text(text)
        path.chmod(0o600)

    def test_negative_control_reproduces_exact_illegal_number_with_r2_redirection(self):
        self.answers('d-i regression/value string expected\n')
        code = 'old_run() { "$@" <&0 & wait "$!"; }; old_run /bin/debconf-set-selections /tmp/answers'
        result, _ = self.run_code(code)
        self.assertEqual(result.returncode, 2)
        self.assertIn('return: line 88: Illegal number', result.stderr)

    def test_supervised_installer_selector_registers_and_sets_real_database(self):
        self.answers('d-i regression/value string expected\nd-i regression/value seen false\n')
        result, session = self.run_code('. /tmp/lifecycle.sh; installer_run_supervised /bin/debconf-set-selections /tmp/answers')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.db.value('regression/value'), 'expected')
        self.assertEqual(self.db.value('regression/value', 'seen'), 'false')
        self.assertTrue(any(r.startswith(b'REGISTER ') for r in session.requests))

    def test_dash_supervisor_also_preserves_busybox_client_protocol(self):
        self.box.copy_executable(Path('/bin/dash'), '/bin/dash')
        self.answers('d-i regression/value string expected\n')
        for runner in ('installer_run_supervised', 'installer_run_bounded 10'):
            code = '. /tmp/lifecycle.sh; ' + runner + ' /bin/debconf-set-selections /tmp/answers'
            result, _ = self.run_code('exec /bin/dash -eu -c ' + Q(code))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.db.value('regression/value'), 'expected')

    def test_bounded_installer_selector_preserves_live_stdin(self):
        self.answers('d-i regression/value string expected\n')
        result, _ = self.run_code('. /tmp/lifecycle.sh; installer_run_bounded 0180 /bin/debconf-set-selections /tmp/answers')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.db.value('regression/value'), 'expected')

    def test_nested_supervision_and_capture_preserve_connection_and_fd9(self):
        self.answers('d-i regression/value string expected\n')
        code = '''. /tmp/lifecycle.sh
exec 9</etc/passwd
nested() { installer_run_bounded 10 /bin/debconf-set-selections /tmp/answers; }
installer_run_supervised nested || exit "$?"
. /tmp/debconf.sh
value=$(installer_debconf_request GET regression/value) || exit "$?"
[ "$value" = expected ] || exit 91
IFS= read -r saved <&9
[ "$saved" = 'root:x:0:0:root:/root:/bin/sh' ] || exit 92
printf screen >&5
'''
        result, _ = self.run_code(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'screen')

    def test_raw_main_menu_descriptors_initialized_before_supervision(self):
        self.answers('d-i regression/value string expected\n')
        result, _ = self.run_code('set -e; . /tmp/lifecycle.sh; installer_lifecycle_begin regression; '
            'installer_run_supervised /bin/debconf-set-selections /tmp/answers; '
            'installer_lifecycle_complete', raw=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.db.value('regression/value'), 'expected')
        self.assertTrue((self.box.runtime / 'state/regression.done').is_file())

    def test_runtime_trailing_backslash_empty_hash_seen_and_literal_metacharacters(self):
        secret = 'Fixture!$[xy];$(not-a-command)' + chr(92)
        self.answers('d-i passwd/root-password password ' + secret + '\n'
                     'd-i passwd/root-password-crypted password\n'
                     'd-i passwd/root-password seen false\n')
        result, _ = self.run_code('set -e; . /tmp/runtime.sh; runtime_apply_answers_file /tmp/answers')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.db.value('passwd/root-password'), secret)
        self.assertEqual(self.db.value('passwd/root-password-crypted'), '')
        self.assertEqual(self.db.value('passwd/root-password', 'seen'), 'false')
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(list((self.box.root / 'tmp').glob('installer-runtime-answers.*')), [])

    def test_single_value_registration_never_pipes_answers_to_selector(self):
        secret = 'Fixture-literal' + chr(92)
        result, _ = self.run_code('. /tmp/debconf.sh; installer_debconf_seed_value d-i regression/value string ' + Q(secret))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.db.value('regression/value'), secret)

    def test_cleanup_retains_root_failure_and_rejects_successful_work_with_failed_cleanup(self):
        selector = self.box.root / 'bin/debconf-set-selections'
        self.answers('d-i regression/cleanup password Fixture-value\n')
        for initial in (37, 0):
            if initial:
                selector.write_text('#!/bin/sh\nexit 37\n')
            else:
                shutil.copyfile(FIXTURES / 'debconf-set-selections', selector)
            selector.chmod(0o755)
            for code in (
                '. /tmp/debconf.sh; rm() { return 99; }; '
                'installer_debconf_seed_value d-i regression/cleanup string value',
                '. /tmp/runtime.sh; rm() { return 99; }; '
                'runtime_apply_answers_file /tmp/answers',
            ):
                with self.subTest(initial=initial, runtime='runtime.sh' in code):
                    result, _ = self.run_code('set -e; ' + code + '; printf UNREACHABLE')
                    self.assertEqual(result.returncode, initial or 99, result.stderr)
                    self.assertNotIn('UNREACHABLE', result.stdout)

    def test_eof_reply_is_fatal_without_illegal_return_or_secret_leak(self):
        result, _ = self.run_code('. /tmp/debconf.sh; installer_debconf_request GET test/secret', override=lambda r: None)
        self.assertEqual(result.returncode, 125, result.stderr)
        self.assertIn('reply stream closed', result.stderr)
        self.assertNotIn('Illegal number', result.stderr)

    def test_malformed_reply_is_not_converted_to_shell_status(self):
        for reply in (b'', b'secret-FIXTURE', b'08 value', b'256 value', b'-1 value'):
            with self.subTest(reply_status=reply.split(b' ')[0]):
                result, _ = self.run_code('. /tmp/debconf.sh; installer_debconf_request GET test/secret', override=lambda r: reply)
                self.assertEqual(result.returncode, 125, result.stderr)
                self.assertNotIn('secret-FIXTURE', result.stdout + result.stderr)
                self.assertNotIn('Illegal number', result.stderr)

    def test_valid_nonzero_reply_preserves_original_status(self):
        result, _ = self.run_code('. /tmp/debconf.sh; installer_debconf_request GET test/secret', override=lambda r: b'42 do-not-log-FIXTURE')
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertNotIn('do-not-log-FIXTURE', result.stdout + result.stderr)

    def test_failed_selector_not_retried_and_diagnostics_remain_private(self):
        self.answers('d-i regression/value string expected\n')
        path = self.box.root / 'bin/debconf-set-selections'
        path.write_text('#!/bin/sh\necho "$*" >>/tmp/selector.calls\necho secret-FIXTURE >&2\nexit 37\n')
        result, _ = self.run_code('. /tmp/debconf.sh; installer_debconf_apply_file /tmp/answers')
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual((self.box.root / 'tmp/selector.calls').read_text().splitlines(), ['/tmp/answers'])
        self.assertNotIn('secret-FIXTURE', result.stdout + result.stderr)
        diagnostics = list((self.box.root / 'tmp').glob('installer-debconf.*/stderr'))
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(stat.S_IMODE(diagnostics[0].stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(diagnostics[0].parent.stat().st_mode), 0o700)

    def test_canonical_debconf_copies_are_identical(self):
        canonical = (FORKY / 'scripts/common/debconf.sh').read_text()
        for rel in ('scripts/common/lib.sh', 'scripts/runtime/common.sh'):
            text = (FORKY / rel).read_text()
            actual = text.split('# BEGIN EMBEDDED DEBCONF\n', 1)[1].split('# END EMBEDDED DEBCONF\n', 1)[0]
            self.assertEqual(actual, canonical)

    def test_runtime_password_not_written_to_upstream_preseed_log(self):
        secret = 'Fixture-Only!not-a-real-password'
        self.answers('d-i passwd/root-password password ' + secret + '\n')
        result, _ = self.run_code('set -e; . /tmp/runtime.sh; runtime_apply_answers_file /tmp/answers')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.db.value('passwd/root-password'), secret)
        log = self.box.root / 'var/lib/preseed/log'
        self.assertNotIn(secret, log.read_text())
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_symlink_answer_file_rejected_before_database_changes(self):
        self.answers('d-i regression/value string expected\n')
        (self.box.root / 'tmp/answer-link').symlink_to('/tmp/answers')
        result, session = self.run_code('. /tmp/debconf.sh; installer_debconf_apply_file /tmp/answer-link')
        self.assertEqual(result.returncode, 125)
        self.assertEqual(session.requests, [])

    def prepare_phase_runner(self):
        boot = self.box.runtime / 'bootstrap'
        boot.mkdir(parents=True)
        (boot / 'preflight.ok').touch()
        shutil.copyfile(FORKY / 'preseed.cfg', self.box.root / 'tmp/preseed.cfg')
        result, _ = self.run_code('/bin/debconf-set-selections /tmp/preseed.cfg')
        self.assertEqual(result.returncode, 0, result.stderr)
        entry = boot / 'preseed-bootstrap-entry.sh'
        entry.write_text('#!/bin/sh\nset -eu\n. /tmp/debconf.sh\n'
            'installer_debconf_seed_value d-i regression/phase string "$1"\n'
            'printf "%s\\n" "$1" >>/tmp/visited\n')
        entry.chmod(0o700)
        return entry

    def test_all_generated_phase_commands_preserve_debconf_roundtrip(self):
        self.prepare_phase_runner()
        for question, expected in generated_commands().items():
            self.assertEqual(self.db.value(question), expected)
        for question, phase in (('preseed/early_command', 'early'),
                                ('partman/early_command', 'partman'),
                                ('preseed/late_command', 'late')):
            result, _ = self.run_code('/bin/preseed_command ' + question)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.db.value('regression/phase'), phase)
        self.assertEqual((self.box.root / 'tmp/visited').read_text().splitlines(),
                         ['early', 'partman', 'late'])

    def test_failed_selector_in_preseed_command_holds_without_reentry(self):
        self.prepare_phase_runner()
        tool = self.box.root / 'bin/debconf-set-selections'
        tool.write_text('#!/bin/sh\necho invoked >>/tmp/selector.calls\nexit 37\n')
        code = '/bin/preseed_command preseed/late_command'
        for attempt in range(2):
            session = ProtocolSession(self.box, self.db, code)
            self.addCleanup(session.close)
            result, held = session.finish(10, self.box.runtime / 'state/first-failure')
            self.assertTrue(held, result.stderr)
            record = (self.box.runtime / 'state/first-failure').read_text()
            self.assertIn('status=37', record)
        self.assertEqual((self.box.root / 'tmp/selector.calls').read_text().splitlines(), ['invoked'])
        self.assertFalse((self.box.root / 'tmp/visited').exists())
        self.assertFalse((self.box.runtime / 'state/installation.success').exists())

    def bootstrap(self, cmdline, *, http=False):
        shutil.copytree(FORKY, self.box.root / 'seed', ignore=shutil.ignore_patterns('tests', '__pycache__'))
        # Execute Debian's real include and preseed/run control flow, not just
        # our include-command; all selections go through its shell client.
        code = 'set -e; . /usr/share/debconf/confmodule; . /lib/preseed/preseed.sh; preseed_location file:///seed/preseed.cfg ""'
        result, session = self.run_code(code, env={'INSTALLER_CMDLINE': cmdline}, timeout=70)
        self.assertEqual(result.returncode, 0, result.stderr + self.failure_details())
        self.assertTrue((self.box.runtime / 'state/apply.done').is_file(), self.failure_details())
        self.assertFalse((self.box.runtime / 'state/first-failure').exists())
        self.assertFalse((self.box.runtime / 'state/installation.success').exists())
        self.assertTrue(self.db.value('pkgsel/include'))
        self.assertTrue(self.db.value('anna/choose_modules'))
        self.assertEqual(self.db.value('mirror/suite'), 'forky')
        self.assertRegex(self.db.value('netcfg/get_hostname'), r'^LPL-[0-9]{3}$')
        # Re-entry must not perform a second batch of database writes.
        before = self.db.value('pkgsel/include')
        again, repeated = self.run_code('/tmp/install-runtime/bootstrap/preseed-apply.sh', timeout=30)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertFalse(any(request.split(b' ', 1)[0] in (b'SET', b'REGISTER', b'FSET')
                             for request in repeated.requests), 'completed apply repeated database writes')
        self.assertEqual(self.db.value('pkgsel/include'), before)
        return session

    def test_full_debian_preseed_include_and_run_local_apply(self):
        self.bootstrap('file=/seed/preseed.cfg classes=prod;desktop;standard;dhcp;ssh')

    def test_full_debian_preseed_include_and_run_http_apply(self):
        web = Endpoint(FORKY)
        self.addCleanup(web.close)
        self.bootstrap(f'url={web.url}/short classes=prod;desktop;standard;dhcp;ssh')

    def test_full_debian_preseed_f2fs_arm64_apply(self):
        uname = self.box.root / 'bin/uname'
        uname.unlink()
        uname.write_text('#!/bin/sh\n[ "$1" != -m ] || { echo aarch64; exit; }\nexec /bin/busybox uname "$@"\n')
        uname.chmod(0o755)
        (self.box.root / 'proc/cpuinfo').write_text('CPU implementer : 0x41\n')
        nvme = self.box.root / 'sys/block/nvme0n1'
        nvme.rename(nvme.with_name('mmcblk0'))
        self.bootstrap('file=/seed/preseed.cfg classes=prod;desktop;standard;dhcp;ssh')
        context = (self.box.runtime / 'state/context.env').read_text()
        self.assertIn('arm64', context)
        self.assertIn('f2fs-desktop', context)
        self.assertIn('grub-efi-arm64-signed', self.db.value('pkgsel/include'))
        self.assertNotIn('grub-efi-amd64', self.db.value('pkgsel/include'))

    def test_full_debian_preseed_vm_apply(self):
        nvme = self.box.root / 'sys/block/nvme0n1'
        nvme.rename(nvme.with_name('vda'))
        dmi = self.box.root / 'sys/class/dmi/id'
        dmi.mkdir(parents=True)
        (dmi / 'product_name').write_text('QEMU Virtual Machine\n')
        self.bootstrap('file=/seed/preseed.cfg classes=prod;desktop;standard;dhcp;ssh')
        context = (self.box.runtime / 'state/context.env').read_text()
        self.assertIn('vm-desktop', context)


if __name__ == '__main__':
    unittest.main()
