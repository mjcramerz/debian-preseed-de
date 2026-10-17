# October 17 incident review and bounded runtime corrections

## Scope and completion boundary

Baseline: `5c7b69ea6d9e934de82cd09a259e9a30508fd75f`. The checkout was clean
before this work. The requested objectives were investigated in numeric order.
Two concrete runtime defects found in the related code review are corrected
below. The supplied evidence also contains upstream application diagnostics,
external approval requirements, forwarding loss and hardware errors that remain
unresolved. This report does **not** certify that every logged error is fixed,
that every source branch is correct, or that target acceptance has passed.

No test, repository import, native syntax validator, installed management
helper, running service manager, policy loader or host configuration probe was
executed. No prepared disposable Forky VM/image was supplied. The repository's
`AGENTS.override.md` and `docs/test-isolation.md` prohibit host execution as a
fallback. The fixtures added here remain **unexecuted**.

The two runtime edits use the existing packaged Python facilities. No package,
source compilation, AppArmor grant, network/firewall setting, Xwayland source,
Xwayland configuration or application eligibility rule was changed. The private
Zoom/Discord boundary is retained. Sidecar agents failed to initialize with
encrypted-content hydration errors; no independent review result is credited.

## 1. Reported Tailscale and VS Code messages

### Tailscale control stream

`todo/journalctl:1449` reports one `PollNetMap` unexpected EOF. The next record
reports a new control-plane dial plan. Later records at lines 1474-1475 confirm
a successful DERP post-rebind ping and updated endpoints. The daemon PID is
unchanged. This is evidence of recovery, not a proof of uninterrupted peer
traffic or of the original connection's failure cause.

The captured daemon identifies itself as Tailscale 1.104.1. Its
[upstream map routine](https://github.com/tailscale/tailscale/blob/v1.104.1/control/controlclient/auto.go#L548-L614)
already retries interrupted polling with backoff. Its status path logs this
error without exiting the daemon. The repository's daemon drop-in retains that
native retry, `Restart=on-failure` and the port-80 Noise/HTTPS-443 fallback.
No restart watchdog, reauthentication loop, forced transport or log filter was
added for an already-recovered stream interruption.

The initial stopped/warming-up notices at journal lines 923 and 975 clear at
976 and 1055. Bootstrap reports completion at 1058. Missing initial profile and
optional logging configuration files precede successful first enrollment; this
capture does not justify manufacturing daemon state files. Netfilter-off is
the existing nftables-owned policy, not a request to enable another firewall
owner. Exact EOF cause and long-duration peer continuity remain unverified.

### VS Code DEP0169

`todo/journalctl:1490-1491` and `todo/managed/apps/apps.log:257-258` contain a
Node deprecation warning without a stack trace or subsequent application
failure. The installed launch path remains `/usr/share/code/code`, preserving
the foreground Electron process and transient-service lifetime. The managed
launcher contains no JavaScript `url.parse()` implementation to replace.

[Node's DEP0169 contract](https://nodejs.org/api/deprecations.html#dep0169-insecure-urlparse)
requires the application to migrate to WHATWG URL parsing. The corresponding
[VS Code issue](https://github.com/microsoft/vscode/issues/301941) and
[replacement pull request](https://github.com/microsoft/vscode/pull/302334)
were still open when inspected. This matches the warning class; it does not
identify the exact caller in this installation. The supplied capture does not
include its Code package version or a deprecation stack.

The warning remains unresolved upstream. No `--no-deprecation`, warning filter,
Node parser shim, package downgrade or vendor-bundle rewrite was introduced.
An isolated reproduction with the same signed Code package and
`--trace-deprecation` is required to identify the precise call site and verify
a vendor release that removes it. The fourteen unknown-option messages say
explicitly that the switches are forwarded to Electron/Chromium; they are not
evidence of failed Wayland/GPU option delivery.

## 2. Complete todo evidence inventory and dispositions

All **52 regular files**, including `todo/.~` and all four audit rotations,
were read as data: **8,246,756 bytes, 36,072 physical lines, 23 empty files**.
The companion `todo-20261017-inventory.json` records every path, byte count,
physical-line count, SHA-256, diagnostic candidate line and disposition.
Candidate scanning included error/failure/deprecation messages and forwarding,
suppression, overflow, degradation and taint diagnostics. Audit records were
correlated by event ID before classifying failed syscalls.

| Evidence | Finding and disposition |
| --- | --- |
| Current journal; `managed/network/veth.log` | Three application route/readiness pairs succeed. No broker setup rejection appears. Tailscale also reacts to veth changes; that alone does not establish a routing fault. |
| Four audit logs | 30,204 audit records. 142 failed syscalls return ENOENT: 42 executable PATH probes and 100 absent-entry cleanup probes. Five directory-removal calls return ENOTEMPTY. These records do not establish permission denial or failed higher-level cleanup. |
| AppArmor and audit | 435 AppArmor `STATUS` records, zero `DENIED` records. Mode reconciliation reports success. This is evidence about the supplied capture, not proof that every application branch is permitted. |
| `managed/security/crowdsec/crowdsec.log:273,292` | CAPI activation precedes Console enrollment. At journal 1118-1120, enrollment submission succeeds and is explicitly recorded as pending approval. Remote Console synchronization remains unavailable until the account approves enrollment and the engine picks up that state. No remote approval or service restart was performed. |
| CrowdSec grok warnings | The upstream sshd and sshd-success parsers define the same workaround patterns. Both parser nodes load. No local parser renaming, Hub-asset rewrite or collection removal is justified by this notice. |
| CrowdSec qBittorrent acquisition | The removable-volume log is absent at boot. The existing exact-path acquisition enables 30-second file discovery and inotify; no empty user log was fabricated and no polling/duplicate reader was added. Acquisition after the volume appears remains an isolated integration gate. |
| CrowdSec API/bouncer, Fail2Ban, auth | Local API responses/bouncer startup and the sshd jail start succeed. Fail2Ban's new-database warning is followed by initialization. These are not full detection/remediation acceptance tests. |
| `journalctl:1114` | **430 syslog forwards were missed.** Systemd 262 increments this diagnostic when nonblocking forwarding encounters a full receiving socket. Rsyslog starts receiving at journal 949-950, after early boot output. The loss interval and exact effective socket/queue limits are not captured. Existing output queues cannot recover input that never arrived. This remains an unresolved logging acceptance gate. |
| Historical `todo/.~:1368` | A separate October 13 boot reports 480 missed forwards. The socket-only collector has no journal replay. A buffer-only change would require effective kernel/socket evidence, early socket-creation ordering and burst/downtime acceptance; it is not presented as a proven loss-free repair. |
| `managed/system/kernel.log:887` | 143 audit printk callbacks are suppressed. The native auditd stream is acquired separately and was reviewed. This message is not, by itself, an auditd event-loss counter. End-to-end loss accounting still needs isolated load testing. |
| `managed/apps/apps.log:177-180` | Vivaldi UI references an unavailable extension ID and a NoScript image not exposed to other extensions. The missing ID is not in the managed extension policy; NoScript is installed by that policy. NoScript's resource denial is its manifest boundary. Vendor/extension reproduction remains necessary; extending file or AppArmor access would not repair the manifest contract. |
| `managed/apps/apps.log:208` | Tor's graphics probe reports no DRM device. The launcher already supplies a unique render node through `MOZ_DRM_DEVICE` when available; primary display devices are intentionally hidden. Subsequent Tor records reach 100% bootstrap and report completed circuits. Browser rendering/acceleration still needs native isolated verification; neither a crash nor full graphics success is established by this annotation. |
| Labwc global Xwayland diagnostic | The public executable is absent under the existing private-only policy. The requested preservation boundary applies; no public Xwayland or third eligible application was introduced. |
| Crystal Dock deprecation | A packaged LayerShellQt API warning. No bundled application source is present for a narrow API migration. No warning suppression or source build. |
| BlueZ, USB, ACPI/SPI diagnostics | Missing initial Bluetooth identity and UCSI error 88/GET_PDOS -5, firmware resource reservations and the fallback SPI regulator require target/package/hardware evidence. No invented identity, broad permission change, driver blacklist or hardware reset. |
| `System is tainted: unmerged-bin` | A systemd filesystem-layout diagnostic. It is not proof of kernel compromise; no Debian-owned executable directory was rearranged from this message. |
| Initramfs, Zram, Timeshift, nftables | Boot/pressure-monitor initialization, snapshot-not-due records and packet drops are present. No additional failed initialization or rule-load failure was identified. Packet drops are not treated as configuration failures. |
| Empty scanner/model/storage logs | No scan, model execution, firmware check or clean-security result can be inferred from an empty file. |
| Historical `todo/.~` | Separate host/date. Its Tailscale failure is a pending-device-approval result; current code already records and retries that state without reusing the auth key. Old monitor-enumerator fallback and cleanup-trigger diagnostics are not current-boot regressions. No current acceptance is inferred from older remediation reports. |

The upstream source directly supporting the syslog-loss interpretation is
[systemd 262 journald forwarding](https://github.com/systemd/systemd/blob/v262/src/journal/journald-syslog.c#L74-L105).
The separate
[syslog socket contract](https://github.com/systemd/systemd/blob/v262/units/syslog.socket)
already configures an 8 MiB receive buffer. The capture does not supply the
effective overrides, datagram count limit, queue occupancy or consumer timing
needed to select and validate a deterministic capacity change.

The Console error occurs in the upstream
[CrowdSec 1.8.2-rc1 API startup branch](https://github.com/crowdsecurity/crowdsec/blob/v1.8.2-rc1/pkg/apiserver/apiserver.go#L186-L209).
The duplicated patterns can be compared in its maintained
[sshd parser](https://github.com/crowdsecurity/hub/blob/master/parsers/s01-parse/crowdsecurity/sshd-logs.yaml)
and [successful-login parser](https://github.com/crowdsecurity/hub/blob/master/parsers/s01-parse/crowdsecurity/sshd-success-logs.yaml).

## 3. Source sweep and implemented corrections

The structural sweep inventories shell, Perl and Python source under
`d-i/forky/` and `tools/`, including fixtures. Python is parsed as AST data;
repository modules are never imported. The screen for direct Python
`eval`/`exec`, `yaml.load`, literal `shell=True` and simple Perl string-form
process calls produced no production-source candidate. Shell indirect-variable
accesses were inspected as source; their presence is not treated as a defect
without tracing the identifier/value origin. This is a bounded structural
screen and focused review, not a branch-complete security audit.

The focused review follows managed launches through `labwc-app`, profiles,
session service construction, namespace supervisor, network lease client,
output capture, staging lists, runtime verifier, service drop-ins and AppArmor
client permissions. It also checks the relevant runtime/lifecycle acceptance
requirements in `debian-preseed-de-audit.md`. Historical remediation reports
were used only to locate current implementations and remaining gates.

### One deadline for network lease acquisition

`labwc_managed_app/network_client.py` previously set a 15-second socket timeout
once. Connect, request send and reply receive could each consume that interval.
Both initial startup and reattachment use this constructor, so a slow broker
could hold the supervisor longer than the intended lease budget.

The constructor now creates one monotonic 15-second deadline. Each blocking
socket operation receives only the remaining interval; final response/policy
validation must finish before expiry. Socket ownership, peer credentials,
namespace transfer, assigned address/interface, typed peer-port policy and
nonblocking steady state are preserved. Failure closes the channel. Startup
still gates the payload, and a timed-out reattachment retains its namespace
and uses the existing five-second retry without terminating the application.

This is a lease-handshake deadline, not a new deadline on the entire interactive
application or all filesystem operations. No broker protocol or installed
policy changes are needed. The existing package staging list includes the
module, installs mode 0644 and verifies package integrity. The existing
AppArmor client abstraction already permits its imports and Unix seqpacket
access. The offline runtime-verification boundary remains before activation.

### Bounded application-output cleanup

`rsyslog-app-run.tmpl` previously performed an unbounded final `wait()` after
KILL on an error path. Its signal-stop loop could also repeatedly send KILL
and wait for a child that never became reapable.

Cleanup now has one four-second monotonic budget: up to two seconds for TERM
on an error path, then KILL and only the remaining reap interval. An already
completed 15-second application stop grace proceeds directly to KILL; there
is no second TERM grace or repeated polling loop. Confirmed cleanup retains
the existing killed-child signal result. Unconfirmed cleanup or failed signal
delivery raises `CaptureCleanupUnknown`; the public entrypoint reports only
that error class and exits **3**. Ordinary capture failures remain **1**, and
ordinary application exit/signal results remain unchanged.

Each output chunk and selector wait also observes the stop/drain deadline, so
continuous output cannot restart that grace period. The existing 50 ms socket
send timeout bounds an in-flight datagram at the deadline. Output pipes, the
pidfd, stderr flags and signal handlers are still released
or restored on the unknown-cleanup path. The existing systemd service keeps
`KillMode=control-group`, `ExitType=main`, `TimeoutStopSec=20s` and final KILL
ownership. There is no new PID/session scan, privileged runner or numeric-PID
fallback. No throughput or boot-speed measurement is claimed for either fix.

### Prepared failure fixtures

Nine methods were added to the existing guarded suites:

- `test_kernel_veth_networking.py`: shrinking timeouts on success; expiry before
  connect/send/receive and after a late valid reply; socket closure; timed-out
  reattachment retaining the namespace and five-second retry.
- `test_managed_logging_r3.py`: already-reaped child; TERM success; TERM/KILL
  escalation with one total budget; completed 15-second grace; no repeated stop
  loop; streaming delivery at stop expiry; timeout/signal-failure uncertainty;
  pipe/handler/stderr cleanup.

These use mock clocks/channels/processes for failure injection. They have not
been executed. Existing local-IPC/process and native suites also remain gated
by the mandatory disposable environment.

## Verification and remaining acceptance gates

Completed static work consists of source/caller/policy review, AST data parsing,
diff checks and the explicitly permitted pure payload serializer. Exact
fingerprints and product results are recorded below.

Required execution remains:

1. Review/provision the disposable VM/image boundary in `docs/test-isolation.md`.
   Use its own Forky packages, Python 3.14, systemd 262, procfs, managers,
   sockets, policy and devices. Record actual image/package identities.
2. Run the changed `AuthorizationTests`, `LeaseRecoveryTests` and
   `ApplicationCaptureTests` inside the guarded environment. Exercise a real
   stalled Unix seqpacket peer, broker restart, namespace retention and late
   readiness refusal. Confirm actual closure and broker slot recovery.
3. Run native isolated output/stop tests: quiet child, streaming child,
   inherited pipes, ignored TERM, failed/slow reap and repeated cancellation.
   Confirm exit 3 on unknown cleanup, preserved signal result on confirmed
   cleanup and actual cgroup emptiness at the service boundary.
4. Verify rendered installer assets and integrity manifest against these
   current inputs, then native application launch/shutdown and unchanged private
   Zoom/Discord launch/shutdown. Serialization equality is not runtime acceptance.
5. Reproduce syslog boot bursts and collector downtime with known effective
   socket/queue limits. Account for direct journal, forwarded, auditd and
   private-application records separately; verify no feedback duplicates.
6. Obtain the Code deprecation stack/package identity, approved CrowdSec Console
   state and target-specific Vivaldi/Tor/USB-C evidence before claiming those
   remaining diagnostics fixed. No remote account or host changes were made.

All application, boot, loaded-policy, networking, hardware and performance
claims beyond the stated static evidence remain pending.

### Recorded static and serialization results

The final source inventory contains **902 files and 263,357 physical lines**:

| Language | Files | Physical lines | Inspection |
| --- | ---: | ---: | --- |
| Python | 423 | 144,537 | All parsed as AST data with no parse errors; no imports or code execution. |
| Shell | 295 | 79,167 | Structural inventory and focused source review; no shell syntax runner. |
| Perl | 184 | 39,653 | Structural inventory and focused source review; no interpreter or BEGIN execution. |

The source classifier uses extensions (including `.tmpl` forms) and interpreter
shebangs under `d-i/forky/` and `tools/`. Generated products and cache directories
are excluded. These counts include fixtures and do not imply full semantic
review of every line or target-interpreter acceptance.

Fingerprints are SHA-256 of sorted records containing relative path, NUL, file
SHA-256 and LF:

| Input set | SHA-256 |
| --- | --- |
| All 902 classified source files | `cfcb54422e19ba101604d5907ece83ab2ed32b603536cfcfe6e269b6eaeca839` |
| Two modified production files | `68ccf196a2ee187fda6c2ae0e72a80fcbd1d0588240c006cc54b9cad1a40bce7` |
| Two modified fixture files | `a6303ff997e2295e4ef129d464cf8bcfae49d0c9d78acbdf88ea3ec71bda2552` |
| Four modified production/fixture files together | `f2e5ed069bb81a117f0ead638018aac4c3bd61793ed5b0273807a4ad9f491246` |

The evidence inventory's own file SHA-256 is
`b18db5467afc90142e86ce07a27d889bbbab4c93e67f860d25ff808dec01457a`.
Every current `todo/` path, byte count, physical-line count and file SHA-256
matches it. No supplied evidence file was modified.

After reading the complete Makefile build recipe, `tools/build.py` and
`tools/publication.py`, the permitted serializer was invoked with this explicit
argument array and a minimal environment:

```text
/usr/bin/make --file Makefile --no-print-directory --no-builtin-rules --no-builtin-variables build 'PYTHON=/usr/bin/python3 -I -S'
PATH=/usr/bin:/bin HOME=/nonexistent LC_ALL=C.UTF-8
```

It exited **0**, reported `built 1795 payload files`, and emitted no stderr.
The before/after content-and-mode snapshot confirmed that exactly
`payload.tar.gz`, `payload.manifest` and `preseed.cfg` changed; all **2,416 other
checkout files** were unchanged, with no additions or removals during generation.
This is installer serialization, not compilation or a runtime test.

An independent standard-library data reader then compared every manifest entry
and archive member with the current source bytes: **1,795 files, 34,421,446
uncompressed bytes**. Names, file sets, SHA-256 values and canonical archive
metadata agree. No archive was extracted or executed. The generated preseed
contains the current archive, manifest and bootstrap-source pins.

| Generated product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `0a580e2694fe69732ce92370e8c3faae7193cb6cc4a7d1caca296b116f81e0a7` |
| `d-i/forky/payload.manifest` | `05e54bad4d17dfcf58511b73da0e02c3b2bcef1b2e602f2506b80093bff90018` |
| `d-i/forky/preseed.cfg` | `1f85223b4e312cf0c3838613d1e10e389839f0d54249ec4d6a5f7c313e7fbdf2` |

The bootstrap source pin is
`6b3a40bb85942ed8f4b780852743140132414898b578af7c7597bb7c3872b246`.
`git diff --check` completed with no whitespace errors. An explicit comparison
against HEAD found no changes to the private-Xwayland setup/runner, compatibility
modules, application profiles, session construction or native/compatibility
lifecycle drop-ins. The final changed production paths are limited to the two
Python helpers described above.

No disposable image or package identity is available for executed acceptance.
Forky, Python 3.14 and systemd 262 are the intended target contracts, not versions
verified by probing the development host. The captured application versions
inform the log investigation only. All nine new fixture methods, native policy
checks and launch/stop regression gates remain unexecuted. The serializer
products are current; they have not been deployed or accepted on a target.

### Subsequent power-flow work

The later October 17 power-flow changes and replacement generated-product
hashes are recorded in `power-drive-ordering-20261017.md`. The hashes above
identify this incident-review snapshot. Its four production/fixture edits and
all supplied `todo/` evidence were preserved during that follow-up.
