#!/usr/bin/env python3
"""Compile repaired interfaces against real prepared headers; NEVER load a module.

Uses minimal source-derived fixtures, not the complete proprietary driver.
An explicit header path is recorded; success does not certify another kernel.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--headers', type=Path, required=True)
parser.add_argument('--cc', default='gcc')
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / 'd-i/forky/tests'))
from test_nvidia_72_interfaces import write_tree, functions

out = Path(__file__).resolve().parent
headers = args.headers.resolve(strict=True)
for name in ('Makefile', 'Module.symvers'):
    if not (headers / name).is_file():
        parser.error(f'Prepared headers required; {name} is missing')
scope = ('Minimal repaired process-name, NVSwitch registry/copy, modeset copy, '
         'and UVM cache-name interfaces against the recorded real headers. '
         'NOT full NVIDIA DKMS, NOT a Linux 7.2 build. No module loaded.')
with tempfile.TemporaryDirectory(prefix='nv72-real-kernel-') as td:
    root = Path(td)
    tree = root / 'source'
    write_tree(tree, drm=False, original_process=True)
    script = functions() + '\npatch_nv_os_interface "$1/nvidia/os-interface.c"\npatch_nv_72_interfaces "$1"\n'
    patched = subprocess.run(['/bin/sh', '-eu', '-c', script, 'sh', str(tree)],
                             capture_output=True, text=True, timeout=20)
    if patched.returncode:
        raise SystemExit(patched.stderr)
    prelude = r'''
#include <linux/module.h>
#include <linux/sched.h>
#include <linux/sched/task.h>
#include <linux/string.h>
#include <linux/kstrtox.h>
#define NV_API_CALL
#define NvU32 u32
typedef size_t NvLength;
typedef int NvlStatus;
#define NVSWITCH_REGKEY_VALUE_LEN 8
#define NVL_ERR_GENERIC 1
#define NVL_SUCCESS 0
static const char *NvSwitchRegDwords;
static int nvswitch_os_strtouint(char *s, unsigned *v) { return kstrtou32(s, 16, v); }
void os_get_current_process_name(char *buf, NvU32 len);
NvlStatus nvswitch_os_read_registry_dword(void *os_handle, const char *name, NvU32 *data);
char *nvswitch_os_strncpy(char *dest, const char *src, NvLength length);
char *nvkms_strncpy(char *dest, const char *src, size_t n);
#pragma GCC poison strncpy
'''
    suffix = r'''
static int __init compatibility_probe_init(void)
{
    char task_name[32], buffer[64];
    NvU32 value;
    os_get_current_process_name(task_name, sizeof(task_name));
    nvswitch_os_strncpy(buffer, task_name, sizeof(buffer));
    nvkms_strncpy(buffer, task_name, sizeof(buffer));
    NvSwitchRegDwords = "Test=ffffffff;Other=1";
    if (nvswitch_os_read_registry_dword(NULL, "Test", &value))
        return -EINVAL;
    init_chunk_split_cache_level(0);
    return value == 0xffffffffU ? 0 : -EINVAL;
}
static void __exit compatibility_probe_exit(void) { }
module_init(compatibility_probe_init);
module_exit(compatibility_probe_exit);
MODULE_LICENSE("NVIDIA");
MODULE_DESCRIPTION("Compile-only compatibility probe, NOT the NVIDIA driver; do not load");
'''
    body = '\n'.join((tree / name).read_text() for name in (
        'nvidia/os-interface.c', 'nvidia/linux_nvswitch.c',
        'nvidia-modeset/nvidia-modeset-linux.c', 'nvidia-uvm/uvm_pmm_gpu.c'))
    c = prelude + body + suffix
    (root / 'compat_probe.c').write_text(c)
    (out / 'kernel-api-probe.c').write_text(c)
    (root / 'Makefile').write_text('obj-m := compat_probe.o\n')
    cmd = ['make', '-C', str(headers), f'M={root}', f'CC={args.cc}', 'modules']
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    info = ''
    undefined = ''
    if p.returncode == 0:
        info = subprocess.check_output(['modinfo', str(root / 'compat_probe.ko')], text=True)
        undefined = subprocess.check_output(['nm', '-u', str(root / 'compat_probe.ko')], text=True)
        if any(line.split()[-1] == 'strncpy' for line in undefined.splitlines() if line.split()):
            raise SystemExit('unexpected removed strncpy import in compiled probe')
    log = f'Scope: {scope}\nHeaders: {headers}\nCommand: {cmd!r}\n' + patched.stderr + p.stdout + p.stderr + info + '\nUndefined symbols (strncpy must be absent):\n' + undefined
    (out / 'kernel-api-probe.log').write_text(log)
    report = {'returncode': p.returncode, 'headers': str(headers), 'scope': scope,
              'module_created': (root / 'compat_probe.ko').is_file(), 'modinfo': info,
              'undefined_symbols': undefined, 'removed_strncpy_import': False}
    (out / 'kernel-api-probe.json').write_text(json.dumps(report, indent=2) + '\n')
    print(log)
    raise SystemExit(p.returncode)
