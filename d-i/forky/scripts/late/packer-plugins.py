#!/usr/bin/python3 -I
"""Install the managed HCL's exact plugins from signed upstream binary releases.

Do not depend on version-enumeration/manifest fallback or GitHub API discovery.
The HCL stays the single version authority. No build or source patch is involved.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import zipfile

FINGERPRINT = 'C874011F0AB405110D02105534365D9472D7468F'
KEY_URL = 'https://www.hashicorp.com/.well-known/pgp-key.txt'
ORIGIN = 'https://releases.hashicorp.com'
# Proxmox remains a community-distributed GitHub release, unlike the six
# official plugins. Pin its published binary digests independently of transport.
# https://github.com/hashicorp/packer-plugin-proxmox/releases/tag/v1.2.4
COMMUNITY_RELEASES = {
    ('proxmox', '1.2.4', 'amd64'): '84a50e8204180756708671809df0f4ec7bcdde9d702c74c7c4e005d3ce9d89e5',
    ('proxmox', '1.2.4', 'arm64'): 'f416e2332a2e75cd3d03e99efbf75b7d0f8de0e85420dac39ac4cad0b7547bf4',
}
PLUGINS = frozenset(('amazon', 'ansible', 'azure', 'docker', 'googlecompute', 'proxmox', 'qemu'))
VERSION = r'[0-9]+\.[0-9]+\.[0-9]+'
ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'CHECKPOINT_DISABLE': '1'}


class Error(RuntimeError):
    """An installation prerequisite or authenticity check failed."""


def requirements(text: str) -> tuple[str, dict[str, str]]:
    # This is the intentionally small, managed template grammar, NOT a general
    # HCL parser. Fail closed on interpolation, extra blocks or non-exact pins.
    outer = re.fullmatch(r'\s*packer\s*\{\s*required_version\s*=\s*"= (' + VERSION +
                         r')"\s*required_plugins\s*\{(.*)\}\s*\}\s*', text, re.S)
    if not outer:
        raise Error('managed Packer template must contain only exact version requirements')
    body = outer[2]
    pattern = re.compile(r'\s*([a-z]+)\s*=\s*\{\s*source\s*=\s*"github\.com/hashicorp/([a-z]+)"'
                         r'\s*version\s*=\s*"= (' + VERSION + r')"\s*\}')
    plugins: dict[str, str] = {}
    while body.strip():
        match = pattern.match(body)
        if not match or match[1] != match[2] or match[1] in plugins:
            raise Error('ambiguous or unsupported managed Packer plugin requirement')
        plugins[match[1]] = match[3]
        body = body[match.end():]
    if plugins.keys() != PLUGINS:
        raise Error('managed Packer plugin inventory differs from the desktop policy')
    return outer[1], plugins


def regular(path: Path, limit: int) -> None:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or not 0 < value.st_size <= limit:
        raise Error(f'not a bounded, non-linked regular file: {path}')


def directory(path: Path, *, private: bool = False) -> None:
    if not path.is_absolute():
        raise Error('managed Packer paths must be absolute')
    for parent in (*reversed(path.parents), path):
        value = parent.lstat()
        if not stat.S_ISDIR(value.st_mode):
            raise Error(f'unsafe managed Packer directory: {parent}')
    value = path.stat()
    if private and (value.st_uid != os.geteuid() or value.st_mode & 0o077):
        raise Error(f'Packer plugin directory must be account-owned and private: {path}')


def fetch(url: str, destination: Path, limit: int, env: dict[str, str]) -> None:
    subprocess.run(['/usr/bin/curl', '--disable', '--fail', '--silent', '--show-error',
                    '--location', '--proto', '=https', '--proto-redir', '=https',
                    '--max-redirs', '4', '--connect-timeout', '15', '--max-time', '180',
                    '--retry', '2', '--retry-max-time', '240', '--max-filesize', str(limit),
                    '--output', str(destination), '--url', url],
                   env=env, stdin=subprocess.DEVNULL, check=True, timeout=270)
    regular(destination, limit)


def archive_checksum(text: str, name: str, version: str, arch: str) -> tuple[str, str]:
    # Accept the two upstream naming generations, never URLs or arbitrary paths.
    pattern = re.compile(r'packer-plugin-' + re.escape(name) + r'_(?:v)?' +
                         re.escape(version) + r'(?:_x[0-9]+\.[0-9]+)?_linux_' + re.escape(arch) + r'\.zip')
    matches = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 2 or not re.fullmatch(r'[0-9a-fA-F]{64}', fields[0]):
            raise Error('malformed signed plugin checksum file')
        filename = fields[1].removeprefix('*')
        if pattern.fullmatch(filename):
            matches.append((filename, fields[0].lower()))
    if len(matches) != 1:
        raise Error(f'no unique signed Linux {arch} release for {name} {version}')
    return matches[0]


def unpack(archive: Path, destination: Path, name: str, version: str, arch: str) -> Path:
    pattern = re.compile(r'packer-plugin-' + re.escape(name) + r'_v' + re.escape(version) +
                         r'_x[0-9]+\.[0-9]+_linux_' + re.escape(arch))
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 32 or sum(item.file_size for item in members) > 768 * 1024**2:
            raise Error('plugin release exceeds extraction limits')
        matches = []
        names = set()
        for member in members:
            if (not re.fullmatch(r'[A-Za-z0-9._-]{1,255}', member.filename) or
                    member.filename in ('.', '..') or member.filename in names or member.flag_bits & 1):
                raise Error('unexpected path inside plugin release')
            names.add(member.filename)
            mode = member.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise Error('non-regular member inside plugin release')
            if pattern.fullmatch(member.filename):
                matches.append(member)
        if len(matches) != 1:
            raise Error('plugin release has no unique expected executable')
        member = matches[0]
        output = destination / member.filename
        with bundle.open(member) as source, output.open('xb') as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
        regular(output, 768 * 1024**2)
        with output.open('rb') as source:
            header = source.read(20)
        machine = {'amd64': 62, 'arm64': 183}[arch]
        if (header[:6] != b'\x7fELF\x02\x01' or len(header) < 20 or
                int.from_bytes(header[18:20], 'little') != machine):
            raise Error('plugin executable does not match target ELF architecture')
        output.chmod(0o700)
        return output


def import_release_key(gpg: list[str], key: Path, env: dict[str, str]) -> None:
    listing = subprocess.check_output(gpg + ['--with-colons', '--import-options', 'show-only',
                                           '--import', str(key)], env=env, text=True, timeout=30)
    primary = []
    pending = False
    for line in listing.splitlines():
        fields = line.split(':')
        if fields[0] == 'pub':
            pending = True
        elif fields[0] == 'fpr' and pending:
            primary.append(fields[9])
            pending = False
    if primary != [FINGERPRINT]:
        raise Error('HashiCorp release signing-key fingerprint mismatch')
    subprocess.run(gpg + ['--import', str(key)], env=env, check=True, timeout=30)

def verify_checksums(gpg: list[str], signature: Path, sums: Path, env: dict[str, str]) -> None:
    status = subprocess.check_output(gpg + ['--status-fd=1', '--verify', str(signature), str(sums)],
                                     env=env, text=True, timeout=30)
    valid = [line.split() for line in status.splitlines() if line.startswith('[GNUPG:] VALIDSIG ')]
    if len(valid) != 1 or FINGERPRINT not in (valid[0][2], valid[0][-1]):
        raise Error('release checksum signature is not from the pinned HashiCorp key')


def verify_local_plugins(packer: Path, template: Path, root: Path,
                         plugins: dict[str, str], arch: str, env: dict[str, str]) -> None:
    """Check Packer's on-disk identities and its view of the managed HCL offline."""
    installed = subprocess.check_output([str(packer), 'plugins', 'installed'], env=env,
                                        text=True, timeout=30).splitlines()
    expected_paths = []
    for name, pin in plugins.items():
        prefix = root / 'github.com/hashicorp' / name
        pattern = re.compile(re.escape(str(prefix)) + r'/packer-plugin-' + re.escape(name) +
                             r'_v' + re.escape(pin) + r'_x[0-9]+\.[0-9]+_linux_' +
                             re.escape(arch))
        matches = [Path(line.strip()) for line in installed if pattern.fullmatch(line.strip())]
        if len(matches) != 1:
            raise Error(f'Packer does not recognize exactly one installed {name} {pin} plugin')
        binary = matches[0]
        directory(binary.parent)
        regular(binary, 768 * 1024**2)
        if not os.access(binary, os.X_OK):
            raise Error(f'installed Packer plugin is not executable: {name} {pin}')
        checksum = Path(str(binary) + '_SHA256SUM')
        regular(checksum, 128)
        digest = checksum.read_text(encoding='ascii').strip()
        if not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
            raise Error(f'invalid installed Packer checksum: {name} {pin}')
        with binary.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != digest.lower():
                raise Error(f'installed Packer plugin checksum mismatch: {name} {pin}')
        expected_paths.append(str(binary))
    # Unlike init, this command only reports matching locally installed
    # binaries. It catches an HCL/CLI constraint mismatch without attempting
    # a remote GitHub plugin discovery after authenticated installation.
    required = subprocess.check_output([str(packer), 'plugins', 'required', str(template)],
                                       env=env, text=True, timeout=60)
    if any(path not in required for path in expected_paths):
        raise Error('managed Packer template does not select every verified local plugin')


def install(template: Path, packer: Path, root: Path) -> None:
    if os.geteuid() == 0:
        raise Error('Packer plugins must be provisioned as the desktop account, not root')
    directory(template.parent)
    regular(template, 64 * 1024)
    directory(root)
    value = root.stat()
    if value.st_uid != os.geteuid() or value.st_mode & 0o007:
        raise Error('Packer plugin storage must be account-owned and not world-accessible')
    # The shared DevOps cache is normally 2770. Executable plugins and their
    # verification workspace are account-private, unlike ordinary cache data.
    root.chmod(0o700)
    directory(root, private=True)
    if not packer.is_absolute():
        raise Error('managed Packer executable path must be absolute')
    for path in (*reversed(packer.parents), packer):
        value = path.lstat()
        if (value.st_uid != 0 or value.st_mode & 0o022 or
                not (stat.S_ISDIR(value.st_mode) if path != packer else stat.S_ISREG(value.st_mode))):
            raise Error('managed Packer executable ancestry is not root-owned and protected')
    if not os.access(packer, os.X_OK):
        raise Error('managed Packer executable is not executable')
    version, plugins = requirements(template.read_text(encoding='utf-8'))
    arch = subprocess.check_output(['/usr/bin/dpkg', '--print-architecture'], text=True, env=ENV).strip()
    if arch not in ('amd64', 'arm64'):
        raise Error('unsupported managed plugin architecture')
    env = dict(ENV, HOME=str(Path.home()), PACKER_PLUGIN_PATH=str(root))
    # Packer probes plugin binaries with execve. Neither shared /tmp nor a
    # noexec /var/tmp is an appropriate staging directory for this operation.
    with tempfile.TemporaryDirectory(prefix='.init-', dir=root) as temporary:
        work = Path(temporary)
        env['TMPDIR'] = str(work)
        probe = work / 'exec-probe'
        shutil.copyfile('/usr/bin/true', probe)
        probe.chmod(0o700)
        try:
            subprocess.run([str(probe)], env=env, check=True, timeout=10)
        except OSError as exc:
            raise Error('Packer plugin storage is not executable; check mount and AppArmor policy') from exc
        probe.unlink()
        actual = subprocess.check_output([str(packer), 'version'], env=env, text=True, timeout=30)
        if not re.match(r'Packer v' + re.escape(version) + r'(?:\s|$)', actual):
            raise Error('managed Packer binary and exact HCL version disagree')
        home = work / 'gnupg'
        home.mkdir(mode=0o700)
        gpg = ['/usr/bin/gpg', '--no-options', '--no-autostart', '--batch', '--no-tty', '--homedir', str(home)]
        key = work / 'release-key.asc'
        fetch(KEY_URL, key, 256 * 1024, env)
        import_release_key(gpg, key, env)
        for name, pin in plugins.items():
            print(f'Installing authenticated Packer plugin {name} {pin}', flush=True)
            if name == 'proxmox':
                expected = COMMUNITY_RELEASES.get((name, pin, arch))
                if expected is None:
                    raise Error('the exact Proxmox release needs a reviewed binary digest pin')
                base = f'https://github.com/hashicorp/packer-plugin-{name}/releases/download/v{pin}/'
                filename = f'packer-plugin-{name}_v{pin}_x5.0_linux_{arch}.zip'
            else:
                base = f'{ORIGIN}/packer-plugin-{name}/{pin}/'
                sums_name = f'packer-plugin-{name}_{pin}_SHA256SUMS'
                sums, signature = work / sums_name, work / (sums_name + '.sig')
                fetch(base + sums_name, sums, 1024 * 1024, env)
                fetch(base + sums_name + '.sig', signature, 64 * 1024, env)
                verify_checksums(gpg, signature, sums, env)
                filename, expected = archive_checksum(sums.read_text(encoding='ascii'), name, pin, arch)
            archive = work / filename
            fetch(base + filename, archive, 256 * 1024**2, env)
            with archive.open('rb') as source:
                actual_hash = hashlib.file_digest(source, 'sha256').hexdigest()
            if actual_hash != expected:
                raise Error(f'checksum mismatch for authenticated {name} release; nothing executed')
            binary = unpack(archive, work, name, pin, arch)
            # Packer itself validates describe/protocol and writes its canonical
            # executable + SHA256SUM pair. Do not invent its on-disk cache format.
            subprocess.run([str(packer), 'plugins', 'install', '--path', str(binary),
                            f'github.com/hashicorp/{name}'], env=env, check=True, timeout=90)
            binary.unlink()
            archive.unlink()
        verify_local_plugins(packer, template, root, plugins, arch, env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('template', type=Path)
    parser.add_argument('packer', type=Path)
    parser.add_argument('plugin_root', type=Path)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise Error('Packer plugin initialization interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    os.umask(0o077)
    try:
        install(args.template, args.packer, args.plugin_root)
        return 0
    except (Error, OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(f'fatal: authenticated Packer plugin initialization failed: {exc}', file=__import__('sys').stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
