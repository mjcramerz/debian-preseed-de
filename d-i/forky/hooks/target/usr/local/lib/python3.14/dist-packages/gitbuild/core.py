from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import time
import uuid

from managed_workflows.fs import Tree, open_directory
from managed_workflows.process import CommandError, checked, environment

PACKAGE = re.compile(r'[a-z0-9][a-z0-9+.-]+\Z')
VERSION = re.compile(r'[0-9][A-Za-z0-9.+:~\-]*\Z')
JOB = re.compile(r'[0-9]{8}T[0-9]{6}-[0-9a-f]{12}\Z')
ARTIFACT = re.compile(r'[a-z0-9][A-Za-z0-9.+_~\-]*\.(?:deb|udeb|ddeb|dsc|changes|buildinfo|(?:orig\.)?tar\.(?:xz|gz|bz2|zst)|debian\.tar\.(?:xz|gz|bz2|zst))\Z')
WORKER = '/usr/local/libexec/gitbuild-worker'
PUBLISHER = '/usr/local/libexec/gitbuild-publish'


def private_child(parent: Path, name: str) -> Path:
    """Shared /pool parents are existing installer assets; children are private."""
    if not re.fullmatch(r'[a-z][a-z0-9-]*', name):
        raise ValueError('invalid private directory name')
    fd = open_directory(parent)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o002:
            raise ValueError(f'unsafe account storage: {parent}')
        try:
            os.mkdir(name, 0o700, dir_fd=fd)
            created = True
        except FileExistsError:
            created = False
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            info = os.fstat(child)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('build storage is not private')
            if created:
                os.fchmod(child, 0o700)  # clear inherited setgid
        finally:
            os.close(child)
    finally:
        os.close(fd)
    return parent / name


class RepositoryRequired(ValueError):
    pass


def workspace_repositories(workspace: Path) -> list[Path]:
    """Bounded, no-follow discovery for invocation from ~/Workspace itself."""
    result, pending, visited = [], [workspace], 0
    while pending:
        directory = pending.pop()
        visited += 1
        if visited > 10000:
            raise ValueError('Workspace discovery exceeded 10000 directories; run inside the desired repository')
        with Tree(directory) as tree:
            names = sorted(os.listdir(tree.fd))
            if '.git' in names:
                info = os.stat('.git', dir_fd=tree.fd, follow_symlinks=False)
                if ((stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) and
                        info.st_uid == os.getuid() and not info.st_mode & 0o022):
                    result.append(directory)
                continue
            if len(directory.relative_to(workspace).parts) >= 32:
                continue
            for name in names:
                if name.startswith('.') or name in {'target', 'node_modules', '__pycache__'}:
                    continue
                info = os.stat(name, dir_fd=tree.fd, follow_symlinks=False)
                if (stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and
                        not info.st_mode & 0o022 and all(c.isprintable() for c in name)):
                    pending.append(directory / name)
    return sorted(result)


class Context:
    def __init__(self, repository: Path | None = None):
        if os.getuid() == 0 or os.getuid() != os.geteuid():
            raise ValueError('gitbuild must run as the ordinary desktop account, never root')
        self.account = pwd.getpwuid(os.getuid())
        if not re.fullmatch(r'[A-Za-z0-9_.@+-]+', self.account.pw_name):
            raise ValueError('unsupported account name')
        self.home = Path(self.account.pw_dir)
        self.workspace = self.home / 'Workspace'
        with Tree(self.workspace):
            pass
        cwd = repository or Path.cwd()
        if not cwd.is_relative_to(self.workspace):
            raise ValueError('run gitbuild inside ~/Workspace or one of its repositories')
        env = environment()
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                   GIT_TERMINAL_PROMPT='0')
        try:
            root = checked(['/usr/bin/git', '-c', 'core.fsmonitor=false', '-c',
                            'core.hooksPath=/dev/null', 'rev-parse', '--show-toplevel'],
                           env=env, cwd=cwd, capture=True).strip()
        except CommandError as error:
            # Do not disguise a broken Git checkout as an empty workspace.
            parents = (cwd, *cwd.parents)
            if any((path / '.git').exists() for path in parents if path.is_relative_to(self.workspace)):
                raise
            raise RepositoryRequired('select a Git repository below ~/Workspace') from error
        self.repo = Path(root)
        if not self.repo.is_absolute() or not self.repo.is_relative_to(self.workspace):
            raise ValueError('the Git repository must be rooted below ~/Workspace')
        with Tree(self.workspace) as workspace:
            relative = str(self.repo.relative_to(self.workspace))
            if relative != '.':
                with workspace.parent(relative + '/.anchor'):
                    pass
        self.tree = Tree(self.repo)
        self.tree.mkdir('target/gitbuild')
        self.output = self.repo / 'target/gitbuild'
        self.cache = private_child(Path('/pool/cache') / self.account.pw_name, 'gitbuild')
        self.state = private_child(Path('/pool/db') / self.account.pw_name, 'gitbuild')
        self.arch = checked(['/usr/bin/dpkg', '--print-architecture'], capture=True).strip()
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', self.arch):
            raise ValueError('invalid native Debian architecture')
        self.tarball = self.cache / f'forky-{self.arch}.tar'
        self.jobs = max(1, min(os.cpu_count() or 1, 64))
        expected = {'GITBUILD_WORKSPACE': str(self.workspace),
                    'GITBUILD_CACHE_HOME': str(self.cache), 'GITBUILD_STATE_HOME': str(self.state),
                    'GITBUILD_DISTRIBUTION': 'forky'}
        for name, value in expected.items():
            if name in os.environ and os.environ[name] != value:
                raise ValueError(f'{name} differs from the managed account policy')

    def source_files(self) -> set[str]:
        """Tracked edits plus non-ignored new files, without running Git hooks."""
        env = environment()
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                   GIT_TERMINAL_PROMPT='0')
        git = ['/usr/bin/git', '-c', 'core.fsmonitor=false', '-c',
               'core.hooksPath=/dev/null', 'ls-files']
        index = checked([*git, '--stage', '-z'], env=env, cwd=self.repo, capture=True)
        if any(record.startswith('160000 ') for record in index.split('\0')):
            raise ValueError('submodules require a reviewed, flattened source tree; no implicit fetch or recursive build')
        records = checked([*git, '--cached', '--others', '--exclude-standard', '-z'],
                          env=env, cwd=self.repo, capture=True).split('\0')
        entries = set()
        for name in filter(None, records):
            if (name.endswith('/') or Path(name).is_absolute() or
                    any(part in ('', '.', '..', '.git') for part in name.split('/')) or
                    any(not c.isprintable() for c in name)):
                raise ValueError('unsupported source filename or nested Git repository')
            if name.split('/')[0] != 'target' and not name.split('/')[0].startswith('.gitbuild-debian-'):
                entries.add(name)
        if len(entries) > 250000:
            raise ValueError('source snapshot exceeds 250000 files')
        return entries

    def metadata(self) -> tuple[str, str]:
        raw = self.tree.read('debian/changelog').decode('utf-8')
        match = re.match(r'([a-z0-9][a-z0-9+.-]+) \(([^\s()]+)\) ', raw)
        if not match or not VERSION.fullmatch(match[2]):
            raise ValueError('debian/changelog has an invalid source name or version')
        checked(['/usr/bin/dpkg', '--validate-version', match[2]], capture=True)
        return match[1], match[2]

    def new_job(self, kind: str) -> Path:
        name = time.strftime('%Y%m%dT%H%M%S', time.gmtime()) + '-' + uuid.uuid4().hex[:12]
        self.tree.mkdir('target/gitbuild/' + name)
        job = self.output / name
        with Tree(job, private=True) as tree:
            tree.mkdir('home/.config')
            tree.mkdir('tmp')
            tree.mkdir('work')
            tree.mkdir('artifacts')
            tree.put_json('job.json', {'schema': 1, 'kind': kind, 'status': 'pending',
                                      'repository': str(self.repo), 'artifacts': {}})
        return job

    def completed(self) -> list[Path]:
        result = []
        for path in sorted(self.output.iterdir(), reverse=True):
            if not JOB.fullmatch(path.name):
                continue
            with Tree(path, private=True) as tree:
                record = tree.json('job.json', {})
                if record.get('status') == 'complete' and record.get('artifacts'):
                    result.append(path)
        return result


def snapshot(repo: Path, destination: Path, *, packaging: bool = True,
             entries: set[str] | None = None) -> None:
    """Snapshot current working files, including uncommitted edits, not .git.

    Reject external symlinks, devices, hardlinks and writable shared source
    files; no Git filters, hooks, submodule commands or archive attributes run.
    """
    count = 0
    # Prefixes permit descending only into directories containing selected files.
    selected = None if entries is None else set(entries)
    directories = set()
    for name in selected or ():
        parts = name.split('/')
        if any(part in ('', '.', '..') for part in parts):
            raise ValueError('invalid snapshot inventory')
        directories.update('/'.join(parts[:index]) for index in range(1, len(parts)))
    destination.mkdir(mode=0o700)
    with Tree(repo) as source, Tree(destination) as target:
        def copy_directory(relative: str):
            nonlocal count
            with source.parent((relative + '/' if relative else '') + '.anchor') as (fd, _):
                entries = sorted(os.listdir(fd))
                for name in entries:
                    if (not relative and name in ('.git', 'target')) or name == '.git':
                        continue
                    if not packaging and not relative and name == 'debian':
                        continue
                    rel = (relative + '/' if relative else '') + name
                    if selected is not None and rel not in selected and rel not in directories:
                        continue
                    count += 1
                    if count > 250000:
                        raise ValueError('source snapshot exceeds 250000 entries')
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if info.st_uid != os.getuid() or (not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022):
                        raise ValueError(f'unsafe shared source: {rel}')
                    if stat.S_ISDIR(info.st_mode):
                        target.mkdir(rel)
                        copy_directory(rel)
                        with target.parent(rel) as (out, leaf):
                            os.chmod(leaf, 0o755, dir_fd=out, follow_symlinks=False)
                    elif stat.S_ISREG(info.st_mode):
                        target.copy(rel, source, rel, mode=0o755 if info.st_mode & 0o111 else 0o644,
                                    limit=512 * 1024 * 1024)
                    elif stat.S_ISLNK(info.st_mode):
                        link = os.readlink(name, dir_fd=fd)
                        resolved = (repo / rel).resolve(strict=True)
                        if Path(link).is_absolute() or not resolved.is_relative_to(repo):
                            raise ValueError(f'source symlink escapes the repository: {rel}')
                        resolved_name = str(resolved.relative_to(repo))
                        if selected is not None and resolved_name not in selected and resolved_name not in directories:
                            raise ValueError('source symlink targets an ignored or missing source')
                        if (not packaging and resolved.relative_to(repo).parts[0] == 'debian') or any(p in ('.git', 'target') for p in resolved.relative_to(repo).parts):
                            raise ValueError('source symlink targets excluded build state')
                        with target.parent(rel, create=True) as (out, leaf):
                            os.symlink(link, leaf, dir_fd=out)
                    else:
                        raise ValueError(f'special source file refused: {rel}')
        copy_directory('')


def artifact_digest(path: Path) -> str:
    with Tree(path.parent) as tree:
        with tree.open_read(path.name) as (stream, _):
            return hashlib.file_digest(stream, 'sha256').hexdigest()


def record_artifacts(job: Path, *, complete: bool = True) -> None:
    artifacts = {}
    with Tree(job / 'artifacts') as tree:
        for name in sorted(os.listdir(tree.fd)):
            if not ARTIFACT.fullmatch(name):
                raise ValueError(f'unexpected output in artifact directory: {name!r}')
            artifacts[name] = artifact_digest(job / 'artifacts' / name)
    with Tree(job) as tree:
        record = tree.json('job.json')
        record.update(status='complete' if complete else 'failed', artifacts=artifacts)
        tree.put_json('job.json', record)


def verified_artifacts(job: Path) -> list[Path]:
    if not JOB.fullmatch(job.name):
        raise ValueError('invalid job identity')
    with Tree(job, private=True) as tree:
        record = tree.json('job.json')
    if record.get('schema') != 1 or record.get('status') != 'complete':
        raise ValueError('only complete jobs may be signed or published')
    entries = record.get('artifacts')
    if not isinstance(entries, dict) or not entries:
        raise ValueError('job has no build artifacts')
    paths = []
    for name, digest in entries.items():
        if not ARTIFACT.fullmatch(name) or not re.fullmatch(r'[0-9a-f]{64}', str(digest)):
            raise ValueError('invalid artifact manifest')
        path = job / 'artifacts' / name
        if artifact_digest(path) != digest:
            raise ValueError(f'artifact changed since build/signing: {name}')
        paths.append(path)
    return paths


def descriptor_files(path: Path) -> list[Path]:
    """Verify SHA256 and size before handing source/changes metadata to tools."""
    with Tree(path.parent) as tree:
        text = tree.read(path.name).decode('utf-8')
        matches = re.findall(r'^Checksums-Sha256:[^\S\n]*\n((?:[ \t].*\n)+)', text, re.M)
        if len(matches) != 1:
            raise ValueError('descriptor requires one Checksums-Sha256 field')
        result = []
        seen = set()
        for line in matches[0].splitlines():
            fields = line.split()
            if len(fields) != 3:
                raise ValueError('invalid checksum record')
            digest, size, name = fields
            if (not re.fullmatch(r'[0-9a-f]{64}', digest) or not size.isdecimal() or
                    not ARTIFACT.fullmatch(name) or name in seen or name == path.name):
                raise ValueError('unsafe descriptor filename or checksum')
            with tree.open_read(name) as (stream, info):
                if info.st_size != int(size) or hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                    raise ValueError(f'descriptor checksum mismatch: {name}')
            seen.add(name)
            result.append(path.parent / name)
        if not result:
            raise ValueError('empty source/changes descriptor')
        # debsign/dpkg also consume legacy checksum fields. They must not name
        # extra files, escape staging, or disagree with the SHA256 inventory.
        for field, width in (('Files', 32), ('Checksums-Sha1', 40)):
            fields = re.findall(r'^' + field + r':[^\S\n]*\n((?:[ \t].*\n)+)', text, re.M)
            if len(fields) > 1:
                raise ValueError('duplicate descriptor field')
            if not fields:
                continue
            listed = set()
            for line in fields[0].splitlines():
                row = line.split()
                if (len(row) not in ((3, 5) if field == 'Files' else (3,)) or
                        not re.fullmatch(r'[0-9a-f]{' + str(width) + '}', row[0]) or
                        not row[1].isdecimal() or row[-1] not in seen or row[-1] in listed):
                    raise ValueError('unsafe legacy checksum inventory')
                listed.add(row[-1])
            if listed != seen:
                raise ValueError('descriptor checksum inventories disagree')
    return result


def require_subids() -> None:
    account = pwd.getpwuid(os.getuid())
    for filename in ('/etc/subuid', '/etc/subgid'):
        found = False
        for line in Path(filename).read_text().splitlines():
            fields = line.split(':')
            if len(fields) == 3 and fields[0] in (account.pw_name, str(account.pw_uid)):
                if fields[1].isdecimal() and fields[2].isdecimal() and int(fields[2]) >= 65536:
                    found = True
        if not found:
            raise ValueError(f'{filename} needs an administrator-assigned range of at least 65536 IDs')
