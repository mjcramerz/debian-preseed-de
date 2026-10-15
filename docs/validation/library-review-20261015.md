# Library review and integration, 2026-10-15

## Scope and evidence boundary

The requested library root is `d-i/forky/hooks/target/usr/local/lib/`. Its 239
source files were inventoried and read as data, including templates. Before
this pass it contained 55,138 lines across 24 subsystem groups. Python AST
inspection covers 83 files; source inspection covers 156 Perl modules and
templates. Full-tree structural inspection is distinct from the detailed
control-flow review of shared helpers and selected callers described below.
This is not a claim that every possible runtime path has been proved correct.

The review followed subprocess creation, capture budgets, descriptor ownership,
filesystem traversal, archive publication, state recovery, network control
messages and installer staging. Detailed reads included the shared Perl
`Managed::Process` supervisor, managed-workflow filesystem and process helpers,
key-manager core/CLI, firewall transactions and application, archive safe I/O,
hardware policy/engine/broker/client, app-veth policy/client, APT servicing
atomic/state/HTTP/process helpers, and representative networking, AppArmor,
Whisper, AI model-store, desktop appearance and ZRAM modules.

The repository's `AGENTS.override.md` and `docs/test-isolation.md` require a
prepared disposable VM/image before any tests, validation runners, Perl compile
checks, shell execution checks or native policy parsers may run. No such
environment was available in this session. The checks below are source-as-data
inspection and the explicitly permitted pure artifact generation. Repository
runtime modules were not imported or executed during static inspection.

Independent review agents failed to start because of encrypted-content hydration
errors. Findings and integration were reviewed directly; no independent agent
verification is claimed.

## Changes

### Bounded workflow command capture

`python3.14/dist-packages/managed_workflows/process.py` now routes `checked(...,
capture=True)` through a private capture implementation. The existing
non-capturing command path retains its terminal and subprocess behavior.

- One 64 MiB budget bounds the combined captured stdout/stderr byte count.
  Stderr is drained and counted without retaining arbitrary diagnostic data.
- Optional text input is bounded before and after encoding. A nonblocking input
  pipe and readiness selector multiplex input with both output streams; early
  stdin closure and empty input have explicit paths.
- A monotonic deadline covers input/output readiness, inherited output writers,
  and the direct child's subsequent exit. Failure kills the owned process group
  while its direct child is still unreaped, then bounds reaping to five seconds.
- Completed children are not signalled using an already-reaped group identifier.
  Cleanup retains the original failure and adds cancellation/reaping notes.
- Captured text retains locale decoding, universal newline conversion and NUL
  bytes. Nonzero status errors omit captured subprocess output.

The budget applies to captured bytes, not to the entire Python process's memory;
decoding and caller-held data also consume memory. Commands that deliberately
daemonize or escape their process group still require the existing supervised
service/cgroup API. Process creation and uninterruptible kernel I/O are not made
interruptible by a userspace deadline.

All current capture callers were traced through Git workspace/file inventory,
package metadata, descriptor verification, OBS status and appearance gsettings.
The shared module is already staged mode 0644 by both
`scripts/late/devops/gitbuild.sh` and
`scripts/desktop/components/appearance.sh`. The change uses ordinary pipes and
requires no new module, AppArmor path grant or service property.

### Key-manager command lifecycle

`python3.14/dist-packages/key_manager/core.py` registers output closure, terminal
foreground restoration and SIGTTOU restoration with the existing `ExitStack`.
An error restoring the terminal or reaping a cancelled child no longer skips
the remaining cleanup callbacks. Failure after a completed wait does not send
SIGKILL to an already-reaped process-group identifier. The explicit privileged
unit cancellation callback remains in place.

The capture selector now waits for readiness using the remaining deadline,
removing the previous 200 ms periodic wakeup. No elapsed-time speedup or power
saving was measured. Input, output, timeout and native terminal handoff contracts
remain in the existing helper. Installer staging is the existing `core` module
loop in `scripts/desktop/components/target-assets.sh`.

### Firewall recovery

`python3.14/dist-packages/labwc_firewall/files.py` attempts restoration of both
managed files when one restoration fails, aggregates their errors, and retains
both private recovery backups. Candidate files are still removed. The retained
backup paths are included in the error. Interrupted restoration also retains
the backups. A successful retry releases them through normal cleanup.

Invalid UTF-8 in a recovery backup is translated to `FirewallError`, so it follows
the same recovery/error path and does not skip the other managed file. The
existing nftables caller continues to report incomplete rollback as a failure;
it does not report successful live restoration when disk recovery failed.

The existing firewall module staging list includes `files.py`. The root helper's
existing AppArmor profile already permits its candidate, restoration and
`/tmp/firewall-security-*` backup paths. Retained backups remain mode 0600 and
are recovery material, not a new automatic migration or startup mechanism.

### Archive publication descriptor lifetime

`python3.14/dist-packages/labwc_compz/safeio.py` closes the source directory
descriptor if opening the destination directory fails. Each successful open now
has its own enclosing cleanup scope. Atomic `RENAME_NOREPLACE`, collision
behavior and destination fsync are preserved. The existing compz module staging
loop already installs `safeio.py` mode 0644.

### Hardware transaction ordering

`hardware_tuning/engine.py` indexes requested controls by pair once instead of
rescanning every requested control for each pair. Pair membership discovery is
linear in the request size; the existing deterministic priority sort remains
O(n log n). The maximum member's current value is still read when that pair is
reached, after preceding governor/turbo yields. Requested membership, min/max
ordering, safety checks, journal behavior and policy values are preserved.

The existing hardware installer loop stages `engine.py` mode 0644, and the
worker's existing AppArmor profile permits that exact module. No tuning profile,
clock value, power limit or installed host hardware was changed by this pass.

## Regression coverage added, not executed

21 test methods were added to existing guarded suites:

| Existing suite | New methods | Contracts covered |
| --- | ---: | --- |
| `d-i/forky/tests/test_gitbuild_appearance_20260928.py` | 8 | Simultaneous stdin/stdout/stderr; Unicode, CR/LF and NUL handling; empty/early-closed stdin; both output limits; status/output privacy; inherited writers; closed-stream deadlines; input bounds before spawn |
| `d-i/forky/tests/test_key_manager_lifecycle_20261014.py` | 5 | Terminal restoration failure; cancellation reaping failure; completed-child group safety; spawn failure cleanup; readiness deadline |
| `tools/tests/test_scoped_lifecycle_keyrings.py` | 4 | Each file's failed rollback with independent restoration of its companion; aggregate errors and retry; invalid UTF-8; interruption and retained backups |
| `d-i/forky/tests/test_compz_20260925.py` | 1 | Source descriptor closure and absence of publication after destination-open failure |
| `d-i/forky/tests/test_hardware_tuning_refactor_20260917.py` | 3 | Safe ordering over 128 synthetic pairs with bounded inventory lookups; live boundary reads after a governor yield; exclusion of unrequested pair members |

The new tests use mocks, private file fixtures, synthetic control inventories
and image-provided Python fixture children. Their existing isolation gates run
before runtime imports. They have not been executed; no test pass count or live
acceptance result is inferred from reading or AST parsing them.

## Static checks and artifact integration

- Full source inventory and reads cover all 239 files; Python AST parsing
  succeeds for all 83 Python sources/templates without importing them.
- The five changed library modules and five changed test modules were parsed as
  AST data. New tests' import gates and fixture command paths were inspected.
- Full-tree structural discovery found no Python `shell=True`, direct `eval`,
  direct `exec`, `os.system`, pickle loading or `yaml.load` calls. This bounded
  search is not a general security proof and does not cover indirect aliases.
- `git diff --check` is clean. Edited source/test files retain mode 0644.
- Installer source lists, entrypoints and existing policy paths were inspected
  for all five changed modules. Private Xwayland sources and policy are intact.
- Existing bootstrap/dock edits and their regression/report files from the
  preceding passes are preserved.

Tests, runtime benchmarks, native AppArmor or systemd checks, and a fresh
unattended Forky installation remain unexecuted.

### Generated installer snapshot

After reading the Makefile, `tools/build.py` and `tools/publication.py`, the
explicitly permitted pure-generation command completed successfully:

```text
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
```

It reported `built 1784 payload files`. No software was compiled. A separate
standard-library source-as-data comparison then found:

- All 1,784 regular archive members match the canonical source bytes and
  manifest SHA-256 entries; total source content is 34,321,229 bytes.
- Archive paths are unique and safe; archive entries have mode 0644,
  uid/gid/mtime zero and empty owner/group names. The gzip header timestamp is
  zero and has no embedded filename.
- `preseed.cfg` pins the current archive, manifest and transport source hashes.
- Both the before/after digest and path count agree for 3,064 nonproduct checkout
  paths. Compared fields were type/mode, uid/gid, inode, link count, size, mtime,
  symlink targets and regular-file hashes. `.git` and the three products were
  excluded; the products' immediate parent directory size/mtime were ignored.
  Thus this generation did not rewrite source inputs or the added regressions.
- The final library inventory contains 239 files and 55,260 lines. All 83 Python
  library sources/templates and the five changed test files parse as AST data.
- A source-method comparison with HEAD confirms the 21 added regression methods
  listed above. This count is not an executed-test result.

| Generated product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `a0fec8fdd8cb0353c34b9ffcf333a831eb803934d9071915be8ab632a750b4ee` |
| `d-i/forky/payload.manifest` | `1353ecbeee90552709d259fd21df26f68009bfdc299460ace46c6f624a06433b` |
| `d-i/forky/preseed.cfg` | `46fe9b42ce8468edfe5926fdaeee6ed01fc0d95eeddded1de7dee3455abfcd65` |

These hashes identify this generated snapshot. They demonstrate serialization
and integrity agreement, not an installed-system deployment or runtime test.
