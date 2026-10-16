# DNS, Wi-Fi and bootstrap lifecycle corrections, 2026-10-16

## Scope and evidence

The checkout was clean before this work. All 97 files under `todo/` were read
as data, including empty files, rotated audit records, installer snapshots and
the hidden older journal. Total evidence size: 6,049,568 bytes. Repeated routine
records were reduced to inventories/counts before examining relevant records.
No repository module, test, validator or installed management helper was executed
during this review.

The current capture identifies Debian Forky, systemd 262-1, NetworkManager
1.58.1 and Tailscale 1.104.1. `todo/.~` is a separate October 13 capture from
another host; its pending-approval bootstrap failure does not describe the
October 16 boot. No AppArmor `DENIED` record was found in the supplied current
AppArmor/audit logs. Other observed messages include USB-C UCSI firmware errors,
CrowdSec parser/acquisition warnings and the existing unavailable public
Xwayland executable. Those paths were outside this correction.

## 1. Host DNS startup

`todo/journalctl:570` and the following line report resolved's DO/EDNS0
downgrades; Stubby reports started immediately afterward. The firstboot
`resolvectl-status.txt` snapshot reports the global resolver as
`DNSSEC=allow-downgrade/unsupported` against the same local port.

The source defect is an ordering gap: Debian's Stubby unit waits for
`network-online.target`, whereas resolved starts before `sysinit.target` and
networking. No packet capture was supplied, so the exact failed transaction
cannot be established from these messages alone. The observed ordering permits
queries to a listener that has not bound yet and is consistent with the
degradation. Systemd 262 also uses the same diagnostic for several DNS response
and loss conditions; the message alone is not proof of an upstream DNSSEC defect.

The managed Stubby drop-in now clears the package's network-online dependencies,
starts after local filesystems, sysusers and AppArmor, and orders before resolved
and sysinit. The new resolved service drop-in wants and starts after Stubby.
Debian's packaged `Type=notify`, DynamicUser and restart behavior remain in use.
The upstream Stubby source sends READY after `server_listen()`; this is listener
readiness, not proof of Internet reachability. Resolved is not bound to Stubby's
lifetime, preserving per-link VPN resolution when the global resolver fails.
The late installer stages both service drop-ins. TLS authentication, DNSSEC,
upstream identities/order, firewall policy and empty global fallback are unchanged.

Primary sources read as data:

- [Debian getdns 1.7.3-5 packaging](https://deb.debian.org/debian/pool/main/g/getdns/getdns_1.7.3-5.debian.tar.xz), `debian/stubby.service`.
- [Systemd 262 resolved unit](https://github.com/systemd/systemd/blob/v262/units/systemd-resolved.service.in).
- [Systemd 262 DNS feature downgrade implementation](https://github.com/systemd/systemd/blob/v262/src/resolve/resolved-dns-server.c).
- [Stubby 0.4.3 readiness implementation](https://github.com/getdnsapi/stubby/blob/v0.4.3/src/stubby.c).

## 2. Tailscale RAW-STDERR

`todo/journalctl:1162` records `Starting -> Running`, line 1169 records its DERP
connection, and line 1170 records bootstrap completion. The RAW-STDERR banner
appears at lines 1309-1313, without a subsequent panic or daemon failure in the
capture.

The [Tailscale 1.104.1 logtail source](https://github.com/tailscale/tailscale/blob/v1.104.1/logtail/logtail.go)
prints this banner while draining a non-JSON record from its stderr buffer.
That branch prints the output buffer `b`, rather than the offending `line`;
the output buffer initially contains `[`. The supplied lone bracket therefore
does not reveal the original raw record or establish a crash. The banner's
suggestion that a record is from an earlier run is not a determination of its
age. Existing disabled vendor uploads and local diagnostics remain unchanged.
No vendor source modification, compilation or log suppression was introduced.

## 3. Wi-Fi cleanup

`todo/journalctl:1190-1208` correlates NetworkManager radio-off, rfkill events,
supplicant interface teardown, the two EBUSY messages and the helper's successful
completion. The duplicate scan request is at line 1176. These are firstboot
preparation/teardown records, not evidence of an attempted association failing.

Supplicant now places its control sockets in `/run/wpa_supplicant/control`.
The systemd-owned outer runtime directory remains in place; supplicant can
remove its child directory when the last interface is released. Both the daemon
`-O` argument and managed station configuration agree. Repository consumers use
NetworkManager/D-Bus; an administrator using `wpa_cli` directly must select this
control directory.

Firstboot uses `--rescan auto` to let NetworkManager reuse a fresh scan. Cleanup
temporarily releases the selected adapter with `managed no`, waits up to five
seconds for its station/P2P control sockets to disappear, turns the radio off,
then restores `managed yes`. Each cleanup command has a seven-second process
timeout. Restoration is attempted even after a timeout, because the preceding
request may already have reached NetworkManager. Failure prevents publication
of the firstboot completion marker. A firstboot-only SIGTERM handler unwinds
through cleanup instead of Python's default immediate termination; repeat TERM
is ignored during restoration. Cleanup ignores TERM on its normal-success path
too, so an initial stop signal cannot interrupt radio-off. `KillMode=mixed`
delivers the initial TERM to the wrapper; its children remain under the
wrapper's bounded termination and command timeouts, with systemd group KILL
still enforced. Stop timeout is thirty-five seconds to cover capture
termination and bounded cleanup. Existing manual activation, address
policy, profile ownership and autoconnect=false remain intact. The helper's AppArmor profile gains only
metadata/read access to the control directory and sockets.

The [NetworkManager 1.58.1 source](https://github.com/NetworkManager/NetworkManager/blob/1.58.1/src/core/devices/wifi/nm-device-wifi.c)
was inspected for unmanaged-state interface release. Debian's wpa 2.11-2
packaging was read for its runtime-directory ownership. These source comparisons
do not establish runtime driver or AppArmor acceptance on the target.

## 4. Bootstrap and cleanup ordering

`todo/journalctl:1274` says exit-status propagation was skipped because several
OnSuccess sources shared a cleanup handler. It does not say cleanup was skipped;
lines 1275-1303 show cleanup starting and finishing successfully.

Each bootstrap unit now invokes the existing cleanup helper with `--queue`
through ExecStopPost, after its process exits. The helper atomically replaces a
private request file. `secondboot.path` watches that file and is staged/enabled
alongside the existing next-boot cleanup service. Failed attempts also request
a pass; component completion markers continue to authorize every removal.

Cleanup consumes the request before work and checks all six MainPID/ControlPID
values and all three service substates. It defers while a main process, stop
command or exit transition is still running and rejects failed, empty or
incomplete manager responses. Idle restart backoff is allowed; missing component
markers continue to protect pending retry artifacts.
An active process/transition returns 75, with `RestartForceExitStatus=75` and a
five-second service retry. This closes the request-consumption race when a
Type=exec bootstrap exits naturally after its start job has already finished:
`After=` alone only orders outstanding jobs. `Restart=no` leaves other failures
visible without automatic retries; `RestartMode=direct` avoids unnecessary
inactive/failure propagation during this temporary busy state. Status 75 is not
classified as success, since oneshot success suppresses forced restarts.
This prevents retirement of shared files while ExecStopPost is still using
them. A later request remains present for another activation. Systemd's
[262 path-unit contract](https://github.com/systemd/systemd/blob/v262/man/systemd.path.xml)
explicitly rechecks watched paths after the activated service terminates.

Completed bootstrap services are disabled without stopping processes. The path
watcher alone is stopped at final retirement. Its file, enablement links, helper,
bootstrap units and transient policy are then removed through the existing
cleanup flow. Pending enrollment state, credentials and retry services remain
until their respective markers authorize removal. TPM reenrollment and release
evidence retain their existing lifecycle.

## 5. Focused reliability and performance

All unit disables use `--no-reload`. One exit handler performs the manager reload
after unit changes, including partial/error exits. This replaces the capture's
repeated reloads during a single cleanup run. No measured boot-time or throughput
improvement is claimed. Changes are limited to these resolver, Wi-Fi and
bootstrap contracts; no package selection, source build or Xwayland policy was
changed.

## Security follow-up

The follow-up review traced the changed privilege, input and lifecycle
boundaries. It found and corrected the busy-cleanup retry gap and the initial
TERM interruption of an already-running Wi-Fi cleanup described above. No new
capability, unconfined execution rule, writable system path or network exposure
was added by these follow-up corrections.

The reviewed source retains these controls:

- Stubby uses required TLS authentication, the configured CA and upstream names,
  TLS-only transport, DNSSEC validation and an empty capability set. Its
  DynamicUser, AppArmor profile, filesystem protections and resource bounds
  remain configured. Resolved's global `DNSSEC=allow-downgrade` remains the
  existing policy; this work does not establish strict DNSSEC enforcement by
  resolved on every per-link/VPN resolver.
- The Wi-Fi helper uses fixed argument arrays, a minimal child environment,
  private root-owned configuration, no-follow reads, bounded untrusted scan
  output and deadlines. The new interface check rejects traversal components
  before constructing control-socket paths. Automatic connection remains off.
- Cleanup requests are empty mode-0600 files published atomically inside the
  installer's root-only state directory. Completion markers authorize cleanup;
  process/substate checks gate it. Missing or malformed manager responses
  prevent artifact retirement. Cleanup retains pending credentials and retry
  artifacts until their component completes, then unlinks transient secrets
  without following links or claiming reliable SSD erasure.
- Existing `NoNewPrivileges=false` exceptions for explicit AppArmor transitions
  remain. The temporary cleanup service still needs root and initramfs/unit
  write access for its defined task. Those are meaningful privilege boundaries,
  not a claim that every service has an equally restrictive sandbox.

The changes to service restart and signal handling were checked against
[systemd 262 job ordering](https://github.com/systemd/systemd/blob/v262/src/core/job.c),
[service restart semantics](https://github.com/systemd/systemd/blob/v262/man/systemd.service.xml)
and [KillMode semantics](https://github.com/systemd/systemd/blob/v262/man/systemd.kill.xml).
This is a scoped source review, not a security certification of the complete
repository or proof of installed runtime enforcement.

## Verification boundary

`AGENTS.override.md` and `docs/test-isolation.md` require a prepared disposable VM
for all tests and native validators. No prepared disposable VM was supplied or
established in this session. No unittest, shell
syntax runner, AppArmor parser, systemd validator, service operation, network
probe or live installed helper was run. No test pass or target deployment is
claimed. Attempts to delegate read-only review failed during agent context
initialization, before file access; no independent review result is credited.

Guarded fixtures were added/updated for Wi-Fi command ordering, failures and
release deadlines; atomic private cleanup requests and preservation of pending
work; active/malformed bootstrap PID responses; and busy cleanup retry versus
error/success exits before removal. Signal handler calls are mocked in the
Wi-Fi fixture so it cannot alter the runner's handlers. These fixtures have not been
executed. Python AST parsing and source/diff inspection execute none of them.

Fresh Forky/systemd 262 acceptance remains required for the complete native
ordering graph, DNS queries/DNSSEC, adapter scanning/release/radio restoration,
AppArmor transitions, and concurrent path-triggered cleanup. The following
generation record establishes only source/artifact consistency.

### Generation record

The reviewed pure serialization command completed successfully:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
```

It produced 1,790 payload members containing 34,352,534 source bytes after the
security follow-up. Data-only inspection compared every archive member with its canonical source and manifest
digest. All names, ordering and normalized member metadata agree; the preseed
archive/manifest/bootstrap-source checksum pins agree. All 2,437 nonproduct
files retained their bytes, modes, sizes and modification times across
generation. Only the three permitted products changed during that command.
This report's generation record was filled in afterward.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `72d22eb2b86ff6bedc0af49fc7bc029d598186c5328f715508b61d5dd3b92a58` |
| `d-i/forky/payload.manifest` | `28b64947678e8e2c32addd7daef24f53967e81bc88b50bd72db9513de1729a9c` |
| `d-i/forky/preseed.cfg` | `3214a54c7cc0de3b45377abaf6a6c49a0fc57417148938e55b0867b6897a8543` |

All three changed Python inputs parsed using standard-library `ast.parse`,
without importing repository code. Source-as-data checks reconciled resolver
readiness/staging, the common Wi-Fi control directory, cleanup request/retirement
wiring and the single reload call. `git diff --check` reported no errors. Six
Xwayland/compatibility paths match HEAD byte-for-byte; removing the three new
Wi-Fi read grants from the shared desktop AppArmor template yields HEAD exactly.
Source inputs retain repository mode 0644; installer staging retains the existing
executable target modes.

### Changed paths

Paths below are relative to the repository root; every path belongs to these
corrections or their guarded fixtures, documentation and generated output.

```text
d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
d-i/forky/hooks/target/etc/systemd/system/stubby.service.d/60-app-veth.conf
d-i/forky/hooks/target/etc/systemd/system/systemd-resolved.service.d/60-stubby.conf
d-i/forky/hooks/target/etc/systemd/system/wifi-firstboot.service
d-i/forky/hooks/target/etc/systemd/system/wpa_supplicant.service.d/override.conf
d-i/forky/hooks/target/etc/wpa_supplicant/wpa_supplicant.conf
d-i/forky/hooks/target/usr/local/libexec/network-wifi-configure
d-i/forky/scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl
d-i/forky/scripts/firstboot/assets/etc/systemd/system/crowdsec-firstboot.service.tmpl
d-i/forky/scripts/firstboot/assets/etc/systemd/system/firstboot.service
d-i/forky/scripts/firstboot/assets/etc/systemd/system/secondboot.path
d-i/forky/scripts/firstboot/assets/etc/systemd/system/secondboot.service
d-i/forky/scripts/firstboot/assets/etc/systemd/system/tailscale-bootstrap.service.tmpl
d-i/forky/scripts/firstboot/assets/var/lib/firstboot/bin/secondboot-cleanup
d-i/forky/scripts/late/core.sh
d-i/forky/scripts/late/security.sh
d-i/forky/tests/test_boot_runtime_20260913.py
d-i/forky/tests/test_crowdsec_firstboot_retry.py
docs/app-veth.md
docs/validation/startup-network-bootstrap-20261016.md
d-i/forky/payload.tar.gz
d-i/forky/payload.manifest
d-i/forky/preseed.cfg
```
