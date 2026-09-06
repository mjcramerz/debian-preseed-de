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
import tempfile
import types
import unittest
from unittest import mock
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
        with self.assertRaises(c.CodexError):
            c.codex_parse_arguments(['--no-bwrap', *c.CODEX_APP_SERVER_ARGUMENTS])
        enabled, args = c.codex_parse_arguments(c.CODEX_APP_SERVER_ARGUMENTS)
        self.assertTrue(enabled)
        self.assertTrue(c.CODEX_APP_SERVER_MODE)
        self.assertEqual(args, list(c.CODEX_APP_SERVER_ARGUMENTS))

    def test_non_service_arguments_do_not_import_credentials(self):
        c = self.codex
        c.codex_parse_arguments(['app-server', '--listen', 'tcp://127.0.0.1:4321'])
        with mock.patch.object(c.os, 'open', side_effect=AssertionError('must not open')):
            c.codex_capture_auth_credential()
        self.assertIsNone(c.CODEX_AUTH_FD)

    def test_injected_secret_environment_names_rejected(self):
        c = self.codex
        for name in ['LD_PRELOAD', 'PYTHONPATH', 'PERL5OPT', 'PATH', 'HOME', 'BASH_ENV',
                     'CODEX_HOME', 'lowercase', 'BAD-NAME', 'X' * 129]:
            with self.subTest(name=name):
                self.assertFalse(c._app_server_secret_environment_name_is_safe(name))
        self.assertTrue(c._app_server_secret_environment_name_is_safe('MCP_ACCESS_TOKEN'))

    def credential_context(self, directory: Path):
        c = self.codex
        expected = f'/run/user/{os.getuid()}/credentials/codex-app-server.service'
        real_open = os.open
        def opened(path, flags, *args, **kwargs):
            return real_open(directory if path == expected else path, flags, *args, **kwargs)
        stack = ExitStack()
        stack.enter_context(mock.patch.dict(os.environ, CREDENTIALS_DIRECTORY=expected))
        stack.enter_context(mock.patch.object(c.os.path, 'realpath', side_effect=lambda path: path))
        stack.enter_context(mock.patch.object(c.os, 'open', side_effect=opened))
        c.CODEX_APP_SERVER_MODE = True
        return stack

    def test_auth_credential_is_rewound_readonly_fd(self):
        c = self.codex
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'codex-auth.json'
            path.write_text('{"test": "not-a-real-credential"}')
            path.chmod(0o600)
            with self.credential_context(Path(tmp)):
                c.codex_capture_auth_credential()
                try:
                    self.assertEqual(json.loads(os.read(c.CODEX_AUTH_FD, 4096)), {'test': 'not-a-real-credential'})
                    with self.assertRaises(OSError):
                        os.write(c.CODEX_AUTH_FD, b'x')
                finally:
                    os.close(c.CODEX_AUTH_FD)
                    c.CODEX_AUTH_FD = None

    def test_auth_rejects_world_readable_file(self):
        c = self.codex
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'codex-auth.json'
            path.write_text('{}')
            path.chmod(0o644)
            with self.credential_context(Path(tmp)), self.assertRaises(c.CodexError):
                c.codex_capture_auth_credential()
            self.assertIsNone(c.CODEX_AUTH_FD)

    def test_auth_rejects_non_object_and_oversize(self):
        c = self.codex
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'codex-auth.json'
            for data in [b'[]', b'broken', b'{' + b' ' * c.MAX_AUTH_CREDENTIAL_BYTES + b'}']:
                path.write_bytes(data)
                path.chmod(0o600)
                with self.subTest(size=len(data)), self.credential_context(Path(tmp)), self.assertRaises(c.CodexError):
                    c.codex_capture_auth_credential()
                self.assertIsNone(c.CODEX_AUTH_FD)

    def test_auth_rejects_symlink(self):
        c = self.codex
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'actual'
            target.write_text('{}')
            target.chmod(0o600)
            (Path(tmp) / 'codex-auth.json').symlink_to(target)
            with self.credential_context(Path(tmp)), self.assertRaises(OSError):
                c.codex_capture_auth_credential()

    def test_auth_rejects_arbitrary_credential_directory(self):
        c = self.codex
        c.CODEX_APP_SERVER_MODE = True
        with mock.patch.dict(os.environ, CREDENTIALS_DIRECTORY='/tmp/attacker'), self.assertRaises(c.CodexError):
            c.codex_capture_auth_credential()

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
        c.CODEX_AUTH_FD = 123 if service else None
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

    def test_service_credential_uses_readonly_bind_data(self):
        args = self.bwrap_arguments(service=True)
        index = args.index('--ro-bind-data')
        self.assertEqual(args[index-2:index+3], ['--perms','0600','--ro-bind-data','123','/data/codex/usr/home/auth.json'])
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

    def test_arbitrary_commands_are_not_accepted(self):
        for args in [[],['sh','-c','true'],['session-ready','extra']]:
            self.assertEqual(self.helper.main(args),2)

    def test_missing_wayland_environment_is_not_ready(self):
        with mock.patch.dict(os.environ,{},clear=True):
            self.assertEqual(self.helper.main(['session-ready']),1)

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
        data = (DESKTOP/'etc/skel/.config/systemd/user/codex-app-server.service').read_text()
        self.assertIn('NoNewPrivileges=no\n',data)
        for line in data.splitlines():
            if line and not line.startswith('#'):
                self.assertFalse(line.startswith(('BindReadOnlyPaths=','RestrictNamespaces=',
                                                  'ProtectProc=','ProcSubset=','CapabilityBoundingSet=',
                                                  'RestrictSUIDSGID=','SystemCallFilter=')))
        self.assertIn('LoadCredential=codex-auth.json:',data)

    def test_zathura_selection_uses_regular_clipboard(self):
        data = (DESKTOP/'etc/skel/.config/zathura/zathurarc').read_text()
        self.assertIn('set selection-clipboard clipboard',data)
        self.assertIn('set recolor false',data)

    def test_docx_default_remains_focuswriter(self):
        data = (DESKTOP/'etc/skel/.config/mimeapps.list').read_text()
        matches = [line for line in data.splitlines() if line.startswith('application/vnd.openxmlformats-officedocument.wordprocessingml.document=')]
        self.assertEqual(len(matches),2)
        self.assertTrue(all('=focuswriter.desktop;' in line for line in matches))

    def test_new_desktop_assets_are_explicitly_staged(self):
        staging = (ROOT/'scripts/desktop/components.sh').read_text()
        for path in ['.config/zathura/zathurarc','usr/local/bin/labwc-focuswriter-import',
                     'usr/local/libexec/labwc-session-check','usr/local/libexec/whisper-record-timed',
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


if __name__ == '__main__':
    unittest.main()
