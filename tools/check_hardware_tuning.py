#!/usr/bin/env python3
"""Offline verification of generated tuning units and AppArmor policies.

Run only against a trusted checkout, as root (the target publisher verifies
root ownership). This never starts units, loads AppArmor into the kernel or
writes hardware. All installed paths are inside disposable fixture roots.
Unit executable lines are replaced ONLY in the fixtures; this checks settings
and dependency parsing, not executable operation or live systemd semantics.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from check_logging import load_logging, render_logging
from check_themes import load_themes, render_text as render_theme

ROOT = Path(__file__).resolve().parents[1]
FORKY = ROOT / 'd-i/forky'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT / '.build/validation/hardware-tuning')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('fixture publishing requires root; no target services are started')
    for executable in ('systemd-analyze', 'apparmor_parser'):
        if shutil.which(executable) is None:
            parser.error(f'{executable} is required')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(FORKY / 'hooks/target/usr/local/lib/hardware_tuning'))
    spec = importlib.util.spec_from_file_location(
        'hardware_install', FORKY / 'scripts/desktop/hardware-tuning-config.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('hardware installer module cannot be loaded')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    environment = module.parse_environment('\n'.join(
        line for line in (FORKY / 'hosts/profiles/btrfs-de-p15s.env').read_text().splitlines()
        if line.startswith('HARDWARE_')))
    results = []
    with tempfile.TemporaryDirectory(prefix='tuning-units-', dir=Path.home()) as temporary:
        root = Path(temporary)
        for vendors in (['intel'], ['nvidia'], ['intel', 'nvidia']):
            stage = root / '-'.join(vendors)
            stage.mkdir()
            waybar = stage / 'etc/skel-desktop/.config/waybar/config'
            waybar.parent.mkdir(parents=True)
            waybar.write_text('[{"name":"internal","battery":{"on-click":"preserved"}},'
                              '{"name":"external","battery":{"on-click":"preserved"}}]')
            module.install(stage, 1000, 1000, environment, vendors, FORKY / "hooks/target")
            for scope in ('system', 'user'):
                directory = stage / 'etc/systemd' / scope
                for path in directory.glob('*.service'):
                    lines = []
                    for line in path.read_text().splitlines():
                        key = line.partition('=')[0]
                        if key in {'ExecStart', 'ExecStop', 'ExecStopPost'}:
                            line = key + '=/usr/bin/true'
                        lines.append(line)
                    path.write_text('\n'.join(lines) + '\n')
                if scope == 'user':
                    (directory / 'labwc-session.target').write_text(
                        '[Unit]\nDescription=Fixture Labwc session\n')
                    for name in ('labwc-native-vivaldi-stable-fixture.service',
                                 'labwc-native-chromium-fixture.service',
                                 'labwc-native-microsoft-edge-fixture.service',
                                 'labwc-wayland-fixture.service',
                                 'labwc-electron-fixture.service',
                                 'labwc-devops-fixture.service'):
                        (directory / name).write_text(
                            '[Unit]\nDescription=Fixture application\n'
                            '[Service]\nExecStart=/usr/bin/true\n')
                else:
                    (directory / 'apparmor.service').write_text(
                        '[Unit]\nDescription=Fixture AppArmor dependency\n'
                        '[Service]\nType=oneshot\nExecStart=/usr/bin/true\n')
                command = ['systemd-analyze', '--man=no']
                if scope == 'user':
                    command.append('--user')
                command += ['verify'] + [str(path) for path in sorted(directory.iterdir())
                                         if path.is_file()]
                runtime = stage / 'runtime'
                runtime.mkdir(mode=0o700, exist_ok=True)
                child_environment = dict(os.environ,
                    SYSTEMD_UNIT_PATH=f'{directory}:/usr/lib/systemd/{scope}',
                    XDG_RUNTIME_DIR=str(runtime), SYSTEMD_LOG_LEVEL='warning')
                run = subprocess.run(command, capture_output=True, text=True,
                                     env=child_environment, timeout=25)
                label = '-'.join(vendors) + '-' + scope
                log = 'units-' + label + '.log'
                (output / log).write_text(run.stdout + run.stderr)
                results.append({'check': 'systemd-verify', 'vendors': vendors,
                    'scope': scope, 'returncode': run.returncode, 'log': log,
                    'fixture_executables': True})
            apparmor = stage / 'apparmor.d'
            shutil.copytree('/etc/apparmor.d', apparmor)
            shutil.copytree(FORKY / 'hooks/target/etc/apparmor.d', apparmor,
                            dirs_exist_ok=True)
            logging_values = load_logging(FORKY)
            theme_values = load_themes()
            for template in apparmor.rglob('*.tmpl'):
                destination = template.with_name(template.name[:-5])
                destination.write_text(render_theme(
                    render_logging(template.read_text(), logging_values), theme_values))
                shutil.copymode(template, destination)
                template.unlink()
            for vendor in ('intel', 'nvidia'):
                if vendor not in vendors:
                    (apparmor / 'abstractions' /
                     ('hardware-tuning-' + vendor)).unlink()
            command = ['apparmor_parser', '-Q', '-K', '-I', str(apparmor)]
            command += [str(apparmor / name) for name in
                        ('hardware-tuning', 'desktop-wrappers',
                         'desktop-utilities')]
            run = subprocess.run(command, capture_output=True, text=True, timeout=35)
            log = 'apparmor-' + '-'.join(vendors) + '.log'
            (output / log).write_text(run.stdout + run.stderr)
            results.append({'check': 'apparmor-parse', 'vendors': vendors,
                'returncode': run.returncode, 'log': log, 'kernel_load': False})
    report = {
        'systemd_version': subprocess.check_output(
            ['systemd-analyze', '--version'], text=True).splitlines()[0],
        'checks': results,
        'success': all(result['returncode'] == 0 for result in results),
        'limits': [
            'Offline parser/dependency checks with fixture executables and '
            'session/AppArmor dependencies; no target units started.',
            'AppArmor policies compiled without kernel loading; '
            'on-target enforcement remains required.'],
    }
    (output / 'generated-integration.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
