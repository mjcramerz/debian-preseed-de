"""Offline installation of verified theme data before consumer activation.

Asset directories are append-only. Existing matching assets are reused;
different existing bytes are refused. The public inventory is published last.
An interrupted publication retains its private candidate and journal instead
of guessing which published directory may be removed or silently retrying.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sysconfig
import time
import uuid
from managed_workflows.fs import Tree, parts
from .theme_archive import MAX_MEMBER
from .theme_assets import Candidate, MAX_FILES, Source, prepare

REGISTRY = Path('/usr/local/share/labwc-appearance')
SOURCE = REGISTRY / '.installer-themes'
PUBLIC = Path('/usr/share')
PENDING = 'themes-install-pending.json'
INVENTORY = 'themes.json'
PACKAGES = ('qt5ct', 'qt6ct', 'adwaita-qt', 'adwaita-qt6', 'qt-style-kvantum',
            'kde-style-breeze', 'libgtk-3-0t64', 'libgtk-4-1',
            'libadwaita-1-0', 'python3-gi', 'python3-tinycss2')


class OutcomeUnknown(RuntimeError):
    """Publication started; retained identities must be reconciled first."""


class CleanupPending(RuntimeError):
    """The inventory commit succeeded; cleanup still has retained evidence."""


def check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError('desktop theme installation exceeded its deadline')


def dependencies() -> dict:
    architecture = sysconfig.get_config_var('MULTIARCH')
    if not isinstance(architecture, str) or not re.fullmatch(r'[a-zA-Z0-9_+-]{1,80}', architecture):
        raise ValueError('target Python has no validated Debian multiarch identity')
    plugins = {}
    with Tree(Path('/usr'), uid=0) as usr:
        for version, names in (('5', ('adwaita.so', 'libkvantum.so')),
                               ('6', ('adwaita.so', 'libkvantum.so', 'breeze6.so'))):
            for name in (*('styles/' + item for item in names), 'platformthemes/libqt' + version + 'ct.so'):
                path = 'lib/' + architecture + '/qt' + version + '/plugins/' + name
                blob = usr.read(path, limit=MAX_MEMBER)
                if not blob.startswith(b'\x7fELF'):
                    raise ValueError('installed Qt theme engine is not an ELF plugin')
                plugins[path] = hashlib.sha256(blob).hexdigest()
    with Tree(Path('/var/lib/dpkg'), uid=0) as dpkg:
        status = dpkg.read('status', limit=16 * 1024**2).decode('utf-8')
    versions = {}
    for paragraph in status.split('\n\n'):
        values = {}
        for line in paragraph.splitlines():
            if line.startswith(('Package: ', 'Status: ', 'Version: ')):
                key, _, value = line.partition(': ')
                if key in values:
                    raise ValueError('ambiguous target package metadata')
                values[key] = value
        package = values.get('Package')
        if package in PACKAGES:
            if (package in versions or values.get('Status') != 'install ok installed' or
                    not re.fullmatch(r'[A-Za-z0-9.+:~_-]{1,100}', values.get('Version', ''))):
                raise ValueError('required target GTK/Qt theme dependency is not fully installed')
            versions[package] = values['Version']
    if set(versions) != set(PACKAGES):
        raise ValueError('required GTK3/GTK4 and Qt5/Qt6 theme dependencies are missing')
    return {'multiarch': architecture, 'versions': versions, 'plugins': plugins}


def directory(tree: Tree, relative: str, *, mode: int = 0o755) -> None:
    components = parts(relative)
    for length in range(1, len(components) + 1):
        path = '/'.join(components[:length])
        desired = 0o700 if re.fullmatch(r'\.labwc-theme-stage-[0-9a-f]{32}', components[length - 1]) else 0o755
        if length == len(components) and mode != desired:
            raise ValueError('invalid public/private theme directory mode')
        with tree.parent(path) as (parent, name):
            created = False
            try:
                os.mkdir(name, desired, dir_fd=parent)
                created = True
            except FileExistsError:
                pass
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            try:
                info = os.fstat(fd)
                if info.st_uid != 0 or info.st_mode & 0o022:
                    raise ValueError('unsafe root-owned theme asset directory')
                if created:
                    os.fchmod(fd, desired)
                    os.fsync(fd)
                    os.fsync(parent)
                elif stat.S_IMODE(info.st_mode) != desired:
                    raise ValueError('existing theme asset directory has unexpected permissions')
            finally:
                os.close(fd)


def matches(tree: Tree, relative: str, files: dict[str, bytes], *, deadline: float) -> bool:
    try:
        with tree.parent(relative + '/.anchor') as (parent, _):
            fd = os.dup(parent)
    except FileNotFoundError:
        return False
    seen = set()
    entry_count = 0
    expected_dirs = {str(parent) for path in files for parent in PurePosixPath(path).parents if str(parent) != '.'}
    def visit(current: int, prefix: str = '') -> None:
        nonlocal entry_count
        check(deadline)
        info = os.fstat(current)
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o755:
            raise ValueError('existing theme directory is not public root-owned data')
        with os.scandir(current) as children:
            for entry in children:
                check(deadline)
                entry_count += 1
                if entry_count > 2 * MAX_FILES:
                    raise ValueError('existing theme directory exceeds the entry budget')
                path = prefix + '/' + entry.name if prefix else entry.name
                parts(path)
                if len(PurePosixPath(path).parts) > 32:
                    raise ValueError('existing theme directory exceeds the depth budget')
                item = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(item.st_mode):
                    if path not in expected_dirs:
                        raise ValueError('existing theme directory contains an unexpected subdirectory')
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current)
                    try:
                        visit(child, path)
                    finally:
                        os.close(child)
                else:
                    if (path not in files or len(seen) >= MAX_FILES or not stat.S_ISREG(item.st_mode) or
                            item.st_uid != 0 or stat.S_IMODE(item.st_mode) != 0o644 or item.st_nlink != 1):
                        raise ValueError('existing theme directory contains unowned or unexpected data')
                    seen.add(path)
                    if tree.read(relative + '/' + path, limit=MAX_MEMBER) != files[path]:
                        raise ValueError('existing desktop theme assets differ; refusing replacement')
    try:
        visit(fd)
    finally:
        os.close(fd)
    if seen != set(files):
        raise ValueError('existing desktop theme directory is incomplete')
    return True


def inventory(candidate: Candidate, packages: dict, source: Source) -> bytes:
    files = {directory + '/' + path: {'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}
             for directory, values in candidate.directories.items() for path, blob in values.items()}
    value = {'schema': 1, 'variants': candidate.variants, 'files': files,
             'packages': packages, 'repairs': candidate.repairs,
             'sourceInventorySha256': hashlib.sha256(source.tree.read('sources.json')).hexdigest(),
             'trust': 'Pinned public HTTPS data and local installation hashes; no vendor signature claim.'}
    data = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode('utf-8')
    if len(data) > 6 * 1024**2:
        raise ValueError('installed desktop theme inventory exceeds the read budget')
    return data


def remove_inputs(registry: Tree, paths: tuple[str, ...], identity: list[int], *, deadline: float) -> None:
    with Tree(SOURCE, uid=0, private=True) as inputs:
        info = os.fstat(inputs.fd)
        if [info.st_dev, info.st_ino] != identity:
            raise RuntimeError('theme input directory identity changed; inputs retained')
        source = Source(inputs, deadline=deadline)
        if set(source.files) != set(paths):
            raise RuntimeError('theme source inventory changed before cleanup')
        source.verify_all()
        directories = {str(parent) for path in paths for parent in PurePosixPath(path).parents if str(parent) != '.'}
        for path in (*paths, 'sources.json'):
            check(deadline)
            inputs.write(path, None)
        for path in sorted(directories, key=lambda value: (-value.count('/'), value)):
            check(deadline)
            with inputs.parent(path) as (parent, name):
                os.rmdir(name, dir_fd=parent)
                os.fsync(parent)
    current = os.stat('.installer-themes', dir_fd=registry.fd, follow_symlinks=False)
    if not stat.S_ISDIR(current.st_mode) or [current.st_dev, current.st_ino] != identity:
        raise RuntimeError('theme input directory identity changed before removal')
    os.rmdir('.installer-themes', dir_fd=registry.fd)
    os.fsync(registry.fd)


def main(argv: list[str]) -> int:
    if argv != ['--install'] or os.getuid() != 0 or os.geteuid() != 0:
        raise ValueError('installation-only usage: labwc-appearance-themes --install (root)')
    deadline = time.monotonic() + 600
    with Tree(REGISTRY, uid=0) as registry, registry.lock('themes-install.lock'):
        if registry.read(PENDING, missing=True) is not None:
            raise OutcomeUnknown('theme publication needs explicit recovery; evidence retained at ' + str(REGISTRY / PENDING))
        with Tree(SOURCE, uid=0, private=True) as inputs:
            info = os.fstat(inputs.fd)
            input_identity = [info.st_dev, info.st_ino]
            source = Source(inputs, deadline=deadline)
            source.verify_all()
            input_paths = tuple(source.files)
            packages = dependencies()
            candidate = prepare(source)
            data = inventory(candidate, packages, source)
        with Tree(PUBLIC, uid=0) as public:
            missing = []
            for path, files in candidate.directories.items():
                check(deadline)
                directory(public, path.rsplit('/', 1)[0])
                if not matches(public, path, files, deadline=deadline):
                    missing.append(path)
            token = uuid.uuid4().hex
            stages = {parent: parent + '/.labwc-theme-stage-' + token
                      for parent in {path.rsplit('/', 1)[0] for path in missing}}
            previous = registry.read(INVENTORY, missing=True)
            journal = {'schema': 1, 'token': token, 'phase': 'preparing', 'stages': stages,
                       'newDirectories': missing, 'published': [],
                       'identities': {}, 'stageIdentities': {}, 'sourceIdentity': input_identity,
                       'previousInventoryPresent': previous is not None,
                       'previousInventorySha256': hashlib.sha256(previous or b'').hexdigest(),
                       'newInventorySha256': hashlib.sha256(data).hexdigest()}
            registry.write('themes-install-previous.json', previous)
            registry.write('themes-install-next.json', data)
            registry.put_json(PENDING, journal)
            publication_started = False
            inventory_committed = False
            try:
                for stage in stages.values():
                    directory(public, stage, mode=0o700)
                    with public.parent(stage + '/.anchor') as (fd, _):
                        info = os.fstat(fd)
                        journal['stageIdentities'][stage] = [info.st_dev, info.st_ino]
                    registry.put_json(PENDING, journal)
                for path in missing:
                    parent, _, name = path.rpartition('/')
                    staged = stages[parent] + '/' + name
                    directory(public, staged)
                    for relative, blob in candidate.directories[path].items():
                        check(deadline)
                        if '/' in relative:
                            directory(public, staged + '/' + relative.rsplit('/', 1)[0])
                        public.write(staged + '/' + relative, blob, mode=0o644, replace=False)
                    with public.parent(staged + '/.anchor') as (fd, _):
                        info = os.fstat(fd)
                        journal['identities'][path] = [info.st_dev, info.st_ino]
                journal['phase'] = 'publishing'
                registry.put_json(PENDING, journal)
                for path in missing:
                    check(deadline)
                    parent, _, name = path.rpartition('/')
                    with public.parent(path) as (destination, basename), public.parent(stages[parent] + '/' + name) as (stage, staged_name):
                        info = os.stat(staged_name, dir_fd=stage, follow_symlinks=False)
                        if (not stat.S_ISDIR(info.st_mode) or
                                [info.st_dev, info.st_ino] != journal['identities'][path]):
                            raise RuntimeError('staged desktop theme identity changed before publication')
                        try:
                            os.stat(basename, dir_fd=destination, follow_symlinks=False)
                        except FileNotFoundError:
                            pass
                        else:
                            raise RuntimeError('desktop theme destination appeared concurrently')
                        publication_started = True
                        os.rename(staged_name, basename, src_dir_fd=stage, dst_dir_fd=destination)
                        os.fsync(stage)
                        os.fsync(destination)
                    journal['published'].append(path)
                    registry.put_json(PENDING, journal)
                if registry.read(INVENTORY, missing=True) != previous:
                    raise RuntimeError('installed theme inventory changed concurrently')
                publication_started = True
                registry.write(INVENTORY, data, mode=0o644)
                inventory_committed = True
                journal['phase'] = 'committed'
                registry.put_json(PENDING, journal)
                for stage in stages.values():
                    with public.parent(stage) as (parent, name):
                        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                        if (not stat.S_ISDIR(info.st_mode) or
                                [info.st_dev, info.st_ino] != journal['stageIdentities'][stage]):
                            raise RuntimeError('theme cleanup stage identity changed; evidence retained')
                        os.rmdir(name, dir_fd=parent)  # Only the owned, now-empty stage.
                        os.fsync(parent)
                remove_inputs(registry, input_paths, input_identity, deadline=time.monotonic() + 60)
                registry.write('themes-install-next.json', None)
                registry.write('themes-install-previous.json', None)
                registry.write(PENDING, None)
            except BaseException as error:
                evidence = str(REGISTRY / PENDING)
                if inventory_committed:
                    raise CleanupPending('theme installation committed; cleanup incomplete; evidence retained at ' + evidence) from error
                if publication_started:
                    raise OutcomeUnknown('theme publication outcome unknown; candidate and journal retained at ' + evidence) from error
                if isinstance(error, KeyboardInterrupt):
                    raise
                raise RuntimeError('theme installation failed before publication; private candidate retained at ' + evidence) from error
    return 0
