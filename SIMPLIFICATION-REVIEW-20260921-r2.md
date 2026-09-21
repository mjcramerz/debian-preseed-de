# Debian preseed desktop - simplification follow-up, 2026-09-21 (R2)

> **Superseded by R3 for graphics, icon size and flex storage.** See [ATOMIC-OUTPUT-ZRAM-REVIEW-20260921-r3.md](ATOMIC-OUTPUT-ZRAM-REVIEW-20260921-r3.md). The legacy-KMS policy below has been removed; drawer icons are now 24px. This document records the earlier revision, not current deployment instructions.

## Scope and delivery

This revision starts from the complete R1 archive, `debian-preseed-de-refactored-20260921.tar.gz`, and makes only the requested Foot and application-drawer simplifications, their tests, and the necessary generated installer products. It is a complete repository, not a patch. The requested helpers are deleted, not renamed, disabled, or replaced with equivalent helpers.

The installed target remains Debian Forky with the user's systemd 261.2. No vendor source patches, new source builds, package-version changes, additional runtime dependencies, icon-download stage, or global Xwayland server are introduced. The existing `apps-symbolic.svg` and `wayscriber-symbolic.svg` remain unchanged.

## Removed helpers and dependencies

`d-i/forky/hooks/target/usr/local/libexec/labwc-stage-waybar-icons` and `d-i/forky/hooks/target/usr/local/libexec/labwc-foot-supervisor` are absent from the source tree, rebuilt payload manifest, and payload archive.

The corresponding role-asset staging entries have been removed. The icon-preparation function and its installer call are removed. Waybar's AppArmor profile no longer grants access to the removed `/usr/local/share/labwc/waybar-icons/` cache. Foot's launch path no longer executes a supervisor. Tests which previously executed the deleted helpers now exercise their simpler replacements directly.

Historical R1 reports, manifests and logs remain as historical evidence; their references do not create runtime dependencies. A banner on the R1 review points to this report for the superseding behavior.

## Icons: installed artwork, direct URL, fixed display size

The drawer reads the package-installed icon files directly. No second copy or generated cache is created:

| Application | Installed image used by normal and hover rules |
|---|---|
| Foot | `/usr/share/icons/Papirus/24x24/apps/foot.svg` |
| Thunar | `/usr/share/icons/Papirus/24x24/apps/org.xfce.thunar.svg` |
| FeatherPad | `/usr/share/icons/Papirus/24x24/apps/featherpad.svg` |
| Tuta Mail | `/usr/share/icons/hicolor/512x512/apps/tuta-mail.png` |
| Sleek | `/usr/share/icons/hicolor/512x512/apps/sleek.png` |

Papirus-Dark shares the application directory with Papirus through a package symlink [4]; these are the same application SVGs, not a hicolor fallback for Thunar. Tuta's existing installer explicitly installs its PNG at the path above. Sleek's existing pinned Debian package supplies its application artwork. The installer verifies that selected applications' actual paths exist and decode; it does not silently substitute an unrelated icon.

CSS URL images are sized to **18 by 18 logical pixels** with `background-size`, centered and non-repeating. Hover rules retain the same image as their first layer and the existing gradient as their second layer. Both internal and external bars use the same rule. No font glyph supplies these five app icons.

The large 512-pixel source images are not displayed at their intrinsic dimensions: real GTK3/Cairo tests render synthetic 512-pixel sources at both 1x and 2x scale, checking the central color and the painted bounding box. Those tests also check the Papirus URL against a deliberately wrong hicolor Thunar fixture. They are rendering tests of the implemented CSS, not claims to have run the installed Waybar binary or inspected the real laptop display.

The retained inline installer verifier checks both skeleton and account configurations, the configured application group and callbacks, both hover and normal image references, image decoding at 18 pixels, and the account/home association. Optional Tuta/Sleek checks run only for amd64 installs selecting the existing software bundle; no new package requirement is imposed on other architectures or unselected bundles. The verifier is read-only and does not create any assets.

### Why not add `image-path`, `image-name`, and `icon-size` here?

Upstream Waybar's development branch documents those custom-module options [1]. The Forky package currently listed by Debian is **0.15.0-1** [2], whose tagged custom-module implementation is an `ALabel` and does not implement them [3]. Adding unsupported keys would silently leave this installer dependent on a feature it does not install. The existing static CSS image mechanism therefore provides the requested small icons without source builds, version detection, compatibility helpers, or changed package pins. This distinction was checked on 2026-09-21.

No duplicate Tuta/Sleek SVGs or downloaded brand assets are necessary: their installed logos already work with explicit sizing. Existing custom SVGs for the Applications drawer button and Wayscriber remain untouched.

## Foot: direct process under the existing transient service

The generic managed launcher now puts `/usr/bin/foot` directly after systemd-run's `--` argument separator. There is no extra supervisor process. The session restore token still records the original application command.

For the canonical Wayland Foot executable, the existing `KillMode=mixed` signals the terminal process first and retains systemd's final cgroup cleanup. `ExitType=cgroup`, the 20-second stop timeout, `SendSIGKILL=yes`, `Restart=no`, collection, session target ownership/order, launch-closing guard, and existing terminal host-UID policy are retained. With mixed mode, remaining processes may be killed when the main process exits or the stop timeout expires; the timeout is not a promise that every descendant gets an additional full 20 seconds [5].

Only an argument-free `/usr/bin/foot` launch adds `SuccessExitStatus=1`, covering the observed default-shell close result. This is a deliberately limited classification: any default-shell exit with status 1 is accepted for that exact launch, not just a provably detected hangup. Explicit commands or options receive no such exception; other paths, applications, and launcher kinds retain their existing policies. No shell text is evaluated or argv concatenated into a command.

Foot documents **230** as its internal error status and otherwise returns its client's exit status [6]. R2 does not treat 230 as success, even during shutdown, and does not hide arbitrary command failures or crashes. Removing the supervisor also removes its special stop-context status translation. The save-aware session preparation remains unchanged; real target testing is still needed to establish whether any further Foot failure has an underlying application/display cause. Native systemd success-status handling is described in [7].

## Preserved behavior

The earlier save/cancel power-action flow, user-session stop checks, single-force power handoff, wlsunset fix, host-scoped DRM mitigation, GTK menu contents/icons/arrows, main-panel button ordering and tint/rim colors, workspace colors, software pins and installers remain unchanged. AppArmor changes in this follow-up only remove the obsolete icon-cache reads; access to package artwork already exists in the installed profile abstractions.

All existing Xwayland implementation files, application-isolation definitions, compositor unit and host profiles outside the exact Foot dispatch changes remain byte-identical to R1. No global Xwayland access is added. Hash-based preservation checks and the exact changed/removed paths are supplied in `CHANGE-MANIFEST-20260921-r2.json` and the validation directory.

## Validation results

**2,234 passed; 49 skipped; 0 failed**, across 2,283 test cases and 96 runnable modules. All 97 discovered files were attempted; the remaining file is a support module with no tests. Each test module ran in its own process.

One first-pass source-contract assertion still referred to the removed supervisor's variable name. It was updated to assert the equivalent direct-Foot predicate, not deleted or weakened; its 24 tests pass on rerun. The original failure and rerun details remain in the validation evidence. The final drawer test module was also rerun after a comment-only clarification.

Payload/build freshness, browser-config freshness, 59 preseed files and four private debconf round trips pass. All 285 shell files pass 581 parser checks. All 37 managed top-level AppArmor files compile offline. The rebuilt payload contains 1,405 files, exactly two fewer than R1 because the helpers are gone.

The GTK fixture checks 40 paint cases: five icons, normal and hover states, internal and external bars, and 1x and 2x scale. Installer-verifier regressions reject absent selected-package images, bad decode results, oversized decode results, missing hover images, missing size bounds and corrupted account configuration. Foot regressions check direct argv, original restoration metadata, retained cgroup/session properties, the narrow default-shell exit-status exception and preservation of explicit errors.

Missing dependencies remain explicit skips, including Perl/Moo support and selected desktop/runtime integration binaries. The audit separately reports blocked-dependency and inventory-only entries; these are not successful semantic or runtime tests. The complete reasons and per-module outcomes are in `VALIDATION-20260921-r2.json` and `validation-20260921-r2/`.

No booted installer, live save dialogs, physical reboot, installed Waybar, real target Foot lifecycle, or kernel-enforced target AppArmor run is claimed. The test container does not contain the target vendor packages or Python GI bindings; direct package paths are verified on installation, while the container's GTK paint test uses ctypes and synthetic fixture images. Validation is not a guarantee that future package layouts will never change.

### Reproduce the offline checks

From the repository root:

```sh
python3 -B tools/build.py --check
python3 -B tools/build_browser_config.py --check
python3 -B tools/check_preseeds.py
python3 -B tools/check_shells.py --output /tmp/debian-preseed-shell-check.json
python3 -B d-i/forky/tests/audit_codebase.py --output /tmp/debian-preseed-audit.json
```

To repeat an individual test module in a fresh process:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -v \
  -s d-i/forky/tests -p test_drawer_native_icons_20260920.py
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -v \
  -s d-i/forky/tests -p test_session_reliability_20260921.py
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -v \
  -s tools/tests -p test_labwc_power_handoff.py
```

The complete per-module names are listed in the validation JSON. The source-only AppArmor compile is part of `test_menu_apparmor_integration_20260919.py`. No test requires issuing a real reboot or poweroff.

## Deployment and target acceptance

Publish the full extracted repository atomically, keeping `d-i/forky/preseed.cfg`, `payload.manifest` and `payload.tar.gz` from this same revision. Serving this archive updates the unattended-install source; it is not an automatic in-place migration of an already-running desktop.

On a freshly installed target, check both Waybar layouts, normal and hover appearance, and the retained tooltips/actions. Confirm all five icons remain compact at the configured output scales. The installer already fails explicitly when a selected package's required icon is missing or cannot be decoded.

Open the normal Foot launcher, close its window, and check the collected service's journal result. Also launch a deliberately failing explicit command in a disposable terminal to verify that failures remain visible. Review an ordinary logout before testing a real power action; do not terminate a working terminal with unsaved work merely to test shutdown. Retain the original R1 acceptance checks for save cancellation, user-unit quiescence, graphics and AppArmor enforcement.

The archive's regular files are compared against the final repository for path safety, SHA-256, size and mode. The adjacent SHA-256 file covers the complete compressed archive. All 3,468 files from the user's original ZIP remain present; the only deleted source files were the two helpers introduced in R1.

## Primary references checked on 2026-09-21

[1] Waybar development custom-module documentation: https://raw.githubusercontent.com/Alexays/Waybar/master/man/waybar-custom.5.scd

[2] Debian Forky Waybar package listing: https://packages.debian.org/forky/waybar

[3] Released Waybar 0.15.0 custom implementation: https://raw.githubusercontent.com/Alexays/Waybar/0.15.0/src/modules/custom.cpp

[4] Papirus-Dark shared application-directory symlink: https://raw.githubusercontent.com/PapirusDevelopmentTeam/papirus-icon-theme/master/Papirus-Dark/24x24/apps

[5] systemd.kill, mixed-mode signal ordering and final cgroup cleanup: https://manpages.debian.org/unstable/systemd/systemd.kill.5.en.html

[6] Foot, exit-status contract: https://manpages.debian.org/testing/foot/foot.1.en.html

[7] systemd.service, ExitType and SuccessExitStatus: https://manpages.debian.org/unstable/systemd/systemd.service.5.en.html

[8] Existing Sleek v2.0.26 Linux packaging and original 512-pixel artwork: https://raw.githubusercontent.com/ransome1/sleek/v2.0.26/electron-builder.yml ; https://raw.githubusercontent.com/ransome1/sleek/v2.0.26/resources/icon.png
