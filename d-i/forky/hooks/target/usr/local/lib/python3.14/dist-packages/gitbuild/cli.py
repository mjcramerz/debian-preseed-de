"""Terminal menus. Labels never become commands, options or shell fragments."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from managed_workflows.fs import Tree
from managed_workflows.process import checked, environment, supervised
from .core import (Context, RepositoryRequired, workspace_repositories, JOB, PACKAGE, VERSION, WORKER, PUBLISHER, snapshot,
                   verified_artifacts, descriptor_files, require_subids)

MENUS = {
    'Debian packaging': {
        'Initiating Debian Directory': 'init',
        'Review Debian control files': 'review',
        'Create upstream orig archive from working tree': 'orig',
        'Create source package (.dsc and .changes)': 'source',
        'Check host build dependencies': 'deps',
    },
    'Build and test': {
        'Prepare / refresh Forky sbuild image': 'bootstrap',
        'Build .deb with sbuild (recommended)': 'binary',
        'Build .deb with host tools in offline sandbox': 'local',
        'Run Lintian on completed bundle': 'lintian',
        'Run autopkgtest in unshare image': 'autopkgtest',
        'Inspect completed Debian packages': 'inspect',
    },
    'Sign and publish': {
        'Sign completed source / binary bundle': 'sign',
        'Publish verified bundle to Aptly': 'aptly',
        'Stage and publish source bundle to OBS': 'obs',
        'Publish .deb to apt-local-repo': 'local-repo',
    },
    'Status and artifacts': {'Show artifact paths': 'artifacts', 'Read job log': 'log',
                             'Check build prerequisites': 'doctor'},
}


def choose(labels: list[str], prompt: str) -> str | None:
    env = environment(desktop=True)
    result = subprocess.run(['/usr/bin/fzf', '--no-multi', '--no-sort', '--exact',
                             '--layout=reverse', '--border', '--height=80%',
                             '--prompt=' + prompt + ' > ', '--header=Arrows: navigate  Enter: select  Esc: back'],
                            input='\n'.join(labels) + '\n', text=True, stdout=subprocess.PIPE,
                            env=env, check=False)
    if result.returncode in (1, 130):
        return None
    if result.returncode:
        raise RuntimeError(f'menu failed ({result.returncode})')
    selected = result.stdout.rstrip('\n')
    return selected if selected in labels else None


def confirm(message: str) -> bool:
    print('\n' + message)
    return choose(['Cancel', 'Proceed'], 'Confirm') == 'Proceed'


def ask(prompt: str, pattern: str, default: str = '') -> str:
    value = input(prompt + (f' [{default}]' if default else '') + ': ').strip() or default
    if not re.fullmatch(pattern, value):
        raise ValueError('invalid input; no changes made')
    return value


def epoch(ctx: Context) -> int:
    try:
        value = checked(['/usr/bin/git', '-c', 'core.fsmonitor=false', 'show', '-s', '--format=%ct', 'HEAD'],
                        cwd=ctx.repo, capture=True).strip()
        if value.isdecimal() and len(value) <= 12:
            return int(value)
    except RuntimeError:
        pass
    return int(time.time())


def request_job(ctx: Context, kind: str, request: dict, *, prepared: Path | None = None) -> Path:
    job = prepared or ctx.new_job(kind)
    request.update(kind=kind, jobs=ctx.jobs)
    with Tree(job) as tree:
        tree.put_json('request.json', request)
    print(f'Job: {job}\n')
    supervised([WORKER, str(job)], cwd=ctx.repo)
    return job


def bundle(ctx: Context) -> Path | None:
    jobs = ctx.completed()
    selected = choose([p.name for p in jobs], 'Completed bundle') if jobs else None
    if not jobs:
        print('No completed build bundles. Build a source or binary package first.')
    if selected is None:
        return None
    job = ctx.output / selected
    verified_artifacts(job)
    return job


def prepare_source(ctx: Context, kind: str) -> tuple[Path, dict]:
    package, version = ctx.metadata()
    upstream = version.split(':', 1)[-1].rsplit('-', 1)[0] if '-' in version else version.split(':', 1)[-1]
    source = f'{package}-{upstream}'
    if not re.fullmatch(r'[a-z0-9][A-Za-z0-9.+~\-]+', source):
        raise ValueError('unsupported source version in directory name')
    job = ctx.new_job(kind)
    snapshot(ctx.repo, job / 'work' / source, entries=ctx.source_files())
    fmt = ctx.tree.read('debian/source/format', missing=True)
    if fmt is None or fmt.strip() not in (b'3.0 (native)', b'3.0 (quilt)'):
        raise ValueError('an explicit debian/source/format (3.0 native or quilt) is required')
    if fmt.strip() == b'3.0 (quilt)' and kind in {'source', 'binary'}:
        prefix = package + '_' + upstream + '.orig'
        originals = []
        # Standard upstream sibling or explicitly generated managed orig cache.
        for parent in (ctx.repo.parent, ctx.output / 'orig'):
            if not parent.is_dir():
                continue
            for file in sorted(parent.glob(prefix + '*.tar.*')):
                if re.fullmatch(re.escape(prefix) + r'(?:-[A-Za-z0-9+.-]+)?\.tar\.(?:gz|xz|bz2|zst)', file.name):
                    originals.append(file)
        names = [p.name for p in originals]
        if len(names) != len(set(names)):
            raise ValueError('ambiguous upstream orig archives; retain one authoritative copy')
        if not any(p.name.startswith(prefix + '.tar.') for p in originals):
            raise ValueError('quilt needs its authoritative upstream .orig.tar archive; select Create upstream orig only for a reviewed local snapshot')
        with Tree(job / 'work') as output:
            for file in originals:
                with Tree(file.parent) as source_tree:
                    output.copy(file.name, source_tree, file.name)
    return job, {'source': source, 'epoch': epoch(ctx)}


def init_debian(ctx: Context) -> None:
    if (ctx.repo / 'debian').exists() or (ctx.repo / 'debian').is_symlink():
        raise ValueError('debian/ already exists; refusing to overwrite packaging')
    package = ask('Debian source package name', PACKAGE.pattern, ctx.repo.name.lower())
    version = ask('Upstream version (no Debian revision)', r'[0-9][A-Za-z0-9.+~]*', '1.0.0')
    name = ask('Maintainer full name', r'[^\x00-\x1f\x7f<>]{1,100}')
    email = ask('Maintainer email', r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+')
    fmt = choose(['Quilt (upstream project)', 'Native (Debian-specific project)'], 'Source format')
    if fmt is None:
        return
    native = fmt.startswith('Native')
    if not confirm('Generate a debmake skeleton in debian/. Review copyright, dependencies, install rules and tests before publishing. No packaging is committed automatically.'):
        return
    job = ctx.new_job('init')
    source = package + '-' + version
    snapshot(ctx.repo, job / 'work' / source, packaging=False, entries=ctx.source_files())
    request_job(ctx, 'init', {'source': source, 'package': package, 'version': version,
                             'name': name, 'email': email, 'format': 'native' if native else 'quilt',
                             'epoch': epoch(ctx)}, prepared=job)
    generated = job / 'work' / source / 'debian'
    with Tree(generated) as tree:
        for required in ('control', 'rules', 'changelog', 'copyright', 'source/format'):
            tree.read(required)
    # Copy only generated packaging into a private sibling; rename cannot follow
    # a destination link, and a pre-existing directory is never merged.
    staging = '.gitbuild-debian-' + job.name
    snapshot(generated, ctx.repo / staging)
    if (ctx.repo / 'debian').exists() or (ctx.repo / 'debian').is_symlink():
        raise ValueError('debian/ appeared during generation; staging retained for review')
    # Linux renameat2(RENAME_NOREPLACE) protects against a concurrent empty dir.
    from .safe_rename import rename_new_directory
    rename_new_directory(ctx.tree.fd, staging, 'debian')
    if not native:
        ctx.tree.mkdir('target/gitbuild/orig')
        orig = package + '_' + version + '.orig.tar.xz'
        with Tree(job / 'work') as src:
            ctx.tree.copy('target/gitbuild/orig/' + orig, src, orig)
    print('Created debian/ without changing Git history. Review the generated templates before building.')


def create_orig(ctx: Context) -> None:
    package, version = ctx.metadata()
    if ('-' not in version or
            ctx.tree.read('debian/source/format').strip() != b'3.0 (quilt)'):
        raise ValueError('only quilt packages with a Debian revision use upstream orig tarballs')
    upstream = version.split(':', 1)[-1].rsplit('-', 1)[0]
    name = package + '_' + upstream + '.orig.tar.xz'
    ctx.tree.mkdir('target/gitbuild/orig')
    if (ctx.output / 'orig' / name).exists():
        raise ValueError('orig for this upstream version already exists; increment version instead of replacing it')
    if not confirm('Create an upstream orig archive from current working files, excluding ignored files, .git, target and debian? Use the official upstream tarball instead when one exists.'):
        return
    job = ctx.new_job('orig')
    source = job / 'work' / (package + '-' + upstream)
    snapshot(ctx.repo, source, packaging=False, entries=ctx.source_files())
    from .worker import orig_archive
    orig_archive(source, job / 'work' / name, epoch(ctx))
    with Tree(job / 'work') as src:
        ctx.tree.copy('target/gitbuild/orig/' + name, src, name)
    print(ctx.output / 'orig' / name)


def doctor(ctx: Context) -> None:
    tools = ('fzf', 'git', 'debmake', 'dpkg-buildpackage', 'dpkg-source', 'sbuild', 'mmdebstrap',
             'bwrap', 'newuidmap', 'newgidmap', 'lintian', 'autopkgtest', 'debsign')
    for tool in tools:
        print(f'{tool}: ' + ('available' if Path('/usr/bin', tool).is_file() else 'MISSING'))
    for command in ('aptly-publishing-bin/aptly-publish-local', 'obs-publishing-bin/osc',
                    'obs-publishing-bin/obs-publish-source'):
        print(command + ': ' + ('available' if Path('/usr/local/libexec', command).is_file() else 'MISSING'))
    require_subids()
    checked(['/usr/bin/systemctl', '--user', 'show-environment'], capture=True)
    print(f'Native architecture: {ctx.arch}\nDistribution: forky\nImage: {ctx.tarball}\n'
          f'Outputs: {ctx.output}\nConfinement: {Path("/proc/self/attr/current").read_text().strip()}')


def act(ctx: Context, action: str) -> None:
    if action == 'doctor':
        doctor(ctx)
    elif action == 'init':
        init_debian(ctx)
    elif action == 'orig':
        create_orig(ctx)
    elif action == 'review':
        for name in ('control', 'changelog', 'rules', 'copyright', 'source/format', 'tests/control'):
            raw = ctx.tree.read('debian/' + name, missing=True)
            if raw is not None:
                print('\n--- debian/' + name + ' ---\n' + printable(raw))
    elif action == 'bootstrap':
        if confirm('Create/replace the native Forky build image using signed Debian archive metadata? Package downloads require network access; compiler builds remain offline.'):
            require_subids()
            request_job(ctx, 'bootstrap', {})
    elif action in {'source', 'binary', 'local', 'deps'}:
        if action != 'deps' and not confirm('Build a snapshot of current working files? Results and logs stay under target/gitbuild; no packages are installed on the host.'):
            return
        if action == 'binary':
            require_subids()
        job, request = prepare_source(ctx, action)
        # The service owns its image lock, including after the menu disconnects.
        request_job(ctx, action, request, prepared=job)
    elif action == 'log':
        jobs = [p.name for p in sorted(ctx.output.iterdir(), reverse=True) if JOB.fullmatch(p.name)]
        selected = choose(jobs, 'Job log') if jobs else None
        if selected:
            with Tree(ctx.output / selected) as tree:
                print(printable(tree.read('build.log', 64 * 1024**2 + 4096)))
    else:
        job = bundle(ctx)
        if job is None:
            return
        if action == 'artifacts':
            print('\n'.join(str(p) for p in verified_artifacts(job)))
        elif action in {'lintian', 'autopkgtest', 'inspect'}:
            request_job(ctx, action, {'bundle': str(job)})
        elif action in {'sign', 'aptly', 'obs'}:
            extra = []
            if action == 'sign':
                key = ask('Signing key full fingerprint', r'(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})')
                extra = [key.upper()]
            elif action == 'aptly':
                with Tree(Path('/pool/db') / ctx.account.pw_name / 'aptly', private=True) as tree:
                    config = tree.json('aptly.conf')
                distributions = config['managedLocalPublishing']['distributions'].split()
                if not distributions or any(not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', d) for d in distributions):
                    raise ValueError('invalid managed Aptly distribution list')
                distribution = choose(distributions, 'Aptly distribution')
                if distribution is None:
                    return
                extra = [distribution]
            if confirm(f'{action.upper()}: act on verified bundle {job.name}? Publishing is not an installation. OBS uploads only the selected source bundle to an existing, plain (non-linked) package in the managed project.'):
                supervised([PUBLISHER, action, str(job), *extra], cwd=ctx.repo, prefix='gitbuild-publish', timeout=3600)
        elif action == 'local-repo':
            files = [p for p in verified_artifacts(job) if p.suffix == '.deb']
            if not files:
                raise ValueError('bundle contains no .deb packages')
            if confirm('Import these .deb files into the signed local APT repository? Administrator authentication is required. This does not install the packages.\n' + '\n'.join(p.name for p in files)):
                for file in files:
                    checked(['/usr/bin/pkexec', '/usr/local/libexec/gitbuild-import-local', str(file)], timeout=3600)
        else:
            raise ValueError('unknown action')


def printable(raw: bytes) -> str:
    return ''.join(c if c in '\n\t' or c.isprintable() else '?'
                   for c in raw.decode('utf-8', 'replace'))


def main(argv: list[str]) -> int:
    if argv == ['--catalog']:
        print(json.dumps(MENUS, indent=2))
        return 0
    if argv not in ([], ['--doctor']):
        raise ValueError('usage: gitbuild [--doctor|--catalog]')
    try:
        ctx = Context()
    except RepositoryRequired:
        if argv or not sys.stdin.isatty() or not sys.stdout.isatty():
            raise
        import pwd
        workspace = Path(pwd.getpwuid(os.getuid()).pw_dir) / 'Workspace'
        repositories = workspace_repositories(workspace)
        names = {str(repo.relative_to(workspace)): repo for repo in repositories}
        if not names:
            raise ValueError('no Git repositories found; clone or initialize a project below ~/Workspace first')
        chosen = choose(list(names), 'Workspace repository')
        if chosen is None:
            return 0
        ctx = Context(names[chosen])
    try:
        if argv:
            doctor(ctx)
            return 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError('gitbuild needs an interactive terminal')
        with ctx.tree.lock('target/gitbuild/menu.lock'):
            while True:
                group = choose([*MENUS, 'Exit'], 'gitbuild')
                if group in (None, 'Exit'):
                    break
                while True:
                    selected = choose([*MENUS[group], 'Back'], group)
                    if selected in (None, 'Back'):
                        break
                    try:
                        act(ctx, MENUS[group][selected])
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                        print('gitbuild: ' + printable(str(error).encode()), file=sys.stderr)
                    input('\nPress Enter to return to the menu...')
    finally:
        ctx.tree.close()
    return 0
