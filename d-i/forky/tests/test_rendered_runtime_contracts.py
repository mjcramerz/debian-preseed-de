"""Unexecuted source contracts for the metadata-only installer verifier.

These fixtures inspect source data only. No target, helper, repository import,
service manager or disposable execution environment is used by the cases.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

from pathlib import Path
import re
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts/desktop'


class RenderedRuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.source = (SCRIPTS / 'verify.sh.tmpl').read_text()

    def test_verifier_has_no_content_or_installed_helper_execution(self):
        for pattern in (
                r'(?m)^\s*(?:/\S*/)?(?:python3|desktop-file-validate|dpkg-query|dpkg|git|cat|grep|awk|sed)\s',
                r'/usr/local/libexec/labwc-hyprpolkit-agent --check',
                r'obsidian_git\(', r'findmnt -', r'import gi',
                r'read_(?:text|bytes)\(', r'open\('):
            self.assertNotRegex(self.source, pattern)
        self.assertIn('file contents are intentionally never read or compared', self.source)

    def test_stage_is_passed_to_the_independent_target_shell(self):
        function = self.source.split('desktop_verify_runtime_contracts() {', 1)[1]
        self.assertIn('stage=$1', function)
        self.assertIn("' sh \"$stage\"", function)
        self.assertIn('case "$stage" in code-only|with-account|account-only)', function)

    def test_metadata_rejects_aliases_wrong_owner_mode_and_hardlinks(self):
        function = self.source.split('desktop_verify_runtime_contracts() {', 1)[1]
        self.assertIn('[ -f "$path" ] && [ ! -L "$path" ]', function)
        self.assertIn('"0:0:$mode:1"', function)
        self.assertIn('[ -d "$directory" ] && [ ! -L "$directory" ]', function)
        self.assertIn('= 0:0:755', function)
        self.assertIn('executable() { metadata "$1" 755;', function)
        self.assertIn('""|*[!a-z0-9_-]*|[!a-z_]*)', function)
        self.assertIn('[ "${#runtime_identifier}" -le 32 ]', function)

    def test_metadata_gate_is_after_staging_and_before_consumer_enablement(self):
        source = (SCRIPTS / 'labwc.sh').read_text()
        gate = source.index('  desktop_verify_runtime_contracts with-account')
        for step in ('desktop_stage_target_assets', 'desktop_install_user_config',
                     'desktop_install_fonts', 'desktop_install_waypaper'):
            self.assertLess(source.index('  ' + step), gate)
        self.assertLess(gate, source.index('  desktop_enable_target_services'))
        loader = (SCRIPTS.parent / 'late/desktop.sh').read_text()
        self.assertIn('fonts verify labwc; do', loader)
        self.assertIn('. "${desktop_module_dir}/verify.sh"', loader)
        renderer = (SCRIPTS / 'components/rendering-access.sh').read_text()
        self.assertIn('desktop_assert_no_unresolved_template_placeholders', renderer)


if __name__ == '__main__':
    unittest.main()
