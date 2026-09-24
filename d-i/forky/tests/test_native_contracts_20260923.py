"""Logging/configuration wiring added by the 2026-09-23 scoped refactor."""
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
        self.assertIn('cmp -s "$profile" "/opt/Mullvad VPN/resources/apparmor_mullvad"', installer)

    def test_crowdsec_status_lines_have_one_native_stdout_sink(self):
        text = read_text(TARGET / 'usr/local/libexec/crowdsec-firstboot')
        block = re.search(r'^log_line\(\) \{\n.*?^\}', text, re.M | re.S).group(0)
        self.assertNotIn('>>', block)
        self.assertEqual(len(re.findall(r'^  printf ', block, re.M)), 1)
        self.assertNotRegex(text, r'>>?\s*"?\$CROWDSEC_LOG_FILE')
        self.assertIn('StandardOutput=journal', read_text(TARGET / 'etc/systemd/system/crowdsec-firstboot.service'))

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
