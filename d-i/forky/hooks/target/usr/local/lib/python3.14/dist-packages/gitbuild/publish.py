"""Publish verified, private copies; never evaluate a repository or OBS service."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import pwd
import re
import time
import uuid

from managed_workflows.fs import Tree
from managed_workflows.process import checked, environment
from .core import ARTIFACT, PACKAGE, descriptor_files, record_artifacts, verified_artifacts
from .worker import validate_job

OSC = '/usr/local/libexec/obs-publishing-bin/osc'
APTLY = '/usr/local/libexec/aptly-publishing-bin/aptly-publish-local'


def copy_bundle(job: Path, destination: Path) -> list[Path]:
    inventory = verified_artifacts(job)
    with Tree(job, private=True) as tree:
        expected = tree.json('job.json')['artifacts']
    with Tree(job / 'artifacts') as source, Tree(destination, private=True) as target:
        for path in inventory:
            target.copy(path.name, source, path.name)
            with target.open_read(path.name) as (stream, _):
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected[path.name]:
                    raise ValueError('artifact changed while preparing publication')
    files = [destination / path.name for path in inventory]
    validate_descriptors(files)
    return files


def validate_descriptors(files: list[Path]) -> None:
    names = {p.name for p in files}
    for path in files:
        if path.suffix in ('.dsc', '.changes', '.buildinfo'):
            references = descriptor_files(path)
            if any(p.name not in names for p in references):
                raise ValueError('descriptor references a file outside the verified bundle')


def signed_job(job: Path, fingerprint: str) -> Path:
    if not re.fullmatch(r'(?:[A-F0-9]{40}|[A-F0-9]{64})', fingerprint):
        raise ValueError('use a full uppercase OpenPGP fingerprint')
    name = time.strftime('%Y%m%dT%H%M%S', time.gmtime()) + '-' + uuid.uuid4().hex[:12]
    with Tree(job.parent) as parent:
        parent.mkdir(name + '/artifacts')
    result = job.parent / name
    with Tree(result, private=True) as tree:
        tree.put_json('job.json', {'schema': 1, 'kind': 'sign', 'status': 'pending',
                                 'sourceJob': job.name, 'artifacts': {}})
        try:
            files = copy_bundle(job, result / 'artifacts')
            changes = sorted(p for p in files if p.suffix == '.changes')
            roots = changes or sorted(p for p in files if p.suffix in ('.dsc', '.buildinfo'))
            if not roots:
                raise ValueError('the bundle has no .changes, .dsc or .buildinfo to sign')
            # No ~/.devscripts, package-local scripts, shell or key-id guessing.
            # Reusing child signatures lets multiple .changes refer to one .dsc.
            checked(['/usr/bin/debsign', '--no-conf', '--no-re-sign', '-k' + fingerprint,
                     *map(str, roots)], cwd=result / 'artifacts', timeout=1800)
            validate_descriptors(files)
            # Verify the actual signer, not just the presence of an armor header.
            for path in files:
                if path.suffix in ('.changes', '.dsc', '.buildinfo'):
                    status = checked(['/usr/bin/gpg', '--batch', '--no-auto-key-retrieve',
                                      '--status-fd=1', '--verify', str(path)], capture=True)
                    signatures = [line.split() for line in status.splitlines()
                                  if line.startswith('[GNUPG:] VALIDSIG ')]
                    if not signatures or any(fingerprint not in (row[2], row[-1]) for row in signatures):
                        raise ValueError('descriptor was not signed by the selected primary key')
            record_artifacts(result)
        except BaseException:
            record = tree.json('job.json')
            record['status'] = 'failed'
            tree.put_json('job.json', record)
            raise
    return result


def publish_obs(files: list[Path], state: Tree, account: str) -> None:
    descriptors = [p for p in files if p.suffix == '.dsc']
    if len(descriptors) != 1:
        raise ValueError('OBS requires exactly one Debian source package (.dsc)')
    dsc = descriptors[0]
    with Tree(dsc.parent) as source:
        text = source.read(dsc.name).decode('utf-8')
    names = re.findall(r'^Source: ([a-z0-9][a-z0-9+.-]+)$', text, re.M)
    if len(names) != 1 or not PACKAGE.fullmatch(names[0]):
        raise ValueError('source descriptor has no unique valid Source field')
    package = names[0]
    with Tree(Path('/pool/db') / account / 'osc', private=True) as tree:
        metadata = tree.json('managed.json')
    project = metadata.get('project', '')
    workspace = Path('/pool/build') / account / 'osc'
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:+-]*', project) or
            metadata.get('workspace') != str(workspace)):
        raise ValueError('OBS project/workspace differs from installed account policy')
    # Use the already installed credential broker and its managed API endpoint.
    # A dedicated fresh checkout cannot accidentally commit the user's edits.
    from .core import private_child
    checkout_parent = private_child(workspace, 'gitbuild')
    checkout = checkout_parent / uuid.uuid4().hex
    checked([OSC, 'checkout', '--output-dir', str(checkout), project, package],
            cwd=checkout_parent, timeout=1800)
    with Tree(checkout) as target:
        if target.read('.osc/_project').decode().strip() != project or target.read('.osc/_package').decode().strip() != package:
            raise ValueError('OBS checkout identity mismatch')
        # Linked/service-generated packages require a maintainer-specific flow;
        # never run their services or unexpectedly rewrite a remote link.
        if any(target.read(n, missing=True) is not None for n in ('_link', '_service')):
            raise ValueError('OBS _link/_service package refused; publish to a plain Debian-source package')
        source_files = [dsc, *descriptor_files(dsc)]
        keep = {p.name for p in source_files}
        for old in os.listdir(target.fd):
            if ARTIFACT.fullmatch(old) and old not in keep:
                target.write(old, None)
        with Tree(dsc.parent) as source:
            for path in source_files:
                target.copy(path.name, source, path.name, mode=0o644)
    checked([OSC, 'addremove', str(checkout)], cwd=checkout, timeout=600)
    status = checked([OSC, 'status', str(checkout)], cwd=checkout, capture=True)
    if not status.strip():
        print('OBS source is already current.')
        return
    # Never execute _service while holding credentials, even if checkout changed.
    checked([OSC, 'commit', '--skip-local-service-run', '-m', 'gitbuild: publish ' + dsc.name,
             str(checkout)], cwd=checkout, timeout=1800)
    state.put_json('last-obs.json', {'project': project, 'package': package,
                                   'descriptor': dsc.name, 'checkout': str(checkout)})
    print('Published source to ' + project + '/' + package + '; server-side builds are asynchronous.')


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3) or argv[0] not in ('sign', 'aptly', 'obs'):
        raise ValueError('usage: gitbuild-publish {sign JOB FINGERPRINT|aptly JOB DISTRIBUTION|obs JOB}')
    action, job = argv[0], Path(argv[1])
    if (action == 'obs') != (len(argv) == 2):
        raise ValueError('invalid publication arguments')
    validate_job(job)
    account = pwd.getpwuid(os.getuid()).pw_name
    env = environment(desktop=True)
    os.environ.clear()
    os.environ.update(env)
    os.environ['QT_QPA_PLATFORM'] = 'wayland'
    # Credential brokers resolve their account-specific D-Bus/keyring endpoint.
    os.environ['XDG_RUNTIME_DIR'] = '/run/user/' + str(os.getuid())
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=' + os.environ['XDG_RUNTIME_DIR'] + '/bus'
    with Tree(Path('/pool/db') / account / 'gitbuild', private=True) as state, state.lock('publish.lock'):
        if action == 'sign':
            print('Signed bundle: ' + str(signed_job(job, argv[2])))
            return 0
        operation = 'operations/' + uuid.uuid4().hex
        state.mkdir(operation)
        stage = state.root / operation
        files = copy_bundle(job, stage)
        if action == 'aptly':
            distribution = argv[2]
            if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', distribution):
                raise ValueError('invalid Aptly distribution')
            with Tree(Path('/pool/db') / account / 'aptly', private=True) as tree:
                config = tree.json('aptly.conf')
            if distribution not in config['managedLocalPublishing']['distributions'].split():
                raise ValueError('distribution is not in the installed Aptly policy')
            selected = [p for p in files if p.suffix in ('.deb', '.dsc')]
            if not selected:
                raise ValueError('bundle contains no publishable package')
            checked([APTLY, distribution, *map(str, selected)], cwd=stage, timeout=3500)
        else:
            publish_obs(files, state, account)
        state.put_json('last-publication.json', {'kind': action, 'job': job.name, 'staging': str(stage)})
    return 0
