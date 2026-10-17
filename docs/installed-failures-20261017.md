# Installed failures, 17 October 2026

## Scope and evidence

Read every regular file under `todo/` as data: **52 files, 4,799,105 bytes,
22,205 newline-delimited records, including 24 empty files**. The current
17 October LPL-068 boot and the historical 13 October LPL-584 journal in `todo/.~`
are distinct observations. Journal excerpts, application logs and audit copies
repeat many of the same incidents; they are not independent defects.

The sorted inventory records path, byte count, LF record count and SHA-256.
Its JSON receipt is `/tmp/preseed-todo-incident-384s4i3c/inventory-lf.json`,
SHA-256 `fc98f4c98f360cd3822c10c34923ef962f54a17b46555a093276a2db103d2971`.
LF counts deliberately do not split auditd's enriched-record separator byte.
No raw credentials or command arguments are copied into this report.

There are six distinct AppArmor denial events, all the same read contract for
`apt-repo-local-software-notify` and `Managed/Process.pm`. The native audit files
contain 93 failed syscall events: six EACCES, 84 ENOENT and three ENOTEMPTY.
The ENOENT records show command search candidates or removal of absent owned
links; successful later executions and cleanup messages are correlated by
process/event. ENOTEMPTY is systemd preserving nonempty wants directories.
No additional permission failure was established from those records.

## Source repairs and installation wiring

Paths in this table are relative to `d-i/forky`.

| Incident and evidence | Cause and repair | Boundary retained |
|---|---|---|
| Notifier cannot load `Managed/Process.pm`; `todo/journalctl:1455`, `todo/app:1`, `todo/managed/apps/apps.log:137`. | `hooks/target/usr/local/libexec/apt-repo-local-software-notify` imported the entire updater CLI, which eagerly imports ChatGPT and repository delegates. It now imports and invokes only `Servicing::Notifier`, preserving argument rejection and its returned status. `scripts/late/software.sh.tmpl` already stages the notifier and its Atomic/ArtifactLimits dependencies before bootstrap. | The notifier profile remains restricted; it gains no updater, import, signing or package-management authority. Its existing service reads trusted events without remapping host root. |
| Plans exits with `unsafe notification policy file` five times, then hits the start limit; `todo/journalctl:1398`, `todo/Fail:14`. | The live policy reader requires UID 0, while this user unit's mount/UTS restrictions implicitly create a user namespace in systemd 262. Host root becomes unmapped. `hooks/target/etc/skel-desktop/.config/systemd/user/labwc-plans.service` now follows the notifier unit's existing host-UID convention and omits those namespace settings. `components/user-session.sh` stages the canonical unit, and `desktop-config.sh` renders the policy root:account-group 0640. | UID 0, regular-file, single-link, size, mode, no-follow and changed-file checks remain. AppArmor still grants only read access to the policy and input plans, plus the helper's private state. NoNewPrivileges, syscall/address-family/namespace restrictions, UMask and cgroup lifetime remain. The unit loses its mount/UTS/proc sandbox; native acceptance must confirm the resulting policy visibility. |
| Secondboot reports a corrupt initramfs; `todo/journalctl:1439-1446`. | The rejected filename is actually `initrd.img-7.2.11-x64v3-xanmod1.sig`, the detached signature published by the signing hook. `scripts/firstboot/assets/var/lib/firstboot/bin/secondboot-cleanup` now excludes `.sig` from its image enumeration. This canonical script is installed by the existing firstboot asset staging path. | Every actual image must still be listed successfully, fit the output limit, and contain no temporary health hook. Signature-only/no-image and real verification failures still fail cleanup and retain pending work. No signature verification is bypassed or boot artifact deleted by this filter. |
| CrowdSec cannot find any key/value pair and its audit parser fails; `todo/managed/security/crowdsec/crowdsec.log:274-275`. | The old local pre-parser handled only one exact syslog rotation notice. `hooks/target/etc/crowdsec/parsers/s01-parse/00-auditd-daemon.yaml` now labels non-record `auditd` messages before the upstream unconditional ParseKV call, for either acquisition. `scripts/late/crowdsec.sh` already stages this local parser before service bootstrap. | Native `type=... msg=audit(...)` records, with or without `node=`, retain the auditd route, including numeric and unknown record types. Existing audit ABI/root/user coverage and requested collections remain. The error's exact input is absent from the supplied log; native parser acceptance remains open. |

The plans namespace explanation is an inference from the installed unit, staged
file metadata contract and [systemd 262 execution source](https://github.com/systemd/systemd/blob/v262/src/core/exec-invoke.c).
No installed-file stat or host manager query was performed. The parser repair
matches the upstream [auditd parser's unconditional ParseKV contract](https://github.com/crowdsecurity/hub/blob/master/parsers/s01-parse/crowdsecurity/auditd-logs.yaml);
the upstream parser was not modified.

## Other reported messages

| Observation | Disposition |
|---|---|
| USB-C `ucsi_acpi` unknown error 88 and `UCSI_GET_PDOS failed (-5)`; `todo/managed/system/usb/usb.log:50-54`. | Unresolved native firmware/driver issue. Supplied records do not establish a repository cause or safe firmware-specific fix. Do not disable the controller or claim USB-C charging/dock functionality accepted. Requires a disposable/native hardware check using the same firmware and packaged kernel. |
| Global `/usr/bin/Xwayland` missing; `todo/journalctl:1338`, historical journal too. | Expected consequence of the explicit private-Xwayland boundary. Labwc continues without global Xwayland. User excludes changing this implementation; exactly Zoom/Discord remain eligible for private Xwayland. Their native launch/shutdown acceptance remains required. |
| Historical Waypaper `No enumerators available`, falling back to `All`; `todo/.~:1434-1435`. | Nonfatal fallback in the older boot; the managed configuration already selects `All` with native swaybg. No current-boot recurrence or denied monitor operation is supplied. Per-output enumeration is not established as working; reproducing the pinned Waypaper 2.9/native display combination remains open. No X11 fallback or vendor patch was introduced. |
| CrowdSec console not enrolled; `crowdsec.log:273,294`. | Journal later records `pending-approval` and bootstrap `status=pass` at `todo/journalctl:1403-1405`; bouncer authentication succeeds. Console approval is external. Do not reset credentials, reenroll repeatedly or report approval completed. |
| Historical Tailscale approval timeout; `todo/.~:1560-1563`. | That bootstrap deliberately retains its pending approval state and retry service. The newer boot completes and retires its completed bootstrap. External device approval cannot be supplied by a source change. |
| Tailscale stopped/starting, `netfilter=off`. | Boot transition messages; the repository owns firewall policy. The newer journal subsequently reports bootstrap completion. These lines do not establish a persistent VPN fault. |
| Duplicate CrowdSec `IPv4_WORKAROUND`/`IP_WORKAROUND` Grok warnings. | Upstream sshd and successful-login parsers register the same definitions; parsing continues. Keep the requested collections and both login paths. Native parser coverage remains a gate. |
| Missing qBittorrent acquisition file before its first launch. | Acquisition reports a polling retry. Do not create fake application data or disable collection to suppress this warning. Native acquisition after first launch remains required. |
| Bluetooth identity missing on fresh boot. | The immediately following messages report `Generated IRK successfully`; BlueZ enables the controller and completes initialization. Do not manufacture an identity file or overwrite keys. |
| Fail2ban database creation/version warning, XFS log-only policy messages, PCIe DPC capability banners, early supply/ACPI reservations. | Startup/policy/capability observations with later service progress; no additional repository failure established. No speculative driver, storage or security-policy edits. |
| Empty application/scanner/security logs. | Absence of evidence only. Neither a successful scan/application launch nor a failure can be inferred. |

## Complete file coverage

All paths below are relative to `todo/`. An empty file has no runtime evidence.

| File | LF records | Review result |
|---|---:|---|
| `.~` | 1617 | Historical journal; approval, global Xwayland and Waypaper observations above. |
| `Fail` | 17 | Repeated service failures correlated to the three service repairs. |
| `app` | 5 | Copies of the notifier denial. |
| `fail` | 20 | Notifier compilation chain and global Xwayland; Fail2ban starts successfully. |
| `journalctl` | 1729 | Current boot chronology and decisive service errors. |
| `managed/apps/apps.log` | 269 | Plans/notifier repetitions; other session components start. |
| `managed/models/openai/chatgpt/chatgpt.log` | 0 | Empty. |
| `managed/models/openai/chatgpt/runtime/codex-login.log` | 0 | Empty. |
| `managed/models/openai/chatgpt/runtime/codex-tui.log` | 0 | Empty. |
| `managed/models/openai/codex/codex-login.log` | 0 | Empty. |
| `managed/models/openai/codex/codex-tui.log` | 0 | Empty. |
| `managed/models/whisper/whisper.log` | 1 | Daemon start only; no recognition acceptance. |
| `managed/network/veth.log` | 0 | Empty. |
| `managed/security/apparmor/apparmor.log` | 441 | Loaded-state records and notifier denial; no second denial contract. |
| `managed/security/apparmor/modes.log` | 52 | Requested/source/loaded modes agree in the supplied snapshot. |
| `managed/security/audit/auditd.log` | 7859 | Native syscall/event correlation. |
| `managed/security/audit/auditd.log.1` | 8390 | Earlier records of the same boot; native syscall/event correlation. |
| `managed/security/auth/auth.log` | 20 | Normal authentication/session/privilege records. |
| `managed/security/chkrootkit/chkrootkit.log` | 0 | Empty. |
| `managed/security/chkrootkit/daily.log` | 0 | Empty. |
| `managed/security/chkrootkit/daily.log.raw` | 0 | Empty. |
| `managed/security/chkrootkit/log.expected` | 0 | Empty. |
| `managed/security/clamav/clamav.log` | 0 | Empty. |
| `managed/security/clamav/freshclam.log` | 0 | Empty. |
| `managed/security/clamscan/clamscan.log` | 0 | Empty. |
| `managed/security/crowdsec/crowdsec-firewall-bouncer.log` | 18 | Authentication and streaming start; no bouncer error. |
| `managed/security/crowdsec/crowdsec.log` | 393 | Audit parser repair and startup/approval messages above. |
| `managed/security/crowdsec/crowdsec_api.log` | 20 | Successful local API/bouncer requests. |
| `managed/security/debsecan/debsecan.log` | 0 | Empty. |
| `managed/security/debsums/debsums.log` | 0 | Empty. |
| `managed/security/fail2ban/fail2ban.log` | 18 | New database and successful service initialization. |
| `managed/security/lynis/lynis-report.dat` | 0 | Empty. |
| `managed/security/lynis/lynis.log` | 0 | Empty. |
| `managed/security/lynis/scan.log` | 0 | Empty. |
| `managed/security/nftables/nftables.log` | 18 | Accept logs only; no policy-generation failure. |
| `managed/security/rkhunter/rkhunter.log` | 0 | Empty. |
| `managed/security/rkhunter/scan.log` | 0 | Empty. |
| `managed/security/spectre-meltdown-checker/spectre-meltdown-checker.log` | 0 | Empty. |
| `managed/system/fwupd/security-scan.log` | 0 | Empty. |
| `managed/system/initramfs/01-init-top.log` | 49 | Supplied stage progress; no stage error. |
| `managed/system/initramfs/02-init-premount.log` | 53 | Supplied stage progress; no stage error. |
| `managed/system/initramfs/03-local-top.log` | 55 | Supplied stage progress; no stage error. |
| `managed/system/initramfs/04-local-block.log` | 5 | Supplied stage progress; no stage error. |
| `managed/system/initramfs/05-local-premount.log` | 25 | Supplied stage progress; no stage error. |
| `managed/system/initramfs/06-local-bottom.log` | 33 | Supplied stage progress; no stage error. |
| `managed/system/initramfs/07-init-bottom.log` | 85 | Supplied stage progress; no stage error. |
| `managed/system/kernel.log` | 923 | Boot and capability records; no additional actionable failure established. |
| `managed/system/storage/storage.log` | 0 | Empty. |
| `managed/system/system.log` | 3 | Secondboot service failure duplicate. |
| `managed/system/timeshift/timeshift.log` | 0 | Empty. |
| `managed/system/usb/usb.log` | 84 | UCSI firmware/driver errors remain open. |
| `managed/system/zram/zram.log` | 3 | Active 16-GiB lz4 device with encrypted writeback; no failure logged. |

## Regression specifications and acceptance boundary

- `d-i/forky/tests/test_installed_failures_20261017.py`: notifier import closure,
  delegate status/argument handling, signature exclusion, corrupt real image,
  retained health hook, signature-only/no-image failure and audit-header routing.
  The last case models the regex; it does not execute the CrowdSec expression.
- `test_notification_policy_20261017.py`: live disable/destination behavior and
  rejection of writable, symlinked and hardlinked policy files.
- `test_desktop_sandbox.py`: the plans unit's UID namespace contract and retained
  independent restrictions. `test_logged_failures_20260927.py` retains the
  earlier exact policy-read and secondboot temporary-file AppArmor contracts.
- `test_comprehensive_contracts_20261017.py`: conditional MOK guard and nonfatal
  installer failure cases. See the comprehensive implementation ledger.

**None of these fixtures was executed.** `AGENTS.override.md` and
`docs/test-isolation.md` prohibit host execution; no prepared disposable image
is available. No repository import, Perl compile/BEGIN execution, shell syntax
runner, native CrowdSec/AppArmor/systemd validator, firmware operation, host
service probe, package installation or host repair was performed. Sidecar
delegation failed at agent initialization and supplies no independent evidence.

The target contract is Forky/systemd 262. The supplied logs identify kernel
`7.2.11-x64v3-xanmod1`, CrowdSec `1.8.2~rc1-debian-pragmatic-amd64-c86bf40b`
and BlueZ 5.87; these are log observations, not a validated image/package
inventory. Native acceptance must cover plans policy reads in the actual user
service, confined notifier loading/delivery, real signed-initramfs cleanup and
reboot, CrowdSec parsing/rotation/acquisition, and unchanged native/private-app
launch/shutdown. The original comprehensive audit's other open gates remain.

## Final static and serialization receipt

- Base revision: `16282bfcfc771fbb0fed81135f4b276886766d9c`, plus the preserved
  working tree; no commit or deployment was made.
- Source fingerprint:
  `c8a80e0424b642a9a928ba06d5dde77707e6415bec0e0b9c990824ebcdae4391`,
  over 2,311 records. Each record is four-digit octal mode, SHA-256 and relative
  path, separated by spaces and terminated by LF, in sorted path order.
  Exclusions are the three generated products and the four review reports
  `audit-remediation-20261017.md`, `comprehensive-audit-implementation-20261017.md`,
  `tracked-changes-review-20261017.md` and this report under `docs/`.
- Fixture fingerprint:
  `fcdd53ad68dbf694b37dd55c146f8fb725487609f68e012785513e616537cbc8`,
  over the 258 source records whose paths contain `/tests/`. These identify
  authored fixture bytes, not executed results.
- Standard-library AST parsing succeeded for 47 changed/new Python or
  Python-shebang source files. No repository module was imported or executed.
  `git diff --check` exited 0.
- Fifteen path-named private-Xwayland/NVIDIA-legacy/CUDA-legacy implementation,
  configuration, test and preservation-report files were compared as data and
  are byte-identical to HEAD. The current two-app eligibility and shared-file
  changes were inspected separately; no Xwayland implementation was changed.
- The reviewed pure serialization command below exited 0 and reported 1,798
  payload files. Data-only archive inspection matched every member byte to its
  current source and manifest digest: 34,554,745 uncompressed bytes. Member
  sets agree; all members are regular files, mode 0644, uid/gid/mtime zero and
  empty owner/group names. No archive member was extracted or executed.
- Archive, manifest and bootstrap-source pins in `preseed.cfg` match those
  bytes. A before/after inventory of 2,318 Git-enumerated existing tracked and
  untracked files showed exactly the three product changes below; source
  inputs did not change during generation. This report was updated separately
  after generation and is excluded from the source fingerprint.

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
```

| Product under `d-i/forky/` | Bytes | SHA-256 |
|---|---:|---|
| `payload.tar.gz` | 26,521,983 | `0622b4027404a09bef14dd3e87722ec75e4ee078e09c5ecda5ed98c7b9250e77` |
| `payload.manifest` | 221,645 | `a9cd67ac282865a96ac374b0871c51821805e584a0f6133ecb3f77d88602e75e` |
| `preseed.cfg` | 95,579 | `71cfb05d4e1015fcb664cc5c6ef7bb0b1c7061446061904739b2472de100d78b` |

Detailed local static receipts are in `/tmp/preseed-installed-final-1wbpsszq`.
Pure serialization and byte consistency are distinct from target runtime
acceptance. The unresolved hardware, historical GUI and external-approval
observations above, the unavailable fixture execution and the comprehensive
audit's remaining gates are not claimed complete.
