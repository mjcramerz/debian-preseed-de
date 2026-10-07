# Desktop incident review — 2026-09-26

This report covers the supplied `journalctl`, `fail`, `libinput`, `pavu`,
`managed.zip`, and `installer-state.zip` captures. The archive is an installer
source snapshot for subsequent Debian Forky installations. It does not modify
the already installed host. The private Xwayland design for Zoom and Discord
was not changed.

## Changes made

* Removed `DRI_PRIME=0` from the integrated Intel launch policy and the
  qBittorrent launcher. The generic launcher already removes inherited
  `DRI_PRIME`; the default GPU is now selected by leaving it unset.
* Added a system Code desktop entry routed through the existing managed app
  launcher, with D-Bus activation disabled. The user launcher synchronizer
  reads that entry; exact Code executable transitions in the terminal and
  managed app profiles avoid the observed nested AppArmor null profiles.
* Addressed the other *observed* complain events with scoped Code, Waypaper,
  Qt temporary file, Telegram hardware/proc, FeatherPad configuration,
  KeePassXC probe, and Bubblewrap `unshare` rules. Waypaper's wallpaper save
  helper retains the host UID view so its root-owned path checks work.
  Waypaper cannot execute a second `swaybg` alongside the existing session
  supervisor, including when its saved backend changes from `none`.
* Added `gir1.2-secret-1` for Liferea's `Secret` introspection namespace.
* Made the four requested Waybar button hover treatments equal. The six
  requested status modules use one background before and during hover;
  their hover shadows are transparent and only the outline changes.
* Set GTK, GNOME/GLib, Gnote, and Qt6ct defaults to dark, with a dark Qt Quick
  Material style for Hyprpolkit. The GTK3 notification center follows those
  GTK defaults; Mako's existing palette is already dark.

The AppArmor captures include repeated Code and Waypaper **null learning
descendants**, which are symptoms of missing process transitions. They also
include direct events for the specific paths above. A complain log is not a
complete permission inventory: the rsyslog action reported lost messages, and
workloads not exercised in the capture cannot be inferred from it. Explicit
denials for the second wallpaper renderer are intentional; allowing that
renderer would undermine the session's single-owner wallpaper policy.

## Remaining host-dependent failures

* At 17:25:13, rsyslog reported that `rsyslog-size-rotate` exited 1 and then
  lost AppArmor messages. The capture omits the helper's error text and the
  installed files' original owner/group information. This revision cannot
  identify why its fail-closed ownership, lock, or rotation checks refused the
  operation. The rotation policy was not weakened or made to discard records.
  Check the actual helper stderr and `stat` of the output, retained archives,
  lock, and ancestors on the installed host before adjusting that policy.
* The eDP-1 atomic `EBUSY` occurred once near session startup and again near
  the overlapping Waypaper renderers. Preventing the second renderer addresses
  that concrete source of contention; whether the startup error persists
  requires a live DRM/kernel trace on the target GPU.
* A 23 ms libinput dispatch delay means the compositor did not process that
  event on time. Removing Code/Waypaper audit floods and the duplicate renderer
  may help, but the capture does not establish the latency cause. The existing
  compositor CPU/IO weights remain in place. Confirm with live compositor and
  scheduler measurements before changing priority or driver settings.
* Foot's PTY slave received SIGHUP. One `foot -e ncdu /` unit exited 1;
  return code 1 can also be a real command failure. The existing narrowly
  scoped success statuses were kept so unexpected exit codes remain visible.
* Obsidian's missing per-vault JSON file is logged as `Ignored`. Its ID and
  contents are user state; manufacturing that file in the installer would be
  unsafe. Its first successful vault initialization needs live observation.
* Code via Fuzzel and all complain-mode profiles still require target-side
  runtime verification under AppArmor enforce. No such verification was
  possible from this archive alone.

## Offline validation and limitations

`tools/check_themes.py` validated 1,993 inputs and 101 tokenized files. The
focused launcher suite passed 30 tests, managed app review passed 21, desktop
integration passed 28, and the theme suite passed 23 (one graphical test
skipped). The source validator rebuilt 1,605 payload files and
`tools/build.py --check` reported the snapshot, manifest and pins current.

This runner lacks BusyBox. For artifact generation alone, a **temporary
workspace-only adapter** invoked `/bin/dash` at both shell syntax boundaries
where `tools/build.py` normally invokes BusyBox `ash`. That adapter is outside
this repository and the release archive. This establishes deterministic
products and `dash` syntax only; rerun the unmodified `tools/build.py --check`
with a real BusyBox before publishing to installer hosts. This runner also
lacks `apparmor_parser`, a live Forky compositor/GPU, and an enforcing kernel;
the policy has not been loaded or certified under enforce here. Tests needing
`/var/lib` fixture directories, `/proc/self/fd`, native rsyslog, or system
ownership changes fail in this sandbox and are not counted as passes. No
systemd 261.2 boot or full unattended install was performed.
