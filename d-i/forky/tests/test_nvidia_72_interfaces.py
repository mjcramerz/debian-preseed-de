"""NVIDIA 580 Linux-7.2 interface regressions, NOT a full NVIDIA driver build.

Source-derived minimal fixtures: NVIDIA/open-gpu-kernel-modules tag 580.142,
kernel-open/nvidia/linux_nvswitch.c, nvidia-modeset/nvidia-modeset-linux.c,
nvidia-uvm/uvm_pmm_gpu.c. The NVSwitch call sites match make(1).log exactly.
Tests execute the production wrapper's embedded Perl, never a second patcher.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

import test_nvidia_legacy_dkms as legacy
from test_nvidia_legacy_dkms import OLD, NEW, HEADER, wrapper_text

SWITCH = r'''
#include <linux/string.h>
NvlStatus nvswitch_os_read_registry_dword(void *os_handle, const char *name, NvU32 *data)
{
    char *regkey, *regkey_val_start, *regkey_val_end;
    char regkey_val[NVSWITCH_REGKEY_VALUE_LEN + 1];
    NvU32 regkey_val_len = 0;
    *data = 0;
    if (!NvSwitchRegDwords) return -NVL_ERR_GENERIC;
    regkey = strstr(NvSwitchRegDwords, name);
    if (!regkey) return -NVL_ERR_GENERIC;
    regkey = strchr(regkey, '=');
    if (!regkey) return -NVL_ERR_GENERIC;
    regkey_val_start = regkey + 1;
    regkey_val_end = strchr(regkey, ';');
    if (!regkey_val_end) regkey_val_end = strchr(regkey, '\0');
    regkey_val_len = regkey_val_end - regkey_val_start;
    if (regkey_val_len > NVSWITCH_REGKEY_VALUE_LEN || regkey_val_len == 0)
        return -NVL_ERR_GENERIC;
    strncpy(regkey_val, regkey_val_start, regkey_val_len);
    regkey_val[regkey_val_len] = '\0';
    if (nvswitch_os_strtouint(regkey_val, data) != 0) return -NVL_ERR_GENERIC;
    return NVL_SUCCESS;
}
char*
nvswitch_os_strncpy
(
    char *dest,
    const char *src,
    NvLength length
)
{
    return strncpy(dest, src, length);
}
'''
MODESET = '''#include <linux/string.h>
char* nvkms_strncpy(char *dest, const char *src, size_t n)
{
    return strncpy(dest, src, n);
}
'''
UVM = '''#include <linux/string.h>
struct { char name[64]; } chunk_split_cache[2];
static void init_chunk_split_cache_level(unsigned level)
{
    strncpy(chunk_split_cache[level].name, "uvm_gpu_chunk_t", sizeof(chunk_split_cache[level].name) - 1);
}
'''
# Shell harness implementing the documented vendor conftest call interface.
# It is intentionally minimal; it is NOT the complete NVIDIA conftest.sh.
CONFTEST = '''#!/bin/sh
set -eu
CC=$1
CFLAGS=$2
cd "$(dirname "$0")"
CONFTEST_PREAMBLE=""
compile_check_conftest() {
    printf '%s\\n' "$CONFTEST_PREAMBLE" "$1" > probe.c
    if $CC $CFLAGS -c probe.c -o probe.o; then
        printf '#define %s\\n' "$2"
    else
        printf '#undef %s\\n' "$2"
    fi
}
compile_test() {
    case "$1" in
        drm_plane_atomic_check_has_atomic_state_arg)
            :
        ;;
    esac
}
compile_test "$3"
'''
MK = 'NV_CONFTEST_TYPE_COMPILE_TESTS += drm_plane_atomic_check_has_atomic_state_arg\n'
DRM_HEADER = '''#ifndef __NVIDIA_DRM_CONFTEST_H__
#define __NVIDIA_DRM_CONFTEST_H__
#include "conftest.h"
#endif /* defined(__NVIDIA_DRM_CONFTEST_H__) */
'''


def functions():
    return wrapper_text().split('\npatch_legacy_nvidia_source_tree()', 1)[0]


def write_tree(root: Path, *, drm=True, original_process=False):
    data = {'common/inc/nv-linux.h': HEADER,
            'nvidia/os-interface.c': OLD if original_process else NEW,
            'nvidia/linux_nvswitch.c': SWITCH,
            'nvidia-modeset/nvidia-modeset-linux.c': MODESET,
            'nvidia-uvm/uvm_pmm_gpu.c': UVM}
    if drm:
        data.update({'conftest.sh': CONFTEST, 'nvidia-drm/nvidia-drm-sources.mk': MK,
                     'nvidia-drm/nvidia-drm-conftest.h': DRM_HEADER})
    for name, text in data.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return data


def patch(root: Path, *, shell='/bin/sh'):
    return subprocess.run([shell, '-eu', '-c', functions() + '\npatch_nv_72_interfaces "$1"\n',
                           'sh', str(root)], capture_output=True, text=True, timeout=20)


class Nvidia72InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nv72-interfaces-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tree = self.root / 'source'
        self.files = write_tree(self.tree)

    def must_patch(self):
        p = patch(self.tree)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def test_repairs_all_remaining_string_sites_and_keeps_exported_abi(self):
        self.must_patch()
        switch = (self.tree / 'nvidia/linux_nvswitch.c').read_text()
        mode = (self.tree / 'nvidia-modeset/nvidia-modeset-linux.c').read_text()
        uvm = (self.tree / 'nvidia-uvm/uvm_pmm_gpu.c').read_text()
        self.assertIn('memcpy(regkey_val, regkey_val_start, regkey_val_len);', switch)
        self.assertIn("regkey_val[regkey_val_len] = '\\0';", switch)
        self.assertRegex(switch, r'char\*\s+nvswitch_os_strncpy')
        self.assertIn('char* nvkms_strncpy', mode)
        for text in (switch, mode):
            self.assertIn('return dest;', text)
            self.assertIn('strnlen(src,', text)
            self.assertIn('memset(dest + copied, 0,', text)
            self.assertNotIn('return strscpy', text)
            self.assertNotRegex(text, r'\bstrncpy\b')
        self.assertIn('strscpy_pad(chunk_split_cache[level].name, "uvm_gpu_chunk_t", sizeof(chunk_split_cache[level].name));', uvm)

    def test_idempotent_preserves_metadata_and_no_temporary_files(self):
        path = self.tree / 'nvidia/linux_nvswitch.c'
        path.chmod(0o640)
        owner = (path.stat().st_uid, path.stat().st_gid)
        self.must_patch()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertEqual((path.stat().st_uid, path.stat().st_gid), owner)
        before = {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns)
                  for p in self.tree.rglob('*') if p.is_file()}
        p = self.must_patch()
        self.assertEqual(p.stderr, '')
        for path, prior in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns), prior)
        self.assertFalse(list(self.tree.rglob('*.nv72.*')))

    def test_patch_already_clean_tree_needs_no_write_access(self):
        self.must_patch()
        for p in self.tree.rglob('*'):
            if p.is_file(): p.chmod(0o444)
        self.must_patch()

    def test_readonly_unprivileged_rerun(self):
        if os.geteuid() != 0:
            self.skipTest('requires root to drop privileges')
        self.must_patch()
        self.root.chmod(0o755)
        for p in self.tree.rglob('*'):
            p.chmod(0o555 if p.is_dir() else 0o444)
        self.tree.chmod(0o555)
        script = self.root / 'readonly.sh'
        script.write_text(functions() + '\npatch_nv_72_interfaces "$1"\n')
        script.chmod(0o555)
        p = subprocess.run(['/bin/sh', str(script), str(self.tree)], user=65534, group=65534,
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_unknown_raw_call_anywhere_stops_before_changes(self):
        unknown = self.tree / 'nvidia-uvm/subdir/another.c'
        unknown.parent.mkdir()
        unknown.write_text('void other(void) { strncpy(dst, src, n); }\n')
        before = {n: (self.tree / n).read_bytes() for n in self.files}
        p = patch(self.tree)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('unhandled removed strncpy API', p.stderr)
        self.assertIn('another.c:1', p.stderr)
        for n, value in before.items():
            self.assertEqual((self.tree / n).read_bytes(), value)

    def test_audit_ignores_comments_strings_and_prefixed_identifiers(self):
        p = self.tree / 'nvidia/notes.h'
        p.write_text('/* strncpy is removed */\n// strncpy() documentation\n'
                     'const char *msg = "strncpy failed";\n'
                     'char *nvswitch_os_strncpy(char *, const char *, unsigned);\n')
        self.must_patch()

    def test_audit_catches_macro_alias_to_removed_symbol(self):
        p = self.tree / 'common/inc/unhandled.h'
        p.write_text('#define MY_COPY strncpy\n')
        result = patch(self.tree)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unhandled.h:1', result.stderr)

    def test_incorrect_wrapper_body_fails_atomically(self):
        p = self.tree / 'nvidia-modeset/nvidia-modeset-linux.c'
        p.write_text(MODESET.replace('src, n)', 'src, n - 1)'))
        before = {n: (self.tree / n).read_bytes() for n in self.files}
        result = patch(self.tree)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unrecognized NVIDIA 580 nvkms_strncpy body', result.stderr)
        for n, value in before.items(): self.assertEqual((self.tree / n).read_bytes(), value)

    def test_unknown_registry_bounds_fail_before_changes(self):
        p = self.tree / 'nvidia/linux_nvswitch.c'
        text = SWITCH.replace('regkey_val_len > NVSWITCH_REGKEY_VALUE_LEN', 'regkey_val_len > 10000')
        p.write_text(text)
        result = patch(self.tree)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(p.read_text(), text)

    def test_partial_own_patch_is_not_accepted_by_marker(self):
        self.must_patch()
        for rel, old, new in (
            ('nvidia/linux_nvswitch.c', 'return dest;', 'return src;'),
            ('nvidia-drm/nvidia-drm-conftest.h', '#define drm_atomic_state_put drm_atomic_commit_put', ''),
            ('conftest.sh', 'return sizeof(struct drm_atomic_commit);', 'return 0;'),
        ):
            with self.subTest(file=rel):
                p = self.tree / rel
                good = p.read_text()
                bad = good.replace(old, new)
                p.write_text(bad)
                result = patch(self.tree)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertEqual(p.read_text(), bad)
                p.write_text(good)

    def test_source_file_symlinks_rejected_without_overwriting(self):
        p = self.tree / 'nvidia/linux_nvswitch.c'
        real = self.root / 'real.c'
        p.rename(real)
        p.symlink_to(real)
        result = patch(self.tree)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(p.is_symlink())
        self.assertEqual(real.read_text(), SWITCH)

    def test_partial_drm_tree_is_rejected(self):
        (self.tree / 'conftest.sh').unlink()
        p = patch(self.tree)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('incomplete NVIDIA DRM source tree', p.stderr)

    def test_vendor_clean_non_drm_sources_left_unchanged(self):
        shutil.rmtree(self.tree)
        self.tree.mkdir()
        f = self.tree / 'nvidia-modeset/nvidia-modeset-linux.c'
        f.parent.mkdir()
        text = '/* vendor implementation without removed API */\n'
        f.write_text(text)
        self.must_patch()
        self.assertEqual(f.read_text(), text)

    def test_tabs_crlf_and_duplicate_wrapper(self):
        p = self.tree / 'nvidia-modeset/nvidia-modeset-linux.c'
        p.write_bytes(MODESET.replace('    ', '\t').replace('\n', '\r\n').encode())
        self.must_patch()
        p.write_text(MODESET + MODESET)
        result = patch(self.tree)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate', result.stderr)

    @unittest.skipUnless(shutil.which('busybox'), 'BusyBox unavailable')
    def test_busybox_ash_runs_generated_perl_patch(self):
        script = self.root / 'patch.sh'
        script.write_text(functions() + '\npatch_nv_72_interfaces "$1"\n')
        p = subprocess.run(['busybox', 'sh', '-eu', str(script), str(self.tree)],
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)

    @unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
    def test_compiled_bounded_copy_and_registry_contracts(self):
        self.must_patch()
        switch = (self.tree / 'nvidia/linux_nvswitch.c').read_text().replace('#include <linux/string.h>', '')
        mode = (self.tree / 'nvidia-modeset/nvidia-modeset-linux.c').read_text().replace('#include <linux/string.h>', '')
        uvm = (self.tree / 'nvidia-uvm/uvm_pmm_gpu.c').read_text().replace('#include <linux/string.h>', '')
        prelude = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/mman.h>
#include <unistd.h>
typedef size_t NvLength;
typedef uint32_t NvU32;
typedef int NvlStatus;
#define NVSWITCH_REGKEY_VALUE_LEN 8
#define NVL_ERR_GENERIC 1
#define NVL_SUCCESS 0
static const char *NvSwitchRegDwords;
static int nvswitch_os_strtouint(char *s, unsigned *v) {
    char *end; unsigned long x;
    errno=0; x=strtoul(s, &end, 16);
    if (errno || *end || x>UINT32_MAX) return -1;
    *v=(unsigned)x; return 0;
}
static long strscpy_pad(char *d, const char *s, size_t n) {
    size_t i=0;
    if (!n) return -7;
    while (i+1<n && s[i]) { d[i]=s[i]; ++i; }
    d[i]=0;
    if (s[i]) return -7;
    memset(d+i+1, 0, n-i-1); return (long)i;
}
#pragma GCC poison strncpy
'''
        main = r'''
int main(void) {
    unsigned cases=0;
    char *(*copies[])(char *,const char *,size_t)={nvswitch_os_strncpy,nvkms_strncpy};
    for (size_t f=0; f<2; f++) {
        assert(copies[f](NULL,NULL,0)==NULL);
        for(size_t len=0;len<=96;len++) {
            char src[98]; memset(src,'Q',sizeof(src)); src[len]=0;
            for(size_t n=0;n<=96;n++) {
                unsigned char got[112],want[112];
                memset(got,0xa5,sizeof(got)); memset(want,0xa5,sizeof(want));
                for(size_t i=0;i<n;i++) want[8+i]=i<len?'Q':0;
                assert(copies[f]((char*)got+8,src,n)==(char*)got+8);
                assert(!memcmp(got,want,sizeof(got))); cases++;
            }
        }
        /* A non-NUL source ending exactly at a protected page boundary. */
        size_t page=(size_t)sysconf(_SC_PAGESIZE);
        char *m=mmap(NULL,page*2,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        assert(m!=MAP_FAILED); assert(!mprotect(m+page,page,PROT_NONE));
        memset(m+page-32,'X',32);
        char out[32]; assert(copies[f](out,m+page-32,32)==out);
        for (size_t i=0;i<32;i++) assert(out[i]=='X');
        assert(!munmap(m,page*2));
    }
    NvU32 value;
    NvSwitchRegDwords="Key=1234abcd;Other=1";
    assert(!nvswitch_os_read_registry_dword(NULL,"Key",&value)); assert(value==0x1234abcdU);
    NvSwitchRegDwords="Key=f";
    assert(!nvswitch_os_read_registry_dword(NULL,"Key",&value)); assert(value==15);
    NvSwitchRegDwords="Key=ffffffff";
    assert(!nvswitch_os_read_registry_dword(NULL,"Key",&value)); assert(value==UINT32_MAX);
    NvSwitchRegDwords="Key=;Other=1";
    assert(nvswitch_os_read_registry_dword(NULL,"Key",&value)!=0);
    NvSwitchRegDwords="Key=123456789";
    assert(nvswitch_os_read_registry_dword(NULL,"Key",&value)!=0);
    memset(chunk_split_cache,0xa5,sizeof(chunk_split_cache));
    init_chunk_split_cache_level(0);
    assert(!strcmp(chunk_split_cache[0].name,"uvm_gpu_chunk_t"));
    for(size_t i=strlen("uvm_gpu_chunk_t");i<64;i++) assert(!chunk_split_cache[0].name[i]);
    printf("%u ABI-copy boundary cases, source guard pages, registry and UVM contracts: PASS\n",cases);
    return 0;
}
'''
        c = self.root / 'contracts.c'
        exe = self.root / 'contracts'
        c.write_text(prelude + switch + mode + uvm + main)
        for compiler_index, compiler in enumerate(filter(None, (shutil.which('cc'), shutil.which('clang')))):
            with self.subTest(compiler=compiler):
                probe = subprocess.run([
                    compiler, '-std=gnu11', '-fsanitize=undefined', '-x', 'c', '-',
                    '-o', str(self.root / f'ubsan-probe-{compiler_index}'),
                ], input='int main(void) { return 0; }\n', capture_output=True, text=True)
                if probe.returncode:
                    detail = next((line for line in reversed(probe.stderr.splitlines()) if line),
                                  'compiler cannot link the UBSan runtime')
                    self.skipTest(f'{compiler} cannot link -fsanitize=undefined: {detail}')
                p = subprocess.run([compiler, '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-O2', '-fsanitize=undefined',
                    '-fno-sanitize-recover=undefined', str(c), '-o', str(exe)], capture_output=True, text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                p = subprocess.run([str(exe)], capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertIn('18818 ABI-copy',p.stdout)
        # Every original affected translation unit fails independently: no
        # first-error stop may conceal the modeset and UVM failures this time.
        for name, text in [('NVSwitch',SWITCH),('modeset',MODESET),('UVM',UVM)]:
            with self.subTest(negative_control=name):
                c.write_text(prelude + text.replace('#include <linux/string.h>',''))
                p=subprocess.run(['cc','-std=gnu11','-c',str(c),'-o',str(self.root/'bad.o')],
                                 capture_output=True,text=True)
                self.assertNotEqual(p.returncode,0)
                self.assertIn('poisoned',p.stderr)

    @unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
    def test_drm_probe_and_callback_compilation_old_new_and_missing_types(self):
        self.must_patch()
        inc = self.root / 'include'
        (inc / 'drm').mkdir(parents=True)
        probe = self.tree / 'conftest.sh'
        common = 'struct drm_crtc {}; struct drm_plane {};\n'
        for kind in ('state','commit','missing','wrong_callback'):
            with self.subTest(api=kind):
                actual = 'commit' if kind in ('commit','wrong_callback') else 'state'
                types = common
                if kind != 'missing': types += f'struct drm_atomic_{actual} {{ int field; }};\n'
                (inc/'drm/drm_atomic.h').write_text('#pragma once\n'+types)
                cb_type = 'state' if kind == 'wrong_callback' else actual
                vtables = '#include "drm_atomic.h"\n'
                if kind == 'wrong_callback': vtables += 'struct drm_atomic_state;\n'
                for name in ('crtc','plane'):
                    vtables += f'struct drm_{name}_helper_funcs {{ int (*atomic_check)(struct drm_{name} *, struct drm_atomic_{cb_type} *); }};\n'
                (inc/'drm/drm_modeset_helper_vtables.h').write_text(vtables)
                p=subprocess.run(['/bin/sh',str(probe),'cc',f'-Werror -I{inc}',
                                  'nv_installer_drm_atomic_commit_present'],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                present = kind == 'commit'
                expected = '#define' if present else '#undef'
                self.assertEqual(p.stdout.strip(),expected+' NV_INSTALLER_DRM_ATOMIC_COMMIT_PRESENT')
                if kind not in ('state','commit'): continue
                (inc/'conftest.h').write_text(p.stdout)
                hdr=(self.tree/'nvidia-drm/nvidia-drm-conftest.h').read_text()
                (inc/'compat.h').write_text(hdr)
                # Old callback probes remain true on 6.12; they fail on 7.2
                # before the new compatibility block selects the correct path.
                if not present:
                    with (inc/'conftest.h').open('a') as out:
                        out.write('#define NV_DRM_CRTC_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG\n'
                                  '#define NV_DRM_PLANE_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG\n')
                c = self.root/'drm-test.c'
                c.write_text('''#include "compat.h"
#include <drm/drm_modeset_helper_vtables.h>
#ifndef NV_DRM_CRTC_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG
#error wrong_crtc_branch
#endif
#ifndef NV_DRM_PLANE_ATOMIC_CHECK_HAS_ATOMIC_STATE_ARG
#error wrong_plane_branch
#endif
int crtc_check(struct drm_crtc *p, struct drm_atomic_state *s) { return sizeof(*s); }
int plane_check(struct drm_plane *p, struct drm_atomic_state *s) { return sizeof(*s); }
struct drm_crtc_helper_funcs c = { .atomic_check = crtc_check };
struct drm_plane_helper_funcs p = { .atomic_check = plane_check };
''')
                p=subprocess.run(['cc','-Werror',f'-I{inc}','-c',str(c),'-o',str(self.root/'drm.o')],
                                 capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)


class Nvidia72WrapperIntegrationTests(unittest.TestCase):
    # Reuse fixture setup without rediscovering or double-counting old tests.
    setUp = legacy.NvidiaLegacyDkmsTests.setUp
    source = legacy.NvidiaLegacyDkmsTests.source
    sandbox_wrapper = legacy.NvidiaLegacyDkmsTests.sandbox_wrapper
    def test_full_tree_source_copy_build_reunpack_and_argument_forwarding(self):
        roots=['usr/src/nvidia-580.142','usr/src/nvidia-current-580.142',
               'var/lib/dkms/nvidia/580.142/build']
        for r in roots:
            for sub in ('','kernel-open'):
                write_tree(self.root/r/sub, original_process=True)
        link=self.root/'var/lib/dkms/nvidia/580.142/source'
        link.symlink_to(self.root/roots[0],target_is_directory=True)
        skipped=self.root/'usr/src/nvidia-590.10'
        write_tree(skipped,original_process=True)
        log=self.root/'called'
        script=self.sandbox_wrapper(f'printf "<%s>\\n" "$@" > "{log}"\nexit 27\n')
        for operation in ('add','build','install','autoinstall'):
            p=self.root/roots[0]/'nvidia/linux_nvswitch.c'
            p.write_text(SWITCH)
            run=subprocess.run([str(script),operation,'-m','nvidia','space in argument'],
                               capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,27,run.stderr)
            self.assertEqual(log.read_text(),f'<{operation}>\n<-m>\n<nvidia>\n<space in argument>\n')
            for r in roots:
                for sub in ('','kernel-open'):
                    tree=self.root/r/sub
                    self.assertIn('memcpy(regkey_val', (tree/'nvidia/linux_nvswitch.c').read_text())
                    self.assertIn('size_t copied;', (tree/'nvidia-modeset/nvidia-modeset-linux.c').read_text())
                    self.assertIn('strscpy_pad', (tree/'nvidia-uvm/uvm_pmm_gpu.c').read_text())
                    self.assertEqual((tree/'nvidia/os-interface.c').read_text(),NEW)
        self.assertEqual((skipped/'nvidia/linux_nvswitch.c').read_text(),SWITCH)
        self.assertTrue(link.is_symlink())

    def test_unknown_removed_api_does_not_call_real_dkms(self):
        tree=self.root/'usr/src/nvidia-580.142'
        write_tree(tree,original_process=True)
        (tree/'nvidia-uvm/new.c').write_text('void f(void) { strncpy(a,b,c); }\n')
        called=self.root/'called'
        script=self.sandbox_wrapper(f'touch "{called}"\n')
        run=subprocess.run([str(script),'build'],capture_output=True,text=True,timeout=20)
        self.assertNotEqual(run.returncode,0)
        self.assertFalse(called.exists())
        self.assertIn('unhandled removed strncpy API',run.stderr)


if __name__ == '__main__':
    unittest.main()
