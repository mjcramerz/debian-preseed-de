# Hardware tuning and protected resctl documentation refactor

> Historical revision report. The subsequent confirmed PPD handover and current menu semantics are documented in `HARDWARE-TUNING-POLICY-HANDOVER-20260917.md` and `hardware-tuning/README.md`.

Revision: 17 September 2026. Input: the supplied `debian-preseed-de(1).zip`.
Target supplied by the operator: Debian Forky with systemd 261.2.

This report supersedes older hardware-tuning enablement/default/readback claims
and the old resctl documentation destination. Earlier reports and validation logs
are retained as historical evidence, not rewritten as current test successes.
The executable release pins and the earlier native/noexec installation fixes are
preserved.

## Evidence and scope

The supplied Flex audit identifies the i3-1115G4 with active intel_pstate,
powersave and balance_performance EPP; the P15s audit identifies the i7-10610U
and Quadro P520. Both report an existing power-profiles-daemon policy owner.
Their frequency limits, temperatures and negotiated PCIe links are observations,
not sustained-load acceptance or an OEM authorization to increase power. The
supplied low-level tuning report recommends a baseline, one policy owner,
conservative HWP/EPP changes, named RAPL constraints, retained thermal/security
protection, and workload/reboot/resume validation before persistence. This
revision follows that hierarchy instead of copying illustrative PL1 values or
unsupported Pascal clock-lock recipes into every laptop.

No changes are made to CPU/cpuset/I/O delegation, cgroup weights, partitioning,
package-safe power actions, browser/process isolation, labwc/wlroots settings,
Crystal Dock, networking, firmware flashing, driver package selection, or the
native resctl release/version/digest. In particular, missing delegated cpuset/IO
in experimental audit snapshots is not treated as a deployed-system defect.

The existing bounded broker/worker architecture is retained. Changes are confined
to its hardware discovery, transaction/recovery, known-owner gate, lifecycle,
profile values, associated installer/verifiers, regression tests and documentation.
The complete original file inventory is retained. The scope manifest records
all changed/new files and verifies that profile lines outside HARDWARE_* have
not changed.

## Profile wiring

| Profiles | Intel tuning installation | NVIDIA tuning installation |
|---|---|---|
| btrfs-de-main, btrfs-de-dual-main | true | true |
| btrfs-de-flex, btrfs-de-dual-flex | true | false |
| All nine other profiles | false | false |

Every profile has the same complete tuning schema and values. Intel additionally
requires GenuineIntel discovery; NVIDIA additionally requires the selected
NVIDIA class and an actual display GPU. The common runtime and vendor-specific
assets/permissions are installed only after their existing gates succeed.
`system_state.py` is staged only for Intel. The source repository still contains
both vendors so it can serve different hosts. This remains a fresh-install
mechanism, not an automatic remover of previously installed vendor assets.

Balanced AC Intel defaults are now balance_performance EPP with a 100% maximum
performance ceiling. The previous arbitrary 85% balanced ceiling is removed.
Active intel_pstate keeps adaptive powersave behavior, rather than being forced
to the generic fixed-minimum powersave algorithm. Silent retains its explicit
55% ceiling, power EPP and turbo-disabled policy. High/performance retain their
existing priorities and conservative stock-limit requests. Labels do not imply
measured distinct clock rates or that every device implements every control.

Autostart, positive-overclock permission, power-increase permission, exclusive
unqueryable clock-lock permission and administrator-verified RAPL bounds remain
off. RAPL PL1/PL2/PL4, uncore overrides and NVIDIA offsets/locks/application clocks
remain keep until explicitly configured and validated. Workload leases still
outrank the idle AC/battery fallback; this revision does not silently add a
battery ceiling over an explicitly selected workload/manual profile.

## Policy ownership and security

A custom CPU policy cannot safely run independently alongside PPD/TLP/tuned.
Before CPU/RAPL/domain/uncore mutation, the worker queries a fixed list of known
competing services using libsystemd's typed, bounded D-Bus ActiveState interface.
Active/transitional/unknown ownership and bus errors fail closed before writes.
Absent/inactive/failed services are distinguished. The gate does not execute a
shell or stop/mask other services. Intel GPU-only controls are not incorrectly
blocked on a CPU-owner query. Thermal control (thermald, kernel and firmware)
is deliberately retained.

This is an **explicit ownership choice**, not a transparent takeover. The
unchanged default PPD service keeps normal left-click energy profiles working;
custom Intel tuning initially refuses concurrent ownership. Follow the
recorded-state, runtime-mask trial in `hardware-tuning/README.md` to select the
custom controller, then reset before restoring PPD. Persistent tuning requires
an administrator's corresponding persistent ownership decision. Do not disable
thermal protection. A service check cannot exclude arbitrary root scripts or EC
writes; periodic exact readback and owner checks provide the second guard.

The Intel AppArmor abstraction gains only the new module read and the system-bus
connection/Hello/Properties.Get surface needed for that read-only query. No
StartUnit, StopUnit, Set, arbitrary privileged command, internet socket, raw MSR
or firmware control is introduced. Existing root-owned configuration, isolated
Python entrypoints, authenticated peer UID/active-seat checks, fixed worker argv,
no shell evaluation, resource/deadline limits and separate broker/worker domains
are retained. Unknown selected-vendor and common environment keys now fail before
policy publication rather than silently accepting a misspelled setting.

## Transaction and recovery correctness

Requests that initially match current values are retained through preflight.
When a governor/turbo/global limit changes, explicitly requested companion values
are rechecked after that side effect. Independent already-correct knobs are not
needlessly written or owned. Final readable values must match the resolved
request exactly, as well as satisfy advertised/effective bounds and permission
gates. A legal but ignored, quantized or externally overridden request is not
reported as success. Administrator-selected values must be representable by the
driver; this code does not invent a universal rounding tolerance.

Reset now persists its own pending intent before the first restore write, so an
interrupted restore remains recoverable rather than looking like an unrelated
writer. It verifies final coupled values after all writes and retains the whole
involved pair/companion CPU domain when restoration fails. Another manager's
changed CPU policy is yielded as a coupled group. Original RAPL/window baseline
values remain the power-increase reference across recovery rather than ratcheting
up from a previously tuned value. Empty-journal resets take the same exclusive
lock as applies, closing a no-op/reset race. Journals are not removed to suppress
an error.

Application clocks and offset/modern-lock interfaces cannot be requested
together on the same NVIDIA GPU. Unqueryable lock ranges still require exclusive
control acknowledgement and are reported unknown, not fabricated as measured
state. Their reset means release to driver behavior, not reconstruction of an
unobservable previous third-party lock.

## Capability discovery and low-overhead observation

Intel covers CPUFreq/HWP/EPP/EPB, percentage/turbo policy, supported uncore,
i915/per-GT and Xe frequency interfaces, and named package/subdomain powercap
constraints. Flat and nested RAPL/MSR/MMIO aliases are deduplicated; disabled
zones are not implicitly enabled. Nonpositive optional bounds remain unknown.
Read-only attributes are reported rather than write-probed. Granular TPMI uncore
clusters take precedence over overlapping aggregate package controls. A generic
powersave governor is not substituted for an unavailable adaptive governor.
All discovered CPU packages need valid coretemp coverage for risky changes.

Passive Intel reports add PCIe current/maximum links, runtime PM, cumulative
AER, Thunderbolt security/IOMMU state, platform profiles, CPU0 idle states,
thermal throttle counters, and i915 firmware-related settings. They are bounded
and omit serial numbers. No ASPM force, APST disable, deep-idle restriction,
Thunderbolt authorization bypass, IOMMU weakening, raw PCI write, firmware update
or unsafe storage benchmark is automated. These interfaces are intentionally
observed rather than treated as universal performance switches.

NVIDIA retains per-device feature probing and Pascal architecture limits. It
adds current/maximum PCIe generation/width and typed 64-bit clock-event telemetry
with the older symbol fallback. Health/recovery discover only owned control
families/P-states instead of repeatedly scanning all offsets and clock tables.
Full reports and apply preflight retain comprehensive discovery. Oversized clock
tables are refused, not silently truncated; partial constructor failures close
NVML. No claim is made that NVML observation has zero wake/power cost.

## Lifecycle

Application dash-prefix Wants/Upholds leases, vendor targets, PartOf relationships,
pidfd-bound DevOps sidecars and application independence are unchanged. Tuning
failure still must not kill a browser, terminal or its development shell.

Known laptop battery presence with unreadable AC state now chooses battery,
not AC; USB_PD_DRP is recognized. Manual selections cannot be revived after a
broker restart without an active local seat. Faulted vendors are not hammered
by every poll. Recovery-pending state is explicit, with bounded explicit/pre-sleep
retries. Resume preserves latched thermal/ownership faults. A safely restored
historical fault no longer spuriously blocks suspend, while unresolved recovery
or still-owned controls must block the pause result. Accepted compound requests
have adequate client/sleep-unit deadlines; queued requests time out before
execution, with reserved connection headroom for root recovery.

## resctl-bench failure and fix

The existing tmpfiles policy deliberately makes `/data/docs` account-owned with
mode 2750. The resctl installer correctly refuses to publish root-managed release
files through that mutable ancestor. The error was therefore a destination
contract mismatch, not a reason to weaken ownership validation or chown the
user's documents.

The installation root for release data is now:

```text
/usr/local/share/doc/resctl-bench/INSTALLATION.json
/usr/local/share/doc/resctl-bench/release/...
```

The desktop and first-boot verification paths are updated together. Binaries stay
under `/usr/local/bin`. Documentation, release provenance, licenses and debug
material are preserved as non-executable root-owned data. `/data/docs` ownership,
mode and existing files remain untouched. No unsafe compatibility symlink is
created and no previous user-managed directory is adopted or removed.

The exact pinned archive, internal checksums, strict path/member/type/size checks,
private extraction, root-controlled executable staging on the destination
filesystem, nobody-only `--version` probes, no-clobber publication and rollback
remain. `/var/tmp` stays noexec. Neither the upstream install.py nor a benchmark
runs during installation. The native binary's actual CPU/loader compatibility
still requires its real target probe; a successful synthetic regression does
not establish compatibility with every amd64 CPU.

## Validation evidence

Current logs and machine-readable results are in
`validation/tuning-refactor-20260917/`. The focused suite includes real private
D-Bus ABI/error/timeout tests, sysfs/NVML failure-injection fixtures, interrupted
restore recovery, policy-owner conflicts, 32 installation gate combinations,
profile schema consistency, unit generation, and the actual account-owned-docs
reproduction. Synthetic executable probes do not run the downloaded release.

The final validation summary records exact test counts, skips, inherited
failures and parser/tool versions. The full validator's result must not be
confused with the focused suite's result. On-host AppArmor enforcement, systemd
261.2 lifecycle behavior, unattended partitioning/boot, driver/firmware operation,
thermal soak, resume and dock hot-plug are **not** certified by container tests.

### Completed results for this revision

| Check | Result |
|---|---|
| Focused hardware tuning suite | 116 tests, all passed; 37 newly added tests |
| Focused resctl suite | 68 tests, passed with 1 skip; 5 newly added tests |
| Generated units and AppArmor | 9 checks passed across Intel-only, NVIDIA-only and dual-vendor generation |
| Preseed generation / private debconf readback | 59 preseed files passed |
| Shell parsing | 280 files / 571 parser checks passed |
| Tools suite | 179 tests passed, no skips |
| Whole repository suite | 1,400 tests completed; 7 failures, 2 errors, 28 skips |
| Payload / manifest / preseed consistency | Passed |

**The whole repository suite is not all green.** Eight of its nine failure/error
entries reproduce against the untouched input: missing historical AppArmor
incident fixtures, missing Moo for four managed-software tests, an existing
scope-drop-in expectation and an unrelated Fuzzel mock/subprocess error. The
ninth is the unchanged Spotify cancellation fixture (137 instead of 1); it
passes both baseline and refactored focused reruns. Its exact full-run cause
was not established, and its failure remains in the evidence. No unrelated
implementation or assertion was changed to hide these results. The focused
hardware/resctl suites have no failures.

The audit reports 459 parser passes, 175 structural passes, 495 inventory-only
entries, 2 templates needing rendering and 156 dependency-blocked checks. These
categories are not interchangeable with live runtime validation. The available
unit parser is systemd 257.9, **not** the requested target's 261.2. AppArmor
compilation used skip-kernel-load; its unavailable kernel-interface warning is
retained. Actual target acceptance is still required.

The test runner's initial parent was interrupted by the execution transport;
its separately-sessioned main suite completed to the recorded 1,400-test result.
The partial initial tools log is retained and a complete tools rerun passed;
remaining parser/audit checks completed separately. `summary.json` records this
rather than pretending the parent returned an all-green result. Original input
integrity was verified against all 2,568 regular ZIP members with zero baseline
byte mismatches, and all 13 profiles are unchanged outside HARDWARE_* lines.

Run from a disposable extracted repository, not a running installation target:

```sh
python3 -B tools/check_resctl_bench.py
python3 -B tools/build.py --check
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_hardware_tuning*.py'
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_resctl_bench*.py'
python3 -B tools/check_hardware_tuning.py --output-dir validation/local-generated
python3 -B tools/validate.py --output-dir validation/local-full --test-timeout 900
```

See `hardware-tuning/ACCEPTANCE.md` for the remaining physical-host acceptance.
No bottleneck-free or stable-overclock guarantee is inferred from the audit.

## Deployment

Publish the complete new repository atomically, including the matching rebuilt
`d-i/forky/preseed.cfg`, `payload.manifest` and `payload.tar.gz`. Rebuild with
`make build` after changing future installer profiles. Use a fresh installer boot,
not a resumed mixed/cached failed snapshot. Do not clear fatal state or bypass
checksums to force an old installation to continue. This archive is a complete
served unattended-install codebase, not an in-place host upgrade script.

## Primary-source checks

The supplied report is the hardware-policy basis; the following upstream sources
were used separately to verify interface semantics rather than to infer
board-specific power values (accessed 17 September 2026):

- Linux intel_pstate: https://cdn.kernel.org/doc/html/latest/admin-guide/pm/intel_pstate.html
- Linux powercap: https://docs.kernel.org/power/powercap/powercap.html
- Intel uncore interface: https://docs.kernel.org/admin-guide/pm/intel_uncore_frequency_scaling.html
- TLP conflict guidance: https://linrunner.de/tlp/faq/conflicts.html
- systemd typed bus ABI: https://raw.githubusercontent.com/systemd/systemd/main/src/systemd/sd-bus.h
- NVIDIA NVML queries: https://docs.nvidia.com/deploy/nvml-api/api/group__nvmlDeviceQueries.html
- NVIDIA SMI architecture/control notes: https://docs.nvidia.com/deploy/nvidia-smi/

No external latest-version assumption replaces the operator-supplied Forky /
systemd 261.2 deployment baseline.
