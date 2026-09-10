#!/usr/bin/python3 -I
"""Post-install acceptance probe. Read-only unless --exercise is explicitly used.

Run as the authorized desktop user, never root. Exercise pulls an explicitly
approved immutable image and creates/removes only uniquely named test objects.
It does not test reboot, installer boot, or the complete Incus VM lifecycle.
"""
from __future__ import annotations
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import re
import signal
import stat
import subprocess
import sys
import tempfile
import uuid

PODMAN = '/usr/local/bin/podman'
DOCKER = '/usr/local/bin/docker'
RUNTIME = Path('/run/podman-devops')
SOCKET = RUNTIME / 'podman.sock'
POOL = Path('/pool/podman')
CONFIG = Path('/etc/podman-devops')
SERVER_CONFIG = CONFIG / 'server/containers'
LABEL = 'io.managed.podman.acceptance'


def run(argv: list[str], timeout: int = 120) -> str:
    process = subprocess.Popen(argv, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = process.communicate(timeout=timeout)
    except BaseException:
        # A reaped leader does not mean that its descendants closed our pipes.
        for sig, grace in ((signal.SIGTERM, 3), (signal.SIGKILL, 2)):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
        else:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        raise
    if process.returncode:
        raise RuntimeError(f'{argv[0]} {argv[1:3]}: exit {process.returncode}: {err.strip()[-2000:]}')
    return out.strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)
    print('PASS: ' + message, flush=True)


def unit_state(unit: str) -> dict[str, str]:
    output = run([
        '/usr/bin/systemctl', 'show', '--property=ActiveState',
        '--property=SubState', '--property=Result', '--property=ExecMainStatus', unit,
    ])
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def readonly(require_incus: bool) -> None:
    require(os.geteuid() != 0, 'probe runs without root or sudo')
    user, group = pwd.getpwnam('devops'), grp.getgrnam('devops')
    require(0 < user.pw_uid < 1000 and user.pw_gid == group.gr_gid and
            user.pw_dir == '/nonexistent' and
            user.pw_shell == '/usr/sbin/nologin',
            'devops is a non-root system account with no home and nologin')
    require(set(os.getgrouplist('devops', user.pw_gid)) == {group.gr_gid},
            'devops has only its primary group and no supplementary groups')
    require(group.gr_gid in {*os.getgroups(), os.getegid()},
            'desktop session has the trusted devops operator group')
    for forbidden in (Path('/nonexistent'), Path('/data/accounts/devops')):
        require(not forbidden.exists() and not forbidden.is_symlink(),
                f'devops has no home-shaped filesystem state: {forbidden}')
    config_metadata = CONFIG.lstat()
    require(stat.S_ISDIR(config_metadata.st_mode) and config_metadata.st_uid == 0 and
            config_metadata.st_gid == group.gr_gid and
            stat.S_IMODE(config_metadata.st_mode) == 0o750,
            'service configuration root is root:devops mode 0750')
    for name in ('containers.conf', 'storage.conf', 'registries.conf'):
        path = SERVER_CONFIG / name
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0 and
                metadata.st_gid == group.gr_gid and stat.S_IMODE(metadata.st_mode) == 0o640,
                f'root-owned server configuration is immutable to devops: {name}')
    linger = Path('/var/lib/systemd/linger/devops')
    require(not linger.exists() and not linger.is_symlink(),
            'devops has no linger state')
    manager = subprocess.run(
        ['/usr/bin/systemctl', 'is-active', '--quiet', f'user@{user.pw_uid}.service'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=10,
    )
    require(manager.returncode != 0, 'devops has no systemd user manager')
    runtime_user = Path('/run/user') / str(user.pw_uid)
    for relative in ('bus', 'systemd'):
        forbidden = runtime_user / relative
        require(not forbidden.exists() and not forbidden.is_symlink(),
                f'devops has no runtime user-manager state: {relative}')
    bootstrap = unit_state('podman-devops-bootstrap.service')
    require(bootstrap.get('ActiveState') == 'active' and
            bootstrap.get('SubState') == 'exited' and
            bootstrap.get('Result') == 'success' and
            bootstrap.get('ExecMainStatus') == '0',
            'bootstrap completed the privileged service-account and engine checks')
    socket_state = unit_state('podman-devops.socket')
    require(socket_state.get('ActiveState') == 'active' and
            socket_state.get('SubState') == 'listening' and
            socket_state.get('Result') == 'success',
            'system-level Podman socket is active and listening')
    api = unit_state('podman-devops.service')
    require(api.get('ActiveState') == 'active' and
            api.get('SubState') == 'running' and api.get('Result') == 'success',
            'system-level Podman API runs as the service account')
    restart = unit_state('podman-devops-restart.service')
    require(restart.get('ActiveState') == 'active' and
            restart.get('SubState') == 'exited' and
            restart.get('Result') == 'success' and
            restart.get('ExecMainStatus') == '0',
            'persistent-container restart policy completed successfully')
    runtime_metadata = RUNTIME.lstat()
    require(stat.S_ISDIR(runtime_metadata.st_mode) and
            runtime_metadata.st_uid == user.pw_uid and
            runtime_metadata.st_gid == group.gr_gid and
            stat.S_IMODE(runtime_metadata.st_mode) == 0o710,
            'service runtime is devops:devops mode 0710 outside /run/user')
    metadata = SOCKET.lstat()
    require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == user.pw_uid and
            metadata.st_gid == group.gr_gid and stat.S_IMODE(metadata.st_mode) == 0o660,
            'live API socket has expected owner/group/mode')
    info = json.loads(run([PODMAN, 'info', '--format=json']))
    host, store = info['host'], info['store']
    require(host['security']['rootless'] is True, 'actual API engine is rootless')
    require(host['cgroupVersion'] == 'v2' and host['cgroupManager'] == 'cgroupfs',
            'actual engine uses delegated cgroupfs on cgroup v2')
    require(store['graphRoot'] == '/pool/podman/storage' and
            store['volumePath'] == '/pool/podman/volumes',
            'actual storage and volume paths are under the pool')
    require(host['networkBackend'] == 'netavark', 'actual network backend is Netavark')
    pool_root = Path('/pool').lstat()
    require(stat.S_ISDIR(pool_root.st_mode) and pool_root.st_uid == 0 and
            pool_root.st_gid == group.gr_gid and stat.S_IMODE(pool_root.st_mode) == 0o3775,
            'shared pool root is root:devops mode 3775')
    for leaf in ('xdg-data', 'xdg-cache'):
        metadata = (POOL / leaf).lstat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == user.pw_uid and
                metadata.st_gid == group.gr_gid and stat.S_IMODE(metadata.st_mode) == 0o700,
                f'non-home Podman {leaf} state is private to devops')
    print('Docker version:\n' + run([DOCKER, 'version']))
    print('Compose version: ' + run([DOCKER, 'compose', 'version']))
    run([PODMAN, 'ps', '--all'])
    run([DOCKER, 'ps', '--all'])
    for unit in ('podman.service', 'podman.socket', 'docker.service', 'docker.socket'):
        path = Path('/etc/systemd/system') / unit
        require(path.is_symlink() and os.readlink(path) == '/dev/null',
                f'rootful {unit} is masked')
    if Path('/usr/bin/incus').is_file():
        require(grp.getgrnam('incus-admin').gr_gid not in {*os.getgroups(), os.getegid()},
                'desktop does not have the Incus administrator group')
        run(['/usr/bin/incus', 'info'])
        print('PASS: confined Incus client can query its local endpoint')
    elif require_incus:
        raise RuntimeError('Incus was required but is not installed')
    else:
        print('SKIP: Incus addon is not installed')


def exercise(image: str) -> None:
    token = uuid.uuid4().hex[:20]
    name, tag = 'managed-smoke-' + token, 'localhost/managed-smoke:' + token
    created = []
    cleanup_errors = []
    compose = None
    scratch = tempfile.TemporaryDirectory(prefix='managed-container-smoke-')
    base = Path(scratch.name)
    try:
        run([PODMAN, 'pull', image], 900)
        run([PODMAN, 'volume', 'create', '--label', LABEL + '=' + token, name]); created.append(('volume', name))
        run([PODMAN, 'network', 'create', '--label', LABEL + '=' + token, name]); created.append(('network', name))
        run([PODMAN, 'run', '--detach', '--name', name, '--label', LABEL + '=' + token,
             '--network', name, '--volume', name + ':/smoke-data', '--restart=unless-stopped',
             image, '/bin/sh', '-c', 'while :; do sleep 60; done'])
        created.append(('container', name))
        run([PODMAN, 'exec', name, '/bin/sh', '-c', 'printf acceptance > /smoke-data/probe'])
        require(run([DOCKER, 'exec', name, '/bin/sh', '-c', 'cat /smoke-data/probe']) == 'acceptance',
                'Podman and Docker operate on the same container and named volume')
        run([PODMAN, 'stop', '--time', '5', name]); run([DOCKER, 'start', name])
        (base / 'Containerfile').write_text('FROM ' + image + '\nRUN printf built > /managed-smoke\n')
        run([PODMAN, 'build', '--label', LABEL + '=' + token, '--tag', tag, str(base)], 900)
        created.append(('image', tag))
        require(run([DOCKER, 'run', '--rm', tag, '/bin/sh', '-c', 'cat /managed-smoke']) == 'built',
                'remote Podman build uploads a local context and Docker runs its result')
        document = {'services': {'probe': {'image': tag, 'labels': {LABEL: token},
                    'command': ['/bin/sh', '-c', 'while :; do sleep 60; done']}}}
        filename = base / 'compose.json'; filename.write_text(json.dumps(document))
        compose = [DOCKER, 'compose', '--project-name', name, '--file', str(filename)]
        run(compose + ['up', '--detach'], 180)
        require(bool(run(compose + ['ps', '--quiet'])), 'Docker Compose deploys to the shared rootless engine')
    finally:
        if compose is not None:
            try:
                run(compose + ['down', '--timeout', '5'], 90)
            except Exception as exc:
                cleanup_errors.append(str(exc))
        for kind, resource in reversed(created):
            try:
                if kind == 'container':
                    run([PODMAN, 'rm', '--force', resource])
                else:
                    run([PODMAN, kind, 'rm', resource])
            except Exception as exc:
                cleanup_errors.append(str(exc))
        scratch.cleanup()
        if cleanup_errors:
            print('CLEANUP FAILURE; inspect only test prefix ' + name, file=sys.stderr)
            for error in cleanup_errors:
                print(error, file=sys.stderr)
            raise RuntimeError('acceptance cleanup was incomplete')
        print('PASS: temporary test objects removed; pulled base image intentionally retained')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-incus', action='store_true')
    parser.add_argument('--exercise', action='store_true')
    parser.add_argument('--image', help='approved fully qualified image@sha256:digest, containing /bin/sh and basic tools')
    args = parser.parse_args()
    if args.exercise and (not args.image or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]*/[A-Za-z0-9_./:-]+@sha256:[a-fA-F0-9]{64}', args.image)):
        parser.error('--exercise requires an approved fully qualified --image pinned by sha256 digest')
    if args.image and not args.exercise:
        parser.error('--image is only used with --exercise')
    readonly(args.require_incus)
    if args.exercise:
        exercise(args.image)
    return 0


if __name__ == '__main__':
    for number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, lambda sig, _frame: sys.exit(128 + sig))
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        sys.exit(1)
