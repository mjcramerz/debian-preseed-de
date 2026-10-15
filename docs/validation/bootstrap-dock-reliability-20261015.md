# Bootstrap dispatch and dock supervision review — 2026-10-15

## Scope and observed defects

The checkout was clean before this work. This was a focused source review of
bootstrap dispatch, installer module loading, generated artifact publication,
managed application service ownership, veth lease handling and dock supervision.
It does not certify every implementation in the repository. Changes are limited
to two demonstrated failure paths and their fixture regressions.

1. `scripts/common/bootstrap.sh` built a `runner_args` string and expanded it
   unquoted. A source path containing spaces, or a wildcard matching a local
   path, could change the runner's argument count or values. Preparation calls
   also relied on the caller's `errexit` context rather than explicitly returning
   their failure status.
2. `hooks/target/usr/local/libexec/labwc-panel-run` performed synchronous writes
   and flushes for each diagnostic line. A full output pipe could stop the
   supervisor inside a write, preventing its deadline loop from escalating a
   stop signal or finishing the post-exit drain.

## Changes and installation wiring

- Phase dispatch now builds function-local positional arguments and invokes
  the runner with `"$@"`. Resolution, environment loading, path selection,
  persistence and fetching return their failure status before any runner runs.
  The phase selection and runner paths are unchanged. The second pass also
  traced the real persistence helper: its path lookups, directory preparation,
  state writes and opposite-source cleanup now check failures explicitly.
  A failed write cannot reach cleanup or be hidden by a later successful
  command when a caller tests the function's status. Directory creation reuses
  the resolved state-file parent, avoiding a redundant command substitution.
- Dock output uses separate queues for stdout and stderr, with a 256 KiB read
  threshold per stream. Child reads pause under output backpressure. Writes are
  nonblocking and batched; splitting complete lines in one pass replaces repeated
  deletion from the front of the input buffer. Exact known diagnostic coalescing
  remains in the existing `Coalescer`.
- `poll` handles both the service journal descriptors and regular-file output.
  The original output blocking flags are restored in reverse setup order, including
  on spawn failure. This also accounts for stdout and stderr sharing an open-file
  description.
- The existing five-second escalation and two-second drain budgets remain.
  After child exit, undelivered output and inherited pipe writers share that
  two-second budget. An output sink still blocked at expiry can lose queued or
  unread tail diagnostics; it cannot keep the supervisor waiting indefinitely.
  No measured CPU or latency improvement is claimed.
- The bootstrap entrypoint continues fetching `scripts/common/bootstrap.sh`
  from the pinned payload. `scripts/desktop/components/target-assets.sh` already
  stages the dock helper as mode `0755` and its user unit as mode `0644`.
  `crystal-dock.service` continues using the helper with `KillMode=control-group`
  and `TimeoutStopSec=10s`. The existing service enablement and AppArmor attachment
  cover the same executable and permissions.

Veth policy, systemd unit settings, AppArmor policy, application defaults and
private Xwayland implementations were not edited. No software was compiled or
installed, and no host service or configuration was changed.

## Added regressions — not executed

All additions remain behind the existing mandatory isolation gate.

`tools/tests/test_installer_modules.py`, `PhaseDispatchContracts`:

- All five phases preserve spaces and literal wildcard arguments, including a
  wildcard with an actual matching path in the fixture.
- Six injected preparation failures retain status `37` and never invoke a
  pre-existing fixture runner. The call is deliberately in a shell conditional
  to cover contexts where POSIX `errexit` is suppressed.
- Runner status `23` reaches the caller unchanged.
- An explicitly supplied runner bypasses default runner-path resolution,
  including when that default lookup would fail.
- The real persistence helper stops on directory preparation failure with
  status `37`, before state writes or cleanup, for both source kinds.
- A real state-file redirection failure never reaches opposite-source cleanup.
- Persistence cleanup failure retains status `41` for both source kinds.

These are dispatch fixtures with explicit replacements for preparation calls;
the persistence regressions call the production persistence function with
fixture `install` and `rm` commands and private state paths. They do not execute
real installer phases. Four additional methods were added on the second pass.

`tools/tests/test_scoped_desktop_fixes.py`, `PanelTests`:

- Mocked partial writes and `BlockingIOError` retain queued bytes.
- A fixture child emits more than one queue's worth of diagnostics to a regular
  file, including an unterminated tail and exit status `17`.
- An injected spawn failure restores both output flags in reverse order.
- A fixture child ignores SIGTERM and fills an unread output pipe; its supervisor
  must escalate and finish within the existing shutdown budget.

The two process fixtures execute checkout code and fixture children only. Their
environment has explicit `PATH`, `HOME`, `TMPDIR`, locale and bytecode settings;
they use no desktop, service manager, installed management helper or external
network endpoint.

## Checks actually performed

- Read `AGENTS.override.md`, `Makefile`, `docs/test-isolation.md`, the isolation
  guard and init, and the complete pure build/publication path before generation.
- Used standard-library `ast.parse` on the dock helper and both edited Python
  test modules as source data. No repository module was imported or executed by
  this inspection. Both test modules retain the isolation gate before runtime
  imports.
- `git diff --check` completed without errors.
- A final source-mode inspection initially found mode `0600` on the four edited
  source/test files and the new report after editor writes. Those five owned
  paths were restored to mode `0644`; the repeated inspection confirmed all
  eight changed paths are regular mode-`0644` files with one link. This changed
  no payload input bytes or generated hashes.
- Executed only the permitted pure generation command:

  ```sh
  /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
  ```

  It completed with `built 1784 payload files`.
- Compared metadata before and after second-pass generation: 3,062 non-product entries were
  unchanged. The comparison excluded `.git`, the three generated products and
  their immediate directory timestamp. It included this report, whose verification
  figures were updated afterward.
- Independently inspected the archive as data: all 1,784 regular members,
  totaling 34,315,474 content bytes, match current source bytes and manifest
  SHA-256 values. Member paths are safe and unique; modes, ownership, timestamps
  and names are normalized. The archive and manifest pins in `preseed.cfg`, its
  transport-source pin and the gzip timestamp match the rebuilt snapshot.

| Generated product | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `7d71cf5ce6ead5568c2736645f2a8458f9d8c00553f7f1d0ac0bbf30bf8ddaff` |
| `payload.manifest` | `5a666813ba2b6a2c68b5f6cc5176db21f58e97bb29f009ef81f7e271d68d7df4` |
| `preseed.cfg` | `b79af276e3cf3e70e17bc5c0840f92e3fbc165ac46937b60436182ba699626e1` |

## Remaining acceptance

No prepared disposable environment was identified in this session. No tests,
shell syntax runners, source validators, native policy parsers, service probes,
benchmarks or installed helpers were run. The added regressions and existing
signal/exit-status tests remain unexecuted. No validation suite was interrupted.

Run the two focused tools-test modules through the approved disposable image's
`tools/test-init.py tools-test --pattern test_installer_modules.py` and
`tools/test-init.py tools-test --pattern test_scoped_desktop_fixes.py` entrypoints.
Existing dock signal/lifecycle regressions and a disposable Forky installation
with systemd 262 still need runtime acceptance before deployment. The snapshot
is generated and statically consistent; this is not a passing release gate or
evidence of a live deployment.

## Second-pass review

The follow-up reviewed the phase dispatcher, actual persistence/environment/fetch
helpers and all direct persistence callers, together with the dock's read/write
registration, buffer limits, partial writes, EOF handling, signal forwarding,
cleanup and shared stdout/stderr descriptor handling. Installation staging,
service ownership and AppArmor executable/signal grants were checked again as
source data. The dock source required no further changes in this pass.

The persistence issue was not covered by the original injected-dispatch test,
which replaced that helper. The additional regressions now exercise the real
helper in a conditional call, where POSIX shell `errexit` cannot be relied on.
No runtime test or benchmark result is inferred from this source review.
