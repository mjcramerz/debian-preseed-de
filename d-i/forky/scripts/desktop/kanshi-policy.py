#!/usr/bin/python3 -I
"""Installer-only opt-in Kanshi reconciliation. Never run in a live desktop.

Only the named Debian package and byte-identical installer-owned activation
files are removed. Administrator changes fail closed. Inert user display
profiles are retained, not erased. The caller removes this helper after use.
"""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import stat
import signal
import subprocess
import sys

# Exact known managed assets; no regex/content-marker ownership guesses.
KNOWN = {
    'kanshi.service': {'4e8bc3c6657947ed78eb850f517bcbf6aef3196b37cd6a1e360509b8f6f7b88b'},
    '60-resource-class.conf': {'72f14f2f8d8f2ca33c751eedc1631c3d9013c52a4f3156424e0559b260efeee8'},
    'labwc-kanshi': {'58e9109521808650b8fc896a69f2ec783ae11f84db7cd3ca62b2cf5265a210f8',
                    '264939767fa436eef61ad5f8c2f822fca19fef5ca89dcff74ee47055da371e3b'},
}
WRAPPER = Path('/usr/local/libexec/labwc-kanshi')
EXECUTABLES = tuple(Path(p) for p in ('/usr/local/bin/kanshi', '/usr/bin/kanshi', '/bin/kanshi'))
ENV = {'HOME': '/root', 'PATH': '/usr/sbin:/usr/bin:/sbin:/bin',
       'LC_ALL': 'C', 'DEBIAN_FRONTEND': 'noninteractive'}


def safe_path(path: Path) -> None:
    for parent in reversed(path.parents):
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError(f'unsafe Kanshi policy parent: {parent}')


def unit_roots(home: Path) -> tuple[Path, ...]:
    return (Path('/etc/systemd/user'), Path('/etc/skel-desktop/.config/systemd/user'),
            home / '.config/systemd/user')


def cleanup_plan(home: Path) -> list[tuple[Path, str]]:
    plan = []
    for base in unit_roots(home):
        safe_path(base / '.policy-check')
        if not base.exists():
            continue
        dropins = base / 'kanshi.service.d'
        safe_path(dropins / '.policy-check')
        if dropins.exists() and any(p.name != '60-resource-class.conf' for p in dropins.iterdir()):
            raise ValueError(f'unmanaged Kanshi drop-ins preserved: {dropins}')
        for path in (base / 'kanshi.service', dropins / '60-resource-class.conf'):
            check_file(path, plan)
        for directory in sorted(base.iterdir()):
            if not directory.name.endswith(('.wants', '.requires')):
                continue
            safe_path(directory / 'kanshi.service')
            link = directory / 'kanshi.service'
            if not link.exists() and not link.is_symlink():
                continue
            allowed = {'../kanshi.service', str(base / 'kanshi.service'),
                       '/usr/lib/systemd/user/kanshi.service', '/lib/systemd/user/kanshi.service'}
            if not link.is_symlink() or os.readlink(link) not in allowed:
                raise ValueError(f'unmanaged Kanshi activation preserved: {link}')
            plan.append((link, 'link:' + os.readlink(link)))
    check_file(WRAPPER, plan)
    return plan


def check_file(path: Path, plan: list[tuple[Path, str]]) -> None:
    safe_path(path)
    if not path.exists() and not path.is_symlink():
        return
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f'unmanaged Kanshi file preserved: {path}')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest not in KNOWN[path.name]:
        raise ValueError(f'modified Kanshi file preserved: {path}')
    plan.append((path, digest))


def command(argv: list[str], *, check: bool = True, capture: bool = False,
            timeout: float = 600) -> subprocess.CompletedProcess[str]:
    # Own the process group: an interrupted installer must not leave apt/dpkg
    # descendants mutating the target after the caller has reported failure.
    def interrupted(number, _frame):
        raise InterruptedError(f"Kanshi command interrupted by signal {number}")

    handlers = {sig: signal.signal(sig, interrupted)
                for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    child = None
    try:
        child = subprocess.Popen(argv, env=ENV, text=True, start_new_session=True,
                                 stdout=subprocess.PIPE if capture else None,
                                 stderr=subprocess.PIPE if capture else None)
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except BaseException:
            # Ignore a second termination while reaping our group.
            for sig in handlers:
                signal.signal(sig, signal.SIG_IGN)
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            finally:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.communicate()
            raise
        result = subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def package_state() -> str:
    result = command(['/usr/bin/dpkg-query', '-W', '-f=${db:Status-Status}', 'kanshi'],
                     check=False, capture=True)
    if result.returncode == 1:
        return 'not-installed'
    if result.returncode:
        raise RuntimeError('cannot inspect Kanshi package state: ' + result.stderr)
    return result.stdout.strip()


def reconcile(enabled: bool, home: Path) -> None:
    if enabled:
        command(['/usr/bin/apt-get', '-q', '-y', '-o', 'DPkg::Lock::Timeout=120',
                 '-o', 'Acquire::Retries=2', '-o', 'Acquire::http::Timeout=30',
                 '-o', 'Acquire::https::Timeout=30',
                 '-o', 'Acquire::AllowInsecureRepositories=false',
                 '-o', 'Acquire::AllowDowngradeToInsecureRepositories=false',
                 '-o', 'APT::Get::AllowUnauthenticated=false',
                 '--no-install-recommends', '--no-install-suggests', '--no-remove',
                 'install', 'kanshi'])
        if package_state() != 'installed':
            raise RuntimeError('enabled Kanshi package is not installed')
        # Only the account-local managed session should activate this daemon.
        if any(Path(p).is_file() for p in ('/usr/lib/systemd/user/kanshi.service',
                                          '/lib/systemd/user/kanshi.service')):
            command(['/usr/bin/systemctl', '--global', 'disable', 'kanshi.service'])
        return

    plan = cleanup_plan(home)  # Validate ALL ownership before any mutation.
    if package_state() != 'not-installed':
        # dpkg refuses unmet reverse dependencies; never force them or remove
        # unrelated packages using an automatic dependency solver/autoremove.
        command(['/usr/bin/dpkg', '--purge', 'kanshi'])
    if package_state() != 'not-installed':
        raise RuntimeError('disabled Kanshi package is still present')
    for path, expected in plan:
        safe_path(path)
        if not path.exists() and not path.is_symlink():
            continue
        if expected.startswith('link:'):
            current = 'link:' + os.readlink(path) if path.is_symlink() else ''
        else:
            current = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else ''
        if current != expected:
            raise RuntimeError(f'Kanshi asset changed during installer cleanup: {path}')
        path.unlink()
    for base in unit_roots(home):
        dropins = base / 'kanshi.service.d'
        if dropins.is_dir():
            dropins.rmdir()  # Only empty directories, never recursive removal.
    for path in EXECUTABLES:
        if os.path.lexists(path):
            raise RuntimeError(f'unmanaged disabled Kanshi executable preserved: {path}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enabled', required=True, choices=('true', 'false'))
    parser.add_argument('--home', required=True)
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise ValueError('Kanshi package policy must run as installer root')
    home = Path(args.home)
    if not home.is_absolute() or home == Path('/') or str(home) != args.home or '..' in home.parts:
        raise ValueError('account home must be a normalized absolute non-root path')
    safe_path(home / '.policy-check')
    reconcile(args.enabled == 'true', home)
    print('kanshi_policy enabled=' + args.enabled)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'fatal: Kanshi policy: {exc}', file=sys.stderr)
        raise SystemExit(1)
