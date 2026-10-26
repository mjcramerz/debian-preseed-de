# Application launch, aggressive tuning and supplied-log review — 2026-10-26

## Scope and evidence boundary

The task prioritizes failed native application launches, the supplied DRM,
thermal-lease and Waybar messages, then the other installed-system logs under
`todo/`. Subsequent user instructions select a 99 C temperature acceptance
limit and aggressive tuning for both Flex profiles and both P15s profiles.

The checkout started clean on `mcr/main` at
`41ef1d8636a7566cf951f3a8bc9317dc0df4f895`. All findings below distinguish the
supplied installed-system snapshot from the changed installer sources. Nothing
was installed on, or changed in, the running host. Tests, fixture imports,
native checks and validation runners were not executed. No disposable execution
environment was created or used. The existing private Zoom/Discord Xwayland
implementation and eligibility boundary were not changed. No software was
compiled from source.

The requested `debian-preseed-de-audit.md` is absent from this checkout; no
revision-specific acceptance claim is inferred from older remediation reports.
Several attempts to delegate independent read-only reviews failed at agent
startup with an encrypted-content hydration error. No child review result is
claimed as evidence.

## 1. Primary failures and source repairs

### Generic application launcher

`todo/journalctl:1385` and `:1392` record systemd rejecting transient launches
with `Invalid UnsetEnvironment= list`. The supplied audit log contains two
Foot launch requests. Decoding their environment-exclusion arguments as data
shows repeated GPU selector names. Managed clients such as Tuta use a different
service construction path, explaining why the reported failure can affect
generic native clients while managed applications still launch.

The combined exclusions in
`hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/generic.py`
contained overlapping fixed exclusions and `gpu.SELECTOR_NAMES`. The definition
now deduplicates them in declaration order. Static literal inspection counts
44 input entries and 33 unique valid environment names, retaining all 18 GPU
selectors. Environment names explicitly supplied by the launcher are still
excluded from `UnsetEnvironment`, and values are still passed by name rather
than copied into arguments.

The entrypoints, bootstrap, module staging list and generic AppArmor attachment
were inspected. The repair changes no payload arguments, toolkit selection,
GPG gate, user-manager ownership, cgroup cleanup or sandbox policy. Unexecuted
cases in `tests/test_installation_fixes_20260912.py` cover Foot, footclient,
Kitty, both Thunar executable names and generic Wayland/Electron paths across
the launch/Intel/NVIDIA modes, with duplicate rejection and exclusion coverage.

The staged `crystal-dock.service` launches `/usr/local/libexec/labwc-panel-run`
and contains no `UnsetEnvironment=` directive. The copied audit capture also
records a Foot request entering `/usr/local/bin/labwc-wayland-app` and the shared
`systemd-run` transient path in the same boot interval as the journal messages.
The logs do not prove whether Crystal Dock or Waybar constructed their own
invalid list or delegated to the shared helper, and the Crystal Dock binary is
not in this checkout. The source diagnosis is therefore limited to the
installer-owned shared transient-property construction: it now deduplicates the
environment names used by Foot, Kitty and Thunar. No direct Crystal Dock binary
repair is claimed.

Systemd 262's [D-Bus property handler](https://github.com/systemd/systemd/blob/v262/src/core/dbus-execute.c)
validates `UnsetEnvironment` using
[`strv_env_name_or_assignment_is_valid`](https://github.com/systemd/systemd/blob/v262/src/basic/env-util.c),
which rejects duplicate entries. This supports the source diagnosis; it is not
an executed launch result for this change.

### Hardware tuning policy and lease failure

The broker first reports a thermal refusal in `todo/journalctl:1225`. The Intel
high lease then fails at `:1396`, `:1416` and `:1424`, followed by a start-limit
failure at `:1429`. The source latches broker faults until an explicit operator
action; reconnecting cannot clear that fault. A confirmed reconciled refusal
now raises `LeaseRejected`, maps to exit status 78 in the unprivileged entrypoint
and is covered by `RestartPreventExitStatus=78` in all eight vendor/profile
lease services. It remains a failed lease and sends no READY notification.
Transport failures and broker disconnection still use the existing bounded
restart policy. Applications retain nonfatal tuning dependencies.

Systemd 262 documents the main-process behavior of
[`RestartPreventExitStatus`](https://github.com/systemd/systemd/blob/v262/man/systemd.service.xml).
The eight target files still use `Wants` for their lease services; they do not
repeatedly uphold a failed lease. The entrypoint, client dispatch, installer
staging, template renderer, broker fault latch and recovery path were reviewed
as source. No readiness, service state or hardware result was tested.

The software refusal diagnostic now includes both the sampled temperature and
the configured limit. The original supplied refusal does not record either
value, so it does not prove the physical reason for the high temperature.

The following policy is present in `btrfs-de-flex.env`,
`btrfs-de-flex-duo.env`, `btrfs-de-p15s.env` and `btrfs-de-p15s-duo.env`:

| Request | Performance and high |
| --- | --- |
| Intel thermal guard | 99 C; application/health guard trips at or above the limit |
| Firmware profile | performance, when the single supported handler is available |
| CPU governor / EPP / EPB | performance / performance / 0 |
| CPU minimum / maximum performance percentage | 100 / 100 |
| Turbo / HWP dynamic boost | enabled when supported |
| CPU frequency ceiling | driver-advertised maximum |
| Uncore minimum / maximum | driver-advertised maximum / maximum |
| Intel GPU minimum / maximum / boost | driver-advertised maximum / maximum / maximum |
| P15s NVIDIA power limit | supported maximum |
| P15s NVIDIA application clocks | maximum working advertised memory/graphics pair |
| P15s NVIDIA persistence | supported mode 1 |

The Flex pair and P15s pair each have identical hardware policy literals.
P15s NVIDIA tuning already used a 99 C software guard. Flex has no NVIDIA
tuning enabled. Automatic AC selection remains performance; battery idle
selection remains silent, with the existing application/manual arbitration.
This is aggressive driver-bounded policy. It does not establish actual clocks,
sustained throughput or thermal stability. Firmware throttling, C-states,
thermald, driver bounds and restoration remain in place. Raw voltage, CPU RAPL
guesses and positive clock offsets were not introduced.

The literal policy extraction and integer conversion in
`scripts/desktop/hardware-tuning.sh`, `hardware-tuning-config.py`,
`etc/hardware-tuning/intel.json.tmpl` and the 50..99 policy validator were
inspected. They carry the selected 99 value into the target policy without
sourcing arbitrary profile data in the Python renderer. Policy fixtures and
thermal-before-write/health fixtures remain unexecuted.

### Waybar helper deprecation

`todo/journalctl:1318` and `:1321` identify the deprecated
`GLib.unix_signal_add` call in the two status-reader processes. The reader now
imports `GLibUnix` 2.0 and uses `GLibUnix.signal_add`; the existing target API
verification source follows the same interface. The packaged dependency and
AppArmor source paths were reviewed. The added inert fixture checks the three
signal registrations and cleanup of their owned source IDs, but was not run.
GLib documents the binding's priority/signum/callback interface in
[`signal_add_full`](https://docs.gtk.org/glib-unix/func.signal_add_full.html).

### Remaining primary messages

| Evidence | Current conclusion |
| --- | --- |
| `todo/journalctl:1301`, eDP-1 atomic commit returns busy | One startup failure is recorded. The supplied journal does not identify the initiating commit, and contains no output-watcher transaction-begin/end record. The source already serializes output changes and takes fresh snapshots after rejection. A compositor/driver failure is not proven resolved by these edits. |
| `todo/journalctl:1410` through `:1421`, GTK accelerator-group assertions | These occur in Waybar after Tuta creates its tray. [Debian Forky Waybar 0.15.0-1](https://sources.debian.org/src/waybar/0.15.0-1/) uses the tagged [SNI implementation](https://raw.githubusercontent.com/Alexays/Waybar/0.15.0/src/modules/sni/item.cpp) that creates dbusmenu clients without an accelerator group, while the [current upstream implementation](https://raw.githubusercontent.com/Alexays/Waybar/master/src/modules/sni/item.cpp) creates one before attaching the menu. The host-profile contract now defines `LABWC_WAYBAR_TRAY_ENABLE=true` in every profile, so the SNI tray remains enabled. The managed Tuta D-Bus proxy and launcher remain unchanged; the GTK assertion remains an unverified package-level runtime risk. |

The source keeps the tray consumer enabled and does not patch or rebuild the
Waybar binary. The DRM message remains an isolated compositor/driver-level
observation without a proven installer-owned initiating transaction.

## 2. Other supplied logs

Every supplied regular file was read and decoded as data for bounded census,
marker and structured-event inspection: 92 files, 25 empty, 4,831,529 bytes.
Detailed content and source tracing concentrated on application, firstboot,
service, networking, audit, security and firmware findings. Marker absence and
empty files are not treated as successful runtime acceptance.

| Log family / evidence | Disposition |
| --- | --- |
| SSH service and auth log: unsupported `GSSAPIAuthentication` | Removed the unsupported directive from the canonical server config. `AuthenticationMethods publickey` continues to restrict authentication. The installer still renders account/port tokens, retains the original conffile, verifies target artifacts and stages enablement offline. No host SSH command was run. |
| SSH journal: negotiated curve25519 produces non-PQ warning | Client and server configs now prefer ML-KEM/X25519 and SNTRUP/X25519 hybrid exchanges, retaining curve25519 compatibility. Account authorization, Ed25519 host/user keys, no-password and no-forwarding settings remain. [OpenSSH guidance](https://www.openssh.org/pq.html) documents these hybrid algorithms and the non-PQ warning. A remote peer can still select a compatible non-PQ exchange; no negotiated result is claimed. |
| Firstboot validation results | The supplied report ends `validation_status=pass`, but records `system_state=starting` and explicitly skips desktop graphics capture because there was no active Wayland session. It does not validate these later launch attempts or the new source revision. |
| Firstboot failed-unit/system/desktop inventories | The early snapshot has no failed system units. The later user-session tuning failures are visible in the journal. These are different capture boundaries. |
| Initramfs stages | Seven stages are retained; local-block explicitly says it was not invoked because root resolved without retry. The root is mounted by local-bottom/init-bottom and target init paths are present. No boot execution was performed here. |
| Mount/fstab/storage snapshots | The supplied findmnt report ends with no errors/warnings and records expected mounts. Empty managed storage logs give no extra coverage. No storage or mount was changed. |
| AppArmor / audit | All 451 captured AppArmor events are STATUS; no DENIED or ALLOWED records are present. Existing profile modes were verified in the historical firstboot report. No policy broadening follows from these captures, and current loaded policy remains unverified. |
| Audit syscall failures | Grouped 18 signatures without printing command payloads. Most are ENOENT executable searches/removal attempts; several systemd directory removals return ENOTEMPTY. The snapshot also contains a failed sudo command and SSH PAM identity events. These records are retained as evidence; no authorization/cleanup policy was weakened from the failure codes alone. |
| veth / network / DNS snapshots | Tuta records route update and network-ready events. The early snapshot shows active NetworkManager/static networking and intentionally inactive networkd. `network-targets.txt` status 3 includes that inactive unit. Repeated `DNSSEC=no/unsupported` describes link capabilities; the configured local upstream is a loopback Stubby endpoint. No live connectivity, DNS confidentiality or isolation result was tested. |
| nftables / Fail2ban | Firewall capture contains accepted traffic. Fail2ban creates a new database and starts the configured SSH jail. These are historical events, not new enforcement tests. |
| CrowdSec | The bootstrap journal ends complete with console enrollment pending approval. The two console-sync errors occur before enrollment completes/pends. Early CAPI-disabled phases are followed by communication-enabled bootstrap events. Duplicate GROK registration warnings and absent qBittorrent log warnings do not prove failed ingestion; file discovery polling is enabled. Console acceptance and actual security-event ingestion remain unverified. |
| Other security/model logs | Scanner, antivirus, firmware-scan and model logs that are empty provide no scan/model acceptance evidence. Their emptiness alone does not authorize changing service scheduling or security controls. |
| Kernel / USB / dmesg | UCSI PDO retrieval, I2C firmware fallback and HID report diagnostics are present. The captures do not isolate an installer source defect or prove that firmware updates would resolve them. No speculative firmware, module, USB or power change was made. |
| Timeshift / zram | GRUB snapshot refresh completes. Zram maintenance reports normal state and skips below the configured pressure threshold. No workload, writeback or recovery benchmark was run. |
| Tuta application stream | The supplied log reaches Webapp ready and dictionary-download success, with vendor Node/updater warnings. This supplies evidence for that recorded launch only; it does not prove every application works. |

## Checks performed for this revision

1. Read attachments, repository instructions, Makefile, full build/publication
   source and the relevant callers/delegates/templates/policies as data.
2. Parsed ten changed Python entrypoint/module/fixture sources using `ast.parse`,
   without repository imports or execution. Parsed the changed embedded target
   verifier and its nested GI probe source the same way.
3. Inspected literal exclusion names and four hardware policies as data. Checked
   single/Duo policy equality and the selected aggressive settings.
4. Inspected all eight service/target directive pairs. An initial overly broad
   string assertion matched `Upholds=` in a comment; directive-only inspection
   resolved that inspection false positive without a production change.
5. Inspected all ten host profiles as data. Btrfs profiles contain only their
   Btrfs slot/size schema, F2FS profiles contain only their F2FS slot/size
   schema, and every profile explicitly selects atomic KMS with
   `LABWC_WLR_DRM_NO_ATOMIC="0"`.
6. Ran `git diff --check`; no whitespace errors were reported.
7. Ran only the reviewed generation path:
   `/usr/bin/env -i PATH=/usr/bin:/bin /usr/bin/timeout 60s /usr/bin/make build PYTHON='/usr/bin/python3 -I'`.
   It reported `built 1845 payload files`.

No unittest, test discovery, native syntax checker, target API probe, validator,
AppArmor parser, service operation or application launch was run. No inventory
utility was executed. Existing inventory products were not regenerated and
must not be assumed to describe this new payload. Generated products are
present from the permitted serialization command above; no additional
artifact-fingerprint comparison is recorded here.

The supplied target reports Debian Forky/sid, systemd `262-1` and kernel
`7.2.12-x64v3-xanmod1`. No target image ID or complete application/library
package version set was supplied. No deployment or performance improvement is
claimed from serialization or source parsing.

## Remaining acceptance evidence

The full objective remains incomplete. Current source evidence does not prove
successful Thunar/Foot/Kitty launches, the complete installed application set,
loaded policy, native Zoom/Discord launch/shutdown, GI signal delivery, actual
maximum clock acceptance, sustained thermal/performance behavior, SSH
negotiation, security-event ingestion or the DRM compositor/driver cause. Existing
unexecuted fixtures are not substitutes for those observations. Repository
instructions prohibit running the native checks or requesting a disposable
environment; these limits do not authorize a host fallback or host repair.

## Supplied-file census

The supplied `todo/` tree contains 92 regular files totaling 4,831,529 bytes;
25 are empty and 67 contain data. The review covered the journal, installer
state and firstboot reports, audit and AppArmor records, initramfs and mount
snapshots, networking/DNS/firewall records, CrowdSec and Fail2ban logs, kernel
and USB diagnostics, application streams, and the remaining empty or metadata
only captures. No private log payloads are reproduced in this report.
