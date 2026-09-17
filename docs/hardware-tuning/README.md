# Gated Intel CPU/iGPU and NVIDIA GPU tuning

## Scope and installation

This change adds a separate, opt-in hardware policy controller. It does not replace the existing energy-profile menu, cgroup delegation, resource weights, launcher isolation, display configuration, driver installation, or power-management services. The served payload and generated preseed must be rebuilt together with `make build` after changing any installer profile.

Both `HARDWARE_INTEL_CPU_TUNING_ENABLE` and `HARDWARE_NVIDIA_GPU_TUNING_ENABLE` are `"true"` in `btrfs-de-main.env`, `btrfs-de-dual-main.env`, `btrfs-de-flex.env`, and `btrfs-de-dual-flex.env`. Both are `"false"` in the other nine profiles. Every profile carries the same initial tuning values; enablement is the only intended difference in this added configuration block.

Intel additionally requires a detected GenuineIntel CPU. NVIDIA additionally requires a selected `addon/nvidia` or `addon/nvidia-legacy` class and a detected NVIDIA display GPU. NVIDIA GPU detection, not a nonexistent requirement for an NVIDIA CPU, is used. Both flags are literal booleans; invalid values fail installation. The desktop role and Labwc must also be enabled by the existing installer policy.

A disabled or undetected vendor installs no vendor backend, vendor JSON, vendor target/lease service, or vendor AppArmor permissions. With neither vendor selected, no common tuning executable, service, socket, policy, or Waybar right-click hook is installed. The source files necessarily remain in the COMPLETE served repository so a different host can select the feature. This is a fresh-install mechanism, not an in-place uninstaller for previously installed assets.

**Enabling installation does not start tuning.** `HARDWARE_TUNING_AUTOSTART_ENABLE="false"` is the initial value in every profile. Automatic tuning is off until explicitly started; a single profile is also an explicit action. Enabling boot autostart affects subsequent boots, not the current automatic state.

## Audit-based choices

The supplied Flex audit reports an Intel i3-1115G4, 400000..4100000 kHz CPU limits and Tiger Lake Intel graphics; no NVIDIA display GPU was identified. The P15s audit reports an Intel i7-10610U, 400000..4900000 kHz CPU limits, Intel UHD graphics and a Quadro P520 (GP108GLM, PCI vendor/device 10de:1d34). These are inventory observations from the supplied archives, not performance benchmarks.

Evidence: `debugsys-flex.zip/20260916T211928Z-report-3925b3f9/evidence/` and `debugsys-p15s.zip/20260916T212228Z-report-70f722af/evidence/`. The audit's temporary missing delegation was not used to change any CPU, cpuset or I/O delegation policy. Runtime feature discovery, not a hostname or those particular clock numbers, determines each installed machine's controls.

The P520 must not be treated as a Volta/Ampere GPU. Driver support for power, offsets and legacy application clocks is individually queried; a P520 may expose some controls read-only or not at all. The implementation does not promise clock offsets merely because an NVML symbol exists.

## Waybar menu and command line

Right-click the existing battery/plugged icon. The installer changes only the rendered battery module's `on-click-right`; its `on-click` energy-profile command and other fields are preserved.

The first entry is **Set Single Tuning Profile**. Its submenu contains **Reset Profiles [All]**, followed by **Set Performance Profile**, **Set High Profile**, **Set Balanced Profile**, and **Set Silent Profile**, with `[Intel]` and/or `[Nvidia]` labels for the installed backends. A manual selection is independent for each vendor and overrides automatic selection for that vendor only.

The remaining main-menu entries are **Generate Hardware Tuning Report**, **Start Automatic Tuning**, **Stop Automatic Tuning**, **Enable Autostart Tuning at Boot**, **Disable Autostart Tuning at Boot**, and **Reset Hardware Tuning**.

`Reset Profiles [All]` clears both manual selections but leaves automatic tuning enabled when it already was enabled. `Stop Automatic Tuning` leaves explicit manual selections alone. `Reset Hardware Tuning` clears automatic/manual state, disables this manager's boot-autostart link and restores the controls it owns. It does not select balanced as a substitute for resetting. Unprivileged lease processes may remain while their applications are open, but cannot re-enable automatic tuning; this avoids terminating applications or racing systemd's Upholds dependencies.

The same bounded API is available from a terminal in the active local desktop session:

```sh
labwc-hardware-tuning status
labwc-hardware-tuning report
labwc-hardware-tuning auto-start
labwc-hardware-tuning auto-stop
labwc-hardware-tuning manual intel high
labwc-hardware-tuning manual nvidia performance
labwc-hardware-tuning profiles-reset
labwc-hardware-tuning boot-enable
labwc-hardware-tuning boot-disable
labwc-hardware-tuning reset
```

Use only the installed vendor names. Menu reports create both human-readable text and JSON under the passwd-defined `~/.local/state/hardware-tuning/` with directory mode 0700 and file mode 0600. The CLI `report` prints JSON. Generating a report does not apply a profile, but NVML inventory can briefly wake a suspended GPU.

## Automatic selection and application lifetimes

Selection order is manual override, otherwise the highest live automatic lease (`performance > high > balanced > silent`), otherwise the configured idle profile. Defaults are balanced on AC and silent on battery. The idle choice is a fallback, not a competing lease. `HARDWARE_TUNING_IDLE_AC` and `HARDWARE_TUNING_IDLE_BATTERY` can also be `"none"` to leave hardware untouched when no mapped workload is active.

The installer creates `intel-{performance,high,balanced,silent}.target` and/or equivalent `nvidia-*.target` user targets. Each requires a single unprivileged connection-lifetime lease service. Each lease service is `PartOf=` its vendor/profile target and the existing `labwc-session.target`. Targets have `StopWhenUnneeded=yes`.

Mapped application drop-ins have only `Wants=` and `Upholds=` towards those targets. Applications are deliberately NOT PartOf, BindsTo or Requires dependents of tuning targets: stopping/failing tuning must not kill a browser or terminal. A target remains needed while another mapped application still holds it. A dropped connection releases its lease; user services reconnect after broker failure. No browser processes are polled or discovered by command-line matching.

Required high-profile dash-prefix drop-ins:

```text
/etc/systemd/user/labwc-native-vivaldi-.service.d/85-hardware-tuning.conf
/etc/systemd/user/labwc-native-chromium-.service.d/85-hardware-tuning.conf
/etc/systemd/user/labwc-native-microsoft-.service.d/85-hardware-tuning.conf
/etc/systemd/user/labwc-electron-.service.d/85-hardware-tuning.conf
```

These are systemd's real dash-prefix directories, NOT directories containing a literal `*`. For example, the vivaldi prefix covers `labwc-native-vivaldi-stable-<instance>.service`.

DevOps receives performance through `labwc-devops-.service.d`. The existing `71-devops-de.sh` calls a foreground helper before its unchanged interactive-shell invocation. The helper creates a unique transient **sidecar**, bound by a kernel pidfd to the actual activation subshell (PPID plus process start time, never POSIX `$$` or an untrusted PID file). Exiting/toggling off that DevOps activation ends only its sidecar. A second terminal's sidecar keeps the performance target needed. The development shell is not moved into a new confinement domain, replaced, or killed by tuning. A sidecar-start failure leaves the shell usable and prints a warning.

Additional mappings: `llama-server.service` and Wayland OBS/Kdenlive/Blender use performance; Wayland MPV/Recoll use balanced; Firefox, Mullvad Browser and the existing native Code/ChatGPT/Obsidian/QoreDB/Postman/Sleek/Spotify/Filen/Discord/Ledger Live/Tutanota prefixes use high. The complete mapping is the `APPLICATIONS` dictionary in `scripts/desktop/hardware-tuning-config.py`. More-specific workload drop-ins can override ordinary systemd dependencies; inspect `systemctl --user show UNIT -p Wants -p Upholds` on the installed host.

## Tuning values and units

Source values use `HARDWARE_INTEL_CPU_TUNING_<PROFILE>_<SETTING>` or `HARDWARE_NVIDIA_GPU_TUNING_<PROFILE>_<SETTING>`, where PROFILE is PERFORMANCE, HIGH, BALANCED or SILENT. Runtime policies are root-owned 0600 JSON in `/etc/hardware-tuning/intel.json` and/or `nvidia.json`. Both contain all four profiles, portable `knobs`, and optional per-device `overrides` keyed by exact report identifiers.

`keep` means this manager does not change the control; it does not mean zero. `min` and `max` resolve only against known effective bounds. `default` is a driver-provided default, and Intel graphics `efficient` is its advertised RP1/RPe frequency. Numerical frequency values are kHz for CPUs/uncore and MHz for GPU controls. Intel RAPL power is micro-watts; NVIDIA power is milli-watts; time windows are micro-seconds. Offset values are signed MHz. NVIDIA application-clock pairs are `memory,graphics`; locked-clock pairs are `minimum,maximum`.

### Intel defaults

| Setting | Performance | High | Balanced | Silent |
|---|---|---|---|---|
| `CPU_GOVERNOR` | `adaptive` | `adaptive` | `adaptive` | `adaptive` |
| `CPU_EPP` | `performance` | `balance_performance` | `balance_power` | `power` |
| `CPU_EPB` | `0` | `4` | `6` | `15` |
| `CPU_MIN_PERF_PCT` | `keep` | `keep` | `keep` | `keep` |
| `CPU_MAX_PERF_PCT` | `100` | `100` | `85` | `55` |
| `CPU_NO_TURBO` | `0` | `0` | `0` | `1` |
| `CPU_HWP_DYNAMIC_BOOST` | `1` | `1` | `0` | `0` |
| `CPU_MIN_FREQ_KHZ` | `keep` | `keep` | `keep` | `keep` |
| `CPU_MAX_FREQ_KHZ` | `keep` | `keep` | `keep` | `keep` |
| `UNCORE_MIN_FREQ_KHZ` | `keep` | `keep` | `keep` | `keep` |
| `UNCORE_MAX_FREQ_KHZ` | `keep` | `keep` | `keep` | `keep` |
| `GPU_MIN_FREQ_MHZ` | `keep` | `keep` | `keep` | `keep` |
| `GPU_MAX_FREQ_MHZ` | `max` | `max` | `keep` | `efficient` |
| `GPU_BOOST_FREQ_MHZ` | `max` | `max` | `keep` | `efficient` |
| `RAPL_PL1_POWER_UW` | `keep` | `keep` | `keep` | `keep` |
| `RAPL_PL1_WINDOW_US` | `keep` | `keep` | `keep` | `keep` |
| `RAPL_PL2_POWER_UW` | `keep` | `keep` | `keep` | `keep` |
| `RAPL_PL2_WINDOW_US` | `keep` | `keep` | `keep` | `keep` |
| `RAPL_PL4_POWER_UW` | `keep` | `keep` | `keep` | `keep` |
| `RAPL_PL4_WINDOW_US` | `keep` | `keep` | `keep` | `keep` |

Active intel_pstate uses the powersave governor with EPP to retain hardware-managed frequency selection; `adaptive` resolves differently for passive Intel/acpi-cpufreq drivers. Unsupported portable defaults are reported and skipped. A customized request for an unsupported knob, unknown device override, unsupported enum, inverted pair, or performance-governor/nonperformance-EPP combination fails before writes. An explicitly configured value identical to a portable default remains indistinguishable from that default and retains the same optional behavior; use an exact device override to require a discovered control.

CPUFreq governors/EPP, per-CPU EPB, intel_pstate percentages/turbo/HWP, supported uncore domains, i915 legacy/per-GT frequencies and Xe tile/GT frequency interfaces are discovered. Graphics limits use advertised stock RPn..RP0 bounds. RAPL package PL1/PL2/PL4 constraints are discovered by constraint name; subdomains appear in the report and can use exact device overrides. PL4 generally has no time-window control: its source setting remains keep and the report marks it unavailable.

### NVIDIA defaults

| Setting | Performance | High | Balanced | Silent |
|---|---|---|---|---|
| `POWER_LIMIT_MW` | `default` | `default` | `keep` | `min` |
| `GPU_OFFSET_MHZ` | `keep` | `keep` | `keep` | `keep` |
| `MEMORY_OFFSET_MHZ` | `keep` | `keep` | `keep` | `keep` |
| `GPU_LOCK_MHZ` | `keep` | `keep` | `keep` | `keep` |
| `MEMORY_LOCK_MHZ` | `keep` | `keep` | `keep` | `keep` |
| `APPLICATION_CLOCKS_MHZ` | `keep` | `keep` | `keep` | `keep` |
| `PERSISTENCE_MODE` | `keep` | `keep` | `keep` | `keep` |
| `AUTO_BOOST` | `keep` | `keep` | `keep` | `keep` |
| `TARGET_TEMPERATURE_C` | `keep` | `keep` | `keep` | `keep` |

NVML is called directly with explicit ctypes signatures; no X11 display, Coolbits, nvidia-settings command shell, nvidia-smi parsing or firmware modification is involved. Device IDs are physical GPU UUIDs. The backend queries supported offsets by P-state when available and feature-probes older global VF-offset APIs otherwise. Current driver support, architecture and advertised clock tables gate locks and application clocks.

NVIDIA performance and high intentionally share stock default power unless the administrator supplies different supported values. These labels are lifecycle priorities, not a claim that a read-only laptop GPU can deliver two distinct overclocks. Clock locks are not offered for the P520 architecture. Runtime memory-lock changes on Hopper are excluded rather than installing a reboot/deferred-clock mutation.

## Explicit safety gates and missing hardware bounds

All defaults preserve firmware voltage, manual-fan and thermal-protection policy. There is no automatic stress-test/overclock search. Automatic tuning selects configured profiles; it does not experiment with unstable clocks.

`ALLOW_OVERCLOCK="false"` rejects positive GPU offsets. `ALLOW_POWER_INCREASE="false"` rejects limits above NVIDIA's driver default or the Intel pre-tuning baseline. Both can be explicitly enabled per vendor, but cannot widen known hardware bounds. Readable temperature coverage is required for these higher-risk changes; for NVIDIA, every enumerated GPU must have a valid sensor reading so one GPU cannot mask another GPU's missing sensor. Loss of that coverage or reaching the configured threshold causes restoration and a latched fault. Initial interlocks are 85 C for Intel and 80 C for NVIDIA; accepted configuration range is 50..95 C. Shutdown/slowdown thresholds and fan controls are never weakened. A configurable acoustic GPU target must be at or below the software interlock.

`EXCLUSIVE_CLOCK_CONTROL="false"` prevents use of NVIDIA lock APIs whose previous lock range is not queryable through the portable NVML interface. Enabling it is an explicit assertion that no other clock-lock owner exists. The report displays unknown, not a fabricated current lock range. Reset releases this manager's locks to driver-default clock behavior; it cannot reconstruct an unknown externally established lock range. Do not combine exclusive locks with another locking tool.

The Linux powercap interface makes RAPL minimum/maximum and window-bound attributes optional. A current value is not a maximum, a guessed TDP is not an advertised bound, and a firmware write lock is not bypassed. With missing bounds, RAPL values remain report-only/keep by default.

To use a RAPL constraint whose bounds are not fully exposed, the hardware owner must first verify the safe endpoints against that platform's specification, then explicitly set `HARDWARE_INTEL_CPU_TUNING_ALLOW_VERIFIED_BOUNDS="true"` and both `HARDWARE_INTEL_CPU_TUNING_RAPL_<PL1|PL2|PL4>_<POWER_UW|WINDOW_US>_VERIFIED_MIN/MAX`. All these fields ship as keep. No numeric RAPL endpoints are inferred from the audit. In runtime JSON the corresponding optional fields are `allow_verified_bounds` and `verified_bounds`, whose keys are named package RAPL settings and whose values contain positive integer `minimum` and `maximum`. Every known driver bound is intersected with, never widened by, these constraints. Reports distinguish administrator-supplied effective bounds from actual driver-advertised bounds. The driver may still reject or quantize a request.

Raw MSR/voltage mailbox writes, Intel multiplier unlocking, GPU voltage overrides, firmware flashing, manual fan control, PCI GPU reset, changing ECC/compute/MIG mode and deferred reboot clock settings are deliberately not exposed. There is no safe portable interface covering those operations across these machines. The report explains this limitation rather than inventing a current value or claiming an unsupported overclock was applied.

## Editing, reporting and recovery

First generate a report before enabling profiles. It includes telemetry, all discovered controls, current values, units, known/effective bounds, choices, configured and resolved requests for each profile, combined preflight results, unsupported settings, recovery records and limitations. Suggestions are bounded configuration requests, not measured performance or stability guarantees. No writes are used to test whether a read-only BIOS/driver control is writable.

Edit only the relevant root-owned JSON through your normal administrator mechanism, for example `sudoedit /etc/hardware-tuning/intel.json`. Preserve root ownership, mode 0600, strict JSON booleans and all profile keys. Do not source JSON or turn runtime files into shell scripts. Duplicate JSON keys, nonfinite numbers, unknown fields, symlinks, mutable ancestors and oversized inputs are rejected. Choose a per-device override from the report when different CPUs/GTs/GPUs need different values.

Use **Start Automatic Tuning** again, or reselect the desired single profile, to recover old owned settings and reload the edited vendor policy even when the profile name is unchanged. Broker-wide UID, polling and idle settings are installer/root policy; restarting `hardware-tuning.service` reloads them. Modifying source `.env` files affects future installations only and requires `make build`.

Transactions acquire a per-vendor exclusive lock, discover current controls, preflight complete profile requests and persist a root-owned write-ahead journal before the first hardware mutation. Min/max pairs are ordered against current readback. Governor/turbo side effects and legacy application-clock/auto-boost effects are captured as companions. Actual driver readback, including permitted quantization, is recorded and checked against bounds and permission gates. Exceptions and normal signals trigger rollback; an interrupted process leaves journal evidence for the next recovery.

Restoration means returning owned controls to their pre-tuning values, not resetting unrelated platform software or another tool's configuration. Another writer's changed value is preserved. Because intel_pstate globals and per-policy governor/EPP/frequency values are coupled, external CPU-policy interference hands back the complete coupled group rather than overwriting it through a sibling write. Automatic transitions check for interference before applying a different profile and latch a vendor-specific fault instead of repeatedly fighting power-profiles-daemon/firmware. Explicit re-enablement is required after a fault. A reset cannot promise factory defaults for settings changed by other software.

The broker restores on seat loss, session/lease loss, full reset, service termination and before sleep. Manual selections are cleared on local-seat loss. Only the configured non-system desktop UID on active `seat0` can activate a profile; SSH/lingering alone is insufficient. Root may invoke the bounded administrative controls. Sleep uses a required, ordered hook: failed restoration blocks the sleep transaction rather than knowingly sleeping with an unresolved operation. Resume re-evaluates current state/leases. Failure to restore keeps the journal and reports a fault; it is never silently reported as success.

Root-only emergency recovery (stop the broker first so it cannot reapply):

```sh
sudo systemctl stop hardware-tuning.service hardware-tuning.socket
sudo /usr/local/libexec/hardware-tuning-worker recover-all
```

For a single vendor use `hardware-tuning-worker intel reset` or `nvidia reset`. Emergency root reset/recovery is allowed when AppArmor was disabled so recovery is still possible; applying profiles and starting the broker require their enforced AppArmor labels. Do not delete a pending `/run/hardware-tuning/<vendor>.json` journal to make a failure disappear. If a GPU/control is unavailable, restore it only after its driver/device is available again. A power cycle/driver reset may be necessary for a genuinely failed device; no guarantee is made that software can recover inaccessible hardware.

## Security and operational cost

One root AF_UNIX broker listens on `/run/hardware-tuning/control.sock` (root:desktop-primary-group, 0660). Kernel `SO_PEERCRED` UID checks remain authoritative even if another group member can connect. Requests contain only finite actions/vendor/profile names: no paths, clock numbers, executable names, shell text or caller-supplied lifecycle PIDs enter the privileged API. The broker uses fixed worker argv, a clean environment, response limits, connection/request deadlines, a 64-connection cap and rate limiting; user reports are limited to one per 30 seconds.

The broker's AppArmor domain can edit only its own control state and the exact boot-autostart symlink, not sysfs or GPU devices. A separate root-only worker domain has only the selected vendor's hardware permissions. Intel-only installations have an empty capability bounding set and private devices; NVIDIA setters receive bounded device access and CAP_SYS_ADMIN only inside the worker's AppArmor domain. No sudoers rule, polkit policy, setuid binary or world-writable control/configuration file is added.

The broker unit deliberately does not set `NoNewPrivileges=yes`: the fixed worker must transition into a different hardware-capable AppArmor domain. That worker sets no-new-privileges immediately after exec and executes no commands. Executable attachment chooses the correct profile for both ExecStart and ExecStopPost; a single unit-wide AppArmorProfile would incorrectly put emergency recovery in the broker domain. Root profiles do not inherit the repository's shell-permitting wrapper abstraction. Minimal conditional parent/child SIGCHLD bridges preserve Fuzzel and DevOps operation without granting the parent any hardware access.

App leases share one connection/process per active vendor/profile target, not one worker per browser. DevOps sidecars wait on pidfds without periodic PID scanning. Workers are short-lived; NVML handles close after operations and no NVML worker is started for untouched vendor recovery or health when that vendor owns no changed control. The broker checks active selection/interlocks on the configured 5..60-second interval (default 5); this is a software interlock, NOT a real-time thermal guarantee. A slow driver operation can delay checks; each worker operation has a 25-second deadline, and firmware thermal protections remain responsible for immediate hardware protection. Serialized workers favor correctness over simultaneous writes. Tune idle policy/polling deliberately rather than disabling hardware protection.

## Validation and acceptance boundary

Offline checks can be repeated from the repository root:

```sh
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_hardware_tuning_20260916.py'
sudo python3 -B tools/check_hardware_tuning.py
python3 -B tools/build.py --check
```

The generated-unit checker requires root only to satisfy the real installer's root-ownership validation in disposable fixture directories. It never starts a target unit, loads a kernel policy or writes hardware. Read its header before running against any checkout.

See `validation/hardware-tuning/` for actual logs and `docs/hardware-tuning/ACCEPTANCE.md` for the installed-host acceptance procedure. Unit tests use fixture sysfs/NVML, fault injection, real Unix peer credentials and real pidfds. They never write the build container's hardware. The full repository validator is also run without partitioning, booting d-i or starting target services.

The implementation targets the supplied systemd 261.2 deployment. The available offline checker is systemd 257.9; generated unit verification is a parser/dependency check with explicit fixture executables/dependencies, not proof of 261.2 live behavior. This environment has no Flex/P15s hardware, NVIDIA device, graphical session or enforceable target AppArmor kernel. Real installation, thermal behavior, firmware write permissions, suspend/resume and GUI acceptance remain on-target checks, not claimed passes.

## Primary interface references

- systemd.unit: https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html (dash-prefix drop-ins, PartOf, Upholds and StopWhenUnneeded)
- systemd.socket: https://www.freedesktop.org/software/systemd/man/latest/systemd.socket.html
- systemd.resource-control: https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html (device-group allow lists)
- sd_uid_is_on_seat: https://www.freedesktop.org/software/systemd/man/latest/sd_uid_is_on_seat.html
- Intel P-state: https://www.kernel.org/doc/html/latest/admin-guide/pm/intel_pstate.html
- Intel uncore: https://www.kernel.org/doc/html/latest/admin-guide/pm/intel_uncore_frequency_scaling.html
- Powercap/RAPL: https://www.kernel.org/doc/html/latest/power/powercap/powercap.html
- NVIDIA NVML device commands: https://docs.nvidia.com/deploy/nvml-api/group__nvmlDeviceCommands.html
- NVIDIA NVML device queries: https://docs.nvidia.com/deploy/nvml-api/group__nvmlDeviceQueries.html
- NVIDIA-SMI architecture/support notes: https://docs.nvidia.com/deploy/nvidia-smi/index.html
