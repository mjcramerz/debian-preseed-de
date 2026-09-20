# Native wlsunset and Waybar hover - 20 September 2026

This follow-up supersedes the Gammastep indicator portion of the preceding
20 September session repairs. It is based on the complete previously delivered
repository, not on an older original ZIP. Other desktop repairs are retained.
The private Zoom/Discord Xwayland runtime and its launch arguments are unchanged.
No upstream source is patched or compiled by this change.

## Package and retirement scope

`d-i/forky/classes/class-select/role/desktop.cfg` now selects Debian's `wlsunset`
in place of `gammastep`, `geoclue-2.0`, and the indicator-only
`gir1.2-ayatanaappindicator3-0.1`. The preexisting Ayatana runtime library used by
other desktop applications is not removed. The old managed indicator executable,
desktop entries, static user unit, system configuration, AppArmor profiles,
installer enablement, and profile boolean are removed.

The installer-only repair helper retires exact obsolete managed files and known
activation links in the target and selected account. Descriptor-relative
operations reject symlinked or writable parents, never recurse, never follow a
leaf symlink, and leave unrelated files untouched. It removes the old managed
GeoClue authorization drop-in; it creates no replacement location-service policy.
Old names remain only in this guarded retirement code, negative regression tests,
and dated historical evidence. They are not an active implementation.

This repository installs hosts unattended; publishing it does not modify an
already-running host. There is intentionally no indiscriminate live APT purge,
recursive home cleanup, global service masking, or removal of another application's
GeoClue dependency. A fresh installation no longer explicitly requests the old
packages. Package dependencies of other applications remain the package manager's
responsibility.

## Profile settings

Every one of the thirteen `d-i/forky/hosts/profiles/*.env` files contains:

```sh
WLSUNSET_ENABLED="true"
WLSUNSET_LATITUDE="55.60587"
WLSUNSET_LONGITUDE="13.00073"
WLSUNSET_TEMPERATURE_DAY="6500"
WLSUNSET_TEMPERATURE_NIGHT="4500"
WLSUNSET_GAMMA="1.0"
WLSUNSET_SUNRISE=""
WLSUNSET_SUNSET=""
WLSUNSET_TRANSITION_SECONDS="1800"
WLSUNSET_OUTPUTS=""
```

Latitude/longitude default to Malmo, Sweden. North/east are positive and
south/west negative. These are geographical coordinates, not altitude; wlsunset
has no altitude command-line setting. The latitude range is -90..90 and longitude
range -180..180. Decimals must be finite literal values, not shell expressions.
Coordinates are configurable; no geolocation request, DNS lookup, network account,
API key or GeoClue service is used.

With both manual times empty, the daemon calculates its solar schedule from the
coordinates. `WLSUNSET_TRANSITION_SECONDS` is used only with a manual schedule;
it is intentionally not passed in astronomical mode. To use local-clock scheduling,
set BOTH `WLSUNSET_SUNRISE` and `WLSUNSET_SUNSET` to `HH:MM`. These replace the
coordinate arguments for that invocation. Manual transitions must be ordered
within a single local day, rather than wrapping across midnight. Host system
time/timezone must be correct; the service does not override `/etc/localtime`.

Day/night values are integer Kelvin temperatures in 1000..10000, with day strictly
greater than night; gamma is 0.1..10. Transition duration is 1..21600 seconds.
These are explicit managed-policy bounds, not a statement that upstream accepts
only this subset of values. `WLSUNSET_OUTPUTS=""` applies to all supported outputs,
including outputs discovered by the running daemon. A space-separated list such
as `"eDP-1 DP-1"` restricts adjustment to named connectors through repeated `-o`
arguments. Up to sixteen unique, validated connector names are accepted. There
is no unvalidated extra-arguments escape hatch.

The installer validates the policy, renders a root-owned mode-0644
`/etc/default/labwc-wlsunset` from the dedicated template, and runs the installed
controller's `check` action before considering staging complete. Runtime parsing
is literal tokenization, not shell sourcing or evaluation. Unknown, duplicate,
missing, oversized, malformed, redirected, multiply-linked or writable
configuration files are rejected. A disabled policy still has to be valid.

## Runtime and lifecycle

`/usr/local/bin/labwc-wlsunset` is a short-lived, isolated-system-Python controller.
It is not a wrapper loop masquerading as a daemon. `/usr/bin/wlsunset` itself is
the long-running process. Labwc autostart invokes the controller only after
activation-environment publication, session-target startup, and output readiness.

Default application command:

```sh
/usr/bin/wlsunset -T 6500 -t 4500 -g 1.0 -l 55.60587 -L 13.00073
```

The controller submits a fixed-name `labwc-wlsunset.service` through
`systemd-run --user --collect --service-type=exec --expand-environment=no`.
It uses a transient SERVICE, not a scope, static installed service, shell
background process, cron job, or recurring timer. The controller waits for exec
startup to succeed, not for the long-running application to finish. A successful
submission does not prove the compositor accepted gamma control for every output;
inspect the journal and the real display for that acceptance gate.

An owner-checked mode-0600 flock file and the fixed unit name serialize operations.
The lock inode is retained until runtime-directory teardown. Repeated `start`
calls do not replace an active instance; `restart` validates new policy and the
current session before stopping the old instance. A loaded unit with this name
that is not the expected managed transient service is refused. `stop` acts only
on that unit, never on arbitrary process names/PIDs. Garbage-collection waits,
subprocess calls, and lock waits are bounded.

The service has `PartOf=labwc-session.target`, `Requisite=labwc-session.target`,
`BindsTo=labwc-compositor.service`, and ordering after both. Systemd owns and
reaps its control group. Logout/compositor stop tears it down; manual stop does
not trigger a restart. `Restart=always` covers the upstream successful-exit path
on display disconnection as well as crashes, with a ten-second delay and three
start attempts per five-minute window. Persistent failure stops automatic retries
and remains in the journal, rather than spinning. With `--collect`, a terminally
failed unit can disappear from `systemctl --failed`; retain journal diagnostics.
Use the controller's `start` after resolving the failure. No separate restart
watchdog or bus/Wayland polling daemon is installed.

## Wayland identity and environment

Start/restart require a non-root desktop user, a private canonical
`/run/user/UID` directory, and the real user bus socket. Caller-provided bus
addresses are not trusted. The controller queries the user manager's imported
activation variables, verifies active session/compositor units, and compares
`LABWC_PID` with the compositor's `MainPID`. It opens the named Wayland socket
and verifies Linux `SO_PEERCRED` PID and UID against that compositor. A stale,
symlinked, noncanonical or private nested compositor socket is rejected.

The verified `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`, `XDG_SESSION_TYPE`,
`LABWC_SESSION_OWNER` and `LABWC_PID` are passed explicitly using `--setenv`,
with a fixed PATH and C locale. The daemon's environment drops inherited X11
selectors, `WAYLAND_SOCKET`, loader-injection variables, Python-path variables,
D-Bus addresses and timezone overrides. This does not modify global compositor
or private Zoom/Discord environment policy.

## Security boundary

The transient service uses no-new-privileges, empty capability sets, AF_UNIX-only
sockets, namespace-creation restrictions, locked personality, no executable
writable mappings, native syscall architecture and the `@system-service` syscall
allowlist. Core dumps are disabled; limits are 64 MiB memory, eight tasks and 128
file descriptors. Shutdown is control-group scoped with a five-second timeout.
These limits and the restart budget are fixed audited policy, not arbitrary
profile-provided command fragments.

Two explicit AppArmor executable attachments separate controller and daemon.
The controller can read only its root-owned policy and required runtime/identity
metadata and operate the user manager. The daemon needs libraries, timezone data,
the user-owned Wayland socket, and its narrowly named unlinked gamma-ramp file.
The compositor gains narrowly scoped read/write permission for that same
`/tmp/wlsunset-shared-*` file family: upstream transfers an O_RDWR descriptor,
and the kernel file_receive hook checks both open modes even when the receiver
only reads its contents. Its explicit labelled UNIX send/connect rule names the
managed compositor. AppArmor mediates filesystem-named sockets through file rules;
the controller's SO_PEERCRED check additionally verifies the actual compositor
identity at startup. Standard-library and journal access come from the distribution's
base abstraction; this includes that abstraction's existing grants, not a claim
that it is an empty allowlist. No application-specific home-data grant is added.
`mediate_deleted` is necessary for upstream's unlinked temporary-FD handoff.
Primary/render GPU device and internet access are explicitly denied to the daemon.
This is a native Wayland protocol client, not a second KMS owner.

Executable attachment is used deliberately: systemd documents `AppArmorProfile=`
as unsupported in per-user managers. The design does not rely on ignored root-only
sandbox properties or add mount/user namespaces just to make those properties work.
Effective enforcement still depends on the installed AppArmor mode and kernel
features; fixture tests and offline policy compilation are not enforcement tests.

## Operations

In the actual managed desktop session, as its user:

```sh
labwc-wlsunset check
labwc-wlsunset status
labwc-wlsunset start
labwc-wlsunset restart
labwc-wlsunset stop
systemctl --user show labwc-wlsunset.service \
  -p Transient -p MainPID -p ExecStart -p Environment -p PartOf -p BindsTo -p NRestarts
journalctl --user -b -u labwc-wlsunset.service --no-pager
```

`check` may also run as root because it only reads policy and prints the validated
application command. User-manager operations must not run with sudo. `stop` is
session-local; subsequent desktop login starts the configured policy again.
For a persistent disable, set `WLSUNSET_ENABLED="false"` in the selected installer
profile before rebuilding, or administratively edit the installed root-owned
configuration and invoke `labwc-wlsunset restart` as the desktop user. That action
stops any current managed daemon without creating another.

Do not run another gamma-control client alongside it. Check real sunrise/night
adjustment, stop/reset behavior, output hotplug, DPMS resume and logout on the target.
A compositor/output that does not provide the required gamma-control protocol is
not repaired by an environment variable or service restart. Hardware KMS issues
from the preceding task remain a separate acceptance gate.

## Waybar

`#custom-window-switcher:hover` is now in the exact selector group shared by the
Menu, workspace, wayscriber and application buttons. It uses their existing
warm-gold gradient, dark foreground, border and shadow. The later green hover
override is removed. Normal non-hover icon colour, geometry, click action,
workspaces and native switcher implementation are unchanged. The shared template
covers both internal and external bar configurations.

## Validation and publication

Current machine-readable results and logs are in
`validation/2026-09-20-wlsunset/`. Earlier dated verification directories are
historical snapshots, not claims about this revised payload. This container runs
Debian 13/systemd 257, not the requested Forky/systemd 261.2 graphical target.
Offline checks do not certify live gamma adjustment, GPU-driver behavior or the
visual Waybar hover result.

Publish the complete repository atomically through the existing serving workflow.
The payload archive, manifest and preseed pins are rebuilt together. Follow the
updated `docs/repairs-20260920/TARGET-ACCEPTANCE.md` for real-target checks.

## Primary references consulted

- Debian Forky binary package and dependency listing:
  `https://packages.debian.org/forky/amd64/wlsunset`.
- Upstream source distributed by Debian, inspected but not modified:
  `https://sources.debian.org/src/wlsunset/0.3.0-1/main.c` and
  `https://sources.debian.org/src/wlsunset/0.3.0-1/wlsunset.1.scd/`.
- Transient service semantics, explicit environment and exec startup:
  `https://manpages.debian.org/unstable/systemd/systemd-run.1.en.html`.
- User-manager sandbox availability and AppArmor caveats:
  `https://manpages.debian.org/unstable/systemd/systemd.exec.5.en.html`.
- Linux AppArmor FD-receipt/open-mode mediation, inspected but not modified:
  `https://github.com/torvalds/linux/blob/master/security/apparmor/lsm.c` and
  `https://github.com/torvalds/linux/blob/master/security/apparmor/include/file.h`.
- Malmo default coordinates, GeoNames ID 2692969:
  `https://www.geonames.org/2692969/malmoe.html`.

- AppArmor UNIX socket rule semantics and standard base-abstraction grants:
  `https://www.apparmor.net/man/4.0/apparmor.d/` and
  `https://gitlab.com/apparmor/apparmor/blob/master/profiles/apparmor.d/abstractions/base`.
