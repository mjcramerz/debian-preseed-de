# October 24 failure review and hardware tuning

## Scope and execution boundary

The requested order is (1) the three supplied files under `todo/failures/`,
then (2) hardware tuning from the supplied Flex and P15s measurements. The
working tree was clean at the start on `mcr/main`, revision
`c624a65567a65476d79abf939ad7384dad8a0c69`.

This review reads supplied logs and source as data. No host services, devices,
package state, security policy or networking are queried or changed. No tests,
native syntax checks or policy validators have run. The user's subsequent
instruction permanently prohibits disposable VMs, containers and other
disposable execution environments. `AGENTS.override.md` and
`docs/test-isolation.md` now record that policy. Verification remains static;
no environment will be requested or provisioned. The audit file named
`debian-preseed-de-audit.md` in repository guidance is absent from this checkout.
Its historical acceptance findings cannot be asserted for this revision.

The supplied package report records systemd `262-1` and kernel
`7.2.12-x64v3-xanmod1`; the failure journal records Tailscale
`v1.104.2-tc3430f0d2-g598b63867` / Go `1.27.3`. These are supplied target
observations, not development-host package queries. The checked-in APT
inventory lists Forky's wpasupplicant `2:2.11-4` and libnl `3.12.0-2+b1`;
the journal does not establish the installed wpasupplicant/libnl versions.

## Objective 1: complete failure-log disposition

`todo/failures/netkit` duplicates the single 409 occurrence in the journal.
`todo/failures/stuff` repeats it and the Labwc/Wi-Fi messages. The journal spans
two boots, a desktop login, USB input hotplug, and a requested reboot.

| Supplied diagnostic | Evidence and disposition |
| --- | --- |
| Tailscale lite-map HTTP 409, superseded by another update | Journal line 1076 is followed immediately by a new map, `Starting -> Running` at line 1100, warming-up health `ok` at line 1103, bootstrap completion at line 1104, and route publication at line 1107. The server rejected an obsolete request; this is not evidence of two local daemons or a broken netkit link. Preserve the native client's retry/backoff, identity and health reporting. No daemon restart, reauthentication, route change or error suppression is justified. |
| Tailscale `PollNetMap: unexpected EOF` | Lines 1374–1376 show reconnection through the native 443 fallback and a new dial plan in the same second. Preserve that fallback and diagnostic. The journal contains no persistent control-plane outage. |
| Tailscale initially stopped/starting | Lines 1022 and 1049 are intermediate initial-enrollment states, cleared at lines 1050 and 1103. The second boot also clears warming-up. These are not failed systemd units. |
| `netfilter=off; configure iptables yourself` | The image intentionally owns packet filtering through nftables; netkit also installs its private namespace transport policy. Enabling a second packet-policy owner or installing iptables would change that contract. The native CLI warning remains informative. |
| wpa_supplicant `send_event_marker failed: Source based routing not supported` | At lines 1736–1750 NetworkManager deliberately releases Wi-Fi during reboot, disconnect reason 3 is locally generated, and both services exit successfully. WPA connectivity succeeded at lines 934 and 2714. The packaged source has a success-path diagnostic bug, explained below. Add a system-service journal filter for exactly this one complete false message. This is a logging correction, not a routing repair. |
| Labwc cannot find `/usr/bin/Xwayland`, then continues without | Lines 1273–1274 and 2939–2940 refer to the outer compositor. The user's explicit invariant forbids modifying existing Xwayland implementation/configuration and permits it privately only for Zoom and Discord. No Xwayland files, launch arguments, eligibility or AppArmor policy are changed. The outer-compositor diagnostic remains. Private-app launch/shutdown acceptance remains unexecuted. |
| seatd cannot revoke evdev, `No such device` | Four messages at lines 1398–1401 follow hotplug of a composite USB keyboard/mouse at lines 1390–1395. This is consistent with removal before revoke; the supplied log has no seatd crash, restart or continued input failure. Do not broaden device privileges or hide other revoke failures. Native unplug/replug acceptance remains open. |
| BlueZ missing controller `identity` file | Line 345 occurs on the first boot; the second boot has no corresponding diagnostic. BlueZ owns privacy identity creation. Do not manufacture cryptographic controller keys or disable privacy. Bluetooth pairing/identity persistence is not proven by this journal. |
| KSecretD translation/QWizard warnings | Lines 1328 and 1359 are packaged UI diagnostics during first wallet setup. The credential publisher completes successfully at line 1373. No supplied credential-publication failure is shown; wallet UI acceptance is still needed. No binary patch, compilation or blanket Qt warning suppression. |
| Crystal Dock LayerShellQt deprecation | Lines 1355 and 3024 are a packaged QML API deprecation; both docks start. Updating its compiled/resource code requires a packaged upstream fix. Do not compile software or suppress all Qt warnings. |
| Launcher synchronization `skipped_missing=1 missing=code` | Lines 1351 and 3019 explicitly skip an absent optional application, with `skipped_invalid=0` and successful unit completion. Do not install an unrequested editor or create a launcher to a missing executable. |
| Netavark exits after 30 seconds of inactivity | Lines 1173 and 2851 describe its idle service lifetime, not an operation timeout. No failed network operation is recorded. |
| XFS healer `Only logging errors per autofsck directive` | Eight startup messages state the configured reporting policy. They do not report corrupt filesystems or failed repair. No filesystem mutation is justified. |
| AppArmor skips absent `signal-desktop` | Lines 459 and 2205 report an optional executable absent from the installation. No AppArmor denial is present in the supplied journal. Do not activate a profile for nonexistent code. |

Ordinary SIGTERM handling, successful unit deactivation, conditional unit skips,
and the hardware watchdog announcement during the requested reboot are normal
lifecycle events. No failed systemd unit, traceback, denied operation, crash or
shutdown timeout appears in the supplied journal. This does not prove absence
of failures outside the captured interval.

### Wi-Fi source trace and narrow workaround

The existing installation path is
`scripts/late/{btrfs-family,f2fs-family}.sh` ->
`install_target_wpa_supplicant_runtime_policy()` in `scripts/late/core.sh` ->
`/etc/systemd/system/wpa_supplicant.service.d/override.conf` (0644). The existing
installation boundary checks the managed config and delegate before activation.
The D-Bus daemon retains its current capabilities and radio access. This change
adds no executable, privilege, AppArmor exception or command-line flag.

In Debian's [wpa 2:2.11-4 source](https://sources.debian.org/src/wpa/2%3A2.11-4/src/drivers/driver_nl80211.c/#L455),
`send_event_marker()` stores the return from `nl_send_auto_complete`, checks for
a negative result, obtains the sequence number on success, then incorrectly
checks any nonzero result before formatting an error. The
[libnl 3.12 send implementation](https://github.com/thom311/libnl/blob/libnl3_12_0/lib/nl.c)
returns a positive byte count on success. Its
[error formatter](https://github.com/thom311/libnl/blob/libnl3_12_0/lib/error.c)
takes the absolute value, so the count can become an unrelated error string.
The generic-netlink marker is 28 bytes; libnl's error 28 is the reported
source-routing string. This path does not attempt to install a source route.

`LogFilterPatterns` is supported for system services by
[systemd 262](https://www.freedesktop.org/software/systemd/man/262/systemd.exec.html#LogFilterPatterns=).
Its [v262 source reader](https://github.com/systemd/systemd/blob/v262/src/core/load-fragment.c#L6144)
uses the complete right-hand value as one pattern, preserving its spaces.
The filter is anchored at both ends and names only that diagnostic. Actual
authentication, permission, allocation, link and other netlink failures remain
visible. This workaround does not fix the packaged C source. Confirm the
installed versions and native journal behavior in an isolated Forky target.

For Tailscale, inspect the matching
[v1.104.2 update routine](https://github.com/tailscale/tailscale/blob/v1.104.2/control/controlclient/auto.go)
and [HTTP/map handling](https://github.com/tailscale/tailscale/blob/v1.104.2/control/controlclient/direct.go):
non-success responses are errors handled by its own retry loop. A local sleep,
duplicate retry loop, forced transport setting or journal filter cannot fix a
server-side superseded request. The healthy follow-up in the supplied journal
is the evidence for recovery here; it is not a new live integration result.

## Objective 2: policies from an untuned baseline

The user explicitly confirms that **none of the proposed tuning had been
applied when these reports were collected**. The observations establish
capabilities, limits and reference throughput. They do not show a failure of an
already deployed policy or prove the performance/stability of this change.

### Baseline evidence

| Evidence | Observation used for this change |
| --- | --- |
| Flex Core i3-1115G4 | Active Intel P-state, 400 MHz–4.1 GHz advertised CPU range, 400 MHz–3.5 GHz uncore, one `ideapad-laptop` firmware profile handler, Intel GPU RPn/RP1/RP0 100/400/1250 MHz, writable RPS thresholds 95/85, RC6 enabled. |
| P15s Core i7-10610U | Active Intel P-state, 400 MHz–4.9 GHz advertised CPU range, 400 MHz–4.6 GHz uncore, one `thinkpad-acpi-profile` handler, Intel GPU RPn/RP1/RP0 300/300/1150 MHz. |
| CPU throughput | Flex median sysbench throughput is 1274.51 events/s with one worker and 2645.99 with four. The reports describe a baseline; no tuned comparison was run. |
| RAM throughput | Scalar 1 GiB-working-set medians are 17735.23/11467.03 MiB/s single-worker read/write, and 31690.41/9095.57 with four workers. These are not STREAM results and do not justify unrelated VM or kernel policy changes. |
| Thermal/RAPL | Nonzero cumulative CPU throttle counters do not increase during the supplied samples. P15s MMIO PL1 changes from 12 W to 5 W; reported MSR values and advertised limits disagree. Flex lacks complete advertised RAPL bounds. Preserve firmware/thermald control rather than invent fixed power limits. |
| Quadro P520 | Pascal, 2 GiB; valid maximum application-clock pair 3004 MHz memory / 1531 MHz graphics versus default 3004/1303. All 61 offset snapshots expose zero-only ranges. The current power-limit getter and Auto Boost getter are unsupported; numeric power metadata alone does not make a writable control. Idle P8 and idle PCIe Gen1 are not loaded-performance measurements. |

Companion SHA-256 values in the Flex/P15s JSON agree with all five companion
files (two Flex, three P15s). The CPU/RAM/storage `SHA256SUMS` manifests agree
with all 127/115/148 listed files respectively. These checks establish byte
consistency of the supplied evidence, not hardware calibration acceptance.

### Requested levels and integration

The following policy applies to both Flex single/duo and P15s single/duo;
other host policies retain their existing values and use `keep` for new knobs.

| Control | Performance | High | Balanced / silent |
| --- | --- | --- | --- |
| Firmware profile | performance | performance | balanced / low-power |
| CPU governor | performance | adaptive Intel P-state | Existing adaptive policy |
| Minimum CPU performance | 100% | Flex 35%, P15s 40% | Existing values |
| EPP / EPB | performance / 0 | performance / 0 | Existing values |
| CPU/uncore upper limits | Advertised maximum | Advertised maximum | Existing values |
| Uncore floor | 2 GHz | 1.2 GHz | keep |
| Intel GPU active minimum | Advertised maximum | Advertised efficient frequency | Existing values |
| Intel GPU RPS up/down | 80% / 60% | 90% / 75% | Baseline 95% / 85% |

Turbo/HWP boost requests, CPU thermal interlocks (85 C Flex, 88 C P15s), the
P520's 85 C interlock, RC6, C-states and firmware protection remain in place.
The uncore floors and RPS thresholds are explicit policy choices within the
exposed ranges, not measured optima. Actual clocks remain subject to package
power, workload and firmware limits. A higher CPU/iGPU floor may trade package
power against sustained throughput; native loaded comparisons are required.

All ten profiles have exactly **155 matching `HARDWARE_*` fields**, including
the three new knobs at all four levels: `PLATFORM_PROFILE`,
`GPU_RPS_UP_THRESHOLD_PCT`, `GPU_RPS_DOWN_THRESHOLD_PCT`. Their names cover every
setting in both backend dictionaries (23 Intel, 9 NVIDIA). Flex and P15s
single/duo tuning values agree. Pre-existing filesystem/layout and unrelated
profile-field differences are outside this change.

The existing installer consumes the backend setting dictionaries, validates
all policy candidates, then renders the root-owned vendor JSON, installed user
units and all five application drop-ins. No new renderer token or installation
delegate is needed. Firmware writes are confined by the Intel AppArmor
abstraction and the broker's existing `/sys/devices` writable service boundary.

Firmware discovery selects a single per-driver class device, binds its kernel
directory/file identity and driver name into its recovery identifier, and
rechecks that identity before I/O. Multiple handlers, a custom state or selector
replacement is unavailable; there is no aggregate-file fallback. Performance
requires power-increase permission and readable thermal coverage. The firmware
selector runs before explicit CPU/GT/uncore requests. The complete affected
domain is snapshotted before mutation, retained after partial recovery, and
yielded when another owner changes a member. Missing/replaced selectors prevent
dependent restoration from writing an uncertain firmware domain.

The paired RPS thresholds use a separate pair identity from GT frequencies and
require `down < up`. The existing transaction ordering raises a pair's upper
limit before its lower limit when necessary and verifies final readback.

Application units now have `After=` ordering on their tuning targets. All eight
vendor/profile lease services use `Type=notify`, `NotifyAccess=main`, and a
370-second startup budget covering the existing 360-second control deadline.
Readiness follows the broker's reconciliation reply and reports the actual
applied profile, including manual overrides. Faults do not produce readiness.
The client adds only a write rule for the owning user's systemd notify socket.
Applications retain `Wants`/`Upholds` rather than failure/stop propagation from
tuning. Native launches remain available when tuning fails. Already active
targets rely on the existing broker arbitration and monitoring.

The P15s performance/high policies already request conditional maximum valid
NVML application clocks and persistence mode. Those source policies had **not**
been applied in the supplied baseline. The new startup ordering makes their
reconciliation precede application startup. The existing backend chooses the
highest graphics frequency for the selected memory frequency, enables
persistence first, and retains recovery on failures. It does not substitute
Volta-only locks for Pascal, assume offset support, or accept unsupported power
getter metadata. Setter permission/driver acceptance remains a native gate.
See the [NVIDIA NVML command contract](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceCommands.html).

The user's subsequent supported-clock capture identifies driver 580.142 /
CUDA 13.0 and confirms the same 3004 MHz memory / 1531 MHz graphics maximum.
Per the user's clarification, `supported-max` remains conditional: skip an
unavailable control; request that maximum when available. NVIDIA staging and
application dependencies remain gated by its enable flag, selected class and
detected hardware. Per the user's further clarification, unavailable memory
tables fall back to the highest available lower level. Runtime maximum selection
also tries advertised memory/graphics pairs in descending order after an
explicit invalid/unsupported rejection with unchanged clock/companion readback.
It records the actual selected pair and skips an exhausted conditional request.
Permission, lost-device, readback mismatch and uncertain outcomes do not trigger
another mutation. Search is bounded to 4096 candidates and an eight-second retry
budget within the existing worker deadline. Exact restoration has no fallback.
The error adapter preserves numeric NVML status using the
[vendor's return-code definitions](https://github.com/NVIDIA/go-nvml/blob/main/pkg/nvml/nvml.h).
Only explicit invalid-argument/not-supported setter replies (2/3), followed by
unchanged readback, advance to another pair. A wholly skipped or already-working
unchanged clock selection is removed from recovery ownership, avoiding an
unsupported reset call for a clock that was never changed.
An additional recheck identified exported persistence/power setters that can
return `NOT_SUPPORTED` despite a working getter. NVML status 3 now has an explicit
unsupported-operation type while preserving its function/status fields. A
`supported-1` or `supported-max` scalar request skips that reply only after all
journaled controls are proven queryable and unchanged across the attempt.
This prevents unsupported persistence from aborting the later maximum-clock
search. Explicit requests, status 2/4/15/999, unreadable state and changed state
remain errors. Unchanged skipped controls are removed from recovery ownership;
previous baselines changed by another owned write remain journaled.
Three additional unexecuted fixtures in the existing test file
check the exact P520 pair in both P15s profiles at Performance/High, and the
unsupported-control skip path using the actual profile policies, plus that
highest-table failure with the next available memory level.

### IOCost values are not accepted by the supplied export

The supplied storage model explicitly says `needs_review`, `applied=false`.
All 27 fio trials complete, but sequential-read trials span approximately
3.240/2.350/2.155 GB/s and fail its repeatability gate. The candidate QoS is only
`rpct=0 wpct=0`, explicitly an internal-saturation policy, without accepted
latency or controller min/max values. No newly accepted complete model/QoS
export is present. The existing September 23 profile solutions remain in place;
no rejected coefficients or invented QoS values are published as accepted.
The candidate coefficients and the missing acceptance evidence are documented
in [IOCost](../hardware-tuning/IOCOST.md). Incorporating replacement accepted
quality values remains open pending that evidence.

## Verification evidence and remaining gates

Performed as static source/data inspection only:

- `git diff --check`: exit 0.
- `/usr/bin/python3 -I -B` inline standard-library data inspection:
  `ast.parse` of `intel.py`, `nvidia.py`, `common.py`, `engine.py`, `client.py`,
  `test_hardware_tuning_20260916.py` and
  `test_hardware_tuning_profiles_20261024.py`; no imports or execution of those
  files. All seven parse.
- Literal profile assignment inspection: no duplicate/invalid tuning fields;
  matching 155-key sets in all ten profiles, complete backend setting coverage,
  identical Flex/P15s single/duo tuning.
- Bounded SHA-256 comparison of supplied evidence as described above.

The new fixture file contains **30 unexecuted test methods** covering firmware
choice/permission, replacement identity, multiple/custom handlers, paired RPS,
side effects, external changes, partial/missing-selector recovery, thermal
coverage, descending NVIDIA selection, unsupported skips, deadlines, uncertain
failures, exact recovery, conditional unsupported persistence/power replies,
error classification, changed-state rejection and lease readiness/failure. Existing profile/install
expectations are updated. No test runner, isolation probe, fixture import, AppArmor parser,
systemd verifier, native syntax command or host helper was executed.

The following runtime behavior remains unverified. Tests and native checks are
unexecuted under the user's permanent prohibition on disposable environments
and the existing prohibition on host execution. These limits are not requests
to provision or use an environment:

- All authored fixtures, including firmware recovery, descending clock
  selection, conditional unsupported setters and lease readiness.
- Native systemd 262 ordering/readiness, journal filtering, Wi-Fi
  association/shutdown and installed package versions.
- Tailscale enrollment, control reconnect, routes/DNS and clean stop.
- AppArmor parse/load and journal recovery/failure injection, including
  selector replacement and concurrent external policy ownership.
- Flex/P15s hardware readback, loaded CPU/RAM/GPU throughput,
  sustained temperatures/power/throttling, application leases, manual overrides,
  thermal refusal and exact restoration. The baseline is not a tuned result.
- Native application and private Zoom/Discord launch/shutdown regressions.

Accepted replacement Flex IOCost model/QoS data for the identified drive and
firmware remains missing from the supplied artifacts. This is a data requirement;
no local calibration or benchmark is authorized.

## Generation receipt and source identity

The reviewed Makefile invokes only `tools/build.py` and its bounded publication
helper for `make build PYTHON=/usr/bin/python3`. The final invocation exits 0:
`built 1838 payload files`. No installer module, test, validator, shell snippet,
policy parser or management helper is executed by this serialization path.

A separate standard-library data comparison confirms every archived member
matches its current source bytes and manifest digest, the complete member set
matches the serialization inputs, and canonical mode/uid/gid/mtime are
0644/0/0/0. There are 1838 files and 34,942,520 expanded bytes. Preseed's archive,
manifest and bootstrap-source pins agree. No archive member is extracted or
executed. Together with base revision `c624a65567a65476d79abf939ad7384dad8a0c69`,
the manifest digest identifies the uncommitted payload-input snapshot; fixtures
are excluded from the payload and have separate fingerprints.

| Artifact / fixture | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `349812432a25ded242800b3dff275de7c03f5f5ca1558e6958d356d4c0e362ad` |
| `d-i/forky/payload.manifest` | `8507160a1a49c36d22782b9593abcb1be125d1112e7ad4fdfb05eaf37c9700c8` |
| `d-i/forky/preseed.cfg` | `a83ead45ca553faade2bd127dcef1c61efe5f56e4436e56080ecef3b1296da14` |
| `d-i/forky/tests/test_hardware_tuning_20260916.py` | `cc0c0614f15e148987dcdcd0ba8b181377ca1125d847e8bcd87100887822d7bd` |
| `d-i/forky/tests/test_hardware_tuning_profiles_20261024.py` | `34b4936edfc1f9b8ed5a224731b671eac1e2d3299ba9f246ae8d42eb36c78528` |
| `inventory.json` | `101d9a666954a76d7a11aa0dca758b602ddfdef3b9a372ed6264a196ccfdfbe0` |
| `inventory-apt.json` | `95acaa4453f67b67a81f82e74208ecce54fe8c146170e80bbfcde50f4c59291e` |

The final `make inventory PYTHON=/usr/bin/python3` invocation exits 0. It scans
1838 archive members (1808 text files, 353 relevant files), acquires 97 public
APT indexes and retains 21,359 package candidates with zero unavailable metadata
requests. Both JSON payload pins match the final archive; `inventory.json`'s
APT-metadata hash matches the exact `inventory-apt.json` bytes. Its metadata
trust remains HTTPS plus Release SHA-256 consistency, without OpenPGP signature
verification in this inventory acquisition. Target installer signing/keyring
policy is unchanged. No host package database or package manager was used.
The three serialized products and the two inventories are current for this
payload snapshot.

An earlier inventory invocation lost its tool handle during a user update and
left `.inventory-apt-z2dvs8fj/` (54 public-metadata scratch files, 116,396,859
bytes). The final generation completed successfully. Source inspection confirms
that acquisition threads are joined and the temporary context exits before the
repository-directory generation lock is released. Cleanup acquired that same
exclusive writer lock, verified the scratch directory's observed device/inode,
owner, private mode and each regular member's identity, then removed only that
inactive task-owned workspace. No recovery backups or unrelated files were
removed. No test or validation runner was interrupted; none was started.

Hashes establish byte consistency. Serialization is not runtime acceptance.
No installed-target changes, commit, push or deployment have been performed.

## Changed paths

```text
AGENTS.override.md
d-i/forky/hooks/target/etc/apparmor.d/abstractions/hardware-tuning-intel
d-i/forky/hooks/target/etc/apparmor.d/hardware-tuning
d-i/forky/hooks/target/etc/systemd/system/wpa_supplicant.service.d/override.conf
d-i/forky/hooks/target/etc/systemd/user/hardware-tuning-intel-balanced.service
d-i/forky/hooks/target/etc/systemd/user/hardware-tuning-intel-high.service
d-i/forky/hooks/target/etc/systemd/user/hardware-tuning-intel-performance.service
d-i/forky/hooks/target/etc/systemd/user/hardware-tuning-intel-silent.service
d-i/forky/hooks/target/etc/systemd/user/hardware-tuning-nvidia-balanced.service
d-i/forky/hooks/target/etc/systemd/user/hardware-tuning-nvidia-high.service
d-i/forky/hooks/target/etc/systemd/user/hardware-tuning-nvidia-performance.service
d-i/forky/hooks/target/etc/systemd/user/hardware-tuning-nvidia-silent.service
d-i/forky/hooks/target/etc/systemd/user/labwc-devops-.service.d/85-hardware-tuning.conf.tmpl
d-i/forky/hooks/target/etc/systemd/user/labwc-electron-.service.d/85-hardware-tuning.conf.tmpl
d-i/forky/hooks/target/etc/systemd/user/labwc-native-.service.d/85-hardware-tuning.conf.tmpl
d-i/forky/hooks/target/etc/systemd/user/labwc-wayland-.service.d/85-hardware-tuning.conf.tmpl
d-i/forky/hooks/target/etc/systemd/user/llama-server.service.d/85-hardware-tuning.conf.tmpl
d-i/forky/hooks/target/usr/local/lib/hardware_tuning/client.py
d-i/forky/hooks/target/usr/local/lib/hardware_tuning/common.py
d-i/forky/hooks/target/usr/local/lib/hardware_tuning/engine.py
d-i/forky/hooks/target/usr/local/lib/hardware_tuning/intel.py
d-i/forky/hooks/target/usr/local/lib/hardware_tuning/nvidia.py
d-i/forky/hosts/profiles/btrfs-de-duo.env
d-i/forky/hosts/profiles/btrfs-de-flex-duo.env
d-i/forky/hosts/profiles/btrfs-de-flex.env
d-i/forky/hosts/profiles/btrfs-de-p15s-duo.env
d-i/forky/hosts/profiles/btrfs-de-p15s.env
d-i/forky/hosts/profiles/btrfs-de.env
d-i/forky/hosts/profiles/f2fs-de-hp14-duo.env
d-i/forky/hosts/profiles/f2fs-de-hp14.env
d-i/forky/hosts/profiles/f2fs-de-x360-duo.env
d-i/forky/hosts/profiles/f2fs-de-x360.env
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
d-i/forky/preseed.cfg
d-i/forky/tests/test_hardware_tuning_20260916.py
d-i/forky/tests/test_hardware_tuning_profiles_20261024.py
docs/hardware-tuning/README.md
docs/test-isolation.md
docs/hardware-tuning/IOCOST.md
docs/validation/failures-hardware-20261024.md
inventory-apt.json
inventory.json
```
