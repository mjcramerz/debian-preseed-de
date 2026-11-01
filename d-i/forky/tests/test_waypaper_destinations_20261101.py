"""Unexecuted wallpaper regression/failure fixtures; no host IO or GUI imports.

Only selected AST function definitions are evaluated against an in-memory file
store. No managed entrypoint, import, image decoder or process is invoked.
The repository's test execution prohibition still applies to this file.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import ast
import base64
import contextlib
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest

import tinycss2

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
PACKAGE = TARGET / 'usr/local/lib/python3.14/dist-packages/labwc_appearance'
PNG = b'\x89PNG\r\n\x1a\nfixture-only-image-data'
CSS = b'window { color: #123456; background-image: url("file:///original.png"); }\n'


def functions(path, names, namespace):
    source = ast.parse(path.read_text(encoding='utf-8'))
    body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)]
    body.extend(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names)
    if len(body) != len(names) + 1:
        raise AssertionError('fixture function contract changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), str(path), 'exec'), namespace)
    return namespace


class MemoryTree:
    def __init__(self, files=None):
        self.files = dict(files or {})
        self.fd = object()
        self.fail = None

    def read(self, name, limit=8 * 1024**2, *, missing=False):
        if name not in self.files:
            if missing:
                return None
            raise FileNotFoundError(name)
        raw = self.files[name]
        if len(raw) > limit:
            raise ValueError('fixture read limit')
        return raw

    def write(self, name, data, **_):
        if self.fail is not None:
            self.fail(name, data)
        if data is None:
            self.files.pop(name, None)
        else:
            self.files[name] = data

    def json(self, name):
        return json.loads(self.files[name]) if name in self.files else None

    def put_json(self, name, data):
        self.write(name, json.dumps(data).encode())


class WallpaperFixtures(unittest.TestCase):
    def setUp(self):
        txn = functions(PACKAGE/'transaction.py', {
            'encoded', 'decoded', 'plan', 'validate', 'check_current', 'check_committed', 'apply', 'rollback',
        }, {'base64': base64, 're': re, 'MAX_IMAGE_BYTES': 2 * 1024**2,
            'MAX_TOTAL_IMAGE_BYTES': 4 * 1024**2})
        self.config = MemoryTree({'gtkgreet.css': CSS, 'gtkgreet-power.css': b'window { color: white; }'})
        self.state = MemoryTree()
        fake_os = SimpleNamespace(
            urandom=lambda n: b'a' * n,
            scandir=lambda fd: contextlib.nullcontext(iter(
                SimpleNamespace(name=name) for name in list(self.config.files))),
        )
        self.code = functions(PACKAGE/'wallpaper.py', {'image_suffix', 'stylesheet', 'publish'}, {
            'hashlib': hashlib, 're': re, 'tinycss2': tinycss2, 'os': fake_os,
            'transaction': SimpleNamespace(**{key: value for key, value in txn.items() if not key.startswith('__')}),
            'MAX_BYTES': 32 * 1024**2,
            'ASSET_NAME': re.compile(r'waypaper-wallpaper-[0-9a-f]{64}\.(?:png|jpg)\Z'),
        })

    def test_publish_preserves_other_css_and_root_asset_precedes_css(self):
        self.code['publish'](self.state, self.config, PNG)
        css = self.config.files['gtkgreet.css']
        self.assertIn(b'color: #123456', css)
        name = 'waypaper-wallpaper-' + hashlib.sha256(PNG).hexdigest() + '.png'
        self.assertEqual(self.config.files[name], PNG)
        self.assertIn(name.encode(), css)
        self.assertIsNone(self.state.json('wallpaper-pending.json'))

    def test_failed_css_publication_recovers_exact_previous_bytes(self):
        def failure(name, data):
            if name == 'gtkgreet.css' and data != CSS:
                self.config.files[name] = data  # replacement happened, fsync failed
                raise OSError('injected publication failure')
        self.config.fail = failure
        with self.assertRaises(OSError):
            self.code['publish'](self.state, self.config, PNG)
        self.assertEqual(self.config.files['gtkgreet.css'], CSS)
        self.assertIsNone(self.state.json('wallpaper-pending.json'))

    def test_uncertain_rollback_retains_journal_and_blocks_other_writers(self):
        def failure(name, data):
            if name == 'gtkgreet.css':
                self.config.files[name] = b'concurrent replacement'
                raise OSError('injected replacement/rollback failure')
        self.config.fail = failure
        with self.assertRaisesRegex(RuntimeError, 'outcome unknown'):
            self.code['publish'](self.state, self.config, PNG)
        self.assertIsNotNone(self.state.json('wallpaper-pending.json'))
        for module in ('greeter.py', 'fields.py'):
            self.assertIn("state.json('wallpaper-pending.json')", (PACKAGE/module).read_text())

    def test_other_pending_writer_is_rejected_without_publication(self):
        self.state.put_json('pending.json', {'owned': 'another transaction'})
        previous = dict(self.config.files)
        with self.assertRaisesRegex(RuntimeError, 'pending greeter'):
            self.code['publish'](self.state, self.config, PNG)
        self.assertEqual(self.config.files, previous)

    def test_only_unreferenced_owned_asset_names_are_pruned(self):
        orphan = 'waypaper-wallpaper-' + '1' * 64 + '.png'
        self.config.files[orphan] = PNG
        self.config.files['administrator-image.png'] = PNG
        self.code['publish'](self.state, self.config, PNG)
        self.assertNotIn(orphan, self.config.files)
        self.assertEqual(self.config.files['administrator-image.png'], PNG)

    def test_state_identity_and_stream_deadlines_remain_explicit(self):
        controller = (TARGET/'usr/local/libexec/labwc-wallpaper-control').read_text()
        self.assertIn("component not in ('swaybg', 'swaylock')", controller)
        self.assertIn('os.O_NOFOLLOW', controller)
        self.assertIn('meta.st_nlink != 1', controller)
        self.assertIn('fcntl.LOCK_EX | fcntl.LOCK_NB', controller)
        source = (PACKAGE/'wallpaper.py').read_text()
        self.assertIn('deadline - time.monotonic()', source)
        self.assertIn('selector.select(remaining)', source)
        adapter = (TARGET/'usr/local/libexec/labwc-waypaper.tmpl').read_text()
        self.assertIn('timeout=120', adapter)
        self.assertIn('except subprocess.TimeoutExpired', adapter)
        self.assertIn('outcome is unknown', adapter)
        self.assertNotIn('shell=True', adapter)


if __name__ == '__main__':
    unittest.main()
