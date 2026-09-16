# R5 - explicit application classes and orderly shutdown

Date: 16 September 2026. Baseline: the accepted complete R4 archive,
`debian-preseed-de-systemd2612-apparmor-gitops-r4-20260916.tar.gz`.
This is a complete fresh-install publishing tree, not a live-host upgrade script.

## Scope and evidence

The three requested application-class assignments are explicit. The shutdown
review found an actionable source defect: the R4 root power worker always
terminated the invoking account first, escalating TERM/KILL after short waits,
and then used `systemctl --force` for reboot/poweroff. Single force still contacts
PID 1, but skips the ordinary service-stop transaction [1]. In that path, adding
unit stop-timeout drop-ins alone would not restore normal service teardown.

The supplied `user-systemd-delegate` dump already gives `user@.service` a
120-second stop timeout and `KillMode=mixed`. Those settings are preserved. The
resource audit confirms systemd 261.2-1 on the installed host. The reviewed
attachments do not establish a timed shutdown failure or prove that the named
processes caused the intermittent delay. The source fix below is justified
independently; it is not a measured claim that every shutdown hang is resolved.

## Explicit application classes

Under `d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/`:

| File | Active configuration |
| --- | --- |
| `app-.scope.d/60-resource-class.conf` | `[Scope]` and `Slice=app.slice` |
| `waybar.service.d/60-resource-class.conf` | `[Service]` and `Slice=app.slice` |
| `crystal-dock.service.d/60-resource-class.conf` | `[Service]` and `Slice=app.slice` |

These files contain no weights, timeouts or lifecycle changes. The existing
`app-.scope.d/50-session-labwc.conf` is unchanged. The scope-prefix policy is now
an explicit administrator choice, rather than a speculative optimization. It
does not create scopes or migrate a running process; managed application
launchers continue to pass their existing `--slice=app.slice` property.

`desktop_install_user_resource_policy` stages these policies before the original
home-copy step. Panel/dock policies require their base service to have been
staged. The runtime scope prefix intentionally has no base file to probe.
Desktop verification checks the new files in both the skeleton and account home,
as well as the two global broker stop drop-ins. Existing ownership and private
home-directory handling are preserved.

## Normal machine shutdown, not an unconditional force path

After authorization, active-session checking, application-save preparation and
the second other-account check, reboot/poweroff now request:

```sh
/usr/bin/systemctl --no-ask-password --no-block reboot
# or the identical options followed by poweroff
```

No `terminate-user`, user-slice kill, manual sync subprocess or `--force` runs on
this machine-power path. PID 1 retains responsibility for ordered unit stops,
service stop hooks, final process cleanup and filesystem shutdown. Requests are
explicitly nonblocking: this worker is itself part of the shutdown transaction,
and must not wait for its own stop to complete [1]. The CLI already documents
reboot/poweroff as queued operations; the explicit option records the intent.

One bounded retry remains for a failed submission; both attempts are ordinary
requests. There is no automatic forced escalation. The worker marks commitment
after a successful request. Before commitment, a failure allows the existing
session helper to remove the closing barrier and report an error. Preparation
may already have closed applications gracefully; failure recovery does not
resurrect those processes. Transport errors can leave acceptance uncertain, so
a failed response is not proof that PID 1 received no request.

`terminate_user` is explicitly restricted to logout. Its existing account-local
cleanup behavior is retained. Suspend retains the separate locker-readiness and
systemd sleep/GPU-hook path; its pre-existing `--force suspend` command is not the
machine shutdown path. No executable path, sandbox, privilege, AppArmor rule,
service restart rule or worker runtime/stop budget is widened or replaced.

## Broker-only stop grace

Both broker scopes receive `60-stop-timeout.conf`:

```ini
[Service]
TimeoutStopSec=30s
```

The source files are templates in the system and global-user broker drop-in
directories. Their sole token is
`__INSTALLER_DBUS_BROKER_TIMEOUT_STOP_SEC__`. All 13 profiles define:

```sh
DBUS_BROKER_TIMEOUT_STOP_SEC="30"
```

Accepted values are canonical integer seconds from 5 through 120. Missing,
multiline, signed, padded, suffixed, infinite and out-of-range values fail before
either timeout file is published. The existing atomic per-file publisher is
used; a valid multi-file update is not claimed to be a cross-file transaction.
A failed fetch cannot expose a partly rendered destination file.

The existing broker publisher installs these files after the original hardening
files and before offline unit enablement, in the configured override directories.
It does not restart a live bus. No `dbus-broker-lau.service` is invented: the
launcher is a process within `dbus-broker.service`, not a separate service to kill.

Thirty seconds is a local stop-grace policy, not a demonstrated optimum or a
whole-machine shutdown deadline. The documented control-group kill default and
SIGKILL fallback cover both the launcher and broker child [2][3]; this revision
does not replace them, override vendor socket ordering, change startup timeouts,
add watchdog activation, or shorten all service stop limits. Notify services can
extend a stop timeout, and kernel-uninterruptible tasks cannot be made killable
by a configuration file [2]. Custom later administrator drop-ins can override
these settings, so inspect effective properties on the actual host.

The current upstream broker fragments retain socket dependencies, ordering
before `basic.target`/`shutdown.target`, and the user broker's `session.slice`
placement [5][6]. Existing local and package dependencies are left intact.

Hardware `RebootWatchdogSec` governs the later shutdown phase after regular
services have been stopped, not a replacement for per-service stop ordering [4].
R5 does not change hardware watchdogs, system manager defaults, user@.service's
120-second budget, logind policy, or shutdown target forced-reboot actions.

## Preserved boundaries

R4 AppArmor profiles and local fragments are byte-identical, including Edge's
Workspace denial. Podman/zram workloads and generators are unchanged. The
original workload-policy regression fixture still passes. GitOps mirror support
and diagnostics are retained unchanged.

The six managed I/O weights, independent accounting switch, controller delegation,
compositor 300/300 policy, audio CPU-only preference, sensitive-process core
limits, child system slices and vendor-preserving coredump socket policy remain
as accepted in R4. The broker stop policy does not depend on the I/O switch.

## Validation and deployment

See `VALIDATION-R5.md` and `validation/r5/`. Tests use isolated trees, mocked power
commands and offline manager graphs; no test reboots this environment or loads
policy into its kernel. The available manager is systemd 257.9, not the target
261.2 binary. The online Debian manuals retrieved for the review are in the
261 family, not an authenticated copy of the target package build.

Extract into a clean directory and publish the entire tree, with the rebuilt
`payload.tar.gz`, `payload.manifest` and `preseed.cfg` together. Do not restart the
live system or session broker just to apply a drop-in. This archive does not
silently edit an already installed host; account-local skeleton files alone also
do not update an existing home directory outside the installer home-copy step.

### Post-installation inspection (read-only)

Run user commands as the desktop account; inspect the effective units, not just
the source templates:

```sh
systemctl --user cat waybar.service crystal-dock.service
systemctl --user show waybar.service crystal-dock.service -p Slice -p DropInPaths
cat "$HOME/.config/systemd/user/app-.scope.d/60-resource-class.conf"
systemctl --user list-units --all 'app-*.scope'
# For an actual listed scope, inspect it with: systemctl --user show NAME -p Slice -p DropInPaths

systemctl cat dbus-broker.service
systemctl show dbus-broker.service -p TimeoutStopUSec -p KillMode -p SendSIGKILL -p DropInPaths
systemctl --user cat dbus-broker.service
systemctl --user show dbus-broker.service -p TimeoutStopUSec -p KillMode -p SendSIGKILL -p DropInPaths
systemctl show "user@$(id -u).service" -p DelegateControllers -p TimeoutStopUSec -p KillMode
systemctl --user show labwc-compositor.service -p Slice -p CPUWeight -p IOWeight
systemctl cat systemd-coredump.socket
```

After saving work, perform separately planned logout, reboot and poweroff checks
on the installed host. Check for normal service stop messages and broker timeout
messages, rather than inferring a cause from the last process name on screen.
If a slow shutdown recurs, retain the previous-boot journal where persistence is
available; this codebase can use volatile log storage, so `-b -1` may have no data.
Do not change persistence or upload logs implicitly.

```sh
journalctl --list-boots
sudo journalctl -b -1 --no-pager -o short-monotonic \
  -u dbus-broker.service -u "user@$(id -u).service" -u 'labwc-admin-action@*'
journalctl --user -b -1 --no-pager -o short-monotonic -u dbus-broker.service
# During a delay, from an available terminal:
systemctl list-jobs
```

Confirm which phase was slow before changing any further timeout. A failed
broker's last output, per-unit stop timeout, user-manager exit and later kernel
watchdog messages are different observations, not interchangeable diagnoses.

## Primary references reviewed

1. systemctl force, reboot/poweroff and nonblocking semantics:
   https://manpages.debian.org/unstable/systemd/systemctl.1.en.html
2. Per-service stop timeout and notification extensions:
   https://manpages.debian.org/unstable/systemd/systemd.service.5.en.html
3. Cgroup-wide stop and final-signal semantics:
   https://manpages.debian.org/unstable/systemd/systemd.kill.5.en.html
4. Manager defaults and hardware watchdog shutdown phases:
   https://manpages.debian.org/unstable/systemd/systemd-system.conf.5.en.html
5. Upstream system broker unit (moving upstream reference; not a target binary):
   https://github.com/bus1/dbus-broker/blob/main/src/units/system/dbus-broker.service.in
6. Upstream user broker unit (same qualification):
   https://github.com/bus1/dbus-broker/blob/main/src/units/user/dbus-broker.service.in
