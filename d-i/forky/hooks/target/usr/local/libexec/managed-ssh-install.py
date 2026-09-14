#!/usr/bin/python3 -I
"""Privileged, installer-only Git identity provisioning. No secret in argv/env.

Inputs: an encrypted private/public pair in private staging, passphrase on stdin.
SSH_ASKPASS reads an anonymous sealed memfd. Only the encrypted key and a
GPG-encrypted passphrase survive. This program never downloads a private key.
"""
from __future__ import annotations
import argparse
import base64
import contextlib
import fcntl
import os
from pathlib import Path
import pwd
import re
import resource
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time

CODEX_URL = 'git@gitlab.com:computes/misc/codex-home.git'
CODEX_BRANCH = 'mcr/main'
HOSTS = '/etc/ssh/managed_git_known_hosts'
ASKPASS = '/usr/local/libexec/managed-ssh-install-askpass'
BASE_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C.UTF-8',
            'HOME': '/root', 'USER': 'root', 'LOGNAME': 'root'}

class InstallError(ValueError):
    pass

def checked(argv: list[str], *, env: dict[str, str] | None = None,
            data: bytes | None = None, timeout: int = 120,
            umask: int = -1) -> bytes:
    """Kill the entire child process group on timeout/cancellation; hide output."""
    proc = subprocess.Popen(argv, env=env or BASE_ENV, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            start_new_session=True, umask=umask)
    try:
        output, _ = proc.communicate(data, timeout=timeout)
        if proc.returncode:
            raise InstallError(f'{Path(argv[0]).name} failed (status {proc.returncode})')
        return output
    finally:
        # Also covers interrupted ssh-add/askpass descendants.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()

def read_direct(path: Path, limit: int, uid: int = 0, *, public: bool = False) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != uid
                or stat.S_IMODE(st.st_mode) not in ((0o600, 0o644) if public else (0o600,))
                or st.st_size > limit):
            raise InstallError('unsafe identity input metadata')
        value = os.read(fd, limit + 1)
        if not value or len(value) > limit:
            raise InstallError('empty or oversized identity input')
        return value
    finally:
        os.close(fd)

def encrypted_openssh(data: bytes) -> None:
    """Reject unencrypted keys before asking ssh-add to validate the full key."""
    lines = data.strip().splitlines()
    if (not lines or lines[0] != b'-----BEGIN OPENSSH PRIVATE KEY-----'
            or lines[-1] != b'-----END OPENSSH PRIVATE KEY-----'):
        raise InstallError('an encrypted OpenSSH private key is required')
    try:
        raw = base64.b64decode(b''.join(lines[1:-1]), validate=True)
        if not raw.startswith(b'openssh-key-v1\0'):
            raise ValueError()
        offset = 15
        fields = []
        for _ in range(3):
            length = struct.unpack_from('>I', raw, offset)[0]
            offset += 4
            if length > len(raw) - offset:
                raise ValueError()
            fields.append(raw[offset:offset+length]); offset += length
        if fields[0] == b'none' or fields[1] != b'bcrypt' or not fields[2]:
            raise ValueError()
    except (ValueError, struct.error) as exc:
        raise InstallError('private key is malformed or not passphrase-encrypted') from exc

@contextlib.contextmanager
def temporary_agent(stage: Path, secret: bytes):
    """Private, supervised agent. The secret's only file is anonymous RAM."""
    fd = os.memfd_create('managed-ssh-passphrase', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    agent = None
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, secret + b'\n')
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
        sock = stage / 'agent.sock'
        env = dict(BASE_ENV, SSH_AUTH_SOCK=str(sock), SSH_ASKPASS=ASKPASS,
                   SSH_ASKPASS_REQUIRE='force',
                   MANAGED_SSH_PASSPHRASE_FD=f'/proc/{os.getpid()}/fd/{fd}')
        agent = subprocess.Popen(['/usr/bin/ssh-agent', '-D', '-a', str(sock)],
                                 env=BASE_ENV, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        for _ in range(100):
            if agent.poll() is not None:
                raise InstallError('temporary SSH agent exited')
            if sock.exists() and stat.S_ISSOCK(sock.lstat().st_mode):
                break
            time.sleep(.05)
        else:
            raise InstallError('temporary SSH agent did not become ready')
        checked(['/usr/bin/ssh-add', '-q', str(stage/'private')], env=env)
        checked(['/usr/bin/ssh-add', '-T', str(stage/'public')], env=env)
        if len(checked(['/usr/bin/ssh-add', '-L'], env=env).splitlines()) != 1:
            raise InstallError('temporary agent must contain exactly one identity')
        # Neither the SSH client nor Git needs the askpass channel after loading.
        for name in ('SSH_ASKPASS', 'SSH_ASKPASS_REQUIRE', 'MANAGED_SSH_PASSPHRASE_FD'):
            env.pop(name)
        yield env
    finally:
        if agent is not None:
            try:
                os.killpg(agent.pid, signal.SIGTERM)
                agent.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(agent.pid, signal.SIGKILL); agent.wait()
            except ProcessLookupError:
                agent.wait()
        os.close(fd)
        (stage/'agent.sock').unlink(missing_ok=True)

def directory(path: Path, uid: int, gid: int) -> None:
    """No symlinked or other-user-writable parent in a managed destination."""
    if path == Path('/'):
        return
    directory(path.parent, uid, gid)
    try:
        st = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=0o700)
        os.chown(path, uid, gid)
        st = path.lstat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid not in (0, uid)
            or stat.S_IMODE(st.st_mode) & 0o022):
        raise InstallError('unsafe destination directory')

def publish(path: Path, data: bytes, uid: int, gid: int, mode: int = 0o600) -> None:
    directory(path.parent, uid, gid)
    if path.exists() or path.is_symlink():
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != uid:
            raise InstallError('unsafe existing managed identity file')
    fd, name = tempfile.mkstemp(prefix='.managed-ssh-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode); os.fchown(stream.fileno(), uid, gid)
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)

def publish_pair(home: Path, private: bytes, public: bytes, uid: int, gid: int) -> None:
    values = {home/'.local/share/managed-ssh/private/id_git_ed25519': private,
              home/'.ssh/id_git_ed25519.pub': public}
    saved = {}
    for path in values:
        directory(path.parent,uid,gid)
        saved[path] = (read_direct(path,16384,uid,public=path.name.endswith('.pub')),
                       stat.S_IMODE(path.lstat().st_mode)) if path.exists() or path.is_symlink() else None
    written = []
    try:
        for path,data in values.items():
            publish(path,data,uid,gid)
            written.append(path)
    except BaseException:
        for path in written:
            if saved[path] is None:
                path.unlink(missing_ok=True)
            else:
                publish(path,saved[path][0],uid,gid,saved[path][1])
        raise

def seal(account: pwd.struct_passwd, home: Path, secret: bytes) -> None:
    gnupg = home/'.gnupg'
    st = gnupg.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != account.pw_uid or stat.S_IMODE(st.st_mode) != 0o700:
        raise InstallError('managed GPG home is not ready')
    prefix = ['/usr/sbin/runuser', '-u', account.pw_name, '--', '/usr/bin/env', '-i',
              f'HOME={home}', f'GNUPGHOME={gnupg}', f'USER={account.pw_name}',
              f'LOGNAME={account.pw_name}', 'PATH=/usr/bin:/bin', 'LC_ALL=C.UTF-8',
              '/usr/bin/gpg', '--no-options', '--batch']
    listing = checked(prefix + ['--with-colons', '--list-secret-keys']).decode()
    fingerprints = []
    primary = False
    for line in listing.splitlines():
        fields = line.split(':')
        if fields[0] == 'sec':
            if fields[1] in ('r', 'e', 'd') or 'e' not in fields[11].lower():
                raise InstallError('managed GPG key cannot encrypt')
            primary = True
        elif fields[0] == 'fpr' and primary:
            fingerprints.append(fields[9]); primary = False
    if len(fingerprints) != 1 or not re.fullmatch(r'[0-9A-F]{40,64}', fingerprints[0]):
        raise InstallError('exactly one managed encryption-capable GPG identity is required')
    ciphertext = checked(prefix + ['--trust-model', 'always', '--recipient', fingerprints[0],
                                   '--output', '-', '--encrypt'], data=secret)
    if not ciphertext or ciphertext == secret:
        raise InstallError('GPG did not produce ciphertext')
    publish(home/'.local/share/managed-ssh/git-key-passphrase.gpg', ciphertext,
            account.pw_uid, account.pw_gid)

def clone(destination: Path, stage: Path, agent_env: dict[str, str]) -> None:
    # Only the approved URL/branch, an empty template and explicit SSH policy.
    # Do not consult root's or the user's Git/SSH configuration during install.
    if not re.fullmatch(r'/data/codex/\.home-clone\.[A-Za-z0-9]+/repository', str(destination)):
        raise InstallError('unapproved Codex clone destination')
    if destination.exists() or destination.is_symlink():
        raise InstallError('Codex clone destination already exists')
    parent = destination.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or stat.S_IMODE(parent.st_mode) != 0o700:
        # The allocator must clear inherited setgid; do not accept 2700 here.
        # Metadata only: never disclose keys, passphrases or child output.
        raise InstallError(
            'unsafe Codex clone staging parent: expected root-owned direct directory '
            f'mode 0700; found uid={parent.st_uid}, '
            f'mode={stat.S_IMODE(parent.st_mode):04o}, '
            f'directory={stat.S_ISDIR(parent.st_mode)}')
    ssh_config = stage/'ssh_config'
    ssh_config.write_text(f'''Host gitlab.com
  User git
  Hostname gitlab.com
  IdentityAgent SSH_AUTH_SOCK
  IdentityFile {stage}/public
  IdentitiesOnly yes
  BatchMode yes
  StrictHostKeyChecking yes
  UserKnownHostsFile {HOSTS}
  GlobalKnownHostsFile /dev/null
  HostKeyAlgorithms ssh-ed25519
  ForwardAgent no
  PasswordAuthentication no
  KbdInteractiveAuthentication no
  ConnectTimeout 15
  ServerAliveInterval 15
  ServerAliveCountMax 3
''')
    ssh_config.chmod(0o600)
    # Staging names are generated from a fixed safe alphabet above.
    env = dict(agent_env, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_TERMINAL_PROMPT='0', GIT_SSH_VARIANT='ssh',
               GIT_SSH_COMMAND=f'/usr/bin/ssh -F {ssh_config}')
    # Only Git's checkout child uses ordinary repository modes. Its enclosing
    # stage is still root-only 0700; the parent and credential commands retain
    # umask 077. Otherwise published root-owned /etc/codex files stay unreadable.
    checked(['/usr/bin/git', '-c', 'core.hooksPath=/dev/null', 'clone', '--template=',
             '--no-hardlinks', '--single-branch', '--branch', CODEX_BRANCH,
             '--no-tags', '--', CODEX_URL, str(destination)], env=env, timeout=300,
            umask=0o022)
    actual = checked(['/usr/bin/git', '-C', str(destination), 'symbolic-ref', '--short', 'HEAD'], env=env)
    upstream = checked(['/usr/bin/git', '-C', str(destination), 'rev-parse', '--abbrev-ref', '@{upstream}'], env=env)
    if actual.strip() != b'mcr/main' or upstream.strip() != b'origin/mcr/main':
        raise InstallError('Codex clone is not tracking origin/mcr/main')
    # -c core.hooksPath is process-only; no installer agent/config path persists.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('provision', 'seal', 'clone-codex'))
    parser.add_argument('account')
    parser.add_argument('stage', type=Path)
    parser.add_argument('destination', nargs='?', type=Path)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, lambda number, _frame: sys.exit(128 + number))
    try:
        if os.geteuid() != 0:
            raise InstallError('installer action requires root')
        if not re.fullmatch(r'/tmp/managed-git-ssh\.[A-Za-z0-9]+', str(args.stage)):
            raise InstallError('unapproved installer staging path')
        st = args.stage.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700:
            raise InstallError('unsafe installer staging directory')
        secret = sys.stdin.buffer.read(4097)
        if not secret or len(secret) > 4096 or any(b < 32 or b == 127 for b in secret):
            raise InstallError('passphrase must be nonempty single-line text, at most 4096 bytes')
        account = pwd.getpwnam(args.account)
        home = Path(account.pw_dir)
        if account.pw_uid == 0 or not str(home).startswith('/home/'):
            raise InstallError('primary desktop account/home is invalid')
        private = read_direct(args.stage/'private', 16384)
        public = read_direct(args.stage/'public', 4096)
        encrypted_openssh(private)
        if len(public.splitlines()) != 1 or not public.startswith(b'ssh-ed25519 '):
            raise InstallError('exactly one Ed25519 public key is required')
        with temporary_agent(args.stage, secret) as env:
            if args.action == 'provision':
                publish_pair(home,private,public,account.pw_uid,account.pw_gid)
            elif args.action == 'seal':
                # Reject mismatched staging versus already-provisioned identity.
                if read_direct(home/'.local/share/managed-ssh/private/id_git_ed25519', 16384, account.pw_uid) != private:
                    raise InstallError('installed SSH identity differs from the initrd identity')
                if read_direct(home/'.ssh/id_git_ed25519.pub', 4096, account.pw_uid, public=True) != public:
                    raise InstallError('installed SSH public key differs from initrd')
                seal(account, home, secret)
            else:
                if args.destination is None:
                    raise InstallError('Codex clone destination is required')
                clone(args.destination, args.stage, env)
    except (OSError, KeyError, ValueError, subprocess.SubprocessError) as exc:
        # No child output, passphrase, key bytes or environment in diagnostics.
        print(f'managed-ssh-install: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
