"""Authenticated, fixed-purpose bridge into the existing signed local APT repo."""
from __future__ import annotations
import os
from pathlib import Path
import pwd
import re
import uuid
from managed_workflows.fs import Tree
from managed_workflows.process import checked, environment
from .core import ARTIFACT, JOB


def caller_source(argument: str) -> tuple[Path, int]:
    raw_uid = os.environ.get('PKEXEC_UID', '')
    if os.getuid() != 0 or os.geteuid() != 0 or not re.fullmatch(r'[1-9][0-9]{0,9}', raw_uid):
        raise ValueError('administrator authentication through pkexec is required')
    uid = int(raw_uid)
    account = pwd.getpwuid(uid)
    path = Path(argument)
    workspace = Path(account.pw_dir) / 'Workspace'
    if (not path.is_absolute() or str(path) != argument or '..' in path.parts or
            not path.is_relative_to(workspace) or path.suffix != '.deb' or
            not ARTIFACT.fullmatch(path.name) or len(path.parts) < 6 or
            path.parent.name != 'artifacts' or not JOB.fullmatch(path.parent.parent.name) or
            path.parent.parent.parent.name != 'gitbuild' or
            path.parent.parent.parent.parent.name != 'target'):
        raise ValueError('only gitbuild .deb artifacts below the caller Workspace may be imported')
    # Validate *all* owned components from Workspace, not just the final file.
    with Tree(workspace, uid=uid) as tree:
        with tree.parent(str(path.relative_to(workspace))):
            pass
    return path, uid


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        raise ValueError('exactly one .deb artifact is required')
    path, uid = caller_source(argv[0])
    # The caller can replace its own artifacts. Copy through descriptors into a
    # root-only directory before handing a pathname to privileged repository IO.
    with Tree(Path('/var/lib/software'), uid=0) as repository:
        repository.mkdir('.gitbuild-incoming')
        with Tree(repository.root / '.gitbuild-incoming', uid=0, private=True) as incoming, incoming.lock('import.lock'):
            name = uuid.uuid4().hex + '.deb'
            try:
                with Tree(path.parent, uid=uid, private=True) as source:
                    incoming.copy(name, source, path.name)
                with incoming.open_read(name) as (stream, _):
                    if stream.read(8) != b'!<arch>\n':
                        raise ValueError('not a Debian ar package')
                checked(['/usr/local/bin/apt-repo-init', '--add', str(incoming.root / name), '--yes'],
                        cwd=incoming.root, env=environment(), timeout=3500)
            finally:
                incoming.write(name, None)
    return 0
