# Managed service incident review — 18 October 2026

## Status and evidence boundary

The source corrections below are incorporated in the generated installer
products. **Native acceptance is pending.** No disposable Forky test environment
was supplied. `AGENTS.override.md` and `docs/test-isolation.md` prohibit running
tests, discovery, Perl compilation/imports, native policy parsers, systemd
validators, or installed management helpers on the development host.

The later [GRUB/Timeshift/MOK integration snapshot](grub-timeshift-mok-20261018.md)
preserves these corrections and regenerates the three installer products.
Hashes below identify this earlier recorded snapshot; use the later report for
the current artifact hashes. Its additional source work does not accept any
of this report's pending native service gates.

### Follow-up: installer `stat: not found` abort

The reported abort is in `stage_target_logging_foundation`, before target
activation. Its metadata check previously required `stat` in the **installer**
environment. A target installation of coreutils does not supply that command
to the installer's command search path. The current implementation at
`scripts/late/target-assets.sh:424` calls the existing
`installer_metadata_value ... uid_gid_mode_links` reader instead. That reader
is loaded by `scripts/common/lib.sh` before either storage-family entrypoint
reaches the foundation; it uses numeric `ls -ldn` and `awk`. Regular-file,
non-symlink, root UID/GID, exact mode and single-link requirements remain.

The follow-up source review also found a stale fixture in
`tests/test_logging_size_20260924.py`: it expected only the original five
logging destinations and did not provide files for the five forwarding-asset
checks. It now covers all ten destinations with the real metadata reader,
a private target path containing spaces and an explicit utility-only `PATH`
with **no `stat`**. The fixture specifies 21 cases: successful staging, a failure
at each of ten publication steps, and ten unsafe/error cases covering ordinary
and special permission bits, UID, GID, hardlinks, symlinks, absence, failed `ls`,
failed `awk`, and placeholder-check status propagation. No target helper,
service manager or package command is available in this fixture's `PATH`.
Its disposable-image guard is retained; **these cases have not been executed**.

Follow-up checks actually performed:

- Static `ast.parse()` of the changed fixture, without imports or execution.
- Source review of both storage-family callers and the common-library load
  order; a bounded search found no executable `stat -c`, `busybox stat`, or
  `command -v stat` use in common/late/partman/early scripts or installer hooks.
- `git diff --check`: clean.
- Reviewed pure `make --no-print-directory build PYTHON=/usr/bin/python3`:
  completed with 1,817 payload files. The fixture is excluded from the payload,
  so this follow-up leaves the later GRUB/Timeshift/MOK artifact bytes unchanged.
- Standard-library archive inspection as data, without extraction: all 1,817
  members (34,692,860 uncompressed bytes) match current source and manifest;
  membership and canonical metadata match; preseed archive, manifest and
  bootstrap-source pins match. The packaged journal foundation contains the
  canonical metadata-reader call and no `stat` command.

Generated products for this missing-stat follow-up, SHA-256. The later
Timeshift publication-status correction supersedes these artifact hashes;
use `grub-timeshift-mok-20261018.md` for the current products:

```text
5f21cd0be9a4f799b203b0b7ffd8cad52f65f754cf7ba79463265f7037199c68  d-i/forky/payload.tar.gz
0a46e837654b2cb8dd57c3780bdfa468750eef5d035ee3e15e36fcd685f810f7  d-i/forky/payload.manifest
70d6cbf945fb420b07252ae4dd03ea5752ae0ca6d93f24f46ccebbf785c04203  d-i/forky/preseed.cfg
```

Relevant source/fixture identities, SHA-256:

```text
d5d5e7b4ae25d4ab621fb4ccc6c8de723d041244ff4916296572fe2ec896aa28  d-i/forky/scripts/late/target-assets.sh
73d4f3e45dd024d2456e6bc34dba5cab4542209e0f369cdb346f8403fc17e993  d-i/forky/scripts/common/lifecycle.sh
b78a1a2ae01ff41569750eee0a914e04744960ba88d0813684adec470372fe34  d-i/forky/tests/test_logging_size_20260924.py
```

The source/fixture aggregate fingerprint and generated hashes in the historical
sections below identify their earlier snapshot. The changed fixture above
supersedes its earlier identity. No prepared disposable environment is available;
the restricted-path fixture, actual busybox-udeb staging for both storage
families, native policy/service checks and a fresh target installation remain
unaccepted. No live server publication was performed or inspected, so the
bytes currently served to an installer are unknown. Publish the three products
from the same snapshot through the existing deployment process.

The working tree was clean at the start. Base revision:
`20861dbc0b86d6bd4485306cafa4052ff24c669e`.

All 94 regular files in `todo/`, including the hidden historical `todo/.~`,
were read as data: 10,682,142 bytes; 22 empty files. The supplied current target
reports systemd `262-1` in
`todo/installer-state/logs/firstboot/data/systemd-version.txt`. This is supplied
target evidence, not a development-host package probe. No new test image or
exact native acceptance package inventory is available.

The named `debian-preseed-de-audit.md` is absent. Relevant current acceptance
boundaries were reviewed in `docs/comprehensive-audit-implementation-20261017.md`,
`docs/audit-remediation-20261017.md`, and
`docs/validation/audit-remediation-20261016.md`; their historical results do not
accept this working tree.

## Findings and repairs

| Finding | Supplied evidence | Source correction |
|---|---|---|
| Filen refuses private inputs | `todo/journalctl:651` and `:658`: both accounts return `invalid-configuration cause=private-input`. Firstboot's validation results list both failed units. | `FilenSync/Config.pm` accepts systemd's root-owned credential ACL mask layout (`0440`) only for the three fixed service credential filenames, retaining regular-file, ownership, single-link, byte-limit and other-access checks. The credential directory must also be private and trusted. Ordinary private inputs retain the stricter permission check. `Daemon.pm` reports fixed `settings` or `credentials` categories without exception text or secret values. |
| Tailscale ancestor mount namespace bind fails | `todo/journalctl:787`: binding `host.mnt` fails with `move_mount()` / `ELOOP`. | The constructor records the validated PID 1 mount namespace device/inode in a private regular `host.mnt` file. It does not bind an ancestor mount namespace into its descendant. The SSH delegate independently opens and pins `/proc/1/ns/mnt`, checks its namespace type and recorded identity, then pins the host root before either namespace change. Network namespace pinning and native PAM/account selection remain in place. Descriptors are closed on success and failure paths. |
| Tailscale cleanup rejects its own routing rules | `todo/journalctl:806`, `:980` and subsequent retries: `unexpected managed route rule; evidence retained`; starts then refuse the retained recovery state. | Cleanup uses iproute2's rule JSON schema: `action=unreachable` and string numeric table IDs. It still validates priorities, exact host source selectors, destination, protocol, flags and the field allowlist before network removal. Foreign actions, broader source prefixes and extra selectors are rejected. Existing recovery evidence is retained when cleanup is uncertain. |
| Repeated enforced AppArmor denial | `todo/managed/security/apparmor/apparmor.log:435` and `:442`–`:451`: 11 events, all `tailscale-netkit`, `operation=capable`, `comm=ip`, `capname=sys_module`. No other DENIED pattern was present in the supplied files. | Add `capability sys_module` to the existing root constructor profile only. The daemon and SSH delegate profiles do not receive that grant. Existing mode reconciliation stages the complete profile file. No policy was loaded on the development host. |
| Expected secondboot deferral appears as failure | `todo/journalctl:1037`–`:1104`: the helper defers while bootstrap processes/stop commands are busy, returns 75, and systemd reports repeated cleanup failures. | `secondboot.service` uses `Type=exec`, `SuccessExitStatus=75`, and the existing forced retry for 75. Other errors remain failures. `RuntimeMaxSec=5min` retains the operation limit after changing service type; cgroup termination and stop timeout remain in place. |
| Firstboot validation failure | `todo/installer-state/logs/firstboot/data/validation-results.txt:20`–`:22`, `:483` and `20-firstboot.log`: failed Filen units make validation fail. | Repair the input contract. The validation failure gate remains active; failed units are not ignored or reset to manufacture a pass. A fresh target run is required. |
| Installer staging aborts on missing `stat` | The installation reported `line 419: stat: not found` while checking `journal-check`. Debian Installer's BusyBox environment intentionally has no `stat` applet. | Replace the new late-command `stat -c` call with the already-loaded `installer_metadata_value` reader, which uses the supported numeric `ls -ldn` and `awk` path. The check still rejects non-regular files, symlinks, wrong root ownership, wrong mode, or multiple links. A full late-script search now finds no executable `stat` use. |
| Installer effective forwarding policy conflicts | The subsequent installation reported `effective ForwardToSyslog='yes' conflicts with managed ForwardToSyslog=no`. Debian's systemd 262-1 packaging supplies `/usr/lib/systemd/journald.conf.d/syslog.conf` with `ForwardToSyslog=yes`; its filename sorts after both numbered managed drop-ins. | Stage a root-owned mode-0644 regular `/etc/systemd/journald.conf.d/syslog.conf` containing an empty `[Journal]` section. Same-basename local precedence replaces that vendor fragment without adding another assignment. The existing persistent off value and ready/on runtime override then remain authoritative. The effective-policy checker stays strict. |
| Early syslog forwarding loses messages | `todo/journalctl:1030` reports 387 missed forwarded messages; historical `todo/.~:1368` reports 480. The current boot starts rsyslog at 02:47:15, acquires its socket at 02:47:19, and finishes startup at 02:47:19. | Start with `ForwardToSyslog=no`. The new `rsyslog-journal-forwarding.service` enables the transient forwarding override only after the daemon's `READY=1` and all startup hooks, and disables it before an orderly collector stop. Early records remain in the selected journal store without socket replay. Native boot acceptance remains pending. |

The Filen messages deliberately omit the exact failed check. The credential
ACL mismatch is a definite source incompatibility and matches the observed
startup stage; the supplied logs alone cannot prove it was the only failing
input check on that installed machine. The revised fixed diagnostic categories
make a subsequent failure distinguishable without exposing secrets.

### Forwarding readiness and failure contract

Systemd v262 forwards to the syslog socket with nonblocking `sendmsg()`. A full
queue (`EAGAIN`) increments the missed-message counter; there is no retry or
journal replay. The warning is rate limited to once per 30 seconds, so its
02:47:34 timestamp does not identify when the 387 messages were dropped. The
boot's receiver startup interval is a concrete exposure to this failure, not
proof that every missing message came from that interval. The socket already
requests an 8 MiB receive buffer; arbitrary byte-buffer tuning does not establish
a delivery fix.

The correction gates forwarding on readiness, without an arbitrary delay:

1. The rendered persistent policy starts with forwarding off. Journal storage,
   levels, retention, rate limits and the independent audit input are unchanged.
2. Rsyslog explicitly uses its packaged systemd notify contract. Its `Wants=`
   starts the forwarding owner, whose `After=` waits for complete collector
   startup and journal sealing's policy reader.
3. The root helper atomically publishes only
   `/run/systemd/journald.conf.d/90-rsyslog-forwarding.conf`, checks the effective
   policy, and requests an acknowledged reload of the already running journal
   service. Systemd 262 uses `Type=notify-reload`; journald is not restarted.
4. `After=`, `PartOf=` and `BindsTo=` associate the owner with the collector's
   lifecycle. Its stop hook removes the validated owned override and reloads
   journald before an orderly receiver stop. For this specific reload only,
   `--job-mode=ignore-dependencies` avoids waiting behind the owner's own stop
   job. It does not start/restart services or request another dependency job.
5. Runtime policy files must have the exact expected bytes, root ownership,
   mode 0644 and one link. Ancestors must be real root-owned directories without
   group/other write access. Foreign paths are retained and rejected. Command
   waits are bounded; a failed disable or timed-out enable reports an unknown
   outcome instead of asserting successful recovery. A timed-out enable is not
   retried by the helper and retains its override for the separate stop path.
6. Firstboot waits for the owner and requires both its active state and
   `journal-check --require-forwarding`. A running collector with forwarding
   absent cannot satisfy the validation gate.

Early boot and collector downtime are intentionally journal-only; those records
are not copied later into managed text files. This retains the existing live
`imuxsock` UID/PID/executable trust model. It does not recover the historical 387
missing socket copies, prove the identity of those messages, or guarantee that
an overloaded/crashed receiver can never lose a later socket message. A native
boot with a deliberately delayed receiver and late-message delivery accounting
is required to accept the specific startup correction.

### Debian vendor precedence correction

The original readiness change omitted Debian's unnumbered vendor fragment.
Changing only `10-storage.conf` was insufficient: native drop-in ordering is
lexicographic across all directories, and `syslog.conf` sorts after `90-*`.
Renaming a managed file to another numbered priority would not solve this
particular conflict.

The local replacement has the **same basename** as the vendor fragment and
contains no setting assignments. Therefore `/etc` shadows `/usr/lib` for that
one filename, while leaving the existing numbered assignments intact:

| Phase | Active managed assignment | Effective intended value |
|---|---|---|
| Installer / boot / stopped collector | `10-storage.conf` | `ForwardToSyslog=no` |
| Ready collector | Runtime `90-rsyslog-forwarding.conf` after `10-storage.conf` | `ForwardToSyslog=yes` |
| After orderly deactivation | Runtime override removed; `10-storage.conf` applies | `ForwardToSyslog=no` |

Both storage families stage and validate the replacement in the shared logging
foundation before the desktop's installed policy check. Desktop verification
also requires the installed path. Publication uses the existing atomic asset
helper and BusyBox-compatible metadata reader. The vendor file under `/usr/lib`
is not modified, and unrelated conflicting drop-ins remain validation failures.

Primary package evidence was inspected as data from Debian's
[systemd 262-1 packaging archive](https://deb.debian.org/debian/pool/main/s/systemd/systemd_262-1.debian.tar.xz):
`debian/extra/journald.conf.d/syslog.conf` contains the forwarding-on assignment.
The downloaded archive was 189,824 bytes with SHA-256
`f3c33171e982901844e394d508c03a82d000c17df50dd484c59f5fa6687211e7`.
This was HTTPS source inspection without extraction or execution; no package
signature or installed target behavior was verified by that read. The
[Debian package file list](https://packages.debian.org/sid/amd64/systemd/filelist)
also lists the vendor fragment, and
[systemd v262 precedence documentation](https://github.com/systemd/systemd/blob/v262/man/standard-conf.xml)
defines same-basename replacement and lexical ordering.

A follow-up read of systemd v262's
[configuration resolver](https://github.com/systemd/systemd/blob/v262/src/basic/conf-files.c)
and [configuration display path](https://github.com/systemd/systemd/blob/v262/src/shared/pretty-print.c)
confirms the fixture's lookup assumptions: the explicit root is used for file
resolution, an earlier directory's basename overrides the later vendor entry,
and the selected files are sorted by basename. Drop-ins are still displayed
when the private root has no main `journald.conf`. This is upstream source
inspection, not execution of the native fixture or acceptance of a boot.

### Primary implementation references

- [systemd v262 credential publication](https://github.com/systemd/systemd/blob/v262/src/core/exec-credential.c):
  `write_credential()` prefers a root-owned file with a named-user read ACL and
  falls back to ownership when necessary.
- [Linux mount namespace cycle checks](https://github.com/torvalds/linux/blob/v6.17/fs/namespace.c):
  `mnt_ns_loop()` rejects references to older/same mount namespaces;
  `do_move_mount()` reports `ELOOP` for an unsafe namespace subtree. This is the
  source-level explanation matching the supplied kernel error, not an executed
  reproduction on the target's XanMod kernel.
- [iproute2 rule JSON output](https://github.com/iproute2/iproute2/blob/main/ip/iprule.c):
  rule actions use the `action` key and table identifiers are printed as strings.
- [systemd v262 service restart semantics](https://github.com/systemd/systemd/blob/v262/man/systemd.service.xml):
  successful oneshot termination does not provide the needed successful-status
  retry; `Type=exec` permits that retry with a distinct successful exit status.
- [systemd v262 syslog forwarding](https://github.com/systemd/systemd/blob/v262/src/journal/journald-syslog.c)
  and [syslog socket](https://github.com/systemd/systemd/blob/v262/units/syslog.socket):
  nonblocking queue-full handling, delayed aggregate warning and existing buffer.
- [systemd v262 journald reload](https://github.com/systemd/systemd/blob/v262/src/journal/journald-config.c)
  and [journal service](https://github.com/systemd/systemd/blob/v262/units/systemd-journald.service.in):
  SIGHUP configuration reload with reloading/ready notification.
- [rsyslog v8.2608.0 readiness](https://github.com/rsyslog/rsyslog/blob/v8.2608.0/tools/rsyslogd.c):
  the packaged notify protocol signals `READY=1` after initialization.
- [systemd v262 job ordering](https://github.com/systemd/systemd/blob/v262/src/core/job.c)
  and [systemctl job modes](https://github.com/systemd/systemd/blob/v262/man/systemctl.xml):
  an ordinary reload ordered before an in-progress stop would wait for that
  stop; the scoped ignore-dependencies reload avoids this self-wait.

## Other log findings and remaining limitations

| Observation | Assessment / remaining boundary |
|---|---|
| Historical Tailscale `NeedsMachineAuth` | `todo/.~:1520` and `:1560` describe device approval pending in the remote admin console. Current `tailscale-up` already returns pending status 75, removes the consumed key, retains node identity, and the unit treats 75 as successful but retryable. Local code cannot grant remote device approval. |
| CrowdSec console synchronization errors during enrollment | `crowdsec.log:273` and `:292` occur during firstboot enrollment. `todo/journalctl:1031`–`:1033` subsequently records successful bootstrap with console enrollment pending approval. This does not prove remote approval. No token or remote enrollment was altered in this task. |
| CrowdSec duplicate grok warnings | The warnings name `IPv4_WORKAROUND` and `IP_WORKAROUND` in the upstream `crowdsecurity/sshd-success-logs` parser. The [upstream parser](https://github.com/crowdsecurity/hub/blob/master/parsers/s01-parse/crowdsecurity/sshd-success-logs.yaml) defines those names. No parser failure is shown. Required collections, including the good-actor whitelist, remain installed. |
| qBittorrent log absent at boot | The external volume/log is absent when acquisition starts. Current `24-qbittorrent.yaml.tmpl` already polls the exact native filename every 30 seconds and uses inotify after discovery. The warning alone does not establish a broken acquisition path. Native discovery after the volume appears remains an acceptance gate. |
| Kernel audit printk suppression | `kernel.log:886` reports 143 suppressed kernel-print copies. The authoritative audit files and direct AppArmor acquisition are separate; suppression does not by itself prove those files lost the same records. End-to-end native loss accounting remains required. |
| USB-C/UCSI, I2C-HID, firmware/ACPI, Bluetooth feature messages | Supplied kernel/USB logs show hardware/firmware problems or feature fallbacks, including UCSI `-5`, HID reports and an unsupported coded PHY feature. There is no deterministic configuration repair established by the snapshot. No devices, drivers, kernel arguments or firmware were changed. |
| BlueZ identity file absent | A first-boot missing local identity file is logged; no corresponding failed Bluetooth service is shown. Do not manufacture identity keys or modify account/device state from this evidence. |
| Podman overlay compatibility messages | The messages come from named overlay capability probes. They do not establish container engine failure or authorize resetting its store. |
| Installer Mullvad profile reload message | The vendor postinst reports inability to reload during installation. Supplied firstboot AppArmor data later shows the Mullvad profiles loaded in enforce mode. An offline installer must not load policy into a running host as a workaround. |
| Main Labwc Xwayland messages | Excluded by the user's explicit instruction. No Xwayland source/configuration or eligibility boundary was changed. Private Zoom/Discord launch and shutdown remain native regression gates. |
| Crystal Dock deprecation | Qt reports a deprecated API; the dock starts. No source compilation, package replacement or desktop redesign was introduced. |
| Historical Waypaper monitor fallback | Only the older hidden log reports fallback to All. The snapshot provides no current failing operation or deterministic local repair. |
| One failed audited exec | The supplied syscall records contain one `execve` ENOENT under Mako's Glycin loader path; no audited EACCES/EPERM syscall pattern was found. A failed optional loader probe does not establish a Mako service failure. |
| Sudo authentication conversation failure | The supplied journal records a failed conversation and later successful sudo sessions. No credential or PAM change is justified by those records alone. |
| Empty scanner/model logs | Twenty-two files are empty. They supply neither a scanner failure nor successful scan evidence. Scanner scheduling/native execution has not been accepted here. |

## Source-to-target integration

- `scripts/desktop/filen.sh` stages both changed Perl modules. The existing
  `filen-install.py` publishes them root-owned, mode 0644, under the fixed module
  root; the wrapper and per-account service continue to use Perl taint mode.
  Native credentials are supplied by each unit's existing `LoadCredential=`
  directives; there is no ambient-secret fallback.
- `scripts/late/tailscale.sh` stages both changed delegates at mode 0755 and
  retains the offline target verification gate before enablement.
  `scripts/late/security.sh` stages `usr.sbin.tailscaled`; the existing central
  mode policy covers all named profiles in that file.
- `scripts/late/core.sh` stages the changed secondboot unit at mode 0644.
  The existing path request and helper busy check still own cleanup admission.
- Both storage-family hooks call `stage_target_logging_foundation` before class
  dispatch. It now stages the forwarding helper/checker at 0755 and the owner
  unit/rsyslog request drop-in at 0644, and rejects missing/unsafe metadata or
  unresolved installer tokens before activation. The empty local `syslog.conf`
  vendor replacement is staged and checked at mode 0644 through the same path.
  The existing desktop staged
  path check and firstboot logging checks include the new assets. No offline
  staging path invokes the mutating forwarding helper or a running manager.
- The desktop package baseline already selects Python 3 and rsyslog. The new
  helper uses Python's standard library; no new package or source build is
  introduced. Supplied daemon startup logs report rsyslog 8.2608.0.
- No new packages, compilation, Xwayland changes, global AppArmor mode changes,
  host service operations, policy reloads, firewall changes or live deployment
  occurred.

## Exact changed paths

Production inputs:

```text
d-i/forky/hooks/target/etc/apparmor.d/usr.sbin.tailscaled
d-i/forky/hooks/target/etc/rsyslog.conf.tmpl
d-i/forky/hooks/target/etc/systemd/journald.conf.d/10-storage.conf.tmpl
d-i/forky/hooks/target/etc/systemd/journald.conf.d/syslog.conf
d-i/forky/hooks/target/etc/systemd/system/rsyslog-journal-forwarding.service
d-i/forky/hooks/target/etc/systemd/system/rsyslog.service.d/40-journal-forwarding.conf
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/filen/FilenSync/Config.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/filen/FilenSync/Daemon.pm
d-i/forky/hooks/target/usr/local/libexec/journal-check
d-i/forky/hooks/target/usr/local/libexec/journal-forwarding
d-i/forky/hooks/target/usr/local/libexec/tailscale-netkit
d-i/forky/hooks/target/usr/local/libexec/tailscale-ssh-host
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/scripts/firstboot/04-validation.sh.tmpl
d-i/forky/scripts/firstboot/assets/etc/systemd/system/firstboot.service
d-i/forky/scripts/firstboot/assets/etc/systemd/system/secondboot.service
d-i/forky/scripts/late/storage-maintenance.sh
d-i/forky/scripts/late/target-assets.sh
```

Authored/updated fixtures, **not executed**:

```text
d-i/forky/tests/test_filen_sync_20261017.py
d-i/forky/tests/test_tailscale_netkit_20261017.py
d-i/forky/tests/test_crowdsec_firstboot_retry.py
d-i/forky/tests/test_logging_size_20260924.py
d-i/forky/tests/test_managed_logging_r3.py
d-i/forky/tests/test_systemd_resource_policy.py
```

The sorted `SHA256(file) + two spaces + path + LF` records for exactly those
24 files have SHA-256:
`345f7d2b1479645d8a7d60d8b175f22dd7d578932e2718a9c8de76c30c461855`.
This identifies the changed source/fixture set, excluding generated products and
this report.

The three generated products below and this report are the other changed paths.

## Checks actually performed

1. Read-only supplied-log inventory and normalized AppArmor/syscall grouping
   using Python standard-library data processing; no repository imports.
2. Source, caller, installation rendering/staging, policy and diff review.
3. `/usr/bin/python3 -I -B` with `ast.parse()` on the four changed Python
   delegates and the six changed Python fixture modules, as source data only.
   All ten parsed. No Perl module, embedded Perl fixture, shell or policy was
   executed by this check.
4. `git diff --check`: clean.
5. `make --no-print-directory build PYTHON=/usr/bin/python3`: completed;
   **1,816 payload files**. The complete Makefile recipe, `tools/build.py`, and
   `tools/publication.py` were reviewed first. This was pure serialization.
6. Standard-library archive/hash inspection, without extraction or repository
   imports: all 1,816 archive members (34,688,099 uncompressed bytes) match the
   current source and manifest. Archive modes/UID/GID/mtime are canonical, and
   preseed pins for the archive, manifest and `source.sh` match. This proves
   serialization consistency, not rendered runtime behavior.
7. Read-only late-installer search for executable `stat` usage: none found.
   The remaining matches are AppArmor `/proc/*/stat` paths and a comment about
   the intentionally absent applet.
8. Source review of the shared staging order, empty same-basename replacement,
   unchanged strict checker and both runtime policy states. Native precedence
   and foundation-staging regression fixtures were updated but not executed.

Generated SHA-256 values:

```text
c9b6fd8aa603018a232d4b2738cfb6eae6fa4c41f2a371e5f47011f2b918da1a  d-i/forky/payload.tar.gz
e443a22756160eb0963a3d2f00b980fe99e1abc57a083fc9f61bfe95c44b419a  d-i/forky/payload.manifest
fca3d9a6410813de89384e9be9a17eabb3133dd78277c7423241e7b513297f50  d-i/forky/preseed.cfg
```

No validation runner was interrupted or bypassed. None was started without the
required isolation. The generated artifacts are current for this recorded
source set.

## Required acceptance before deployment

- Run the six named fixture modules in the reviewed disposable environment.
  The new credential fixtures redirect only the fixed credential prefix into
  their private tree; they exercise permission/ownership representation, not
  real systemd credential publication. Network/service/namespace commands in
  the netkit fixtures are explicit mocks.
- The forwarding fixture uses only its private `/workspace` tree and mocks
  every management command. Its new cases cover the two policy states, exact
  override bytes, idempotence, unrelated drop-ins, unsafe links/modes/ownership
  and directories, failed enable recovery, timeout/unknown outcomes and wiring.
  None of these fixtures has been executed in this review.
- Run the updated native drop-in fixture with the disposable image's
  `systemd-analyze --root` against its private configuration tree. It represents
  the vendor `syslog.conf`, checks the original conflict, applies the real local
  replacement, and checks off/on/off plus unrelated shadow conflicts. The added
  staging fixture executes the production foundation in a private target and
  rejects any attempted in-target helper or manager invocation. These are
  unexecuted fixtures, not evidence of a passing installation.
- In a disposable native Forky/systemd 262 target, delay rsyslog startup and
  generate bounded early markers. Verify forwarding stays off, early journal
  records remain available, and no queue-full forwarding warning occurs during
  that interval. After `READY=1`, verify the acknowledged reload, trusted auth
  routing and late managed-file delivery. Exercise restart, stop, failed startup,
  abrupt daemon exit, reload timeout/failure and sealing startup ordering; retain
  unknown outcomes and never infer loaded state solely from configuration bytes.
- In a disposable native Forky/systemd 262 target, exercise actual systemd
  credential ACL and ownership fallback layouts as both Filen service UIDs;
  retain negative mode, link, size and directory-access cases. Verify the pinned
  native Filen CLI, time synchronization, account separation and sync lifecycle.
- Exercise netkit startup, Bubblewrap/AppArmor transitions, authenticated SSH
  namespace/root restoration, route-mirror/cleanup, constructor failure,
  interface/namespace replacement, and failed cleanup with retained evidence.
  Verify no observed constructor capability denials recur and no authority is
  added to the daemon/SSH profiles beyond the unchanged design.
- Verify secondboot exit 75 is successful and retries after five seconds, exit
  1 remains failed, and the five-minute total runtime and cgroup cleanup apply.
- Re-run firstboot validation and native application launch, including the
  unchanged private Zoom/Discord launch/shutdown boundary. Accept forwarding
  readiness and native delivery through the gates above before deployment.
- Record the disposable image identity, actual package/kernel versions, fixture
  counts/skips, source fingerprint and generated hashes with acceptance output.
  Existing retained installed-host recovery state needs identity-checked
  reconciliation; this task did not delete it or repair a running host.
