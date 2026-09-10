#!/usr/bin/env python3
"""Run non-destructive repository validation in a disposable Linux environment.

Perl -c can execute BEGIN blocks: validate only a trusted source tree. This does
not boot d-i, start target services, partition disks or install packages.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

def unittest_counts(text: str) -> tuple[int | None, int]:
    run_match = re.search(r'Ran (\d+) tests? in ', text)
    result_match = re.search(r'^(?:OK|FAILED)(?: \(([^)]*)\))?$', text, re.M)
    result_fields = result_match.group(1) if result_match and result_match.group(1) else ''
    skipped_match = re.search(r'(?:^|, )skipped=(\d+)(?:,|$)', result_fields)
    return (int(run_match.group(1)) if run_match else None,
            int(skipped_match.group(1)) if skipped_match else 0)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'validation')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True,exist_ok=True)
    stages = [
        ('browser-check', [sys.executable,'-B','tools/build_browser_config.py','--check'],30),
        ('build-check', [sys.executable,'-B','tools/build.py','--check'],90),
        ('preseed-check', [sys.executable,'-B','tools/check_preseeds.py'],90),
        ('shell-check', [sys.executable,'-B','tools/check_shells.py','--output',str(output/'shell-check.json')],120),
        ('tests', [sys.executable,'-B','-m','unittest','discover','-v','-s','d-i/forky/tests','-p','test_*.py'],300),
        ('audit', [sys.executable,'-B','d-i/forky/tests/audit_codebase.py','--output',str(output/'audit.json')],120),
    ]
    results=[]
    for name,command,timeout in stages:
        print(f'[{name}] running; log: {output/name}.log',flush=True)
        start=time.monotonic()
        log=output/(name+'.log')
        timed_out=False
        with log.open('w') as stream:
            process=subprocess.Popen(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                status=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True
                os.killpg(process.pid,signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL)
                    process.wait()
                status=124
        record={'stage':name,'returncode':status,'timed_out':timed_out,
                'seconds':round(time.monotonic()-start,3),'log':log.name}
        if name=='tests':
            text=log.read_text()
            record['tests_run'], record['skipped'] = unittest_counts(text)
        results.append(record)
        print(f'[{name}] {"PASS" if status==0 else "FAIL"} ({status})',flush=True)
    audit={}
    if (output/'audit.json').is_file():
        audit=json.loads((output/'audit.json').read_text())
    report={'repository':ROOT.name,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'stages':results,'success':all(r['returncode']==0 for r in results),
            'audit_check_counts':audit.get('check_counts',{}),
            'runtime_product_sha256':{name:hashlib.sha256((ROOT/'d-i/forky'/name).read_bytes()).hexdigest()
                                     for name in ('preseed.cfg','payload.manifest','payload.tar.gz')},
            'limits':['Offline/loopback checks, not a booted Debian installer.',
                      'Systemd unit checks are lexical structure only.',
                      'Blocked dependencies, inventory-only files and unrendered templates are not passing runtime tests.',
                      'No package availability, partitioning, hardware, Secure Boot or service activation acceptance test was performed.',
                      'Browser export coverage is static, not live site testing or GUI import acceptance.']}
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Summary: '+str(output/'summary.json'),flush=True)
    return 0 if report['success'] else 1

if __name__=='__main__':
    raise SystemExit(main())
