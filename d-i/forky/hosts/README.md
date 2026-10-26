# Host environments

Every deployable profile is directly in `profiles/`. Named profile classes map
to `profiles/<class-name>.env`; the internal logical identifier is
`override-<class-name>`. Removed class names and duplicate desktop profiles are
not aliases and are no longer supported.

| Disk family | Default | Hardware choices | Preserving other installed systems |
| --- | --- | --- | --- |
| NVMe / Btrfs | `btrfs-de` | `btrfs-de-p15s`, `btrfs-de-flex` | Append `-duo` to any of these three names |
| eMMC / F2FS | `f2fs-de-x360` | `f2fs-de-hp14` | Append `-duo` to either name |

The `-duo` suffix denotes a multi-OS profile, not a limit of two operating systems.
These profile classes require `addon/dualboot` (the short class token is
`dualboot`). Supply the existing `dualboot_efi=<slot>` and
`dualboot_debian=<first-Debian-slot>` parameters. The installer preserves the
existing slots before that first Debian slot and reuses the explicitly selected
ESP; it does not discover or relocate arbitrary interleaved operating systems.
Never guess these slot numbers. A duo class without the preservation addon is
rejected before partitioning rather than silently becoming a whole-disk install.

## Composition order

```text
profiles/<selected>.env
installer/identity.env
installer/runtime.env
installer/layout.env
installer/btrfs.env OR installer/f2fs.env
installer/boot.env
```

The VM family uses the Btrfs layout environment. Account configuration is read
separately. With no named profile, the NVMe and eMMC defaults resolve to the
canonical profiles listed above; no duplicate fallback files are required.

## Profile policy boundaries

Shared desktop, launcher, hardware-tuning and compositor policy keys stay
consistent across the ten profiles. Filesystem layout keys remain in the layout
family that consumes them: F2FS profiles own `F2FS_LAYOUT_VARIANT`, while Btrfs
profiles own the additional Btrfs partition slots and sizes. APP_VETH identity
defaults come from `installer/identity.env`; only the four F2FS profiles add
profile-specific application overrides. Generic Btrfs profiles remain
hardware-neutral, while Flex, P15s and Chromebook profiles name their concrete
modprobe policy. Every profile keeps `LABWC_WLR_DRM_NO_ATOMIC="0"`, selecting
the modern atomic KMS path.

Partition sizing uses measured disk capacity and, for multi-OS installs, measured
preserved partitions. Profiles provide preferred sizes and caps, not a claimed
physical drive size. Filesystems shrink to their configured minimums on smaller
media, then grow toward their preferred sizes on larger media; root absorbs the
remaining recipe space. A disk below the minimum layout budget is rejected.

After any profile or environment change, run `python3 -B tools/build.py` from the
repository root and publish the complete result. Treat account and enrollment
configuration as sensitive. Historical review paths have been normalized to the
current names; their old hashes and logs are provenance, not fresh validation.

Virtual storage uses the canonical generic Btrfs environment, with the existing
VM disk candidates and hooks. There is no separate VM host profile.

## OpenSSH server policy

Every profile declares literal `SSH_SERVER_ENABLE="true"` or `"false"` and one
`SSH_SERVER_PORT` in `30000..40000`. The two P15s profiles disable the OpenSSH
server; the other eight profiles enable it. These values govern fresh installs.

| Profile | OpenSSH | Port |
| --- | --- | ---: |
| `btrfs-de-duo` | enabled | 32001 |
| `btrfs-de-flex-duo` | enabled | 32002 |
| `btrfs-de-flex` | enabled | 32003 |
| `btrfs-de-p15s-duo` | disabled | 32004 |
| `btrfs-de-p15s` | disabled | 32005 |
| `btrfs-de` | enabled | 32006 |
| `f2fs-de-hp14-duo` | enabled | 32007 |
| `f2fs-de-hp14` | enabled | 32008 |
| `f2fs-de-x360-duo` | enabled | 32009 |
| `f2fs-de-x360` | enabled | 32010 |

Before collecting package fragments, the installer reads these fields as data.
An enabled profile adds `addon/ssh`, so `classes/class-addon/ssh.cfg` installs
`openssh-server` without an SSH class on the boot command line. The late hook
installs `ssh/lan_ed25519.pub` into the primary account's
`.ssh/authorized_keys`, renders the server and firewall port, verifies the target
OpenSSH artifacts, and stages `ssh.service` enablement without starting it.

Neither `ssh_port` nor an explicit SSH class is required. A legacy `ssh_port`
may repeat the profile port; a conflicting value is rejected. An explicit
`addon/ssh` with a disabled profile is also rejected. Tailscale SSH keeps its
separate profile settings, authorization path and firewall policy.

The Fail2ban SSH jail follows the same boolean and port. The daemon is masked
offline when neither SSH nor the web class supplies an active managed jail.
CrowdSec retains its audit, firewall, local privilege escalation and qBittorrent
sources. Its firstboot policy selects SSH detection only for enabled profiles;
the generic Linux collections are replaced with their non-SSH components so
their transitive dependencies cannot silently re-enable SSH detection.

## Sharing mount storage

The public sharing root remains empty during installation. Its backing tree is
`<parent>/.<sharing-name>-store/root` (normally `/data/.sharing-store/root`). The
backing parent is root-owned mode `0700`, so ordinary accounts cannot bypass the
public mount's restrictions through its source path. At boot it is bound to
`/data/sharing` with the existing shared propagation and safety options; the
recursive slave mount at `~/Sharing` receives later NFS mounts.

NFS and Filen installation populate the backing tree offline. An existing
nonempty public destination or an unowned backing tree is refused and preserved.
This layout is for fresh installs; it does not migrate an installed system's
existing sharing data.

## Native client rendering and panel status

Intel and NVIDIA actions resolve the requested vendor from kernel PCI, driver
and render-node identity. On the reported P15s these are Intel `0000:00:02.0`
at `renderD128` and NVIDIA `0000:2d:00.0` at `renderD129`; enumeration numbers
are discovered at each launch. Native managed sandboxes expose only the selected
render node and its required NVIDIA graphics devices. EGL vendor, Firefox and
Chromium selectors use that same identity. Missing or ambiguous explicit GPU
selection fails before client startup. Existing Vulkan restrictions remain.
An unspecified `launch` with no supported PCI GPU retains the software-capable
native launch path; that does not satisfy an explicit Intel/NVIDIA request.
An application's already-running process keeps its original renderer until it
exits; a new environment cannot migrate that process to another GPU.

Waybar uses native Bluetooth and backlight modules. Battery, notification mode
and recording state use continuous readers with cached JSON output, bounded
event handling and reconciliation without subprocesses. Keyboard status runs
at startup and on its existing change signal. Menus and control actions remain
available. The display watcher reconciles at startup and on settled DRM events
instead of invoking output policy on an unconditional 30-second timer.
The SNI tray module is enabled in every host profile. Each profile defines the
same `LABWC_WAYBAR_TRAY_ENABLE` variable with `true` as its value. The
renderer retains a boolean compatibility switch for explicit callers, while
the profile contract keeps the tray present. Managed application D-Bus proxy
permissions and application launchers are unchanged.

Audit execution telemetry remains enabled. These source changes remove the
recurring status command chains; they do not establish a measured reduction
in CPU, audit volume, CrowdSec load or power consumption.
