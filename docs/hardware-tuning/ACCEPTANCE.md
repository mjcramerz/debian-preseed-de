# Installed-host acceptance: hardware tuning

These checks are deliberately NOT marked completed by the offline validator. Use stock/keep defaults first. Save unrelated work before evaluating new hardware limits; positive offsets and power increases are never stability guarantees.

## Installation gates

Install one enabled Flex profile and one enabled P15s profile through the normal preseed path. Check the installer log for its gated vendor list. Flex must have only Intel tuning assets: its NVIDIA tuning flag is false regardless of a later attached NVIDIA GPU. P15s needs both a detected NVIDIA GPU and the selected NVIDIA class. Also exercise an all-disabled profile: `/usr/local/bin/labwc-hardware-tuning`, `/etc/hardware-tuning`, the tuning socket/system units and vendor user targets must not have been installed by this feature.

```sh
systemctl --version
systemctl cat hardware-tuning.socket hardware-tuning.service hardware-tuning-sleep.service
systemctl --user cat intel-high.target hardware-tuning-intel-high.service
sudo aa-status
```

Check installed runtime files/modules are root-owned, not group/world writable, and JSON files are 0600. Confirm all three managed-hardware-tuning profiles are enforced. Inspect kernel/AppArmor logs after every test; do not change them to complain to mask missing permissions.

## Menu and inventory

Confirm battery left-click still presents the original energy profiles. Confirm right-click presents the new Fuzzel menu and only detected/installed vendor labels. Generate a report with tuning off; verify current CPU limits against CPUFreq/intel_pstate, GPU UUID and telemetry against the installed NVML/driver, and RAPL values against that machine's sysfs. Unknown bounds must remain explicitly unknown. Check JSON and text report file permissions.

## Policy-owner gate

With the original PPD service active, request Intel balanced and verify a visible single-owner refusal with no CPU writes. Normal PPD left-click behavior must still work. Follow the recorded-state, runtime-mask trial in README before running the lifetime tests. Confirm the report can query the system bus under the enforced worker AppArmor profile; fix any denial rather than bypassing the check. Keep thermald active. Confirm Intel-only installation includes system_state.py and NVIDIA-only installation does not.

## Reference lifetimes

Start automatic tuning. Open two mapped browsers, then close only one: high must remain. Open DevOps in two separate terminal windows: performance must remain until BOTH activations have exited/toggled off. Closing the last DevOps activation while a browser remains should return to high, not idle. Check the actual transient app unit's Wants/Upholds properties and the vendor target's WantedBy/RequiredBy/UpheldBy dependencies. Confirm no browser/terminal was restarted or killed by tuning transitions.

Select one manual profile for Intel, and separately for NVIDIA when present. Close mapped apps: the chosen manual profile should remain. Reset Profiles [All]: automatic selection should resume without disabling automatic mode. Stop Automatic Tuning: an explicit manual selection remains. Full Reset: automatic/manual/autostart are off and owned controls return to baseline. Existing lease-only user targets are harmless and must not re-enable tuning after reset.

## Failure, coexistence and recovery

Capture baseline knobs in the report. In an administrator-controlled coexistence test, restore PPD's recorded mask state and deliberately start it while a stock custom policy is active. Verify the next health check faults, preserves PPD's externally changed CPU group, and releases remaining owned controls. Then reset custom tuning and restore the intended owner arrangement. Do not merely reselect a custom profile while PPD is still active: preflight must refuse it. With stock settings, test broker restart and then crash recovery while saving the per-vendor recovery journal. Inaccessible controls must produce retained recovery records and a visible error.

Switch away from the active local seat or log out: owned settings restore. Test suspend/resume and inspect `hardware-tuning-sleep.service` ordering and journal output. A restore failure must not be reported as a successful reset or silently ignored by the sleep hook. A historical fault with no owned/pending controls must allow sleep, and resume must not clear that fault or reapply its rejected profile. Verify an SSH-only/lingering user cannot activate a profile without active seat0.

On multi-GPU hosts, confirm the report has a valid temperature for every enumerated NVIDIA GPU before requesting positive offsets or above-default power. Missing/invalid coverage must block those requests rather than borrowing a temperature from another GPU. Do not disable physical thermal protection to test this; use fault-injected fixtures for sensor-loss scenarios.

Test boot enable/disable on subsequent real boots. Merely enabling future boot autostart must not alter the current state. Full Reset must remove the exact autostart link and prevent tuning on the next boot. Do not remove pending journals as a substitute for recovery.

## Custom values only after stock acceptance

Change one explicitly supported setting at a time. Use report bounds, correct units and device IDs. Do not infer P520 lock support from newer NVIDIA APIs. Do not supply RAPL verified bounds without a platform specification. Observe real temperatures, throttling, stability and workload responsiveness under realistic sustained load. These are machine-specific acceptance measurements, not actions the installer can safely assume complete.

```sh
labwc-hardware-tuning status
journalctl -u hardware-tuning.service -u hardware-tuning-sleep.service -b
journalctl --user -u 'hardware-tuning-*.service' -b
```

## Platform and resctl acceptance

Compare PCIe links under representative load, cumulative AER/thermal-counter deltas, NVMe health and latency, and Thunderbolt DMA security before/after. Test dock cold boot, hot-plug, suspend/resume and combined downstream I/O without raw-device writes. Do not disable ASPM, APST, deep idle or IOMMU protection as a generic optimization. CPU-only, GPU-only and mixed sustained workloads must each be measured: the supplied audit temperatures are snapshots, not stable power-budget limits.

Confirm the original user ownership/mode/content of /data/docs is unchanged. Verify root-owned /usr/local/share/doc/resctl-bench/INSTALLATION.json and the retained release documentation/licenses, plus the three mandatory executables under /usr/local/bin. Read the install log for successful unprivileged --version probes. /var/tmp must remain noexec. No benchmark is started by installation. The pinned native build must still be tested for the actual host CPU/loader; amd64 alone is not proof of native-instruction compatibility. Exercise a fresh preseed install using the rebuilt matching payload/manifest/preseed rather than resuming a mixed cached installer snapshot.
