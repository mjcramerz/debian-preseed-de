# Installed logging startup failure, 2026-10-16

## Subsequent integration pass

This section records the later integration pass and supersedes the earlier
generated-product hashes below. The initial incident evidence and runtime
acceptance limits remain applicable.

Four additional defects were corrected narrowly:

1. The generic application launcher could pass a relative `shutil.which()`
   result to `rsyslog-app-run`, whose public interface requires an absolute
   executable. The launcher now anchors only relative results to its current
   directory before handing off. It retains argument bytes and symlink/`..`
   traversal, without canonicalizing the executable or changing its basename.
   Absolute lookup results take the existing path without a new directory
   lookup. This agrees with the documented
   [Python 3.14 lookup behavior](https://docs.python.org/3.14/library/shutil.html#shutil.which).
2. The output supervisor restored stderr's original blocking mode before its
   outer exception handler called `print()`. That fatal diagnostic could then
   block failure exit on a full journal stream. Its bounded, error-class-only
   report now uses one nonblocking write, tolerates a closed/full sink and
   restores the original descriptor flags. Normal output capture, retry,
   child status and signal handling are unchanged.
3. `tools/check_logging.py` still required an obsolete polling-mode audit input,
   even though the checked-in production configuration and existing routing
   regressions require inotify. The checker now requires the same single
   inotify input. This mismatch already existed in HEAD; it was found while
   reviewing the current logging integration. No polling or second reader is
   introduced.
4. The logging catalog accepted nested private socket paths even though startup
   creates only the fixed protected parents and `CreatePath` is off. It also
   accepted paths exceeding the Linux pathname-socket capacity. The authoritative
   AWK parser now rejects those settings before staging. Alternate filenames
   directly inside the same protected parents remain supported, through 107
   ASCII path bytes. This leaves room for the terminator in
   [Linux's 108-byte `sun_path`](https://man7.org/linux/man-pages/man7/unix.7.html).

The new guarded fixtures cover relative/parent/symlink spellings and literal
arguments at the manager handoff, nonblocking/redacted fatal diagnostics with
descriptor restoration, and valid/invalid socket paths including the 107/108
byte boundary. The existing complete-catalog regression covers the repaired
checker. None of these tests was executed: no approved disposable test
environment was available. The test gate, init, relevant fixture imports,
Makefile and complete build/publication path were reviewed as source data.

The review also retraced native/Bitwarden/generic/qBittorrent/backend launch
callers, private ChatGPT capture, firstboot retry/completion, AppArmor attachment,
shared auth readers, catalog rendering and installer staging. No measured
latency or throughput improvement is claimed. The changes remove a launch
failure, a blocking error path, a stale validation gate and accepted settings
that cannot satisfy the runtime contract.

Completed checks for this pass:

- Standard-library AST parsing accepts all 24 changed Python inputs, including
  Python templates, plus both constant embedded Python drivers. No repository
  module or test was imported or executed.
- Literal catalog inspection reconciles all 114 keys and their schema bounds,
  all catalog references across 88 source inputs, and the three default socket
  paths against the created parents and length limit. The checker module
  literal matches the production inotify declaration.
- `git diff --check` reports no whitespace errors.
- Pure generation completed using `env -i PATH=/usr/bin:/bin HOME=/nonexistent
  LC_ALL=C.UTF-8 /usr/bin/make --no-print-directory build
  'PYTHON=/usr/bin/python3 -I -S'`: `built 1788 payload files`.
- Data-only archive inspection matches all 1,788 regular members and
  34,344,740 source bytes against source and manifest. Ownership, modes and
  timestamps are deterministic, and the archive/manifest/bootstrap-source
  hashes pinned by preseed agree with the current bytes.
- Before/after snapshots show generation changed exactly the three generated
  products; the other 2,341 files were unchanged. No additions, deletions or
  mode changes occurred during generation. This pass changed only three
  runtime sources, one checker, three existing guarded test modules, this
  report and the three generated products.
- All 43 copied incident files are unchanged. All three private Xwayland
  sources remain byte-identical to HEAD. Independent sidecar reviews failed
  at encrypted-context initialization; no independent review result is credited.

| Current generated product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `933e71fbb768bdc1219e2cdd6c04eca029f58e28f9b6a7d8eeefeabfb4ed6091` |
| `d-i/forky/payload.manifest` | `635200a31709fffb989befb5dfebf1d700b5061844ccade7fe8d194a6ebf29f6` |
| `d-i/forky/preseed.cfg` | `0732a19f33565c69706b51c9d8e1ddff2cb175b26c064be1e9313b640bb88dc1` |

These are static source/product results. No benchmark, native validator,
isolated test suite, fresh install or running-host repair was executed.

## Evidence and causal chain

The supplied `todo/managed/**`, `todo/installer-state/**` and `todo/journalctl`
capture contains 43 files, including 24 empty files. All supplied files were
read as data. Audit records were correlated by event ID; command arguments,
credentials, machine names and network identities are omitted from this report.
No copied file or repository helper was executed.

| Evidence | Observation |
| --- | --- |
| `todo/journalctl:1011` | rsyslog 8.2608.0 warns that the application input ruleset lacks a dedicated queue. |
| `todo/journalctl:1012` | rsyslog acquires the systemd syslog socket descriptor. |
| `todo/journalctl:1013` | The rsyslog daemon starts. |
| `todo/journalctl:1166` | A service control process exits with status 1 after daemon startup. |
| `todo/journalctl:1167` | systemd terminates the daemon with SIGTERM. |
| `todo/journalctl:1170` | firstboot's required rsyslog dependency fails; the wrapper never runs. |
| `todo/journalctl:1330` | Repeated collector startups exhaust the service start limit. |
| `todo/journalctl:1333` | `syslog.socket` fails with `service-start-limit-hit`. |
| `todo/installer-state/installer.log:3812` | Installer `rsyslogd -N1` parsing had succeeded. This did not exercise service startup or post-start helpers. |
| `todo/installer-state/target-validated` | The target is prepared, but installation success is explicitly `not_yet`. |

The copied journal has no diagnostic identifying the exact failing post-start
command. The repository nevertheless contains a deterministic defect matching
this failure sequence: `rsyslog-openai-socket` transferred the socket to the
desktop UID before calling `chmod` as root.

The [Debian rsyslog 8.2608.0-4 service source](https://sources.debian.org/data/main/r/rsyslog/8.2608.0-4/debian/rsyslog.service)
permits `CAP_CHOWN` and excludes `CAP_FOWNER`. Its stdout is null and stderr
inherits stdout by default. Both facts were checked against the package source;
the same service text was retrieved from Debian's packaging repository.
[Linux chmod semantics](https://man7.org/linux/man-pages/man2/chmod.2.html)
require the caller to own the inode or hold `CAP_FOWNER`. Root UID alone does
not satisfy that requirement after the ownership transfer. An AppArmor allow
rule cannot restore a capability removed by systemd's bounding set.

This defect explains a post-start failure and the subsequent dependency/start
limit cascade. The original failing command's stderr is absent, so attribution
to that particular command remains a source-based inference rather than a
direct observation in the copied journal.

## Corrections

- Reclaim root/group socket ownership first, set mode 0660 while root owns it,
  and transfer to the mapped account last. This is also retry-safe after a
  partial handoff. Preserve the protected parent, dedicated group, account UID
  bounds and existing socket destination. Reject a symlink socket. Report
  individual ownership/mode/stat failures explicitly. No extra capability or
  relaxed service sandbox is introduced.
- Set the managed rsyslog drop-in's `StandardError=journal`. Errors in pre/post
  commands reach journald independently of the failed collector. Retain Debian's
  stdout policy.
- Give the application input ruleset a bounded LinkedList queue, one worker and
  zero enqueue wait, matching its explicit input binding. Retain the existing
  disk-assisted file action queue and its persistence/retry policy. This fixes
  the queue warning and bounds dispatch; no measured speedup is claimed.
- Change only firstboot's rsyslog dependency from `Requires` to `Wants`, retaining
  `After`. Keep AppArmor, auditd, journal sealing, local filesystems and tmpfiles
  as required dependencies. The wrapper can therefore collect persistent
  diagnostics when rsyslog fails. At the end of validation, independently
  require `rsyslog.service` and `syslog.socket` to be active and capture their
  status with existing bounded I/O. A failed check increments the failure count;
  the wrapper retains status 1 and does not publish completion or run success
  cleanup.

## Other captured diagnostics

| Component | Evidence and disposition |
| --- | --- |
| AppArmor | All 428 copied AVC records are STATUS records. No DENIED record appears in the supplied audit or AppArmor logs. No policy widening is justified by this capture. |
| Audit syscall failures | All 69 unsuccessful SYSCALL records are ENOENT or ENOTEMPTY. These cover PATH probes, absent optional cleanup links and nonempty systemd directories. All 27 unsuccessful exec probes have a successful exec for the same PID. The three vdirsyncer probes are immediately followed by successful execution of `/usr/bin/vdirsyncer`. They are not missing-calendar failures. |
| Fail2ban | The SSH jail starts with pyinotify and watches the managed auth log. Its new-database warning is initial state. Rsyslog failure subsequently interrupts delivery into that file. |
| CrowdSec | Core bootstrap and CAPI activation complete; the nftables bouncer starts and imports decisions. Console enrollment remains pending external approval. The early not-enrolled errors precede the recorded pending-approval result; repository code cannot grant console approval. |
| CrowdSec qBittorrent acquisition | The optional native application log does not exist before the application/media path is present. This is a warning, not a collector or CrowdSec startup failure. |
| Secondboot cleanup | It removes completed CrowdSec/Tailscale bootstrap assets and explicitly retains firstboot assets until firstboot publishes completion (`todo/journalctl:1355`). No premature firstboot cleanup is shown. |
| Tailscale | Initial stopped/warming-up health messages resolve to Running/ok and successful bootstrap. The netfilter-off warning reflects the configured firewall ownership. |
| Storage, NFS and zram | Copied records show successful mounts, managed NFS source/home bind mounts and zram setup. The XFS autofsck records describe error-only reporting, not a failed filesystem check. |
| nftables | All 11 copied firewall records are accepted outbound packets. No rejected flow is shown in this file. The independently recorded CrowdSec bouncer rules are active. |
| USB firmware | Four copied UCSI errors report `UCSI_GET_PDOS`/error 88. These are kernel/device power-delivery diagnostics. The capture does not establish a repository configuration correction. No firmware, kernel or USB policy is changed. |
| Bluetooth | A missing initial identity key is reported; the Bluetooth daemon starts. No captured service failure or pairing attempt establishes a separate repair. |
| sudo | One PAM conversation failure is present. The capture does not establish its initiating interaction or a sudo/AppArmor policy defect. Authentication policy is preserved. |
| Xwayland | Labwc logs a missing global Xwayland binary and continues without it. The explicit private-Xwayland policy is preserved; no Xwayland file is changed. |
| Installer package scripts | Mullvad/Zoom attempt AppArmor activation in the installer environment. Mullvad policy validation succeeds and its deferred activation is staged. These package-script diagnostics are distinct from the installed collector failure. |
| Empty managed logs | Empty scanner/application logs do not prove failure of every producer. The collector stops early and firstboot never ran; several producers also had not been used. |

## Verification boundary

The repository's `AGENTS.override.md` prohibits tests, native validators,
repository module imports and installed management helpers on the development
host. No prepared disposable environment was supplied. No test, shell syntax
checker, rsyslog parser/daemon, systemd manager, AppArmor parser or host service
operation was executed in this incident pass. No running installation was
modified. Independent review delegation failed at agent initialization with an
encrypted-context runtime error; no child review is credited.

Guarded regressions now model CAP_CHOWN without CAP_FOWNER, both fresh and
partially handed-off sockets, failures in each ownership/mode phase, invalid
UIDs, independent startup stderr, all four collector/socket health combinations,
and the actual firstboot wrapper/marker publisher across failure, successful
retry and completed-work skip. The lifecycle fixture substitutes all four
diagnostic stages, redirects state to its private tree and uses no manager or
installed helper. These are source fixtures and have **not been run**. The
capability fixture models the access decision; it is not a native capability
or full systemd lifecycle test.

Permitted checks are source/diff inspection, standard-library AST parsing,
literal staging/dependency analysis and archive/hash comparison as data.
`make build` is the separately permitted pure serialization operation. Its
complete Makefile/build/publication path was inspected before use; it executes
no tests or validators. Generation and final source/product comparison results
follow below.

### Completed source and product checks

- `git diff --check` reports no whitespace errors.
- Standard-library AST parsing accepts all 22 currently changed Python inputs,
  including the two updated regression modules. No repository module or test
  was imported or executed.
- Source inspection follows all five changed runtime assets through their
  existing installer staging paths. Firstboot retains its required security
  prerequisites and success-only completion/cleanup path. The two new health
  checks run immediately before the final validation result.
- Data-only fixed-pattern comparison reconciles 20 firstboot predicates with
  checked-in target assets and eight generated Podman unit predicates with
  their canonical templates. This is a bounded comparison, not execution of
  firstboot's full set of checks.
- Pure generation completed with `env -i PATH=/usr/bin:/bin HOME=/nonexistent
  LC_ALL=C.UTF-8 /usr/bin/make --no-print-directory build
  'PYTHON=/usr/bin/python3 -I -S'`: `built 1788 payload files`.
- Before/after content and mode snapshots show generation changed exactly
  `payload.tar.gz`, `payload.manifest` and `preseed.cfg`; the other 2,341 files
  were unchanged. No file was added/deleted and no mode changed during
  generation.
- Data-only tar inspection matches all 1,788 regular members and all
  34,343,478 source bytes against both source and manifest. Tar ownership,
  modes and timestamps are deterministic. The archive/manifest/source SHA-256
  pins in preseed agree with their current bytes.
- All 43 supplied evidence files retain their original hashes. All existing
  baseline file modes are preserved. Incident changes are limited to five
  runtime assets, two existing guarded regression modules, two reports and
  the three generated products.
- The private Xwayland AppArmor source and both compatibility runtime modules
  remain byte-identical to HEAD.

| Generated product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `42ecbd296861e428af1c1f9101e48cce8bfd97163bc0e2abaaa67aa5cc2ce24a` |
| `d-i/forky/payload.manifest` | `24681e00b00773ca344b4747c994a692f5c8493f1b549df6ca00cfad48e3a773` |
| `d-i/forky/preseed.cfg` | `2f80c30e8de2b41a82e8374633b3dbaf29349dc7826725e5aad727d80ab6cc40` |

Native rsyslog/systemd startup, socket handoff under the packaged service
sandbox, firstboot retry/completion and a fresh install remain unverified.
The guarded suite must run in the approved disposable environment. The
repository and generated payload contain the correction; this work does not
claim that the already-running installation has been repaired.
