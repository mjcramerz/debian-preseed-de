# Firstboot and AppArmor audit repair — 2026-09-26

This record applies to the complete repository delivered with this directory.
It supplements the historical validation records; their earlier full-suite pass
counts are not results for this revision. The deployment target remains Debian
Forky with systemd 261.2. No target machine was booted or modified during this
repair.

## Evidence and cause

The supplied `Fail`, `failing`, `journalctl`, `managed.zip`, and
`installer-state.zip` describe the same firstboot failure. The firstboot results
contain exactly one failed gate, `apparmor-log-delivery`; the graphics capture is
explicitly skipped because root firstboot has no active Wayland environment.

The native `security/audit/auditd.log` contains 3,262 newline-delimited records,
including 430 AppArmor records: 399 STATUS, 30 DENIED, and one ALLOWED. Its enriched
records contain ASCII group separators; those bytes are part of each record, not
additional log lines. The dedicated AppArmor log was empty.

The rendered rsyslog configuration was replayed against the supplied audit file
with the packaged Debian rsyslog 8.2608.0-4 binary. Its default imfile submission
batch is 1,024 records, exceeding this route's 1,000-record queue. With this
backlog, the original configuration stalls before the worker delivers anything.
This is a batching/queue interaction, not evidence that auditd needs its syslog
plugin enabled.

| Isolated replay | AppArmor records delivered | Denial signals | Exact record bytes |
|---|---:|---:|---|
| Original configuration, observed for 22.047 seconds | 0 of 430 | 0 | No |
| Repaired configuration, complete at 0.252 seconds | 430 of 430 | 30 | Yes |

`audit-replay.json` records the input/configuration hashes and measurements. These
are measurements of one local fixture, not throughput or scheduling guarantees.
The fixture maps file ownership to its own numeric UID/GID, uses private temporary
paths, and opens no system syslog sockets.

## Changes and wiring

All paths in this table are relative to `d-i/forky/`.

| File | Change and resulting behavior |
|---|---|
| `hooks/target/etc/rsyslog.d/30-apparmor.conf.tmpl` | Set imfile `MaxSubmitAtOnce="64"`, below even the configured schema's minimum queue capacity of 100. Keep the two-second polling input, native audit source, existing AppArmor filter, raw record template, bounded rotation, and one writer/worker. |
| `scripts/firstboot/assets/etc/systemd/system/firstboot.service` | Require and order after auditd and rsyslog, in addition to the existing prerequisites. |
| `scripts/firstboot/04-validation.sh.tmpl` | Require an exact real native AppArmor record in the dedicated log or its retained rotations. Observe delayed file creation and native audit rotations during the bounded wait. Empty/missing native evidence cannot pass. No synthetic audit event is used. |
| `scripts/firstboot/service-account-processes.py` | Read only Name and real UID from `/proc/PID/status` for the existing service-account isolation check. Ignore only exited processes; malformed or unreadable identity data fails the check. |
| `scripts/late/core.sh` and `scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl` | Stage the new helper as mode 0644, allow its exact read path, and remove the unused `ps` execute entry. Keep existing confinement; add no ptrace permission. |
| `hooks/target/usr/local/libexec/labwc-waybar-exec` and `hooks/target/etc/skel-desktop/.config/waybar/config.tmpl` | Add the exact argument-free battery command to the existing fixed allowlist and route both battery configurations through the existing descriptor-closing trampoline. |
| `scripts/firstboot/04-validation.sh.tmpl` | Collect system service status separately from packaged user-unit file status. Root firstboot no longer asks the system manager for PipeWire/portal user services. It does not start a user manager or contact a desktop user's bus. |

The 30 DENIED records all identify `comm="ps"`, the `firstboot` profile, and
ptrace reads against other confined desktop processes. Using only process status
identity fields removes that source of unnecessary probes while retaining the
existing forbidden-process check. This does not broaden AppArmor access to those
desktop profiles.

The one ALLOWED record is a complain-mode `file_inherit` event for `/dev/rfkill`
in `labwc-waybar-battery`. Closing inherited descriptors before the helper's
profile transition addresses the cause; no `/dev/rfkill` permission was added.

The destination remains
`/var/log/managed/security/apparmor/apparmor.log`. Native auditd retention remains
authoritative. Audit syslog plugins stay disabled intentionally, so auditd's
"No plugins found" message is not itself an error in this design. AppArmor
STATUS, ALLOWED, and DENIED records all use the same mirror route; DENIED records
also produce the existing content-free desktop signal.

This change preserves existing retention and restart semantics. It does not claim
lossless delivery across arbitrary crashes, rotation while rsyslog is stopped,
or a pre-existing damaged imfile state. Do not blindly delete an installed host's
state files or replay its entire audit history into the live writer. The archive
is a complete installer source snapshot for subsequent installations, not an
in-place repair command for the already installed host.

## Validation actually performed

`results.json` is the machine-readable result summary. Focused logs are included
beside this report. Tests use temporary fixtures and never start target services,
load kernel AppArmor policy, repartition disks, or change host configuration.

| Check | Result |
|---|---|
| Repository build and subsequent `tools/build.py --check` | PASS; generated payload, manifest, and preseed pins rebuilt/current |
| Browser artifact check | PASS |
| Preseed command read-back and syntax | PASS; 59 preseed files |
| Shell parsing/dependency checks with packaged BusyBox available | PASS; 362 files, 735 checks |
| New firstboot/audit regression module | PASS; 14 tests, including native rsyslog backlog/live append/input rotation/restart delivery |
| Existing focused battery/audit integration tests | PASS; 8 tests |
| Installer module/build-preservation tests with scoped packaged BusyBox | PASS; 12 tests, including rebuild after editing every environment file |
| Existing session reliability module | 37 run; 36 pass, one failure because this environment has no `/proc/self/fd` |
| Existing Podman/Incus regression module | 88 run; 85 pass, two ownership-fixture errors (`chown` to UID 65534 returns EINVAL), one skip |
| Offline firstboot and labwc-session AppArmor parsing | PASS with packaged AppArmor 4.1.8-2; no kernel policy loaded |
| Broad code inventory/parser audit | 560 pass; 215 structure-only; 586 inventory-only; 158 dependency-blocked; 11 templates requiring rendering |
| Standard full validation runner | INCOMPLETE; fixed child PATH lacks BusyBox, and installer tests stopped in a transport fixture without a final suite result |
| Separate tooling suite with the standard PATH | NOT PASSING here; 166 tests run, one failure and 76 errors, including class setup errors; unavailable `/var/lib` fixture paths and BusyBox block those checks |

The native regression replays 4,096 mixed audit records (more than the queue's
capacity), then verifies a live denial, auditd-style rename/create input rotation,
and restart/append without duplicate output. The shell regressions also cover
exact-record matching, enriched bytes, empty/missing input, retained archives,
delayed delivery, and symlink refusal. Process fixtures cover real versus
effective UID, an exiting process, and malformed/unreadable status data.

The packaged validation tools were extracted under a private workspace directory,
without running package installation scripts or compiling source. A scoped PATH
was used for the separate build/shell/native checks. The repository's standard
validation runner deliberately resets PATH; its blocked results have not been
rewritten as passes. Missing Perl Moo/MooX dependencies account for the blocked
Perl parser checks. Inventory and structure checks are not runtime acceptance.

The validation environment lacks normal procfs and ownership facilities. The
full installer suite produced partial successes, failures, errors, and skips, but
no completed summary; no total pass count is claimed for it. Existing tests were
not weakened to accommodate these restrictions. Full Debian/Forky execution is
still required before deployment acceptance.

On a suitable disposable Linux validation host with the repository's documented
dependencies, rerun:

```sh
python3 -B tools/build.py --check
python3 -B tools/validate.py --test-timeout 1500
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_firstboot_audit_20260926.py
```

## Other supplied-log findings

| Observation | Assessment/action |
|---|---|
| PipeWire/WirePlumber/portal "Unit not found" in `desktop-units.txt` | System/user-manager diagnostic mismatch; corrected as described above. |
| CrowdSec console not enrolled early in startup | Later firstboot output records enrollment success at 14:10:34 local journal time; bootstrap completion and bouncer verification succeed. No enrollment policy or credentials changed. |
| CrowdSec repeated grok-pattern warnings | Package/hub warnings with successful subsequent startup; no unsupported vendor parser patches introduced. |
| Tailscale stopped/warming-up messages | Both health conditions become OK during startup. `netfilter=off` matches the managed firewall design; the later EOF is a transport interruption, not evidence to change firewall policy. |
| labwc cannot find the global Xwayland executable | Existing behavior preserved under the explicit private-Xwayland constraint. Xwayland remains limited to Zoom and Discord. |
| Obsidian ignored missing per-vault JSON and optional launcher omissions | No evidence of an installer policy failure requiring fabricated user state or additional applications. |
| Installer-chroot AppArmor reload warnings for package profiles | Supplied target boot records show successful later profile loads/mode checks. No profile permissions relaxed to silence installer-chroot warnings. |
| Installer glycin icon probe warning | Target icon-theme validation passes; live image-loader behavior remains an installed-session check. |
| Firmware UCSI/I2C/TDX/Bluetooth warnings | Hardware/firmware observations; no evidence-backed repository change or source patch made. |
| EFI FAT volume was not properly unmounted | Existing disk-state warning remains. Inspect/repair the unmounted EFI filesystem from maintenance media; this repair does not run fsck or change storage policy. |

## Preservation and installed-host acceptance

`file-accounting.json` accounts for every original ZIP file, changed/new files,
and rebuilt product hashes. All original paths remain present with their original
file modes, including the three rebuilt products. Host
environments, credentials, filesystem choices, hardware tuning, package pins,
private Xwayland implementation, and unrelated desktop/process-lifecycle code
are preserved byte-for-byte. No new vendor build, source patch, package-policy
change, or global Xwayland server was introduced. The tarball excludes validation
tool binaries, supplied system logs, temporary fixtures, and build caches.

After a controlled installation, acceptance still requires firstboot to finish
successfully on Forky/systemd 261.2, with its normal completion state and the
exact-record delivery check passing. Verify continuing native AppArmor delivery
and rotation, and absence of the former firstboot `ps`/battery inheritance audit
noise with enforcing target profiles. Confirm desktop startup/session teardown,
private Zoom/Discord Xwayland behavior, and the physical host's EFI/firmware state.
Offline parsing and preserved implementation cannot establish those live results.

Technical references consulted:

- [rsyslog imfile MaxSubmitAtOnce](https://docs.rsyslog.com/doc/reference/parameters/imfile-maxsubmitatonce.html)
- [rsyslog queue parameters](https://docs.rsyslog.com/doc/rainerscript/queue_parameters.html)
- [rsyslog imfile and rotation behavior](https://docs.rsyslog.com/doc/configuration/modules/imfile.html)
- [Linux procfs process status fields](https://www.kernel.org/doc/html/latest/filesystems/proc.html)
