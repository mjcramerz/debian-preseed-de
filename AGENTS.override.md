# Test isolation is mandatory

## Absolute prohibition on host access and host changes

**NO TEST MAY READ, USE, OR MODIFY THE REAL HOST'S CONFIGURATION, SERVICES,
PACKAGE STATE, SECURITY POLICY, NETWORKING, DEVICES, OR USER DATA. NO TEST MAY
EXECUTE AN INSTALLED HOST MANAGEMENT HELPER.**

This applies to every test, fixture, discovery/import hook, test runner,
validation command, audit, benchmark, and smoke check in this repository. A
test's name, comments, mocks, temporary directory, or use of a namespace is not
proof that it is isolated.

- Never run tests directly on the development host. Execute them only inside
  an explicitly prepared disposable environment with no access to host state.
  If that environment is unavailable, stop at static inspection. Do not use
  automatic fallback, an opt-in environment variable, or elevated privileges.
- Never bind the host root, host `/etc`, `/var`, `/run`, `/proc`, `/sys`, `/dev`,
  user HOME, runtime sockets, or installed `/usr/local` helpers into a test.
  Namespace isolation alone does not make a host-root bind safe.
- Never contact the host system or user systemd manager, D-Bus, desktop session,
  CrowdSec API, package manager, or other running daemon. Never start, stop,
  restart, reload, enable, disable, mask, or reset host services or timers.
- Never load AppArmor policy, change host firewall rules, routes, interfaces,
  sysctls, mounts, storage, permissions, ownership, package repositories,
  package lists, credentials, or any file outside owned test fixtures.
- Never execute installed host helpers such as `/usr/local/libexec/apt-repo-local*`
  or `/usr/local/sbin/*`. Fixture programs must come from the checkout or an
  isolated test image, with all state paths and commands explicitly controlled.
- Replace privileged commands and external services with explicit fixture
  implementations. Run native integration checks only inside the disposable
  environment, using its own procfs, sysfs, devices, package tree, managers,
  sockets, and network. No host sockets or writable host mounts are permitted.
- Use a minimal fixture environment. Do not inherit host HOME, XDG runtime
  directories, D-Bus addresses, service variables, credentials, or full `PATH`.
- Keep test writes inside a private fixture tree or the disposable environment.
  Reject paths that resolve outside that tree. Cleanup may remove only resources
  created and owned by that test.

## Work in this checkout

`make build` is generation only. It may write exactly `d-i/forky/payload.tar.gz`,
`d-i/forky/payload.manifest`, and `d-i/forky/preseed.cfg`. It must not execute any
tests, validators, shell snippets, browser generators, policy parsers or host
management helpers, or rewrite source inputs. This pure serialization command
is permitted in the checkout. Source validation belongs to the separately
guarded `make check` / `make validate` commands in the disposable environment.

`make inventory` is a separate permitted generation command. It invokes
`tools/inventory.py --refresh-apt` and checks the payload archive hash against
both root JSON inventories before any scan or network acquisition. On a stale
pair it reads only `d-i/forky/payload.tar.gz` members as data, acquires public
HTTPS APT metadata and generates root `inventory-apt.json` and `inventory.json`.
These are its only persistent outputs on success; acquisition and publication
use private temporary files, with recovery evidence retained on an uncertain
rollback. It must not execute installer code, tests, validators or
host management helpers, or read host package state. Direct invocation without
`--refresh-apt` remains offline and writes only root `inventory.json`.
`make build` must not invoke inventory generation, and `make inventory` must
not rebuild the payload.

Preserve all unrelated and uncommitted work. Inspect callers and execution
helpers before editing. Keep fixes narrow and deterministic. Do not build
software from source or change the existing private Xwayland policy for Zoom
and Discord.

Following a host-impact report, do not run any test or validation runner until
its complete execution path and isolation boundary have been reviewed. Static
inspection must parse source as data without importing or executing repository
modules, helpers, shell snippets, or Makefile recipes. Read-only investigation
of a reported host failure is separate from testing; it does not authorize a
host repair, service restart, or configuration change.

Report exact changed paths and checks. Distinguish static inspection, mocks,
isolated integration, and live host execution. Never claim a test passed when
it was not run. Report any interrupted validation and stale generated artifacts.

## Runtime and authority contracts

- The installation target is Debian Forky with systemd 262. Validate the
  rendered target's interpreter, packaged modules and service contracts; do not
  infer target compatibility from the development host.
- Trace an affected entrypoint through its delegates, renderer, installed paths
  and applicable AppArmor, authorization and service policy before editing.
  At the existing installation verification boundary, reject unresolved
  installer tokens, invalid configured identifiers, missing delegates and
  incorrect code ownership or modes before consumer activation. Offline staging
  must not start services or contact a running host manager.
- Keep same-UID desktop state distinct from privileged code/import authority.
  Privileged imports consume validated private snapshots. Do not execute
  managed Perl imports or their BEGIN blocks as a host inspection technique.
- Preserve the shared Perl capture API's raw wait status, including timeout
  `124 << 8` and signal bits. Decode exactly once at public adapters; cover
  affected adapters with fixtures rather than rewriting unrelated runners.
- Make operation deadlines cover streaming, retries and final waits, with a
  separate bounded cleanup budget. Retain owning service cgroups for jobs that
  daemonize or escape a session. Preserve intentional interactive operations.
- In the root container-bootstrap runner, pin processes with pidfds before
  validating their current session and liveness; signal only verified pinned
  identities. Close descriptors on every path and retain the total cleanup
  deadline. Missing identity evidence must not trigger a numeric-PID fallback.
- Bind selected device, model staging, namespace and storage identities through
  mode changes and mutation. If an installed tool cannot bind the selected
  identity safely, return unavailable before mutation; do not invent selectors
  or substitute a different device.
- Preserve the rootless container engine, shared socket authority, service
  lifetime and existing-store no-reset rules when changing lifecycle helpers.

## Recovery, concurrency and bounded artifacts

- Validate a complete candidate before publication. Keep AppArmor parent and
  all affected local child modes consistent before the single explicit reload,
  then verify the loaded result inside the transaction.
- Keep standalone nftables recovery separate from the desktop transaction.
  Restore only owned tables and previous file bytes, metadata or absence;
  preserve unrelated policy.
- Retain private recovery material until restoration and any required reload
  are proven. A failure return alone does not prove rollback. On uncertainty,
  report the retained recovery path and a distinct outcome-unknown result.
- Synchronize durable published files, recovery files and their parent
  directories at the relevant transaction boundaries. Do not impose durable
  writes on unrelated transient UI state.
- Prune and reset use the same ownership locks as writers. Validate names and
  restat identity while holding the lock; skip active state. Do not introduce
  a second competing lock protocol or broaden cleanup ownership.
- Enforce aggregate parser/extraction limits during work, before member lists,
  expanded bytes or inode use can exhaust resources. Reject unsafe members,
  reuse packaged tools and existing isolation, and retain workspaces when
  worker termination cannot be proved. A watchdog is not a filesystem quota.
- Preserve final artifact identity checks when accepting staging names. Keep
  temporary files private and pass passwords through private inputs, never
  command arguments or diagnostics. Consume repaired output in the next stage
  and require a valid final artifact before reporting success.
- Document artifact trust accurately: content hashes establish byte
  consistency, vendor signatures establish the verified vendor claim, and local
  repository signing authenticates the local publisher. These are distinct.
  Check each redirect before requesting its destination under the applicable
  input policy; preserve HTTPS, credential handling and bounded hop/time limits.
- Keep failure, cancellation, unavailable and outcome-unknown results distinct
  across callers and UI adapters. Do not automatically retry an uncertain
  mutation. Keep secrets and raw hostile payloads out of diagnostics.

## Revision-specific acceptance evidence

- For affected audit work, review the relevant findings and acceptance gates in
  `debian-preseed-de-audit.md`, the current implementation and its callers.
  Historical remediation reports describe their recorded snapshots; they do
  not establish acceptance of a later working tree.
- Review `docs/test-isolation.md` and the complete execution path before using
  a prepared disposable environment. Use its own target packages, managers,
  policy, devices and sockets. No unavailable environment permits a host
  fallback, including native syntax checks or test discovery imports.
- Use failure injection for the changed contracts: exact previous-state
  recovery or retained evidence, concurrent writer/cleanup ownership, identity
  replacement, bounded termination and correct result propagation. Target
  policy, boot, GUI, network and hardware claims require isolated native
  operations appropriate to those boundaries.
- Record the exact source revision or working-tree fingerprint, fixture
  revision, generated artifact hashes and target image/package versions with
  acceptance results. Distinguish unexecuted fixtures, static inspection,
  isolated mocks and native integration; list remaining gates explicitly.
- Rebuild generated payload products when their inputs change, using only the
  reviewed pure serialization path. Compare generated bytes and manifest pins
  with the current inputs as data. Serialization consistency does not prove
  rendered runtime behavior or a passing acceptance gate.
- Keep native application launch and private Zoom/Discord launch/shutdown as
  regression invariants. Preserve exactly the existing two-app eligibility
  boundary without changing Xwayland implementation or configuration.
