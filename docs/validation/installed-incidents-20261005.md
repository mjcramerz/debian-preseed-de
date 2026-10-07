# Supplied installed-host incidents: 2026-10-05

## Scope and evidence coverage

The deployment target remains Debian Forky with systemd 261.2. All 88 regular
files under `todo/` were read: 4,016,329 bytes, including 42 empty files. The
P15s evidence is `todo/managed/`; the Flex evidence is `todo/nfs/managed/`.
The top-level storage log duplicates the P15s managed storage log byte for
byte. Repeated events across journal, audit and service logs were correlated.
Empty scanner/model logs provide no evidence of a completed scan or execution.

| Evidence paths under `todo/` | Files | Review |
| --- | ---: | --- |
| `apparmor.log`, `storage.log`, `journalctl` | 3 | P15s denial, repeated NVMe Receiver Error, boot/session context. |
| `managed/system/**` | 14 | Kernel/system/storage, seven initramfs logs, USB, fwupd, zram and Timeshift. |
| `managed/security/**` | 24 | AppArmor modes/audit/authentication, nftables, fail2ban, CrowdSec, antivirus and scanner outputs. |
| `managed/apps/**` | 1 | Audio startup, native Vivaldi launch, browser/vendor messages and display errors. |
| `managed/models/**` | 6 | Codex/ChatGPT runtime and login logs, Whisper. |
| `nfs/Fail`, `nfs/journalctl` | 2 | NFS identity timeout and disconnected-network/DNS failures. |
| `nfs/managed/system/**` | 7 | Flex network boot, client automount, kernel/USB, fwupd, storage, zram and Timeshift. |
| `nfs/managed/security/**` | 24 | Same security families on Flex, including loaded AppArmor modes. |
| `nfs/managed/apps/**` | 1 | Flex session/audio/application context. |
| `nfs/managed/models/**` | 6 | Flex model/runtime/login evidence. |

No supplied log was changed. This repair changes installer sources and their
generated snapshot. It does not constitute a live repair or deployment to
either logged host.

## NVMe correctable messages

The reported endpoint is `15b7:5006`, PCI class `010802`, WDC PC SN730
SDBQNTY-512G-1001, firmware `11170101`. The supplied errors are correctable
Receiver Errors (`RxErr`, bit 0). Firmware withholds OS ASPM control and the
kernel runs with Secure Boot and `lockdown=integrity`. Raw `setpci` configuration
writes would be rejected by the kernel's PCI lockdown check.

`74-nvme-link-idle.rules` retains the supported APST/runtime-power/available
link-idle mitigations and sets this PCI device's supported AER log controls:

```text
aer/correctable_ratelimit_interval_ms = 5000
aer/correctable_ratelimit_burst = 0
```

The positive interval is essential: interval zero disables limiting. Burst zero
suppresses correctable log messages for this endpoint. The kernel also gates
the root-port message naming a found error source on the source's log decision.
The rule does not change the root port, PCI error masks, global logging or the
nonfatal/fatal log-limit settings. AER statistics, tracing and error handling
continue. The read-only `nvme-pcie-status` helper reports the actual log-control
state alongside counters and power/link evidence; absent controls remain
unknown and it always reports `hardware_health_verified: false`.

The rule and its initramfs hook are staged by both storage families. The hook
copies the rule into initramfs; existing kernel repair refreshes the initramfs
after storage asset staging. No new binary or software compilation is needed.
The kernel ABI introduced these controls in Linux 6.16, before the supplied
7.2.9 kernel. See the [kernel AER ABI](https://raw.githubusercontent.com/torvalds/linux/master/Documentation/ABI/testing/sysfs-bus-pci-devices-aer),
[AER driver](https://raw.githubusercontent.com/torvalds/linux/master/drivers/pci/pcie/aer.c),
[rate-limit implementation](https://raw.githubusercontent.com/torvalds/linux/master/lib/ratelimit.c)
and [PCI lockdown check](https://raw.githubusercontent.com/torvalds/linux/master/drivers/pci/pci-sysfs.c).

This is the requested correctable-message workaround. Physical link errors can
still occur and increment counters. Events before udev applies the rule, or
firmware-originated reports through another reporting path, cannot be ruled
out by this configuration. The supplied logs establish neither media failure
nor drive health; increasing counters still require hardware/firmware assessment.

## Networking and NFS client

Flex `system.log` records the validator waiting 15 seconds for absent `eth0`.
Only `wifi0` is present on that boot and NetworkManager leaves it disconnected.
The agreed policy is Ethernet when attached and Wi-Fi when Ethernet is absent.

Boot `network.service` now uses `validate --wait-seconds 15 --allow-absent`.
This permits a detached adapter but retains configuration, CIDR, interface type,
wireless classification and MAC validation for attached adapters. Partially
registered devices still require readable attributes. Manual validation is
strict by default; duplicate/unknown options fail. The installer retains
supplied Wi-Fi settings even when Ethernet carries installation. Existing
Ethernet/Wi-Fi route metrics remain 100/200. Wi-Fi needs its SSID/authentication
through the existing private installer inputs; these logs do not supply usable
Wi-Fi configuration and the code does not invent credentials.

The client identity service times out after 30 seconds, without an AppArmor
denial or helper execution record identifying its blocking stage. Two concrete
startup hazards are removed:

- The read-only identity service hides `/data`, `/pool`, `/srv` and homes from
  its namespace, so it cannot touch the automount waiting for the check.
- Shared membership uses the managed group's member list and primary GID.
  It no longer enumerates all NSS group providers with unbounded `getgrouplist`.

The helper emits `checking` and `verified` events. UID/GID/home/domain checks,
anonymous exclusion, mapping/module requirements, export/daemon drift checks,
AppArmor enforcement requirements and the service timeout remain. These changes
address source hazards; the exact installed timeout mechanism still needs live
confirmation.

The supplied source profiles are preserved: `btrfs-de-p15s` enables its server
and server home bind; `btrfs-de-flex-duo` enables its client and client home bind
to `192.168.50.82:/`. The other eight profiles disable both roles. This existing
client address is configuration, not a new discovery from a live server.

`/data/sharing` and `~/Sharing` remain parents. Only the server child is exported;
only the client child mounts the remote namespace. The installer already uses
a browsable root-owned 0755 home parent and separate endpoints. Its AppArmor
document abstraction incorrectly required account ownership of the root-owned
parent. That rule is now an unqualified read of `@{HOME}/Sharing/`; parent writes
and execution are not added. Native parser checks verify access by a non-owner
to the parent and separate child rules. The client child can still wait/fail
when the network/server is unavailable, as required by the existing hard-mount
and group/export policy.

## AppArmor and audio

The distinct current audit denial is `ksecretd` executing `/usr/bin/gpgsm`.
The wallet profile now grants exactly `/usr/bin/gpgsm rix,`, inheriting wallet
confinement just like its existing GPG engine permissions. No unconfined
transition or executable wildcard was added. The other supplied AppArmor
records are profile/mode status events; Flex has no distinct denied operation
requiring another grant.

Both hosts log a successful initial speaker selection. P15s subsequently
recreates HDMI/audio nodes, so a one-time login choice is insufficient.
The P15s-only WirePlumber fragment now loads a required native Lua policy hook.
It selects an available Speaker profile from actual `EnumProfile` names and
associated output-route availability whenever WirePlumber selects a profile.
It runs before preferred/best-profile ranking, supports differing UCM Mic/HDMI
combinations, rejects explicit unavailable speaker routes, and leaves an
already-selected earlier-hook choice intact. Speaker node priority remains
above headphones. Flex profile staging and its existing audio policy remain.
There is no additional service, polling process or source compilation.

## Remaining supplied incidents

| Incident | Source action or remaining requirement |
| --- | --- |
| Native Vivaldi rejects a missing `DBUS_SESSION_BUS_ADDRESS` | Native launch may recover only the existing, current-user-owned bus socket in the validated private runtime directory. Explicit malformed/foreign addresses and non-socket/symlink/foreign-owner paths still fail. The desktop must already be active. Private Zoom/Discord calls retain the existing bus requirement. |
| Calendar/Fruux, antivirus update, CrowdSec CAPI and Tailscale DNS failures on Flex | Correlated with disconnected Wi-Fi and absent Ethernet. Adapter validation and configured Wi-Fi retention are repaired; actual association, routing, DNS and reachability need an installed host. |
| Flex USB descriptor errors `-71`, failure to accept addresses/enumerate, port enable failure, UCSI `GET_PDOS -5` | No failing device VID/PID is established before enumeration. Cable/device/port/firmware diagnosis remains; no safe device-specific quirk can be selected from this evidence. |
| P15s ACPI `_SB.HIDD._DSM` / `AE_AML_OPERAND_TYPE`, resource reservations | Firmware/kernel interaction remains. No evidence supports a narrow AML override or global ACPI disablement. |
| P15s HDMI-A-2 atomic commits return `EBUSY`; NVIDIA no-CRTC and libinput lag messages | Display/driver acceptance requires the actual monitor/dock and running compositor. A log alone does not establish a safe modesetting or GPU policy change. |
| Codex reserved marketplace and missing bundled plugin references | The installer clones the managed Codex home from another repository; the failing marketplace/plugin definitions are not authored here. That external configuration must be reconciled against the installed Codex version. No fabricated plugin references or credentials were added. |
| Vivaldi missing first-run `search_engines.json`; NoScript image rejected by `web_accessible_resources` | Browser/extension initialization and vendor manifest behavior. No synthetic browser database or extension permission bypass is justified. |
| Bitwarden hardlink `EXDEV`, then copy success; missing refresh token | The copy fallback succeeds across the intended filesystems. Missing authentication requires the account's real login state. |
| CrowdSec unenrolled console, packaged duplicate grok warnings | Console enrollment is optional and requires its real enrollment configuration. Local API/bouncer records show successful responses. CAPI DNS failure remains conditional on connectivity. |
| Missing Bluetooth IRK on an unpaired host; fail2ban database/jail initialization warnings | Expected initial state; no source defect established by the supplied logs. |
| Global Xwayland executable missing | The requested private Zoom/Discord arrangement is preserved. No Xwayland source or archive member changed. |
| Initramfs, Timeshift and zram records; empty scanner/model/fwupd outputs | Supplied nonempty maintenance records do not establish another correctable source fault. Empty files cannot establish successful scans or firmware health. |

## Validation

Python 3.14.7, AppArmor parser 4.1.8, WirePlumber 0.5.17 and native Perl/Moo
dependencies were available. The local systemd tools are **262**, so their
generator results are not runtime acceptance of target systemd **261.2**.

All unittest commands below used `python3 -B -m unittest discover -s
d-i/forky/tests`, followed by the listed pattern and optional selection:

| Pattern / selection | Result and boundary |
| --- | --- |
| `-p test_nvme_link_idle_20260927.py` | 7 passed, 15 root-owned-sysfs fixtures skipped. Native `udevadm verify`, staging failure checks, and read-only log-state fixtures; no PCI write or udev trigger. |
| `-p test_network_sharing.py` | 102 passed, 22 skipped: 21 root-owned filesystem fixtures and one unavailable native systemd condition environment. Includes all ten profile policies, native fstab generation, real NFS config parsing, effective source AppArmor permissions and identity drift fixtures. No mount/server activation. |
| `-p test_boot_runtime_20260913.py -k NetworkReadinessTests` | 12 passed using actual Perl/Moo dependencies with disposable network/sysfs data. No real adapter or network mutation. |
| `-p test_boot_runtime_20260913.py -k test_installer_stages_configured_wifi` | 1 passed, four cases in both dash and BusyBox sh, with installer discovery/staging fixtures. |
| `-p test_apparmor_incidents_20261004.py` | 9 passed, exact incident policy contracts. |
| `-p test_p15s_audio_20261004.py` | 5 passed: real SPA JSON/native WirePlumber rule matcher, Lua execution with mocked events/parameters, and filesystem staging fixtures. No real audio devices/daemon. |
| `-p test_installed_failures_20260911.py -k NativeSessionBusTests` | 5 passed. Real private filesystem plus explicitly mocked socket metadata; Unix socket bind is forbidden by the execution platform. No bus contacted. |
| `-p test_installed_failures_20260911.py -k SessionOwnershipTests` | 7 passed, transient launch/ownership/lifecycle argument fixtures. No user-manager activation. |

That is 148 selected tests passed and 37 explicitly skipped. An additional
single network test passed with the deliberately forced test-only Perl
constructor adapter; it checks fixture portability, not Moo's type system.

Additional successful checks:

- Native offline `labwc-session` parsing, with the repository abstraction/local
  overlay, an empty private parser configuration, `-Q` and `-K`. `ksecretd` is
  emitted; no kernel policy load or cache write occurs. NFS parser tests use
  the same isolated source selection so installed includes cannot shadow edits.
- `python3 -B tools/check_shells.py`: 350 shell files, 711 syntax/parser checks.
- `python3 -B tools/check_preseeds.py`: 59 preseed files; all four generated
  command values survive private debconf database read-back.
- ShellCheck 0.11.0: new initramfs hook passes. Comparison against `HEAD` adds
  zero diagnostics in the three changed installer shell files; four pre-existing
  diagnostics remain across those files.
- `python3 -B tools/build.py`: 1703 payload members; 16 changed/added members,
  comprising 14 edited sources and two new assets. Browser outputs are current.
  The archive, manifest and preseed pins were regenerated together.
- `python3 -B tools/build.py --check`: snapshot, pins and preseed are current.
- `git diff --check`: passes with no whitespace errors.

Live acceptance remains necessary for the actual NVMe logging state after
boot/resume, Ethernet/dock removal and Wi-Fi association, NFS identity startup
and browse/read/write behavior, enforcing wallet execution, and P15s audio
after jack/profile changes. Physical USB/PCIe/firmware/display faults and
external account/vendor configuration cannot be declared resolved by these
offline checks. Earlier broad-suite failures recorded in `BUILD-STATUS.md`
were not rerun as part of this scoped repair.
