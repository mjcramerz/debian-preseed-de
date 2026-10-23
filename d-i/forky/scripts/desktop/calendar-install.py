#!/usr/bin/python3 -I
"""Install pinned calendar release data in the offline target, without launch."""
from __future__ import annotations

import hashlib
import gzip
import io
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


class Error(ValueError):
    pass


def directory(path: Path) -> None:
    if path == Path('/'):
        return
    directory(path.parent)
    if not path.exists():
        path.mkdir(mode=0o755)
        path.chmod(0o755)
    info = path.lstat()
    private_tmp = path == Path('/tmp') and stat.S_IMODE(info.st_mode) == 0o1777
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or (info.st_mode & 0o022 and not private_tmp):
        raise Error('untrusted calendar installation directory')


def publish(path: Path, data: bytes, mode: int = 0o644) -> None:
    directory(path.parent)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_nlink != 1:
            raise Error('untrusted existing calendar asset')
    fd, name = tempfile.mkstemp(prefix='.calendar-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        Path(name).unlink(missing_ok=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        return None


def download(url: str, digest: str, maximum: int) -> bytes:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + 180
    for hop in range(5):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in {
                'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
                or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443)):
            raise Error('calendar release redirect rejected')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Error('calendar release download deadline exceeded')
        try:
            response = opener.open(urllib.request.Request(url, headers={'User-Agent': 'preseed-calendar-installer'}),
                                   timeout=min(10, remaining))
        except urllib.error.HTTPError as error:
            with error:
                location = error.headers.get('Location')
                if error.code not in {301, 302, 303, 307, 308} or not location or hop == 4:
                    raise Error('calendar release HTTP failure') from None
                url = urllib.parse.urljoin(url, location)
                continue
        with response:
            data = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise Error('calendar release download deadline exceeded')
                block = response.read1(min(65536, maximum + 1 - len(data)))
                if time.monotonic() >= deadline:
                    raise Error('calendar release download deadline exceeded')
                if not block:
                    break
                data.extend(block)
                if len(data) > maximum:
                    raise Error('calendar release download limit exceeded')
        if hashlib.sha256(data).hexdigest() != digest:
            raise Error('calendar release SHA-256 mismatch')
        return bytes(data)
    raise Error('calendar release redirect limit exceeded')


def members(data: bytes, root: str, wanted: set[str], *, agenda: bool = False) -> dict[str, bytes]:
    # Bound expanded bytes before tarfile can materialize extension headers.
    with gzip.GzipFile(fileobj=io.BytesIO(data), mode='rb') as compressed:
        expanded = compressed.read(50331649)
    if len(expanded) > 50331648:
        raise Error('calendar release expansion limit exceeded')
    result = {}
    seen = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(expanded), mode='r|') as archive:
        for index, member in enumerate(archive):
            path = PurePosixPath(member.name)
            if (index >= (256 if agenda else 128) or len(member.name) > 512 or path.is_absolute()
                    or '..' in path.parts or not path.parts or path.parts[0] != root
                    or path.as_posix() in seen or path.as_posix() != member.name.rstrip('/')
                    or not (member.isfile() or member.isdir())
                    or member.size < 0 or member.size > 33554432):
                raise Error('unsafe calendar release member')
            seen.add(path.as_posix())
            total += member.size
            if total > 50331648:
                raise Error('calendar release expansion limit exceeded')
            relative = '/'.join(path.parts[1:])
            # Agenda's translations have a compiled /usr prefix. Select only
            # its namespaced data, never the vendor installer or desktop file.
            extra = agenda and re.fullmatch(
                r'rootfs/usr/share/(?:locale/[A-Za-z_@]+/LC_MESSAGES/'
                r'com\.github\.dahenson\.agenda\.mo|icons/hicolor/'
                r'(?:16|24|32|48|64|128)x(?:16|24|32|48|64|128)(?:@2)?/apps/'
                r'com\.github\.dahenson\.agenda\.svg)', relative)
            if relative in wanted or extra:
                if not member.isfile():
                    raise Error('calendar release asset is not regular')
                stream = archive.extractfile(member)
                if stream is None:
                    raise Error('missing calendar release asset')
                with stream:
                    result[relative] = stream.read(member.size + 1)
                if len(result[relative]) != member.size:
                    raise Error('truncated calendar release asset')
    if not wanted <= set(result):
        raise Error('calendar release lacks required assets')
    return result


def install_agenda() -> None:
    version = '1.2.1'
    commit = '5276daf526fd29bf7166fda0ea00996ae8e28310'
    digest = '22c2c9bb03f77225710cacb947ad36bbb08b302f7d6ed3b923d51b67abcdc719'
    url = 'https://github.com/mjcramerz/agenda/releases/download/agenda-v1.2.1/agenda-1.2.1-debian-amd64.tar.gz'
    pins = {'VERSION': version, 'COMMIT': commit, 'SHA256': digest, 'URL': url,
            'MAXIMUM_BYTES': '1048576'}
    if any(os.environ.get('AGENDA_' + key) != value for key, value in pins.items()):
        raise Error('Agenda profile release pins differ')
    app = 'com.github.dahenson.agenda'
    binary = 'rootfs/usr/bin/' + app
    schema = 'rootfs/usr/share/glib-2.0/schemas/' + app + '.gschema.xml'
    license_path = 'rootfs/usr/share/doc/agenda/copyright'
    icon = 'rootfs/usr/share/icons/hicolor/128x128/apps/' + app + '.svg'
    assets = members(download(url, digest, 1048576), 'agenda-1.2.1-debian-amd64',
                     {binary, schema, license_path, icon, 'BUILD-INFO.json', 'prefix.txt'}, agenda=True)
    elf(assets[binary])
    metadata = json.loads(assets['BUILD-INFO.json'])
    # The release records a dirty build at an earlier commit than its tag.
    # Record those facts separately; neither metadata nor hashes prove that
    # the published binary was compiled from the tagged source tree.
    if (assets['prefix.txt'] != b'/usr\n' or metadata.get('application') != app
            or metadata.get('architecture') != 'amd64' or metadata.get('version') != version
            or metadata.get('prefix') != '/usr'
            or metadata.get('commit') != 'e7a71a506b8452e307b908c55d4d63237a7113cb'
            or metadata.get('working_tree_modified') is not True):
        raise Error('Agenda archive metadata differs')
    schema_dir = Path('/usr/local/share/agenda/schemas')
    publish(schema_dir / (app + '.gschema.xml'), assets[schema])
    compiled = schema_dir / 'gschemas.compiled'
    if compiled.exists() or compiled.is_symlink():
        info = compiled.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise Error('unsafe previous Agenda compiled schema')
    # The repository-owned override has already been staged in this directory.
    subprocess.run(['/usr/bin/glib-compile-schemas', '--strict', str(schema_dir)],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, timeout=15, check=True)
    info = compiled.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_size > 1048576:
        raise Error('unsafe compiled Agenda schema')
    publish(compiled, compiled.read_bytes())
    for name, data in assets.items():
        relative = name.removeprefix('rootfs/usr/share/')
        if relative.startswith('locale/'):
            publish(Path('/usr/share') / relative, data)
        elif relative.startswith('icons/'):
            publish(Path('/usr/local/share') / relative, data)
    publish(Path('/usr/local/share/doc/agenda/copyright'), assets[license_path])
    publish(Path('/usr/local/share/doc/agenda/BUILD-INFO.json'), assets['BUILD-INFO.json'])
    publish(Path('/usr/local/bin') / app, assets[binary], 0o755)
    receipt = {key.lower(): value for key, value in pins.items() if key != 'MAXIMUM_BYTES'}
    receipt.update(executable_sha256=hashlib.sha256(assets[binary]).hexdigest(),
                   schema_sha256=hashlib.sha256(assets[schema]).hexdigest(),
                   build_commit=metadata['commit'], working_tree_modified=True)
    publish(Path('/usr/local/share/agenda/release.json'), (json.dumps(receipt, sort_keys=True) + '\n').encode())


def elf(data: bytes) -> None:
    if (len(data) < 64 or data[:6] != b'\x7fELF\x02\x01'
            or struct.unpack_from('<H', data, 18)[0] != 62):
        raise Error('calendar executable is not x86-64 ELF')


def bootstrap(stage: Path, account: pwd.struct_passwd) -> None:
    home = Path(account.pw_dir)
    for parent in (home, home / '.config'):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid or info.st_mode & 0o077:
            raise Error('untrusted calendar account directory')
    destination = home / '.config/calix'
    try:
        destination.mkdir(mode=0o700)
        os.chown(destination, account.pw_uid, account.pw_gid)
    except FileExistsError:
        pass
    info = destination.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise Error('untrusted Calix configuration directory')
    credentials = {}
    for field in ('username', 'password'):
        fd = os.open(stage / field, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
                raise Error('untrusted private Fruux input')
            data = stream.read(4097)
        if not data or len(data) > 4096 or b'\0' in data:
            raise Error('invalid private Fruux input')
        credentials[field] = data.decode('utf-8')
    credentials['username'] = credentials['username'].strip()
    if not credentials['username'] or any(ord(c) < 32 for c in credentials['username']):
        raise Error('invalid Fruux account identifier')
    path = destination / 'fruux-bootstrap.json'
    # Never replace user-owned credentials on a repeated installation step.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        os.fchown(stream.fileno(), account.pw_uid, account.pw_gid)
        stream.write((json.dumps(credentials, ensure_ascii=True) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    # Non-secret account identity for the direct CalDAV actions. The password
    # remains solely in the one-time bootstrap and then in Secret Service.
    account_path = destination / 'fruux-account.json'
    fd = os.open(account_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        os.fchown(stream.fileno(), account.pw_uid, account.pw_gid)
        stream.write((json.dumps({'version': 1, 'server': 'https://dav.fruux.com',
                                  'username': credentials['username']}, ensure_ascii=True) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(destination, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> None:
    if os.geteuid() != 0 or len(sys.argv) != 2:
        raise Error('calendar installation requires a private target stage')
    architecture = subprocess.run(['/usr/bin/dpkg', '--print-architecture'],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, timeout=10, check=True)
    if architecture.stdout != b'amd64\n':
        raise Error('calendar release architecture differs from target')
    stage = Path(sys.argv[1])
    if not re.fullmatch(r'/tmp/installer-calendar\.[A-Za-z0-9]+', str(stage)):
        raise Error('invalid calendar stage')
    info = stage.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise Error('untrusted calendar stage')
    pins = {
        'waycal': ('0.2.1', 'b9b5abd73fbaebf0756157ad141e509410ff181c',
                   'b2d7a98129f3b5444d9597e8e263b0f590dfc268e38c30b5ae6c78a832b1004b',
                   'ForrestKnight/waycal', 'waycal-0.2.1-x86_64-linux', 'waycal'),
        'calix': ('0.8.0', '56fb3aae672384af2a304f69815c3a8d601e7f35',
                  '935257aed019834e3d79f127bb14b575ee2cbb32b33baa8f4b9c12e50efedb64',
                  'ianswope/calix', 'calix-0.8.0-linux-x86_64', 'bin/calix'),
    }
    candidates = []
    for app, (version, commit, digest, repository, root, binary) in pins.items():
        prefix = app.upper()
        url = f'https://github.com/{repository}/releases/download/v{version}/{root}.tar.gz'
        if any(os.environ.get(prefix + '_' + field) != value for field, value in {
                'VERSION': version, 'COMMIT': commit, 'SHA256': digest, 'URL': url,
                'MAXIMUM_BYTES': '16777216'}.items()):
            raise Error('calendar profile release pins do not match the supported contract')
        wanted = {binary, 'LICENSE' if app == 'waycal' else 'share/doc/calix/LICENSE'}
        icon = 'share/icons/hicolor/scalable/apps/com.ianswope.Calix.svg'
        if app == 'calix':
            wanted.add(icon)
        assets = members(download(url, digest, 16777216), root, wanted)
        elf(assets[binary])
        candidates.append((app, binary, assets, {'version': version, 'commit': commit, 'sha256': digest, 'url': url,
                                               'executable_sha256': hashlib.sha256(assets[binary]).hexdigest()}))
    # All candidates are checked before publishing either application.
    for app, binary, assets, receipt in candidates:
        publish(Path('/opt') / app / app, assets[binary], 0o755)
        publish(Path('/opt') / app / 'release.json', (json.dumps(receipt, sort_keys=True) + '\n').encode())
        license_path = 'LICENSE' if app == 'waycal' else 'share/doc/calix/LICENSE'
        publish(Path('/usr/local/share/doc') / app / 'LICENSE', assets[license_path])
        if app == 'calix':
            publish(Path('/usr/local/share/icons/hicolor/scalable/apps/com.ianswope.Calix.svg'), assets[icon])
    account = pwd.getpwnam(os.environ['ACCOUNT_USERNAME'])
    if account.pw_uid == 0 or account.pw_dir != os.environ['ACCOUNT_HOME']:
        raise Error('calendar account identity mismatch')
    install_agenda()
    bootstrap(stage, account)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Upstream exceptions can include URLs or credential-derived values.
        print('calendar-install: installation failed; private inputs retained until installer cleanup', file=sys.stderr)
        raise SystemExit(1) from None
