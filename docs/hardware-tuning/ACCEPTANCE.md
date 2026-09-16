# Installed-host acceptance: hardware tuning

These checks are deliberately NOT marked completed by the offline validator. Use stock/keep defaults first. Save unrelated work before evaluating new hardware limits; positive offsets and power increases are never stability guarantees.

## Installation gates

Install one enabled Flex profile and one enabled P15s profile through the normal preseed path. Check the installer log for its gated vendor list. Flex should have only Intel assets if its current PCI inventory still has no NVIDIA GPU. P15s needs both a detected NVIDIA GPU and the selected NVIDIA class. Also exercise an all-disabled profile: `/usr/local/bin/labwc-hardware-tuning`, `/etc/hardware-tuning`, the tuning socket/system units and vendor user targets must not have been installed by this feature.

```sh
systemctl --version
systemctl cat hardware-tuning.socket hardware-tuning.service hardware-tuning-sleep.service
systemctl --user cat intel-high.target hardware-tuning-intel-high.service
sudo aa-status
```

Check installed runtime files/modules are root-owned, not group/world writable, and JSON files are 0600. Confirm all three managed-hardware-tuning profiles are enforced. Inspect kernel/AppArmor logs after every test; do not change them to complain to mask missing permissions.

## Menu and inventory

Confirm battery left-click still presents the original energy profiles. Confirm right-click presents the new Fuzzel menu and only detected/installed vendor labels. Generate a report with tuning off; verify current CPU limits against CPUFreq/intel_pstate, GPU UUID and telemetry against the installed NVML/driver, and RAPL values against that machine's sysfs. Unknown bounds must remain explicitly unknown. Check JSON and text report file permissions.

## Reference lifetimes

Start automatic tuning. Open two mapped browsers, then close only one: high must remain. Open DevOps in two separate terminal windows: performance must remain until BOTH activations have exited/toggled off. Closing the last DevOps activation while a browser remains should return to high, not idle. Check the actual transient app unit's Wants/Upholds properties and the vendor target's WantedBy/RequiredBy/UpheldBy dependencies. Confirm no browser/terminal was restarted or killed by tuning transitions.

Select one manual profile for Intel, and separately for NVIDIA when present. Close mapped apps: the chosen manual profile should remain. Reset Profiles [All]: automatic selection should resume without disabling automatic mode. Stop Automatic Tuning: an explicit manual selection remains. Full Reset: automatic/manual/autostart are off and owned controls return to baseline. Existing lease-only user targets are harmless and must not re-enable tuning after reset.

## Failure, coexistence and recovery

Capture baseline knobs in the report. While tuning owns controls, use the original left-click energy menu. Verify the tuner detects changed controls, preserves the other power manager's values and latches a fault rather than repeatedly fighting it. Explicitly restart tuning to take ownership again. With stock settings, test broker restart and then crash recovery while saving the per-vendor recovery journal. Inaccessible controls must produce retained recovery records and a visible error.

Switch away from the active local seat or log out: owned settings restore. Test suspend/resume and inspect `hardware-tuning-sleep.service` ordering and journal output. A restore failure must not be reported as a successful reset or silently ignored by the sleep hook. Verify an SSH-only/lingering user cannot activate a profile without active seat0.

Test boot enable/disable on subsequent real boots. Merely enabling future boot autostart must not alter the current state. Full Reset must remove the exact autostart link and prevent tuning on the next boot. Do not remove pending journals as a substitute for recovery.

## Custom values only after stock acceptance

Change one explicitly supported setting at a time. Use report bounds, correct units and device IDs. Do not infer P520 lock support from newer NVIDIA APIs. Do not supply RAPL verified bounds without a platform specification. Observe real temperatures, throttling, stability and workload responsiveness under realistic sustained load. These are machine-specific acceptance measurements, not actions the installer can safely assume complete.

```sh
labwc-hardware-tuning status
journalctl -u hardware-tuning.service -u hardware-tuning-sleep.service -b
journalctl --user -u 'hardware-tuning-*.service' -b
```
