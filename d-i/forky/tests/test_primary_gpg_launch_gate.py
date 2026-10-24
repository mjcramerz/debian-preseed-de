"""Fail-closed primary identity and managed route contracts, disposable image only."""
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import unittest
from types import SimpleNamespace

SEED = Path(__file__).resolve().parents[1]
HOOKS = SEED / 'hooks/target'
PACKAGE = HOOKS / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app'


class PrimaryGPGProofTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((HOOKS / 'usr/local/libexec/labwc-primary-gpg').read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        self.scope = dict(os=os, Path=Path, stat=stat, json=json, base64=base64,
                          hashlib=hashlib, secrets=secrets, MAX_BYTES=16384)
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<proof predicates>', 'exec'), self.scope)
        self.plaintext = b'x' * 32
        self.fingerprint = 'A' * 40
        self.policy = dict(schema=1, username='fixture', home='/fixture', fingerprint=self.fingerprint,
                           challenge=base64.b64encode(b'ciphertext' * 10).decode(),
                           sha256=hashlib.sha256(self.plaintext).hexdigest())
        self.scope['read_policy'] = lambda: self.policy
        self.scope['account_context'] = lambda *_: SimpleNamespace(pw_uid=os.getuid())
        self.scope['gpg'] = lambda *_args, **_kwargs: (self.plaintext,
            ('[GNUPG:] DECRYPTION_KEY ' + 'B' * 40 + ' ' + self.fingerprint +
             ' u\n[GNUPG:] DECRYPTION_OKAY\n').encode())

    def test_exact_primary_key_and_challenge_are_required(self):
        self.scope['check']()
        for field, value in (('fingerprint', 'C' * 40), ('sha256', '0' * 64),
                             ('challenge', '!invalid-base64!')):
            original = self.policy[field]
            self.policy[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.scope['check']()
            self.policy[field] = original

    def test_readiness_without_real_decrypt_proof_is_denied(self):
        for status in (b'', b'[GNUPG:] DECRYPTION_OKAY\n',
                       ('[GNUPG:] DECRYPTION_KEY ' + 'B' * 40 + ' ' + self.fingerprint + ' u\n').encode()):
            self.scope['gpg'] = lambda *_args, **_kwargs: (self.plaintext, status)
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.scope['check']()
        def cancelled(*_args, **_kwargs):
            raise ValueError('fixture cancellation')
        self.scope['gpg'] = cancelled
        with self.assertRaises(ValueError):
            self.scope['check']()

    def test_gate_is_after_host_handoff_and_before_payloads(self):
        cli = (PACKAGE / 'cli.py').read_text()
        start = cli.index('def main(')
        source = cli[start:]
        self.assertLess(source.index('redirect_native_from_private_users('), source.index('require_primary_gpg()'))
        for consumer in ('return _run_compatibility(', 'ensure_managed_runtime_state(', 'run_pure_privacy('):
            self.assertLess(source.index('require_primary_gpg()'), source.index(consumer))
        generic = (PACKAGE / 'generic.py').read_text()
        self.assertLess(generic.index('        require_primary_gpg()'), generic.index('os.execve(systemd_run'))
        torrent = (HOOKS / 'usr/local/bin/labwc-qbittorrent').read_text()
        main = torrent[torrent.index('def main()'):]
        self.assertLess(main.index('require_primary_gpg()'), main.index('prepare_storage('))

    def test_managed_vendor_actions_and_code_aliases(self):
        source = (HOOKS / 'usr/local/bin/labwc-sync-application-launchers.tmpl').read_text()
        tree = ast.parse(source)
        config = next(ast.literal_eval(node.value) for node in tree.body
                      if isinstance(node, ast.Assign) and any(
                          isinstance(target, ast.Name) and target.id == 'APP_CONFIG' for target in node.targets))
        code = [item for item in config if item['action_app'] == 'code']
        self.assertEqual(code[0]['desktop_names'], ('code.desktop', 'com.microsoft.VSCode.desktop'))
        self.assertEqual(code[1]['desktop_names'],
                         ('code-url-handler.desktop', 'com.microsoft.VSCode.UrlHandler.desktop'))
        self.assertTrue(code[1]['no_display'])
        self.assertIn('entry["NoDisplay"] = "true"', source)
        self.assertIn('"/usr/local/bin/labwc-wayland-app auto -- " + command', source)
