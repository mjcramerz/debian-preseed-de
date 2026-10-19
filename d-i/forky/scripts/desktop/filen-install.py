#!/usr/bin/python3 -I
"""Offline target installation of the pinned CLI and two independent services.

Downloads are data until their digest and ELF architecture are verified. This
program runs only inside the installer target; it never logs in or starts units.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import grp
import json
import os
from pathlib import Path
import pwd
import re
import stat
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/nonexistent',
       'LC_ALL': 'C.UTF-8', 'SYSTEMD_OFFLINE': '1'}
MODES = {'twoWay', 'localToCloud', 'cloudToLocal', 'localBackup', 'cloudBackup'}


class Error(ValueError):
    """Fixed, non-secret policy diagnostic suitable for installation logs."""


def directory(path: Path, mode: int = 0o755) -> None:
    if path == Path('/'):
        return
    directory(path.parent)
    try:
        info = path.lstat()
    except FileNotFoundError:
        # Create privately, then set the requested mode on the pinned directory.
        # d-i may keep umask 077; it must not hide public Perl/config parents.
        path.mkdir(mode=0o700)
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if os.fstat(descriptor).st_uid != 0:
                raise Error('untrusted installation directory')
            os.fchown(descriptor, 0, 0)
            os.fchmod(descriptor, mode)
            info = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    private_stage_parent = path == Path('/tmp') and stat.S_IMODE(info.st_mode) == 0o1777
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or (info.st_mode & 0o022 and not private_stage_parent)):
        raise Error('untrusted installation directory')


def read(path: Path, maximum: int = 262144, *, private: bool = False) -> bytes:
    directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                or info.st_nlink != 1 or info.st_mode & (0o077 if private else 0o022)):
            raise Error('untrusted installation input')
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise Error('installation input exceeds limit')
    return data


def publish(path: Path, data: bytes, mode: int = 0o644) -> None:
    directory(path.parent)
    if path.exists() or path.is_symlink():
        read(path, maximum=201326592)  # Refuse links or untrusted existing code.
    fd, name = tempfile.mkstemp(prefix='.filen-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), 0, 0)
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(name).unlink(missing_ok=True)


def command(argv: list[str], *, identity: pwd.struct_passwd | None = None) -> bytes:
    credentials = ({'user': identity.pw_uid, 'group': identity.pw_gid, 'extra_groups': []}
                   if identity is not None else {})
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=ENV, timeout=30, check=True, **credentials)
    return result.stdout


def sync_tree(local: Path, identity, desktop_uid: int) -> None:
    directory(local.parent)
    if local.exists() or local.is_symlink():
        info = local.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != identity.pw_uid or info.st_gid != identity.pw_gid:
            raise Error('existing Filen sync tree has an unexpected owner')
    else:
        local.mkdir(mode=0o700)
        os.chown(local, identity.pw_uid, identity.pw_gid)
    # Both UIDs need default entries: desktop-created children belong to the
    # desktop UID, so the service cannot rely on the directory's owner entry.
    command(['/usr/bin/setfacl', '--set', f'u::rwx,u:{desktop_uid}:rwx,g::---,m::rwx,o::---,'
             f'd:u::rwx,d:u:{desktop_uid}:rwx,d:u:{identity.pw_uid}:rwx,d:g::---,d:m::rwx,d:o::---',
             '--', str(local)])


def path_value(value: str) -> str:
    if (not re.fullmatch(r'/[A-Za-z0-9_./-]{1,1023}', value)
            or any(part in {'', '.', '..'} for part in value[1:].split('/'))):
        raise Error('invalid configured local path')
    return value


def remote_value(value: str) -> str:
    if (not value.startswith('/') or len(value.encode()) > 2048
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or (value != '/' and any(p in {'', '.', '..'} for p in value[1:].split('/')))):
        raise Error('invalid Filen remote directory')
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        return None


def download(url: str, expected: str, maximum: int) -> bytes:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + 300
    for hop in range(5):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in {'github.com', 'release-assets.githubusercontent.com',
                'objects.githubusercontent.com'} or parsed.username or parsed.password or parsed.fragment
                or parsed.port not in (None, 443)):
            raise Error('download redirect violates the release URL policy')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Error('release download deadline exceeded')
        try:
            response = opener.open(urllib.request.Request(url, headers={'User-Agent': 'preseed-filen-installer'}),
                                   timeout=min(15, remaining))
        except urllib.error.HTTPError as error:
            with error:
                location = error.headers.get('Location')
                if error.code not in {301, 302, 303, 307, 308} or not location or hop == 4:
                    raise Error('release download HTTP failure') from None
                url = urllib.parse.urljoin(url, location)
                continue  # Validate the next origin BEFORE making its request.
        with response:
            data = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise Error('release download deadline exceeded')
                block = response.read1(min(65536, maximum + 1 - len(data)))
                if time.monotonic() >= deadline:
                    raise Error('release download deadline exceeded')
                if not block:
                    break
                data.extend(block)
                if len(data) > maximum:
                    raise Error('release download exceeds configured limit')
        if hashlib.sha256(data).hexdigest() != expected:
            raise Error('release SHA-256 mismatch')
        return bytes(data)
    raise Error('release redirect limit exceeded')


def validate_services(identities: dict[str, pwd.struct_passwd]) -> None:
    # Compile as each service UID, with no supplementary groups, before any
    # publication is accepted. Root compilation would conceal unreadable code directories.
    # Native unit/policy acceptance is a separate isolated gate.
    if not read(Path('/usr/bin/getconf')).startswith(b'\x7fELF'):
        raise Error('target libc probe must be a packaged native executable')
    for identity in identities.values():
        command(['/usr/bin/perl', '-T', '-c', '/usr/local/libexec/filen-sync'], identity=identity)
        # The pinned watcher uses this probe before its shell-script fallback.
        # Check target availability as the real account before accepting either
        # unit; this command neither authenticates nor contacts a manager.
        version = command(['/usr/bin/getconf', 'GNU_LIBC_VERSION'], identity=identity)
        if not re.fullmatch(rb'glibc [0-9]+(?:\.[0-9]+)+\n', version):
            raise Error('target libc probe did not identify glibc')
    # Leave both instances disabled. Only an explicit filenmnt request starts
    # synchronization; the static template has no boot enablement target.


def install(stage: Path, env: dict[str, str]) -> None:
    version, architecture = env['FILEN_CLI_VERSION'], env['FILEN_CLI_ARCHITECTURE']
    if not re.fullmatch(r'0\.0\.[0-9]+', version) or architecture not in {'amd64', 'arm64'}:
        raise Error('invalid pinned Filen release or architecture')
    if command(['/usr/bin/dpkg', '--print-architecture']).decode().strip() != architecture:
        raise Error('Filen binary and target architectures differ')
    asset_arch = 'x64' if architecture == 'amd64' else 'arm64'
    url = f'https://github.com/FilenCloudDienste/filen-cli/releases/download/v{version}/filen-cli-v{version}-linux-{asset_arch}'
    sha = env['FILEN_CLI_SHA256']
    if env['FILEN_CLI_URL'] != url or not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise Error('invalid pinned release URL or digest')
    maximum = int(env['FILEN_CLI_MAXIMUM_BYTES'])
    if not 1048576 <= maximum <= 201326592:
        raise Error('invalid release download size bound')
    root = path_value(env['NETWORK_SHARING_ROOT_PATH'])
    home = path_value(env['ACCOUNT_HOME'])
    home_bind = env['NETWORK_SHARING_HOME_BIND_PATH']
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}', home_bind):
        raise Error('invalid sharing home directory')
    desktop = pwd.getpwnam(env['ACCOUNT_USERNAME'])
    if desktop.pw_uid < 1000 or desktop.pw_dir != home:
        raise Error('desktop account identity differs from profile')
    sharing = json.loads(read(Path('/etc/network-sharing/config.json')))
    if (sharing.get('version') != 3 or sharing.get('profile', {}).get('NETWORK_SHARING_ROOT_PATH') != root
            or sharing['profile'].get('NETWORK_SHARING_HOME_BIND_PATH') != home_bind
            or sharing['profile'].get('ACCOUNT_HOME') != home
            or sharing['profile'].get('ACCOUNT_USERNAME') != env['ACCOUNT_USERNAME']):
        raise Error('Filen and installed sharing paths differ')
    accounts = []
    for key, account in (('PRIV', 'private'), ('OFFSEC', 'offsec')):
        enabled = env[f'FILEN_CLI_{key}_ENABLE']
        if enabled not in {'true', 'false'}:
            raise Error('invalid Filen enable flag')
        if enabled == 'false':
            continue
        mode = env[f'FILEN_CLI_{key}_SYNC_MODE']
        if mode not in MODES:
            raise Error('invalid Filen sync mode')
        remote = remote_value(env[f'FILEN_CLI_{key}_REMOTE_PATH'])
        prefix = 'priv' if key == 'PRIV' else 'offsec'
        secrets = {name: read(stage / f'{prefix}-{field}', 8192, private=True)
                   for name, field in (('email', 'email'), ('password', 'password'), ('seed', '2fa_seed'))}
        if any(not value or b'\0' in value or b'\r' in value or b'\n' in value for value in secrets.values()):
            raise Error('Filen credentials must be nonempty single-line values')
        seed = re.sub(rb'[ \t]', b'', secrets['seed']).upper()
        if not re.fullmatch(rb'[A-Z2-7]{16,1024}={0,6}', seed):
            raise Error('Filen TOTP seed must be base32')
        try:
            base64.b32decode(seed + b'=' * (-len(seed) % 8))
        except binascii.Error:
            raise Error('Filen TOTP seed has invalid base32 encoding') from None
        secrets['seed'] = seed
        accounts.append((account, mode, remote, secrets))
    if not accounts:
        return
    # Packaged modules are checked in the target, before publishing or enabling
    # any consumer. No compilation or managed module import occurs here.
    command(['/usr/bin/perl', '-T', '-MMoo', '-MMooX::StrictConstructor', '-MJSON::PP', '-e', 'exit 0'])
    for tool in ('/usr/bin/oathtool', '/usr/bin/setfacl', '/usr/bin/chattr'):
        if not os.access(tool, os.X_OK):
            raise Error('required target package tool is missing')
    binary = download(url, sha, maximum)
    if (binary[:6] != b'\x7fELF\x02\x01' or len(binary) < 64
            or struct.unpack_from('<H', binary, 18)[0] != (62 if architecture == 'amd64' else 183)):
        raise Error('pinned release is not the configured Linux ELF architecture')
    assets = stage / 'assets'
    templates = {name: read(assets / name).decode('utf-8') for name in
                 ('etc/systemd/system/filen-sync@.service.tmpl', 'etc/apparmor.d/filen-sync.tmpl')}
    code = {name: read(assets / name) for name in ('usr/local/libexec/filen-sync',
            'usr/local/lib/perl5/site_perl/filen/FilenSync/Config.pm',
            'usr/local/lib/perl5/site_perl/filen/FilenSync/Daemon.pm')}
    read(Path('/usr/local/lib/perl5/site_perl/runtime/Managed/Process.pm'))
    publish(Path('/usr/local/bin/filen'), binary, 0o755)
    for name, data in code.items():
        publish(Path('/') / name, data, 0o755 if name.endswith('/filen-sync') else 0o644)
    unit = templates['etc/systemd/system/filen-sync@.service.tmpl'].replace('__SHARING_ROOT__', root)
    if '__' in unit:
        raise Error('unresolved Filen service token')
    publish(Path('/etc/systemd/system/filen-sync@.service'), unit.encode())
    identities = {}
    for account, mode, remote, secrets in accounts:
        user = 'filen-' + account
        try:
            identity = pwd.getpwnam(user)
        except KeyError:
            command(['/usr/sbin/useradd', '--system', '--user-group', '--home-dir', '/var/lib/' + user,
                     '--no-create-home', '--shell', '/usr/sbin/nologin', user])
            identity = pwd.getpwnam(user)
        if (not 0 < identity.pw_uid < 1000 or identity.pw_dir != '/var/lib/' + user
                or identity.pw_shell != '/usr/sbin/nologin' or identity.pw_gid == 0
                or pwd.getpwuid(identity.pw_uid).pw_name != user
                or grp.getgrnam(user).gr_gid != identity.pw_gid
                or grp.getgrgid(identity.pw_gid).gr_name != user
                or set(os.getgrouplist(user, identity.pw_gid)) != {identity.pw_gid}):
            raise Error('existing Filen service account has an unexpected identity')
        identities[account] = identity
        # The service owns its own tree; the desktop account receives an ACL.
        # No shared supplementary group grants either daemon the other tree.
        local = Path(root) / user
        sync_tree(local, identity, desktop.pw_uid)
        credential_root = Path('/etc/credstore') / user
        directory(credential_root, 0o700)
        if stat.S_IMODE(credential_root.stat().st_mode) != 0o700:
            raise Error('credential directory must have mode 0700')
        for name, value in secrets.items():
            publish(credential_root / name, value, 0o600)
        registry = [{'local': str(local), 'remote': remote, 'syncMode': mode, 'disableLocalTrash': False, 'excludeDotFiles': False}]
        publish(Path('/etc/filen') / (account + '.sync.json'), (json.dumps(registry, sort_keys=True) + '\n').encode())
        config = {'version': 1, 'account': account, 'local': str(local), 'remote': remote, 'sync_mode': mode}
        publish(Path('/etc/filen') / (account + '.json'), (json.dumps(config, sort_keys=True) + '\n').encode())
        policy = templates['etc/apparmor.d/filen-sync.tmpl'].replace('__ACCOUNT__', account).replace('__SHARING_ROOT__', root)
        if '__' in policy:
            raise Error('unresolved Filen policy token')
        publish(Path('/etc/apparmor.d') / user.replace('filen-', 'filen-sync-'), policy.encode())
        bookmarks = Path('/etc/skel-desktop/.config/gtk-3.0/bookmarks')
        rows = read(bookmarks).decode().splitlines()
        bookmark = f'file://{home}/{home_bind}/{user}'
        if not any(row.split()[0] == bookmark for row in rows if row.strip()):
            rows.append(bookmark + ' ' + user)
        publish(bookmarks, ('\n'.join(rows) + '\n').encode())
    validate_services(identities)
    publish(Path('/usr/local/share/doc/filen-cli/INSTALLATION.json'),
            (json.dumps({'version': version, 'architecture': architecture, 'url': url, 'sha256': sha,
                         'trust': 'Pinned publisher release bytes; SHA-256 is not a vendor signature.'}, sort_keys=True) + '\n').encode())
    print('filen_install outcome=staged accounts=' + ','.join(row[0] for row in accounts))


if __name__ == '__main__':
    try:
        if os.geteuid() != 0 or len(sys.argv) != 2:
            raise Error('root target installer with a private staging directory required')
        stage = Path(path_value(sys.argv[1]))
        if stage.parent != Path('/tmp') or not re.fullmatch(r'installer-filen\.[A-Za-z0-9]{6}', stage.name):
            raise Error('unexpected private staging path')
        directory(stage)
        if stat.S_IMODE(stage.stat().st_mode) != 0o700:
            raise Error('staging directory must have mode 0700')
        install(stage, dict(os.environ))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        # urllib exceptions can contain signed redirect URLs. Credentials,
        # remote payloads and raw exception text never enter installer logs.
        cause = str(error) if isinstance(error, Error) else type(error).__name__
        print('filen_install outcome=failed cause=' + cause, file=sys.stderr)
        raise SystemExit(1)
