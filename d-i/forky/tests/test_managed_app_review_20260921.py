"""R7 app argument and descriptor safety regressions, without services."""
from __future__ import annotations
from payload_fixture import source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import python_library
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

from test_dynamic_storage_sizing_20260921 import TARGET
LIB = python_library(TARGET / 'usr/local/lib/python3.14/dist-packages')
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
from labwc_managed_app import commands, generic, profiles, sandbox, user_state


class ManagedArgumentReviewTests(unittest.TestCase):
    def test_sandbox_disable_switch_names_are_checked_not_boolean_values(self):
        names = ('disable-gpu-sandbox','disable-namespace-sandbox','disable-sandbox',
                 'disable-seccomp-filter-sandbox','disable-setuid-sandbox',
                 'no-sandbox','single-process','no-zygote','in-process-gpu')
        for mode in ('launch','intel','nvidia','pure-privacy'):
            for name in names:
                for prefix in ('-', '--'):
                    for value in ('', '=true', '=false', '=', '=0'):
                        argument = prefix+name+value
                        with self.subTest(mode=mode, argument=argument), redirect_stderr(io.StringIO()):
                            with self.assertRaises(SystemExit):
                                commands.validate_managed_arguments(mode, [argument])

    def test_split_or_missing_control_values_cannot_evade_validation(self):
        for name in ('ozone-platform','ozone-platform-hint','use-angle','use-gl',
                     'enable-features','disable-features'):
            for prefix in ('-', '--'):
                with self.subTest(name=name, prefix=prefix), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        commands.validate_managed_arguments('intel', [prefix+name, 'x11'])

    def test_native_wayland_and_opengl_arguments_remain_accepted(self):
        for prefix in ('-', '--'):
            commands.validate_managed_arguments('intel', [prefix+'ozone-platform=wayland',
                prefix+'use-angle=gl', prefix+'use-gl=angle'])
        arguments = ['https://example.org/doc', '/home/test/notes.txt']
        commands.validate_managed_arguments('launch', arguments)
        self.assertEqual(commands.normalize_managed_arguments('zoom', ['--url=', *arguments]), arguments)

    def test_gpu_disable_switch_values_are_rejected_in_accelerated_modes(self):
        for mode in ('intel','nvidia'):
            for option in ('disable-gpu','disable-gpu-compositing','disable-gpu-rasterization'):
                with self.subTest(mode=mode, option=option), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        commands.validate_managed_arguments(mode, ['-'+option+'=false'])

    def test_generic_electron_rejects_single_dash_and_equals_disable_switches(self):
        for switch in generic.ELECTRON_UNSAFE_SWITCHES:
            for prefix in ('-', '--'):
                for value in ('', '=false', '=0'):
                    with self.subTest(switch=switch, prefix=prefix, value=value), redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit):
                            generic.electron_command(['/opt/fixture/app', prefix+switch[2:]+value])

    def test_generic_electron_single_dash_control_cannot_override_enforced_platform(self):
        result = generic.electron_command(['/opt/fixture/app', '-ozone-platform=x11',
            '-use-angle=vulkan', '-use-gl=desktop', '--vendor-option=yes', 'https://example.org'])
        self.assertIn('--ozone-platform=wayland', result)
        self.assertIn('--use-angle=gl', result)
        self.assertIn('--use-gl=angle', result)
        self.assertNotIn('-ozone-platform=x11', result)
        self.assertNotIn('-use-angle=vulkan', result)
        self.assertNotIn('-use-gl=desktop', result)
        self.assertEqual(result[-2:], ['--vendor-option=yes', 'https://example.org'])

    def test_generic_electron_single_dash_features_get_same_filter_as_double_dash(self):
        single = generic.electron_command(['/opt/fixture/app', '-enable-features=VendorFeature,Vulkan'])
        double = generic.electron_command(['/opt/fixture/app', '--enable-features=VendorFeature,Vulkan'])
        self.assertEqual(single, double)
        enabled = next(a for a in single if a.startswith('--enable-features='))
        self.assertIn('VendorFeature', enabled)
        self.assertNotIn('Vulkan', enabled)


class UserStateReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='x-state-review-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root/'home'; self.home.mkdir(mode=0o700)
        self.config = self.home/'.config'; self.config.mkdir(mode=0o700)
        self.path = self.config/'test.json'
        self.seed = self.root/'seed'; self.seed.write_text('{"seed":true}\n')
        self.seed.chmod(0o600)
        self.errors = io.StringIO()
        self.capture = redirect_stderr(self.errors); self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def ensure(self, *, seed=True):
        return user_state.ensure_managed_user_file(str(self.home), '.config/test.json',
                                                   0o600, str(self.seed) if seed else None)

    def test_new_seeded_file_and_existing_content_are_preserved(self):
        self.ensure()
        self.assertEqual(payload_read_bytes(self.path), payload_read_bytes(self.seed))
        self.assertEqual(stat.S_IMODE(payload_source_stat(self.path).st_mode), 0o600)
        self.path.write_text('{"user":true}')
        self.ensure()
        self.assertEqual(payload_read_text(self.path), '{"user":true}')

    def test_unseeded_file_is_empty_private_and_not_replaced(self):
        self.ensure(seed=False)
        self.assertEqual(payload_read_bytes(self.path), b'')
        inode = payload_source_stat(self.path).st_ino
        self.path.write_text('keep'); self.ensure(seed=False)
        self.assertEqual(payload_source_stat(self.path).st_ino, inode)
        self.assertEqual(payload_read_text(self.path), 'keep')

    def test_dangling_symlink_does_not_create_its_target_inside_or_outside_home(self):
        for target in (self.root/'outside', self.home/'inside'):
            with self.subTest(target=target):
                self.path.symlink_to(target)
                with self.assertRaises(SystemExit): self.ensure()
                self.assertFalse(payload_source_exists(target))
                self.assertTrue(self.path.is_symlink())
                self.path.unlink()

    def test_existing_symlink_hardlink_and_fifo_are_rejected_without_mutation(self):
        target = self.home/'other'; target.write_text('unchanged'); target.chmod(0o644)
        for kind in ('symlink','hardlink','fifo','directory'):
            with self.subTest(kind=kind):
                if kind == 'symlink': self.path.symlink_to(target)
                elif kind == 'hardlink': os.link(target, self.path)
                elif kind == 'fifo': os.mkfifo(self.path)
                else: self.path.mkdir()
                with self.assertRaises(SystemExit): self.ensure()
                self.assertEqual(payload_read_text(target), 'unchanged')
                self.assertEqual(stat.S_IMODE(payload_source_stat(target).st_mode), 0o644)
                if kind == 'directory': self.path.rmdir()
                else: self.path.unlink()

    def test_failed_seed_copy_does_not_leave_a_partial_file(self):
        def interrupted(source, destination, **_kwargs):
            destination.write(b'partial'); raise OSError('fixture copy interruption')
        with mock.patch.object(user_state.shutil, 'copyfileobj', side_effect=interrupted):
            with self.assertRaises(SystemExit): self.ensure()
        self.assertFalse(payload_source_exists(self.path))
        self.ensure(); self.assertEqual(payload_read_bytes(self.path), payload_read_bytes(self.seed))

    def test_failed_copy_does_not_unlink_a_replacement_inode(self):
        def replaced(source, destination, **_kwargs):
            replacement = self.config/'replacement'; replacement.write_text('replacement')
            os.replace(replacement, self.path)
            raise OSError('fixture replacement during copy')
        with mock.patch.object(user_state.shutil, 'copyfileobj', side_effect=replaced):
            with self.assertRaises(SystemExit): self.ensure()
        self.assertEqual(payload_read_text(self.path), 'replacement')

    def test_seed_symlink_is_rejected_and_new_destination_removed(self):
        self.seed.unlink(); self.seed.symlink_to(self.root/'missing')
        with self.assertRaises(SystemExit): self.ensure()
        self.assertFalse(payload_source_exists(self.path))

    def test_directory_ancestry_checked_before_creation(self):
        outside = self.root/'outside'; outside.mkdir()
        (self.home/'linked').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(SystemExit):
            sandbox.persistent_app_directory(str(self.home), 'linked/should-not-exist')
        self.assertFalse(payload_source_exists(outside/'should-not-exist'))
        self.assertEqual(sandbox.persistent_app_directory(str(self.home), 'normal/child'),
                         str(self.home/'normal/child'))

    def test_json_valid_object_and_duplicate_or_nonobject_rejection(self):
        self.path.write_text('{"valid":[1,2,3]}')
        self.assertEqual(user_state.load_user_json_object(str(self.path), 100), {'valid':[1,2,3]})
        for payload in ('{"x":1,"x":2}', '[]', 'not json', '['*1200+']'*1200):
            with self.subTest(payload=payload[:30]):
                self.path.write_text(payload)
                with self.assertRaises(SystemExit):
                    user_state.load_user_json_object(str(self.path), 4096)

    def test_json_symlink_fifo_hardlink_and_directory_rejected(self):
        target = self.home/'other'; target.write_text('{}')
        for kind in ('symlink','hardlink','fifo','directory'):
            with self.subTest(kind=kind):
                if kind == 'symlink': self.path.symlink_to(target)
                elif kind == 'hardlink': os.link(target, self.path)
                elif kind == 'fifo': os.mkfifo(self.path)
                else: self.path.mkdir()
                with self.assertRaises(SystemExit):
                    user_state.load_user_json_object(str(self.path), 100)
                if kind == 'directory': self.path.rmdir()
                else: self.path.unlink()

    def test_json_bounded_read_even_when_reported_size_is_stale(self):
        self.path.write_text('{"padding":"'+'x'*10000+'"}')
        metadata = list(payload_source_stat(self.path)); metadata[6] = 0
        with mock.patch.object(user_state.os, 'fstat', return_value=os.stat_result(metadata)):
            with self.assertRaises(SystemExit):
                user_state.load_user_json_object(str(self.path), 64)
        self.assertIn('exceeds the size limit', self.errors.getvalue())

    def test_json_reads_validated_descriptor_not_replaced_pathname(self):
        self.path.write_text('{"opened":true}')
        fdopen = os.fdopen
        def swap_path(descriptor, mode):
            self.path.rename(self.config/'old')
            self.path.write_text('{"replacement":true}')
            return fdopen(descriptor, mode)
        with mock.patch.object(user_state.os, 'fdopen', side_effect=swap_path):
            self.assertEqual(user_state.load_user_json_object(str(self.path), 100), {'opened':True})

    def test_json_positive_integer_limit_and_utf8_validation(self):
        self.path.write_text('{}')
        for limit in (0, -1, True, 1.5, '100'):
            with self.subTest(limit=limit), self.assertRaises(SystemExit):
                user_state.load_user_json_object(str(self.path), limit)
        self.path.write_bytes(b'\xff')
        with self.assertRaises(SystemExit): user_state.load_user_json_object(str(self.path), 100)


class PreservedCompatibilityReviewTests(unittest.TestCase):
    def test_only_zoom_and_discord_remain_private_compatibility_apps(self):
        self.assertEqual(set(profiles.WAYLAND_COMPAT_APPS), {'zoom','discord'})


if __name__ == '__main__':
    unittest.main()
