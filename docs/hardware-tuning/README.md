# Hardware tuning policy

The installer stages policy, units and the vendor backends only after the
existing CPU/GPU and selected-class gates pass. Staging does not write hardware
or contact a running system manager. Runtime ownership belongs to the existing
hardware tuning broker and its recovery journal.

## AC workstation profiles

`btrfs-de-p15s{,-duo}` targets the Core i7-10610U and Pascal Quadro P520.
`btrfs-de-flex{,-duo}` targets the Core i3-1115G4 and Tiger Lake Intel graphics
with the iHD media driver. Both machines are normally connected to AC power.
Each single/duo pair has the same hardware policy.

| Setting | P15s | Flex |
| --- | --- | --- |
| Automatic tuning at boot | Enabled | Enabled |
| Active local desktop on AC | Performance | Performance |
| Performance CPU governor and minimum percentage | performance / 100 | performance / 100 |
| High CPU governor and minimum percentage | adaptive / 40 | adaptive / 35 |
| Firmware profile, performance/high | performance | performance |
| Firmware profile, balanced/silent | balanced / low-power | balanced / low-power |
| Performance/high EPP and EPB | performance / 0 | performance / 0 |
| Performance/high CPU maximum percentage | 100 | 100 |
| Performance/high turbo and HWP dynamic boost | Enabled when supported | Enabled when supported |
| CPU thermal interlock | 88 C | 85 C |
| Performance/high uncore minimum | 2 GHz / 1.2 GHz | 2 GHz / 1.2 GHz |
| Performance/high Intel GPU minimum | advertised maximum / efficient | advertised maximum / efficient |
| Intel GPU RPS up/down, performance | 80% / 60% | 80% / 60% |
| Intel GPU RPS up/down, high | 90% / 75% | 90% / 75% |
| GPU requests | Driver-advertised NVML controls | Driver-advertised Intel GPU maximum/boost |
| GPU thermal interlock | 85 C | Uses Intel backend sensor coverage |

The performance AC baseline survives application leases requesting high or
balanced. Manual selection retains precedence. An inactive desktop, pause or
vendor fault still prevents automatic writes. If a laptop reports battery power
or its AC state is unknown, its idle selection remains silent; existing
application lease arbitration remains in effect on battery.

The supplied October 24 measurements describe an **untuned baseline**. They
establish available interfaces, frequency limits and reference throughput; they
do not measure the effect of these policies. Performance selects the actual
`performance` governor and the full allowed CPU range. High retains the
driver's adaptive governor with a higher floor and performance EPP. Both restore
the advertised CPU/uncore upper limits. The 2 GHz/1.2 GHz uncore floors are
explicit policy choices within both machines' reported ranges, not measured
optimal frequencies. C-states and firmware thermal protection remain enabled.

Intel GPU performance requests the advertised maximum as both minimum and
maximum active frequency; high uses the driver's efficient minimum. RC6 remains
enabled. Lower RPS thresholds request earlier increases and later decreases
under software RPS. Balanced/silent use the measured baseline 95%/85% thresholds.
The backend offers the paired thresholds only when both per-GT attributes
exist; unsupported or rejected explicit requests fail before success is reported.
Hardware/firmware may still limit actual clocks. Intel
GPU `efficient` resolves to the driver's efficient frequency when available.
The Flex managed, Electron and Wayland launch defaults select Intel acceleration.

The new `PLATFORM_PROFILE`, `GPU_RPS_UP_THRESHOLD_PCT` and
`GPU_RPS_DOWN_THRESHOLD_PCT` fields are present at all four levels in **all ten**
host profiles. Other hardware profiles use `keep` for them. Firmware selection
uses the single advertised per-driver class device, with a device/file identity
bound to its recovery entry. A replaced selector is rejected before a write.
No fallback writes the aggregate `/sys/firmware/acpi/platform_profile` file.
Multiple handlers or an unrestorable custom state are unavailable. Firmware
performance requires explicit power-increase permission and thermal coverage.

## P520 capability requests

These requests are installed only when NVIDIA tuning is enabled and the
existing installer detects the selected NVIDIA class and hardware. Other
installs receive no NVIDIA policy, lease units or application dependencies.

The performance profile requests the advertised maximum NVML power limit.
Performance and high request the maximum supported memory frequency together
with the highest graphics frequency advertised **for that memory frequency**,
and persistence mode 1. No independent maxima are combined into an invented
clock pair.

`supported-max` and `supported-1` mean: skip the request and report it when the
backend did not discover that control. An exported setter returning NVML
`NOT_SUPPORTED` can also be skipped if every journaled control is queryable and
unchanged across that attempt. This allows unsupported persistence or power
setters to leave working clock selection available. For a discovered control
these requests resolve through the maximum/choice handling described below.
Missing bounds, invalid explicit choices, permission failures, uncertain driver
outcomes and recovery failures remain errors.
Above-default power still requires explicit policy permission and complete
readable temperature coverage. A runtime failure does not silently claim the
requested setting was applied.

The supplied P520 advertises `3004,1531` MHz as a valid memory/graphics pair,
above its default `3004,1303` pair. Its 61 offset snapshots report only zero
ranges. Its current-power-limit getter is unsupported despite numeric limit
metadata, so those numbers are not an available power-control range. This policy
requests the advertised pair and persistence, without inventing positive offsets
or using that unusable power metadata. Getter success is not setter acceptance.
The user's separate `nvidia-smi -q -d SUPPORTED_CLOCKS` capture from driver
580.142 / CUDA 13.0 confirms the same maximum: 3004 MHz memory and 1531 MHz
graphics. Both Performance and High use `supported-max`; an absent control
may be skipped, while an available control resolves to that highest valid pair.
Maximum means the highest working advertised pair. Unavailable memory-level
tables are omitted. Runtime selection walks memory levels from highest to
lowest and graphics clocks from highest to lowest within each level. Explicit
NVML invalid/unsupported-pair replies permit the next candidate only when
clock and observable companion readbacks remain unchanged. Selection stops at
the first working pair and reports that actual pair. If none works, the
conditional request is skipped. Permission, device loss, changed state or
uncertain errors remain failures. The search has an eight-second retry budget
within the existing worker deadline and at most 4096 advertised candidates.
Restoration always requests the original pair exactly; it never substitutes a
lower recovery value.

Pascal does not use the Volta/Ampere clock-lock paths. Numeric offsets remain
`keep`, and CPU RAPL power/windows, voltage and raw firmware limits remain
unchanged. The notes in `todo/tuning/` are planning material; example power
figures are not proof of this board's cooling or firmware limits. Neither
profile enables positive clock offsets or bypasses driver/firmware protections.

## Ownership, restoration and verification

Automatic startup uses the existing policy handover before applying hardware
requests, and previous hardware values are journaled for restoration. Intel
installs use the custom Power Profiles API described below; the stock daemon
does not run alongside the custom worker. Stop, thermal conflict and recovery
continue through the same owner and journal. Thermald and firmware thermal
controls are retained. Other host profiles retain their existing conservative
tuning values and do not enable automatic tuning by default.

Firmware selection runs before CPU/GT/uncore writes. Its affected controls are
snapshotted before mutation. Recovery retains the complete firmware domain after
any partial failure and yields it when another owner changes a member. Dynamic
RAPL caps remain under firmware/thermald unless explicitly requested; the
baseline's changing P15s MMIO cap is not copied into an invented fixed limit.

Application drop-ins now order startup after their tuning targets. Lease
services send systemd readiness only after the broker's reconciliation reply;
their status names the actual applied profile, including an explicit manual
override. Tuning faults fail the lease. Applications retain `Wants`/`Upholds`
dependencies, so an unavailable tuning service does not prevent native launches
or give tuning stop/reset authority over applications. The existing 360-second
control deadline is covered by a 370-second service startup budget. Ordinary
successful transitions complete when the broker replies; the budget is a
failure bound, not an added startup sleep.

The new fixtures in `test_hardware_tuning_profiles_20261024.py` cover selector
replacement, paired RPS ordering, firmware side effects, partial recovery,
external ownership, thermal coverage and reconciliation-before-readiness.
They have not been executed for this working tree. Follow
[`docs/test-isolation.md`](../test-isolation.md) before running them. See the
[current source review](../validation/failures-hardware-20261024.md) for evidence
and remaining acceptance gates, and [IOCost](IOCOST.md) for storage quality.

## Power Profiles D-Bus integration

When the existing Intel hardware and policy gates install custom tuning, the
installer also publishes an administrator drop-in at
`/etc/systemd/system/power-profiles-daemon.service.d/50-hardware-tuning.conf`.
The packaged unit remains under `/usr/lib/systemd/system/`. The drop-in clears
the vendor executable, capabilities and state directory, runs the custom API
as the configured desktop account, disables the vendor private user namespace
and IPC removal, and restricts the adapter to Unix sockets. Package updates
normally preserve the local drop-in and continue supplying the base unit.
Changes to the vendor unit still require compatibility review.

Both `org.freedesktop.UPower.PowerProfiles` and legacy
`net.hadess.PowerProfiles` activate that service. The adapter sends mutations
to the existing authenticated hardware tuning broker; it cannot write hardware
or manage services. The broker checks the active configured local seat and
uses the existing fixed worker, policy ownership locks and recovery journal.
The custom provider does not mask, stop or start the public API service while
switching hardware profiles.

| Public profile | Custom policy applied to installed vendors |
| --- | --- |
| `power-saver` | `silent` |
| `balanced` | `balanced` |
| `performance` | `performance` |

The custom `high` profile remains available in the tuning menu. When it is
applied to Intel, the public API reports `performance`. Public profile selection
sets the baseline for every installed custom vendor and cancels public holds.
Automatic application leases continue to use the existing arbitration.

Public `HoldProfile` requests use broker socket leases. Power-saver holds win
over performance holds. Closing the caller's D-Bus connection releases its
holds; adapter or broker termination also releases the sockets. Manual changes
cancel holds and send `ProfileReleased`. Holds are not persisted across boots.
The adapter periodically refreshes read-only status and never retries an
uncertain mutation. Queue waiting, socket connection and response streaming
share an absolute deadline. A D-Bus client's own shorter timeout can still
expire before a hardware operation finishes; inspect broker status before
issuing another mutation.

Stop, Reset, an inactive seat or a thermal refusal restore journaled controls.
The API remains available after a tuning Stop/Reset and reports `balanced` for
the restored baseline, plus a degraded reason when recovery or a fault is
pending. Thermal limits are not bypassed. `BatteryAware` is always true because
the broker retains its AC/battery selection; disabling it is unsupported.
Optional stock PPD actions are not advertised.

The existing offline desktop enablement starts the packaged service with the
drop-in at boot. The persistent custom autostart preference and root broker
recovery remain separate from D-Bus API availability. NVIDIA-only installs and
installs without custom Intel tuning retain their existing stock PPD behavior.
The installer changes describe fresh target staging; they do not migrate a
previously installed machine's masks or administrator unit overrides.

Source and serialization evidence is recorded in
[the October 24 integration report](../validation/hardware-power-profiles-20261024.md).

Persistence is enabled before other requested GPU writes and disabled only
after clock/Auto Boost restoration. If an earlier same-GPU restore fails,
recovery retains persistence and its journal entry for the next attempt. NVIDIA requires
persistence for modifying Auto Boost; see the
[NVML command contract](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceCommands.html).

The isolated fixtures cover paired policy generation, conditional capability
absence, present-control errors, power permission/temperature checks, exact
restoration, maximum clock-pair selection, AC baseline arbitration, persistence
ordering and an injected Auto Boost restoration failure. Any execution must
follow `docs/test-isolation.md`. Source parsing and payload
serialization do not establish live hardware acceptance. Actual frequency,
temperature, sustained throughput and driver support still require measurements
on each intended machine.
