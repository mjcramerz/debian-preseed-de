#!/usr/bin/env python3
"""Check preseed format with a private disposable debconf database.

Target .cfg and class metadata are not debconf selections; build/audit validate
those instead. No host debconf database is opened, locked or changed.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
SEED=ROOT/'d-i/forky'

def main() -> int:
    checker=shutil.which('debconf-set-selections')
    if not checker:
        print('debconf-set-selections is required for the preseed format check',file=sys.stderr)
        return 1
    paths=[SEED/'preseed.cfg',SEED/'common.cfg',*sorted((SEED/'fragments').glob('*.cfg'))]
    for directory in sorted((SEED/'classes').glob('class-*')):
        if directory.is_dir():
            paths.extend(sorted(directory.rglob('*.cfg')))
    with tempfile.TemporaryDirectory(prefix='preseed-format-') as temp:
        base=Path(temp); conf=base/'debconf.conf'
        conf.write_text('Config: check_config\nTemplates: check_templates\n\n'
                        'Name: check_config\nDriver: File\nMode: 600\n'
                        f'Filename: {base/"config.dat"}\n\n'
                        'Name: check_templates\nDriver: File\nMode: 600\n'
                        f'Filename: {base/"templates.dat"}\n')
        env={**os.environ,'DEBCONF_SYSTEMRC':str(conf),'DEBIAN_FRONTEND':'noninteractive'}
        for key in ('DEBCONF_DB_REPLACE','DEBCONF_DB_FALLBACK','DEBCONF_DB_OVERRIDE'):
            env.pop(key,None)
        result=subprocess.run([checker,'--checkonly',*map(str,paths)],
                              capture_output=True,text=True,env=env,timeout=30)
        if result.returncode:
            print(f'preseed check exited {result.returncode}:\n'+result.stdout+result.stderr,file=sys.stderr)
        print(f'{len(paths)} preseed files checked; '+('PASS' if result.returncode==0 else 'FAIL'))
        return 0 if result.returncode==0 else 1

if __name__=='__main__':
    raise SystemExit(main())
