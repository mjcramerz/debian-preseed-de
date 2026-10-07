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

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
# PYTHONSAFEPATH deliberately removes the script directory from sys.path.
# Import only this trusted sibling directory so aggregate validation remains
# deterministic without re-enabling the current working directory.
sys.path.insert(0, str(TOOLS))
from check_shells import preseed_commands

SEED=ROOT/'d-i/forky'


def readback_commands(path: Path, env: dict[str, str]) -> dict[str, str]:
    """Round-trip real generated values through an explicitly private database."""
    if not env.get('DEBCONF_SYSTEMRC'):
        raise ValueError('a private DEBCONF_SYSTEMRC is mandatory')
    original = preseed_commands(path)
    subprocess.run(['debconf-set-selections', str(path)], env=env,
                   capture_output=True, text=True, check=True, timeout=30)
    result = subprocess.run(['debconf-communicate', 'installer-bootstrap-test'],
                            input=''.join('GET ' + key + '\n' for key in original),
                            env=env, capture_output=True, text=True, check=True, timeout=30)
    lines = result.stdout.splitlines()
    if len(lines) != len(original):
        raise ValueError('debconf did not return all generated commands')
    readback = {}
    for (key, expected), line in zip(original.items(), lines):
        if not line.startswith('0 ') or line[2:] != expected:
            raise ValueError(f'debconf changed the generated shell value: {key}')
        readback[key] = line[2:]
    return readback

def main() -> int:
    checker=shutil.which('debconf-set-selections')
    if not checker or not shutil.which('debconf-communicate'):
        print('debconf-set-selections and debconf-communicate are required for the preseed format check',file=sys.stderr)
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
        if result.returncode == 0:
            try:
                readback_commands(SEED / 'preseed.cfg', env)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print('preseed command round-trip failed: ' + str(error), file=sys.stderr)
                return 1
            print('All four generated command values survived private debconf read-back unchanged')
        print(f'{len(paths)} preseed files checked; '+('PASS' if result.returncode==0 else 'FAIL'))
        return 0 if result.returncode==0 else 1

if __name__=='__main__':
    raise SystemExit(main())
