#!/usr/bin/python3
"""Offline regression tests; no target services, mounts, or credentials required.

Run from any directory with Python 3.11+:
    python3 -B d-i/forky/tests/test_desktop_sandbox.py -v
These tests validate code and generated policy, not kernel AppArmor enforcement.
"""
from __future__ import annotations
import ast
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import signal
import stat
import struct
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest import mock

from test_environment import skip_unless_filesystem_unix_socket

import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / 'hooks/target'
SHARED = ROOT / 'hooks/target'


def load_script(path: Path, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def document(body: str, namespace: str = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main') -> bytes:
    return (f'<w:document xmlns:w="{namespace}" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
            f'<w:body>{body}</w:body></w:document>').encode()


class LauncherSynchronizationTests(unittest.TestCase):
    def setUp(self):
        self.launcher = load_script(
            SHARED / 'usr/local/bin/labwc-sync-application-launchers',
            'tested_labwc_sync_application_launchers',
        )
        self.temporary = tempfile.TemporaryDirectory(prefix='labwc-launcher-sync-')
        self.addCleanup(self.temporary.cleanup)
        self.desktop = Path(self.temporary.name) / 'code.desktop'
        self.desktop.write_text('[Desktop Entry]\nName=Code\nType=Application\n')

    def read_with_metadata(self, *, mode: int, uid: int, gid: int,
                           allow_root_group_write: bool) -> str:
        metadata = types.SimpleNamespace(
            st_mode=stat.S_IFREG | mode,
            st_uid=uid,
            st_gid=gid,
            st_size=self.desktop.stat().st_size,
        )
        with mock.patch.object(self.launcher.os, 'fstat', return_value=metadata):
            return self.launcher.read_regular_text(
                str(self.desktop),
                {0},
                allow_root_group_write=allow_root_group_write,
            )

    def test_system_vendor_reader_accepts_root_group_writable_code_launcher(self):
        metadata = types.SimpleNamespace(
            st_mode=stat.S_IFREG | 0o775,
            st_uid=0,
            st_gid=0,
            st_size=self.desktop.stat().st_size,
        )
        with mock.patch.object(self.launcher.os, 'fstat', return_value=metadata):
            content = self.launcher.read_system_desktop_text(str(self.desktop))
        self.assertIn('[Desktop Entry]', content)

    def test_default_reader_keeps_rejecting_group_writable_input(self):
        with self.assertRaisesRegex(RuntimeError, 'untrusted principal'):
            self.read_with_metadata(
                mode=0o775,
                uid=0,
                gid=0,
                allow_root_group_write=False,
            )

    def test_system_vendor_exception_remains_fail_closed(self):
        unsafe_metadata = (
            (0o777, 0, 0),
            (0o775, 0, 1000),
            (0o775, 1000, 0),
            (0o2775, 0, 0),
            (0o770, 0, 0),
        )
        for mode, uid, gid in unsafe_metadata:
            with self.subTest(mode=oct(mode), uid=uid, gid=gid):
                with self.assertRaises(RuntimeError):
                    self.read_with_metadata(
                        mode=mode,
                        uid=uid,
                        gid=gid,
                        allow_root_group_write=True,
                    )

    def test_system_vendor_reader_keeps_the_input_size_bound(self):
        metadata = types.SimpleNamespace(
            st_mode=stat.S_IFREG | 0o775,
            st_uid=0,
            st_gid=0,
            st_size=self.launcher.MAX_DESKTOP_FILE_BYTES + 1,
        )
        with mock.patch.object(self.launcher.os, 'fstat', return_value=metadata):
            with self.assertRaisesRegex(RuntimeError, 'exceeds'):
                self.launcher.read_system_desktop_text(str(self.desktop))


class FuzzelOutputSizingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='labwc-fuzzel-output-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'
        self.runtime = self.root / 'runtime'
        self.bin = self.root / 'bin'
        self.config = self.home / '.config/fuzzel'
        for directory in (self.home, self.runtime, self.bin, self.config):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
        for name in ('fuzzel.ini', 'fuzzel-internal.ini', 'menu.ini', 'menu-internal.ini'):
            (self.config / name).write_text('[main]\n')

        source = (DESKTOP / 'usr/local/bin/labwc-fuzzel').read_text()
        source = source.replace(
            '/etc/default/labwc-desktop',
            str(self.root / 'missing-defaults'),
        ).replace(
            '/usr/local/bin/labwc-fuzzel-log',
            str(self.root / 'missing-logger'),
        )
        self.wrapper = self.root / 'labwc-fuzzel'
        self.wrapper.write_text(source)
        self.wrapper.chmod(0o700)

        fake = self.bin / 'fuzzel'
        fake.write_text(
            '#!/bin/sh\n'
            'printf "%s\\0" "$@" >"$FUZZEL_ARGUMENTS"\n'
        )
        fake.chmod(0o700)
        self.arguments_file = self.root / 'arguments'
        self.environment = {
            'HOME': str(self.home),
            'PATH': f'{self.bin}:/usr/bin:/bin',
            'XDG_CONFIG_HOME': str(self.home / '.config'),
            'XDG_RUNTIME_DIR': str(self.runtime),
            'FUZZEL_ARGUMENTS': str(self.arguments_file),
            'LABWC_OUTPUT_INTERNAL_PREFIXES': 'eDP LVDS DSI',
            'LABWC_FUZZEL_INTERNAL_MENU_WIDTH': '18',
            'LABWC_FUZZEL_INTERNAL_MENU_LINES': '8',
            'LABWC_FUZZEL_INTERNAL_FONT_SIZE': '9',
        }

    def invoke(self, *arguments: str, output: str | None = None,
               extra_environment: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[bytes], list[str]]:
        environment = dict(self.environment)
        if output is not None:
            environment['WAYBAR_OUTPUT_NAME'] = output
        if extra_environment:
            environment.update(extra_environment)
        self.arguments_file.unlink(missing_ok=True)
        result = subprocess.run(
            ['/bin/sh', str(self.wrapper), *arguments],
            input=b'',
            capture_output=True,
            env=environment,
            timeout=10,
        )
        captured = []
        if self.arguments_file.exists():
            captured = [
                value.decode()
                for value in self.arguments_file.read_bytes().split(b'\0')
                if value
            ]
        return result, captured

    def test_waybar_output_selects_internal_or_external_config(self):
        internal, internal_args = self.invoke('launcher', output='eDP-1')
        self.assertEqual(internal.returncode, 0, internal.stderr.decode())
        self.assertIn('--output=eDP-1', internal_args)
        self.assertIn(f'--config={self.config}/fuzzel-internal.ini', internal_args)

        external, external_args = self.invoke('launcher', output='DP-1')
        self.assertEqual(external.returncode, 0, external.stderr.decode())
        self.assertIn('--output=DP-1', external_args)
        self.assertIn(f'--config={self.config}/fuzzel.ini', external_args)
        self.assertNotIn(f'--config={self.config}/fuzzel-internal.ini', external_args)

    def test_explicit_internal_output_clamps_category_menu_sizing(self):
        result, arguments = self.invoke(
            'menu',
            '--dmenu',
            '--output=eDP-1',
            extra_environment={
                'LABWC_FUZZEL_MENU_WIDTH_OVERRIDE': '40',
                'LABWC_FUZZEL_MENU_LINES_OVERRIDE': '20',
                'LABWC_FUZZEL_MENU_FONT_SIZE_OVERRIDE': '16',
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(f'--config={self.config}/menu-internal.ini', arguments)
        self.assertIn('--width=18', arguments)
        self.assertIn('--lines=8', arguments)
        self.assertIn(
            '--font=Noto Sans:size=9,Noto Color Emoji:size=9,'
            'Font Awesome 6 Free:size=9',
            arguments,
        )
        self.assertNotIn('--width=40', arguments)
        self.assertNotIn('--font=Noto Sans:size=16', arguments)

    def test_untrusted_waybar_output_is_rejected_before_fuzzel(self):
        result, arguments = self.invoke('launcher', output='eDP-1;touch')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(arguments)
        self.assertIn(b'unsupported characters', result.stderr)

    def test_profiles_and_renderer_define_compact_internal_dimensions(self):
        expected = {
            'LABWC_FUZZEL_INTERNAL_WIDTH': '28',
            'LABWC_FUZZEL_INTERNAL_LINES': '10',
            'LABWC_FUZZEL_INTERNAL_MENU_WIDTH': '18',
            'LABWC_FUZZEL_INTERNAL_MENU_LINES': '8',
            'LABWC_FUZZEL_INTERNAL_FONT_SIZE': '9',
            'LABWC_FUZZEL_INTERNAL_HORIZONTAL_PAD': '10',
            'LABWC_FUZZEL_INTERNAL_VERTICAL_PAD': '6',
            'LABWC_FUZZEL_INTERNAL_INNER_PAD': '4',
            'LABWC_FUZZEL_INTERNAL_LINE_HEIGHT': '16',
        }
        for profile in (ROOT / 'hosts/profiles').glob('*.env'):
            values = {}
            for line in profile.read_text().splitlines():
                name, separator, value = line.partition('=')
                if separator and name in expected:
                    values[name] = value.strip('"')
            self.assertEqual(values, expected, profile.name)

        renderer = (ROOT / 'scripts/desktop/components.sh').read_text()
        for target in (
            '/etc/skel/primary/.config/fuzzel/base-internal.ini',
            '/etc/skel/primary/.config/fuzzel/fuzzel-internal.ini',
            '/etc/skel/primary/.config/fuzzel/menu-internal.ini',
        ):
            self.assertIn(target, renderer)
        validator = (ROOT / 'scripts/desktop/detect.sh').read_text()
        for name in expected:
            self.assertIn(f'desktop_validate_uint_range {name} ', validator)


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.codex = load_script(SHARED / 'data/codex/lib/codex', 'tested_codex')

    def test_internal_function_references_resolve(self):
        tree = ast.parse(Path(self.codex.__file__).read_text())
        defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name) and n.func.id.startswith('codex_')}
        self.assertFalse(called - defined)

    def test_appserver_requires_isolation(self):
        c = self.codex
        self.assertEqual(
            c.CODEX_APP_SERVER_ARGUMENTS,
            (
                'app-server',
                '--listen',
                'unix:///data/codex/sockets/app-server-backend.sock',
            ),
        )
        with self.assertRaises(c.CodexError):
            c.codex_parse_arguments(['--no-bwrap', *c.CODEX_APP_SERVER_ARGUMENTS])
        enabled, args = c.codex_parse_arguments(c.CODEX_APP_SERVER_ARGUMENTS)
        self.assertTrue(enabled)
        self.assertTrue(c.CODEX_APP_SERVER_MODE)
        self.assertEqual(args, list(c.CODEX_APP_SERVER_ARGUMENTS))

    def test_injected_secret_environment_names_rejected(self):
        c = self.codex
        for name in ['LD_PRELOAD', 'PYTHONPATH', 'PERL5OPT', 'PATH', 'HOME', 'BASH_ENV',
                     'CODEX_HOME', 'lowercase', 'BAD-NAME', 'X' * 129]:
            with self.subTest(name=name):
                self.assertFalse(c._app_server_secret_environment_name_is_safe(name))
        self.assertTrue(c._app_server_secret_environment_name_is_safe('MCP_ACCESS_TOKEN'))

    def test_private_proc_must_be_unobstructed(self):
        c = self.codex
        base = ['bwrap', '--unshare-pid', '--proc', '/proc']
        c.validate_private_procfs(base)
        for suffix in [['--tmpfs', '/proc/sys'], ['--ro-bind', '/proc/cpuinfo', '/proc/cpuinfo'],
                       ['--proc', '/proc'], ['--unshare-pid']]:
            with self.subTest(suffix=suffix), self.assertRaises(c.CodexError):
                c.validate_private_procfs(base + suffix)
        with self.assertRaises(c.CodexError):
            c.validate_private_procfs(['--proc', '/proc'])

    def test_cwd_keeps_spaces_and_unicode(self):
        with mock.patch.dict(os.environ, HOME='/home/test'):
            for directory in ['/pool/build/test/a project', '/data/tmp/caf\u00e9', '/home/test/Workspace/a b']:
                self.assertEqual(self.codex.codex_select_sandbox_cwd(directory), directory)
            self.assertEqual(self.codex.codex_select_sandbox_cwd('/etc'), '/home/test/Workspace')

    def test_cwd_rejects_masked_control_state(self):
        with self.assertRaises(self.codex.CodexError):
            self.codex.codex_select_sandbox_cwd('/data/codex/runtime/control')

    def bwrap_arguments(self, service=False):
        c = self.codex
        c.CODEX_CONTROL_DIR = '/control'
        c.CODEX_SANDBOX_PATH = '/usr/bin:/bin'
        c.CODEX_APP_SERVER_MODE = service
        def bind(source, destination):
            c.BWRAP_ARGS.extend(['--ro-bind', source, destination])
        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, HOME='/home/test'))
            stack.enter_context(mock.patch.object(c, 'codex_select_sandbox_cwd', return_value='/pool/build/test/a project'))
            stack.enter_context(mock.patch.object(c, '_read_bounded_text', return_value='codex-test'))
            stack.enter_context(mock.patch.object(c, 'codex_append_tmpfs_if_present'))
            stack.enter_context(mock.patch.object(c, 'codex_append_accelerator_device_binds'))
            stack.enter_context(mock.patch.object(c, 'codex_append_home_bind_if_present'))
            stack.enter_context(mock.patch.object(c, 'codex_append_ro_bind_if_present', side_effect=bind))
            stack.enter_context(mock.patch.object(c, 'codex_append_ro_bind_to_existing_path', side_effect=bind))
            stack.enter_context(mock.patch.object(c, 'codex_append_required_ro_bind_to_existing_path', side_effect=lambda _, s, d: bind(s, d)))
            return c.codex_build_bwrap_args(1000, 1000)

    def test_mount_plan_writable_roots_and_readonly_release(self):
        args = self.bwrap_arguments()
        binds = [args[i+1:i+3] for i, value in enumerate(args) if value == '--bind']
        for path in ['/pool', '/data/codex', '/data/downloads', '/data/tmp', '/tmp',
                     '/data/codex/usr/home', '/home/test/Workspace']:
            self.assertIn([path, path], binds)
        readonly = [args[i+1:i+3] for i, value in enumerate(args) if value == '--ro-bind']
        for path in ['/data/codex/lib', '/data/codex/share', '/data/codex/usr/etc']:
            self.assertIn([path, path], readonly)
        self.assertIn(['--cap-drop', 'ALL'], [args[i:i+2] for i in range(len(args)-1)])
        self.assertEqual(args.count('/proc'), 1)
        self.assertFalse(any('/usr/bin/uname' == x for x in args))

    def test_service_keeps_codex_home_writable_without_auth_overmount(self):
        args = self.bwrap_arguments(service=True)
        self.assertNotIn('--ro-bind-data', args)
        binds = [args[i+1:i+3] for i, value in enumerate(args) if value == '--bind']
        self.assertIn(['/data/codex/usr/home', '/data/codex/usr/home'], binds)
        self.assertIn(['--tmpfs', '/data/codex/credentials'],
                      [args[i:i+2] for i in range(len(args)-1)])
        self.assertNotIn('/data/codex/usr/home/auth.json', args)
        self.assertNotIn('/data/codex/credentials/auth.json', args)

    def test_generated_launcher_compiles_and_accepts_empty_bounding_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, status = Path(tmp) / 'launcher', Path(tmp) / 'status'
            self.codex.codex_render_payload_launcher(str(path), process_status_path=str(status))
            status.write_text(''.join(f'{name}:\t00000000\n' for name in ['CapInh','CapPrm','CapEff','CapBnd','CapAmb']) + 'NoNewPrivs:\t1\n')
            payload = load_script(path, 'payload')
            payload.validate_outer_capabilities()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_generated_launcher_rejects_active_caps_and_missing_nnp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, status = Path(tmp) / 'launcher', Path(tmp) / 'status'
            self.codex.codex_render_payload_launcher(str(path), process_status_path=str(status))
            payload = load_script(path, 'payload')
            for caps, nnp in [(1,1),(0,0)]:
                status.write_text(f'CapInh: 0\nCapPrm: 0\nCapEff: {caps:x}\nCapBnd: 0\nCapAmb: 0\nNoNewPrivs: {nnp}\n')
                with mock.patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
                    payload.validate_outer_capabilities()

    def test_nested_probe_command_compiles_and_marker_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'launcher'
            self.codex.codex_render_payload_launcher(str(path))
            payload = load_script(path, 'payload')
            seen = []
            def run(command, **kwargs):
                marker = Path(command[-1])
                self.assertTrue(marker.is_file())
                self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
                compile(command[command.index('-c')+1], '<nested-probe>', 'exec')
                self.assertEqual(command.count('--unshare-pid'),1)
                self.assertEqual(command.count('--proc'),1)
                seen.append(marker)
                return subprocess.CompletedProcess(command, 0, stderr=b'')
            with mock.patch.object(payload.subprocess, 'run', side_effect=run):
                payload.nested_bubblewrap_probe()
            self.assertEqual(len(seen),1)
            self.assertFalse(seen[0].exists())

    def test_nested_probe_failure_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'launcher'
            self.codex.codex_render_payload_launcher(str(path))
            payload = load_script(path, 'payload')
            result = subprocess.CompletedProcess([], 1, stderr=b'namespace denied')
            with mock.patch.object(payload.subprocess, 'run', return_value=result), mock.patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
                payload.nested_bubblewrap_probe()

    def test_pid_information_validation(self):
        c = self.codex
        self.assertEqual(c.codex_parse_sandbox_pid(b'{"child-pid": 4321}'), 4321)
        for pid in [True, 0, 1, -1, 2**32, '2', None]:
            with self.subTest(pid=pid), self.assertRaises(c.CodexError):
                c.codex_parse_sandbox_pid(json.dumps({'child-pid':pid}))

    def test_oversized_valid_json_is_not_accepted(self):
        c = self.codex
        payload = b'{"child-pid": 4321,"padding":"' + b'x' * c.MAX_BWRAP_INFO_BYTES + b'"}'
        chunks = [payload[i:i+4096] for i in range(0,len(payload),4096)]
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(c.os,'set_blocking'), mock.patch.object(c.os,'read',side_effect=chunks), mock.patch.object(c.select,'select',return_value=([7],[],[])), self.assertRaises(c.CodexError):
            c._read_json_fd(7,process)

    def test_signal_uses_pinned_pidfd(self):
        c = self.codex
        c.CODEX_SANDBOX_PIDFD = 42
        with mock.patch.object(c.signal,'pidfd_send_signal') as send, mock.patch.object(c.os,'kill',side_effect=AssertionError('numeric PID signal')):
            c._signal_sandbox(signal.SIGTERM)
        send.assert_called_once_with(42,signal.SIGTERM)


class DocumentImportTests(unittest.TestCase):
    def setUp(self):
        self.importer = load_script(DESKTOP / 'usr/local/bin/labwc-focuswriter-import', 'tested_importer')

    def test_simple_transitional_docx(self):
        self.assertEqual(self.importer.extract_text(document('<w:p><w:r><w:t>Hello</w:t></w:r></w:p>')), 'Hello\n')

    def test_strict_docx_and_arbitrary_namespace_prefix(self):
        data = document('<w:p><w:r><w:t>Modern Word</w:t></w:r></w:p>', 'http://purl.oclc.org/ooxml/wordprocessingml/main')
        data = data.replace(b'w:', b'word:').replace(b'xmlns:w=',b'xmlns:word=')
        self.assertEqual(self.importer.extract_text(data),'Modern Word\n')

    def test_content_controls_hyperlinks_and_tables(self):
        data = document('<w:sdt><w:sdtContent><w:p><w:hyperlink><w:r><w:t>Linked</w:t></w:r></w:hyperlink></w:p></w:sdtContent></w:sdt>'
                        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
        text = self.importer.extract_text(data)
        self.assertIn('Linked',text)
        self.assertIn('Cell',text)

    def test_tracked_deletions_are_not_imported(self):
        data = document('<w:p><w:del><w:r><w:t>deleted</w:t></w:r></w:del><w:ins><w:r><w:t>kept</w:t></w:r></w:ins></w:p>')
        self.assertEqual(self.importer.extract_text(data),'kept\n')

    def test_alternate_content_not_duplicated(self):
        data = document('<mc:AlternateContent><mc:Choice><w:p><w:r><w:t>choice</w:t></w:r></w:p></mc:Choice>'
                        '<mc:Fallback><w:p><w:r><w:t>fallback</w:t></w:r></w:p></mc:Fallback></mc:AlternateContent>')
        self.assertEqual(self.importer.extract_text(data),'choice\n')

    def test_tabs_and_linebreaks(self):
        data = document('<w:p><w:r><w:t>first</w:t><w:tab/><w:t>second</w:t><w:br/><w:t>third</w:t></w:r></w:p>')
        self.assertEqual(self.importer.extract_text(data),'first\tsecond\nthird\n')

    def test_empty_document_rejected(self):
        with self.assertRaises(self.importer.ImportFailure):
            self.importer.extract_text(document('<w:p/>'))

    def test_embedded_alternate_chunk_rejected(self):
        with self.assertRaises(self.importer.ImportFailure):
            self.importer.extract_text(document('<w:altChunk/>'))

    def test_dtd_entities_rejected_in_utf8_and_utf16(self):
        data = '<!DOCTYPE w:document [<!ENTITY evil SYSTEM "file:///etc/passwd">]>' + document('<w:p><w:r><w:t>&evil;</w:t></w:r></w:p>').decode()
        for encoding in ['utf-8','utf-16']:
            with self.subTest(encoding=encoding), self.assertRaises(self.importer.ImportFailure):
                self.importer.extract_text(data.encode(encoding))

    def test_deep_structure_rejected(self):
        with self.assertRaises(self.importer.ImportFailure):
            self.importer.extract_text(document('<w:sdt>' * 260 + '<w:t>x</w:t>' + '</w:sdt>' * 260))

    def test_malformed_xml_rejected(self):
        with self.assertRaises(self.importer.ImportFailure):
            self.importer.extract_text(b'<not-xml')

    def test_xml_size_limit(self):
        with mock.patch.object(self.importer, 'MAX_XML', 100), self.assertRaises(self.importer.ImportFailure):
            self.importer.extract_text(document('<w:p><w:r><w:t>long</w:t></w:r></w:p>'))

    def make_archive(self, path, duplicate=False):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
                for _ in range(2 if duplicate else 1):
                    archive.writestr('word/document.xml',document('<w:p><w:r><w:t>Draft</w:t></w:r></w:p>'))
                archive.writestr('../../never-extracted','not executable')

    def test_archive_only_reads_document_never_extracts_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.docx'
            self.make_archive(path)
            before = path.read_bytes()
            with mock.patch.object(zipfile.ZipFile,'extractall',side_effect=AssertionError('must not extract')):
                self.assertEqual(self.importer.read_docx(path),'Draft\n')
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),['a.docx'])

    def test_duplicate_document_member_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.docx'
            self.make_archive(path,True)
            with self.assertRaises(self.importer.ImportFailure):
                self.importer.read_docx(path)

    def test_central_directory_bounded_before_zipfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.docx'
            self.make_archive(path)
            data = bytearray(path.read_bytes())
            eocd = data.rfind(b'PK\x05\x06')
            struct.pack_into('<HH',data,eocd+8,10001,10001)
            path.write_bytes(data)
            with mock.patch.object(zipfile,'ZipFile',side_effect=AssertionError('must reject before allocation')), self.assertRaises(self.importer.ImportFailure):
                self.importer.read_docx(path)

    def test_truncated_archive_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.docx'
            path.write_bytes(b'PK\x03\x04')
            with self.assertRaises(self.importer.ImportFailure):
                self.importer.read_docx(path)

    def test_fifo_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.docx'
            os.mkfifo(path)
            with self.assertRaises(self.importer.ImportFailure):
                self.importer.read_docx(path)

    def test_new_private_draft_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            source = home / 'a.docx'
            source.write_bytes(b'original')
            first = self.importer.create_draft(source,'text\n',home)
            second = self.importer.create_draft(source,'text\n',home)
            self.assertNotEqual(first,second)
            self.assertEqual(source.read_bytes(),b'original')
            self.assertEqual(stat.S_IMODE(first.parent.stat().st_mode),0o700)
            self.assertEqual(stat.S_IMODE(first.stat().st_mode),0o600)
            self.assertIn('TEXT-ONLY COPY',(first.parent/'IMPORT-NOTICE.txt').read_text())

    def test_symlinked_document_output_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            elsewhere = Path(tmp) / 'elsewhere'
            elsewhere.mkdir()
            (home/'Documents').symlink_to(elsewhere)
            with self.assertRaises(self.importer.ImportFailure):
                self.importer.create_draft(home/'source.docx','draft',home)


class SessionAndIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.helper = load_script(DESKTOP / 'usr/local/libexec/labwc-session-check','tested_session')
        self.codex_ready = load_script(
            DESKTOP / 'usr/local/libexec/codex-app-server-wait-ready',
            'tested_codex_app_server_wait_ready',
        )

    def test_arbitrary_commands_are_not_accepted(self):
        for args in [[],['sh','-c','true'],['session-ready','extra']]:
            self.assertEqual(self.helper.main(args),2)

    def test_missing_wayland_environment_is_not_ready(self):
        with mock.patch.dict(os.environ,{},clear=True):
            self.assertEqual(self.helper.main(['session-ready']),1)

    @skip_unless_filesystem_unix_socket
    def test_ready_socket_checks_target_with_bounded_timeout(self):
        import socket
        with tempfile.TemporaryDirectory() as tmp, socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(Path(tmp)/'wayland-1'))
            result = subprocess.CompletedProcess([],0)
            with mock.patch.dict(os.environ,XDG_RUNTIME_DIR=tmp,WAYLAND_DISPLAY='wayland-1'), mock.patch.object(self.helper.subprocess,'run',return_value=result) as run:
                self.assertEqual(self.helper.main(['session-ready']),0)
            self.assertEqual(run.call_args.args[0][-1],'labwc-session.target')
            self.assertEqual(run.call_args.kwargs['timeout'],3)

    def test_reload_rejects_unsafe_pids(self):
        for pid in ['0','1','-1','2147483648','abc','12;id','\u0661\u0662']:
            with self.subTest(pid=pid), mock.patch.object(os,'pidfd_open',side_effect=AssertionError('must not open')):
                self.assertEqual(self.helper.main(['reload-waybar',pid]),1)

    def test_codex_unit_leaves_nnp_to_bubblewrap(self):
        data = (DESKTOP/'etc/skel/primary/.config/systemd/user/codex-app-server.service').read_text()
        self.assertIn('NoNewPrivileges=no\n',data)
        for line in data.splitlines():
            if line and not line.startswith('#'):
                self.assertFalse(line.startswith(('BindReadOnlyPaths=','RestrictNamespaces=',
                                                  'ProtectProc=','ProcSubset=','CapabilityBoundingSet=',
                                                  'RestrictSUIDSGID=','SystemCallFilter=')))
        active = '\n'.join(
            line for line in data.splitlines()
            if line.strip() and not line.lstrip().startswith(('#', ';'))
        )
        self.assertNotIn('auth.json', active)
        self.assertIn('LoadCredential=codex-mcp.env:/data/codex/credentials/mcp.env\n',data)
        self.assertIn('EnvironmentFile=-%d/codex-mcp.env\n',data)

    def test_codex_app_server_is_socket_activated_and_idle_stopped(self):
        unit_dir = DESKTOP / 'etc/skel/primary/.config/systemd/user'
        backend = (unit_dir / 'codex-app-server.service').read_text()
        proxy = (unit_dir / 'codex-app-server-proxy.service').read_text()
        socket_unit = (unit_dir / 'codex-app-server.socket').read_text()

        self.assertIn('StopWhenUnneeded=yes\n', backend)
        self.assertIn(
            'ExecStart=/data/codex/lib/codex app-server --listen '
            'unix:///data/codex/sockets/app-server-backend.sock\n',
            backend,
        )
        self.assertIn('ExecStartPost=/usr/local/libexec/codex-app-server-wait-ready\n', backend)
        self.assertNotIn('/data/codex/share/bin/codex app-server', backend)
        self.assertNotIn('WantedBy=', backend)

        self.assertIn('ListenStream=/data/codex/sockets/app-server-control.sock\n', socket_unit)
        self.assertIn('Accept=no\n', socket_unit)
        self.assertIn('SocketMode=0600\n', socket_unit)
        self.assertIn('Service=codex-app-server-proxy.service\n', socket_unit)
        self.assertIn('WantedBy=sockets.target\n', socket_unit)

        self.assertIn(
            'Requires=codex-app-server.socket codex-app-server.service\n',
            proxy,
        )
        self.assertIn(
            'ExecStart=/usr/lib/systemd/systemd-socket-proxyd '
            '--exit-idle-time=10min '
            '/data/codex/sockets/app-server-backend.sock\n',
            proxy,
        )
        self.assertNotIn('WantedBy=', proxy)

        process_exec_starts = [
            line
            for unit in (backend, proxy, socket_unit)
            for line in unit.splitlines()
            if line.startswith('ExecStart=')
        ]
        payload_starts = [
            line for line in process_exec_starts
            if ' app-server --listen ' in line
        ]
        self.assertEqual(len(payload_starts), 1)
        self.assertIn('/data/codex/lib/codex app-server', payload_starts[0])

    @skip_unless_filesystem_unix_socket
    def test_codex_backend_ready_helper_accepts_only_private_owned_socket(self):
        import socket
        with tempfile.TemporaryDirectory() as tmp:
            endpoint = Path(tmp) / 'backend.sock'
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(endpoint))
                endpoint.chmod(0o600)
                with mock.patch.object(self.codex_ready, 'BACKEND_SOCKET', str(endpoint)):
                    self.assertEqual(self.codex_ready.main([]), 0)

                endpoint.chmod(0o660)
                with mock.patch.object(self.codex_ready, 'BACKEND_SOCKET', str(endpoint)), \
                        mock.patch('sys.stderr', new=io.StringIO()):
                    self.assertEqual(self.codex_ready.main([]), 1)

            endpoint.unlink()
            endpoint.write_text('not a socket')
            with mock.patch.object(self.codex_ready, 'BACKEND_SOCKET', str(endpoint)), \
                    mock.patch('sys.stderr', new=io.StringIO()):
                self.assertEqual(self.codex_ready.main([]), 1)
        with mock.patch('sys.stderr', new=io.StringIO()):
            self.assertEqual(self.codex_ready.main(['unexpected']), 1)

    def test_codex_policy_has_no_systemd_auth_credential_access(self):
        apparmor = (DESKTOP/'etc/apparmor.d/managed-desktop-wrappers').read_text()
        self.assertNotIn('codex-auth.json', apparmor)

    def test_codex_tmpfiles_does_not_create_prelogin_auth(self):
        data = (DESKTOP/'etc/tmpfiles.d/80-codex-storage.conf.tmpl').read_text()
        self.assertNotIn('__INSTALLER_DEVOPS_CODEX_HOME__/auth.json', data)
        self.assertNotIn('__INSTALLER_DEVOPS_CODEX_ROOT__/credentials/auth.json', data)
        self.assertIn('__INSTALLER_DEVOPS_CODEX_ROOT__/credentials/mcp.env', data)

    def test_zathura_selection_uses_regular_clipboard(self):
        data = (DESKTOP/'etc/skel/primary/.config/zathura/zathurarc').read_text()
        self.assertIn('set selection-clipboard clipboard',data)
        self.assertIn('set recolor false',data)

    def test_docx_default_remains_focuswriter(self):
        data = (DESKTOP/'etc/skel/primary/.config/mimeapps.list').read_text()
        matches = [line for line in data.splitlines() if line.startswith('application/vnd.openxmlformats-officedocument.wordprocessingml.document=')]
        self.assertEqual(len(matches),2)
        self.assertTrue(all('=focuswriter.desktop;' in line for line in matches))

    def test_new_desktop_assets_are_explicitly_staged(self):
        staging = (ROOT/'scripts/desktop/components.sh').read_text()
        for path in ['.config/zathura/zathurarc','usr/local/bin/labwc-focuswriter-import',
                     'usr/local/libexec/labwc-session-check','usr/local/libexec/whisper-record-timed',
                     'usr/local/libexec/codex-app-server-wait-ready',
                     '.config/systemd/user/codex-app-server-proxy.service',
                     '.config/systemd/user/codex-app-server.socket',
                     'usr/local/share/applications/labwc-focuswriter-import.desktop']:
            self.assertIn(path,staging)

    def test_new_policies_are_staged_and_required(self):
        staging = (ROOT/'scripts/late/security.sh').read_text()
        modes = (SHARED/'etc/apparmor/managed-modes.conf.tmpl').read_text()
        for name in ['managed-document-applications','managed-desktop-utilities','managed-labwc-session']:
            self.assertIn(name,staging)
            self.assertIn(name,modes)
            self.assertTrue((SHARED/'etc/apparmor.d'/name).is_file())
        for name in ['managed-devops-toolchain-data','managed-user-documents','managed-document-runtime',
                     'managed-session-client']:
            self.assertIn('abstractions/'+name,staging)

    def test_shared_tmp_directory_created_for_fresh_install(self):
        path = next(SHARED.rglob('80-codex-storage.conf.tmpl'))
        self.assertIn('d /data/tmp 3770 root devops -',path.read_text())


class InstalledFailureRegressionTests(unittest.TestCase):
    def test_auth_log_signals_only_explicit_failures(self):
        policy = (DESKTOP / 'etc/rsyslog.d/20-auth.conf').read_text()
        start = policy.index('  if (\n    $msg contains')
        end = policy.index('  ) then {', start)
        patterns = [
            line.split('"', 2)[1]
            for line in policy[start:end].splitlines()
            if '$msg contains "' in line
        ]
        self.assertGreaterEqual(len(patterns), 8)
        routine_messages = (
            'pam_unix(sudo:session): session opened for user root(uid=0)',
            'pam_unix(sudo:session): session closed for user root',
            'mcramer : TTY=pts/0 ; PWD=/home/mcramer ; USER=root ; COMMAND=/usr/bin/id',
            'Accepted publickey for mcramer from 192.0.2.10 port 4242 ssh2',
        )
        failed_messages = (
            'pam_unix(sudo:auth): authentication failure; logname=mcramer',
            'Failed password for invalid user example from 192.0.2.10 port 4242 ssh2',
            'mcramer is not in the sudoers file; user NOT in sudoers',
        )
        for message in routine_messages:
            self.assertFalse(any(pattern in message for pattern in patterns), message)
        for message in failed_messages:
            self.assertTrue(any(pattern in message for pattern in patterns), message)
        self.assertLess(policy.index('name="managed_auth_log"'), start)
        notifier = (DESKTOP / 'usr/local/bin/labwc-health-notify').read_text()
        self.assertIn('"Failed authentication detected"', notifier)
        self.assertNotIn('"Authentication activity detected"', notifier)

    @unittest.skipUnless(Path('/usr/sbin/rsyslogd').is_file(), 'rsyslogd is unavailable')
    def test_auth_rainerscript_parses(self):
        source = (DESKTOP / 'etc/rsyslog.d/20-auth.conf').read_text()
        sanitized = '\n'.join(
            line for line in source.splitlines()
            if not line.lstrip().startswith(('fileOwner=', 'fileGroup=', 'dirOwner=', 'dirGroup='))
        ) + '\n'
        with tempfile.TemporaryDirectory(prefix='auth-rsyslog-') as tmp:
            tmp_path = Path(tmp)
            fragment = tmp_path / '20-auth.conf'
            fragment.write_text(sanitized)
            config = tmp_path / 'rsyslog.conf'
            config.write_text(
                'module(load="imuxsock")\n'
                f'include(file="{fragment}" mode="required")\n'
            )
            result = subprocess.run(
                ['/usr/sbin/rsyslogd', '-N1', '-f', str(config)],
                capture_output=True,
                text=True,
                timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_desktop_service_contracts_are_repaired(self):
        plans = (DESKTOP / 'etc/skel/primary/.config/systemd/user/labwc-plans.service').read_text()
        self.assertIn('EnvironmentFile=/etc/default/labwc-plans\n', plans)
        self.assertNotIn('LoadCredential=', plans)
        self.assertNotIn('EnvironmentFile=%d/', plans)

        staging = (ROOT / 'scripts/desktop/components.sh').read_text()
        for module in ('Audio.pm', 'State.pm', 'Systemd.pm'):
            path = f'usr/local/lib/perl5/site_perl/whisper/WhisperMode/{module}'
            self.assertIn(path, staging)
        self.assertIn('desktop_normalize_system_perl_module_parents', staging)
        self.assertIn('whisper_normalize_system_perl_module_parents',
                      (ROOT / 'scripts/late/whisper.sh').read_text())
        self.assertIn('software_normalize_system_perl_module_parents',
                      (ROOT / 'scripts/late/software.sh').read_text())

        apparmor = (DESKTOP / 'etc/apparmor.d/managed-desktop-wrappers').read_text()
        self.assertIn('/usr/local/lib/perl5/site_perl/whisper/** r,', apparmor)
        for executable in ('flock', 'head', 'mktemp', 'mv', 'stat', 'timeout'):
            self.assertIn(executable, apparmor)

    def test_wallpaper_and_xwayland_boot_contracts_are_explicit(self):
        expected = '/usr/share/backgrounds/desktop/wallpaper-1920x1080.png'
        with tarfile.open(DESKTOP / 'usr/share/backgrounds/desktop/wallpapers.tar.gz', 'r:gz') as archive:
            self.assertIn('labwall0-1920x1080.png', archive.getnames())
        for profile in (ROOT / 'hosts/profiles').glob('*.env'):
            profile_text = profile.read_text()
            if 'LABWC_WALLPAPER_PATH=' in profile_text:
                self.assertIn(f'LABWC_WALLPAPER_PATH="{expected}"', profile_text, profile.name)
        fallback = DESKTOP / expected.lstrip('/')
        self.assertTrue(fallback.is_file())
        fallback_bytes = fallback.read_bytes()
        self.assertGreaterEqual(len(fallback_bytes), 24)
        self.assertEqual(fallback_bytes[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(fallback_bytes[12:16], b'IHDR')
        self.assertEqual(struct.unpack('>II', fallback_bytes[16:24]), (1920, 1080))
        helper = (DESKTOP / 'usr/local/libexec/labwc-swaybg').read_text()
        self.assertIn(f'LABWC_WALLPAPER_PATH:-{expected}', helper)
        self.assertIn('resolved_saved_wallpaper=$(readlink -e', helper)
        self.assertIn('if [ -f "$resolved_saved_wallpaper" ]', helper)
        self.assertIn(f'wallpaper = {expected}',
                      (DESKTOP / 'etc/skel/primary/.config/waypaper/config.ini').read_text())

        tmpfiles = (DESKTOP / 'etc/tmpfiles.d/tmp.conf').read_text()
        self.assertIn('d /tmp/.X11-unix 1777 root root -', tmpfiles)
        compositor = (DESKTOP / 'etc/skel/primary/.config/systemd/user/labwc-compositor.service').read_text()
        self.assertNotIn('Environment=WLR_XWAYLAND=', compositor)
        self.assertIn('UnsetEnvironment=DISPLAY XAUTHORITY WLR_XWAYLAND ', compositor)
        self.assertIn('InaccessiblePaths=-/opt/xwayland', compositor)
        packages = (ROOT / 'classes/class-select/role/desktop.cfg').read_text().split()
        self.assertNotIn('xwayland', packages)
        xwayland = (ROOT / 'scripts/desktop/xwayland.sh').read_text()
        self.assertIn('purge xwayland', xwayland)
        self.assertIn('public /usr/bin/Xwayland must not exist', xwayland)
        profiles = (DESKTOP / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py').read_text()
        sandbox = (DESKTOP / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py').read_text()
        self.assertIn('WAYLAND_COMPAT_APPS = ("discord", "zoom")', profiles)
        self.assertIn('WAYLAND_COMPAT_RUNTIME_ROOT = "/opt/xwayland"', profiles)
        self.assertIn('if private_xwayland_binary is not None and app_name not in WAYLAND_COMPAT_APPS:', sandbox)
        self.assertIn('private Xwayland is not permitted for {app_name}', sandbox)
        firstboot = (ROOT / 'scripts/firstboot/04-validation.sh').read_text()
        self.assertIn('desktop-x11-socket-directory-metadata', firstboot)
        self.assertIn('desktop-public-xwayland-binary', firstboot)
        self.assertIn('desktop-public-xwayland-package-absent', firstboot)
        self.assertIn('desktop-wallpaper-config', firstboot)
        firstboot_unit = (DESKTOP / 'etc/systemd/system/firstboot.service').read_text()
        self.assertIn('Requires=local-fs.target systemd-tmpfiles-setup.service', firstboot_unit)
        self.assertIn('Wants=network-online.target apparmor-managed-modes.service', firstboot_unit)
        self.assertIn('After=local-fs.target systemd-tmpfiles-setup.service systemd-journald.socket network-online.target apparmor-managed-modes.service', firstboot_unit)
        self.assertIn('WantedBy=multi-user.target', firstboot_unit)
        self.assertNotIn('Before=sysinit.target', firstboot_unit)

    def test_pool_and_apparmor_cache_contracts_are_consistent(self):
        codex = (DESKTOP / 'data/codex/lib/codex').read_text()
        environment = (DESKTOP / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app/environment.py').read_text()
        self.assertIn('CODEX_DEVOPS_GROUP, 0o3775, True', codex)
        self.assertIn('CHATGPT_POOL_ROOT_MODE = 0o3775', environment)
        self.assertIn('desktop-pool-root-metadata',
                      (ROOT / 'scripts/firstboot/04-validation.sh').read_text())

        cache = (DESKTOP / 'etc/tmpfiles.d/50-var-cache.conf.tmpl').read_text()
        self.assertIn('__INSTALLER_DIR_VAR_CACHE__/apparmor 0755 root root -', cache)
        dropin = DESKTOP / 'etc/systemd/system/apparmor.service.d/20-managed-cache.conf'
        self.assertTrue(dropin.is_file())
        self.assertIn('ExecStartPre=/usr/bin/install -d -o root -g root -m 0755 /var/cache/apparmor',
                      dropin.read_text())
        self.assertIn('20-managed-cache.conf', (ROOT / 'scripts/late/security.sh').read_text())

    def test_named_apparmor_runtime_gaps_are_covered(self):
        def profile_block(source, name):
            marker = f'profile {name} '
            start = source.index(marker)
            end = source.find('\nprofile ', start + len(marker))
            return source[start:] if end < 0 else source[start:end]

        def direct_device_link_grants(source):
            grants = []
            for raw_line in source.splitlines():
                line = raw_line.strip()
                if '/dev/char/' not in line or line.startswith(('#', 'deny ')):
                    continue
                if line.startswith(('link ', 'owner link ')):
                    grants.append(line)
                    continue
                fields = line.rstrip(',').split()
                if len(fields) >= 2 and 'l' in fields[-1]:
                    grants.append(line)
            return grants

        policy = (DESKTOP / 'etc/apparmor.d/managed-labwc-session').read_text()
        compositor = profile_block(policy, 'managed-labwc-compositor')
        for rule in (
            '/usr/local/share/** r,',
            'owner /proc/[0-9]*/uid_map r,',
            'owner /tmp/.X[0-9]*-lock rwk,',
            'owner /run/user/[0-9]*/labwc-greeter.*/** rwkl,',
            'owner @{HOME}/.local/share/applications/*.desktop r,',
            'deny /dev/char/*:* l,',
            'deny /var/cache/fontconfig/ w,',
        ):
            self.assertIn(rule, compositor)
        self.assertEqual(direct_device_link_grants(compositor), [])

        waybar = profile_block(policy, 'managed-waybar')
        for rule in (
            '/usr/bin/bwrap rPx -> managed-session-glycin-bwrap,',
            '/proc/[0-9]*/net/dev r,',
            'owner /proc/[0-9]*/task/[0-9]*/comm rw,',
            '/dev/rfkill r,',
            'owner @{HOME}/.local/share/gvfs-metadata/{root,root-*.log} r,',
            'owner @{HOME}/.local/share/tutanota-desktop/ r,',
            'owner @{HOME}/Desktop/ r,',
            'signal (send) set=(kill) peer=managed-session-glycin-bwrap,',
        ):
            self.assertIn(rule, waybar)
        self.assertNotIn('owner /proc/[0-9]*/net/dev r,', waybar)

        controls = profile_block(policy, 'managed-session-controls')
        for rule in (
            'deny network inet,',
            'deny network inet6,',
            'owner @{HOME}/.cache/{nwg-look,qt6ct,wayscriber}/ rw,',
            'owner @{HOME}/.cache/glycin/ rw,',
            'owner @{HOME}/.cache/glycin/** rwkl,',
            'owner /run/user/[0-9]*/wayscriber/** rwkl,',
            'signal (send) set=(kill) peer=managed-session-glycin-bwrap,',
        ):
            self.assertIn(rule, controls)
        glycin = profile_block(policy, 'managed-session-glycin-bwrap')
        for rule in (
            '/dev/rfkill r,',
            '/usr/libexec/glycin-loaders/2+/{glycin-image-rs,glycin-svg} rix,',
            '/usr/share/icons/Papirus/24x24/panel/update-low.svg r,',
            'owner @{HOME}/.cache/glycin/** rwkl,',
        ):
            self.assertIn(rule, glycin)
        explicit_link_rules = [line.strip() for line in policy.splitlines() if ' link ' in line]
        for rule in (
            'owner link "@{HOME}/.config/crystal-dock/labwc/appearance.conf.*" -> "@{HOME}/.config/crystal-dock/labwc/#[0-9]*",',
            'owner link "@{HOME}/.config/kwalletrc.*" -> "@{HOME}/.config/#[0-9]*",',
            'owner link "@{HOME}/.local/share/kwalletd/*.kwl.*" -> "@{HOME}/.local/share/kwalletd/#[0-9]*",',
        ):
            self.assertIn(rule, explicit_link_rules)
        self.assertTrue(all(' subset ' not in rule for rule in explicit_link_rules))
        self.assertIn('@{PROC}/sys/kernel/core_pattern r,', policy)
        self.assertIn('@{PROC}/[0-9]*/mountinfo r,', policy)

        wrappers = (DESKTOP / 'etc/apparmor.d/managed-desktop-wrappers').read_text()
        autostart = profile_block(wrappers, 'managed-labwc-autostart')
        self.assertIn('/usr/bin/{sleep,stat,timeout} rix,', autostart)
        self.assertIn('owner /run/user/[0-9]*/systemd/ r,', autostart)

        calendar = profile_block(wrappers, 'managed-labwc-calendar')
        self.assertIn('/usr/bin/{cat,chmod,flock,grep,id,install,mkdir,mktemp,rm,rmdir,stat,timeout} rix,',
                      calendar)
        self.assertIn('owner /run/user/[0-9]*/labwc-calendar-sync.lock rwk,', calendar)

        output_watch = profile_block(wrappers, 'managed-labwc-output-watch')
        for rule in (
            'network netlink raw,',
            '/usr/bin/{systemctl,timeout,udevadm,wlopm,wlr-randr} rix,',
            '/usr/bin/wayland-info rix,',
            '/etc/udev/udev.conf r,',
            '/etc/udev/udev.conf.d/** r,',
            '/dev/dri/ r,',
            '/dev/dri/card[0-9]* rw,',
            '/dev/shm/wlroots-* r,',
            '@{sys}/devices/pci*/**/{device,subsystem_device,subsystem_vendor,uevent,vendor} r,',
        ):
            self.assertIn(rule, output_watch)
        self.assertNotIn(' pux,', output_watch)

        codex = profile_block(wrappers, 'managed-codex-wrapper')
        for rule in (
            '/dev/pts/[0-9]* rw,',
            '@{PROC}/[0-9]*/fd/ r,',
            'owner /run/user/[0-9]*/{ansible,python}/ rw,',
            'owner /run/user/[0-9]*/ansible/{pc,ssh,tmp}/ rw,',
            'owner /run/user/[0-9]*/python/pycache/ rw,',
        ):
            self.assertIn(rule, codex)
        codex_slirp = profile_block(wrappers, 'managed-codex-slirp4netns')
        self.assertIn('/dev/pts/[0-9]* rw,', codex_slirp)
        self.assertIn('ptrace (readby) peer=managed-desktop-launcher,', codex_slirp)

        for profile_name in (
            'managed-labwc-bluetooth',
            'managed-labwc-brightness-control',
            'managed-labwc-capture',
            'managed-labwc-keyboard-layout',
        ):
            self.assertIn('/dev/rfkill r,', profile_block(wrappers, profile_name))
        keyboard = profile_block(wrappers, 'managed-labwc-keyboard-layout')
        self.assertIn('/sys/devices/**/power_supply/*/status r,', keyboard)
        brightness = profile_block(wrappers, 'managed-labwc-brightness-control')
        self.assertIn('@{sys}/devices/**/power_supply/*/status r,', brightness)
        self.assertIn('/dev/rfkill r,', profile_block(wrappers, 'managed-labwc-managed-app'))
        self.assertIn('/dev/rfkill r,', profile_block(wrappers, 'managed-labwc-terminal'))

        health = profile_block(wrappers, 'managed-labwc-health-notify')
        for executable in ('flock', 'head', 'mktemp', 'mv', 'stat', 'timeout'):
            self.assertIn(executable, health)
        waypaper = profile_block(wrappers, 'managed-waypaper')
        self.assertIn('/usr/share/poppler/cMap/** r,', waypaper)
        self.assertIn('owner @{HOME}/.cache/glycin/** rwkl,', waypaper)
        swaybg = profile_block(wrappers, 'managed-labwc-swaybg')
        self.assertIn('/usr/bin/readlink rix,', swaybg)
        session = profile_block(wrappers, 'managed-labwc-session')
        self.assertIn('/usr/bin/{flock,grep,id,jq,sleep,stat} rix,', session)
        microphone = profile_block(wrappers, 'managed-labwc-mute-default-microphone')
        self.assertIn('/usr/local/lib/perl5/site_perl/whisper/** r,', microphone)
        self.assertIn('owner /run/user/[0-9]*/whisper-record-toggle.{lock,recording} rwk,', microphone)
        whisper = profile_block(wrappers, 'managed-whisper-record-toggle')
        self.assertIn('network inet6 dgram,', whisper)
        self.assertIn('#include <abstractions/managed-desktop-graphics>', whisper)
        self.assertEqual(direct_device_link_grants(whisper), [])
        external_notify = profile_block(wrappers, 'managed-managed-external-software-notify')
        self.assertIn('/usr/bin/timeout rix,', external_notify)

        firstboot = (DESKTOP / 'etc/apparmor.d/managed-system-wrappers').read_text()
        crowdsec = profile_block(firstboot, 'managed-crowdsec-firstboot')
        self.assertIn('#include <abstractions/managed-wrapper-python>', crowdsec)
        self.assertIn('/usr/local/libexec/crowdsec-bouncer-verify rix,', crowdsec)
        self.assertIn('/usr/local/libexec/ r,', crowdsec)
        managed_firstboot = profile_block(firstboot, 'managed-firstboot')
        for rule in (
            'capability chown,',
            'capability fowner,',
            '/etc/default/labwc-desktop rw,',
        ):
            self.assertIn(rule, managed_firstboot)
        for executable in ('mktemp', 'stat', 'timeout'):
            self.assertIn(executable, crowdsec)

        launcher = (DESKTOP / 'etc/apparmor.d/managed-desktop-utilities').read_text()
        for rule in (
            'capability sys_ptrace,',
            '/usr/ r,',
            '/data/bin/ r,',
            '/data/codex/lib/ r,',
            '/data/llama/{bin,lib}/ r,',
            '/var/log/ r,',
            '/run/log/journal/ r,',
            '/var/log/journal/*/user-[0-9]*.journal r,',
            '/var/lib/systemd/catalog/database r,',
        ):
            self.assertIn(rule, launcher)
        for peer in (
            'managed-codex-slirp4netns',
            'managed-codex-wrapper',
            'managed-codex-wrapper//codex-bwrap',
            'managed-crystal-dock',
            'managed-ksecretd',
            'managed-labwc-bluetooth',
            'managed-labwc-calendar',
            'managed-labwc-compositor',
            'managed-labwc-fuzzel',
            'managed-labwc-health-notify',
            'managed-labwc-managed-app',
            'managed-labwc-managed-app//managed-app-bwrap',
            'managed-labwc-output-watch',
            'managed-labwc-plans',
            'managed-labwc-session',
            'managed-session-controls',
            'managed-session-glycin-bwrap',
            'managed-waybar',
            'managed-whisper-record-toggle',
            'unconfined',
        ):
            self.assertIn(f'ptrace (read) peer={peer},', launcher)

        session_client = (DESKTOP / 'etc/apparmor.d/abstractions/managed-session-client').read_text()
        self.assertIn('/dev/shm/ r,', session_client)
        self.assertIn('owner /dev/shm/** rwkl,', session_client)
        self.assertIn('owner /proc/[0-9]*/cgroup r,', session_client)

        audio = (DESKTOP / 'etc/apparmor.d/abstractions/managed-pipewire-audio').read_text()
        self.assertIn('owner @{HOME}/.config/pulse/ rw,', audio)
        graphics = (DESKTOP / 'etc/apparmor.d/abstractions/managed-desktop-graphics').read_text()
        self.assertIn('deny /dev/char/*:* l,', graphics)
        self.assertEqual(direct_device_link_grants(graphics), [])

    def test_unix_chkpwd_local_policy_is_staged(self):
        include = DESKTOP / 'etc/apparmor.d/local/unix-chkpwd'
        self.assertTrue(include.is_file())
        self.assertIn('/dev/pts/[0-9]* rw,', include.read_text())
        self.assertNotIn('owner /dev/pts/[0-9]* rw,', include.read_text())
        security = (ROOT / 'scripts/late/security.sh').read_text()
        self.assertIn('usr.bin.pasta\nslirp4netns\nunix-chkpwd\nEOF', security)
        self.assertIn('for apparmor_local_include in $(apparmor_support_local_include_files); do',
                      security)

    def test_installed_service_and_sandbox_failures_are_repaired(self):
        staging = (ROOT / 'scripts/desktop/components.sh').read_text()
        for fragment in (
            'desktop_normalize_system_dbus_service_directories',
            'desktop_stage_global_user_unit_dropin_asset wireplumber.service 20-no-root.conf',
            'etc/udev/rules.d/71-managed-nvidia-char-links.rules',
        ):
            self.assertIn(fragment, staging)

        nvidia_rule_asset = (
            'desktop_stage_role_asset etc/udev/rules.d/71-managed-nvidia-char-links.rules '
            '/etc/udev/rules.d/71-managed-nvidia-char-links.rules 0644'
        )
        self.assertEqual(staging.count(nvidia_rule_asset), 1)
        nvidia_asset_offset = staging.index(nvidia_rule_asset)
        nvidia_branch_start = staging.rfind(
            '  if [ "${LABWC_NVIDIA_ACCELERATION_AVAILABLE:-false}" = true ]; then\n',
            0,
            nvidia_asset_offset,
        )
        self.assertNotEqual(nvidia_branch_start, -1)
        nvidia_branch_else = staging.index('\n  else\n', nvidia_asset_offset)
        nvidia_branch_end = staging.index('\n  fi\n', nvidia_branch_else)
        self.assertLess(nvidia_branch_start, nvidia_asset_offset)
        self.assertLess(nvidia_asset_offset, nvidia_branch_else)
        nvidia_false_branch = staging[nvidia_branch_else:nvidia_branch_end]
        self.assertIn(
            '/target/etc/udev/rules.d/71-managed-nvidia-char-links.rules',
            nvidia_false_branch,
        )

        wireplumber = (DESKTOP / 'etc/systemd/user/wireplumber.service.d/20-no-root.conf').read_text()
        self.assertIn('ConditionUser=!root', wireplumber)
        nvidia_rules = (DESKTOP / 'etc/udev/rules.d/71-managed-nvidia-char-links.rules').read_text()
        self.assertIn('KERNEL=="nvidia[0-9]*"', nvidia_rules)
        self.assertIn('KERNEL=="nvidiactl|nvidia-modeset|nvidia-uvm|nvidia-uvm-tools"', nvidia_rules)
        self.assertEqual(nvidia_rules.count('SYMLINK+="char/%M:%m"'), 2)

        firstboot_early = (ROOT / 'scripts/firstboot/01-early.sh').read_text()
        self.assertIn('[ ! -f "$desktop_defaults" ] || [ -L "$desktop_defaults" ]', firstboot_early)
        self.assertIn('chown root:root "$desktop_defaults"', firstboot_early)
        self.assertIn('chmod 0644 "$desktop_defaults"', firstboot_early)
        firstboot_validation = (ROOT / 'scripts/firstboot/04-validation.sh').read_text()
        for label in (
            'desktop-defaults-metadata',
            'desktop-system-dbus-service-directory-metadata',
            'desktop-wireplumber-root-condition',
            'desktop-nvidia-char-device-links',
        ):
            self.assertIn(label, firstboot_validation)
        self.assertNotIn('validation_deferred=true', firstboot_validation)

        apparmor_modes = (DESKTOP / 'etc/systemd/system/apparmor-managed-modes.service').read_text()
        self.assertIn('After=apparmor.service mullvad-apparmor.service', apparmor_modes)
        greeter = (DESKTOP / 'usr/local/bin/labwc-greeter-session.tmpl').read_text()
        self.assertIn('export GTK_USE_PORTAL=0', greeter)
        self.assertIn('export GIO_USE_PORTALS=0', greeter)
        verify = (ROOT / 'scripts/desktop/verify.sh').read_text()
        self.assertIn('managed icon theme is unavailable', verify)

        profiles = (DESKTOP / 'usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py').read_text()
        persistent = profiles.index('PERSISTENT_SANDBOX_CONFIG = {')
        start = profiles.index('    "tutanota": {', persistent)
        end = profiles.index('    "zoom": {', start)
        tutanota = profiles[start:end]
        self.assertIn('"require_system_bus": True,', tutanota)
        self.assertIn('"system_dbus_names": TUTA_SYSTEM_DBUS_NAMES,', tutanota)
        self.assertIn(
            'TUTA_SYSTEM_DBUS_NAMES = (\n'
            '    "org.freedesktop.UPower",\n'
            ')',
            profiles,
        )

    def test_tooling_resolves_python_when_sys_executable_is_empty(self):
        modules = (
            load_script(ROOT.parents[1] / 'tools/build.py', 'tested_build'),
            load_script(ROOT.parents[1] / 'tools/validate.py', 'tested_validate'),
        )
        with tempfile.TemporaryDirectory(prefix='python-interpreter-') as directory:
            candidate = Path(directory) / 'python3'
            candidate.write_text('#!/bin/sh\nexit 0\n')
            candidate.chmod(0o755)
            for module in modules:
                with self.subTest(module=module.__file__), \
                     mock.patch.object(module.sys, 'executable', ''), \
                     mock.patch.object(module.shutil, 'which', return_value=str(candidate)):
                    self.assertEqual(module.resolve_python_interpreter(), str(candidate))
                with self.subTest(module=module.__file__), \
                     mock.patch.object(module.sys, 'executable', ''), \
                     mock.patch.object(module.shutil, 'which', return_value=None), \
                     self.assertRaises(ValueError):
                    module.resolve_python_interpreter()

        validate = modules[1]
        with mock.patch.dict(validate.os.environ, {'PATH': '/caller-specific'}, clear=True):
            child_environment = validate.validation_environment()
            self.assertEqual(child_environment['PATH'], validate.VALIDATION_PATH)
            self.assertEqual(validate.os.environ['PATH'], '/caller-specific')
        self.assertEqual(
            validate.VALIDATION_PATH,
            '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        )

    def test_wayscriber_self_update_watcher_is_disabled(self):
        unit = (DESKTOP / 'etc/systemd/user/wayscriber.service.d/10-labwc-session.conf').read_text()
        self.assertIn('Environment=WAYSCRIBER_DISABLE_UPDATE_CHECK=1\n', unit)


if __name__ == '__main__':
    unittest.main()
