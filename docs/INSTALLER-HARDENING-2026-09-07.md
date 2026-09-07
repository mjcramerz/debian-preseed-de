# Installer repair and operations guide - 2026-09-07

## Scope and release status

The supplied ZIP is the baseline, not a separately fetched upstream branch. All
13 original profile files are retained. This repair addresses observed failures,
adds fail-closed supervision, and adds deterministic tests; it is not a physical
installation certification. The sanitized incident inventory records supporting
log locations. Raw installer logs and credentials are deliberately not distributed.

## Architecture and lifecycle

The generated `d-i/forky/preseed.cfg` embeds the initial transport and lifecycle
functions. `tools/build.py` embeds canonical common helpers, generates browser
assets, and rebuilds the pinned payload archive and manifest. Edit canonical
sources and run `make build`; never edit only the generated preseed or payload.
A complete hash-checked snapshot is prepared before partitioning. Later phases
use that snapshot rather than independently fetching a moving branch.

The lifecycle is: preflight -> prepare-context -> apply -> early -> partman ->
base installation -> apt-setup/pkgsel -> late -> remaining finish hooks ->
target validation -> target unmount -> reboot authorization. Phase and hook
names have separate completion records. The early hook adapts the known
bootstrap-base APT waypoint and guards mandatory component postinsts and hooks.
An unsupported bootstrap-base layout fails before destructive partitioning.

`common/lifecycle.sh` owns lifecycle state and terminal behavior. A phase creates
`state/<phase>.running`; only explicit completion atomically publishes
`state/<phase>.done`. A completed phase is a no-op on duplicate entry. A leftover
running directory means interrupted or concurrent work and is fatal, not a
resume request. Unexpected zero exit without completion is also fatal.

Each late family executes in an independent `/bin/sh -eu` process. Callers retain
its actual exit status before logging. Helpers used inside conditional calls
explicitly propagate errors where `set -e` does not apply. Host and class policy
are validated before the first renderer. Architecture policy owns all required
GRUB/MokManager/removable EFI paths; no arbitrary empty defaults replace them.

## Why fatal handling does not return to d-i

The supplied logs show a render failure followed by customization and repeated
late invocations. The relevant upstream source has two separate hazards:
`preseed_command` presents a debconf error but does not reliably propagate it;
finish-install logs most hook failures and continues. Exit 10 is a menu/back
contract and exit 11 is a reboot/exit contract, not a fatal-error API.

A fatal supervisor records the first error, snapshots available diagnostics,
stops its actual main-menu ancestor with SIGSTOP, and enters a non-returning
terminal wait. It ignores HUP/INT/TERM in that hold. This is intentionally NOT a
retry loop: no target work, phase dispatch or reboot occurs in it. Even killing
the waiting leaf does not resume the stopped menu. Never resume the menu manually
after a fatal record; use trusted rescue media for recovery.

The implementation does not require `setsid`, `timeout` or `stat` in the initrd:
Debian busybox-udeb omits those applets. It supervises a direct child. On signal,
it freezes that child before enumerating/freeze-killing its descendants, then
holds with the original signal status. `/proc/PID/status` is a fallback when the
kernel lacks `/proc/PID/task/PID/children`. It never signals PID 1 or a global
process group. Once a destructive process is interrupted, preserving evidence
and refusing subsequent work is safer than guessing that cleanup completed.

Finish hook `00-installer-guard` wraps the installed finish hooks and inventories
them. Both normalization hooks run as `94zz-*`, before `95umount`. The mandatory
`94zz-99-validate-target` checks package state, required configuration, bootable
kernel/initrd pairs, PE signature presence, and published placeholder absence.
It publishes target readiness, NOT installation success. The guarded `99reboot`
accepts Debian's exit 11 only after prior mandatory phase/component/hook records
and target readiness exist and no unexpected finish hook has appeared. Normal
zero exit from that sentinel is not accepted as a successful reboot handoff.

## State and diagnosis

| Record | Meaning and location |
|---|---|
| First failure | `/tmp/install-runtime/state/first-failure`; format, phase, component, original status, timestamp and sanitized description; 0600; never overwritten by cleanup errors. |
| Running/done | `/tmp/install-runtime/state/*.running` and `*.done`; private installer lifecycle, not administrator-editable resume controls. |
| Target readiness | `/var/lib/installer-state/target-validated` inside the target, plus live runtime copy; all target checks passed before unmount, not proof of completed reboot. |
| Installation success | `/tmp/install-runtime/state/installation.success`, only at the guarded final exit-11 handoff after unmount; this is intentionally live installer state, not a fictitious post-unmount target write. |
| Diagnostics | `/tmp/installer.log`, `/var/log/syslog`; on fatal while target is mounted, private copies in target `/var/log/installer/`; normal snapshots also use target `/var/lib/installer-state/`. |

Fatal state removes the live success/readiness records. A target readiness file
from an earlier point never overrides a later fatal diagnostic. Runtime state
survives phase re-entry, not power loss. Before a target exists there is nowhere
safe to promise durable on-disk evidence; configure serial-console capture for
unattended sites. Do not distribute raw logs, initrd credentials or MOK material.

Inspect first-failure before the later package errors. Record the deployed
preseed/payload hashes, selected class references, installed package versions,
mounts and mapping state. The fatal hold does not reboot or attempt speculative
unmount/crypt-close operations. Export diagnostics securely and recover using
trusted media. Do not delete running/fatal markers to bypass the gate.

## Retry and network rules

Repository fetches make at most three attempts. Wget retains an inactivity
limit, and the embedded bounded runner limits each attempt to a finite polling
budget (default 180 seconds, configurable from 1 to 900). The budget is not a
hard-real-time scheduling guarantee. Durations are normalized decimal values;
leading zeroes are accepted without octal arithmetic. The bootstrap uses only
integer sleeps. Invalid timeout configuration is rejected before any download.
Timed-out child trees are stopped before retry. HTTPS certificate bypass requests are rejected. Hash or source-identity
failure cannot fall back to another revision. Target APT has three acquisition
retries, 45-second HTTP/HTTPS timeouts, and fatal update errors. Codex Git and
binary preflight commands have explicit target-side coreutils timeouts.

CrowdSec first boot has three systemd start attempts, finite command timeouts,
and no key rotation on ordinary retry. Invalid credential/configuration status
2 is not automatically restarted. Other package-manager operations are not
blindly retried after partial installation: their error becomes terminal.

## Storage safety

Selection excludes removable/read-only devices, partitions presented as disks,
active mounts, swap, device-mapper/RAID holders and mounted Btrfs members. Explicit
hd-media device arguments remain protected even after that media is unmounted.
Explicit unsafe overrides fail; they do not fall back. Multiple safe candidates
are ambiguous and fail. A stored disk identity must remain consistent between
early and partman. Linux sysfs capacity is in 512-byte units even on a 4096-byte
logical-sector device; the selection logic does not multiply capacity by eight.
Existing storage layout validation, partition identities, alignment tolerances,
filesystem-specific mounts and fstab rules remain in place. Tests use fixture
sysfs/device files, never real formatting or host block devices.

The model assumes a trusted installer kernel and sysfs plus physically stable
storage during provisioning. A disk hot-swap concurrent with a destructive
system call is not made safe by unit tests. Devices lacking the required identity
or topology information fail closed. Back up data and verify explicit selectors.

## APT and package ordering

Base-installer's first target update now invokes the managed network-APT boundary.
It removes CD-ROM list/deb822 entries before update, writes a signed Debian
network source using the actual base-install distribution, and checks update
status. It does not prematurely substitute the later Forky target policy.
Apt-setup and finish normalization retain CD-ROM cleanup as defense in depth.

Forky/Trixie/Sid/Experimental and selected vendor repositories retain their
explicit policy. Package-specific pins are not replaced by wholesale suite
migration. The virtual-package check includes installed Provides entries so
mesa-utils-extra does not trigger a false repair when mesa-utils supplies it.
The temporary legacy CUDA archive requires its dedicated Signed-By key and
fingerprint; signature and freshness checks are not bypassed. See SECURITY.md.
This tree is a reproducible installer payload, not a lockfile for every online
Debian/vendor package. Live repository and solver acceptance is still required.

CrowdSec engine installation/configuration precedes installing the nftables
bouncer. Its package-generated private API key is reused and validated, not
hardcoded or unnecessarily replaced. First boot verifies LAPI and authenticates
an actual bouncer request before declaring completion. Optional console enrollment
credentials are private and are not logged. Mullvad installation retains signed
package validation. Its installed AppArmor profile must match the vendor profile
and parse with kernel loading disabled. A required first-boot unit performs the
real kernel load before the daemon. Installer-chroot inability to reload a profile
is not silently treated as successful runtime activation.

## Codex transaction and rerun rules

The pinned archive/repository is staged under private paths, preflighted and
normalized before publication. A missing CODEX_HOME/packages managed link is now
created by both the candidate preparation and tmpfiles policy. Immutable files,
revision, .git control data, ownership/mode and hardlinks are checked without
executing Git against existing writable state. Defined runtime session/history
paths are permitted without making the repository root generally mutable.

Components are renamed atomically on their destination filesystem; the release
record is last. Failure rolls back only newly published components. Existing
matching pinned components can converge on a deliberate component rerun; unknown
or modified external contents still fail. Power loss between a component rename
and bookkeeping leaves a component that must pass the same full comparison,
not a path that is blindly overwritten. Fault-injection tests fail each rename
boundary and assert original status and preservation of unrelated data.
Automatic whole-installer resume is prohibited after any fatal phase.

## Secure Boot, kernels and architecture

amd64 uses x86_64-efi with shimx64/grubx64/mmx64 and BOOTX64.EFI; arm64 uses
arm64-efi with shimaa64/grubaa64/mmaa64 and BOOTAA64.EFI. The added generic-arm64
CPU class avoids rejecting arm64 during CPU detection or applying x86 microcode,
pstate or vendor KVM settings. GPU/storage classes remain independently selected.

The existing encrypted MOK state, checked DKMS signing and enrollment workflow
are retained. Kernel/module signing and initramfs repair occur before final GRUB
generation. The final target check requires actual kernel/initrd pairs and EFI
signature records; signature presence alone is not a claim that firmware enrolled
or trusts the key. MOK enrollment and NVRAM/fallback behavior need firmware tests.
No private signing key or enrollment secret is embedded in the release.

## Validation and deployment acceptance

Run `make build`, `make check`, `make test`, `make audit`, and `make validate`.
`tools/release_audit.py` additionally inventories the complete tree and checks
shell/Python syntax without executing target programs. Unit tests include real
loopback APT/GnuPG verification, process supervision, fault injection, template
publication, storage fixtures and all three late families. Systemd structure
checks are not service activation tests. Missing Perl dependencies are explicitly
reported as blocked; ShellCheck is not silently substituted with sh -n.

Before production rollout, boot the exact signed installer image and snapshot on
disposable amd64 and arm64 UEFI targets. Exercise Btrfs/NVMe, F2FS/eMMC and VM
profiles, 4Kn disks, installer-media exclusion, network loss and forced late
failure. Verify no subsequent target work or reboot after failure. On successful
runs verify Secure Boot trust/enrollment, actual boot, DKMS/NVIDIA modules, initrd,
network/DNS, CrowdSec LAPI/bouncer, Mullvad/AppArmor, greetd/labwc/user services,
and addon activation. The release report separates executed local evidence from
these unexecuted acceptance tests.

## Source contracts examined

- Debian preseed 1.125: `preseed_command` in sources.debian.org/src/preseed/1.125/.
- Debian finish-install 2.124: `debian/postinst`, `finish-install.d/07preseed`,
  `95umount`, `99reboot` in sources.debian.org/src/finish-install/2.124/.
- Debian main-menu 1.70 source: failed-component handling and menu priority.
- Debian base-installer 1.226: `debian/bootstrap-base.postinst`, APT waypoint 3.
- Debian busybox 1:1.37.0-6: `debian/config/pkg/udeb`, which omits stat, setsid
  and timeout. R2 uses numeric ls and integer sleeps and does not require
  fractional-duration support. See BOOTSTRAP-PORTABILITY-R2.md for the restricted
  BusyBox execution tests and their image-acceptance limitations.
- NVIDIA driver installation guide, Debian Signed-By/keyring authentication:
  docs.nvidia.com/datacenter/tesla/driver-installation-guide/debian.html.
- CrowdSec `cs-firewall-bouncer/debian/crowdsec-firewall-bouncer-nftables.postinst`.
- Mullvad `mullvadvpn-app/dist-assets/linux/after-install.sh` and Debian
  apparmor_parser documentation for skip-kernel-load/replace.

These contracts match the supplied log's package generation where visible. A
newer installer image must satisfy the adapter/guard checks and pass boot
acceptance; newer package versions are not presumed equivalent from their names.
