# Installed-system evidence and acceptance — 2026-09-29

The supplied `journalctl` capture is the 10:28 boot. `managed.zip` and
`managed1.zip` capture the same later 10:35 boot; the latter continues further
into the session. They are successive views, not three separate failures.

## WirePlumber and display hotplug

At 10:28:58–59 the output watcher disables the internal panel and activates
HDMI-A-2. WirePlumber enumerates HDMI ALSA nodes at the same time and logs one
`Object activation aborted: proxy destroyed` event. The supplied trace does
not show a WirePlumber service crash or continued audio failure. The managed
policy deliberately disables selectable HDMI/DisplayPort audio nodes, so an
unproven change to that policy would risk the installed audio requirement.

On the installed system, switch outputs repeatedly while recording the user
journal for `wireplumber.service` and `pipewire.service`. Confirm the intended
internal capture and playback devices remain available with `wpctl status`,
that the default microphone remains muted, and that HDMI audio nodes are not
selectable. If a repeatable failure remains, capture the WirePlumber debug
journal and the active node/device identifiers around the transition before
changing the rule or service ordering.

## Discord private compatibility session

Both supplied Discord launches select Cage's private
`/opt/xwayland/usr/bin/Xwayland`; both then print `Failed to open /dev/null`
and Chromium's zygote exits with status 133. The outer Bubblewrap sandbox
creates a private `/dev` and selectively binds its camera/render nodes. The
inner application-only socket-mask sandbox previously remounted that tree
with a regular bind, which can mark character devices `nodev`. It now uses a
device bind of the *outer sandbox's private* `/dev` and checks that `/dev/null`
opens as the expected character device before starting Discord or Zoom.

Run both applications after installation, including Discord's `intel` and
`auto` paths, then verify the transient user units exit normally on close.
Confirm the host Wayland socket remains masked inside the application and
that no public `/usr/bin/Xwayland` is installed or launched. The native Labwc
log's attempt to find `/usr/bin/Xwayland` is expected under this private-only
policy; the Xwayland binary and its policy were not changed.

## CrowdSec status

The first boot reports that `cscli console enroll` accepted a request, while
the later boot reports that the machine is not enrolled in the Console. That
can occur while Console approval is pending. Firstboot now records
`pending-approval` after a successful request, rather than claiming that
Console enrollment is complete. Approve the engine in the CrowdSec Console,
then verify its status and restart CrowdSec as directed by the Console.

The later boot also contains a transient DNS lookup failure and parser grok
warnings; its local CrowdSec API and firewall bouncer subsequently exchange
successful requests. Those observations do not justify changing vendored
parser expressions or disabling the local bouncer.

## Follow-up AppArmor and NVMe evidence

The later AppArmor capture records `ALLOWED` (complain mode) for create/open
and lock operations on `/run/user/1000/labwc-clipboard-wayland-1.lock` in the
Zoom/Discord Bubblewrap child. The child policy now grants owner-only `rwk` on
the corresponding managed Cage lock names. In enforce mode, repeat clipboard
copy in both directions in Zoom and Discord and check for denials; the audit
entry alone does not prove that enforce-mode operation has passed.

The storage capture contains a correctable PCIe Physical Layer receiver error
on the `15b7:5006` NVMe endpoint at `0000:2e:00.0`. The existing
`74-nvme-link-idle.rules` already targets exactly that vendor, device, and NVMe
class, leaves AER enabled, and disables supported link-idle states only when
the kernel exposes their controls. The two supplied lines do not show the
controls' actual values or whether the error count continues to rise. On the
installed host, record `/usr/local/sbin/nvme-pcie-status` output twice across
the workload and compare `aer_correctable` and `policy_state`; retain the
kernel journal around each increment. `link-idle-still-enabled` needs a rule
application investigation; `unavailable-kernel-or-firmware-owned` means that
the rule cannot claim a mitigation; new errors even with available controls
disabled need firmware, link, and drive investigation. Do not suppress AER,
reset the live storage controller, or apply a global PCIe override to make a
correctable warning disappear.
