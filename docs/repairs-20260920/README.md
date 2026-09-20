# Desktop session repairs - 2026-09-20

## Scope and acceptance status

This is the complete installer repository, not an overlay-only patch. Changes are confined to the eleven requested desktop/session issues and the tests and packaging needed to deliver them. Existing source-build facilities were not extended. No upstream application source was patched. The existing Zoom/Discord-only private Xwayland architecture is retained.

The supplied logs establish several concrete configuration/policy defects. They do **not** establish a unique cause for the host compositor's KMS `EBUSY` failures. This revision corrects the demonstrated graphics-backend inconsistency, but **does not claim the atomic-commit failure is conclusively fixed**. Physical ThinkPad input, rendered frames, actual wlsunset gamma adjustment, and all applications under enforced AppArmor require target acceptance testing. The verification container is not the user's Forky/systemd 261.2 installation.

The dated reports in `validation/2026-09-20/` describe this revision. Older validation directories were part of the input and are retained, but are not evidence for these changes.

## 1. ThinkPad Extra Buttons

`hooks/target/etc/udev/hwdb.d/90-managed-thinkpad-extra-buttons.hwdb` clears the 22 inherited `KEYBOARD_KEY_*` overrides rejected with `EVIOCSKEYCODE: EINVAL` in `event4`. The match uses the input name and Lenovo DMI vendor, not the unstable `/dev/input/event4` number. Empty properties remove the invalid udev assignments; they do not assign `KEY_RESERVED`, disable the device, or replace the driver's sparse keymap with guessed scan codes.

The installer stages the file to `/etc/udev/hwdb.d`, normalizes its public parent directories and invokes `/usr/bin/systemd-hwdb --strict update` inside the target. The database is therefore ready for first boot. Existing brightness/volume handling is unchanged. Native Labwc key bindings are added for microphone mute, lock, display selection, wireless/network controls, battery/power controls, launcher keys and notification restore. Sleep and power keys remain owned by logind under its existing policy; Labwc does not add a second suspend/power handler.

The regression fixture compiles an isolated hwdb and checks matching and nonmatching devices. `systemd-hwdb query` displays empty values in the raw database; sd-device removes them when importing properties. No physical key events or exact machine DMI/modalias capture were supplied, so all-key hardware acceptance is not claimed.

## 2. Graphics consistency and the atomic-commit timeline

The journal records Chromium's Dawn trying Vulkan at **13:29:03**, with `VK_ERROR_INCOMPATIBLE_DRIVER`, followed by an OpenGL adapter discovery failure. This is inconsistent with the project's existing ANGLE/OpenGL/GLES policy. Native browser argument builders and ChatGPT's existing launch/intel/nvidia argument sets now explicitly select `--use-webgpu-adapter=opengles`. The GPU sandbox, hardware rendering, compositor renderer, driver packages and kernel policy are not disabled or replaced. Rust's `WGPU_BACKEND` is not a replacement for Chromium's Dawn selection.

The actual `Atomic commit failed: Device or resource busy` lines come from **host labwc PID 6638**, connector `eDP-1`, at 13:05:05, 13:05:34, 13:05:44, 13:09:06, 13:30:02, 13:30:04, 13:30:06, 13:30:26, 13:47:28 and 13:56:06. ChatGPT was already running around 13:00; Liferea starts at 13:30:01, Chromium/Edge activity occurs nearby, and the supplied Zoom Cage line at 13:32:34 is an **INFO extension listing**, not an atomic error. Temporal proximity alone does not identify a causal application.

No speculative `WLR_DRM_NO_ATOMIC`, blanket software-rendering, modifier disablement, GPU sandbox removal, new driver build or private-Xwayland modification is introduced. Reproduce the KMS issue on the target before selecting any driver/compositor workaround. This objective is an acceleration-consistency correction, **not a verified KMS repair**.

`validation/2026-09-20/private-xwayland-preservation.json` contains original/current byte comparisons for 13 protected runtime/configuration files and the comparison of all non-ChatGPT Electron launch/intel/nvidia arguments. The compatibility AppArmor child receives only four read-only CPU `base_frequency` paths requested in the audit.

## 3. Telegram Desktop

The Telegram log's 11:31:40 application timestamp is two hours behind the matching 13:31:40 journal/audit event. The correlation uses the executable, path and operation as well as that timestamp offset; the attached application log does not itself state a timezone. Its fatal publication of `log.txt` coincides with an AppArmor temporary-inode link lookup failure. The existing Telegram directory permissions already include link/write permissions. `mediate_deleted` is added to the Telegram profile so the unnamed/deleted temporary inode can be mediated during Qt's atomic publication. No broad HOME write rule, Telegram data deletion, fallback to X11, or application patch is used.

## 4. Failed service entries and notifications

`Failed` contains eleven health-notifier activations reported twice each, plus one `pam_systemd(sudo-i:session)` root-runtime-bus warning. Those are distinct issues.

The health checker now uses a small headless `labwc-notification-send` transport, which calls the Notifications D-Bus method through `busctl`. It accepts only the needed notify-send-compatible options, passes lexical arguments without a shell, bounds content/diagnostics/timeouts, escapes markup, includes category and local timestamp, and reports success only after a positive daemon notification ID. It tries at most twice; a lost reply can produce an at-least-once duplicate, not a false acknowledgement. A failed transport leaves queued events and state unacknowledged for the next path/timer activation. Other health checks can continue, while the cycle reports a genuine transport failure instead of silently losing an event. Both the coalescing child and any in-flight bounded delivery are reaped on cancellation. The existing systemd control-group lifecycle remains.

Mako's popup height is increased to 320; the format includes application identity as well as summary and body. Critical notifications remain persistent. The implementation does not manufacture a successful notification when Mako or the session bus is unavailable. The old log suppressed the notifier's stderr, so the exact original transport failure is not recoverable from `Failed` alone.

For `sudo -i`, a root-owned PAM environment file sets `XDG_SESSION_CLASS=none` immediately before the existing `common-session` include. The installer validates the regular, root-owned, non-writable PAM file, requires the expected include once, and applies an atomic, idempotent configuration insertion. It does not modify authentication/account policy or grant access to `/run/user/0/bus`. This uses systemd's supported non-registering session class for nested session handling. Unknown PAM layouts stop installation rather than guessing.

## 5. Waypaper and persistent wallpaper ownership

Waypaper keeps its unmodified `backend=none` configuration and post-command. `labwc-wallpaper-save` becomes a compatibility entry point into `labwc-wallpaper-control save`. Requests are published atomically under a private state directory, using pinned directory descriptors, no-follow opens, ownership/mode/link checks, a serialized write lock, file and directory fsync, and a bounded root-owned PNG/JPEG selection. A FIFO or symlink must not block or redirect a request.

`swaybg.service` now owns one persistent supervisor rather than being restarted for each click. Inotify wakes it on a new request. A 250 ms debounce selects the latest request; repeated selections of the same active image do not respawn a backend. A second supervisor is excluded by a held lock. The previous child remains until the replacement survives a 500 ms liveness probe, and a failing replacement leaves the previous wallpaper running. Recovery backs off between two and thirty seconds, and fresh selections wake it immediately. Children are terminated, waited for, and killed only after their bounded stop grace period. There is no process-name killing or detached wallpaper daemon.

The liveness probe is **not a first-frame Wayland acknowledgement**; no claim of flicker-free presentation on every display is made. Real inotify and process-lifecycle tests use a stub backend; actual swaybg rendering remains a target test. Invalid requests leave the existing background available.

## 6. Main Menu categories

Exact desktop identity overrides place `QoreDB.desktop` and known spelling variants in Development; Qalculate GTK/Qt in Office & Productivity; and RetroArch's supported desktop IDs in Games. Vendor `System`/`Emulator` combinations no longer misclassify RetroArch. The existing GIO visibility, tombstone, TryExec and launch semantics are retained. Arbitrary localized names are not used as executable identities.

## 7. Computer Management geometry

The Computer Management process tree exports `LABWC_FUZZEL_GEOMETRY=computer-management`, independently of the logging scope. Root menus, nested menus, action prompts and Android child menus therefore select Main Menu configuration and geometry instead of a compact menu configuration. Explicit compact width/line overrides are superseded by the management context; the flag is not exported into the systemd user manager.

All thirteen profiles define:

```sh
LABWC_FUZZEL_COMPUTER_MANAGEMENT_WIDTH="$LABWC_FUZZEL_MAIN_MENU_WIDTH"
LABWC_FUZZEL_COMPUTER_MANAGEMENT_LINES="$LABWC_FUZZEL_MAIN_MENU_LINES"
LABWC_FUZZEL_COMPUTER_MANAGEMENT_INTERNAL_WIDTH="$LABWC_FUZZEL_INTERNAL_MAIN_MENU_WIDTH"
LABWC_FUZZEL_COMPUTER_MANAGEMENT_INTERNAL_LINES="$LABWC_FUZZEL_INTERNAL_MAIN_MENU_LINES"
```

These values are validated and rendered to the target defaults, with safe fallbacks for minimal profile fixtures. Existing internal/external fonts and Main Menu padding are reused. Explicit terminal/fzf mode is unchanged; these Fuzzel dimensions do not apply to a terminal UI. The regression test runs the actual shell wrapper with a fake Fuzzel binary, checking internal/external and nested logging contexts.

## 8. Native colour adjustment (superseded implementation)

The subsequent requested revision replaces the entire managed Gammastep indicator
and its GeoClue dependency with Debian's `wlsunset`. Every profile now includes
the ten `WLSUNSET_*` settings, enabled with Malmo latitude/longitude by default.
A guarded short-lived controller submits the long-running native daemon as a
session-bound transient user service after validating the real Wayland identity.
There is no indicator process, location provider or static colour-daemon unit.

See `../WLSUNSET-FOLLOWUP-20260920.md` for settings, lifecycle, security boundaries,
exact retirement scope and current verification evidence. Earlier validation
snapshots mentioning the old indicator describe the previous delivery only.

## 9. Duplicate Labwc settings

The canonical project desktop entry is named Labwc Tweaks and is marked NoDisplay because the fixed Desktop Settings submenu already contains its action. Application enumeration excludes the two known duplicate Tweaks desktop identities, leaving that one fixed action. Unrelated applications with a settings-like display name are not hidden.

## 10. Thunar preferences and removable-media dialogs

GTK3 `gtk-dialogs-use-header=false` is staged in the user's GTK settings, together with the corresponding Xfce `Gtk/DialogsUseHeader=false` channel setting. This uses the libxfce4ui/GTK configuration path for the requested dialogs rather than modifying Thunar, injecting a replacement library or building a patched package.

This is not a claim that Labwc can force every arbitrary GTK4/libadwaita client into server-side decoration against that client's own implementation. Such a system-wide absolute guarantee would conflict with the no-source-patching constraint. The targeted Thunar/libxfce4ui dialogs need visual acceptance on the installed package version.

## 11. AppArmor review and enforce-mode boundary

Every physical line of the supplied audit log was processed, retaining duplicates. The source has 10,817 newline-terminated records: 10,419 ALLOWED audit events, four DENIED events, 392 STATUS records and two kernel-command-line context records. There are 10,423 actionable audit records, 9,330 file-class records and 1,093 non-file records across 26 original profile labels. A trailing empty split is not an event.

The source digest, counts and limitations are in `apparmor-review-summary.json`. `apparmor-record-dispositions.jsonl` has one disposition for every actionable source record, indexed by physical source line. It avoids republishing user paths, remote endpoints, messages and audit contents. The original upload is the reference for those indices.

Corrections include Qt temporary-inode mediation; exact application configuration/state/font reads; typed executable transitions for wpctl, Spotify's launcher trampoline, WebKit helpers and glycin's namespace builder; bounded hardware metadata reads; reciprocal signal/ptrace-read permissions; and separation of FreeRDP's network client from the privileged clipboard FUSE helper. Namespace capabilities remain in the builder/helper domains, not in ordinary GUI/network clients. Root bus access and arbitrary home/system write permissions are not added.

Four classes intentionally remain denied: optional writes to packaged Python bytecode, media primary-DRM-node probes, generic launcher probes of private compatibility modules, and the unprivileged direct FUSE mount probe. The clipboard helper has narrowly scoped mount/unmount permissions; the network client does not receive SYS_ADMIN. Complain-mode `//null-*` descendants are not copied into policy as profile names.

A conservative static checker found a candidate rule/transition or an intentional denial for every recorded file access. That checker approximates AARE, owner matching and transitions; it is **not** the kernel's enforcement engine. Offline compilation and these dispositions cannot establish that every unexercised application feature is allowed. Test fresh starts, documents, downloads, clipboard, media, conferencing and logout on the target before promoting the complete desktop to enforcement. No policy is made unconfined or left in complain mode merely to hide a failure.

## Build and publication

From the repository root:

```sh
python3 -B tools/build.py
python3 -B tools/build.py --check
python3 -B tools/validate.py --output-dir validation/local-session-repairs
```

Serve the **whole rebuilt repository atomically** using the project's existing deployment procedure. The shipped payload, manifest and preseed pin are rebuilt from the changed sources. Do not copy a new preseed over an old payload, and do not treat a source edit as deployed until the build and publication are complete. This archive is for unattended installations, not an unreviewed in-place migration over a running desktop.

See `TARGET-ACCEPTANCE.md` for non-destructive target checks and the unresolved hardware gates.

## Primary references consulted

- systemd keyboard hwdb and property import semantics: `https://github.com/systemd/systemd/blob/main/hwdb.d/60-keyboard.hwdb`, `https://github.com/systemd/systemd/blob/main/src/libsystemd/sd-device/sd-device.c`.
- Kernel ThinkPad sparse keymap: `https://github.com/torvalds/linux/blob/master/drivers/platform/x86/lenovo/thinkpad_acpi.c`.
- Chromium Dawn backend selection: `https://chromium.googlesource.com/chromium/src/+/lkgr/gpu/command_buffer/service/webgpu_decoder_impl.cc`.
- AppArmor deleted-file mediation discussion: `https://gitlab.com/apparmor/apparmor/-/merge_requests/1272`.
- systemd suspend/power-key ownership: `https://manpages.debian.org/testing/systemd/logind.conf.5.en.html`.
- systemd PAM session classes: `https://manpages.debian.org/testing/libpam-systemd/pam_systemd.8.en.html`.
- GTK3 header-bar setting: `https://docs.gtk.org/gtk3/property.Settings.gtk-dialogs-use-header.html`; libxfce4ui implementation: `https://gitlab.xfce.org/xfce/libxfce4ui/-/blob/master/libxfce4ui/xfce-titled-dialog.c`.

These references describe interfaces and mechanisms; they are not evidence that this revision has run on the supplied ThinkPad.
