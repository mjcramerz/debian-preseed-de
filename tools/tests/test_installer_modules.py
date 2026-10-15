"""Direct editable input, runtime module inventory and publication contracts."""

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[2] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

from pathlib import Path
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

checker = load('check_modules')
publisher = load('publication')
builder = load('build')
build_checks = load('check_build')

class RepositoryFileModes(unittest.TestCase):
    def test_builder_serializes_without_commands_or_source_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory)
            source = seed / 'scripts/common/source.sh'
            source.parent.mkdir(parents=True)
            source.write_text('# BEGIN BOOTSTRAP CORE\n:;\n# END BOOTSTRAP CORE\n')
            malformed = seed / 'scripts/not-a-valid-shell.sh'
            malformed.write_text('if then\n')
            private = seed / 'preseed.env'
            private.write_text('PRIVATE_FIXTURE=never-package-this\n')
            before = {path: path.read_bytes() for path in seed.rglob('*') if path.is_file()}
            with mock.patch.object(builder, 'SEED', seed), \
                 mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('build executed a command')):
                products = builder.build()
            self.assertEqual(set(products), publisher.SNAPSHOT_PRODUCTS)
            self.assertIn(b'scripts/not-a-valid-shell.sh', products['payload.manifest'])
            self.assertNotIn(b'preseed.env', products['payload.manifest'])
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_every_python_test_and_fixture_checks_isolation_before_runtime_imports(self):
        import ast
        paths = sorted((ROOT / 'd-i/forky/tests').rglob('*.py')) + sorted((ROOT / 'tools/tests').rglob('*.py'))
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                tree = ast.parse(path.read_text(), filename=str(path))
                calls = [index for index, node in enumerate(tree.body)
                         if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                         and isinstance(node.value.func, ast.Name)
                         and node.value.func.id == '_require_test_isolation']
                self.assertEqual(len(calls), 1, 'missing mandatory host-isolation gate')
                prefix = tree.body[:calls[0]]
                for node in prefix:
                    if isinstance(node, ast.Import):
                        self.assertEqual([alias.name for alias in node.names], ['sys'])
                    elif isinstance(node, ast.ImportFrom):
                        self.assertIn(node.module, ('__future__', 'pathlib', 'isolation'))
                    elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                        self.assertIsInstance(node.value.func, ast.Attribute)
                        self.assertIn(node.value.func.attr, ('insert', 'pop'))
                    else:
                        self.assertIsInstance(node, ast.Expr)
                        self.assertIsInstance(node.value, ast.Constant)
                        self.assertIsInstance(node.value.value, str)

    def test_all_repository_source_files_are_nonexecutable(self):
        paths = [path for path in ROOT.iterdir() if path.is_file()]
        for name in ('d-i', 'docs', 'tools'):
            paths.extend(path for path in (ROOT / name).rglob('*') if path.is_file())
        self.assertTrue(paths)
        self.assertEqual([str(path.relative_to(ROOT)) for path in paths
                          if path.stat().st_mode & 0o111], [])

    def test_builder_rejects_executable_input_and_packages_nonexecutable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'script.sh'
            source.write_text('#!/bin/sh\nexit 0\n')
            source.chmod(0o755)
            with mock.patch.object(builder, 'SEED', Path(directory)):
                with self.assertRaisesRegex(ValueError, 'source file must not be executable'):
                    builder.payload_files()
                source.chmod(0o644)
                self.assertEqual(builder.payload_files(), [source])

    def test_builder_rejects_undeclared_apparmor_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory)
            policy_dir = seed / 'hooks/target/etc/apparmor.d'
            policy_dir.mkdir(parents=True)
            (policy_dir / 'new-policy').write_text('profile new-policy {\n}\n')
            config = seed / 'hooks/target/etc/apparmor/modes.conf.tmpl'
            config.parent.mkdir(parents=True)
            config.write_text('__DESKTOP_APPARMOR_STATE__ optional firstboot -\n')
            with mock.patch.object(build_checks, 'SEED', seed):
                with self.assertRaisesRegex(ValueError, 'unmanaged repository AppArmor profile'):
                    build_checks.validate_apparmor_modes()
                config.write_text(config.read_text() +
                                  '__DESKTOP_APPARMOR_STATE__ required new-policy -\n')
                build_checks.validate_apparmor_modes()

class ModuleContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.seed = self.root / 'd-i/forky'
        shutil.copytree(ROOT / 'd-i/forky/scripts', self.seed / 'scripts')
        shutil.copytree(ROOT / 'd-i/forky/hosts/profiles', self.seed / 'hosts/profiles')

    def test_inventory_is_explicit_complete_and_read_only(self):
        before = {p: p.read_bytes() for p in self.seed.rglob('*') if p.is_file()}
        self.assertEqual(checker.check(self.seed), 49)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertFalse((ROOT / 'src').exists())
        self.assertFalse((ROOT / 'tools/generate_installer.py').exists())

    def test_module_edit_remains_authoritative_and_is_not_repaired(self):
        path = self.seed / 'scripts/common/modules/files-logging.sh'
        path.write_text(path.read_text() + '\n# local administrator edit\n')
        before = path.read_bytes()
        checker.check(self.seed)
        self.assertEqual(path.read_bytes(), before)

    def test_profile_edit_is_read_directly_and_does_not_change_other_hosts(self):
        files = sorted((self.seed / 'hosts/profiles').glob('*.env'))
        before = {p: p.read_bytes() for p in files}
        path = files[0]
        path.write_text(path.read_text().replace('SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="256"',
                                                'SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="512"'))
        edited = path.read_bytes()
        checker.check(self.seed)
        self.assertEqual(path.read_bytes(), edited)
        self.assertEqual([p for p in files if p.read_bytes() != before[p]], [path])

    def test_invalid_flags_sizes_and_duplicates_are_rejected_without_writes(self):
        path = next((self.seed / 'hosts/profiles').glob('*.env'))
        original = path.read_text()
        bad = [original.replace('TMPFS_VAR_SPOOL_RSYSLOG="true"', 'TMPFS_VAR_SPOOL_RSYSLOG="maybe"'),
               original.replace('SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="256"', 'SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="0"'),
               original + 'TMPFS_VAR_SPOOL_RSYSLOG="false"\n',
               original.replace('SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="256"', 'SIZE_TMPFS_VAR_SPOOL_RSYSLOG_MIB="$(false)"')]
        for text in bad:
            with self.subTest(text=text[-90:]):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    checker.check(self.seed)
                self.assertEqual(path.read_text(), text)

    def test_orphan_duplicate_and_missing_modules_are_rejected(self):
        orphan = self.seed / 'scripts/common/modules/orphan.sh'
        orphan.write_text('#!/bin/sh\n')
        with self.assertRaises(ValueError): checker.check(self.seed)
        orphan.unlink()
        entry = self.seed / 'scripts/common/lib.sh'
        text = entry.read_text()
        line = next(line for line in text.splitlines() if line.startswith('bootstrap_source_module '))
        entry.write_text(text + line + '\n')
        with self.assertRaises(ValueError): checker.check(self.seed)
        entry.write_text(text)
        (self.seed / 'scripts/common/modules/files-logging.sh').unlink()
        with self.assertRaises(ValueError): checker.check(self.seed)

    def test_symlink_hardlink_and_path_traversal_are_rejected(self):
        path = self.seed / 'scripts/common/modules/files-logging.sh'
        path.unlink()
        path.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError): checker.check(self.seed)
        path.unlink()
        os.link(self.seed / 'scripts/common/credentials.sh', path)
        with self.assertRaises(ValueError): checker.check(self.seed)
        for name in ('../outside.sh', '/etc/passwd', 'scripts/common/../x.sh'):
            with self.assertRaises(ValueError): checker.module_file(self.seed, name)

    def test_invalid_module_syntax_is_rejected(self):
        (self.seed / 'scripts/common/modules/files-logging.sh').write_text('if then\n')
        with self.assertRaises(ValueError): checker.check(self.seed)

    def test_build_and_check_preserve_every_edited_environment_file(self):
        # A full repository copy: edits exist in the actual served files only.
        for name in ('tools', 'd-i'):
            shutil.copytree(ROOT / name, self.root / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('tests', '__pycache__'))
        files = list(self.seed.rglob('*.env'))
        for path in files:
            path.write_bytes(path.read_bytes() + b'\n# administrator edit must survive publication\n')
        before = {p: (p.read_bytes(), p.stat().st_mode) for p in files}
        generated = {self.seed / name for name in builder.GENERATED}
        source_before = {path.relative_to(self.root): (path.read_bytes(), path.stat().st_mode)
                         for path in self.root.rglob('*') if path.is_file() and path not in generated}
        for args in ([], ['--check']):
            result = subprocess.run([sys.executable, '-B', str(self.root / 'tools/build.py'), *args],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mode) for p in files})
            self.assertEqual(source_before,
                             {path.relative_to(self.root): (path.read_bytes(), path.stat().st_mode)
                              for path in self.root.rglob('*') if path.is_file() and path not in generated})

class PhaseDispatchContracts(unittest.TestCase):
    """Dispatch only fixture runners; never enter an installer phase."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='phase-dispatch-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / 'arguments'
        self.runner = self.root / 'fixture runner'
        self.runner.write_text('#!/bin/sh\nprintf "%s\\n" "$#" "$@" >"$PHASE_OUTPUT"\nexit "${PHASE_RUNNER_STATUS:-0}"\n')
        self.runner.chmod(0o700)
        (self.root / 'sourcea').mkdir()
        self.state = self.root / 'runtime/bootstrap'
        self.state.mkdir(parents=True)
        self.trace = self.root / 'operations'
        self.shells = [['/bin/dash']]
        if busybox := shutil.which('busybox'):
            self.shells.append([busybox, 'sh'])

    def dispatch(self, shell, phase, source, *, explicit_runner=False, **values):
        self.output.unlink(missing_ok=True)
        bootstrap = ROOT / 'd-i/forky/scripts/common/bootstrap.sh'
        code = '. ' + shlex.quote(str(bootstrap)) + '''
bootstrap_require_seed_base() { printf '%s\\n' "$1"; return "${PHASE_RESOLVE_STATUS:-0}"; }
bootstrap_ensure_repo_env() { return "${PHASE_ENV_STATUS:-0}"; }
bootstrap_repo_join_var() { printf '%s/%s\\n' "$1" "$2"; return "${PHASE_PATH_STATUS:-0}"; }
bootstrap_phase_runner_path() { printf '%s\\n' "$PHASE_RUNNER"; return "${PHASE_RUNNER_PATH_STATUS:-0}"; }
bootstrap_persist_seed_source() { return "${PHASE_PERSIST_STATUS:-0}"; }
bootstrap_fetch_seed_file() { return "${PHASE_FETCH_STATUS:-0}"; }
if bootstrap_run_preseed_phase "$@"; then exit 0; else exit "$?"; fi
'''
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'LC_ALL': 'C',
               'PHASE_OUTPUT': str(self.output), 'PHASE_RUNNER': str(self.runner),
               'INSTALLER_BOOTSTRAP_LIB': str(bootstrap), **values}
        return subprocess.run([*shell, '-eu', '-c', code, 'phase-fixture', phase, source,
                               *([str(self.runner)] if explicit_runner else [])],
                              cwd=self.root, env=env, text=True, capture_output=True, timeout=10)

    def persist(self, shell, source, **values):
        self.trace.unlink(missing_ok=True)
        bootstrap = ROOT / 'd-i/forky/scripts/common/bootstrap.sh'
        code = '. ' + shlex.quote(str(bootstrap)) + '''
install() { printf 'install\\n' >>"$PERSIST_TRACE"; return "${PERSIST_INSTALL_STATUS:-0}"; }
rm() { printf 'cleanup\\n' >>"$PERSIST_TRACE"; return "${PERSIST_CLEANUP_STATUS:-0}"; }
if bootstrap_persist_seed_source "$1"; then exit 0; else exit "$?"; fi
'''
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'LC_ALL': 'C',
               'INSTALLER_RUNTIME_DIR': str(self.state.parent),
               'PERSIST_TRACE': str(self.trace), **values}
        return subprocess.run([*shell, '-eu', '-c', code, 'persistence-fixture', source],
                              cwd=self.root, env=env, text=True, capture_output=True, timeout=10)

    def test_all_phase_arguments_preserve_spaces_and_globs(self):
        for shell in self.shells:
            for phase in ('prepare-context', 'apply', 'early', 'partman', 'late'):
                for source in ('/fixture/source with spaces', str(self.root / 'source[ab]*'),
                               'https://fixture.invalid/repo[ab]*'):
                    with self.subTest(shell=shell, phase=phase, source=source):
                        result = self.dispatch(shell, phase, source)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        arguments = [phase, source] if phase in ('prepare-context', 'apply') else [source]
                        self.assertEqual(self.output.read_text().splitlines(), [str(len(arguments)), *arguments])

    def test_preparation_failure_never_executes_a_stale_runner(self):
        for shell in self.shells:
            for name in ('RESOLVE', 'ENV', 'PATH', 'RUNNER_PATH', 'PERSIST', 'FETCH'):
                with self.subTest(shell=shell, failure=name):
                    result = self.dispatch(shell, 'late', '/fixture/source', **{'PHASE_' + name + '_STATUS': '37'})
                    self.assertEqual(result.returncode, 37, result.stderr)
                    self.assertFalse(self.output.exists())

    def test_runner_status_is_preserved(self):
        for shell in self.shells:
            with self.subTest(shell=shell):
                result = self.dispatch(shell, 'early', '/fixture/source', PHASE_RUNNER_STATUS='23')
                self.assertEqual(result.returncode, 23, result.stderr)

    def test_explicit_runner_skips_default_runner_path_resolution(self):
        for shell in self.shells:
            with self.subTest(shell=shell):
                result = self.dispatch(shell, 'early', '/fixture/source', explicit_runner=True,
                                       PHASE_RUNNER_PATH_STATUS='37')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.output.read_text().splitlines(), ['1', '/fixture/source'])

    def test_real_persistence_setup_failure_never_writes_or_cleans_state(self):
        for shell in self.shells:
            for source in ('/fixture/source', 'https://fixture.invalid/repo'):
                with self.subTest(shell=shell, source=source):
                    result = self.persist(shell, source, PERSIST_INSTALL_STATUS='37')
                    self.assertEqual(result.returncode, 37, result.stderr)
                    self.assertEqual(list(self.state.iterdir()), [])
                    self.assertEqual(self.trace.read_text().splitlines(), ['install'])

    def test_real_persistence_write_failure_keeps_the_other_source(self):
        for shell in self.shells:
            for source, kind, other in (('/fixture/source', 'file', 'url'),
                                        ('https://fixture.invalid/repo', 'url', 'file')):
                with self.subTest(shell=shell, source=source):
                    destination = self.state / ('seed.' + kind)
                    previous = self.state / ('seed.' + other)
                    destination.mkdir()  # Redirection fails even as image root.
                    previous.write_text('retained source\n')
                    try:
                        result = self.persist(shell, source)
                        self.assertNotEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(previous.read_text(), 'retained source\n')
                        self.assertEqual(self.trace.read_text().splitlines(), ['install'])
                    finally:
                        destination.rmdir()
                        previous.unlink()

    def test_real_persistence_cleanup_failure_keeps_its_status(self):
        for shell in self.shells:
            for source, kind in (('/fixture/source', 'file'), ('https://fixture.invalid/repo', 'url')):
                with self.subTest(shell=shell, source=source):
                    result = self.persist(shell, source, PERSIST_CLEANUP_STATUS='41')
                    self.assertEqual(result.returncode, 41, result.stderr)
                    self.assertEqual((self.state / ('seed.' + kind)).read_text(), source + '\n')
                    self.assertEqual(self.trace.read_text().splitlines(), ['install', 'cleanup'])

class PublicationContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.products = {name: b'new-' + name.encode() for name in publisher.SNAPSHOT_PRODUCTS}
        for name in self.products:
            (self.root / name).write_bytes(b'old-' + name.encode())
            (self.root / name).chmod(0o644)

    def test_snapshot_publication_is_idempotent(self):
        self.assertEqual(publisher.publish_snapshot(self.root, self.products), 3)
        self.assertEqual(publisher.publish_snapshot(self.root, self.products), 0)

    def test_failure_restores_previous_generation(self):
        before = {p: p.read_bytes() for p in self.root.iterdir()}
        real = publisher.atomic_write
        calls = 0
        def fail_once(*args):
            nonlocal calls
            calls += 1
            if calls == 2: raise OSError('injected publication failure')
            return real(*args)
        with mock.patch.object(publisher, 'atomic_write', side_effect=fail_once):
            with self.assertRaises(OSError): publisher.publish_snapshot(self.root, self.products)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.iterdir()})

    def test_rollback_failure_preserves_original_error_and_restores_other_products(self):
        self.products = {name: b'new-' + name.encode() for name in
                         ('payload.tar.gz', 'payload.manifest', 'preseed.cfg')}
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        real = publisher.atomic_write
        failure = OSError('injected publication failure')
        calls = []

        def fail_publication_and_one_restore(path, data, mode):
            calls.append(path.name)
            if len(calls) == 3:
                raise failure
            if data == before['payload.manifest']:
                raise OSError('injected rollback failure')
            return real(path, data, mode)

        with mock.patch.object(publisher, 'atomic_write', side_effect=fail_publication_and_one_restore):
            with self.assertRaises(OSError) as caught:
                publisher.publish_snapshot(self.root, self.products)
        self.assertIs(caught.exception, failure)
        self.assertEqual(calls, ['payload.tar.gz', 'payload.manifest', 'preseed.cfg',
                                 'preseed.cfg', 'payload.manifest', 'payload.tar.gz'])
        self.assertEqual((self.root / 'payload.tar.gz').read_bytes(), before['payload.tar.gz'])
        self.assertEqual((self.root / 'preseed.cfg').read_bytes(), before['preseed.cfg'])
        self.assertTrue(any('payload.manifest' in note and 'injected rollback failure' in note
                            for note in failure.__notes__))

    def test_postpublication_failure_removes_new_product_during_rollback(self):
        self.products = {name: b'new-' + name.encode() for name in
                         ('payload.tar.gz', 'payload.manifest', 'preseed.cfg')}
        new_path = self.root / 'payload.manifest'
        new_path.unlink()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        real = publisher.atomic_write
        calls = 0

        def fail_after_write(*args):
            nonlocal calls
            calls += 1
            real(*args)
            if calls == 2:
                raise OSError('injected postpublication failure')

        with mock.patch.object(publisher, 'atomic_write', side_effect=fail_after_write):
            with self.assertRaisesRegex(OSError, 'injected postpublication failure'):
                publisher.publish_snapshot(self.root, self.products)
        self.assertFalse(new_path.exists())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_environment_output_is_unconditionally_rejected(self):
        env = self.root / 'profile.env'
        env.write_bytes(b'KEEP="true"\n')
        with self.assertRaises(ValueError): publisher.atomic_write(env, b'bad', 0o644)
        with self.assertRaises(ValueError): publisher.publish_snapshot(self.root, {'profile.env': b'bad'})
        self.assertEqual(env.read_bytes(), b'KEEP="true"\n')

    def test_linked_snapshot_output_is_rejected_before_any_write(self):
        path = self.root / 'payload.manifest'
        path.unlink()
        path.symlink_to('/etc/passwd')
        old = (self.root / 'preseed.cfg').read_bytes()
        with self.assertRaises(ValueError): publisher.publish_snapshot(self.root, self.products)
        self.assertEqual((self.root / 'preseed.cfg').read_bytes(), old)

if __name__ == '__main__': unittest.main()
