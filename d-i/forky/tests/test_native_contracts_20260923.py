"""Logging/configuration wiring added by the 2026-09-23 scoped refactor."""

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
from pathlib import Path
import re
import shlex
import subprocess
import unittest

from payload_fixture import read_text, source_path

SEED = Path(__file__).resolve().parents[1]
ROOT = SEED.parents[1]
TARGET = SEED / 'hooks/target'


class NativeContractTests(unittest.TestCase):
    def test_mullvad_logging_override_preserves_nonlogging_vendor_policy(self):
        dropin = read_text(TARGET / 'etc/systemd/system/mullvad-daemon.service.d/40-logging.conf')
        active = [line for line in dropin.splitlines() if line and not line.startswith('#')]
        self.assertEqual(active, ['[Service]', 'ExecStart=',
            'ExecStart=/usr/bin/mullvad-daemon -vv --disable-stdout-timestamps --disable-log-to-file',
            'StandardOutput=journal', 'StandardError=journal', 'SyslogIdentifier=mullvad-daemon'])
        installer = read_text(SEED / 'scripts/late/mullvad.sh')
        self.assertIn('validate Mullvad native journal logging contract', installer)
        self.assertIn('help=$(/usr/bin/mullvad-daemon --help)', installer)
        self.assertIn('40-logging.conf)"', installer)
        self.assertIn('sed -E "$normalize_header" "/opt/Mullvad VPN/resources/apparmor_mullvad"', installer)
        self.assertIn('cmp -s "$policy_check_dir/current" "$policy_check_dir/vendor"', installer)

    def test_crowdsec_status_lines_have_one_native_stdout_sink(self):
        text = read_text(TARGET / 'usr/local/libexec/crowdsec-firstboot')
        block = re.search(r'^log_line\(\) \{\n.*?^\}', text, re.M | re.S).group(0)
        self.assertNotIn('>>', block)
        self.assertEqual(len(re.findall(r'^  printf ', block, re.M)), 1)
        self.assertNotRegex(text, r'>>?\s*"?\$CROWDSEC_LOG_FILE')
        self.assertIn('StandardOutput=journal', read_text(TARGET / 'etc/systemd/system/crowdsec-firstboot.service'))

    def test_crowdsec_enroll_request_does_not_claim_console_approval(self):
        source = (SEED / 'scripts/firstboot/assets/var/lib/firstboot/bin/crowdsec-firstboot.tmpl').read_text()
        self.assertIn('enrollment_status=pending-approval', source)
        self.assertIn('console_enrollment=pending-approval', source)
        self.assertNotIn('enrollment_status=enrolled', source)

    def test_tailscale_does_not_replay_daemon_journal_or_append_a_second_file(self):
        text = read_text(TARGET / 'usr/local/libexec/tailscale-up')
        self.assertNotIn('journalctl', text)
        self.assertNotRegex(text, r'>>?\s*"?\$TAILSCALE_LOG_FILE')
        route = read_text(TARGET / 'etc/rsyslog.d/44-components.conf')
        self.assertIn('file="/var/log/managed/system/system.log"', route)
        self.assertNotIn('re_match(', route)
        unit = read_text(SEED / 'scripts/firstboot/assets/etc/systemd/system/tailscale-bootstrap.service.tmpl')
        self.assertNotIn('EnvironmentFile=', unit)
        self.assertIn('Environment="TAILSCALE_HOSTNAME=', unit)
        self.assertIn('/var/lib/firstboot/bin/tailscale-up', unit)
        self.assertIn('Type=exec\n', unit)
        self.assertIn('SuccessExitStatus=75\n', unit)
        self.assertIn('RestartForceExitStatus=75\n', unit)
        self.assertIn('RuntimeMaxSec=15min\n', unit)
        pending = re.search(r'^tailscale_report_pending_approval\(\) \{\n.*?^\}', text, re.M | re.S).group(0)
        self.assertIn('tailscale_remove_auth_key', pending)
        self.assertIn('exit 75', pending)
        self.assertNotIn('touch ', pending)

    def test_tailscale_self_updates_are_disabled_without_package_manager_grants(self):
        source = (SEED / 'scripts/firstboot/assets/var/lib/firstboot/bin/tailscale-up').read_text()
        self.assertLess(source.index('/usr/bin/tailscale set --auto-update=false'),
                        source.index('if tailscale_is_joined &&'))
        unit = read_text(TARGET / 'etc/systemd/system/tailscaled.service.d/override.conf.tmpl')
        self.assertIn('Environment=TS_ALLOW_ADMIN_CONSOLE_REMOTE_UPDATE=false', unit)
        self.assertIn('Environment=TS_DEBUG_FIREWALL_MODE=nftables', unit)
        profile = (TARGET / 'etc/apparmor.d/usr.sbin.tailscaled').read_text()
        self.assertNotRegex(profile, r'(?m)^\s*/usr/bin/(?:systemd-run|dpkg|apt-get)\s+[^#\n]*x')
        self.assertNotRegex(profile, r'(?m)^\s*/usr/sbin/\{[^\n]*iptables')
        self.assertNotIn('/run/xtables.lock', profile)
        self.assertIn('deny /usr/{bin,sbin}/{ip6tables,ip6tables-restore,ip6tables-save,iptables,iptables-restore,iptables-save,xtables-nft-multi,xtables-legacy-multi} x,', profile)

    def test_tailscale_exact_noop_filters_accept_go_timestamps(self):
        # Regex fixtures only; target systemd/PCRE2 journal acceptance is separate.
        unit = (TARGET / 'etc/systemd/system/tailscaled.service.d/override.conf.tmpl').read_text()
        rules = [line.partition('=')[2] for line in unit.splitlines()
                 if line.startswith('LogFilterPatterns=')]
        self.assertEqual(len(rules), 4)
        self.assertTrue(all(rule.startswith('~^') and rule.endswith('$') for rule in rules))
        token = '__INSTALLER_TAILSCALE_INTERFACE_REGEX__'
        for interface in ('tailscale0', 'ts.mesh0'):
            # Same literal-dot representation as scripts/late/tailscale.sh.
            patterns = [re.compile(rule[1:].replace(token, interface.replace('.', '[.]')))
                        for rule in rules]
            benign = [
                f'router: enumerating {interface} addresses for cleanup failed: '
                f'failed to look up link "{interface}": Link not found',
                'linuxfw: clear iptables: exec: "iptables": executable file not found in $PATH',
                'linuxfw: clear ip6tables: exec: "ip6tables": executable file not found in $PATH',
                'ipnext: work queue shutdown failed: execqueue shut down',
            ]
            visible = [
                'control: lite map update error after 29ms: initial fetch failed 409: '
                'superseded by another update',
                'control: lite map update error after 29ms: initial fetch failed 401: unauthorized',
                'health(warnable=warming-up): error: Tailscale is starting. Please wait.',
                f'router: enumerating {interface} addresses for cleanup failed: permission denied',
                'linuxfw: clear iptables: exec: "iptables": permission denied',
                'linuxfw: clear ip6tables: exec: "ip6tables": permission denied',
                'linuxfw: clear iptables: exit status 1',
                'linuxfw: nftables: permission denied',
                'ipnext: work queue shutdown failed: context deadline exceeded',
                'apparmor="DENIED" operation="exec" name="/usr/sbin/iptables"',
                benign[0].replace(interface, 'other0'),
                benign[0].replace('cleanup failed:', 'failed:'),
                benign[1].replace('$PATH', 'PATH'),
            ]
            if '.' in interface:
                visible.append(benign[0].replace(interface, interface.replace('.', 'x')))
            for prefix in ('', '2026/10/19 18:56:07 '):
                for message in benign:
                    with self.subTest(interface=interface, prefix=prefix, benign=message):
                        self.assertEqual(sum(bool(p.search(prefix + message)) for p in patterns), 1)
                for message in visible:
                    with self.subTest(interface=interface, prefix=prefix, visible=message):
                        self.assertFalse(any(p.search(prefix + message) for p in patterns))
            for message in benign:
                for altered in ('unexpected ' + message, message + ' additional failure',
                                '2026/10/19 18:56:07.123 ' + message):
                    with self.subTest(interface=interface, altered=altered):
                        self.assertFalse(any(p.search(altered) for p in patterns))

    def test_authoritative_audit_and_requested_categories(self):
        env = read_text(SEED / 'hosts/logging/observability.env')
        self.assertIn('LOG_AUDIT_FILE="${LOG_AUDIT_DIR}/auditd.log"', env)
        self.assertIn('LOG_APPLICATIONS_FILE="${LOG_APPS_DIR}/apps.log"', env)
        self.assertNotIn('LOG_ADB_DIR=', env)
        self.assertNotIn('LOG_THUNAR_DIR=', env)
        for path in (TARGET / 'etc/audit').rglob('auditd.conf*'):
            text = read_text(path)
            self.assertIn('__INSTALLER_LOG_AUDIT_FILE__', text)
            self.assertNotIn('kernel-audit.log', text)

    def test_relocated_config_sources_and_readers_exist(self):
        moves = json.loads((ROOT / 'd-i/forky/tests/fixtures/contracts/config-relocations.json').read_text())
        all_text = '\n'.join(p.read_text(errors='replace') for base in (SEED / 'scripts', TARGET)
                             for p in base.rglob('*') if p.is_file())
        for old, new in moves.items():
            if new == 'etc/crowdsec/bootstrap.env':
                self.assertFalse((TARGET / new).exists())
                self.assertNotIn('/' + new, all_text)
                continue
            with self.subTest(old=old, new=new):
                self.assertFalse(source_path(TARGET / old).exists())
                needle = new if new.endswith('.tmpl') else '/' + new
                self.assertTrue(needle in all_text, 'missing consumer: ' + needle)
        helper = TARGET / 'etc/grub.d/40_custom.tmpl'
        self.assertTrue(helper.is_file())
        self.assertTrue(helper.read_text().startswith('#!/bin/sh'))
        self.assertIn('/etc/default/grub-profiles', helper.read_text())

    def test_repo_identity_and_perl_namespace_are_consistent(self):
        repository = read_text(TARGET / 'usr/local/libexec/apt-repo-local')
        self.assertIn('apt-repo-local.sources', repository)
        self.assertIn('apt-repo-local.gpg', repository)
        self.assertTrue((TARGET / 'usr/local/bin/apt-repo-init').is_file())
        perl = TARGET / 'usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal'
        self.assertTrue(perl.is_dir())
        for path in perl.rglob('*.pm'):
            self.assertRegex(path.read_text(), r'package APTRepoLocal::')
            self.assertNotIn('ExternalSoftware', path.read_text())


if __name__ == '__main__':
    unittest.main()
