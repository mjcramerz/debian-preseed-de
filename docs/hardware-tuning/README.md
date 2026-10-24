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
| Performance CPU minimum percentage | 35 | 30 |
| High CPU minimum percentage | 20 | 20 |
| Performance/high EPP and EPB | performance / 0 | performance / 0 |
| Performance/high CPU maximum percentage | 100 | 100 |
| Performance/high turbo and HWP dynamic boost | Enabled when supported | Enabled when supported |
| CPU thermal interlock | 88 C | 85 C |
| GPU requests | Driver-advertised NVML controls | Driver-advertised Intel GPU maximum/boost |
| GPU thermal interlock | 85 C | Uses Intel backend sensor coverage |

The performance AC baseline survives application leases requesting high or
balanced. Manual selection retains precedence. An inactive desktop, pause or
vendor fault still prevents automatic writes. If a laptop reports battery power
or its AC state is unknown, its idle selection remains silent; existing
application lease arbitration remains in effect on battery.

The adaptive Intel governor resolves through the backend's available driver
choices. EPP requests guide HWP; the configured percentages are requests within
kernel bounds, not fixed clock rates or measured performance guarantees. Intel
GPU `efficient` resolves to the driver's efficient frequency when available.
The Flex managed, Electron and Wayland launch defaults select Intel acceleration.

## P520 capability requests

The performance profile requests the advertised maximum NVML power limit.
Performance and high request the maximum supported memory frequency together
with the highest graphics frequency advertised **for that memory frequency**,
and persistence mode 1. No independent maxima are combined into an invented
clock pair.

`supported-max` and `supported-1` mean: skip the request and report it when the
backend did not discover that control. For a discovered control they resolve
through the normal maximum/choice handling. Missing bounds, invalid choices,
permission failures, driver rejection and recovery failures remain errors.
Above-default power still requires explicit policy permission and complete
readable temperature coverage. A runtime failure does not silently claim the
requested setting was applied.

Pascal does not use the Volta/Ampere clock-lock paths. Numeric offsets remain
`keep`, and CPU RAPL power/windows, uncore, voltage and firmware limits remain
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
