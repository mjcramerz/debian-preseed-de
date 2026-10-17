"""Exercise verifier predicates in the mandatory disposable fixture environment."""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import ast
import os
from pathlib import Path
import re
import stat
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts/desktop'


class RenderedRuntimeContractTests(unittest.TestCase):
    def setUp(self):
        source = (SCRIPTS / 'verify.sh.tmpl').read_text()
        begin = source.index('import ast\n', source.index('desktop_verify_runtime_contracts()'))
        end = source.index("\n' \"$ACCOUNT_USERNAME\"", begin)
        tree = ast.parse(source[begin:end])
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        self.contract = {'re': re, 'stat': stat}
        # Select the real pure predicates; never execute the target probes or
        # inspect the disposable image as if it were an installed target.
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<runtime predicates>', 'exec'), self.contract)
        temporary = tempfile.TemporaryDirectory(prefix='runtime-contract-', dir=Path(__file__).resolve().parents[3])
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.helper = self.root / 'helper'
        self.helper.write_text('#!/usr/bin/python3\n')
        self.helper.chmod(0o755)

    def test_literals_and_unresolved_installer_tokens(self):
        validate = self.contract['source_text']
        validate(self.helper, b'return __PACKAGE__->new();')
        validate(Path('/usr/local/sbin/app-veth'), b'__APP_INTERFACES__')
        for token in (b'__INSTALLER_FILE_TOOL__', b'__THEME_ICON__', b'__APP_INTERFACES__'):
            with self.subTest(token=token), self.assertRaises(SystemExit):
                validate(self.helper, token)

    def test_identifiers_are_rejected_before_target_probes(self):
        validate = self.contract['configured_identifier']
        validate('account', 'fixture-user')
        validate('greeter', '_greetd')
        for value in ('', '../root', 'bad name', 'x;id', '-option', 'Auser', 'x' * 33):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                validate('account', value)

    def test_executable_owner_mode_parent_and_symlink_contract(self):
        validate = self.contract['trusted']
        validate(self.helper, True)
        self.helper.chmod(0o644)
        with self.assertRaises(SystemExit):
            validate(self.helper, True)
        self.helper.chmod(0o777)
        with self.assertRaises(SystemExit):
            validate(self.helper)
        self.helper.chmod(0o755)
        self.root.chmod(0o777)
        with self.assertRaises(SystemExit):
            validate(self.helper)
        self.root.chmod(0o700)
        alias = self.root / 'alias'
        alias.symlink_to(self.helper)
        with self.assertRaises(SystemExit):
            validate(alias)
        original = Path.lstat
        def wrong_owner(path):
            result = original(path)
            if path == self.helper:
                values = list(result)
                values[4] = 12345
                return os.stat_result(values)
            return result
        with mock.patch.object(Path, 'lstat', wrong_owner), self.assertRaises(SystemExit):
            validate(self.helper)

    def test_runtime_check_precedes_managed_activation(self):
        source = (SCRIPTS / 'labwc.sh').read_text()
        self.assertLess(source.index('  desktop_stage_target_assets'), source.index('  desktop_verify_runtime_contracts'))
        for activation in ('  run_in_target "wrap installed desktop package launchers"',
                           '  desktop_enable_target_services'):
            self.assertLess(source.index('  desktop_verify_runtime_contracts'), source.index(activation))
