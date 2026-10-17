"""Focused path/wiring and real shell/Perl method tests; no target boot or package install."""
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

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from payload_fixture import read_text, source_path
from test_retained_package_bounds import method

SEED = Path(__file__).resolve().parents[1]
ROOT = SEED.parents[1]
TARGET = SEED / 'hooks/target'


class LayoutContracts(unittest.TestCase):
    def test_removed_prefixes_have_no_source_files(self):
        renames = json.loads((ROOT / 'd-i/forky/tests/fixtures/contracts/prefix-renames.json').read_text())
        moves = json.loads((ROOT / 'd-i/forky/tests/fixtures/contracts/config-file-renames.json').read_text())
        journal = json.loads((ROOT / 'd-i/forky/tests/fixtures/contracts/journal-source-changes.json').read_text())
        moves.update(journal['renamed'])
        current = json.loads((ROOT / 'd-i/forky/tests/fixtures/contracts/source-paths.json').read_text())['source_moves']
        moves.update({'d-i/forky/' + old: 'd-i/forky/' + new for old, new in current.items()})
        for old, new in renames.items():
            while new in moves: new = moves[new]
            with self.subTest(path=old):
                self.assertFalse((ROOT / old).exists())
                if new in journal['retired']:
                    self.assertFalse((ROOT / new).exists())
                else:
                    self.assertTrue((ROOT / new).is_file(), new)
        self.assertTrue((TARGET / 'usr/local/bin/xssh-send').exists())  # Pre-existing, not an added prefix.

    def test_installed_configuration_has_no_obsolete_directories(self):
        for directory in ('etc/installer', 'etc/secure-boot', 'etc/grub-profiles'):
            self.assertFalse((TARGET / directory).exists())
        for path in ('etc/system-runtime.conf', 'etc/secure-boot.conf',
                     'etc/chatgpt/package-policy.conf', 'etc/codex/app-server.env',
                     'etc/default/grub-profiles', 'etc/grub.d/40_custom'):
            self.assertTrue(source_path(TARGET / path).is_file(), path)
        self.assertFalse((TARGET / 'usr/local/libexec/grub-profiles.tmpl').exists())
        codex = read_text(TARGET / 'etc/skel-desktop/.config/systemd/user/codex-app-server.service')
        self.assertIn('/etc/codex/app-server.env', codex)

    def test_fail2ban_jails_are_in_the_native_dropin_directory(self):
        self.assertFalse((TARGET / 'etc/fail2ban/jail.d/managed').exists())
        for path in ('10-sshd.local', '20-nginx-botsearch.local'):
            self.assertTrue(source_path(TARGET / ('etc/fail2ban/jail.d/' + path)).is_file())
        self.assertTrue((TARGET / 'etc/systemd/system/fail2ban.service.d/40-runtime.conf').is_file())

    def test_nmap_manifest_and_guard_use_the_same_explicit_names(self):
        text = read_text(SEED / 'scripts/desktop/components.sh')
        names = re.search(r'desktop_managed_nmap_script_files\(\) \{\n  cat <<\'EOF\'\n(.*?)\nEOF', text, re.S)[1].splitlines()
        self.assertEqual(len(names), 8)
        self.assertNotIn('x-*.nse', text)
        self.assertIn('|'.join(names) + ') ;;', text)
        for name in names:
            self.assertTrue((TARGET / 'usr/local/share/nmap/scripts' / name).is_file())

    def test_native_power_sink_and_its_rotation_share_the_catalogue(self):
        route = read_text(TARGET / 'etc/rsyslog.d/19-power.conf')
        self.assertIn('type="omfile" file="/var/lib/journal/power/actions.log"', route)
        self.assertIn('$programname == "labwc-admin-action"', route)
        self.assertIn('$programname == "labwc-package-sleep-guard"', route)
        self.assertNotIn('$!_SYSTEMD_UNIT', route)
        self.assertNotIn('$!MESSAGE_ID', route)
        self.assertIn('  stop\n', route)
        self.assertNotIn('imfile', route)
        rotation = read_text(TARGET / 'usr/local/libexec/rsyslog-size-rotate')
        self.assertIn("'/var/lib/journal/power/actions.log':", rotation)
        self.assertIn('rotation.sizeLimit="2097152"', route)
        self.assertIn('rotation.sizeLimitCommand="/usr/local/libexec/rsyslog-size-rotate"', route)
        self.assertNotIn('/var/lib/journal/power/actions.log',
                         read_text(TARGET / 'etc/logrotate.d/rsyslog'))
        self.assertNotIn('/var/lib/journal/boot/*', rotation)
        self.assertNotIn('/var/lib/journal/power/*', rotation)
        staging = read_text(SEED / 'scripts/desktop/components.sh')
        for name in ('journal-snapshot', 'boot-log.service', 'boot-log.timer',
                     '19-power.conf'):
            self.assertIn(name, staging)
        for retired in ('boot-log.mount', 'power-log.service', 'power-log-capture.service'):
            self.assertNotIn(retired, staging)


class GrubConfigRendering(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='grub-config-')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.fields = json.loads((ROOT / 'd-i/forky/tests/fixtures/contracts/grub-split.json').read_text())['config_variables']

    def render(self, special=''):
        values = {name: '' for name in self.fields.values()}
        values.update({'DEV_PART_BOOT': '/dev/boot', 'grub_root_device': '/dev/root',
                       'DEV_PART_EFI': '/dev/efi', 'DUALBOOT_ENABLED': 'false',
                       'GRUB_PROFILE_DEFAULT_FLAGS': special})
        config = self.work / 'config'
        config.write_text((TARGET / 'etc/default/grub-profiles.tmpl').read_text())
        scalar = self.work / 'map'
        code = 'set -eu\ninstaller_fatal() { printf "%s\\n" "$*" >&2; return 1; }\n'
        code += '. ' + shlex.quote(str(SEED / 'scripts/late/grub.sh')) + '\n'
        code += '. ' + shlex.quote(str(SEED / 'scripts/late/templates.sh')) + '\n'
        code += '\n'.join(k + '=' + shlex.quote(v) for k, v in values.items()) + '\n'
        code += f'render_grub_profile_config_map >{shlex.quote(str(scalar))}\n'
        code += f'render_target_scalar_placeholders {shlex.quote(str(config))} {shlex.quote(str(scalar))}\n'
        result = subprocess.run(['/bin/sh', '-c', code], capture_output=True, text=True, timeout=10,
                                env={**os.environ, 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        return result, config

    def test_quoted_metacharacters_round_trip_without_evaluation(self):
        marker = self.work / 'must-not-exist'
        value = "one ' two \\ three $HOME & | ; $(touch " + str(marker) + ") `id`"
        result, path = self.render(value)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('__INSTALLER_', path.read_text())
        result = subprocess.run(['/bin/sh', '-c', '. "$1"; printf "%s" "$grub_profile_default_flags"',
                                 'fixture', str(path)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, value)
        self.assertFalse(marker.exists())

    def test_multiline_values_fail_before_rendering(self):
        for value in ('one\ntwo', 'one\rtwo'):
            with self.subTest(value=value):
                result, path = self.render(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('multiline GRUB profile value', result.stderr)
                self.assertEqual(path.read_text(), (TARGET / 'etc/default/grub-profiles.tmpl').read_text())


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('perl'), 'root-owned fixtures and core Perl required')
class ChatGPTPackageAlias(unittest.TestCase):
    """Execute exact new method bodies; Moo constructors and dpkg are not simulated as passes."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='chatgpt-policy-', dir='/root')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.policy = self.work / 'package-policy.conf'
        self.canonical = self.work / 'canonical'
        self.alias = self.work / 'package-default'
        for path in (self.policy, self.canonical):
            path.write_text('repo_add_once="false"\n')
            path.chmod(0o644)
        common = 'use strict; use warnings; use Fcntl qw(:DEFAULT O_NOFOLLOW O_NONBLOCK S_IFMT S_IFREG S_IFLNK); use Errno qw(EINTR);\n'
        code = 'package APTRepoLocal::Servicing::Atomic;\n' + common
        code += method('Atomic.pm', 'assert_absolute_path') + method('Atomic.pm', 'read_limited')
        # The method's only external effect is the fixed root-owned native parent.
        code += method('Atomic.pm', 'ensure_root_directory') + 'use File::Path qw(make_path);\n'
        code += 'package APTRepoLocal::Servicing::ChatGPT;\n' + common
        for key, value in (('DEFAULT_PATH', self.policy), ('PACKAGE_DEFAULT_PATH', self.alias), ('CANONICAL_DEFAULT', self.canonical)):
            code += "use constant " + key + " => '" + str(value) + "';\n"
        for name in ('_root_owned_source_text', '_destination_matches', '_clear_package_default_link', '_install_package_default_link'):
            code += method('ChatGPT.pm', name)
        code += "package main; my $obj=bless {}, 'APTRepoLocal::Servicing::ChatGPT'; $obj->${\\$ARGV[0]}();\n"
        self.harness = self.work / 'methods.pl'
        self.harness.write_text(code)

    def call(self, name):
        return subprocess.run(['perl', str(self.harness), name], capture_output=True, text=True,
                              timeout=10, env={**os.environ, 'PERL5OPT': ''})

    def test_exact_alias_is_created_and_removed_without_modifying_policy(self):
        result = self.call('_install_package_default_link')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.alias.is_symlink())
        self.assertEqual(os.readlink(self.alias), str(self.policy))
        result = self.call('_clear_package_default_link')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.alias.exists())
        self.assertFalse(self.alias.is_symlink())
        self.assertEqual(self.policy.read_bytes(), self.canonical.read_bytes())

    def test_known_previous_policy_is_removed_not_duplicated(self):
        self.alias.write_bytes(self.canonical.read_bytes())
        self.alias.chmod(0o644)
        result = self.call('_clear_package_default_link')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.alias.exists())

    def test_foreign_links_content_hardlinks_and_fifos_fail_closed(self):
        for kind in ('symlink', 'foreign', 'hardlink', 'fifo', 'mode', 'owner'):
            with self.subTest(kind=kind):
                if kind == 'symlink': self.alias.symlink_to(self.canonical)
                elif kind == 'hardlink': os.link(self.canonical, self.alias)
                elif kind == 'fifo': os.mkfifo(self.alias, 0o600)
                else:
                    self.alias.write_text('foreign' if kind == 'foreign' else self.canonical.read_text())
                    self.alias.chmod(0o666 if kind == 'mode' else 0o644)
                    if kind == 'owner': os.chown(self.alias, 65534, 65534)
                before = self.canonical.read_bytes()
                result = self.call('_clear_package_default_link')
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(self.alias.exists() or self.alias.is_symlink())
                self.assertEqual(self.canonical.read_bytes(), before)
                self.alias.unlink()


class ChatGPTCandidateValidation(unittest.TestCase):
    """Exact entrypoint bodies with every external effect replaced by a spy."""
    def test_invalid_candidate_precedes_every_prepare_and_finalize_mutation(self):
        common = '''package APTRepoLocal::Servicing::ChatGPT;
use strict; use warnings;
use constant CANONICAL_APPARMOR => '/fixture/canonical-policy';
use constant APPARMOR_PATH => '/fixture/installed-policy';
use constant APPARMOR_PARSER => '/fixture/policy-parser';
use constant CANONICAL_ICON => '/fixture/icon';
use constant ICON_PATH => '/fixture/installed-icon';
use constant CANONICAL_DESKTOP => '/fixture/desktop';
use constant DESKTOP_PATH => '/fixture/installed-desktop';
sub _root_owned_source_text { print "read $_[1]\\n"; return "fixture candidate"; }
sub _assert_root_owned_regular_executable { print "tool $_[2]\\n"; return 1; }
sub _run_policy_syntax_validation { print "parse $_[1]\\n"; return 0; }
sub _install_managed_policy_files { die "UNEXPECTED mutation: policy files\\n"; }
sub _clear_package_default_link { die "UNEXPECTED mutation: compatibility link\\n"; }
sub _install_package_script_guard { die "UNEXPECTED mutation: package guard\\n"; }
sub _install_package_default_link { die "UNEXPECTED mutation: package defaults\\n"; }
'''
        common += method('ChatGPT.pm', '_validate_policy_syntax')
        common += method('ChatGPT.pm', 'prepare_install')
        common += method('ChatGPT.pm', 'finalize_install')
        common += '''package main;
my $object = bless {}, 'APTRepoLocal::Servicing::ChatGPT';
my $action = $ARGV[0];
my $ok = eval { $object->$action('installer'); 1 };
die "invalid candidate was accepted\\n" if $ok;
die $@ if $@ !~ /failed offline validation/;
'''
        with tempfile.TemporaryDirectory(prefix='chatgpt-candidate-') as temporary:
            workspace = Path(temporary)
            harness = workspace / 'candidate.pl'
            harness.write_text(common)
            for entrypoint in ('prepare_install', 'finalize_install'):
                with self.subTest(entrypoint=entrypoint):
                    result = subprocess.run(
                        ['/usr/bin/perl', str(harness), entrypoint],
                        capture_output=True, text=True, timeout=5,
                        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': str(workspace)},
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(), [
                        'read /fixture/canonical-policy', 'tool /fixture/policy-parser',
                        'parse /fixture/canonical-policy',
                    ])

    def test_parser_receives_candidate_with_offline_flags(self):
        with tempfile.TemporaryDirectory(prefix='chatgpt-offline-') as temporary:
            workspace = Path(temporary)
            parser = workspace / 'parser'
            arguments = workspace / 'arguments'
            parser.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >' + shlex.quote(str(arguments)) + '\n')
            parser.chmod(0o700)
            harness = workspace / 'offline.pl'
            harness.write_text(
                'package APTRepoLocal::Servicing::ChatGPT;\nuse strict; use warnings;\n'
                + 'use Managed::Process qw(capture_command);\n'
                + "use constant APPARMOR_PARSER => '" + str(parser) + "';\n"
                + "use constant APPARMOR_PATH => '/fixture/installed';\n"
                + method('ChatGPT.pm', '_run_policy_syntax_validation')
                + "package main; my $o=bless {}, 'APTRepoLocal::Servicing::ChatGPT'; "
                + "$o->_run_policy_syntax_validation('/fixture/candidate') or die 'parser failed';\n"
            )
            result = subprocess.run(
                ['/usr/bin/perl', '-I' + str(TARGET / 'usr/local/lib/perl5/site_perl/runtime'), str(harness)],
                capture_output=True, text=True, timeout=5,
                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'HOME': str(workspace)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            argv = arguments.read_text().splitlines()
            self.assertIn('--skip-kernel-load', argv)
            self.assertIn('--skip-cache', argv)
            self.assertEqual(argv[-1], '/fixture/candidate')


if __name__ == '__main__':
    unittest.main()
