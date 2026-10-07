"""Language classification is based on policy location, not executable names."""
from pathlib import Path
import runpy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
class PolicyFileClassification(unittest.TestCase):
    def test_shell_named_apparmor_profile_is_not_parsed_as_shell(self):
        checker=runpy.run_path(str(ROOT/'tools/check_shells.py'))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);policy=root/'etc/apparmor.d/usr.local.sbin.example.sh'
            policy.parent.mkdir(parents=True)
            policy.write_text('profile example /usr/local/sbin/example.sh flags=(attach_disconnected) { }\n')
            script=root/'example.sh';script.write_text('#!/bin/sh\nexit 0\n')
            self.assertEqual(list(checker['shell_sources'](root)),[(script,'posix')])
            policy.write_text('#!/bin/sh\nexit 0\n')
            self.assertEqual(len(list(checker['shell_sources'](root))),2)

    def test_audit_does_not_count_policy_attachment_as_a_shell_failure_or_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'d-i/forky/tests/audit_codebase.py'
            script.parent.mkdir(parents=True)
            shutil.copyfile(ROOT/'d-i/forky/tests/audit_codebase.py',script)
            policy=root/'d-i/forky/hooks/target/etc/apparmor.d/usr.local.sbin.example.sh'
            policy.parent.mkdir(parents=True)
            policy.write_text('profile example /usr/local/sbin/example.sh flags=(attach_disconnected) { }\n')
            report=root/'audit.json'
            result=subprocess.run([sys.executable,'-B',str(script),'--output',str(report)],
                                  capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            record=json.loads(report.read_text())['files'][0]
            self.assertEqual(record['kind'],'apparmor-policy')
            self.assertEqual(record['check'],'inventory-only')
