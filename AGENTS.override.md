# Static inspection only; disposable execution environments are prohibited

**NEVER create, provision, launch, request or use a disposable VM, container,
chroot, sandbox image or other disposable execution environment for work in
this repository. This prohibition is permanent repository guidance and applies
to tests, validation, audits, benchmarks, smoke checks and native integration.**

Do not propose or request a disposable environment as a next step. Existing
isolation guards, fixture code, image entrypoints and historical validation
documents do not authorize their execution. Keep the guards intact; never
disable them or substitute host execution. Tests and validation runners remain
unexecuted. Use static inspection and the explicitly permitted generation
commands below, and report the resulting verification limits accurately.

## Absolute prohibition on host access and host changes

**NO TEST MAY READ, USE, OR MODIFY THE REAL HOST'S CONFIGURATION, SERVICES,
PACKAGE STATE, SECURITY POLICY, NETWORKING, DEVICES, OR USER DATA. NO TEST MAY
EXECUTE AN INSTALLED HOST MANAGEMENT HELPER.**

This applies to every test, fixture, discovery/import hook, test runner,
validation command, audit, benchmark, and smoke check in this repository. A
test's name, comments, mocks, temporary directory, or use of a namespace is not
proof that it is isolated.

- Never run tests or validation runners on the development host or in a
  disposable environment. Stop at static inspection. Do not use automatic
  fallback, an opt-in environment variable, or elevated privileges.
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
  or `/usr/local/sbin/*`. Review checkout fixture programs as source only, with
  all state paths and commands explicitly controlled.
- Review privileged-command and external-service fixture implementations as
  source data only. Do not import or execute fixtures, or run native integration
  checks. No host sockets or writable host mounts are permitted.
- Fixture source must not inherit host HOME, XDG runtime directories, D-Bus
  addresses, service variables, credentials, or full `PATH`.
- Fixture source must bound writes to its private owned tree and reject paths
  outside that tree. Cleanup must name only resources owned by that fixture.
  These source requirements do not authorize fixture execution.

## Work in this checkout

`make build` is generation only. It may write exactly `d-i/forky/payload.tar.gz`,
`d-i/forky/payload.manifest`, and `d-i/forky/preseed.cfg`. It must not execute any
tests, validators, shell snippets, browser generators, policy parsers or host
management helpers, or rewrite source inputs. This pure serialization command
is permitted in the checkout. Source validation runners, including the guarded
`make check` / `make validate` commands, must remain unexecuted.

### Standalone inventory tooling: manual use only

`tools/inventory.py` and `tools/inventory_apt.py` are standalone developer
utilities for the user to run manually. **NEVER execute them automatically or
integrate them into installer code, the installed system, payloads, builds,
validation, test discovery, CI, hooks or other runtime flows.** Coding agents
must inspect their source as data and leave their execution to the user.
Importing the collector from the manually invoked inventory entrypoint is part
of that standalone utility; it does not authorize any other integration.
Manual Python dependency resolution requires PyPA `packaging >= 23.2` in the
developer's Python environment. The utilities must never install dependencies.

The existing `make inventory` target is a manual convenience invoking
`tools/inventory.py --refresh-apt`. It scans installer checkout sources as data,
acquires public HTTPS APT metadata and declared public download manifests or
bounded archive metadata as data,
and writes **only root `inventory.json`**,
including selected binary URLs and matching available source archives.
`inventory-apt.json` is a legacy artifact and must not be generated, read as a
cache or required by the redesigned tooling. Direct invocation without
`--refresh-apt` is offline discovery and must identify missing metadata.
Private acquisition scratch and recovery evidence are not inventory products;
retain recovery evidence when restoration is uncertain. Never execute installer
code, tests, validators, host management helpers or package code, or read host
package state. `make build` must not invoke inventory generation, and
`make inventory` must not rebuild the payload. Do not add a download target.

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
- Review `docs/test-isolation.md` for the static-only execution boundary.
  Never use a disposable environment or host fallback, including native syntax
  checks or test discovery imports. Do not ask for an environment to run them.
- Author and inspect unexecuted failure-injection fixtures for changed contracts:
  exact previous-state recovery or retained evidence, concurrent writer/cleanup
  ownership, identity replacement, bounded termination and correct result propagation. Target
  policy, boot, GUI, network and hardware behavior remains unverified without
  native evidence; this does not authorize executing any native check.
- Record the exact source revision or working-tree fingerprint, fixture
  revision, generated artifact hashes and target image/package versions with
  recorded evidence when available. Distinguish unexecuted fixtures and static
  inspection from historical execution evidence; do not fabricate test, target
  image or package results. List verification limits explicitly.
- Rebuild generated payload products when their inputs change, using only the
  reviewed pure serialization path. Compare generated bytes and manifest pins
  with the current inputs as data. Serialization consistency does not prove
  rendered runtime behavior or a passing acceptance gate.
- Keep native application launch and private Zoom/Discord launch/shutdown as
  regression invariants. Preserve exactly the existing two-app eligibility
  boundary without changing Xwayland implementation or configuration.
