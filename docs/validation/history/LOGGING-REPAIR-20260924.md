# Logging and installer prerequisite repair - 2026-09-24

This report supersedes the logging descriptions in the older validation reports.
The deployment target remains Debian Forky / systemd 261.2. This is a focused
repository change, not a replacement desktop, storage policy, or upstream build.

## Installer failure and ordering

The shared storage-family hook completes before the selected software/DevOps
helpers, and desktop deployment runs afterwards. The software and DevOps helpers
were invoking tmpfiles with `/etc/tmpfiles.d/59-log-layout.conf` before desktop
deployment had installed that file. An explicit absolute tmpfiles input is not
optional; creating its destination directories alone cannot fix this failure.

Both storage-family hooks now publish the shared logging foundation after final
volatile-mount preparation and before dispatch reaches the selected helpers. The
VM family uses the same Btrfs-family hook. The foundation contains the authenticated,
rendered 59/65 tmpfiles policies and the protected-path preflight helper. Publication
uses the existing atomic target-asset publisher and propagates failure. Software
and DevOps preflight the shared paths immediately before their native tmpfiles
invocations, and explicitly propagate preflight/tmpfiles failure even when called
from a conditional shell context. No missing-file error is suppressed.

Desktop staging, required-asset verification, payload generation and collector
startup also include the new application route and executable size-rotation helper.
Both journal-policy validators now agree with the configured socket transport.
Tailscale and CrowdSec informational paths name the actual system collector instead
of removed, nonexistent dedicated service files.

## Installed logging path

The main path is now:

```
application/service -> journald -> local syslog socket -> imuxsock
  -> existing priority/security routes
  -> regular local user UID: /var/log/managed/apps/apps.log, then stop
  -> remaining real system/service records: /var/log/managed/system/system.log

kernel -> imklog -> existing kernel/security routes
                 -> /var/log/managed/system/kernel.log
```

There is one generic application output, not a program-to-directory mapping.
The shipped `44-components.conf.tmpl` falls from 245 lines and 89 regex call sites
to 23 lines and zero regex calls. It neither constructs a combined process identity
nor serializes generic records as JSON. The application route is based on trusted
socket UID 1000-59999, not an application name, path fragment or claimed tag. System,
dynamic and nobody accounts are excluded. Missing credentials go to the system
fallback. Application names never become output paths.

The shared policy has 111 settings rather than 275: obsolete application/service
catalog entries were removed, and three explicit input/rotation settings added.
No Brave, LibreWolf, Floorp, Zen, Vivaldi or other speculative application logging
directory is configured. The layout creates only real collector outputs and
ancestors needed by installed native producers. It does not delete historical
logs left by a previous installation or invent replacement log records.

Existing authentication, AppArmor, firewall, storage, USB, scanner and explicit
power-event routes remain. AppArmor retains its native audit-compatible text.
The audit forwarding route requires trusted root UID and a live audisp-syslog
executable, rather than trusting an application-supplied program tag. The native
auditd file remains authoritative. Private model/scanner socket rulesets are
preserved; their sensitive/native files are not folded into the generic apps file.
Existing notification signals remain signals derived from actual security events,
not fabricated application logs.

`imjournal`, its journal cursor and its database-reading overhead are removed.
`ForwardToSyslog=yes` is validated at install and startup. `ReadKMsg=no` remains,
so imklog is still the one managed kernel input. Credential annotation is retained
for safe routing; command-line data is not added to generic output. The low-volume
power-event JSON uses only fields available on this transport, not invented
journal unit/boot metadata. Full structured records remain in journald.

## Size rotation and overload behavior

All 27 configured omfile outputs, including the five notification signals, have
one native omfile callback at **2,097,152 bytes (2 MiB)**. The callback keeps four
numbered archives. It runs only when the writer reaches the threshold: no polling
service, 15-minute scan, compression process, copytruncate or collector-wide HUP
is involved for these files. Ordinary writes remain buffered; the existing
explicit power-event durability setting is preserved.

The root-only Python standard-library helper accepts exactly one compiled-in
output pathname. It rejects traversal, symlinked/writable/non-root ancestors,
symlinked or multiply-linked files, incorrect ownership/modes, unsafe locks and
concurrent rotation. It pins parent directories with file descriptors, checks the
entire bounded archive set before mutation, renames rather than copies, and
syncs directory changes once per rotation. Rsyslog closes its file before the
callback and subsequently opens the replacement itself. A refusal is an error,
not permission to truncate or weaken file ownership. Correct the underlying
permission/path error before restarting a collector with a disabled output.

The threshold is **not a strict maximum file size**: rsyslog can complete a record
or batch before rotating. No log entry is split merely to meet a byte boundary.
Numbered archive retention is count-based, not the previous seven-day collector
expiry. Power-directory aging explicitly excludes the writer-owned action log,
its numbered archives and its lock files.

The previous logrotate stanzas for these collector outputs are replaced in place
with retirement comments, preventing two rotation owners on reinstalls. The
logrotate timer no longer runs every 15 minutes. A daily vendor-style invocation
is retained only for native file producers. Repository-owned Fail2ban and
Codex/ChatGPT runtime policies use `size 2M` rather than time-based rotation; their
size is checked when logrotate runs, not continuously. The user-owned Codex files
retain copytruncate because their unmodified producers hold the file descriptors.
Auditd and ClamAV use their own native 2 MiB policies. No upstream producer is
patched and no replacement producer is compiled.

The main dispatch queue is bounded at 2,000 messages. The apps output has a
1,000-message queue and bounded 64 MiB disk assistance; its zero enqueue timeout
prevents a full apps queue from indefinitely blocking later security work. The
primary socket limits notice/info/debug messages to 2,000 per process per 30
seconds. Warning and higher-severity records are not filtered by that severity
threshold. Existing journald rate limits still apply independently.

These are deliberate availability tradeoffs, not a promise of lossless logging.
Socket forwarding has no journal replay/cursor after collector downtime, and a
full nonblocking input/output queue can drop records. Persistent journald remains
the default explicit host choice; the existing opt-in volatile policy is retained.
Thus this change removes journal rereading and generic regex/JSON work, but does
not claim to eliminate the journal's own persistent write or benchmark a specific
CPU/I/O reduction. Omfile's 2 MiB callbacks also have a finite per-rotation cost.

## Hardware, lifecycle and scope

No CPU/GPU tuning defaults, calibration values, source builds, package selections,
transient-service lifecycle, launchers, compositor policy or Xwayland behavior
were changed. Hardware tuning remains opt-in and retains capability checks,
transaction/rollback handling and existing system/user/AppArmor wiring. The
Intel-only, NVIDIA-only and combined policy compositions were checked offline.
No physical tuning, suspend/resume, GPU isolation or unattended partitioning run
was performed in this container.

The archive contains the whole repository, including regenerated `preseed.cfg`,
`payload.manifest` and `payload.tar.gz`, not just a patch. Publish the matching
repository as one immutable/atomic release; do not mix a new preseed with an old
payload or manifest. Existing profile, disk and credential review requirements
still apply.

## Validation evidence

| Check | Measured result |
| --- | --- |
| Focused logging regression suite | 114 passed; 2 native-rsyslog tests skipped |
| Full installer/repository suite, four shards plus standard-deadline reruns | 2,576 passed; 53 skipped; 1 pre-existing fixture deadline still fails |
| Repository tooling suite, final isolated run | 179 passed |
| Shell parsing | 291 files; 593 parser checks passed |
| Intel, NVIDIA and combined hardware policy compositions | 9 offline systemd/AppArmor checks passed |
| Native logrotate parser | 20 repository fragments accepted in a private dry-run fixture |
| Release consistency | Build/pins, 111-setting logging schema, 10 profiles and 59 preseed files passed |
| Payload integrity | All 1,525 authenticated members match the manifest; no duplicate or unsafe members |
| Protected Xwayland/launcher/hardware-policy files | 89 byte-for-byte unchanged |

The broad suite was not a single clean run: initial parallel runs included stale
build observations and timing failures. The source was then frozen, rebuilt and
the affected original assertions rerun individually. The local preseed fixture
passed its original 70-second deadline in 58.35 seconds. The one remaining
standard-deadline failure is
`test_repository_transport.RealBootstrapTests.test_opposite_role_fails_before_preflight_marker`.
It also fails on the unmodified uploaded repository. A separate diagnostic kept
all behavior assertions but observed for up to 30 seconds rather than the
fixture's eight seconds; it observed the correct fatal record after 10.17 seconds,
verified no preflight-success marker, and verified that the fatal bootstrap did
not return to the installer. That diagnostic is not counted as a standard-deadline
test pass, and the original repository test deadline was not weakened.

The broad code audit has 491 direct passes and 214 structure-only checks. It also
has 158 dependency-blocked entries, 579 inventory-only entries and 11 JavaScript
templates requiring rendering; these categories are not misrepresented as runtime
passes. Full history, skip counts and limitations are preserved in the results JSON.

Final measured results and environment limitations are recorded in
`LOGGING-REPAIR-20260924-results.json`. They distinguish actual execution, offline
fixtures, skips and blocked dependencies. Historical reports are not evidence of
this revision passing on systemd 261.2.

The available container runs Debian 13 with systemd 257.9, not a booted Forky
installation. Packaged rsyslogd and the full Perl Moo/MooX dependency set are not
available here; external package retrieval was unsuccessful. Consequently native
rsyslog parsing/delivery tests are explicitly skipped here, not counted as passes.
The repository includes a private-socket integration test for credential-based
routing, actual size callbacks, newline handling and collector restart. It never
uses the host's /dev/log or journal. Native rsyslog `-N1`, journal-policy checking,
protected-path checking and tmpfiles creation remain mandatory target install/boot
gates. There is no claim that an unattended Forky boot or every hardware-specific
runtime failure has been reproduced or eliminated in this environment.

## Primary implementation references

Consulted on 2026-09-24; no upstream source was modified or built:

- Debian Forky rsyslog package, 8.2608.0-4:
  https://packages.debian.org/forky/rsyslog
- Rsyslog Unix-socket input, trusted properties, rate limiting and systemd socket:
  https://docs.rsyslog.com/doc/configuration/modules/imuxsock.html
- Native size callback and documented record/batch overshoot:
  https://docs.rsyslog.com/doc/reference/parameters/omfile-rotation-sizelimit.html
- Filename argument option, introduced in 2026 and available in the target release:
  https://docs.rsyslog.com/doc/reference/parameters/omfile-rotation-sizelimitcommandpassfilename.html
- Native close/callback/reopen and failure handling:
  https://github.com/rsyslog/rsyslog/blob/master/runtime/stream.c
- systemd 261.2 forwarding credentials and nonblocking delivery behavior:
  https://github.com/systemd/systemd/blob/v261.2/src/journal/journald-syslog.c
