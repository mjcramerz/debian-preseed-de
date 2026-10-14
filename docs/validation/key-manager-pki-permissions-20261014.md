# Key-manager PKI traversal permission repair

## Source defect

The reported installed error is `Permission denied: 'pki'`. The installer
intentionally provisions `DIR_DATA_PKI` and its `exports` parent as root-owned
0711 directories. The desktop account may traverse them, but cannot list them.
Its configuration, GPG/PQC stores and exports are account-owned private leaves;
TLS and TLS exports remain root-owned 0700.

`managed_workflows.fs.open_directory` previously opened every component with
`O_RDONLY`. That requires directory read permission on the PKI parent. Startup
calls `protected_directory(root)` before opening the stores, so it could fail
at the relative component `pki`, exactly matching the supplied error. The same
defect would affect store opens through `pki` and `pki/exports`. No installed
host paths or credentials were read to diagnose this source mismatch.

## Changes and preserved contracts

- `hooks/target/usr/local/lib/python3.14/dist-packages/managed_workflows/fs.py`:
  walk components using Linux `O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC`.
  Ordinary callers promote the pinned final directory to a readable descriptor
  for listing and directory fsync. Metadata-only callers can explicitly retain
  the path descriptor. All descriptors close on success/failure as before.
- `hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/core.py`:
  `protected_directory` requests metadata-only descriptors. Its root ownership
  and prohibition on group/other-writable ancestors are unchanged.
- `tests/test_gitbuild_appearance_20260928.py`: three focused fixture cases
  cover traversal through parents that deny listing, readable store operations,
  metadata-only descriptor behavior and rejecting absolute-path symlinks.
  The traversal case explicitly emulates read denial on two fixture inodes,
  including when the disposable image runs as root. **These tests were not run.**

The default `open_directory` return remains readable for `Tree`, gitbuild and
appearance callers. `Tree` ownership/private-mode checks and its relative
operations are byte-identical. Root-owned PKI parents remain 0711; private
stores retain 0700. No chmod/chown workaround, new PKI tree, AppArmor grant,
pinentry backend, service or privilege escalation was added. The MOK repair and
other accumulated work are preserved.

`desktop_stage_key_manager` stages both changed modules root-owned mode 0644
from these canonical files. Existing appearance/devops module staging uses the
same shared filesystem source. The runtime-storage policy renderer and
normalizer install the existing explicit directory modes and owners.

## Completed verification

`AGENTS.override.md` prohibits host tests/validators. No prepared disposable
environment is available. No repository modules, key-manager command, test
runner, native crypto command, host services or installed management helpers
were executed. The installed machine was not modified. A read-only sidecar
attempt failed before review with encrypted-content hydration failure; its
output was not used as evidence.

- Standard-library AST parsing with `python3 -I -B` parsed both changed runtime
  modules and the changed test source as data, without repository imports.
- Byte comparison confirmed all shared filesystem code outside
  `open_directory` is unchanged, and key-manager core differs only in the
  metadata-open call inside `protected_directory`.
- Archive comparison before rebuilding found exactly these two runtime module
  differences from the preceding MOK snapshot. Ownership/staging policy, all
  MOK assets and other payload sources were unchanged.
- `git diff --check` completed without whitespace errors.
- Reviewed `Makefile`, `tools/build.py` and `tools/publication.py`, then ran the
  permitted serialization-only `make build PYTHON=python3`: **1,768 files**.
- Standard-library archive/hash inspection found all 1,768 normalized regular
  entries identical to source bytes and manifest SHA256, required assets
  present, private inputs/tests excluded, and all three bootstrap pins current.

These checks establish the source/artifact repair. They do not establish live
unprivileged startup, menu operation or native key generation. Acceptance must
run in the prepared disposable Forky environment as its desktop account.

## Snapshot after this repair

| Product | SHA256 |
| --- | --- |
| `payload.tar.gz` | `e28d4b66e9d98ab52105690507969843a89e40813be6208b37d7a87c9b577049` |
| `payload.manifest` | `389e4f76db96d57f34d350187f8cfa938b677488f4a7700062af62cd7410abd7` |
| `preseed.cfg` | `880424a89b8375a006f34f3f60060e30922f3fcb0dcc72055538af4e745b0527` |

The later [desktop CrowdSec report](crowdsec-desktop-relevance-20261014.md)
records the current combined snapshot, preserving this PKI repair.

The already-installed system needs these two updated modules together:
`/usr/local/lib/python3.14/dist-packages/managed_workflows/fs.py` and
`/usr/local/lib/python3.14/dist-packages/key_manager/core.py`. The PKI directory
modes do not need to be widened for this repair.

## Primary reference

[Linux open(2)](https://man7.org/linux/man-pages/man2/open.2.html) documents
`O_PATH` descriptors, their use for `fstat`/descriptor-relative operations, and
search permission on path prefixes without directory read permission. Python
3.14 exposes [O_PATH](https://docs.python.org/3.14/library/os.html#os.O_PATH).
