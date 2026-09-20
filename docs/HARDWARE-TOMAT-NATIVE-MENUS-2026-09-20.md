# Profile hardware policy, Tomat and native Waybar menus

**Follow-up revision:** the Tomat-only upgrade transaction has been removed and the Notifications button revised. See `NOTIFICATIONS-FOLLOWUP-2026-09-20.md` for the current changes and validation; the original validation results below are historical.

## Delivery and scope

This is a complete repository update, not a patch. The generated `d-i/forky/preseed.cfg`, `payload.manifest` and `payload.tar.gz` were regenerated with `python3 -B tools/build.py`. Publish the complete repository atomically; do not mix a new preseed or manifest with an older payload.

The changes add profile-selected hardware configuration, remove the requested ThinkPad hwdb override, integrate the released Tomat amd64 Debian package, and provide native GTK menus through Waybar. No upstream source patch or new source compilation was introduced. Existing private Xwayland implementation, Zoom/Discord launch policy and Crystal Dock configuration are preserved. A machine-readable scope comparison against the supplied ZIP is in `validation/tomat-native-menus-20260920/scope-audit.json`.

This is implementation and offline validation evidence, not a claim of successful deployment on physical Forky/systemd 261.2 hosts. The final validation results and remaining acceptance limits appear below.

## Explicit hardware selection

| Profiles | `SYSTEM_HARDWARE_SPEC` |
| --- | --- |
| `btrfs-de-main`, `btrfs-de-dual-main` | `79-thinkpad-acpi.conf` |
| `btrfs-de-flex`, `btrfs-de-dual-flex` | `79-ideapad-acpi.conf` |
| `f2fs-de-cbook`, `f2fs-de-dual-cbook`, `f2fs-de`, `f2fs-de-dual`, `f2fs-desktop` | `79-chromebook.conf` |

The default is empty. CPU vendor no longer selects a ThinkPad chassis policy. `stage_target_hardware_spec` is called by both filesystem-family installers and accepts only these three exact filenames or an empty value. It validates the target parent, stages the requested file atomically before removing stale alternatives, and removes only the other known managed filenames. It does not delete unrelated administrator-created `79-*.conf` files. An unsupported filename is rejected before target mutation. Generic profiles without a selection install none of these three files.

The ThinkPad file retains the existing `thinkpad_acpi fan_control=1 brightness_enable=1` and adds `options i915 enable_dpcd_backlight=1`. ThinkPad module loading is left to hardware modalias detection rather than imposed on every Intel host.

The IdeaPad file explicitly retains `no_bt_rfkill=0 allow_v4_dytc=0`. There is no invented `ideapad_laptop fan_control=` parameter: supported firmware exposes optional fan-mode control through sysfs, and forcing modes across different Flex models would be unsafe. Automatic firmware thermal management and kernel DMI quirks are preserved.

The Chromebook file uses `options mmc_block mmcblk.perdev_minors=16`. The MMC block driver explicitly retains the `mmcblk.` parameter prefix even in modular builds; an unprefixed `perdev_minors` would be ignored. The HP 14 G7 policy intentionally does not force generic SDHCI timing, CQE, audio-DSP, backlight or power-cycle quirks. Those decisions remain with kernel/firmware discovery. F2FS compression, garbage collection and discard settings belong to the existing mount configuration, not to fictitious module parameters; the existing rootwait, eMMC initramfs, nodiscard and periodic-fstrim configuration is retained. A hardware bring-up test must confirm the actual panel, firmware, storage and optional fan interfaces on each physical model.

`90-managed-thinkpad-extra-buttons.hwdb` is deleted from the source and generated payload. Desktop staging removes a stale installed copy and retains the existing strict hwdb rebuild. Distribution-supplied mappings are not removed.

## Released package, local repository and automatic upgrades

The new Moo/MooX `ExternalSoftware::Servicing::Tomat` adapter resolves the supplied latest-download endpoint through GitHub release metadata. It requires a stable numeric release tag, exactly one `tomat_amd64.deb` asset from the approved repository/tag, a bounded size and a mandatory SHA-256 digest. The artifact is downloaded over the existing verified HTTPS transport and checked against that metadata. Debian package identity, architecture, version and `/usr/bin/tomat` are validated. No `.desktop` file is invented for this CLI application; the existing Debian validator now explicitly permits a CLI-only specification without relaxing GUI specifications.

The Python publisher's automatic release path applies the same Tomat metadata checks. Before publishing Tomat, it requires a regular root-owned executable rather than a symlink or privileged/world-writable payload. The Debian Version must correspond to the verified release tag, optionally followed by a Debian revision. Mismatches and missing hashes retain the last published version and report failure. Normal signed, atomic local-APT publication is reused.

The trust boundary is the upstream GitHub project and HTTPS release metadata. A SHA-256 supplied by the same release source detects byte substitution/corruption relative to that metadata; it is not an independent maintainer signature or a sandbox for Debian maintainer scripts. The existing locally generated APT signature authenticates local publication, not upstream authorship.

The dedicated Tomat upgrade service, success-trigger drop-in and private APT configurations have been removed. The existing persistent weekly `local-apt-refresh.timer` remains unchanged and publishes validated packages only. There is no additional Tomat installation timer, service or private unattended-upgrade pass. Installation of eligible upgrades is left to the normal APT/unattended-upgrades mechanism and the administrator's normal policy.

Policy caveat: the checked-in `52unattended-upgrades` file approves named remote repository sites, but does not approve the managed `file:/var/lib/software/repo` origin. This revision leaves that global policy byte-for-byte unchanged. A host needs its normal administrator-managed policy to allow that origin before unattended-upgrades will install locally published Tomat updates. Local publication alone does not establish upgrade eligibility; no broader origin allowlist has been silently added.

Both packaged `tomat.service` instances (system and global user) are persistently masked before initial installation. The released foreground daemon interface is checked without starting a daemon. Upgrades do not deliberately interrupt an active focus session: an already running daemon uses its loaded executable until the next session or a settings-triggered restart.

Administrator inspection:

```sh
systemctl status local-apt-refresh.timer
journalctl -u local-apt-refresh.service
apt-cache policy tomat
cat /var/lib/software/repo/state/last-refresh.json
```

A manual refresh uses `sudo systemctl start local-apt-refresh.service`; it updates local repository publication only and does not trigger an installation pass. Inspect normal upgrade eligibility with `sudo unattended-upgrade --dry-run --debug` and review failures/holds before changing package policy. This integration intentionally does not fetch or ship a live vendor binary in the repository archive: installation and updates fetch the published `.deb` through the validated adapter.

## Session ownership and configuration

Waybar runs `/usr/local/libexec/labwc-tomat watch`. The controller ensures one `labwc-tomat.service` transient user service, then execs `tomat watch --interval 1 --output waybar`. The daemon is a sibling under the user manager, not a panel-owned daemonized child. Multiple bars can observe the same timer. Restarting Waybar does not deliberately stop the daemon; ending `labwc-session.target` stops its complete cgroup.

The daemon runs `/usr/bin/tomat daemon run` with `Requisite`, `After` and `PartOf` dependencies on the desktop session, `ExitType=cgroup`, `KillMode=control-group`, bounded stop/restart handling, a three-start limit, private runtime ownership, an explicit environment, no inherited X11 display, AF_UNIX-only sockets and process/memory limits. No user-manager `AppArmorProfile=` setting is relied upon: executable attachment supplies AppArmor confinement.

The controller rejects root, unsafe account/runtime/config ownership, symlinks, hard links and oversized or malformed TOML. A private lock serializes daemon creation/settings replacement. Readiness checks validate the socket type, UID, `SO_PEERCRED` PID against systemd's MainPID, and a bounded protocol response. It refuses an unrelated static service using the managed unit name and does not use PID files to kill arbitrary processes. Failed units retain their start-limit state rather than being repeatedly collected/recreated by the watcher.

Initial configuration is `~/.config/tomat/config.toml` (0600): work 45 minutes, break 5, long break 15, three sessions, `auto_advance = "to-break"`, embedded sound at 0.3, notifications enabled with 8000 ms timeout, `{icon} {time}` text and an idle tomato icon. Start presets change work/break durations only; long break, session count and auto-advance remain configured values.

Both `on_break_start` and `on_long_break_start` invoke the fixed `labwc-tomat-hook`, which pauses MPRIS players using playerctl with a 2.5-second bound inside the three-second hook deadline. It never resumes media the user may have paused, rewrites DND state, executes arbitrary shell text or accesses audio hardware directly. Only those reviewed hooks are accepted by the managed TOML validator. Arbitrary custom hooks require a deliberate code/policy review instead of being silently granted execution authority.

Notification/sound settings preserve unrelated TOML values and comments, validate the result, reject ambiguous layouts/concurrent replacement, then atomically replace the file and restart only the managed daemon. The runtime directory is preserved across restart, allowing upstream's saved timer state to remain available. A final session stop removes runtime state. Opening the configuration uses native-Wayland FeatherPad and does not require a valid TOML parse. Editing the file manually requires a daemon restart for startup-read sound/notification/hook options; timer values are re-read on Start. Configurations using extra sound paths may require deliberately reviewed AppArmor read access.

Desktop-user inspection/recovery:

```sh
systemctl --user status labwc-tomat.service
journalctl --user -u labwc-tomat.service
# After fixing the diagnosed configuration or launch failure:
systemctl --user reset-failed labwc-tomat.service
/usr/local/libexec/labwc-tomat ensure
```

## Native menus and confinement

Tomat is immediately to the right of Wayscriber and left of Applications in both bars. Left click toggles pause/resume, middle click skips, and right click opens the GTK menu. The nested Start submenu contains Default, 25/5, 50/10 and 90/15; Settings contains Notifications, Sounds and Open config. Paused CSS uses Tomat's actual phase-specific class names.

The audio menu provides Pavucontrol, output mute, microphone mute, 40% volume and a Whisper submenu for recording, transcribing saved audio, stopping recording (and queuing transcription), and stopping transcription. Existing backends/services remain responsible for audio and recording lifecycle. Existing primary audio-click/scroll actions are preserved.

The notifications module controls the existing Mako daemon. On both output layouts the order is System controls, Notifications, Lock, Power. Left click opens the native menu; middle click toggles DND; right click opens the notification center. Its bell/bell-with-slash icon uses the same font size and button geometry as Lock and Power. The hover fill is warm gold (`#ecb860`) in both normal and DND states. Installed verification requires `mako-notifier >= 1.11` for its JSON list/history interface, failing visibly on an older package instead of shipping a broken history window. It offers DND, dismiss-all-active and a native GTK Current/History window, without installing a second notification daemon. Responses are byte/time bounded; notification content is rendered as plain text, not GTK markup or shell commands. Mako does not expose a general history-purge command: Clear explicitly dismisses active notifications without appending them to history and does **not** promise to purge retained history.

The power button opens a native menu for Lock, Suspend, Reboot, Logout and Shutdown, using the existing `labwc-power-settings` backend. It no longer invokes the Fuzzel power picker. Standalone legacy launchers outside Waybar are left unchanged.

All native menu callbacks use session-bound transient user services. New AppArmor domains cover the controller, foreground daemon/fixed hook and notification UI; the existing editor gets only the Tomat config access needed for safe saving. The desktop's existing configurable AppArmor mode is preserved, including profiles configured to `complain`. This delivery does not silently claim full enforcing-mode runtime qualification. Both new policy files pass offline parser validation.

One existing Waybar installer verification check was corrected to match the already shipped absolute-path **click-release** window-switcher action. The switcher itself and its runtime behavior are unchanged. Profile provenance hashes and tests were updated only where the requested hardware/menu contracts changed.

## Original validation evidence (before the follow-up revision)

The original release run is `validation/tomat-native-menus-20260920/final/summary.json`; its runtime-product hashes identify the prior archive, not the current follow-up archive. Current evidence is under `validation/notifications-followup-20260920/`. It was run after the final MMC parameter, Mako minimum-version and panel callback-count corrections. The preceding run is retained separately for review provenance; see the validation directory README.

| Check | Actual result |
| --- | --- |
| Full installer regression suite | 1,925 tests: 1,874 passed, 48 skipped, **3 baseline failures** |
| Complete tools regression suite | 179 passed; no skips or failures |
| Focused hardware/Tomat/menu suite | 28 tests: 27 passed, 1 Perl dependency skip |
| Existing workspace regression suite | 28 passed |
| Shell syntax/metadata | 285 files, 581 checks, passed |
| Browser, generated build and preseed checks | Passed |
| New native GTK menu XML | All four loaded by real GTK 3 GtkBuilder under Xvfb |
| New AppArmor policy files | Both parsed successfully offline |
| Python helpers and installed verifier | AST parsing passed; Mako version comparisons checked |
| MMC module spelling | Corroborated against the preinstalled Debian module's registered parameter string; no loading or compilation |
| Repository audit | Completed; its dependency-blocked/inventory-only entries are **not** runtime passes |

The final validator returns failure, correctly, because it retains the three baseline IOCost failures. Their exact test names are `test_all_profiles_complete_and_exact_enable_matrix`, `test_both_enabled_profiles_native_staging_and_query` and `test_reported_profile_native_iocost_transaction_through_real_bridge`. No tests were disabled to obtain a green report.

The generated payload contains 1,404 files. Scope comparison retains every original regular file except the explicitly removed hwdb asset; the protected private-Xwayland/Zoom/Discord/Crystal Dock paths remain byte- and mode-identical. The separate delivery checksum and archive-verification record validate the complete tarball, not only its runtime payload.

The untouched original ZIP was extracted separately and exercised for baseline comparison. Its `btrfs-de-dual-flex.env` already sets `IOCOST_CALIBRATE_ENABLE="false"`, whereas three existing assertions expect enabled calibration. Those three failures reproduce on the original code. The profile value and those unrelated assertions are deliberately unchanged; corresponding baseline logs are included. The final full-suite result is not represented as all-green.

Container constraints: no booted Forky/systemd 261.2 user session, physical ThinkPad/IdeaPad/Chromebook, Wayland compositor, live Mako/PipeWire/media path or enforced AppArmor kernel acceptance was available. Perl Moo validation dependencies were absent and are reported as skips; they remain declared by the target package selection. Outbound networking from the execution container was unavailable, so the actual Tomat release `.deb` was not downloaded/executed here. Web review used upstream v2.13.0, the latest release returned during this task. HTTP metadata/download tests use deterministic fixtures; archive tests use clearly labeled synthetic Debian packages, not a substitute Tomat binary.

Before fleet deployment, run a disposable amd64 Forky installation using the complete served repository and verify installer completion, profile-specific module parameters, panel menus, timers/pausing, MPRIS hooks, socket ownership, logout cleanup, stock-unit masks and a real signed-local-repository upgrade. Check AppArmor denial logs in the selected policy mode. The scoped code is implemented; those environment-specific acceptance checks remain outstanding.

## Primary references used for interface decisions

- Tomat release: https://github.com/jolars/tomat/releases/tag/v2.13.0
- Tomat CLI: https://github.com/jolars/tomat/blob/v2.13.0/src/main.rs
- Tomat config/hooks: https://github.com/jolars/tomat/blob/v2.13.0/src/config.rs
- Tomat foreground daemon, socket and saved state: https://github.com/jolars/tomat/blob/v2.13.0/src/server.rs
- Waybar native menus: https://github.com/Alexays/Waybar/blob/master/man/waybar-menu.5.scd
- IdeaPad driver: https://github.com/torvalds/linux/blob/master/drivers/platform/x86/lenovo/ideapad-laptop.c
- IdeaPad optional fan sysfs ABI: https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-platform-ideapad-laptop
- Module parameter prefix expansion: https://github.com/torvalds/linux/blob/master/include/linux/moduleparam.h
- MMC block parameters: https://github.com/torvalds/linux/blob/master/drivers/mmc/core/block.c
- F2FS mount options: https://docs.kernel.org/filesystems/f2fs.html
- Mako controls: https://github.com/emersion/mako/blob/master/doc/makoctl.1.scd
- Unattended-upgrades whitelist semantics: https://github.com/mvo5/unattended-upgrades/blob/master/README.md
- systemd execution/service semantics: https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html and https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
