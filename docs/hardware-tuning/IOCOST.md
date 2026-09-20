# Profile-managed native IOCost

`IOCOST_CALIBRATE_ENABLE` is the only enable switch. It controls deployment,
not calibration: the installer never runs a storage benchmark or writes cgroup
IOCost controls itself. Exactly `btrfs-de-flex.env` and
`btrfs-de-dual-flex.env` enable it initially. The other eleven profiles, including
all F2FS profiles and the VM profile, explicitly disable it. Every profile has
all 35 IOCost fields. The common late-stage helper works with either filesystem.

## Provisional device policy

The initial match is `KXG6AZNV512G*`, firmware `*`. The trailing model wildcard
allows the same capacity/model string to carry an OEM suffix; it does not match
other capacities or all NVMe devices. The firmware wildcard is intentional and
must be replaced when a per-host measured firmware-specific result is available.

**These numbers are conservative engineering placeholders, not measured
resctl-bench results or guarantees of latency/isolation.** The official
[iocost-benchmarks collection](https://github.com/iocost-benchmark/iocost-benchmarks)
and an exact-model search were reviewed on 2026-09-19. No authoritative exact
KXG6AZNV512G device/firmware result was found in the accessible material; the
complete database directory could not be retrieved in the development
environment. This is not an exhaustive claim that no such result exists.
Vendor sequential throughput is not a calibration source. Replace the values in
each host profile after non-installer calibration with resctl-bench/iocost tools.

One canonical physical model is repeated into the four native solution
properties by the template; users maintain only one `IOCOST_MODEL_*` set:

| Suffix | Initial value | Unit |
|---|---:|---|
| RBPS | 1000000000 | bytes/second |
| RSEQIOPS | 100000 | operations/second |
| RRANDIOPS | 50000 | operations/second |
| WBPS | 500000000 | bytes/second |
| WSEQIOPS | 50000 | operations/second |
| WRANDIOPS | 20000 | operations/second |

`IOCOST_SOLUTIONS="isolation isolated-bandwidth bandwidth naive"` and
`IOCOST_TARGET_SOLUTION="isolated-bandwidth"` select the standard named solution
convention used by [resctl-bench iocost-tune](https://github.com/facebookexperimental/resctl-demo/blob/main/resctl-bench/doc/iocost-tune.md).
These names do not imply that the placeholder numbers achieved those objectives.

| QoS solution | RPCT | RLAT (us) | WPCT | WLAT (us) | MIN (%) | MAX (%) |
|---|---:|---:|---:|---:|---:|---:|
| ISOLATION | 95 | 1000 | 95 | 2000 | 50 | 80 |
| ISOLATED_BANDWIDTH | 90 | 2000 | 90 | 5000 | 75 | 100 |
| BANDWIDTH | 90 | 5000 | 90 | 10000 | 75 | 125 |
| NAIVE | 99 | 5000 | 99 | 10000 | 75 | 100 |

Each row is configured by `IOCOST_QOS_<SOLUTION>_{RPCT,RLAT,WPCT,WLAT,MIN,MAX}`.
The native properties are `IOCOST_SOLUTIONS`, `IOCOST_MODEL_<SOLUTION>` and
`IOCOST_QOS_<SOLUTION>`, with uppercase/underscore suffixes. The udev key is
`block::name:<model>:fwrev:<revision>:`. See the inspected systemd sources:
[udev rule](https://github.com/systemd/systemd/blob/v261/rules.d/90-iocost.rules)
and [native solution manager](https://github.com/systemd/systemd/blob/v261/src/udev/iocost/iocost.c).

## Native configuration compatibility and precedence

The installer publishes root:root 0644 regular files only when enabled:

* `/etc/udev/iocost.conf` is the native configuration and contains `[IOCost]`
  and the active `TargetSolution` directive.
* `/etc/udev/iocost.conf.d/70-unattended-installer.conf` mirrors that directive
  from the same validated profile value; the directory is root:root 0755.
* `/etc/udev/hwdb.d/70-unattended-installer-iocost.hwdb` adds the narrow device rule.

**Native precedence:** systemd 257 and the inspected v261 source read only
`/etc/udev/iocost.conf`. They do not merge `iocost.conf.d` files. Consequently,
editing only a drop-in has no effect on native IOCost; the main file remains
authoritative. The installer renders both files consistently rather than
publishing a misleading, inactive drop-in-only configuration. Its native binary
capability check fails closed on an unknown interface. No additional service or
vendor hwdb override is introduced.

Reruns migrate the earlier installer-owned `/etc/systemd/iocost.conf` and
`/etc/systemd/iocost.conf.d/70-unattended-installer.conf` layout, including its
exact compatibility symlink, to this native regular-file layout. Marker,
ownership, type and mode checks apply before any legacy asset is removed.
Unrelated administrator files are retained. Legacy-file removal participates in
the same rollback transaction as native configuration and hwdb publication.

Debian udev also ships a **regular** `/etc/udev/iocost.conf` containing comments,
`[IOCost]`, and the commented example `#TargetSolution=naive`. Its presence is
normal, not an administrator-policy conflict. Enabled staging accepts only a
root:root 0644, single-link regular file with no active directive: blank lines,
comments and at most one `[IOCost]` section. Size is bounded at 64 KiB, and
control characters (including embedded NUL), active settings and other sections
are rejected. No package checksum, executable metadata tool, or shell evaluation
is needed to recognize this inert configuration.

Before replacing that file with the managed native configuration, the transaction
saves its exact original bytes after a managed marker in the root:root 0644 file
`/etc/udev/iocost.conf.unattended-installer-original`. The first saved original
is retained across enabled reruns. The same transaction restores it on failure;
a true-to-false rerun restores the original regular file and removes the backup.
A fresh disabled install leaves the packaged file untouched and runs no hwdb
commands for it. Older installations with a managed link but no saved original
remain supported, as does a target where the native file was originally absent.

A native configuration with active administrator settings, an unrelated link,
unsafe ownership/mode, or multiple hard links is never overwritten. Enabled
staging reports the exact native path and the active/unsafe conflict. If an
administrator replaces an existing managed file or link, disabled staging preserves both
that policy and its saved defaults rather than restoring over the replacement.
The backup has a fixed path, marker, metadata checks and inert-content validation;
an unsafe or unrelated file at that reserved backup path is not adopted.

The local hwdb filename does not collide with a vendor filename. Normal lexical
hwdb precedence is retained, and a conflicting later administrator rule is
reported by exact property-query verification rather than silently accepted.

## Validation, staging and reruns

The builder validates literal profile assignments with the same shell/awk policy
as installation. Values are never sourced from a generated IOCost data file.
The existing scalar renderer consumes only `__INSTALLER_IOCOST_*__` placeholders.
Unknown or unresolved placeholders fail. Boolean spelling is exactly true/false.
Solutions are a duplicate-free canonical list of the four supported names, with
the target present. Model/firmware values reject control characters, colons,
equals signs, bracket/question glob syntax and arbitrary leading wildcards.
Only an optional trailing `*` is allowed; firmware alone may be `*`. Model
literal length is at least eight characters, with limits of 128/64 characters.

BPS fields are positive decimal integers up to 10^12; IOPS up to 10^9. Percentiles
are 0..100; positive integer latencies are at most 60000000 us; MIN/MAX are
0.01..10000 percent with MIN <= MAX. Fractional percent fields have at most two
decimal places. No unit suffixes, exponents or shell expressions are accepted.

All three templates render into private staging before publication. Strict
native hwdb compilation and exact nine-property query verification run there
first. The normal target executor uses the target binary and libraries, including
Debian Installer's `in-target` mount preparation. `--root` always names either
the private target-relative staging root or `/` **inside the target executor**;
the installer host database is never updated. No live uevent is triggered.

A target-local process lock prevents interleaving. Before the first rename, all
old managed files and the old binary database are backed up privately. Failures
restore both files and database; rollback failures are explicit and preserve
private recovery copies. This is ordinary-error/signal rollback, not a claim of
cross-file atomicity across sudden power loss. The native database may be 0444;
its safe native mode is preserved, including on rollback.

A fresh disabled profile creates no IOCost files and does not invoke hwdb tools.
A true-to-false rerun removes only exact installer-marked files, restores the
saved native defaults (or removes only managed configuration when no original was
saved), then rebuilds the target database when its hwdb rule was removed. A
missing native file or an already-restored original is recoverable on a rerun. Vendor
sources and unrelated administrator files are retained.

Tests include the packaged udev conffile, real systemd-hwdb strict compilation
and queries in isolated target roots, and a two-level BusyBox installer/target
chroot with no external metadata executable. A native `iocost query` against an
intentionally nonexistent device verifies the selected config before device
lookup fails; it never runs the apply operation. Tests cover exact-byte defaults
restoration, repeat runs, legacy links, malformed/active content, unsafe metadata,
and failures during backup/configuration publication and final hwdb rebuilding. Sandbox
mounts of proc are denied; rerun fixtures use
the byte-identical available tool with explicit alternate-root arguments to test
native database replacement without mounting proc or changing the host database.
Physical KXG6 behavior and calibration remain hardware acceptance tasks.
