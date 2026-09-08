#!/usr/bin/env python3
from pathlib import Path
import subprocess, tempfile, sys, json
import argparse
parser=argparse.ArgumentParser(description="Compile only the patched NVIDIA process-name function against provided kernel headers. Never loads a module.")
parser.add_argument('--headers', type=Path, required=True)
parser.add_argument('--cc', default='gcc')
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'d-i/forky/tests'))
from test_nvidia_legacy_dkms import OLD, wrapper_text
out=root/'validation/nvidia-580-xanmod-7.2.4'
headers=args.headers.resolve()
if not (headers/'Makefile').is_file() or not (headers/'Module.symvers').is_file():
    raise SystemExit('Prepared kernel headers with Makefile and Module.symvers are required')
with tempfile.TemporaryDirectory(prefix='nvidia-kernel-api-') as td:
    work=Path(td)
    path=work/'function.c'
    path.write_text(OLD)
    script=wrapper_text().split('\npatch_legacy_nvidia_source_tree()',1)[0]+'\npatch_nv_os_interface "$1"\n'
    p=subprocess.run(['/bin/sh','-eu','-c',script,'sh',str(path)],capture_output=True,text=True)
    assert p.returncode==0,p.stderr
    patched=path.read_text()
    prelude='''#include <linux/module.h>
#include <linux/sched.h>
#include <linux/sched/task.h>
#include <linux/string.h>
#define NV_API_CALL
#define NvU32 u32
#pragma GCC poison strncpy
void os_get_current_process_name(char *buf, NvU32 len);
'''
    suffix='''
static int __init compat_probe_init(void) {
    char name[16];
    os_get_current_process_name(name, sizeof(name));
    return 0;
}
static void __exit compat_probe_exit(void) { }
module_init(compat_probe_init);
module_exit(compat_probe_exit);
MODULE_LICENSE("NVIDIA");
MODULE_DESCRIPTION("NVIDIA 580 process-name kernel API compile probe; do not load");
'''
    (work/'compat_probe.c').write_text(prelude+patched+suffix)
    (work/'Makefile').write_text('obj-m := compat_probe.o\n')
    cmd=['make','-C',str(headers),f'M={work}',f'CC={args.cc}','modules']
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=40)
    (out/'kernel-api-probe.log').write_text('Scope: minimal process-name function ONLY, not full NVIDIA DKMS. No module loaded.\nHeaders: '+str(headers)+'\n'+p.stdout+p.stderr)
    info=''
    if p.returncode==0:
        info=subprocess.check_output(['modinfo',str(work/'compat_probe.ko')],text=True)
        with (out/'kernel-api-probe.log').open('a') as f: f.write(info)
    report={'returncode':p.returncode,'headers':str(headers),'scope':'Minimal patched function compiled/linked as a proprietary-license module against the explicitly recorded headers, not full NVIDIA DKMS. No module loaded.', 'modinfo':info}
    (out/'kernel-api-probe.json').write_text(json.dumps(report,indent=2)+'\n')
    print(p.stdout,p.stderr,info)
    sys.exit(p.returncode)
