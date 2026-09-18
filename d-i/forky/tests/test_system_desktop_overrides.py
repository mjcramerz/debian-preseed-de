"""Real filesystem/locking regressions; dpkg, validator and MIME tool are spies.

No installed applications or system configuration are changed. Root is needed
only to construct the same trusted-ancestry/ownership boundary as production.
"""
from contextlib import redirect_stderr
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'


def load_helper(name):
    path = TARGET / 'usr/local/libexec/labwc-wrap-desktop-files'
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


@unittest.skipUnless(os.geteuid() == 0, 'trusted root-owned reconciliation fixtures')
class ReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.m = load_helper('desktop_override_fixture')
        self.temp = tempfile.TemporaryDirectory(prefix='labwc-override-tests-', dir='/var/lib')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'vendor'; self.source.mkdir()
        self.output = self.root / 'output'; self.output.mkdir()
        self.state = self.root / 'state'; self.state.mkdir(mode=0o700)
        values = dict(DEFAULTS=self.root / 'defaults', APPLICATION_DIRS=(self.source,),
                      OUTPUT_DIR=self.output, STATE_DIR=self.state,
                      MANIFEST=self.state / 'overrides.json', PENDING=self.state / 'pending.json',
                      SOURCE_STATE=self.state / 'source-state.json',
                      DATABASE_DIRTY=self.state / 'database-dirty', LOCK=self.root / 'lock')
        for key, value in values.items():
            setattr(self.m, key, value)
        self.m.DEFAULTS.write_text('LABWC_ELECTRON_APP_DEFAULT_EXEC="/usr/local/bin/labwc-electron-app intel"\n'
                                   'LABWC_WAYLAND_APP_DEFAULT_EXEC="/usr/local/bin/labwc-wayland-app intel"\n')
        self.package = self.enterContext(mock.patch.object(self.m, 'package_for', return_value='fixture'))
        self.electron = self.enterContext(mock.patch.object(self.m, 'is_electron', return_value=False))
        self.tools = self.enterContext(mock.patch.object(self.m.subprocess, 'run', side_effect=self.tool))
        self.calls = []
        self.log = io.StringIO()
        self.enterContext(redirect_stderr(self.log))
        self.enterContext(mock.patch.dict(os.environ, {}, clear=True))
        old_umask = os.umask(0o022); self.addCleanup(os.umask, old_umask)

    def tool(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return types.SimpleNamespace(returncode=0, stdout='', stderr='')

    def write(self, name='demo.desktop', extra='', exec_value='/usr/bin/true'):
        path = self.source / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'[Desktop Entry]\nType=Application\nName=Demo\nExec={exec_value}\n{extra}')
        path.chmod(0o644)
        return path

    def run_hook(self, final=True, force=False):
        return self.m.main((['--post-invoke'] if final else []) + (['--force'] if force else []))

    def db_calls(self):
        return [args for args, kw in self.calls if args[0] == str(self.m.DATABASE_TOOL)]

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino)
                for p in self.root.rglob('*') if p.is_file()}

    def test_unchanged_state_is_quiet_cheap_and_has_no_filesystem_churn(self):
        self.write(); self.run_hook()
        before = self.snapshot(); self.calls.clear(); self.package.reset_mock(); self.electron.reset_mock()
        self.log.seek(0); self.log.truncate()
        for _ in range(5): self.assertEqual(self.run_hook(), 0)
        self.assertEqual(self.snapshot(), before)
        self.package.assert_not_called(); self.electron.assert_not_called()
        self.assertEqual(self.calls, []); self.assertEqual(self.log.getvalue(), '')

    def test_addition(self):
        self.run_hook(); self.write(); self.run_hook()
        self.assertIn('labwc-wayland-app intel -- /usr/bin/true', (self.output / 'demo.desktop').read_text())
        self.assertEqual(len(self.db_calls()), 1)

    def test_modification(self):
        p = self.write(); self.run_hook()
        p.write_text(p.read_text().replace('Name=Demo', 'Name=Changed'))
        self.run_hook(); self.assertIn('Name=Changed', (self.output / p.name).read_text())
        self.assertEqual(len(self.db_calls()), 2)

    def test_replacement_preserving_old_mtime(self):
        p = self.write(); self.run_hook(); old = p.stat()
        replacement = self.source / 'replacement'
        replacement.write_text(p.read_text().replace('/usr/bin/true', '/usr/bin/false'))
        os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns)); os.replace(replacement, p)
        self.run_hook(); self.assertIn('/usr/bin/false', (self.output / p.name).read_text())

    def test_identical_replacement_reclassifies_but_does_not_rewrite_output(self):
        p = self.write(); self.run_hook(); before = (self.output / p.name).stat()
        replacement = self.source / 'replacement'; replacement.write_bytes(p.read_bytes())
        os.utime(replacement, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns)); os.replace(replacement, p)
        self.package.reset_mock(); self.run_hook(); self.package.assert_called_once()
        self.assertEqual((self.output / p.name).stat().st_ino, before.st_ino)
        self.assertEqual(len(self.db_calls()), 1)

    def test_removed_vendor_removes_only_stale_owned_output(self):
        p = self.write(); self.run_hook(); p.unlink(); self.run_hook()
        self.assertFalse((self.output / p.name).exists())
        self.assertEqual(json.loads(self.m.MANIFEST.read_text()), {})
        self.assertEqual(len(self.db_calls()), 2)

    def test_hidden_true_false_absent(self):
        for value, expected in (('true', False), ('false', True), (None, True)):
            with self.subTest(value=value):
                self.write(extra='' if value is None else f'Hidden={value}\n')
                self.run_hook(); self.assertEqual((self.output / 'demo.desktop').exists(), expected)
        self.write(extra='Hidden=true\n'); self.run_hook()
        self.assertFalse((self.output / 'demo.desktop').exists())

    def test_nodisplay_true_false_absent_keep_mime_launch_isolation(self):
        for value in ('true', 'false', None):
            with self.subTest(value=value):
                self.write(extra='' if value is None else f'NoDisplay={value}\n'); self.run_hook()
                out = (self.output / 'demo.desktop').read_text()
                self.assertIn('labwc-wayland-app', out)
                self.assertEqual('NoDisplay=' in out, value is not None)

    def test_invalid_booleans_are_not_shell_truth_values(self):
        for key in ('Hidden', 'NoDisplay'):
            for value in ('yes', 'false-ish', 'TRUE', '1'):
                with self.subTest(key=key, value=value):
                    self.write(extra=f'{key}={value}\n'); self.run_hook()
                    self.assertFalse((self.output / 'demo.desktop').exists())
        self.assertIn('malformed', self.log.getvalue())

    def test_visibility_metadata_retained_not_evaluated_as_root(self):
        for desktop_filter in ('OnlyShowIn=labwc;\n', 'NotShowIn=GNOME;\n'):
            extra = desktop_filter + 'TryExec=/not/installed\n'
            self.write(extra=extra); self.run_hook()
            self.assertIn(extra, (self.output / 'demo.desktop').read_text())

    def test_unmanaged_admin_override_preserved_and_not_repeatedly_logged(self):
        self.write(); destination = self.output / 'demo.desktop'
        destination.write_text('administrator\n'); before = destination.stat()
        self.run_hook(); self.assertIn('preserving administrator override', self.log.getvalue())
        self.log.seek(0); self.log.truncate(); self.run_hook(); self.run_hook(final=False)
        self.assertEqual(self.log.getvalue(), '')
        self.assertEqual(destination.read_text(), 'administrator\n')
        self.assertEqual(destination.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(self.db_calls(), [])

    def test_managed_override_can_be_updated(self):
        p = self.write(); self.run_hook()
        self.write(exec_value='/usr/bin/false'); self.run_hook()
        digest = hashlib.sha256((self.output / p.name).read_bytes()).hexdigest()
        self.assertEqual(json.loads(self.m.MANIFEST.read_text())[p.name], digest)

    def test_admin_modified_former_managed_override_is_not_overwritten_or_deleted(self):
        p = self.write(); self.run_hook(); destination = self.output / p.name
        destination.write_text(destination.read_text().replace('Name=Demo', 'Name=Administrator'))
        self.run_hook(); self.assertEqual(json.loads(self.m.MANIFEST.read_text()), {})
        p.unlink(); self.run_hook()
        self.assertIn('Name=Administrator', destination.read_text())

    def test_admin_symlink_not_followed_or_deleted(self):
        self.write(); private = self.root / 'private'; private.write_text('secret')
        link = self.output / 'demo.desktop'; link.symlink_to(private)
        with mock.patch.object(self.m, 'read_desktop', wraps=self.m.read_desktop) as reader:
            self.run_hook()
            self.assertNotIn(link, [call.args[0] for call in reader.call_args_list])
        self.assertTrue(link.is_symlink()); self.assertEqual(private.read_text(), 'secret')

    def test_invalid_utf8_admin_override_is_opaque_preserved_and_quiet(self):
        self.write(); destination = self.output / 'demo.desktop'
        destination.write_bytes(b'Name=administrator\xff\n')
        self.run_hook(); self.package.reset_mock(); self.calls.clear()
        self.run_hook(); self.package.assert_not_called()
        self.assertEqual(self.calls, [])
        self.assertEqual(destination.read_bytes(), b'Name=administrator\xff\n')

    def test_invalid_utf8_vendor_does_not_block_valid_entries(self):
        invalid = self.source / 'broken.desktop'; invalid.write_bytes(b'\xff')
        self.write(); self.run_hook()
        self.assertTrue((self.output / 'demo.desktop').is_file())
        self.assertFalse((self.output / invalid.name).exists())
        self.assertIn('skipped malformed', self.log.getvalue())

    def test_new_output_directories_are_searchable_despite_private_umask(self):
        self.output.rmdir()
        self.write('nested/demo.desktop'); self.run_hook()
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.output / 'nested').stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.output / 'nested/demo.desktop').stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)

    def test_interrupted_pending_journal_recovers_exact_published_digest(self):
        self.write(); original = self.m.write_atomic
        def interrupt(path, *args, **kwargs):
            if path == self.m.MANIFEST: raise OSError('injected crash before manifest commit')
            return original(path, *args, **kwargs)
        with mock.patch.object(self.m, 'write_atomic', side_effect=interrupt), self.assertRaises(OSError):
            self.run_hook()
        self.assertTrue(self.m.PENDING.exists()); self.assertTrue(self.m.DATABASE_DIRTY.exists())
        before = (self.output / 'demo.desktop').stat().st_ino
        self.run_hook()
        self.assertFalse(self.m.PENDING.exists()); self.assertFalse(self.m.DATABASE_DIRTY.exists())
        self.assertEqual((self.output / 'demo.desktop').stat().st_ino, before)
        self.assertEqual(len(self.db_calls()), 1)
        self.assertIn('recovering interrupted', self.log.getvalue())

    def test_unpublished_dirty_intent_does_not_update_database(self):
        self.m.mark_database_dirty(); self.run_hook()
        self.assertEqual(self.db_calls(), []); self.assertFalse(self.m.DATABASE_DIRTY.exists())

    def test_pending_digest_does_not_adopt_administrator_changes(self):
        self.write(); self.run_hook(); original = json.loads(self.m.MANIFEST.read_text())
        self.m.PENDING.write_text(json.dumps(original))
        destination = self.output / 'demo.desktop'; destination.write_text('administrator\n')
        self.run_hook(); self.assertEqual(destination.read_text(), 'administrator\n')
        self.assertEqual(json.loads(self.m.MANIFEST.read_text()), {})

    def test_concurrent_invocations_share_blocking_lock(self):
        self.write(); entered = threading.Event(); release = threading.Event()
        def classify(_):
            entered.set()
            if not release.wait(5): raise RuntimeError('test release timed out')
            return False
        with mock.patch.object(self.m, 'is_electron', side_effect=classify) as classify_call:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.run_hook)
                self.assertTrue(entered.wait(5))
                second = pool.submit(self.run_hook)
                time.sleep(0.03)
                self.assertFalse(second.done())
                release.set()
                self.assertEqual(first.result(timeout=5), 0)
                self.assertEqual(second.result(timeout=5), 0)
            self.assertEqual(classify_call.call_count, 1)
        self.assertEqual(len(self.db_calls()), 1)

    def test_repeated_dpkg_and_path_calls_coalesce_but_final_is_authoritative(self):
        self.write(); self.run_hook(final=False)
        for _ in range(4): self.run_hook(final=False)
        self.assertEqual(self.package.call_count, 1)
        # Same desktop bytes; dpkg finished installing application resources.
        self.electron.return_value = True
        self.run_hook(final=True)
        self.assertEqual(self.package.call_count, 2)
        self.assertIn('labwc-electron-app', (self.output / 'demo.desktop').read_text())
        for _ in range(4): self.run_hook(final=True); self.run_hook(final=False)
        self.assertEqual(self.package.call_count, 2)

    def test_configuration_change_and_force_reconcile(self):
        self.write(); self.run_hook()
        self.m.DEFAULTS.write_text(self.m.DEFAULTS.read_text().replace(' intel', ' nvidia'))
        self.run_hook(); self.assertIn(' nvidia -- ', (self.output / 'demo.desktop').read_text())
        self.calls.clear(); self.package.reset_mock(); self.run_hook(force=True)
        self.package.assert_called_once(); self.assertEqual(self.db_calls(), [])

    def test_root_ignores_user_xdg_environment(self):
        self.write()
        with mock.patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root / 'user'), 'XDG_DATA_DIRS': '/home/other'}):
            self.run_hook()
        self.assertFalse((self.root / 'user').exists())
        self.assertTrue((self.output / 'demo.desktop').exists())
        self.assertTrue(all(kw['env'] == self.m.SAFE_ENV for _, kw in self.calls))

    def test_validation_failure_does_not_publish_or_update_database(self):
        self.write()
        self.tools.side_effect = lambda *_a, **_kw: types.SimpleNamespace(returncode=1, stdout='invalid fixture', stderr='')
        self.run_hook()
        self.assertFalse((self.output / 'demo.desktop').exists())
        self.assertFalse(self.m.DATABASE_DIRTY.exists())
        self.assertIn('desktop-file-validate rejected', self.log.getvalue())

    def test_invalid_update_retains_last_owned_wrapper_and_database(self):
        source = self.write(); self.run_hook()
        output = self.output / source.name; before = output.read_bytes()
        count = len(self.db_calls())
        source.write_text(source.read_text().replace('Name=Demo', 'Name=Changed'))
        with mock.patch.object(self.m, 'validate_desktop', side_effect=self.m.InvalidDesktop('invalid update')):
            self.run_hook()
        self.assertEqual(output.read_bytes(), before)
        self.assertIn(source.name, json.loads(self.m.MANIFEST.read_text()))
        self.assertEqual(len(self.db_calls()), count)
        source.write_bytes(b'\xff')
        self.run_hook(); self.assertEqual(output.read_bytes(), before)
        self.assertEqual(len(self.db_calls()), count)

    def test_state_permissions_and_no_public_temporary_desktop_ids(self):
        self.write(); self.run_hook()
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        for path in self.state.iterdir(): self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(list(self.output.iterdir()), [self.output / 'demo.desktop'])

    def test_missing_output_is_repaired(self):
        self.write(); self.run_hook(); (self.output / 'demo.desktop').unlink()
        self.run_hook(); self.assertTrue((self.output / 'demo.desktop').exists())

    def test_input_change_during_pass_is_not_cached_as_final(self):
        p = self.write(); once = True
        def classify(_):
            nonlocal once
            if once:
                p.write_text(p.read_text().replace('Name=Demo', 'Name=After unpack'))
                once = False
            return False
        self.electron.side_effect = classify
        self.run_hook(); self.assertIn('Name=After unpack', (self.output / p.name).read_text())
        self.assertEqual(self.package.call_count, 2)

    def test_foreign_dpkg_root_is_safe_and_does_not_acquire_lock(self):
        self.write()
        with mock.patch.dict(os.environ, {'DPKG_ROOT': '/another/root'}): self.run_hook()
        self.assertFalse(self.m.LOCK.exists())


if __name__ == '__main__':
    unittest.main()
