#!/usr/bin/env python3
"""Run non-destructive repository validation in a disposable Linux environment.

Perl -c can execute BEGIN blocks: validate only a trusted source tree. This does
not boot d-i, start target services, partition disks or install packages.
"""
from __future__ import annotations

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[1] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tempfile

from stage_process import CleanupUnknown, run_stage

ROOT = Path(__file__).resolve().parents[1]
VALIDATION_PATH = '/usr/sbin:/usr/bin:/sbin:/bin'


def validation_environment() -> dict[str, str]:
    return {'PATH': VALIDATION_PATH, 'HOME': os.environ['HOME'],
            'TMPDIR': '/tmp', 'LC_ALL': 'C.UTF-8', 'LANG': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1'}


def resolve_python_interpreter() -> str:
    candidate = sys.executable or shutil.which('python3')
    if not candidate:
        raise ValueError('repository validation requires a Python 3 interpreter')
    path = Path(candidate)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f'unsafe Python interpreter path: {candidate!r}')
    return str(path)

def unittest_counts(text: str) -> tuple[int | None, int]:
    run_match = re.search(r'Ran (\d+) tests? in ', text)
    result_match = re.search(r'^(?:OK|FAILED)(?: \(([^)]*)\))?$', text, re.M)
    result_fields = result_match.group(1) if result_match and result_match.group(1) else ''
    skipped_match = re.search(r'(?:^|, )skipped=(\d+)(?:,|$)', result_fields)
    return (int(run_match.group(1)) if run_match else None,
            int(skipped_match.group(1)) if skipped_match else 0)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'.build/validation')
    parser.add_argument('--test-timeout', type=int, default=900,
                        help='positive per-suite timeout in seconds (default: 900)')
    args = parser.parse_args()
    if args.test_timeout < 1:
        parser.error('--test-timeout must be a positive integer')
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT):
        parser.error('--output-dir must stay inside the private checkout')
    output.mkdir(parents=True,exist_ok=True)
    # Every report belongs to one fresh run. Never consume a prior audit.json
    # after an interrupted or failed current audit stage.
    output = Path(tempfile.mkdtemp(prefix='run-', dir=output))
    interpreter = resolve_python_interpreter()
    stages = [
        ('browser-check', [interpreter,'-B','tools/check_browser_policies.py'],30),
        ('build-check', [interpreter,'-B','tools/check_build.py'],90),
        ('preseed-check', [interpreter,'-B','tools/check_preseeds.py'],90),
        ('shell-check', [interpreter,'-B','tools/check_shells.py','--output',str(output/'shell-check.json')],120),
        ('tests', [interpreter,'-B','-m','unittest','discover','-v','-s','d-i/forky/tests','-p','test_*.py'],args.test_timeout),
        ('tools-tests', [interpreter,'-B','-m','unittest','discover','-v','-s','tools/tests','-p','test_*.py'],args.test_timeout),
        ('audit', [interpreter,'-B','d-i/forky/tests/audit_codebase.py','--output',str(output/'audit.json')],120),
    ]
    child_environment = validation_environment()
    results=[]
    for name,command,timeout in stages:
        print(f'[{name}] running; log: {output/name}.log',flush=True)
        start=time.monotonic()
        log=output/(name+'.log')
        timed_out=False
        with log.open('w') as stream:
            try:
                result = run_stage(command, cwd=ROOT, env=child_environment,
                                   stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            except CleanupUnknown as error:
                print('Validation outcome unknown; evidence retained at ' + str(output), flush=True)
                stream.write(str(error) + '\n')
                return 75
            status, timed_out = result.returncode, result.timed_out
        record={'stage':name,'returncode':status,'timed_out':timed_out,
                'seconds':round(time.monotonic()-start,3),'log':log.name}
        if name in ('tests', 'tools-tests'):
            text=log.read_text()
            record['tests_run'], record['skipped'] = unittest_counts(text)
        results.append(record)
        print(f'[{name}] {"PASS" if status==0 else "FAIL"} ({status})',flush=True)
        if result.cancelled is not None:
            break
    audit={}
    if (output/'audit.json').is_file():
        audit=json.loads((output/'audit.json').read_text())
    report={'repository':ROOT.name,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'stages':results,'not_run':[name for name, _, _ in stages[len(results):]],
            'success':len(results)==len(stages) and all(r['returncode']==0 for r in results),
            'audit_check_counts':audit.get('check_counts',{}),
            'runtime_product_sha256':{name:hashlib.sha256((ROOT/'d-i/forky'/name).read_bytes()).hexdigest()
                                     for name in ('preseed.cfg','payload.manifest','payload.tar.gz')},
            'limits':['Offline/loopback checks, not a booted Debian installer.',
                      'Systemd unit checks are lexical structure only.',
                      'Blocked dependencies, inventory-only files and unrendered templates are not passing runtime tests.',
                      'No package availability, partitioning, hardware, Secure Boot or service activation acceptance test was performed.',
                      'Browser policy checks are static; live extension installation and GUI import acceptance were not performed.']}
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Summary: '+str(output/'summary.json'),flush=True)
    return 0 if report['success'] else 1

if __name__=='__main__':
    raise SystemExit(main())
