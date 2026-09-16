# R6 - ordered single-force power actions and independent I/O policy

> Historical power design/results: superseded by [the current power and resctl-bench revision](POWER-RESCTL-2026-09-16.md). Do not deploy the R6 shutdown-target finalizers described below. The independent I/O policy is unchanged.

Date: 16 September 2026. Baseline: the complete accepted R5 archive.
This is the full unattended-install publishing tree, not a live-host migration.
This report supersedes R5's non-forced reboot/poweroff dispatch and the earlier
coupled accounting/weight switch descriptions. Earlier reports remain history.

## Contract and scope

Reboot and poweroff now end in an explicit **single `systemctl --force`** after
an explicitly queued service/mount teardown transaction. WirePlumber receives
the requested global user `Slice=session.slice` drop-in. Accounting and weight
publication have separate strict Boolean profile controls. All 13 profiles ship
with both controls set to `false`.

The existing three explicit `app.slice` assignments for `app-*.scope`, Waybar,
and Crystal Dock remain. Accepted delegation, CPU weights, core restrictions,
coredump socket polling and child system slices are retained. AppArmor,
GitOps implementation, and original Podman/zram workload policies are not
rewritten. No drive calibration or hardware-watchdog settings are added.

The supplied host audit identifies systemd 261.2-1. Its user-manager unit is
ordered after `dbus.service`, has `KillMode=mixed`, and has a 120-second stop
timeout. Those properties are not replaced. The attachments do not provide a
timed reproduction proving the cause of every intermittent shutdown stall.

## Power transaction

### Authorization and preflight

The existing root-owned, PID-1-managed `labwc-admin-action@.service` continues
to run the authorized worker. Its AppArmor profile, protected lock directory,
account validation, save-preparation helper, and multi-account checks remain.
The worker still rechecks other logged-in accounts after save preparation.
Logout keeps its separate account-local teardown. Suspend keeps its existing
lock-readiness and systemd sleep-hook path.

For reboot or poweroff the worker validates that both the exact action target
and its finalizer are loaded, then queues exactly one nonblocking transaction:

```text
systemctl --no-ask-password --no-block --show-transaction \
  --job-mode=replace-irreversibly start labwc-power-reboot.target
```

Poweroff uses `labwc-power-poweroff.target`. The worker does not interpolate an
arbitrary instance, shell command, process name or target supplied by a caller.
The accepted actions are a fixed allowlist. These units are installed as static
assets, with no boot enablement, aliases, or `.wants` links.

`replace-irreversibly` is systemd's documented job mode for transactions which
pull in `shutdown.target` [1]. The worker marks the handoff committed before
submission: if shutdown begins but the reply is lost, it does not cancel save
state, resurrect a user manager, retry the destructive request, or issue an
unconditional fallback force. It reports the acceptance as uncertain instead.
A missing/masked unit fails preflight without submission. This is conservative
failure handling; a request rejected during submission may require inspection
because safe cancellation cannot be inferred from a transport error.

### Ordered teardown before the force

Each target requires its fixed finalizer. Each finalizer has:

```ini
[Unit]
DefaultDependencies=no
RefuseManualStart=yes
Requires=shutdown.target umount.target final.target
After=shutdown.target umount.target final.target
```

This constructs the stop jobs through systemd's installed dependency graph.
It does not assume that `systemctl stop basic.target` recursively stops every
service that the target merely wants. `shutdown.target` conflicts with normal
services; their stop jobs run before that barrier. `umount.target` and
`final.target` provide the mount and late-hook ordering used by upstream's own
reboot service [2, 3]. Only after all three barriers does the new finalizer run.

The service-stop transaction keeps clients ordered after their buses at startup
ordered before those buses at shutdown. The installed host's user-manager
`After=dbus.service` relationship participates in that reverse ordering. The
broker's vendor `Before=basic.target shutdown.target` and shutdown conflict
remain intact [4, 5]. Both R5 broker stop-timeout drop-ins remain `30s`; the
user-manager timeout remains 120 seconds. No separate `dbus-broker-lau.service`
is invented: broker and launcher processes belong to their real service cgroup.

The exact reboot final command is:

```ini
ExecStart=/usr/bin/systemctl --force --no-ask-password --no-block reboot
```

Poweroff substitutes `poweroff`. The command contains exactly one `--force`,
never two. Single force asks PID 1 to perform the final shutdown machinery while
skipping another unit-stop transaction; double force would bypass the manager
and is deliberately absent [1]. No `SuccessAction=...-force`, watchdog expiry,
raw reboot syscall, or unconditional timeout fallback jumps past these barriers.

The new service has no dependencies on a live user bus, logind, home directory,
`/data`, `/pool`, or `/usr/local` script. It uses a fixed `/usr/bin/systemctl`;
upstream keeps `/` and `/usr` outside ordinary mount-unit shutdown teardown [6].
Root's local manager connection is direct, rather than broker-dependent [7].
The finalizer clears bus-address overrides and sets `SYSTEMCTL_FORCE_BUS=0`.
It also disables automatic kexec/soft-reboot selection for this explicit reboot
path, retains AF_UNIX access, and has no private-mount/temporary-directory
configuration that would pull early-boot mounts back into the late transaction.
The executable is not inherited from the confined worker: PID 1 executes the
fixed finalizer as its own service. Existing AppArmor grants for the worker's
`systemctl`, manager socket and manager calls suffice; no AppArmor widening was
introduced for this change.

### Limits and failure behavior

This is not a guaranteed short shutdown. Existing service stop hooks and their
configured grace periods still run. Notify timeout extensions, stuck storage,
uninterruptible tasks, or defective custom dependencies may delay completion.
A per-service grace period is not a whole-host watchdog deadline [8]. If a
barrier or final command fails, the implementation records the failure rather
than converting it to a double-force reboot. Once teardown has begun, the
machine may be partly stopped; recovery then belongs to an administrator at
the console. Journaling may no longer be available at the latest phase, so the
finalizer also requests console error output.

No live reboot, shutdown, service stop or hardware-watchdog action was executed
in this development environment. Parser and mocked transaction tests establish
configuration/code behavior, not a live 261.2 acceptance result.

## Independent I/O switches

Every profile explicitly contains:

```sh
SYSTEMD_DEFAULT_IOACCOUNTING_ENABLE="false"
SYSTEMD_IOWEIGHT_ENABLE="false"
```

| Accounting switch | Weight switch | Both manager files | Managed weight lines |
| --- | --- | --- | --- |
| false | false | `DefaultIOAccounting=no` | omitted |
| false | true | `DefaultIOAccounting=no` | rendered |
| true | false | `DefaultIOAccounting=yes` | omitted |
| true | true | `DefaultIOAccounting=yes` | rendered |

The accounting switch alone controls these installed files:

```text
/etc/systemd/system.conf.d/60-resource-accounting.conf
/etc/systemd/user.conf.d/60-resource-accounting.conf
```

With the shipped profile defaults, both have this active content:

```ini
[Manager]
DefaultMemoryAccounting=yes
DefaultTasksAccounting=yes
DefaultIOAccounting=no
```

The repository copies under `d-i/forky/hooks/target/` remain source templates;
placeholders are intentional there. The installer renders actual `yes`/`no`
values into the target. `stage_target_systemd_manager_accounting` checks the
actual installed files for exactly one expected I/O assignment and the memory
and tasks defaults. It runs from common policy staging and again from the
final desktop policy boundary, so that the selected profile replaces stale
manager defaults before home configuration is copied. It is not conditioned
on a desktop slice's weight being enabled. Actual production-rendered default
examples are retained in `validation/r6/rendered-defaults/`.

`SYSTEMD_IOWEIGHT_ENABLE=false` independently suppresses all six managed weight
assignments: session/app/background user slices, compositor, system maintenance
slice and system background slice. It removes complete directives, never
`IOWeight=0` or an empty `IOWeight=` assignment. The opt-in resource renderer
also filters literal `IOWeight` and `StartupIOWeight` lines for future managed
assets, before atomic publication. Invalid/missing Boolean values fail closed;
existing value/range validation for each configured weight is retained. The
publisher works in its private staging directory and renames each file
atomically. This is per-file atomicity, not a cross-file filesystem transaction.

All four combinations are tested for every profile against production staging,
including repeated publication into the same target to detect stale values.
CPU preferences are independent. Delegation still requests `cpuset cpu pids
memory io`, even with both switches false. Accounting defaults do not override
explicit workload accounting, and weights may enable controllers through their
hierarchy independently [9, 10]. Therefore the two false values do not mean the
kernel I/O controller is disabled everywhere. Original zram/Podman explicit
settings and their separate renderers are unchanged, as required in the earlier
scope correction. The new switch applies to our managed resource-policy
drop-ins, not unrelated original workloads or externally installed packages.

## WirePlumber and installation

The added file is exactly:

```ini
# /etc/systemd/user/wireplumber.service.d/60-resource-class.conf
[Service]
Slice=session.slice
```

It adds no service-specific CPU/I/O weight. The existing no-root/greeter
conditions remain. The vendor-user publisher stages the file only when the
base service is available. The desktop target verifier requires the new file
and its class assignment. Audio CPU-weight overrides and the compositor's
CPUWeight=300 are unchanged. Its configured IOWeight=300 becomes present only
when the separate weight switch is true.

The four fixed power units are published by the existing desktop component
installer with mode 0644, and the target verifier checks their presence and
modes. Installer payload contents, manifest, scripts and preseed hash pins are
rebuilt together. README identifies this revision as the current policy;
historical reports are not deployment instructions for the superseded flow.

## Installation acceptance checks

Publish the full extracted repository into a clean destination. Do not overlay
old deliveries, and do not copy unrendered source templates directly into a
live system. Original archive modes are preserved; the publisher must already
have suitable access to its existing source files. This is not an automatic
update of a host installed from R5. Do not restart a live broker to apply its
stop-timeout drop-in.

After a fresh installation and boot, inspect without initiating a power action:

```sh
systemctl cat labwc-power-reboot.target labwc-power-reboot.service
systemctl cat labwc-power-poweroff.target labwc-power-poweroff.service
systemctl cat dbus-broker.service user@1000.service
systemctl --user cat wireplumber.service
systemctl --user show wireplumber.service -p Slice
systemctl show -p DefaultIOAccounting -p DefaultMemoryAccounting -p DefaultTasksAccounting
systemctl --user show -p DefaultIOAccounting -p DefaultMemoryAccounting -p DefaultTasksAccounting
systemctl --user show labwc-compositor.service -p Slice -p CPUWeight -p IOWeight
```

Replace UID 1000 only when the installed account uses a different UID. Both
manager defaults should be `no` for I/O in the shipped configuration. Unit
`IOWeight` may show a vendor/default/unset value even when no local directive
exists; examine the rendered files as well. On a subsequent deliberate reboot
or shutdown, first save work and use the normal authorized desktop action.
Inspect the previous-boot journal after restarting to confirm client, manager,
broker, mount and finalizer sequencing. Do not start the new targets merely as
an inspection test: their purpose is to stop the machine.

## Research references

The source comparison and host dump above are distinct from the following
external documentation. Online upstream/main and unstable pages can evolve;
they are not a claim that a 261.2 binary was run locally.

[1] https://manpages.debian.org/unstable/systemd/systemctl.1.en.html
[2] https://manpages.debian.org/unstable/systemd/systemd.special.7.en.html
[3] https://raw.githubusercontent.com/systemd/systemd/main/units/systemd-reboot.service
[4] https://manpages.debian.org/unstable/systemd/systemd.unit.5.en.html
[5] https://raw.githubusercontent.com/bus1/dbus-broker/main/src/units/system/dbus-broker.service.in
[6] https://raw.githubusercontent.com/systemd/systemd/main/src/core/mount.c
[7] https://raw.githubusercontent.com/systemd/systemd/main/src/systemctl/systemctl-util.c
[8] https://manpages.debian.org/unstable/systemd/systemd.service.5.en.html
[9] https://manpages.debian.org/unstable/systemd/systemd-system.conf.5.en.html
[10] https://manpages.debian.org/unstable/systemd/systemd.resource-control.5.en.html
