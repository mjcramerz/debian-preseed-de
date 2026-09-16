# Resource policy correction, revision 2

Date: 2026-09-16. This revision replaces the previously delivered
`debian-preseed-de-systemd2612-gitops-20260916.tar.gz`.

## Scope and provenance

The implementation was rebuilt from the user's original `debian-preseed-de.zip`,
not by retaining the rejected resource-policy hierarchy. The original archive's
SHA-256 is `73d38c9c6f679dfeb9eb0019bd79e00a96394315c1038fd32a887e8145248456`.
The GitOps alias/helper/documentation and their new mirror tests were carried
forward and retested. Example drop-ins were reviewed as suggestions, not copied
as authoritative policy.

All 2,003 original files remain. There are 25 content-modified original files:
13 profiles, four installer scripts, three GitOps files, the existing journald
storage template, three regenerated publishing artifacts, and the migration
map's current profile metadata. Original file permissions are preserved.
`resource-correction-scope.json` enumerates the complete diff with hashes and
permissions; `VALIDATION-RESOURCE-CORRECTION-R2.md` records verification limits.

## Restored and deliberately unchanged

The original zram service templates retain their explicit `IOAccounting=yes`
and I/O weights. The Podman service template, its generator, deployment hook,
documentation, and the original `PODMAN_SERVICE_SLICE_IO_WEIGHT=100` in every
profile remain unchanged. The original `user-1000.slice` accounting drop-in,
user-manager OOM score, user resource defaults, all existing desktop user unit
files, and all existing global user-service overrides are unchanged.

There are no new system workload slices, per-service I/O weights, wildcard
scope resource policies, coredump socket connection limits, no-core policies,
CPU quotas, memory/task ceilings, vendor audio/portal service overrides, or
hardware scheduler rules. No AppArmor or transient-service lifecycle code was
changed. A regression fixture protects 63 existing workload/configuration files
and the original prefix of each profile against accidental edits.

## Delegation is independent of accounting

The following new system drop-in applies to every user manager, without a
hard-coded UID:

`/etc/systemd/system/user@.service.d/60-resource-delegation.conf`

```ini
[Service]
Delegate=
Delegate=cpuset cpu pids memory io
```

The empty assignment resets the inherited controller selection; the next line
requests precisely the five intended controllers. No code writes to cgroupfs,
changes its ownership, or pins CPUs/NUMA nodes. Systemd is responsible for
ancestor controller enablement. Actual availability still requires kernel
support and no conflicting administrator policy [1].

Both `/etc/systemd/system.conf.d/60-resource-accounting.conf` and
`/etc/systemd/user.conf.d/60-resource-accounting.conf` contain:

```ini
[Manager]
DefaultMemoryAccounting=yes
DefaultTasksAccounting=yes
DefaultIOAccounting=__SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE__
```

These are manager defaults, not overrides of explicit unit settings [2]. This
revision introduces no deprecated CPU-accounting default; CPU weighting is
configured separately. Existing unrelated accounting settings are left alone.

## Three user resource classes, not per-service tuning

The three requested source directories are under
`d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/`:

| Drop-in | CPU weight | Optional I/O weight |
| --- | ---: | ---: |
| `session.slice.d/60-resources.conf` | 200 | 200 |
| `app.slice.d/60-resources.conf` | 100 | 100 |
| `background.slice.d/60-resources.conf` | 30 | 30 |

These are modest relative priorities among sibling classes, not measured
per-host performance targets or fixed bandwidth shares [1]. Normal applications
retain the middle class; the essential session infrastructure is favored under
contention; noninteractive work receives a lower relative priority. There are
no newly imposed memory/task limits or CPU quotas. No promise of improved
performance is made without workload measurements and a capable I/O backend.

Seven additional drop-ins contain only `[Service]` and `Slice=...`:

- `labwc-compositor`, `waybar`, `crystal-dock`, `kanshi`, `labwc-output-watch`,
  and `swayidle` are assigned to `session.slice`.
- `labwc-calendar-sync` is assigned to `background.slice`.

These assignments concern existing repository-owned services only. Optional
services receive no class drop-in unless their base unit has been staged. No
service is enabled by this operation. Session infrastructure and noninteractive
work match the documented purpose of these classes [3]. Existing application
launchers, scope drop-ins, restart/stop rules, sandboxing, dependencies, and
vendor unit policies remain unchanged; a class assignment is not a lifecycle
rewrite.

## Exact I/O toggle boundary

All 13 profiles explicitly contain exactly these three new weight controls:

```sh
SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE="true"
SYSTEMD_IOWEIGHT_HOME_USER_SESSION_SLICE_D="IOWeight=200"
SYSTEMD_IOWEIGHT_HOME_USER_APP_SLICE_D="IOWeight=100"
SYSTEMD_IOWEIGHT_HOME_USER_BACKGROUND_SLICE_D="IOWeight=30"
```

Each weight is a whole-line placeholder in its corresponding slice template.
With `true`, both manager defaults render to `DefaultIOAccounting=yes` and the
configured class weights appear. A weight variable may be empty to omit only
that class's explicit I/O weight.

With `false`, both manager defaults render to `DefaultIOAccounting=no` and all
three new class weight assignments disappear entirely. There is no `IOWeight=0`
or empty reset assignment. Delegation remains enabled. The renderer rejects
undefined/malformed values even when the switch is false, avoiding dormant
invalid profile settings.

**This switch does not remove or disable original explicit zram, Podman, or
other unit policies.** It does not guarantee that no I/O accounting or I/O
weights exist anywhere on the installed system. That restriction is intentional
and follows the user's correction forbidding changes to those workloads.
Accounting can also activate across related cgroups as documented by systemd
[1]; `DefaultIOAccounting=no` is not a controller-disable command.

## Coredump and journal storage

Coredump settings are isolated in
`/etc/systemd/coredump.conf.d/60-managed-limits.conf`. Every profile defines:

```sh
SYSTEMD_COREDUMP_STORAGE="external"
SYSTEMD_COREDUMP_PROCESS_SIZE_MAX="64M"
SYSTEMD_COREDUMP_EXTERNAL_SIZE_MAX="64M"
SYSTEMD_COREDUMP_MAX_USE="128M"
SYSTEMD_COREDUMP_KEEP_FREE="32M"
```

These defaults deliberately retain only small cores; larger application cores
may not have a retained dump or stack trace. They are an explicit starting
policy, not a capacity estimate derived from the audit. Increase them only with
regard to the actual core-storage filesystem/tmpfs and available RAM. Retention
thresholds are not a strict peak-memory, peak-storage, or concurrency budget;
processing can temporarily exceed retention thresholds [4]. No additional
service priority, hard cgroup memory limit, or socket throttling was added.
`Storage=none` with both process/external size variables set to `0` is supported
for metadata-only operation; `Storage=none` alone does not suppress all core
processing [4].

The existing journald storage file is parameterized without changing its
rendered default contents. All 13 profiles contain:

| Profile variable suffix after `SYSTEMD_JOURNAL_` | Default |
| --- | --- |
| `SYSTEM_MAX_USE` | `1G` |
| `SYSTEM_KEEP_FREE` | `256M` |
| `SYSTEM_MAX_FILE_SIZE` | `128M` |
| `SYSTEM_MAX_FILES` | `16` |
| `RUNTIME_MAX_USE` | `128M` |
| `RUNTIME_KEEP_FREE` | `64M` |
| `RUNTIME_MAX_FILE_SIZE` | `16M` |
| `RUNTIME_MAX_FILES` | `16` |

The original routing and retention settings remain intact. Validation now checks
the configured profile values instead of requiring a hard-coded 1G value. This
fixes the rejected revision's disagreement between a 512M default and its 1G
installer assertion without silently reducing the original journal budget.

## Installer integration and input safety

An explicit `resources` mode was added to the existing atomic asset publisher.
Only selected manager/slice/storage assets call it; the generic unit renderer
was not modified to apply a global I/O transformation. Global manager,
delegation, and coredump configuration is staged in the shared late-install
phase used by both storage families. Desktop slice/class configuration is
staged before the existing home-copy routine.

The allowlist accepts exact Boolean values, empty or `IOWeight=1..10000` weight
lines, bounded integer size syntax (bytes or B/K/M/G), and validated journal
file counts. It rejects multiline assignments, unknown placeholders, invalid
integers, and unsafe publication paths. Profile variables are data in the
literal renderer; only fixed variable names are used for shell indirection.
Publication uses temporary files and atomic replacement. A failed file render
does not overwrite the existing destination. This is per-file atomicity, not a
transaction spanning every installer asset.

The real unchanged home-copy routine was exercised in a disposable chroot with
UID/GID 1001. It placed the rendered files under the configured account's
`.config/systemd/user`, owned by that account, with 0600 files and 0700
configuration directories. No assumptions about UID 1000 were introduced into
the new class/delegation mechanism. The original UID-specific accounting file
was intentionally not refactored.

## GitOps remains included

The managed alias supports:

```sh
git mcr-repo-mirror glab YOUR_GROUP              # preview only
git mcr-repo-mirror glab YOUR_GROUP --apply      # apply reviewed destination plan
```

Choose the provider opposite the origin (`gh` for GitHub, `glab` for GitLab).
Applied mirror setup can remove additional destination branches and tags;
review the preview before applying. The helper retains local recovery refs,
preserves origin, validates destination identity, and uses explicit leases and
atomic pushes rather than an unconditional force fallback. New provider
repositories are created private. No authenticated remote mutation was
performed during this revision's validation.

Terminal diagnostics, full native Git commit IDs, and the separately labeled
`SHA256(stored commit object)` fingerprint remain included. The latter is a
hash of the stored commit object's header and raw payload, not a claim that a
SHA-1 repository now contains a native SHA-256 commit. The installed
`/usr/local/share/doc/managed-git/README.md` documents commands and behavior.

## Publishing and acceptance

Extract the complete corrected tarball into a clean directory. Do not overlay
it onto the rejected delivery: stale extra drop-ins would otherwise survive.
Publish the rebuilt repository snapshot together, including `payload.tar.gz`,
`payload.manifest`, `preseed.cfg`, profiles, and scripts. This delivery prepares
fresh unattended installations; it is not an automatic migration tool for
already-running hosts. No active user manager was restarted or modified.

After a test installation and fresh login, these read-only checks can be run
as the installed desktop account:

```sh
uid=$(id -u)
systemctl show "user@${uid}.service" -p Delegate -p DelegateControllers
cg=$(systemctl show "user@${uid}.service" -p ControlGroup --value)
cat "/sys/fs/cgroup${cg}/cgroup.controllers"
systemctl show -p DefaultMemoryAccounting -p DefaultTasksAccounting -p DefaultIOAccounting
systemctl --user show -p DefaultMemoryAccounting -p DefaultTasksAccounting -p DefaultIOAccounting
systemctl --user cat session.slice app.slice background.slice
systemctl --user show labwc-compositor.service waybar.service crystal-dock.service -p Slice
```

Confirm the five delegated controllers, the selected manager defaults, class
placement, and application/session lifecycle. With the switch false, check the
three new class drop-ins for absent I/O assignments, not the whole system for
absent original workload policies. Observe actual workloads before concluding
that the policy meets responsiveness goals. Drive IOcost/scheduler calibration
remains outside this change.

## Primary references consulted

[1] Debian systemd resource-control manual:
https://manpages.debian.org/unstable/systemd/systemd.resource-control.5.en.html

[2] Debian systemd manager configuration manual:
https://manpages.debian.org/unstable/systemd/systemd-system.conf.5.en.html

[3] Debian systemd special units manual (user slice roles):
https://manpages.debian.org/unstable/systemd/systemd.special.7.en.html

[4] Debian systemd-coredump configuration manual:
https://manpages.debian.org/unstable/systemd-coredump/coredump.conf.5.en.html

Documentation review is not a substitute for a booted systemd 261.2 acceptance
test. See the separate validation report for precisely what was executed.
