# Resource policy refinements - revision 3

Date: 2026-09-16. Base: the accepted revision 2 archive, not the rejected first delivery.
This report describes the current policy. Earlier reports and validation files
are historical records; their inventories are not the R3 inventory.

## Implementation boundary

This revision adds 29 target configuration assets and extends their existing
installation paths. It does not change application launchers, existing service
fragments, AppArmor profiles, zram or Podman configuration/generators, existing
OOM policy, kernel settings, drive schedulers, IOcost calibration, or device rules.
The accepted GitOps implementation remains unchanged, including mirror support
and commit diagnostics. New policy is separated into:

* `60-resource-class.conf`: class placement only, using `Slice=`.
* `60-resources.conf`: the few deliberate CPU/I/O weight policies.
* `70-no-core.conf`: `LimitCORE=0`, separate from scheduling.
* `60-concurrency.conf`: coredump socket admission/polling policy only.

These are configuration choices for this desktop installer, not claims of measured
performance improvement on every host. No workload benchmark was performed.
The resource-policy tests retain the original workload hash fixture. The release
scope manifest compares R3 against both R2 and the original archive.

## User classes and service exceptions

The existing R2 class settings remain: session 200/200, app 100/100, and background
30/30 (CPU/I/O). Their source location remains
`d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/`.
The installed account receives the rendered files beneath
`$ACCOUNT_HOME/.config/systemd/user/` through the original private-home copier.

The compositor now has the requested explicit exception:

```ini
# labwc-compositor.service.d/60-resources.conf, rendered defaults
[Service]
CPUWeight=300
IOWeight=300
```

Its existing class-only drop-in keeps it in `session.slice`. The override is
profile-driven; with managed I/O disabled the CPU line remains and the I/O line
is absent. This is a sibling-relative policy, not a 300% CPU quota, a disk rate
limit, or GPU scheduling control. Parent allocations still matter. Configured I/O weights do not establish that
the selected per-device backend enforces proportional I/O; device calibration
remains outside this revision. [1]

PipeWire, PipeWire Pulse, and the filter-chain service receive `CPUWeight=200`
and `Slice=session.slice` in global user drop-ins. They receive no new I/O weight,
RTKit privilege, realtime limit, or memory-lock setting. This explicitly favors
normal CPU-scheduled audio work; it is not a realtime scheduling guarantee.

The class-only policies cover:

| Class | Services/scopes |
|---|---|
| User session | Compositor, Waybar, Crystal Dock, Kanshi, output watcher, swayidle, KWallet/Secret Service, SSH key loader, runtime power-lock services |
| Global user session infrastructure | Hyprpolkitagent, Mako, SSH agent, WirePlumber, main desktop portal, portal backend family |
| User application | `app-*.scope`; Bitwarden's existing launcher already selects `app.slice` |
| User background | Existing calendar-sync service |

The division follows the documented distinction between essential session
infrastructure, ordinary applications, and background work. [2] Routine helpers
receive no redundant per-service CPU or I/O weights. The original lifecycle file
`app-.scope.d/50-session-labwc.conf` is unchanged; the new scope policy adds only
`[Scope] Slice=app.slice`. No service execution limits are applied to scopes.

## Sensitive-process core policy

The following files contain exactly the active configuration `[Service]` and
`LimitCORE=0`:

```text
$ACCOUNT_HOME/.config/systemd/user/labwc-bitwarden-.service.d/70-no-core.conf
$ACCOUNT_HOME/.config/systemd/user/labwc-kwallet-portal.service.d/70-no-core.conf
$ACCOUNT_HOME/.config/systemd/user/labwc-power-lock-.service.d/70-no-core.conf
/etc/systemd/user/hyprpolkitagent.service.d/70-no-core.conf
```

Dash-prefix policies match the UUID-named Bitwarden and power-lock units created
by the existing launchers. They are not broad `labwc-.service.d` overrides. Prefix
lookup is documented by systemd. [3] SSH key loading and the SSH agent already had
`LimitCORE=0`; their existing protections are preserved rather than duplicated.

A single `LimitCORE=0` sets both the soft and hard core-file limit to zero. [4]
This is the OS core policy, not a blanket confidentiality boundary: crash metadata
can remain, application-owned crash reporting is separate, and this does not
prevent authorized debugging or memory access. [5]

## System maintenance and synchronization

Two new system classes are installed:

```text
system.slice
  system-maintenance.slice   CPUWeight=30, IOWeight=30
  system-background.slice    CPUWeight=50, IOWeight=50
```

The `system-` prefix places these beneath `system.slice`. [6] The illustrative
root-level `managed.slice`, `managed-maintenance.slice`, and
`managed-background.slice` are deliberately not introduced. This avoids creating
another top-level peer competing with `system.slice` and `user.slice`.

`apt-daily`, `apt-daily-upgrade`, the `local-apt-` service family, the `timeshift-`
service family, and managed ClamAV signature updates share the maintenance
class. Managed Syncthing uses the background class. Their drop-ins contain only
`Slice=`: one aggregate class allocation, not a fresh allocation for every job.
The original nice levels, I/O scheduling hints, sandbox settings, restart and
shutdown rules, and AppArmor transitions remain intact. In particular, the
ClamAV update service's existing privilege/transition policy is not tightened
speculatively. There are no new hard CPU, memory, or task ceilings.

Slices are loaded as dependencies of their member services, not separately
enabled at boot. Optional workload drop-ins are staged by the same component
that installs the corresponding base workload.

## Coredump socket throttling

The installed socket drop-in renders to:

```ini
# /etc/systemd/system/systemd-coredump.socket.d/60-concurrency.conf
[Socket]
MaxConnections=2
PollLimitIntervalSec=2s
PollLimitBurst=16
```

The selected policy caps worker concurrency and slows polling bursts. Poll
throttling recovers after its window; a tight trigger limit would instead leave
the socket failed until restarted. Excess concurrent connections can be refused.
No listen address, ownership, `Accept=`, or vendor trigger fuse is replaced. A
per-source limit is deliberately omitted: AF_UNIX source identity is the helper's
UID, not a per-crashed-application classification. [7]

This trades some crash diagnostics for bounded worker concurrency. It does not
promise collection of every crash or bound all upstream kernel/helper activity.
It adds no speculative resource limits to `systemd-coredump@.service`.
The R2 coredump storage defaults remain external storage, 64M process/external
size, 128M retained use, and 32M free-space preference. Retention is not a strict
instantaneous allocation bound. [8] Journald defaults remain unchanged from R2.

## Profiles and validation grammar

All 13 profiles contain the following additional controls:

```sh
SYSTEMD_CPUWEIGHT_HOME_USER_LABWC_COMPOSITOR_SERVICE_D="300"
SYSTEMD_IOWEIGHT_HOME_USER_LABWC_COMPOSITOR_SERVICE_D="IOWeight=300"
SYSTEMD_CPUWEIGHT_USER_AUDIO_SERVICE_D="200"
SYSTEMD_CPUWEIGHT_SYSTEM_MAINTENANCE_SLICE_D="30"
SYSTEMD_IOWEIGHT_SYSTEM_MAINTENANCE_SLICE_D="IOWeight=30"
SYSTEMD_CPUWEIGHT_SYSTEM_BACKGROUND_SLICE_D="50"
SYSTEMD_IOWEIGHT_SYSTEM_BACKGROUND_SLICE_D="IOWeight=50"
SYSTEMD_COREDUMP_MAX_CONNECTIONS="2"
SYSTEMD_COREDUMP_POLL_LIMIT_INTERVAL_SEC="2"
SYSTEMD_COREDUMP_POLL_LIMIT_BURST="16"
```

Together with the three R2 user-class weights, there are exactly **six managed
I/O weight assignments**. `SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE="false"` makes both
manager defaults `DefaultIOAccounting=no` and omits all six managed weight lines.
It does not rewrite existing explicit zram, Podman, or other original workload
settings. CPU preferences and the requested `Delegate=cpuset cpu pids memory io`
remain independent of this switch. The switch is not a global controller kill
switch or a guarantee that every unit will report `IOAccounting=no`.

The scoped renderer accepts CPU weights 1..10000, complete `IOWeight=1..10000`
assignments (or an empty individual I/O value), socket connections/poll bursts
1..64, and polling intervals 2..60 integer seconds. These socket bounds are this
installer's supported policy subset, not systemd's complete syntax. They keep
polling below the unchanged default trigger fuse. Malformed/multiline values,
leading zeroes, missing required values and unresolved tokens fail validation.
The publisher validates before replacing each destination file atomically.
The complete profile is validated before the common policy group is published;
this is not a claim of a cross-file filesystem transaction.

## Installation ownership and conditions

| Installer component | Responsibility |
|---|---|
| `scripts/late/storage-maintenance.sh` | Manager defaults, delegation, storage policy, socket throttle, system slices, APT daily class policies |
| `scripts/desktop/components.sh` | Render user classes and compositor policy before copying the home; stage credential/prefix rules; add global vendor-user policies only when a unit is available; stage ClamAV's class with its base unit |
| `scripts/late/software.sh` | Stage the local-APT family policy alongside local-APT units |
| `scripts/late/btrfs-family.sh` | Stage the Timeshift family policy with selected Timeshift units |
| `scripts/late/tailscale.sh` | Stage the Syncthing class with the managed Syncthing service |
| `scripts/late/templates.sh` | Strict, scoped scalar map and I/O omission; generic workload rendering is unchanged |

Source assets live beneath `d-i/forky/hooks/target/`. System/global-user drop-ins
are published with file mode 0644; the original home-copy routine makes the
primary account's configuration private (files 0600, directories 0700, account
ownership). Runtime prefix drop-ins intentionally have no static base file.
Unavailable regular/vendor services are not fabricated or enabled. One portal
backend prefix file is used rather than duplicating identical backend policies.

`docs/resource-policy-r3-inventory.json` lists the exact new assets, source hashes,
profile tokens and intended target locations. `docs/resource-refinements-r3-scope.json`
records changes against both source archives, including protected-file checks.

## Deployment and acceptance checks

Publish the complete rebuilt repository as one coherent release, including
`payload.tar.gz`, `payload.manifest`, `preseed.cfg`, profiles and scripts. Use a
clean extraction directory; do not merge files left from the rejected R1 archive.
This release does not blindly remove unknown existing administrator drop-ins.

Following a new installation and login, inspect without restarting the live
desktop manager:

```sh
systemctl show "user@$(id -u).service" -p Delegate -p DelegateControllers
systemctl --user show labwc-compositor.service -p Slice -p CPUWeight -p IOWeight
systemctl --user show session.slice app.slice background.slice \
  -p CPUWeight -p IOWeight -p MemoryAccounting -p TasksAccounting -p IOAccounting
systemctl --user show pipewire.service pipewire-pulse.service filter-chain.service \
  -p Slice -p CPUWeight -p IOWeight
systemctl --user show hyprpolkitagent.service labwc-kwallet-portal.service \
  -p LimitCORE -p LimitCORESoft -p DropInPaths
systemctl --user list-units 'labwc-bitwarden-*.service' 'labwc-power-lock-*.service'
# Substitute the actual active name in the next command:
# systemctl --user show labwc-bitwarden-<uuid>.service -p LimitCORE -p LimitCORESoft -p DropInPaths
systemctl show systemd-coredump.socket \
  -p MaxConnections -p PollLimitIntervalUSec -p PollLimitBurst -p TriggerLimitBurst
systemctl show system-maintenance.slice system-background.slice -p Slice -p CPUWeight -p IOWeight
systemctl show apt-daily.service managed-syncthing.service -p Slice -p DropInPaths
systemd-analyze cat-config systemd/system.conf
systemd-analyze cat-config systemd/user.conf
systemd-analyze cat-config systemd/coredump.conf
```

Check actual cgroup values as well as configured properties after workloads start.
Absent optional services are expected. Verify enabled and disabled I/O profiles
on separate fresh installations; inspect only managed files when testing weight
omission, because original explicit workload settings are intentionally preserved.
New process limits apply to newly started processes. A planned logout/reboot is
safer than terminating the active user manager to apply policy during a session.

The local tests exercise the production renderer/publishers, the original home
copy in a disposable chroot, and offline systemd loading of synthetic service,
slice and socket fragments. Scopes require a running manager and API creation;
the scope drop-in is structurally checked, not represented as a successful static
scope activation test. Actual transient activation and a booted systemd 261.2
installation remain deployment acceptance checks. See the validation report for
exact results and limitations.

## Primary references consulted

[1] systemd.resource-control(5), Debian systemd 261.2: controller hierarchy, CPU/I/O weights,
    delegation and implicit class dependencies.
    https://manpages.debian.org/unstable/systemd/systemd.resource-control.5.en.html
[2] systemd.special(7), user slices and their roles.
    https://manpages.debian.org/unstable/systemd/systemd.special.7.en.html
[3] systemd.unit(5), dash-prefix drop-in lookup and precedence.
    https://manpages.debian.org/unstable/systemd/systemd.unit.5.en.html
[4] systemd.exec(5), process soft/hard resource limits.
    https://manpages.debian.org/unstable/systemd/systemd.exec.5.en.html
[5] systemd coredump handling and systemd-coredump(8).
    https://systemd.io/COREDUMP/
    https://manpages.debian.org/unstable/systemd-coredump/systemd-coredump.8.en.html
[6] systemd.slice(5), name-derived hierarchy.
    https://manpages.debian.org/unstable/systemd/systemd.slice.5.en.html
[7] systemd.socket(5), MaxConnections and poll/trigger limits.
    https://manpages.debian.org/unstable/systemd/systemd.socket.5.en.html
[8] coredump.conf(5), processing/storage sizes and retention limits.
    https://manpages.debian.org/unstable/systemd-coredump/coredump.conf.5.en.html
