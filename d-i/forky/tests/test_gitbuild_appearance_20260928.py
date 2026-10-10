#!/usr/bin/python3
"""Offline regression tests for the managed build and appearance boundaries."""
from __future__ import annotations
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

SEED = Path(__file__).resolve().parents[1]
TARGET = SEED / 'hooks/target'
LIB = TARGET / 'usr/local/lib/python3.14/dist-packages'
sys.path.insert(0, str(LIB))
from managed_workflows.fs import Tree, parts
from managed_workflows import process
from gitbuild import core, cli as build_cli, worker, publish, import_local
from labwc_appearance import catalog, native, editors, transaction, engine, defaults, greeter
from labwc_appearance import cli as appearance_cli
from payload_fixture import read_text, logging_text
from theme_fixture import render_theme_defaults

JOB = '20260928T120000-0123456789ab'
TOKEN = 'a' * 32


def native_defaults():
    files = {}
    for paths in native.FILES.values():
        for relative in paths:
            if relative == native.OPTIONAL:
                files['.config/' + relative] = None
                continue
            text = render_theme_defaults(read_text(TARGET / 'etc/skel-desktop/.config' / relative))
            text = re.sub(r'__INSTALLER_[A-Z0-9_]+__', '1', text)
            files['.config/' + relative] = text
    greeter_files = {}
    for relative in native.GREETER_FILES:
        text = render_theme_defaults(read_text(TARGET / 'etc/greetd' / relative))
        greeter_files[relative] = re.sub(r'__INSTALLER_[A-Z0-9_]+__', '1', text)
    return defaults.validate({'schema': 1, 'mode': 'light', 'files': files,
                             'greeter': greeter_files,
                             'settings': {'color-scheme': "'prefer-light'", 'gtk-theme': "'Adwaita'"}})


def checksum_field(files):
    return 'Checksums-Sha256:\n' + ''.join(' ' + hashlib.sha256(data).hexdigest() + ' ' +
                                         str(len(data)) + ' ' + name + '\n'
                                         for name, data in files.items())


def fixture_bundle(parent):
    job = parent / JOB
    job.mkdir(mode=0o700)
    (job / 'artifacts').mkdir(mode=0o700)
    files = {'hello_1.0.orig.tar.xz': b'upstream', 'hello_1.0-1.debian.tar.xz': b'packaging',
             'hello_1.0-1_amd64.deb': b'!<arch>\nfixture'}
    files['hello_1.0-1.dsc'] = ('Source: hello\n' + checksum_field({k: v for k, v in files.items() if k.endswith('.xz')})).encode()
    files['hello_1.0-1_amd64.buildinfo'] = checksum_field({k: v for k, v in files.items() if k.endswith('.deb')}).encode()
    files['hello_1.0-1_source.changes'] = checksum_field({k: v for k, v in files.items() if k.endswith(('.dsc', '.xz'))}).encode()
    files['hello_1.0-1_amd64.changes'] = checksum_field({k: v for k, v in files.items() if k.endswith(('.deb', '.buildinfo'))}).encode()
    with Tree(job) as tree:
        tree.put_json('job.json', {'schema': 1, 'kind': 'binary', 'status': 'pending'})
        for name, data in files.items():
            tree.write('artifacts/' + name, data)
    core.record_artifacts(job)
    return job


class Temporary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)


class FilesystemTests(Temporary):
    def test_atomic_read_write_copy_and_delete(self):
        with Tree(self.root) as tree:
            tree.write('a/one', b'content')
            tree.copy('b/two', tree, 'a/one')
            self.assertEqual(tree.read('b/two'), b'content')
            tree.write('b/two', None)
            self.assertIsNone(tree.read('b/two', missing=True))
            self.assertFalse(list(self.root.rglob('.managed-*')))

    def test_paths_are_strictly_relative(self):
        for value in ('', '.', '/etc/passwd', '../file', './file', 'a//file', 'a/../file', 'a\nfile'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parts(value)

    def test_symlink_parent_and_leaf_refused(self):
        outside = self.root / 'outside'; outside.mkdir()
        (outside / 'secret').write_bytes(b'secret')
        (self.root / 'link').symlink_to(outside, target_is_directory=True)
        (self.root / 'file').symlink_to(outside / 'secret')
        with Tree(self.root) as tree:
            for name in ('link/secret', 'file'):
                with self.subTest(name=name), self.assertRaises((ValueError, OSError)):
                    tree.read(name)
                with self.assertRaises((ValueError, OSError)):
                    tree.write(name, b'bad')
        self.assertEqual((outside / 'secret').read_bytes(), b'secret')

    def test_hardlinks_fifo_and_shared_files_refused(self):
        (self.root / 'plain').write_bytes(b'bytes')
        os.link(self.root / 'plain', self.root / 'hardlink')
        os.mkfifo(self.root / 'fifo')
        (self.root / 'shared').write_bytes(b'bytes'); (self.root / 'shared').chmod(0o666)
        with Tree(self.root) as tree:
            for name in ('plain', 'hardlink', 'fifo', 'shared'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    tree.read(name)

    def test_nonblocking_lock(self):
        with Tree(self.root) as tree, tree.lock('work.lock'):
            with self.assertRaises(RuntimeError), tree.lock('work.lock'):
                pass

    def test_private_directory_and_size_limit(self):
        self.root.chmod(0o755)
        with self.assertRaises(ValueError): Tree(self.root, private=True)
        with Tree(self.root) as tree:
            tree.write('data', b'12345')
            with self.assertRaises(ValueError): tree.copy('copy', tree, 'data', limit=4)
            self.assertFalse((self.root / 'copy').exists())

    def test_copy_change_does_not_replace_destination(self):
        with Tree(self.root) as tree:
            tree.write('in', b'initial'); tree.write('out', b'original')
            original = os.fsync
            def changing(fd):
                original(fd)
                with open(self.root / 'in', 'ab') as f: f.write(b'changed')
            with mock.patch('managed_workflows.fs.os.fsync', side_effect=changing), self.assertRaises(ValueError):
                tree.copy('out', tree, 'in')
            self.assertEqual(tree.read('out'), b'original')

    def test_copy_bounds_growth_and_rejects_truncation(self):
        with Tree(self.root) as tree:
            tree.write('in', b'initial'); tree.write('out', b'original')
            metadata = (self.root / 'in').stat()
            for data in (b'initial' + b'excess' * 1000, b'short'):
                stream = io.BytesIO(data)
                with self.subTest(size=len(data)), mock.patch.object(
                        tree, 'open_read', return_value=contextlib.nullcontext((stream, metadata))):
                    with self.assertRaises(ValueError):
                        tree.copy('out', tree, 'in')
                    self.assertLessEqual(stream.tell(), metadata.st_size + 1)
                self.assertEqual(tree.read('out'), b'original')
                self.assertFalse(list(self.root.rglob('.managed-*')))


class SourceTests(Temporary):
    def setUp(self):
        super().setUp()
        self.repo = self.root / 'repo'; self.repo.mkdir()
        subprocess.run(['/usr/bin/git', 'init', '-q', str(self.repo)], check=True)
        (self.repo / '.gitignore').write_text('.env\nignored/\ntarget/\n')
        (self.repo / '.env').write_text('SECRET=private\n')
        (self.repo / 'tracked').write_text('old')
        subprocess.run(['/usr/bin/git', '-C', str(self.repo), 'add', 'tracked', '.gitignore'], check=True)
        (self.repo / 'tracked').write_text('uncommitted edit')
        (self.repo / 'new').write_text('untracked but included')
        self.ctx = object.__new__(core.Context); self.ctx.repo = self.repo

    def test_snapshot_tracks_edits_and_nonignored_files(self):
        destination = self.root / 'snapshot'
        core.snapshot(self.repo, destination, entries=self.ctx.source_files())
        self.assertEqual((destination / 'tracked').read_text(), 'uncommitted edit')
        self.assertTrue((destination / 'new').exists())
        self.assertFalse((destination / '.env').exists())
        self.assertFalse((destination / '.git').exists())

    def test_deleted_tracked_files_are_not_resurrected(self):
        (self.repo / 'tracked').unlink()
        destination = self.root / 'snapshot'
        core.snapshot(self.repo, destination, entries=self.ctx.source_files())
        self.assertFalse((destination / 'tracked').exists())

    def test_internal_symlink_preserved(self):
        (self.repo / 'link').symlink_to('tracked')
        destination = self.root / 'snapshot'
        core.snapshot(self.repo, destination, entries=self.ctx.source_files())
        self.assertEqual(os.readlink(destination / 'link'), 'tracked')

    def test_symlink_to_ignored_file_refused(self):
        (self.repo / 'link').symlink_to('.env')
        with self.assertRaises(ValueError):
            core.snapshot(self.repo, self.root / 'snapshot', entries=self.ctx.source_files())

    def test_external_symlink_refused(self):
        (self.repo / 'link').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            core.snapshot(self.repo, self.root / 'snapshot', entries=self.ctx.source_files())

    def test_gitlink_requires_explicit_flattening(self):
        with mock.patch.object(core, 'checked', return_value='160000 ' + 'a'*40 + ' 0\tsubmodule\0'):
            with self.assertRaisesRegex(ValueError, 'submodules'): self.ctx.source_files()

    def test_workspace_discovery_skips_symlinks_and_build_outputs(self):
        workspace = self.root / 'Workspace'; workspace.mkdir()
        project = workspace / 'group/project'; (project / '.git').mkdir(parents=True)
        skipped = workspace / 'target/hidden'; (skipped / '.git').mkdir(parents=True)
        (workspace / 'linked').symlink_to(self.repo, target_is_directory=True)
        self.assertEqual(core.workspace_repositories(workspace), [project])

    def test_orig_is_reproducible_and_excludes_packaging(self):
        source = self.root / 'hello-1.0'; source.mkdir()
        (source / 'debian').mkdir(); (source / 'debian/control').write_text('excluded')
        (source / 'main').write_text('included')
        a, b = self.root / 'one.tar.xz', self.root / 'two.tar.xz'
        worker.orig_archive(source, a, 123456789)
        worker.orig_archive(source, b, 123456789)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        import tarfile
        with tarfile.open(a) as archive:
            self.assertEqual(archive.getnames(), ['hello-1.0', 'hello-1.0/main'])
        with self.assertRaises(ValueError): worker.orig_archive(source, a, 123456789)


class BuildTests(Temporary):
    def setUp(self):
        super().setUp()
        self.job = self.root / JOB; (self.job / 'work/hello-1.0').mkdir(parents=True)
        self.cache = self.root / 'cache'; self.cache.mkdir()

    def commands(self, kind, **extra):
        return worker.build_commands({'kind': kind, 'source': 'hello-1.0', 'jobs': 2, 'epoch': 123, **extra},
                                     self.job, self.cache, 'amd64')

    def test_debmake_native_and_quilt(self):
        for fmt, flags in (('native', ['-n']), ('quilt', ['-r', '1'])):
            command = self.commands('init', package='hello', version='1.0', name='A Developer', email='a@example.org', format=fmt)[0]
            self.assertIn('/usr/bin/debmake', command)
            self.assertEqual(command[-len(flags):], flags)
            self.assertNotIn('--enable-network', command)

    def test_local_sandbox_exposes_work_not_control_or_credentials(self):
        command = self.commands('local')[0]
        self.assertIn('--unshare-all', command)
        self.assertIn('--cap-drop', command)
        index = command.index('--bind')
        self.assertEqual(command[index+1:index+3], [str(self.job / 'work'), '/build'])
        self.assertNotIn(str(self.job / 'home'), command)
        self.assertIn('HOME=/home/build', command)
        self.assertIn('-j2', command)

    def test_source_generation_does_not_run_host_rules_clean(self):
        for kind in ('source', 'binary'):
            command = self.commands(kind)[0]
            for flag in ('-S', '-sa', '-us', '-uc', '-nc', '-d'): self.assertIn(flag, command)

    def test_bootstrap_streams_tar_without_access_to_private_output_path(self):
        command = self.commands('bootstrap')[0]
        self.assertEqual(command[-3:], ['forky', '-', 'https://deb.debian.org/debian'])
        self.assertIn('--mode=unshare', command)
        self.assertIn('--include=ca-certificates', command)

    def test_unknown_operation_and_unsafe_source_refused(self):
        with mock.patch.object(worker, 'validate_job'), mock.patch.object(worker, 'verified_artifacts', return_value=[]):
            with self.assertRaises(ValueError): self.commands('unknown')
        with self.assertRaises(ValueError): self.commands('local', source='../escape')

    def test_all_inspection_menu_actions_make_expected_commands(self):
        parent = self.root / 'bundles'; parent.mkdir()
        job = fixture_bundle(parent)
        with mock.patch.object(worker, 'validate_job'):
            for kind, exe in (('lintian', '/usr/bin/lintian'), ('inspect', '/usr/bin/dpkg-deb'), ('autopkgtest', '/usr/bin/autopkgtest')):
                command = self.commands(kind, bundle=str(job))[0]
                self.assertEqual(command[0], exe)
                if kind == 'autopkgtest':
                    self.assertIn('--tarball=' + str(self.cache / 'forky-amd64.tar'), command)
                    self.assertIn('unshare', command)
        self.assertIn('/usr/bin/dpkg-checkbuilddeps', self.commands('deps')[0])

    def test_requires_enforcing_profile(self):
        for value in ('unconfined', 'gitbuild-worker (complain)', 'other (enforce)'):
            with mock.patch.object(Path, 'read_text', return_value=value), self.assertRaises(ValueError):
                worker.require_confinement()
        with mock.patch.object(Path, 'read_text', return_value='gitbuild-worker (enforce)\n'):
            worker.require_confinement()

    def test_environment_drops_injection_and_session_authority(self):
        with mock.patch.dict(os.environ, {'PYTHONPATH': '/evil', 'LD_PRELOAD': '/evil', 'GIT_CONFIG_COUNT': '1',
                                         'DISPLAY': ':0', 'DBUS_SESSION_BUS_ADDRESS': 'secret'}):
            env = process.environment()
        self.assertFalse({'PYTHONPATH', 'LD_PRELOAD', 'GIT_CONFIG_COUNT', 'DISPLAY', 'DBUS_SESSION_BUS_ADDRESS'} & env.keys())

    def test_checked_preserves_explicit_empty_environment(self):
        with mock.patch.object(process.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            process.checked(['/usr/bin/true'], env={})
        self.assertEqual(run.call_args.kwargs['env'], {})

    def test_transient_service_has_cgroup_limits_and_unique_identity(self):
        child = mock.Mock(); child.wait.return_value = 0; child.poll.return_value = 0
        with mock.patch.object(process.subprocess, 'Popen', return_value=child) as popen:
            process.supervised([core.WORKER, str(self.job)], cwd=self.root)
        command = popen.call_args.args[0]
        self.assertIn('--property=KillMode=control-group', command)
        self.assertIn('--collect', command)
        self.assertIn('--expand-environment=no', command)
        self.assertIn('--property=RuntimeMaxSec=28800', command)
        for value in ('TasksMax=4096', 'MemoryMax=75%', 'OOMPolicy=stop', 'MemoryOOMGroup=yes'):
            self.assertIn('--property=' + value, command)
        self.assertRegex(next(x for x in command if x.startswith('--unit=')), r'^--unit=gitbuild-[a-f0-9]{32}\.service$')

    def test_interrupt_stops_exact_service_cgroup(self):
        child = mock.Mock(); child.wait.side_effect = KeyboardInterrupt; child.poll.return_value = 0
        with mock.patch.object(process.subprocess, 'Popen', return_value=child) as popen, \
             mock.patch.object(process.subprocess, 'run') as run, self.assertRaises(KeyboardInterrupt):
            process.supervised([core.WORKER, str(self.job)], cwd=self.root)
        unit = next(x.split('=', 1)[1] for x in popen.call_args.args[0] if x.startswith('--unit='))
        self.assertEqual(run.call_args.args[0], ['/usr/bin/systemctl', '--user', 'stop', unit])

    def test_menu_uses_arrows_and_has_no_shell_interpolation(self):
        result = subprocess.CompletedProcess([], 0, 'Build and test\n')
        with mock.patch.object(build_cli.subprocess, 'run', return_value=result) as run:
            self.assertEqual(build_cli.choose(list(build_cli.MENUS), 'gitbuild'), 'Build and test')
        self.assertEqual(run.call_args.args[0][0], '/usr/bin/fzf')
        self.assertNotIn('shell', run.call_args.kwargs)
        actions = {value for group in build_cli.MENUS.values() for value in group.values()}
        self.assertEqual(actions, worker.KINDS | {'orig', 'review', 'sign', 'aptly', 'obs', 'local-repo', 'artifacts', 'log', 'doctor'})


class AppearanceCoordinatorTests(Temporary):
    def setUp(self):
        super().setUp()
        self.defaults = native_defaults()
        with Tree(self.root) as home:
            for name, text in self.defaults['files'].items():
                if text is not None: home.write(name, text.encode())
        # Preserve real descriptor ownership checks; only the public root gate,
        # account lookup and external session services are substituted.
        self.uid = os.getuid()
        original_tree = Tree
        self.enter = contextlib.ExitStack(); self.addCleanup(self.enter.close)
        def owned_tree(path, *args, **kwargs):
            kwargs.setdefault('uid', self.uid)
            return original_tree(path, *args, **kwargs)
        self.enter.enter_context(mock.patch.object(engine.os, 'getuid', return_value=1000))
        self.enter.enter_context(mock.patch.object(engine.os, 'geteuid', return_value=1000))
        self.enter.enter_context(mock.patch.object(engine.pwd, 'getpwuid', return_value=types.SimpleNamespace(pw_dir=str(self.root))))
        self.enter.enter_context(mock.patch.object(engine, 'Tree', side_effect=owned_tree))
        self.enter.enter_context(mock.patch.object(engine, 'load', return_value=self.defaults))
        self.values = dict(self.defaults['settings'])
        def settings(values=None):
            if values is not None: self.values.update(values)
            return dict(self.values)
        self.enter.enter_context(mock.patch.object(engine, 'settings', side_effect=settings))
        self.privileged = self.enter.enter_context(mock.patch.object(engine, 'privileged'))
        self.enter.enter_context(mock.patch.object(engine.service, 'active', return_value=False))
        self.enter.enter_context(mock.patch.object(engine.service, 'refresh', return_value=[]))

    def test_global_apply_and_reset_roundtrip_real_native_files(self):
        engine.apply_choice(['mode', 'dark'])
        self.assertEqual(self.values['color-scheme'], "'prefer-dark'")
        self.assertIn('gtk-theme-name=Adwaita-dark', (self.root / '.config/gtk-3.0/settings.ini').read_text())
        self.assertTrue((self.root / '.config/qt6ct/colors/labwc-appearance.conf').is_file())
        engine.apply_choice(['reset', 'all'])
        self.assertEqual(self.values, self.defaults['settings'])
        self.assertFalse((self.root / '.config/qt6ct/colors/labwc-appearance.conf').exists())
        self.assertFalse((self.root / engine.JOURNAL).exists())
        state = json.loads((self.root / engine.CONFIG).read_text())
        self.assertEqual(state, engine.initial(self.defaults))

    def test_declined_greeter_authentication_rolls_back_local_files(self):
        before = (self.root / '.config/gtk-3.0/settings.ini').read_bytes()
        def privileged(action, *args):
            if action == 'apply': raise RuntimeError('authentication cancelled')
        self.privileged.side_effect = privileged
        with self.assertRaises(RuntimeError): engine.apply_choice(['mode', 'dark'])
        self.assertEqual((self.root / '.config/gtk-3.0/settings.ini').read_bytes(), before)
        self.assertEqual(self.values, self.defaults['settings'])
        self.assertFalse((self.root / engine.JOURNAL).exists())

    def test_dock_is_stopped_before_color_write_and_layout_save_is_preserved(self):
        path = self.root / '.config/crystal-dock/labwc/appearance.conf'
        before = path.read_text()
        def stop():
            self.assertEqual(path.read_text(), before)
            path.write_text(before + '\n[user-layout]\nsize=93\n')
        def start(): self.assertIn('size=93', path.read_text())
        with mock.patch.object(engine.service, 'active', return_value=True), \
             mock.patch.object(engine.service, 'dock_stop', side_effect=stop) as stopped, \
             mock.patch.object(engine.service, 'dock_start', side_effect=start) as started:
            engine.apply_choice(['apply', 'dock', 'ocean-glass'])
        stopped.assert_called_once(); started.assert_called_once()
        self.assertIn('size=93', path.read_text())
        self.assertNotEqual(path.read_text(), before)

    def test_pre_write_crash_preserves_qsettings_shutdown_save(self):
        path = '.config/crystal-dock/labwc/appearance.conf'
        with Tree(self.root, uid=self.uid) as home:
            old = home.read(path)
            journal = transaction.plan(home, {path: b'new appearance'}, TOKEN)
            journal.update(greeter=True, dockRunning=True, filesStarted=False,
                           oldSettings=None, newSettings=None)
            home.put_json(engine.JOURNAL, journal)
            home.write(path, old + b'\n[layout]\nsize=75\n')
            with mock.patch.object(engine.service, 'dock_start') as started:
                engine.recover(home)
            started.assert_called_once()
            self.assertIn(b'size=75', home.read(path))
            self.privileged.assert_not_called()
            self.assertIsNone(home.json(engine.JOURNAL))

    def test_component_selection_does_not_modify_other_native_configs(self):
        other = self.root / '.config/foot/foot.ini'; before = other.read_bytes()
        engine.apply_choice(['apply', 'fuzzel', 'mocha-rose'])
        self.assertEqual(other.read_bytes(), before)
        self.privileged.assert_not_called()


class BundleTests(Temporary):
    def setUp(self):
        super().setUp(); self.job = fixture_bundle(self.root)

    def test_all_descriptors_and_copy_are_verified(self):
        files = core.verified_artifacts(self.job)
        publish.validate_descriptors(files)
        stage = self.root / 'stage'; stage.mkdir(mode=0o700)
        copied = publish.copy_bundle(self.job, stage)
        self.assertEqual({p.name for p in copied}, {p.name for p in files})

    def test_modified_artifact_is_refused(self):
        (self.job / 'artifacts/hello_1.0-1_amd64.deb').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'): core.verified_artifacts(self.job)

    def test_descriptor_traversal_and_disagreeing_legacy_inventory_refused(self):
        path = self.job / 'artifacts/hello_1.0-1.dsc'
        original = path.read_text()
        path.write_text('Checksums-Sha256:\n ' + 'a'*64 + ' 10 ../secret\n')
        with self.assertRaises(ValueError): core.descriptor_files(path)
        path.write_text(original + 'Files:\n ' + 'a'*32 + ' 1 other_1.deb\n')
        with self.assertRaises(ValueError): core.descriptor_files(path)

    def test_sign_uses_full_fingerprint_no_user_config_and_verifies_signer(self):
        fingerprint = 'A' * 40
        def checked(argv, **kwargs):
            if argv[0] == '/usr/bin/gpg': return '[GNUPG:] VALIDSIG ' + fingerprint + ' fixture ' + fingerprint + '\n'
            return ''
        with mock.patch.object(publish, 'checked', side_effect=checked) as run:
            result = publish.signed_job(self.job, fingerprint)
        invocation = next(call.args[0] for call in run.call_args_list if call.args[0][0].endswith('/debsign'))
        self.assertEqual(invocation[1:4], ['--no-conf', '--no-re-sign', '-k' + fingerprint])
        self.assertEqual(len([p for p in invocation if p.endswith('.changes')]), 2)
        self.assertTrue(core.verified_artifacts(result))
        with self.assertRaises(ValueError): publish.signed_job(self.job, '12345678')

    def test_sign_wrong_signer_marks_job_failed(self):
        with mock.patch.object(publish, 'checked', return_value='[GNUPG:] VALIDSIG ' + 'B'*40 + '\n'):
            with self.assertRaisesRegex(ValueError, 'selected primary key'): publish.signed_job(self.job, 'A'*40)
        states = [json.loads(p.read_text()) for p in self.root.glob('*/job.json') if p.parent != self.job]
        self.assertEqual([s['status'] for s in states], ['failed'])

    def test_root_import_requires_authenticated_nonroot_caller(self):
        for value in ('', '0', '-1', 'not-a-uid'):
            with mock.patch.dict(os.environ, {'PKEXEC_UID': value}), self.assertRaises(ValueError):
                import_local.caller_source('/etc/passwd')


class PaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.defaults = native_defaults()

    def test_distinct_dark_light_palettes_and_readable_selection(self):
        self.assertEqual(len(catalog.LABELS), 32)
        for mode in ('dark', 'light'):
            seen = set()
            for identity in catalog.LABELS:
                p = catalog.palette(identity, mode)
                self.assertGreaterEqual(catalog.contrast(p.background, p.foreground), 7)
                self.assertGreaterEqual(catalog.contrast(p.accent, p.selection_text), 4.5)
                self.assertEqual(len(p.ansi), 16)
                seen.add((p.background, p.foreground, p.accent))
            self.assertEqual(len(seen), 32)

    def test_every_profile_renders_all_native_files_in_both_modes(self):
        for identity in catalog.LABELS:
            for mode in ('dark', 'light'):
                for path, baseline in self.defaults['files'].items():
                    with self.subTest(identity=identity, mode=mode, path=path):
                        rendered = native.render(path, baseline or '', baseline, identity, mode, Path('/home/test'))
                        self.assertIsInstance(rendered, str)
                        self.assertNotIn('__THEME_', rendered)
                        if path.endswith('.css'): editors._css_rules(rendered)
                        elif path.endswith(('.ini', '.conf')) and '/kitty/' not in path: editors.ini_values(rendered)
                for baseline in self.defaults['greeter'].values():
                    editors._css_rules(editors.css(baseline, baseline, catalog.palette(identity, mode)))

    def test_reset_restores_installed_color_inventory(self):
        def inventory(text):
            result = []
            for rule in editors._css_rules(text):
                if rule.type != 'qualified-rule': continue
                for d in editors._declarations(rule):
                    if d.type == 'declaration':
                        result.append((editors._selector(rule), d.lower_name,
                                       tuple(str(c) for _, c in editors._color_tokens(d.value))))
            return result
        for path, baseline in self.defaults['files'].items():
            modified = native.render(path, baseline or '', baseline, 'mocha-rose', 'dark', Path('/home/test'))
            reset = native.render(path, modified or '', baseline, None, 'light', Path('/home/test'))
            with self.subTest(path=path):
                if baseline is None: self.assertIsNone(reset)
                elif path.endswith('.css'): self.assertEqual(inventory(reset), inventory(baseline))
                elif path.endswith('themerc-override'): self.assertEqual(editors.flat_values(reset, ':'), editors.flat_values(baseline, ':'))
                elif '/kitty/' in path: self.assertEqual(editors.flat_values(reset, ' '), editors.flat_values(baseline, ' '))
                else: self.assertEqual(editors.ini_values(reset), editors.ini_values(baseline))
        for baseline in self.defaults['greeter'].values():
            modified = editors.css(baseline, baseline, catalog.palette('mocha-rose', 'dark'))
            self.assertEqual(inventory(editors.css(modified, baseline, None)), inventory(baseline))

    def test_color_writes_preserve_layout_and_font_choices(self):
        text = '[main]\nfont=Custom Mono:size=19\nwidth=51\n[colors]\nbackground=ffffffff\n'
        result = native.render('.config/fuzzel/fuzzel.ini', text, text, 'ocean-glass', 'dark', Path('/home/test'))
        self.assertIn('font=Custom Mono:size=19', result); self.assertIn('width=51', result)
        baseline = 'button { padding: 7px 11px; font-size: 23px; color: #112233; background: #eeeeee; }'
        output = editors.css(baseline, baseline, catalog.palette('ocean-glass', 'dark'))
        self.assertIn('padding: 7px 11px', output); self.assertIn('font-size: 23px', output)

    def test_qcolor_and_fuzzel_alpha_orders_are_native(self):
        p = catalog.palette('mocha-rose', 'dark')
        dock = native.render('.config/crystal-dock/labwc/appearance.conf', '', '', 'mocha-rose', 'dark', Path('/home/test'))
        fuzzel = native.render('.config/fuzzel/fuzzel.ini', '', '', 'mocha-rose', 'dark', Path('/home/test'))
        self.assertEqual(editors.ini_values(dock)[('', 'backgroundColor')], '#e8' + p.background[1:])
        self.assertEqual(editors.ini_values(fuzzel)[('colors', 'background')], p.background[1:] + 'ff')

    def test_duplicate_color_declarations_reset_in_order(self):
        baseline = 'button { color:#123456; } button { color:#abcdef; }'
        result = editors.css(editors.css(baseline, baseline, catalog.palette('mocha-rose', 'dark')), baseline, None)
        self.assertIn('#123456', result); self.assertIn('#abcdef', result)

    def test_negated_and_foreground_only_states(self):
        p = catalog.palette('ocean-glass', 'light')
        self.assertEqual(editors._role('button:not(.active):not(.urgent)', 'color', p), p.foreground)
        self.assertEqual(editors._role('.warning', 'color', p), p.ansi[3])
        self.assertGreaterEqual(catalog.contrast(editors._role('.active', 'color', p, background=True), p.accent), 4.5)

    def test_unsupported_imports_ambiguous_keys_and_unknown_paths_refused(self):
        with self.assertRaises(ValueError): editors.css('@import url("evil.css");', '', None)
        with self.assertRaises(ValueError): editors.edit_ini('[a]\nx=1\nx=2\n', {})
        with self.assertRaises(ValueError): native.identify('.ssh/config')
        with self.assertRaises(ValueError): catalog.palette('arbitrary', 'dark')

    def test_all_menu_profiles_and_reset_are_present(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out): appearance_cli.main(['--catalog'])
        data = json.loads(out.getvalue())
        self.assertEqual(set(data['profiles']), set(catalog.COMPONENTS))
        for profiles in data['profiles'].values(): self.assertEqual(len(profiles), 32)
        self.assertEqual(set(data['reset']), {*catalog.COMPONENTS, 'mode', 'all'})

    def test_global_mode_and_component_resets_preserve_other_selections(self):
        old = engine.initial(self.defaults)
        state, affected, privileged = engine.selection(old, ['mode', 'dark'], self.defaults)
        self.assertTrue(privileged); self.assertIn('mode', affected)
        self.assertEqual(state['mode'], 'dark')
        changed, affected, privileged = engine.selection(state, ['apply', 'waybar', 'mocha-rose'], self.defaults)
        self.assertEqual(affected, {'waybar'}); self.assertFalse(privileged)
        restored, _, _ = engine.selection(changed, ['reset', 'waybar'], self.defaults)
        self.assertIsNone(restored['profiles']['waybar'])
        self.assertEqual(restored['profiles']['dock'], state['profiles']['dock'])
        reset, _, _ = engine.selection(restored, ['reset', 'all'], self.defaults)
        self.assertEqual(reset, old)


class TransactionTests(Temporary):
    def test_apply_rollback_and_added_file_removal(self):
        with Tree(self.root) as tree:
            tree.write('native.ini', b'original')
            journal = transaction.plan(tree, {'native.ini': b'new', 'qt/colors.ini': b'palette'}, TOKEN)
            transaction.validate(journal, {'native.ini', 'qt/colors.ini'})
            transaction.apply(tree, journal)
            self.assertEqual(tree.read('native.ini'), b'new')
            transaction.rollback(tree, journal)
            self.assertEqual(tree.read('native.ini'), b'original')
            self.assertIsNone(tree.read('qt/colors.ini', missing=True))

    def test_concurrent_user_edits_are_not_overwritten(self):
        with Tree(self.root) as tree:
            tree.write('config', b'old')
            journal = transaction.plan(tree, {'config': b'new'}, TOKEN)
            tree.write('config', b'user-change')
            for operation in (transaction.apply, transaction.rollback):
                with self.assertRaises(RuntimeError): operation(tree, journal)
            self.assertEqual(tree.read('config'), b'user-change')

    def test_rollback_after_partial_file_commit(self):
        with Tree(self.root) as tree:
            tree.write('one', b'old1'); tree.write('two', b'old2')
            journal = transaction.plan(tree, {'one': b'new1', 'two': b'new2'}, TOKEN)
            tree.write('one', b'new1')
            transaction.rollback(tree, journal)
            self.assertEqual(tree.read('one'), b'old1'); self.assertEqual(tree.read('two'), b'old2')

    def test_journal_cannot_name_arbitrary_paths(self):
        with Tree(self.root) as tree:
            journal = transaction.plan(tree, {'config': b'new'}, TOKEN)
        with self.assertRaises(ValueError): transaction.validate(journal, {'another'})
        journal['token'] = '../token'
        with self.assertRaises(ValueError): transaction.validate(journal, {'config'})

    def test_recovery_restores_local_state_even_if_authentication_fails(self):
        with Tree(self.root) as tree:
            name = '.config/waybar/style.css'
            tree.write(name, b'old')
            journal = transaction.plan(tree, {name: b'new'}, TOKEN)
            journal.update(greeter=True, dockRunning=True, oldSettings=None, newSettings=None)
            tree.put_json(engine.JOURNAL, journal); transaction.apply(tree, journal)
            with mock.patch.object(engine, 'privileged', side_effect=RuntimeError('cancelled')), \
                 mock.patch.object(engine.service, 'dock_start') as start, self.assertRaises(RuntimeError):
                engine.recover(tree)
            self.assertEqual(tree.read(name), b'old'); start.assert_called_once()
            self.assertIsNotNone(tree.json(engine.JOURNAL))
            with mock.patch.object(engine, 'privileged') as privileged, mock.patch.object(engine.service, 'dock_start'):
                self.assertTrue(engine.recover(tree))
            privileged.assert_called_once_with('rollback', TOKEN)
            self.assertIsNone(tree.json(engine.JOURNAL))

    def test_committed_recovery_finishes_instead_of_rolling_back(self):
        with Tree(self.root) as tree:
            name = '.config/waybar/style.css'; tree.write(name, b'old')
            journal = transaction.plan(tree, {name: b'new'}, TOKEN)
            transaction.apply(tree, journal)
            journal.update(phase='committed', greeter=True, dockRunning=False, oldSettings=None, newSettings=None)
            tree.put_json(engine.JOURNAL, journal)
            with mock.patch.object(engine, 'privileged') as privileged: engine.recover(tree)
            privileged.assert_called_once_with('commit', TOKEN)
            self.assertEqual(tree.read(name), b'new')

    def test_greeter_rejects_bad_request_before_editing_files(self):
        with mock.patch.object(greeter, 'caller', return_value=1000):
            for args in (['shell', 'ls'], ['apply', 'theme', 'dark'], ['commit', '../token']):
                with self.subTest(args=args), self.assertRaises(ValueError): greeter.main(args)


class IntegrationTests(unittest.TestCase):
    def test_installer_modules_stage_every_new_module(self):
        for package, script in (('gitbuild', 'scripts/late/devops/gitbuild.sh'),
                                ('labwc_appearance', 'scripts/desktop/components/appearance.sh')):
            text = (SEED / script).read_text()
            for path in (LIB / package).glob('*.py'):
                self.assertRegex(text, r'\b' + re.escape(path.stem) + r'\b')
        self.assertIn('desktop_capture_appearance_defaults', (SEED / 'scripts/desktop/labwc.sh').read_text())
        self.assertIn('devops_stage_gitbuild', (SEED / 'scripts/late/devops/main-orchestration.sh').read_text())

    def test_packaged_dependencies_and_devops_paths_are_wired(self):
        text = (SEED / 'classes/class-addon/devops.cfg').read_text()
        for package in ('sbuild', 'mmdebstrap', 'debmake', 'uidmap', 'autopkgtest', 'fzf', 'fakeroot', 'lintian'):
            self.assertRegex(text, r'\b' + package + r'\b')
        desktop = (SEED / 'classes/class-select/role/desktop.cfg').read_text()
        self.assertIn('python3-tinycss2', desktop)
        environment = (TARGET / 'etc/skel-desktop/.profile.d/71-devops-de.sh').read_text()
        for name in ('GITBUILD_WORKSPACE', 'GITBUILD_CACHE_HOME', 'GITBUILD_STATE_HOME', 'GITBUILD_DISTRIBUTION'):
            self.assertIn(name, environment)

    def test_computer_management_routes_appearance(self):
        text = (TARGET / 'usr/local/bin/labwc-computer-management').read_text()
        self.assertIn('Desktop Appearance', text)
        self.assertIn('labwc-desktop-appearance', text)

    def test_polkit_paths_are_exact_and_require_authentication(self):
        for name, helper in (('desktop-appearance', 'labwc-appearance-greeter'), ('gitbuild-import', 'gitbuild-import-local')):
            root = ET.parse(TARGET / ('usr/share/polkit-1/actions/org.labwc.' + name + '.policy')).getroot()
            action = root.find('action')
            self.assertEqual(action.find('annotate').text.strip(), '/usr/local/libexec/' + helper)
            self.assertEqual(action.find('defaults/allow_active').text, 'auth_admin_keep')
            self.assertEqual(action.find('defaults/allow_any').text, 'no')

    def test_worker_profile_uses_master_mode_and_refuses_unconfined_builds(self):
        text = (TARGET / 'etc/apparmor/modes.conf.tmpl').read_text()
        entries = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
        self.assertIn('__DESKTOP_APPARMOR_STATE__ if-executable gitbuild-worker /usr/local/libexec/gitbuild-worker', entries)
        profile = (TARGET / 'etc/apparmor.d/gitbuild-worker').read_text()
        self.assertIn('profile gitbuild-worker /usr/local/libexec/gitbuild-worker', profile)
        self.assertNotRegex(profile, r'flags=\([^)]*complain')
        self.assertIn('deny /usr/bin/{pkexec,sudo,su} x', profile)
        self.assertIn('gitbuild-worker', (SEED / 'scripts/late/security.sh').read_text())

    @unittest.skipUnless(shutil.which('apparmor_parser'), 'AppArmor parser not installed')
    def test_root_import_can_traverse_caller_home_without_reading_its_secrets(self):
        text = (TARGET / 'etc/apparmor.d/gitbuild').read_text()
        profile = text.split('profile gitbuild-import-local ', 1)[1].split('profile gitbuild-publish ', 1)[0]
        self.assertIn('\n  @{HOME}/ r,', profile)
        self.assertIn('@{HOME}/Workspace/{,**/}target/gitbuild/*/artifacts/*.deb r,', profile)
        self.assertNotIn('@{HOME}/**', profile)
        self.assertNotIn('.gnupg', profile)

    @unittest.skipUnless(shutil.which('apparmor_parser') and
                         Path('/etc/apparmor.d/abstractions/base').is_file() and
                         Path('/usr/share/apparmor-features/features').is_file(),
                         'System AppArmor parser and policy files not installed')
    def test_all_new_and_modified_apparmor_profiles_parse_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree('/etc/apparmor.d', root, dirs_exist_ok=True)
            for folder in ('abstractions', 'local'):
                source = TARGET / 'etc/apparmor.d' / folder
                if source.is_dir(): shutil.copytree(source, root / folder, dirs_exist_ok=True)
            for name in ('gitbuild', 'gitbuild-worker', 'labwc-appearance', 'desktop-wrappers', 'debugsys'):
                path = root / name; path.write_text(render_theme_defaults(read_text(TARGET / 'etc/apparmor.d' / name)))
                result = subprocess.run(['apparmor_parser', '-Q', '-T', '-I', str(root), str(path)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_new_python_entrypoints_are_installed_executable_from_nonexecutable_sources(self):
        for path in (TARGET / 'usr/local/bin/gitbuild', TARGET / 'usr/local/bin/labwc-desktop-appearance',
                     *(TARGET / 'usr/local/libexec').glob('gitbuild-*'),
                     *(TARGET / 'usr/local/libexec').glob('labwc-appearance-*')):
            self.assertFalse(path.stat().st_mode & 0o111, str(path))
            self.assertEqual(path.read_text().splitlines()[0], '#!/usr/bin/python3 -IB')
        self.assertIn('"/$path" 0755', (SEED / 'scripts/late/devops/gitbuild.sh').read_text())
        self.assertIn('/usr/local/bin/labwc-desktop-appearance 0755',
                      (SEED / 'scripts/desktop/components/appearance.sh').read_text())


if __name__ == '__main__':
    unittest.main()
