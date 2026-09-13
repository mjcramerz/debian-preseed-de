# Scoped boot/runtime fixes - 2026-09-13

## Delivery and scope

This complete repository implements the eight requested boot/runtime objectives.
The source changes are limited to those objectives, their installer/firstboot
integration, regression tests, and regenerated delivery products. No kernel,
NVIDIA driver, compositor, Wayscriber, or other application/package was compiled.
`tools/build.py` regenerated the installer archive, manifest and preseed pins; it
is a repository packaging/configuration generator, not a native software build.

The machine-readable source change inventory and validation evidence are in
`validation/boot-runtime-2026-09-13/`. Previous reports in the repository remain
historical records; this document describes this delivery.

The supplied `journalctl` contained 950 NVIDIA-link service start messages,
949 completion messages, three bootprofile starts/completions at 15:08:34, and
an AppArmor reconciliation from 15:08:42 to 15:09:06 (24 seconds). These are
measurements of the supplied old-system log, not a post-change boot benchmark.

## 1. NVIDIA character-device links

Removed `hooks/target/etc/systemd/system/managed-nvidia-char-links.path` beneath
`d-i/forky/`, its staging/enablement, and the firstboot path/watcher requirements.
Installer cleanup removes an obsolete target copy and its old wants symlink.
The existing Python helper and cold-boot oneshot service remain.

The unit now has `StartLimitIntervalSec=30s` and `StartLimitBurst=5`. The existing
NVIDIA-only udev rules retain direct `SYMLINK+="char/%M:%m"` creation and add
`TAG+="systemd"` and
`ENV{SYSTEMD_WANTS}+="managed-nvidia-char-links.service"`. No global `/dev` watch,
udev `RUN+=systemctl`, polling timer, or unlimited restart loop was introduced.
Firstboot verifies boot enablement and the helper's read-only link check rather
than requiring a completed oneshot to remain active.

There is an important systemd distinction: `SYSTEMD_WANTS` starts dependencies
when a device becomes active, not on every change of an already-active device.
The direct udev symlink rule still repairs the individual link on NVIDIA
add/change events. New device activations may request another bounded oneshot.
Coldplug requests can coalesce with the boot job; ordinary unrelated device
activity cannot retrigger it. The intended normal result is the boot
reconciliation, not hundreds of starts. Exact hardware-specific activation
counts were not measured here.

## 2. AppArmor reconciliation and logging

`LoadedState.pm` now provides a bounded loaded-state snapshot and invocation-local
profile-label caching. Labels are derived from the trusted parser rather than
assuming profile filenames equal kernel labels. Disabled-source label discovery
uses an isolated copy, retaining the existing disable semantics.

`Transition.pm` compares desired mode, source state, and loaded kernel state.
When both agree it returns without invoking a mode editor, rewriting the source,
or reloading that source. If only the kernel differs, it reloads that source
with `apparmor_parser -r -T` without touching the correct source or calling aa-*
mode editors. Source changes retain the existing isolated edit, source
verification, and atomic publication. Only mismatching source entries undergo
reconciliation. Disabled profiles are unloaded only when actually present.
Optional include-only sources remain supported, and existing child-profile
semantics are preserved: children must be present and confined but may have
independent enforce/complain modes.

The runner loads configuration once, shares the initial snapshot, refreshes it
between disable/replacement phases when needed, and verifies the final loaded
state again after changes. A no-op pass reuses its initial snapshot. Existing
`--check`, `--check-loaded`, and `--no-reload` contracts remain available.

Pre-login ordering is intentionally retained: the optimization removes redundant
work rather than allowing login before the requested policy is reconciled. No
AppArmor permissions were broadened and no profiles were newly disabled.

Logging uses one sanitized stdout/stderr message, not both Sys::Syslog and a
second print. The unit supplies `SyslogIdentifier=apparmor-managed-modes` and
journal output. Firstboot now invokes only `--check-loaded`, which includes
source verification; the separate preceding `--check` is removed. The final
message reports `mode policy verified reconciled=N`.

## 3. Greeter media-service exclusion

Added four global user drop-in templates:

- `etc/systemd/user/pipewire.socket.d/20-no-greeter.conf.tmpl`
- `etc/systemd/user/pipewire.service.d/20-no-greeter.conf.tmpl`
- `etc/systemd/user/pipewire-pulse.socket.d/20-no-greeter.conf.tmpl`
- `etc/systemd/user/pipewire-pulse.service.d/20-no-greeter.conf.tmpl`

Each adds `ConditionUser=!__INSTALLER_LABWC_GREETER_USER__` in `[Unit]`, rendered
using the configured greeter account. Conditions are not reset, so package root
exclusions remain intact. Both service and socket activation are covered.
WirePlumber's existing exclusions and primary-user audio behavior are unchanged.
Staging, installed-desktop verification, and firstboot checks cover all four.

## 4. Bootprofile once-per-boot lifecycle

`bootprofile-apply.service.tmpl` remains a oneshot and now uses
`RemainAfterExit=yes`. A successful start remains active/exited, so another
ordinary start request does not repeat the application. An explicit restart
still reapplies it.

`install_target_bootprofile_assets()` in `scripts/late/grub.sh` is the single
owner of enablement and uses `stage_target_systemd_unit_enabled`. Its manual
symlink creation is removed. The duplicate enablement in `zram-swap.sh` is
removed. The shared late-command module loader makes the common enabling helper
available before storage-family installation invokes the grub helper.

## 5. Adapter-specific network readiness

`managed-network.service` no longer Wants or orders After
`systemd-udev-settle.service`. It invokes:

```text
/usr/local/libexec/managed-network-run validate --wait-seconds 15
```

The validator checks only the configured Ethernet/Wi-Fi interface names beneath
its expected sysfs root, including readable address/type attributes. One
monotonic 15-second maximum deadline is shared across all selected adapters;
there is no separate full timeout per adapter and no wait for carrier, DHCP,
IP addresses, or unrelated devices. Existing MAC, ARPHRD_ETHER, wireless-type,
configuration and staged-file checks still determine correctness.

The service has a 20-second start timeout. Manual/firstboot `validate` without
the new argument retains immediate checking. CLI input accepts only integers
0 through 15, without shell evaluation. Timeout diagnostics identify the
missing configured interfaces.

## 6. Wayscriber defaults and account installation

Added `etc/skel-desktop/.config/wayscriber/config.toml` under the target tree.
The 629-line configuration covers drawing/erasers/blur, fonts, gestures and
per-button overrides, quick colors, arrows and spotlight, five presets and
optional per-tool settings, performance, history, tablet input, tray/update
behavior, toolbar/UI/status/help styles, click highlights and input HUD,
presenter mode, boards, render profiles, session persistence/autosave limits,
capture, PDF export, and 148 explicit keybinding actions. Optional
output-specific and version-dependent overrides are documented rather than
binding every installed host to one monitor or home directory.

Input HUD is disabled by default and configured for overlay-only input if
enabled. Upstream update checks are disabled because package updates remain
owned by the existing APT integration. No daemon lifecycle, global compositor
shortcut, or environment setting was invented as a TOML option.

The installer stages the file and explicitly includes `.config/wayscriber` in
the primary-account copy allowlist. Existing account ownership/private-home
permission normalization applies, producing
`$HOME/.config/wayscriber/config.toml` owned by that account. Both skeleton and
account copies are verified during installed-desktop/firstboot validation.

The reference is upstream's configuration guide/example reviewed on 2026-09-13.
The existing APT source is unversioned; no package pin or installation mechanism
was changed. TOML parsing and source integration passed, but the final APT
package was not installed or launched here. Consequently this is not a claim
of live schema validation against every present/future Wayscriber release.

## 7. Launcher synchronization observability

The synchronizer accumulates missing managed application identifiers and logs,
for example:

```text
desktop_launcher_sync user=desktop home=/home/desktop processed=0 skipped_missing=2 missing=postman,sleek skipped_invalid=0 invalid=none ...
```

Absent optional applications still do not fail synchronization. A present file
without a Desktop Entry section is reported separately as skipped_invalid;
missing identifiers therefore correspond specifically to missing expected
.desktop files. Existing fatal publication/security errors remain errors.

## 8. GRUB record-failure timeout

Changed `GRUB_RECORDFAIL_TIMEOUT` to `500` in all three shell-generated writers
in `scripts/late/grub.sh` and in the canonical
`etc/default/grub.d/05-bootprofiles.cfg.tmpl`. No managed writer retains `-1`.
Other boot-menu and recovery settings are unchanged.

## Validation performed

| Check | Result |
| --- | --- |
| New scoped regression suite | 28 tests passed. |
| Shell parser checks | 267 shell files, 545 parser checks passed. |
| Preseed checks | 59 preseed files passed; all four generated command values survived private debconf read-back. |
| NVIDIA udev rule | Native `udevadm verify`: one file passed. |
| Changed system units | Native `systemd-analyze verify`: four units passed using isolated dependency/executable fixtures. |
| PipeWire drop-ins | Native unit parsing passed for all four rendered drop-ins with fixture base units. |
| Changed Python | AST parsing passed. |
| Wayscriber TOML | Python tomllib parsing passed; staging/account-copy integration checked. |
| Delivery products | Payload regenerated; `tools/build.py --check` confirms current snapshot, pins and preseed. |

The stripped-down container lacks Moo/MooX/Types::Standard. The new Perl
control-flow tests explicitly opted into their test-only constructor adapter;
AppArmor tools and loaded kernel state were fixtures. These tests exercise the
actual application modules, including no-op, source-only/kernel-only drift,
disable/unload, read-only verification, error paths and logging; they do not
validate the real Moo type system or load kernel policy. The adapter is never
installed and is excluded from the payload. Normal test execution uses actual
Moo dependencies when available, otherwise reports explicit skips unless the
adapter is requested.

The broader existing-suite attempt completed 652 tests across 25 modules;
21 modules completed successfully. Four modules reproduced failures in the
untouched uploaded code: a missing historical AppArmor log/incident fixture,
missing Moo dependencies for external-software tests, and pre-existing profile
provenance hash mismatches. The untouched baseline also had stale generated
build products; this delivery's regenerated products pass that check. Existing
bootstrap/debconf integration runs did not complete within validation bounds.
These unrelated fixtures, dependencies, and provenance records were not changed
to manufacture a green full-suite result. Summary JSON records the outcomes.

No post-change Debian boot, GPU hotplug, physical adapter discovery, greeter
session, AppArmor kernel enforcement, or Wayscriber GUI session was exercised.
The unit fixtures establish parser/structural validity, not a real boot graph or
package-user-manager acceptance test. Actual startup durations and NVIDIA
invocation counts therefore remain deployment acceptance checks.

## Deployment and installed-host acceptance

Publish the complete repository atomically, including the regenerated
`d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg`. Mixing an old
payload or manifest with new preseed pins will fail integrity checks.

After a fresh installed-host boot, inspect:

```sh
sudo journalctl -b -u managed-nvidia-char-links.service --no-pager
sudo systemctl cat managed-nvidia-char-links.service
sudo systemctl show bootprofile-apply.service -p ActiveState -p SubState
sudo journalctl -b -u bootprofile-apply.service --no-pager
sudo journalctl -b -u apparmor-managed-modes.service --no-pager
sudo /usr/local/libexec/apparmor-managed-modes-run --check-loaded
sudo systemctl cat managed-network.service
sudo journalctl -b -u managed-network.service --no-pager
```

Expect no installed NVIDIA `.path` unit, no NVIDIA starts from unrelated `/dev`
changes, bootprofile active/exited after one successful boot application, and
AppArmor `reconciled=0` when sources and loaded modes already match. An
intentional `sudo systemctl restart bootprofile-apply.service` should cause one
additional application. Check the primary user's Wayscriber file and inspect
the greeter user-manager journal to confirm PipeWire/Pulse units are skipped by
the rendered conditions. Optional missing launchers should be named, not cause
session failure. This repository change is not an automatic live-host upgrade;
existing running user managers/services need their normal reload/reboot process
when deploying target files manually.

## Upstream references

- systemd device activation semantics:
  https://manpages.debian.org/unstable/systemd/systemd.device.5.en.html
- systemd oneshot/RemainAfterExit semantics:
  https://manpages.debian.org/testing/systemd/systemd.service.5.en.html
- Why global udev settling is discouraged:
  https://manpages.debian.org/testing/systemd/systemd-udev-settle.service.8.en.html
- Wayscriber configuration guide and example:
  https://github.com/devmobasa/wayscriber/blob/main/docs/CONFIG.md
  https://github.com/devmobasa/wayscriber/blob/main/config.example.toml
