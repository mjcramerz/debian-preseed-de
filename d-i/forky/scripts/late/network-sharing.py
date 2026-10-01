#!/usr/bin/python3 -I
"""Configure NFS in the installer's target chroot, never the running installer.

No probing, mounts, module loads, sysctl writes, or service starts occur here.
The public functions are separable for offline tests; the CLI always uses /.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import grp
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import signal
import stat
import subprocess
import sys
import tempfile
from typing import Iterator, Mapping

BEGIN = '# BEGIN managed-network-sharing'
END = '# END managed-network-sharing'
REQUIRED_FLAGS = {'sync', 'subtree_check', 'root_squash', 'secure', 'sec=sys', 'fsid=0'}
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
BOOLS = ('NFS_SERVER_ENABLE', 'NFS_CLIENT_ENABLE', 'NFS_SERVER_BIND_ENABLE',
         'NFS_CLIENT_BIND_ENABLE', 'NFS_CLIENT_READ_ONLY')
TOOL_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C',
            'DEBIAN_FRONTEND': 'noninteractive', 'DEBCONF_NONINTERACTIVE_SEEN': 'true',
            'NEEDRESTART_SUSPEND': '1', 'SYSTEMD_OFFLINE': '1'}


def normalized_path(value: str, *, relative: bool = False, allow_root: bool = False) -> str:
    if not value or len(value) > 2048 or not re.fullmatch(r'[A-Za-z0-9_./-]+', value):
        raise ValueError('sharing paths must use only ASCII letters, digits, _, ., / and -')
    if value.startswith('/') == relative or (value == '/' and not allow_root):
        raise ValueError('unexpected absolute/relative sharing path')
    if value.startswith('//') or (value != '/' and any(part in ('', '.', '..') for part in value.lstrip('/').split('/'))):
        raise ValueError('sharing path is not normalized')
    return value


def bounded_integer(value: str, name: str, lower: int, upper: int) -> int:
    if not re.fullmatch(r'[0-9]+', value) or not lower <= int(value) <= upper:
        raise ValueError(f'{name} must be an integer in {lower}..{upper}')
    return int(value)


def private_ipv4(value: str) -> ipaddress.IPv4Address:
    ip = ipaddress.IPv4Address(value)
    if not any(ip in network for network in PRIVATE_NETWORKS):
        raise ValueError('NFS peers must have RFC1918 IPv4 addresses on a trusted network')
    return ip


def parse_exports(line: str, server_path: str) -> list[tuple[str, str]]:
    """One explicit export and nonoverlapping CIDRs, never wildcard/DNS entries."""
    if not line or len(line) > 16384 or any(c in line for c in '\r\n\t'):
        raise ValueError('NFS_SERVER_EXPORTS must be one bounded, space-separated line')
    fields = line.split(' ')
    if len(fields) < 2 or fields[0] != server_path or '' in fields:
        raise ValueError('NFS_SERVER_EXPORTS must export exactly NFS_SERVER_PATH')
    peers: list[tuple[str, str]] = []
    networks: list[ipaddress.IPv4Network] = []
    for field in fields[1:]:
        match = re.fullmatch(r'([0-9./]+)\(([a-z0-9_,=]+)\)', field)
        if not match:
            raise ValueError('invalid NFS peer/option grammar')
        network = ipaddress.IPv4Network(match[1], strict=True)
        if '/' not in match[1] or not any(network.subnet_of(n) for n in PRIVATE_NETWORKS):
            raise ValueError('NFS exports require explicit RFC1918 CIDRs')
        if any(network.overlaps(other) for other in networks):
            raise ValueError('overlapping NFS export CIDRs are ambiguous')
        options = match[2].split(',')
        flags = set(options)
        mode = flags & {'ro', 'rw'}
        if len(flags) != len(options) or len(mode) != 1 or flags != REQUIRED_FLAGS | mode:
            raise ValueError('export flags must be ro/rw,sync,subtree_check,root_squash,secure,sec=sys,fsid=0')
        networks.append(network)
        peers.append((str(network), next(iter(mode))))
    return peers


def package_names(value: str, required: set[str]) -> list[str]:
    packages = value.split()
    if not packages or len(packages) > 64 or any(not re.fullmatch(r'[a-z0-9][a-z0-9+.-]{1,79}', p) for p in packages):
        raise ValueError('invalid NFS dependency package names')
    if not required <= set(packages):
        raise ValueError('NFS dependency list omits required packages: ' + ' '.join(sorted(required - set(packages))))
    return sorted(set(packages))


@dataclass(frozen=True)
class Settings:
    values: dict[str, str]
    flags: dict[str, bool]
    peers: list[tuple[str, str]]
    packages: list[str]

    def __getitem__(self, key: str) -> str:
        return self.values[key]

    def enabled(self, key: str) -> bool:
        return self.flags[key]

    @property
    def active(self) -> bool:
        return self.enabled('NFS_SERVER_ENABLE') or self.enabled('NFS_CLIENT_ENABLE')

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> 'Settings':
        names = set(BOOLS) | {
            'ACCOUNT_USERNAME', 'ACCOUNT_HOME', 'SYSTEM_DOMAIN', 'NFT_PROFILE', 'NETWORK_SHARING_ROOT_PATH',
            'NFS_SERVER_PATH', 'NFS_SERVER_HOME_BIND_PATH', 'NFS_SERVER_DEPS', 'NFS_SERVER_THREADS',
            'NFS_SERVER_EXPORTS', 'NFS_CLIENT_PATH', 'NFS_CLIENT_HOME_BIND_PATH',
            'NFS_CLIENT_TARGET_IP', 'NFS_CLIENT_EXPORT_PATH', 'NFS_CLIENT_VERSION',
            'NFS_CLIENT_MOUNT_TIMEOUT', 'NFS_CLIENT_DEPS', 'NFS_ACCOUNT_UID', 'NFS_ACCOUNT_GID',
            'NFS_SHARED_GROUP', 'NFS_SHARED_GID', 'NFS_INTERFACES', 'NFS_TCP_RMEM',
            'NFS_TCP_WMEM', 'NFS_SOCKET_RMEM_MAX', 'NFS_SOCKET_WMEM_MAX'}
        missing = names - env.keys()
        if missing:
            raise ValueError('missing network sharing settings: ' + ', '.join(sorted(missing)))
        values = {k: env[k] for k in names}
        for name in BOOLS:
            if values[name] not in ('true', 'false'):
                raise ValueError(f'{name} must be true or false')
        flags = {name: values[name] == 'true' for name in BOOLS}
        if (flags['NFS_SERVER_ENABLE'] or flags['NFS_CLIENT_ENABLE']) and values['NFT_PROFILE'].lower() == 'none':
            raise ValueError('enabled NFS roles require the managed nftables firewall')
        root = normalized_path(values['NETWORK_SHARING_ROOT_PATH'])
        if not any(root.startswith(base + '/') for base in ('/data', '/pool', '/srv')):
            raise ValueError('sharing root must be below /data, /pool or /srv')
        sources = [normalized_path(values[k]) for k in ('NFS_SERVER_PATH', 'NFS_CLIENT_PATH')]
        if any(not p.startswith(root + '/') for p in sources):
            raise ValueError('NFS paths must be strictly below NETWORK_SHARING_ROOT_PATH')
        if any(a == b or a.startswith(b + '/') for a, b in (sources, sources[::-1])):
            raise ValueError('server and client paths must not overlap')
        home = normalized_path(values['ACCOUNT_HOME'])
        if not home.startswith('/home/'):
            raise ValueError('managed account home must be below /home')
        targets = []
        for role in ('SERVER', 'CLIENT'):
            relative = normalized_path(values[f'NFS_{role}_HOME_BIND_PATH'], relative=True)
            # A dedicated root-owned parent is required; do not take over Documents.
            if len(PurePosixPath(relative).parts) < 2:
                raise ValueError('home bind must have a dedicated parent, e.g. Sharing/nfs-client')
            targets.append(relative)
            if flags[f'NFS_{role}_BIND_ENABLE'] and not flags[f'NFS_{role}_ENABLE']:
                raise ValueError(f'NFS_{role}_BIND_ENABLE requires NFS_{role}_ENABLE')
        if any(a == b or a.startswith(b + '/') for a, b in (targets, targets[::-1])):
            raise ValueError('home bind destinations must not overlap')
        for local_path in (root, *sources, *(home + '/' + target for target in targets)):
            if len(unit_name(local_path, 'automount')) > 255:
                raise ValueError('sharing path exceeds the escaped systemd unit-name limit')
        for key in ('ACCOUNT_USERNAME', 'NFS_SHARED_GROUP'):
            if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', values[key]) or values[key] in ('root', 'nogroup', 'nobody'):
                raise ValueError(f'invalid {key}')
        bounded_integer(values['NFS_SHARED_GID'], 'NFS_SHARED_GID', 1000, 59999)
        bounded_integer(values['NFS_ACCOUNT_UID'], 'NFS_ACCOUNT_UID', 1000, 59999)
        bounded_integer(values['NFS_ACCOUNT_GID'], 'NFS_ACCOUNT_GID', 1000, 59999)
        if int(values['NFS_SHARED_GID']) == int(values['NFS_ACCOUNT_GID']):
            raise ValueError('NFS_SHARED_GID must be separate from the primary account GID')
        bounded_integer(values['NFS_SERVER_THREADS'], 'NFS_SERVER_THREADS', 1, 128)
        bounded_integer(values['NFS_CLIENT_MOUNT_TIMEOUT'], 'NFS_CLIENT_MOUNT_TIMEOUT', 5, 120)
        private_ipv4(values['NFS_CLIENT_TARGET_IP'])
        normalized_path(values['NFS_CLIENT_EXPORT_PATH'], allow_root=True)
        if values['NFS_CLIENT_VERSION'] not in ('4.1', '4.2'):
            raise ValueError('only NFSv4.1 and NFSv4.2 are supported')
        values['SYSTEM_DOMAIN'] = values['SYSTEM_DOMAIN'].lower()
        domain = values['SYSTEM_DOMAIN']
        if len('sharing.' + domain) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in domain.split('.')):
            raise ValueError('invalid SYSTEM_DOMAIN for the derived NFS identity namespace')
        ifaces = values['NFS_INTERFACES'].split()
        if not ifaces or len(ifaces) > 8 or any(not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}', i) or i == 'lo' for i in ifaces):
            raise ValueError('NFS_INTERFACES requires explicit interface names, never wildcards')
        for direction in ('R', 'W'):
            maximum = bounded_integer(values[f'NFS_SOCKET_{direction}MEM_MAX'], 'socket buffer maximum', 262144, 67108864)
            vector = values[f'NFS_TCP_{direction}MEM'].split()
            if len(vector) != 3:
                raise ValueError('TCP buffer values must contain min default max')
            limits = [bounded_integer(v, 'TCP buffer value', 4096, 67108864) for v in vector]
            if limits != sorted(limits) or limits[-1] > maximum:
                raise ValueError('TCP buffers must be ordered and fit within the socket ceiling')
        peers = parse_exports(values['NFS_SERVER_EXPORTS'], values['NFS_SERVER_PATH'])
        common = {'nfs-common', 'libnfsidmap1', 'keyutils', 'nftables'}
        server_required = common | {'nfs-kernel-server', 'acl'}
        client_required = set(common)
        if flags['NFS_SERVER_BIND_ENABLE']:
            server_required.add('e2fsprogs')
        if flags['NFS_CLIENT_BIND_ENABLE']:
            client_required.add('e2fsprogs')
        server = package_names(values['NFS_SERVER_DEPS'], server_required)
        client = package_names(values['NFS_CLIENT_DEPS'], client_required)
        packages = (server if flags['NFS_SERVER_ENABLE'] else []) + (client if flags['NFS_CLIENT_ENABLE'] else [])
        return cls(values, flags, peers, sorted(set(packages)))


def run(argv: list[str], *, timeout: int = 60) -> None:
    # apt can have dpkg/maintscript children. On timeout, kill its owned group
    # before the policy-rc.d context is restored, not only the immediate child.
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL, env=TOOL_ENV,
                          start_new_session=True) as child:
        try:
            returncode = child.wait(timeout=timeout)
        except BaseException:
            # Keep the leader unreaped until signalling: never target a numeric
            # process-group ID after its leader may already have been reused.
            if child.returncode is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            raise  # Popen's context reaps the direct child before unwinding.
        if returncode:
            raise subprocess.CalledProcessError(returncode, argv)


def trusted_parents(path: Path) -> None:
    """Configuration parents must be root-owned real directories, not writable."""
    for parent in reversed(path.parents):
        metadata = parent.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError(f'untrusted configuration parent: {parent}')


def read_regular(path: Path, *, limit: int = 1024 * 1024) -> str:
    trusted_parents(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return ''
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_nlink != 1 or metadata.st_mode & 0o022:
            raise ValueError(f'untrusted managed file: {path}')
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f'oversized managed file: {path}')
        return data


def system_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError(f'unsafe system directory: {path}')
    else:
        system_directory(path.parent)
        path.mkdir(mode=0o755)
        os.chmod(path, 0o755, follow_symlinks=False)
    trusted_parents(path)


def atomic_write(path: Path, text: str, mode: int = 0o644) -> None:
    system_directory(path.parent)
    read_regular(path)  # Reject symlinks, hardlinks, non-regular or writable files.
    fd, name = tempfile.mkstemp(prefix='.network-sharing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def without_managed_block(text: str) -> str:
    if BEGIN not in text and END not in text:
        return text
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError('duplicate or incomplete managed configuration block')
    start, finish = text.index(BEGIN), text.index(END) + len(END)
    if (start >= text.index(END) or (start and text[start-1] != '\n')
            or text[start + len(BEGIN):start + len(BEGIN) + 1] != '\n'
            or (text.index(END) and text[text.index(END)-1] != '\n')
            or (finish < len(text) and text[finish] != '\n')):
        raise ValueError('malformed managed configuration markers')
    if finish < len(text):
        finish += 1
    return text[:start] + text[finish:]


def append_block(text: str, block: str) -> str:
    return text + ('' if not text or text.endswith('\n') else '\n') + block


def render(asset: Path, settings: Settings) -> str:
    text = asset.read_text(encoding='utf-8')
    def substitute(match: re.Match[str]) -> str:
        key = match[1]
        if key not in settings.values:
            raise ValueError('unknown network-sharing template variable: ' + key)
        return settings[key]
    result = re.sub(r'__([A-Z][A-Z0-9_]+)__', substitute, text)
    if re.search(r'__[A-Z][A-Z0-9_]+__', result):
        raise ValueError('unresolved network-sharing template')
    return result


def unit_name(path: str, suffix: str = 'mount') -> str:
    """systemd-escape --path equivalent for our validated ASCII path grammar."""
    normalized_path(path)
    escaped = ''.join('/' if c == '/' else (c if c.isalnum() or c in '_.' else f'\\x{ord(c):02x}')
                      for c in path.strip('/'))
    if escaped.startswith('.'):
        escaped = '\\x2e' + escaped[1:]
    return escaped.replace('/', '-') + '.' + suffix


def fstab_entries(s: Settings) -> list[str]:
    entries: list[str] = []
    if s.enabled('NFS_CLIENT_ENABLE'):
        opts = ['ro' if s.enabled('NFS_CLIENT_READ_ONLY') else 'rw', 'hard', 'proto=tcp',
                'port=2049', 'resvport', 'sec=sys', 'vers=' + s['NFS_CLIENT_VERSION'],
                'nosuid', 'nodev', 'noexec', '_netdev', 'nofail', 'x-systemd.automount',
                'x-systemd.mount-timeout=' + s['NFS_CLIENT_MOUNT_TIMEOUT'] + 's',
                'x-systemd.requires=nfs-client.target', 'x-systemd.requires=nftables.service',
                'x-systemd.requires=network-sharing-identity.service']
        entries.append(f"{s['NFS_CLIENT_TARGET_IP']}:{s['NFS_CLIENT_EXPORT_PATH']} {s['NFS_CLIENT_PATH']} nfs {','.join(opts)} 0 0")
    for role in ('SERVER', 'CLIENT'):
        if not s.enabled(f'NFS_{role}_BIND_ENABLE'):
            continue
        source = s[f'NFS_{role}_PATH']
        target = s['ACCOUNT_HOME'] + '/' + s[f'NFS_{role}_HOME_BIND_PATH']
        opts = ['bind', 'nosuid', 'nodev', 'noexec', 'nofail',
                'x-systemd.requires-mounts-for=' + source]
        if role == 'CLIENT':
            opts += ['_netdev', 'x-systemd.automount',
                     'x-systemd.mount-timeout=' + s['NFS_CLIENT_MOUNT_TIMEOUT'] + 's']
            if s.enabled('NFS_CLIENT_READ_ONLY'):
                opts.append('ro')
        entries.append(f"{source} {target} none {','.join(opts)} 0 0")
    return entries


def primary_account(s: Settings) -> pwd.struct_passwd:
    account = pwd.getpwnam(s['ACCOUNT_USERNAME'])
    if (account.pw_uid != int(s['NFS_ACCOUNT_UID']) or account.pw_gid != int(s['NFS_ACCOUNT_GID'])
            or account.pw_dir != s['ACCOUNT_HOME'] or pwd.getpwuid(account.pw_uid).pw_name != account.pw_name):
        raise ValueError('NFS primary account UID/GID/home mismatch; refusing to renumber AUTH_SYS identities')
    return account


def group_and_account(s: Settings) -> pwd.struct_passwd:
    account = primary_account(s)
    gid = int(s['NFS_SHARED_GID'])
    try:
        existing = grp.getgrnam(s['NFS_SHARED_GROUP'])
    except KeyError:
        try:
            grp.getgrgid(gid)
        except KeyError:
            run(['/usr/sbin/groupadd', '--gid', str(gid), s['NFS_SHARED_GROUP']])
        else:
            raise ValueError('NFS_SHARED_GID is already used by another group')
    else:
        if existing.gr_gid != gid or grp.getgrgid(gid).gr_name != s['NFS_SHARED_GROUP']:
            raise ValueError('NFS_SHARED_GROUP has a different GID; refusing to renumber')
    run(['/usr/sbin/usermod', '--append', '--groups', s['NFS_SHARED_GROUP'], s['ACCOUNT_USERNAME']])
    return account


def sharing_directory(path: Path, mode: int, gid: int = 0, *, empty: bool = False) -> None:
    system_directory(path.parent)
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_gid not in (0, gid):
            raise ValueError(f'unsafe sharing directory: {path}')
        if empty and any(path.iterdir()):
            raise ValueError(f'refusing to hide nonempty mount destination: {path}')
    else:
        path.mkdir(mode=0o700)
    os.chown(path, 0, gid, follow_symlinks=False)
    os.chmod(path, mode, follow_symlinks=False)


def home_bind_directory(s: Settings, role: str, account: pwd.struct_passwd) -> None:
    home = Path(s['ACCOUNT_HOME'])
    trusted_parents(home)
    metadata = home.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != account.pw_uid or metadata.st_mode & 0o022:
        raise ValueError('home bind requires a real, private account home')
    # Never follow symlinks or recursively chown existing user content. Existing
    # nonempty user-owned parents are refused rather than taking them over.
    current = home
    for component in PurePosixPath(s[f'NFS_{role}_HOME_BIND_PATH']).parts:
        current /= component
        if current.exists() or current.is_symlink():
            metadata = current.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
                raise ValueError(f'home bind requires dedicated root-owned directories: {current}')
        else:
            current.mkdir(mode=0o755)
            os.chown(current, 0, 0)
            os.chmod(current, 0o755, follow_symlinks=False)
        if current.is_symlink():
            raise ValueError('symlink in home bind path')
    if any(current.iterdir()):
        raise ValueError('refusing to cover files in home bind destination')
    os.chmod(current, 0o000)


def protect_home_bind_parents(s: Settings) -> None:
    """Prevent the home owner from redirecting persistent root-managed binds.

    Root ownership alone does not stop rename from the user-owned home. Lock
    each dedicated first-level parent only AFTER every endpoint is created.
    This is an offline installer: no target user session may run concurrently.
    Unsupported immutable flags fail before fstab or success publication.
    """
    parents = {str(Path(s['ACCOUNT_HOME']) / PurePosixPath(s[f'NFS_{role}_HOME_BIND_PATH']).parts[0])
               for role in ('SERVER', 'CLIENT') if s.enabled(f'NFS_{role}_BIND_ENABLE')}
    for parent in sorted(parents):
        run(['/usr/bin/chattr', '+i', '--', parent])


@contextmanager
def inhibit_package_services() -> Iterator[None]:
    """Restore d-i's policy-rc.d exactly, even when apt fails. No live starts."""
    path = Path('/usr/sbin/policy-rc.d')
    trusted_parents(path)
    original = path.exists() or path.is_symlink()
    fd, name = tempfile.mkstemp(prefix='.network-sharing-policy-', dir=path.parent)
    os.close(fd)
    backup = Path(name)
    moved = False
    installed = False
    try:
        if original:
            os.replace(path, backup)
            moved = True
        atomic_write(path, '#!/bin/sh\nexit 101\n', 0o755)
        installed = True
        yield
    finally:
        if moved:
            os.replace(backup, path)
        elif installed:
            path.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)


def configure(s: Settings, assets: Path) -> None:
    # Reject changed-role reruns: this is an offline installer, not a live
    # reconfiguration tool. Never silently leave stale exports/mounts enabled.
    config_path = Path('/etc/network-sharing/config.json')
    system_directory(config_path.parent)
    old = read_regular(config_path)
    previous = json.loads(old) if old else None
    if old and (not isinstance(previous, dict) or previous.get('version') != 1 or previous.get('profile') != s.values):
        raise ValueError('network sharing is already configured differently; rebuild/reinstall or follow the administrator migration procedure')
    root = Path(s['NETWORK_SHARING_ROOT_PATH'])
    system_directory(root)
    entries = fstab_entries(s)
    fstab = without_managed_block(read_regular(Path('/etc/fstab')))
    destinations = {entry.split()[1] for entry in entries}
    for line in fstab.splitlines():
        parts = line.split()
        if len(parts) > 1 and not line.lstrip().startswith('#'):
            # fstab allows octal escapes; the generator also canonicalizes ./,
            # ../ and repeated slashes. Reject aliases before writing a second
            # definition of the same unit, without probing remote mount paths.
            destination = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), parts[1])
            if destination.startswith('/'):
                destination = os.path.normpath('/' + destination.lstrip('/'))
            if destination in destinations:
                raise ValueError('an unmanaged fstab entry already owns an NFS mount destination')
    # Validate export ownership before package installation or export mutation.
    exports = ''
    if s.enabled('NFS_SERVER_ENABLE'):
        exports = without_managed_block(read_regular(Path('/etc/exports')))
        if any(line.strip() and not line.lstrip().startswith('#') for line in exports.splitlines()):
            raise ValueError('existing unmanaged exports require administrator review')
        exports_dir = Path('/etc/exports.d')
        if exports_dir.exists() or exports_dir.is_symlink():
            system_directory(exports_dir)
            for other in exports_dir.glob('*.exports'):
                if any(line.strip() and not line.lstrip().startswith('#') for line in read_regular(other).splitlines()):
                    raise ValueError('unmanaged exports.d entries conflict with the dedicated NFSv4 policy')
    if s.active:
        # AUTH_SYS sends numeric credentials independently of NFSv4 name
        # mapping. Refuse a mismatched install before any package mutation.
        primary_account(s)
        overrides = Path('/etc/idmapd.conf.d')
        if overrides.exists() or overrides.is_symlink():
            system_directory(overrides)
            for other in overrides.glob('*.conf'):
                if any(line.strip() and not line.lstrip().startswith(('#', ';')) for line in read_regular(other).splitlines()):
                    raise ValueError('unmanaged idmapd.conf.d settings conflict with the dedicated NFS identity policy')
        if s.enabled('NFS_SERVER_ENABLE'):
            # Package maintscripts may enable a unit even while policy-rc.d
            # blocks starts. Install the boot-time completion guards first.
            name = 'etc/systemd/system/nfs-server.service.d/60-network-sharing.conf.tmpl'
            atomic_write(Path('/') / name.removesuffix('.tmpl'), render(assets / name, s))
        with inhibit_package_services():
            run(['/usr/bin/apt-get', '-o', 'Acquire::Retries=3', '-o', 'Acquire::http::Timeout=45',
                 '-o', 'Acquire::https::Timeout=45', '-o', 'DPkg::Lock::Timeout=60', '-o', 'DPkg::Use-Pty=0',
                 '-y', '--no-install-recommends', '--no-install-suggests', 'install', *s.packages], timeout=1800)
        account = group_and_account(s)
        for name in ('etc/idmapd.conf.tmpl', 'etc/sysctl.d/60-network-sharing.conf.tmpl',
                     'etc/systemd/system/network-sharing-report.service.tmpl',
                     'etc/systemd/system/network-sharing-identity.service'):
            atomic_write(Path('/') / name.removesuffix('.tmpl'), render(assets / name, s))
        atomic_write(Path('/usr/local/libexec/network-sharing-report'),
                     (assets / 'usr/local/libexec/network-sharing-report').read_text(), 0o755)
        atomic_write(Path('/usr/local/libexec/network-sharing-identity'),
                     (assets / 'usr/local/libexec/network-sharing-identity').read_text(), 0o755)
        modules = ['sunrpc']
        options = ['# Managed NFSv4 name mapping (AUTH_SYS still uses numeric credentials).']
        if s.enabled('NFS_CLIENT_ENABLE'):
            modules += ['nfs', 'nfsv4']
            options.append('options nfs nfs4_disable_idmapping=0')
            # Configure Debian's exact id_resolver handler; preserve other
            # request-key handlers (including DNS and GSS entries).
            atomic_write(Path('/etc/request-key.d/id_resolver.conf'),
                         '# Managed NFSv4 identity upcall\ncreate id_resolver * * /usr/sbin/nfsidmap -t 600 %k %d\n')
            sharing_directory(Path(s['NFS_CLIENT_PATH']), 0o000, empty=True)
        if s.enabled('NFS_SERVER_ENABLE'):
            modules.append('nfsd')
            options.append('options nfsd nfs4_disable_idmapping=0')
            sharing_directory(Path(s['NFS_SERVER_PATH']), 0o2770, int(s['NFS_SHARED_GID']))
            # Replace, do not merge: inherited named ACLs must not grant extra
            # access. Only the export root is managed, never existing children.
            run(['/usr/bin/setfacl', '--set',
                 'u::rwx,g::rwx,o::---,d:u::rwx,d:g::rwx,d:m::rwx,d:o::---',
                 '--', s['NFS_SERVER_PATH']])
            atomic_write(Path('/etc/exports'), append_block(exports, render(assets / 'etc/exports.tmpl', s)))
            for name in ('etc/nfs.conf.d/60-network-sharing.conf.tmpl',
                         'etc/systemd/system/nfs-mountd.service.d/60-network-sharing.conf',
                         'etc/systemd/system/nfs-idmapd.service.d/60-network-sharing.conf'):
                atomic_write(Path('/') / name.removesuffix('.tmpl'), render(assets / name, s))
        atomic_write(Path('/etc/modules-load.d/60-network-sharing.conf'), '\n'.join(modules) + '\n')
        atomic_write(Path('/etc/modprobe.d/60-network-sharing.conf'), '\n'.join(options) + '\n')
        for role in ('SERVER', 'CLIENT'):
            if s.enabled(f'NFS_{role}_BIND_ENABLE'):
                home_bind_directory(s, role, account)
        protect_home_bind_parents(s)
        if s.enabled('NFS_CLIENT_BIND_ENABLE'):
            target = s['ACCOUNT_HOME'] + '/' + s['NFS_CLIENT_HOME_BIND_PATH']
            # Also tear down the home bind if the source disappears. No idle
            # unmount is configured: it would race a still-active bind mount.
            atomic_write(Path('/etc/systemd/system') / (unit_name(target) + '.d') / '60-network-sharing.conf',
                         '[Unit]\nBindsTo=' + unit_name(s['NFS_CLIENT_PATH']) + '\nAfter=' + unit_name(s['NFS_CLIENT_PATH']) + '\n')
        if s.enabled('NFS_CLIENT_ENABLE'):
            atomic_write(Path('/etc/systemd/system') / (unit_name(s['NFS_CLIENT_PATH']) + '.d') / '60-network-sharing.conf',
                         '[Unit]\nBindsTo=nftables.service\nAfter=nftables.service\n')
        # Deliberately v4-only; these RPC listeners are not needed for this role.
        run(['/usr/bin/systemctl', '--root=/', 'mask', 'rpcbind.service', 'rpcbind.socket',
             'rpc-statd.service', 'rpc-statd-notify.service'])
        if s.enabled('NFS_CLIENT_ENABLE'):
            run(['/usr/bin/systemctl', '--root=/', 'enable', 'nfs-client.target'])
        if s.enabled('NFS_SERVER_ENABLE'):
            run(['/usr/bin/systemctl', '--root=/', 'enable', 'nfs-server.service'])
    if entries:
        fstab = append_block(fstab, BEGIN + '\n' + '\n'.join(entries) + '\n' + END + '\n')
        atomic_write(Path('/etc/fstab'), fstab)
    public = {'version': 1, 'profile': s.values, 'peers': s.peers,
              'server_enabled': s.enabled('NFS_SERVER_ENABLE'), 'client_enabled': s.enabled('NFS_CLIENT_ENABLE'),
              'client_mount': unit_name(s['NFS_CLIENT_PATH']),
              'client_automount': unit_name(s['NFS_CLIENT_PATH'], 'automount')}
    for role in ('SERVER', 'CLIENT'):
        target = s['ACCOUNT_HOME'] + '/' + s[f'NFS_{role}_HOME_BIND_PATH']
        public[role.lower() + '_bind_mount'] = unit_name(target) if s.enabled(f'NFS_{role}_BIND_ENABLE') else ''
        public[role.lower() + '_bind_automount'] = unit_name(target, 'automount') if role == 'CLIENT' and s.enabled('NFS_CLIENT_BIND_ENABLE') else ''
    atomic_write(config_path, json.dumps(public, indent=2, sort_keys=True) + '\n')
    print('Network sharing configured: server=' + str(s.enabled('NFS_SERVER_ENABLE')).lower()
          + ' client=' + str(s.enabled('NFS_CLIENT_ENABLE')).lower() + ' root=' + str(root))


def main(argv: list[str]) -> int:
    if os.getuid() != 0 or os.geteuid() != 0 or len(argv) != 1:
        raise ValueError('usage (installer chroot, root only): network-sharing.py ASSET_DIRECTORY')
    assets = Path(argv[0])
    if not assets.is_absolute() or not assets.is_dir() or assets.is_symlink():
        raise ValueError('assets must be an existing absolute directory')
    settings = Settings.from_environment(os.environ)
    configure(settings, assets)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('network-sharing: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
