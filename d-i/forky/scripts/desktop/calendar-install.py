#!/usr/bin/python3 -I
"""Install pinned calendar release data in the offline target, without launch."""
from __future__ import annotations

import hashlib
import http.client
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


class DownloadUnavailable(Error):
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


def release_pin(prefix: str) -> dict[str, str]:
    fields = ('VERSION', 'COMMIT', 'SHA256', 'URL', 'MAXIMUM_BYTES')
    values = {field: os.environ.get(f'{prefix}_{field}', '') for field in fields}
    if (not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', values['VERSION'])
            or not re.fullmatch(r'[0-9a-f]{40}', values['COMMIT'])
            or not re.fullmatch(r'[0-9a-f]{64}', values['SHA256'])
            or not re.fullmatch(r'[1-9][0-9]{0,11}', values['MAXIMUM_BYTES'])):
        raise Error(f'{prefix} release pin is incomplete or malformed')
    parsed = urllib.parse.urlsplit(values['URL'])
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.port not in (None, 443)
            or not parsed.path.endswith('.tar.gz')
            or '/releases/download/' not in parsed.path):
        raise Error(f'{prefix} release URL is malformed')
    return values


def download(url: str, digest: str, maximum: int) -> bytes:
    # Retry only release acquisition, before publishing files or credentials.
    # Each socket operation has a stall timeout; active streams have no total
    # elapsed-time cap. Restart from the pinned URL to renew signed redirects.
    for attempt in range(4):
        try:
            return download_attempt(url, digest, maximum)
        except (OSError, http.client.HTTPException, DownloadUnavailable):
            if attempt == 3:
                raise Error('calendar release transport failed after retries') from None
            time.sleep(2 ** attempt)
    raise Error('calendar release transport failed after retries')


def download_attempt(url: str, digest: str, maximum: int) -> bytes:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for hop in range(5):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname
                or parsed.username or parsed.password
                or parsed.fragment or parsed.port not in (None, 443)):
            raise Error('calendar release redirect rejected')
        try:
            response = opener.open(urllib.request.Request(url, headers={'User-Agent': 'preseed-calendar-installer'}),
                                   timeout=300)
        except urllib.error.HTTPError as error:
            with error:
                if error.code in {408, 429} or 500 <= error.code <= 599:
                    raise DownloadUnavailable('calendar release endpoint is temporarily unavailable') from None
                location = error.headers.get('Location')
                if error.code not in {301, 302, 303, 307, 308} or not location or hop == 4:
                    raise Error('calendar release HTTP failure') from None
                url = urllib.parse.urljoin(url, location)
                continue
        with response:
            length = response.headers.get('Content-Length')
            if length is not None and (not re.fullmatch(r'[0-9]{1,12}', length)
                                       or int(length) > maximum):
                raise Error('calendar release content length exceeds its limit or is invalid')
            data = bytearray()
            while True:
                block = response.read1(min(65536, maximum + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
                if len(data) > maximum:
                    raise Error('calendar release download limit exceeded')
            if length is not None and len(data) != int(length):
                raise DownloadUnavailable('calendar release transfer was interrupted')
        if hashlib.sha256(data).hexdigest() != digest:
            raise Error('calendar release SHA-256 mismatch')
        return bytes(data)
    raise Error('calendar release redirect limit exceeded')


def members(data: bytes, root: str, wanted: set[str], *,
            member_limit: int, extra_member_pattern: str,
            maximum_expanded_bytes: int, maximum_member_bytes: int) -> dict[str, bytes]:
    # Bound expanded bytes before tarfile can materialize extension headers.
    with gzip.GzipFile(fileobj=io.BytesIO(data), mode='rb') as compressed:
        expanded = compressed.read(maximum_expanded_bytes + 1)
    if len(expanded) > maximum_expanded_bytes:
        raise Error('calendar release expansion limit exceeded')
    result = {}
    seen = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(expanded), mode='r|') as archive:
        for index, member in enumerate(archive):
            path = PurePosixPath(member.name)
            if (index >= member_limit or len(member.name) > 512 or path.is_absolute()
                    or '..' in path.parts or not path.parts or path.parts[0] != root
                    or path.as_posix() in seen or path.as_posix() != member.name.rstrip('/')
                    or not (member.isfile() or member.isdir())
                    or member.size < 0 or member.size > maximum_member_bytes):
                raise Error('unsafe calendar release member')
            seen.add(path.as_posix())
            total += member.size
            if total > maximum_expanded_bytes:
                raise Error('calendar release expansion limit exceeded')
            relative = '/'.join(path.parts[1:])
            extra = extra_member_pattern and re.fullmatch(extra_member_pattern, relative)
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


def release_metadata(prefix: str, *, agenda: bool = False) -> dict[str, str]:
    if agenda:
        if prefix != 'AGENDA':
            raise Error('unsupported Agenda calendar release')
        return {
            'APPLICATION': 'com.github.dahenson.agenda',
            'BINARY_MEMBER': 'rootfs/usr/bin/com.github.dahenson.agenda',
            'SCHEMA_MEMBER': 'rootfs/usr/share/glib-2.0/schemas/com.github.dahenson.agenda.gschema.xml',
            'LICENSE_MEMBER': 'rootfs/usr/share/doc/agenda/copyright',
            'ICON_MEMBER': 'rootfs/usr/share/icons/hicolor/128x128/apps/com.github.dahenson.agenda.svg',
            'BUILD_INFO_MEMBER': 'BUILD-INFO.json',
            'PREFIX_MEMBER': 'prefix.txt',
            'EXTRA_MEMBER_PATTERN': (
                r'rootfs/usr/share/(?:locale/[A-Za-z_@]+/LC_MESSAGES/'
                r'com\.github\.dahenson\.agenda\.mo|icons/hicolor/'
                r'(?:16|24|32|48|64|128)x(?:16|24|32|48|64|128)(?:@2)?/apps/'
                r'com\.github\.dahenson\.agenda\.svg)'),
            'INSTALL_BINARY': '/usr/local/bin/com.github.dahenson.agenda',
            'INSTALL_LICENSE': '/usr/local/share/doc/agenda/copyright',
            'RECEIPT_PATH': '/usr/local/share/agenda/release.json',
            'INSTALL_ICON': '/usr/local/share/icons/hicolor/128x128/apps/com.github.dahenson.agenda.svg',
            'SCHEMA_INSTALL_PATH': '/usr/local/share/agenda/schemas/com.github.dahenson.agenda.gschema.xml',
            'COMPILED_SCHEMA_PATH': '/usr/local/share/agenda/schemas/gschemas.compiled',
            'BUILD_INFO_INSTALL_PATH': '/usr/local/share/doc/agenda/BUILD-INFO.json',
            'LOCALE_INSTALL_ROOT': '/usr/share',
            'ICON_INSTALL_ROOT': '/usr/local/share',
            'BUILD_PREFIX': '/usr',
            'ARCHITECTURE': 'amd64',
            'WORKING_TREE_MODIFIED': 'true',
            'SHARE_MEMBER_PREFIX': 'rootfs/usr/share/',
            'LOCALE_MEMBER_PREFIX': 'locale/',
            'ICON_MEMBER_PREFIX': 'icons/',
            'CONFIG_RELATIVE_PATH': '.config/calix',
            'BOOTSTRAP_CREDENTIALS_NAME': 'fruux-bootstrap.json',
            'ACCOUNT_IDENTITY_NAME': 'fruux-account.json',
        }
    if prefix == 'WAYCAL':
        return {
            'BINARY_MEMBER': 'waycal',
            'LICENSE_MEMBER': 'LICENSE',
            'EXTRA_MEMBER_PATTERN': '',
            'INSTALL_BINARY': '/opt/waycal/waycal',
            'INSTALL_LICENSE': '/usr/local/share/doc/waycal/LICENSE',
            'RECEIPT_PATH': '/opt/waycal/release.json',
            'ICON_MEMBER': '',
            'INSTALL_ICON': '',
        }
    if prefix == 'CALIX':
        return {
            'BINARY_MEMBER': 'bin/calix',
            'LICENSE_MEMBER': 'share/doc/calix/LICENSE',
            'EXTRA_MEMBER_PATTERN': '',
            'INSTALL_BINARY': '/opt/calix/calix',
            'INSTALL_LICENSE': '/usr/local/share/doc/calix/LICENSE',
            'RECEIPT_PATH': '/opt/calix/release.json',
            'ICON_MEMBER': 'share/icons/hicolor/scalable/apps/com.ianswope.Calix.svg',
            'INSTALL_ICON': '/usr/local/share/icons/hicolor/scalable/apps/com.ianswope.Calix.svg',
        }
    raise Error('unsupported native calendar release')


def release_source(pin: dict[str, str]) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(pin['URL'])
    archive_root = PurePosixPath(parsed.path).name.removesuffix('.tar.gz')
    if (not archive_root or not re.fullmatch(r'[A-Za-z0-9._-]+', archive_root)
            or parsed.hostname is None):
        raise Error('calendar release URL is malformed')
    return pin['URL'], archive_root


def configured_archive_limits() -> tuple[int, int, int, int]:
    names = (
        'CALENDAR_ARCHIVE_MAXIMUM_EXTRACTED_BYTES',
        'CALENDAR_ARCHIVE_MAXIMUM_MEMBER_BYTES',
        'CALENDAR_NATIVE_ARCHIVE_MAXIMUM_MEMBERS',
        'AGENDA_ARCHIVE_MAXIMUM_MEMBERS',
    )
    values = []
    for name in names:
        value = os.environ.get(name, '')
        if not re.fullmatch(r'[1-9][0-9]{0,11}', value):
            raise Error(f'{name} is missing or malformed')
        values.append(int(value))
    expanded, member, native_members, agenda_members = values
    if member > expanded or native_members > 100000 or agenda_members > 100000:
        raise Error('calendar archive limits are inconsistent')
    return expanded, member, native_members, agenda_members


def install_agenda_release(pin: dict[str, str], metadata: dict[str, str],
                           url: str, archive_root: str,
                           archive_limits: tuple[int, int, int, int]) -> None:
    maximum_expanded_bytes, maximum_member_bytes, _, agenda_member_limit = archive_limits
    version = pin['VERSION']
    assets = members(
        download(url, pin['SHA256'], int(pin['MAXIMUM_BYTES'])),
        archive_root,
        {metadata['BINARY_MEMBER'], metadata['SCHEMA_MEMBER'],
         metadata['LICENSE_MEMBER'], metadata['ICON_MEMBER'],
         metadata['BUILD_INFO_MEMBER'], metadata['PREFIX_MEMBER']},
        member_limit=agenda_member_limit,
        extra_member_pattern=metadata['EXTRA_MEMBER_PATTERN'],
        maximum_expanded_bytes=maximum_expanded_bytes,
        maximum_member_bytes=maximum_member_bytes)
    elf(assets[metadata['BINARY_MEMBER']])
    build_metadata = json.loads(assets[metadata['BUILD_INFO_MEMBER']])
    if (assets[metadata['PREFIX_MEMBER']] != (metadata['BUILD_PREFIX'] + '\n').encode()
            or build_metadata.get('application') != metadata['APPLICATION']
            or build_metadata.get('architecture') != metadata['ARCHITECTURE']
            or build_metadata.get('version') != version
            or build_metadata.get('prefix') != metadata['BUILD_PREFIX']
            or not re.fullmatch(r'[0-9a-f]{40}', str(build_metadata.get('commit', '')))
            or build_metadata.get('working_tree_modified') != (metadata['WORKING_TREE_MODIFIED'] == 'true')):
        raise Error('calendar archive metadata differs')
    schema_path = Path(metadata['SCHEMA_INSTALL_PATH'])
    publish(schema_path, assets[metadata['SCHEMA_MEMBER']])
    compiled = Path(metadata['COMPILED_SCHEMA_PATH'])
    if compiled.exists() or compiled.is_symlink():
        info = compiled.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise Error('unsafe previous Agenda compiled schema')
    subprocess.run(['/usr/bin/glib-compile-schemas', '--strict', str(compiled.parent)],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}, timeout=15, check=True)
    info = compiled.lstat()
    compiled_schema_maximum = os.environ.get('AGENDA_COMPILED_SCHEMA_MAXIMUM_BYTES', '')
    if (not re.fullmatch(r'[1-9][0-9]{0,11}', compiled_schema_maximum)
            or not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_nlink != 1 or info.st_size > int(compiled_schema_maximum)):
        raise Error('unsafe compiled Agenda schema')
    publish(compiled, compiled.read_bytes())
    for name, data in assets.items():
        relative = name.removeprefix(metadata['SHARE_MEMBER_PREFIX'])
        if relative.startswith(metadata['LOCALE_MEMBER_PREFIX']):
            publish(Path(metadata['LOCALE_INSTALL_ROOT']) / relative, data)
        elif relative.startswith(metadata['ICON_MEMBER_PREFIX']):
            publish(Path(metadata['ICON_INSTALL_ROOT']) / relative, data)
    publish(Path(metadata['INSTALL_LICENSE']), assets[metadata['LICENSE_MEMBER']])
    publish(Path(metadata['BUILD_INFO_INSTALL_PATH']), assets[metadata['BUILD_INFO_MEMBER']])
    publish(Path(metadata['INSTALL_BINARY']), assets[metadata['BINARY_MEMBER']], 0o755)
    receipt = {key.lower(): value for key, value in pin.items() if key != 'MAXIMUM_BYTES'}
    receipt.update(url=url, executable_sha256=hashlib.sha256(assets[metadata['BINARY_MEMBER']]).hexdigest(),
                   schema_sha256=hashlib.sha256(assets[metadata['SCHEMA_MEMBER']]).hexdigest(),
                   build_commit=build_metadata['commit'],
                   working_tree_modified=build_metadata['working_tree_modified'])
    publish(Path(metadata['RECEIPT_PATH']), (json.dumps(receipt, sort_keys=True) + '\\n').encode())


def elf(data: bytes) -> None:
    if (len(data) < 64 or data[:6] != b'\x7fELF\x02\x01'
            or struct.unpack_from('<H', data, 18)[0] != 62):
        raise Error('calendar executable is not x86-64 ELF')


def bootstrap(stage: Path, account: pwd.struct_passwd, metadata: dict[str, str], server_url: str) -> None:
    home = Path(account.pw_dir)
    for parent in (home, home / '.config'):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid or info.st_mode & 0o077:
            raise Error('untrusted calendar account directory')
    destination = home / metadata['CONFIG_RELATIVE_PATH']
    try:
        destination.mkdir(mode=0o700)
        os.chown(destination, account.pw_uid, account.pw_gid)
    except FileExistsError:
        pass
    info = destination.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise Error('untrusted calendar configuration directory')
    credentials = {}
    for field in ('username', 'password'):
        fd = os.open(stage / field, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
                raise Error('untrusted private calendar input')
            data = stream.read(4097)
        if not data or len(data) > 4096 or b'\0' in data:
            raise Error('invalid private calendar input')
        credentials[field] = data.decode('utf-8')
    credentials['username'] = credentials['username'].strip()
    if (not credentials['username'] or ':' in credentials['username']
            or any(ord(c) < 32 or ord(c) == 127 for c in credentials['username'])):
        raise Error('invalid calendar account identifier')
    path = destination / metadata['BOOTSTRAP_CREDENTIALS_NAME']
    # Never replace user-owned credentials on a repeated installation step.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        os.fchown(stream.fileno(), account.pw_uid, account.pw_gid)
        stream.write((json.dumps(credentials, ensure_ascii=True) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    # Non-secret account identity for the direct CalDAV actions. The password
    # remains solely in the one-time bootstrap and then in Secret Service.
    account_path = destination / metadata['ACCOUNT_IDENTITY_NAME']
    fd = os.open(account_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        os.fchown(stream.fileno(), account.pw_uid, account.pw_gid)
        stream.write((json.dumps({'version': 1, 'server': server_url,
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
    archive_limits = configured_archive_limits()

    candidates = []
    for prefix in ('WAYCAL', 'CALIX'):
        pins = release_pin(prefix)
        metadata = release_metadata(prefix)
        url, archive_root = release_source(pins)
        print(f'calendar-install: downloading pinned {prefix.lower()} {pins["VERSION"]}', file=sys.stderr)
        wanted = {metadata['BINARY_MEMBER'], metadata['LICENSE_MEMBER']}
        if metadata['ICON_MEMBER']:
            wanted.add(metadata['ICON_MEMBER'])
        assets = members(
            download(url, pins['SHA256'], int(pins['MAXIMUM_BYTES'])),
            archive_root, wanted,
            member_limit=archive_limits[2],
            extra_member_pattern=metadata['EXTRA_MEMBER_PATTERN'],
            maximum_expanded_bytes=archive_limits[0],
            maximum_member_bytes=archive_limits[1])
        elf(assets[metadata['BINARY_MEMBER']])
        candidates.append((metadata, assets, {
            'version': pins['VERSION'],
            'commit': pins['COMMIT'],
            'sha256': pins['SHA256'],
            'url': url,
            'executable_sha256': hashlib.sha256(
                assets[metadata['BINARY_MEMBER']]).hexdigest()}))
    # All candidates are checked before publishing either application.
    for metadata, assets, receipt in candidates:
        publish(Path(metadata['INSTALL_BINARY']), assets[metadata['BINARY_MEMBER']], 0o755)
        publish(Path(metadata['RECEIPT_PATH']), (json.dumps(receipt, sort_keys=True) + '\n').encode())
        publish(Path(metadata['INSTALL_LICENSE']), assets[metadata['LICENSE_MEMBER']])
        if metadata['ICON_MEMBER']:
            publish(Path(metadata['INSTALL_ICON']), assets[metadata['ICON_MEMBER']])

    account = pwd.getpwnam(os.environ['ACCOUNT_USERNAME'])
    if account.pw_uid == 0 or account.pw_dir != os.environ['ACCOUNT_HOME']:
        raise Error('calendar account identity mismatch')
    server_url = os.environ.get('CALENDAR_CALDAV_SERVER_URL', '')
    parsed_server = urllib.parse.urlsplit(server_url)
    if (parsed_server.scheme != 'https' or not parsed_server.hostname
            or parsed_server.username or parsed_server.password
            or parsed_server.query or parsed_server.fragment
            or parsed_server.port not in (None, 443) or parsed_server.path not in ('', '/')):
        raise Error('calendar server URL is malformed')
    agenda_pin = release_pin('AGENDA')
    agenda_metadata = release_metadata('AGENDA', agenda=True)
    url, archive_root = release_source(agenda_pin)
    install_agenda_release(agenda_pin, agenda_metadata, url, archive_root, archive_limits)
    bootstrap(stage, account, agenda_metadata, server_url.rstrip('/'))


if __name__ == '__main__':
    try:
        main()
    except Error as error:
        # Our errors contain fixed diagnostics, never upstream URLs or secrets.
        print(f'calendar-install: installation failed: {error}', file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as error:
        # Upstream exceptions can include URLs or credential-derived values.
        print(f'calendar-install: installation failed ({type(error).__name__})', file=sys.stderr)
        raise SystemExit(1) from None
