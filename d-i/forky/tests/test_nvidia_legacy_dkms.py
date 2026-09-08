"""NVIDIA 580/Linux 7.2 regression tests; no driver installation or GPU access.

The failing function is the one in the supplied 580.142 make.log and NVIDIA's
580.142 kernel-open/nvidia/os-interface.c. The installed proprietary layout is
covered separately. Test the actual generated DKMS wrapper, not a second patch.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

SEED = Path(__file__).resolve().parents[1]
HOOK = SEED / 'hooks/installer/pre-pkgsel.d/92nvidia-legacy-dkms.sh'
MARKER = 'NV_INSTALLER_NVIDIA_LEGACY_STRNCPY_COMPAT'
OLD = r'''void NV_API_CALL os_get_current_process_name(char *buf, NvU32 len)
{
    task_lock(current);
    strncpy(buf, current->comm, len - 1);
    buf[len - 1] = '\0';
    task_unlock(current);
}
'''
NEW = OLD.replace(
    "    strncpy(buf, current->comm, len - 1);\n    buf[len - 1] = '\\0';\n",
    f'    /* {MARKER} */\n    strscpy_pad(buf, current->comm, len);\n',
)
HEADER = '#include "conftest.h"\n#include <linux/string.h>\n'


def wrapper_text() -> str:
    return HOOK.read_text().split("<<'EOF'\n", 1)[1].split('\nEOF', 1)[0]


class NvidiaLegacyDkmsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nvidia-580-regression-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch_functions = wrapper_text().split('\npatch_legacy_nvidia_source_tree()', 1)[0]
        self.env = {**os.environ, 'LC_ALL': 'C'}

    def run_patch(self, path: Path, shell=None, env=None):
        return subprocess.run(
            [*(shell or ['/bin/sh']), '-eu', '-c',
             self.patch_functions + '\npatch_nv_os_interface "$1"\n', 'sh', str(path)],
            capture_output=True, text=True, timeout=10, env=env or self.env,
        )

    def source(self, relative='os-interface.c', content=OLD):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def sandbox_wrapper(self, real_body='exit 0\n'):
        text = wrapper_text()
        # Relocate only filesystem constants, preserving the production shell
        # control flow and every argument passed to the real DKMS executable.
        text = text.replace('/usr/src/', str(self.root / 'usr/src') + '/')
        text = text.replace('/var/lib/dkms/', str(self.root / 'var/lib/dkms') + '/')
        real = self.root / 'dkms.distrib'
        text = text.replace('/usr/sbin/dkms.distrib', str(real))
        real.write_text('#!/bin/sh\nset -eu\n' + real_body)
        real.chmod(0o755)
        script = self.root / 'dkms'
        script.write_text(text + '\n')
        script.chmod(0o755)
        return script

    def test_rewrites_only_known_function_and_preserves_metadata(self):
        prefix = '/* unrelated code before */\nvoid untouched(void) { strncpy(a, b, n); }\n'
        suffix = '\n/* unrelated code after */\n'
        path = self.source(content=prefix + OLD + suffix)
        path.chmod(0o640)
        before = path.stat()
        result = self.run_patch(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_text(), prefix + NEW + suffix)
        self.assertIn('Applied NVIDIA 580 Linux 7.2', result.stderr)
        after = path.stat()
        self.assertEqual(stat.S_IMODE(after.st_mode), 0o640)
        self.assertEqual((after.st_uid, after.st_gid), (before.st_uid, before.st_gid))
        self.assertEqual(list(self.root.glob('*.tmp.*')), [])

    def test_idempotent_without_touching_mtime_or_inode(self):
        path = self.source()
        self.assertEqual(self.run_patch(path).returncode, 0)
        before = path.stat()
        again = self.run_patch(path)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(path.read_text(), NEW)
        self.assertEqual(path.stat().st_ino, before.st_ino)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(again.stderr, '')

    def test_already_fixed_source_does_not_need_write_access(self):
        # In particular, an unprivileged `dkms status` must not need mktemp
        # write access to /usr/src after the installation has patched it.
        bindir = self.root / 'no-writes'
        bindir.mkdir()
        stub = bindir / 'mktemp'
        stub.write_text('#!/bin/sh\necho unexpected-write >&2\nexit 1\n')
        stub.chmod(0o755)
        path = self.source(content=NEW)
        result = self.run_patch(path, env={**self.env, 'PATH': str(bindir) + ':' + self.env['PATH']})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(path.read_text(), NEW)

    def test_accepts_equivalent_vendor_fix_without_marker(self):
        content = NEW.replace(f'    /* {MARKER} */\n', '')
        path = self.source(content=content)
        inode = path.stat().st_ino
        result = self.run_patch(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_text(), content)
        self.assertEqual(path.stat().st_ino, inode)

    def test_handles_tabs_and_crlf_in_known_function(self):
        path = self.source(content=OLD.replace('    ', '\t').replace('\n', '\r\n'))
        result = self.run_patch(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_text(), NEW)

    def test_unknown_duplicate_or_partial_function_fails_without_edit(self):
        cases = {
            'missing function': '/* no recognized function */\n',
            'duplicate function': OLD + '\n' + OLD,
            'wrong copy size': OLD.replace('len - 1);', 'len);'),
            'missing terminator': OLD.replace("    buf[len - 1] = '\\0';\n", ''),
            'missing lock': OLD.replace('    task_lock(current);\n', ''),
            'missing unlock': OLD.replace('    task_unlock(current);\n', ''),
            'unterminated function': OLD.rsplit('}', 1)[0],
            'stale marker': OLD.replace('    strncpy', f'    /* {MARKER} */\n    strncpy'),
            'incorrect safe size': NEW.replace('comm, len);', 'comm, len - 1);'),
            'partial new function': NEW.replace('    task_unlock',
                "    buf[len - 1] = '\\0';\n    task_unlock"),
            'duplicate marker': NEW.replace(f'/* {MARKER} */', f'/* {MARKER} */ /* {MARKER} */'),
        }
        for label, content in cases.items():
            with self.subTest(label=label):
                path = self.source(content=content)
                original = path.read_bytes()
                inode = path.stat().st_ino
                result = self.run_patch(path)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn('unrecognized NVIDIA 580 os_get_current_process_name', result.stderr)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(path.stat().st_ino, inode)
                self.assertEqual(list(self.root.glob('*.tmp.*')), [])

    def test_unreadable_missing_source_fails(self):
        result = self.run_patch(self.root / 'missing.c')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not readable', result.stderr)

    def test_temp_copy_and_publish_failures_leave_original_intact(self):
        for command in ('mktemp', 'cp', 'mv'):
            with self.subTest(command=command):
                bindir = self.root / command
                bindir.mkdir()
                stub = bindir / command
                stub.write_text('#!/bin/sh\nexit 1\n')
                stub.chmod(0o755)
                path = self.source()
                result = self.run_patch(path, env={**self.env, 'PATH': str(bindir) + ':' + self.env['PATH']})
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertEqual(path.read_text(), OLD)
                self.assertEqual(list(self.root.glob('*.tmp.*')), [])

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox not installed')
    def test_busybox_ash_and_awk_execute_the_patcher(self):
        bindir = self.root / 'bin'
        bindir.mkdir()
        (bindir / 'awk').symlink_to(shutil.which('busybox'))
        path = self.source()
        result = self.run_patch(path, shell=[shutil.which('busybox'), 'sh'],
                                env={**self.env, 'PATH': str(bindir) + ':' + self.env['PATH']})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_text(), NEW)

    def test_wrapper_covers_source_build_symlink_and_nested_layout(self):
        roots = ['usr/src/nvidia-580.142', 'usr/src/nvidia-current-580.142',
                 'var/lib/dkms/nvidia/580.142/build']
        paths = []
        for root in roots:
            for layout in ('', 'kernel-open/'):
                self.source(f'{root}/{layout}common/inc/nv-linux.h', HEADER)
                paths.append(self.source(f'{root}/{layout}nvidia/os-interface.c'))
        link = self.root / 'var/lib/dkms/nvidia/580.142/source'
        link.symlink_to(self.root / roots[0], target_is_directory=True)
        other = self.source('usr/src/nvidia-590.48.01/nvidia/os-interface.c')
        other_dkms = self.source('var/lib/dkms/nvidia/570.86/build/nvidia/os-interface.c')
        script = self.sandbox_wrapper('printf "<%s>\\n" "$@"\nexit 23\n')
        result = subprocess.run([str(script), 'build', '-m', 'nvidia', 'space in argument'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(result.stdout, '<build>\n<-m>\n<nvidia>\n<space in argument>\n')
        for path in paths:
            self.assertEqual(path.read_text(), NEW)
        self.assertEqual(link.resolve(), (self.root / roots[0]).resolve())
        self.assertTrue(link.is_symlink())
        self.assertEqual(other.read_text(), OLD)
        self.assertEqual(other_dkms.read_text(), OLD)

    def test_wrapper_patches_before_dkms_source_copy_and_after_reunpack(self):
        path = self.source('usr/src/nvidia-580.142/nvidia/os-interface.c')
        copy = self.root / 'fresh-build.c'
        script = self.sandbox_wrapper(f'grep -q {MARKER} "{path}"\ncp "{path}" "{copy}"\n')
        for operation in ('add', 'build', 'install', 'autoinstall'):
            with self.subTest(operation=operation):
                # A package reinstall overwrites /usr/src: no stamp may cause
                # a future DKMS invocation to skip the compatibility repair.
                path.write_text(OLD)
                result = subprocess.run([str(script), operation], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(copy.read_text(), NEW)

    def test_wrapper_does_not_invoke_real_dkms_on_patch_failure(self):
        path = self.source('usr/src/nvidia-580.142/nvidia/os-interface.c', OLD + OLD)
        called = self.root / 'called'
        script = self.sandbox_wrapper(f'touch "{called}"\n')
        result = subprocess.run([str(script), 'build'], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('failed to patch NVIDIA 580 OS interface', result.stderr)
        self.assertFalse(called.exists())
        self.assertEqual(path.read_text(), OLD + OLD)

    def test_wrapper_passes_through_when_no_580_sources_exist(self):
        script = self.sandbox_wrapper('printf "%s\\n" "$1"\n')
        result = subprocess.run([str(script), 'status'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'status\n')

    @unittest.skipUnless(shutil.which('cc'), 'C compiler not installed')
    def test_compiled_function_buffer_bounds_padding_and_locking(self):
        # This is an executable API-contract fixture, not a full NVIDIA build.
        # Poisoning strncpy models the API removal even on older build hosts.
        prelude = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define NV_API_CALL
#define NvU32 uint32_t
struct task { char comm[16]; } task;
#define current (&task)
static unsigned locks, unlocks, locked;
static void task_lock(struct task *p) { assert(p == current && !locked); locked = 1; locks++; }
static void task_unlock(struct task *p) { assert(p == current && locked); locked = 0; unlocks++; }
/* Model the documented strscpy_pad contract without depending on libc strncpy. */
static long strscpy_pad(char *dst, const char *src, size_t size) {
    size_t i = 0;
    if (!size) return -7;
    while (i + 1 < size && src[i]) { dst[i] = src[i]; i++; }
    dst[i] = 0;
    if (src[i]) return -7;
    memset(dst + i + 1, 0, size - i - 1);
    return (long)i;
}
#pragma GCC poison strncpy
'''
        main = r'''
int main(void) {
    unsigned cases = 0;
    for (size_t source_len = 0; source_len < sizeof(task.comm); source_len++) {
        memset(task.comm, 'x', sizeof(task.comm));
        task.comm[source_len] = 0;
        for (uint32_t capacity = 0; capacity <= 64; capacity++) {
            unsigned char actual[80], expected[80];
            memset(actual, 0xa5, sizeof(actual));
            memset(expected, 0xa5, sizeof(expected));
            if (capacity) {
                /* Reference: old bounded copy, padding, then last-byte NUL. */
                for (uint32_t i = 0; i + 1 < capacity; i++)
                    expected[8+i] = i < source_len ? (unsigned char)task.comm[i] : 0;
                expected[8+capacity-1] = 0;
            }
            os_get_current_process_name((char *)actual + 8, capacity);
            assert(memcmp(actual, expected, sizeof(actual)) == 0);
            assert(!locked && locks == unlocks);
            cases++;
        }
    }
    os_get_current_process_name(NULL, 0);
    assert(!locked && locks == unlocks);
    printf("%u buffer cases plus NULL/zero length: PASS\n", cases);
    return 0;
}
'''
        compiler = shutil.which('cc')
        path = self.source()
        result = self.run_patch(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        fixture = self.root / 'contract.c'
        binary = self.root / 'contract'
        fixture.write_text(prelude + path.read_text() + main)
        result = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                                 '-fsanitize=undefined', '-fno-sanitize-recover=all',
                                 str(fixture), '-o', str(binary)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1040 buffer cases', result.stdout)
        # Prove the same compiler fixture rejects the original failing call.
        fixture.write_text(prelude + OLD + main)
        result = subprocess.run([compiler, '-std=c11', '-Werror', '-c', str(fixture),
                                 '-o', str(self.root / 'bad.o')], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('strncpy', result.stderr)


if __name__ == '__main__':
    unittest.main()
