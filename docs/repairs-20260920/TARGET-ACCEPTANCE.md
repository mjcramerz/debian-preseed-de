# Target acceptance - run after a fresh installation

Run user commands in the actual managed Wayland desktop session. Run administrative commands only where marked. Do not enable all AppArmor profiles globally until the application matrix below has been exercised with a recoverable local administrator session.

## Baseline and staged artifacts

```sh
systemd --version
labwc --version
dpkg-query -W systemd udev apparmor labwc wlsunset thunar libxfce4ui-2-0
systemctl --user --failed
systemctl --failed
cat /etc/udev/hwdb.d/90-managed-thinkpad-extra-buttons.hwdb
cat /etc/default/labwc-wlsunset
```

Confirm the target is the expected Forky/systemd 261.2 deployment. The validation container used different installed system packages and did not boot this target.

## ThinkPad input

Do not assume the device remains event4. Discover the current device:

```sh
for device in /sys/class/input/event*; do
    [ "$(cat "$device/device/name")" = 'ThinkPad Extra Buttons' ] || continue
    printf '%s\n' "$device"
    udevadm info --query=property --path="$device"
done
journalctl -b -u systemd-udevd --no-pager | grep -F EVIOCSKEYCODE
wev
```

In wev, exercise actual Fn keys and verify expected native keysyms and one action per press. Brightness/volume should retain the existing behavior. Check lock, suspend, network/display menus and microphone mute. Do not add guessed scan codes or apply a live udev trigger to every input device. If firmware exposes another keysym, retain its evidence before making a machine-specific mapping.

## Persistent wallpaper and notifications

```sh
systemctl --user status swaybg.service mako.service labwc-health-notify.service
systemctl --user show swaybg.service -p MainPID -p NRestarts -p ActiveState -p SubState
/usr/local/libexec/labwc-notification-send -a 'Acceptance check' -u normal -c system.health -- \
    'Notification transport' 'A returned notification ID is required for success.'
journalctl --user -b -u swaybg.service -u mako.service -u labwc-health-notify.service --no-pager
```

Open Waypaper and quickly choose several installed wallpapers. Verify the last choice wins, the supervisor's MainPID is stable, NRestarts does not increase per click, and there is no accumulation of old backend children. Close Waypaper and confirm the selected wallpaper persists; log out/in and confirm restoration. Rendering and first-frame presentation must be visually checked.

For notification retries, use the shipped fixture tests rather than injecting false root security events on a production machine. The test suite covers successful delivery, one retry, permanent failure, unacknowledged events, and acknowledgement only after successful delivery. Test an ordinary target popup and inspect the real bus/Mako journal if it fails.

As an administrator, run `sudo -i`, exit it, and check that the PAM root-bus warning is absent while authentication remains normal. Inspect `/etc/pam.d/sudo-i` to confirm only the scoped environment insertion was made.

## Native wlsunset and GUI settings

The profiles default to enabled solar calculation at Malmo coordinates. In the
real managed desktop session, as its user:

```sh
labwc-wlsunset check
labwc-wlsunset status
systemctl --user show labwc-wlsunset.service \
    -p Transient -p MainPID -p ExecStart -p Environment -p PartOf -p BindsTo -p NRestarts
journalctl --user -b -u labwc-wlsunset.service --no-pager
```

Expect `Transient=yes`, one `/usr/bin/wlsunset` main process, the actual host
Wayland display/runtime directory and no inherited X11/loader selectors. Run
`labwc-wlsunset start` twice and verify MainPID remains unchanged. Change valid
coordinates/temperatures only through the root-owned installed configuration
(or the installer profile before deployment), run `labwc-wlsunset restart`,
and inspect the generated command and actual colour adjustment. Run
`labwc-wlsunset stop` and verify the process exits and display gamma resets.
Set `WLSUNSET_ENABLED="false"` then restart: no managed daemon should remain;
set true and restart to restore it. Invalid replacement configuration must be
rejected without stopping the previous active daemon.

Check external-output hotplug, DPMS resume, log out/in and compositor shutdown
for correct ownership and no leftover colour daemon. Check the service journal
for unavailable gamma-control support or rejected outputs: a successful service
exec does not prove colour adjustment. Do not run another gamma client at the
same time. This feature must work without a GeoClue service or internet location
request. In enforced AppArmor, verify both the daemon and compositor can exchange
the temporary gamma-ramp FD without new DENIED records.

Hover the Waybar window-switcher and compare it with Menu, workspace, wayscriber
and applications buttons on internal and external displays. They must share the
same warm-gold hover gradient and dark foreground; normal-state icons are unchanged.

Open Thunar Preferences and Removable Drives and Media: inspect that they use the compositor titlebar. Inspect Main Menu categorization and that only one Labwc Tweaks action is visible. Compare Main Menu with Computer Management root, child, Android, confirmation and input menus on the internal and an external display. Explicit terminal/fzf mode is not a graphical geometry test.

## Graphics and KMS: unresolved acceptance gate

Do not infer that a new Electron launch option proves an atomic-commit repair. Record a start time, then separately exercise ChatGPT, Zoom, Chromium, Edge, Liferea and RetroArch, plus wallpaper changes and display hotplug. Keep exact application launch times.

```sh
systemctl --user show labwc-compositor.service -p MainPID -p Environment
journalctl --user -b -u labwc-compositor.service --no-pager
journalctl -b --no-pager | grep -E 'Atomic commit failed|VK_ERROR|EGL_BAD|labwc-zoom-cage'
ps -eo pid,ppid,comm,cgroup | grep -E 'labwc|cage|Xwayland|zoom|Discord'
```

Check native-browser diagnostics for the intended ANGLE/OpenGL/GLES/Dawn adapter and hardware rendering. Verify that Xwayland exists only in the private Zoom/Discord runtime and is torn down with its owner. Do not enable global Xwayland to make a test pass.

A recurring host-labwc EBUSY means **this gate has failed**. Preserve kernel/DRM messages, compositor debug output, connector modes/refresh/VRR state and app timestamps. The supplied material did not identify the responsible driver/compositor transaction; no speculative atomic-KMS disablement is shipped.

## AppArmor: enforcement promotion gate

Use the project's existing managed mode mechanism; do not bypass its boot/session sequencing. First ensure every changed policy compiles on the **target's** installed AppArmor parser and features ABI. Keep a recovery administrator session available, and promote a controlled set of application profiles at a time.

Exercise Telegram initial launch/relaunch and log rotation; editor document and preference atomic saves; qimgv image browsing; Liferea images/WebKit; Spotify launch/quit; wpctl hotkeys; system monitoring against the hardware-tuning client; all menu actions; Waypaper bursts; notifications; and wlsunset start/stop/restart. For FreeRDP, test text and file clipboard with the installed FUSE helper, a connection and a disconnect. Test Zoom and Discord audio, video, screen sharing and teardown without changing their private-Xwayland runtime.

After each scenario review the time-bounded AppArmor audit for both DENIED and complain-mode ALLOWED entries. The source-log disposition file is a review trail, not an authorization generator: never automatically translate a new audit log into broad allow rules. In particular, do not grant system-directory writes, arbitrary SYS_ADMIN to GUI clients, or access to private compatibility code in response to optional probes.

Only promote the complete session once all required workflows pass. The shipped offline compile and fixture results cannot certify unexercised target features.
