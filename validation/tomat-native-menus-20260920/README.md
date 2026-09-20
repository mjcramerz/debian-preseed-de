# Validation records for the 2026-09-20 scoped update

This directory is historical evidence for the first archive. `final/summary.json` and its adjacent logs apply to that prior release; their hashes no longer describe the follow-up payload. Current release validation is in `../notifications-followup-20260920/`. Historical logs and diffs intentionally retain the now-removed dedicated Tomat upgrade implementation for provenance.

The top-level `summary.json`, `tests.log`, `tools-tests.log` and associated audit/build logs record the preceding review run. That run exposed an obsolete panel-click-count assertion (58 rather than 60 after the requested menu integration). The assertion was aligned without relaxing its lifecycle checks. Final review also corrected the MMC driver's explicit parameter prefix and added a minimum Mako JSON-interface check; the release run covers these changes.

`native-tomat-tests.log` contains the focused hardware, controller, packaging, update, menu, GTK-builder and AppArmor tests. A missing Perl Moo dependency is explicitly skipped rather than simulated. `workspace-tests.log` is the focused existing workspace regression run.

`baseline-iocost.log` and `baseline-iocost-boundary.log` were run against a separate extraction of the untouched supplied ZIP. They establish the three out-of-scope IOCost test/configuration disagreements. The calibration policy and those assertions are preserved.

`scope-audit.json` and `scoped-changes.diff` compare the delivered repository to the uploaded ZIP. They exclude this validation directory to avoid self-reference. Existing unrelated files, including the private-Xwayland, Zoom, Discord and Crystal Dock assets identified in the report, remain byte/mode-identical.

`mmc-module-parameter.json` corroborates the kernel-source review using a preinstalled Debian module's registered parameter string. No kernel module was loaded or compiled. `native-syntax.json` records additional Python/embedded-verifier parsing.

These are offline/container tests, not a completed physical Forky/systemd 261.2 deployment. See `docs/HARDWARE-TOMAT-NATIVE-MENUS-2026-09-20.md` for package-source trust, AppArmor mode, actual-vendor-binary and live-host acceptance limits.
