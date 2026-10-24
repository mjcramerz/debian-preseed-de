# Custom Power Profiles API and vendor drop-in — 2026-10-24

## Outcome and scope

Newly staged Intel custom-tuning installs now provide the current and legacy
Power Profiles D-Bus APIs through the existing hardware tuning broker. The
public service stays available while custom tuning owns the hardware. The
stock PPD executable is replaced by an unprivileged API adapter through an
administrator **drop-in**, not a replacement service unit or a service symlink.

This supersedes the masked-activation disposition in
[the earlier startup report](startup-shutdown-followup-20261024.md). It changes
installer source and its serialized payload; no installed machine was repaired
or deployed. Existing unrelated work, Xwayland and manual CrowdSec Console
enrollment were preserved.

Base revision: `5926f21a0ac7c8ef331cc4011c3e7fc06c01cffa`, branch `mcr/main`.
The 18 production files and two fixture files listed below have aggregate
SHA-256 `bb7a7c38767644ec8ff8eb8ea9ee1ab554a06ea24ab773d0b93c1aa5c7526169`,
calculated in sorted repository-relative path order as
`path + NUL + bytes + NUL`. Documentation and generated products are excluded
from that fingerprint.

## Service and update behavior

The installer publishes
`/etc/systemd/system/power-profiles-daemon.service.d/50-hardware-tuning.conf`.
The package continues to own `/usr/lib/systemd/system/power-profiles-daemon.service`
and its enablement. The existing desktop stage enables it offline. Local
drop-ins take precedence over vendor settings and normally survive package
updates; see the [systemd unit documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html).
Future changes to the vendor base unit still require compatibility review.

The reviewed package was Debian `power-profiles-daemon_0.30-2_amd64.deb`, read
over public HTTPS as bounded ar/tar data without extraction, installation or
execution. Package SHA-256:
`6e544d123ffbf3f99cf5ea64837e23a353a0248effa4993624f3f60a58813eef`.
The inspected package is available in the
[Debian package pool](https://deb.debian.org/debian/pool/main/p/power-profiles-daemon/power-profiles-daemon_0.30-2_amd64.deb).
This hash records inspected bytes; no package signature acceptance is claimed.
The intended target remains Debian Forky/systemd 262; no target image or live
package set was executed or measured.

The drop-in clears the old ExecStart and lifecycle commands, capabilities,
state directory and address-family list. It sets the configured desktop
UID/GID, `PrivateUsers=no` and `RemoveIPC=no`: retaining the vendor private UID
namespace would break real peer credentials, and retaining IPC removal could
delete the desktop account's IPC objects on service restart. The adapter gets
only Unix sockets, read-only trusted code and its own AppArmor domain. The
drop-in permits executable trampolines for libffi callbacks; it receives no
hardware, privileged helper execution or service-management authority.
`TasksMax=16` is now a drop-in setting. `PartOf=hardware-tuning.service`
propagates explicit broker restarts. Vendor unit dependencies, including its
conflicting policy services and boot ordering, remain inherited.

Both activation names explicitly use `SystemdService=power-profiles-daemon.service`:

- `org.freedesktop.UPower.PowerProfiles`, object
  `/org/freedesktop/UPower/PowerProfiles`;
- `net.hadess.PowerProfiles`, object `/net/hadess/PowerProfiles`.

The adapter registers both names and interfaces. D-Bus policy allows the
configured UID to own them. Mutations authenticate the caller's real D-Bus
Unix UID, then use the adapter's real UID on the broker socket. The broker
retains its configured-account and active-local-seat checks. Neither a claimed
caller UID nor an arbitrary worker command is accepted from D-Bus input.
Local activation files use the administrator system-service directory described
in the [D-Bus daemon manual](https://dbus.freedesktop.org/doc/dbus-daemon.1.html).

## Profile, hold and recovery contracts

| Public selection | Custom profile for each installed vendor |
| --- | --- |
| `power-saver` | `silent` |
| `balanced` | `balanced` |
| `performance` | `performance` |

The existing custom `high` menu selection reports public `performance` when
applied to Intel. Public selections cancel holds and set the baseline across
installed vendors. Battery/AC arbitration, thermal limits and backend readback
checks remain in the root broker and workers. The custom provider flag makes
the policy helper leave the public API service running; Intel's ownership
check exempts that adapter service while still rejecting other policy owners.
NVIDIA-only and non-custom installs preserve the stock provider path.

Holds use broker socket lifetimes. Power-saver takes precedence when holds
conflict. Caller disconnect, manual cancellation, adapter termination or broker
termination releases them. Manual cancellation emits `ProfileReleased` to the
holder. Holds are not persisted across boots. This follows the relevant
[Power Profiles API contracts](https://upower.pages.freedesktop.org/power-profiles-daemon/gdbus-org.freedesktop.UPower.PowerProfiles.html).
The adapter uses explicit asynchronous Properties methods as supported by
[Gio register_object](https://docs.gtk.org/gio/method.DBusConnection.register_object.html).

One bounded queue serializes broker requests off the GLib main loop. The
absolute request deadline includes queue waiting, connection and streaming;
read-only status refresh is bounded separately. Mutations are never retried
automatically after uncertain completion. A client with a shorter D-Bus
timeout may stop waiting while a root operation finishes; status must be
consulted before another mutation.

Failed policy acquisition records restoration intent and uses the existing
Stop/recovery path. Public Set acknowledges only after every installed vendor
reports the requested profile applied. Thermal refusal or incomplete recovery
returns failure and retains faults/journals. Worker journal restoration does
not read the new provider flag, so invalid provider configuration cannot block
that recovery operation. Stop/Reset restores hardware without withdrawing the
API; restored Intel baseline is reported as `balanced`, with a degraded reason
when a fault or recovery is pending. Optional PPD actions are empty and
BatteryAware is always true; disabling battery awareness is unsupported.

The custom autostart preference remains persistent and the broker recovers
from journals on every boot. API availability does not require opening an app
or performing a firstboot enrollment. These installer changes do not migrate
old masks or full administrator units on an already installed system.

## Changed source and fixture paths

All paths below are repository-relative:

- `d-i/forky/hooks/target/etc/apparmor.d/hardware-tuning`
- `d-i/forky/hooks/target/etc/apparmor.d/abstractions/hardware-tuning-intel`
- `d-i/forky/hooks/target/etc/hardware-tuning/broker.json.tmpl`
- `d-i/forky/hooks/target/etc/systemd/system/power-profiles-daemon.service.d/50-hardware-tuning.conf.tmpl`
- `d-i/forky/hooks/target/etc/dbus-1/system.d/90-hardware-tuning-power-profiles.conf.tmpl`
- `d-i/forky/hooks/target/usr/local/share/dbus-1/system-services/org.freedesktop.UPower.PowerProfiles.service.tmpl`
- `d-i/forky/hooks/target/usr/local/share/dbus-1/system-services/net.hadess.PowerProfiles.service.tmpl`
- `d-i/forky/hooks/target/usr/local/lib/hardware_tuning/common.py`
- `d-i/forky/hooks/target/usr/local/lib/hardware_tuning/broker.py`
- `d-i/forky/hooks/target/usr/local/lib/hardware_tuning/client.py`
- `d-i/forky/hooks/target/usr/local/lib/hardware_tuning/engine.py`
- `d-i/forky/hooks/target/usr/local/lib/hardware_tuning/intel.py`
- `d-i/forky/hooks/target/usr/local/lib/hardware_tuning/policy_owner.py`
- `d-i/forky/hooks/target/usr/local/lib/hardware_tuning/power_profiles.py`
- `d-i/forky/hooks/target/usr/local/libexec/hardware-tuning-power-profiles`
- `d-i/forky/scripts/desktop/hardware-tuning-config.py`
- `d-i/forky/scripts/desktop/hardware-tuning.sh`
- `d-i/forky/scripts/desktop/hardware-tuning-assets.list`
- `d-i/forky/tests/test_hardware_tuning_20260916.py`
- `d-i/forky/tests/test_hardware_tuning_handover_20260917.py`

Documentation changes: `docs/hardware-tuning/README.md`, the supersession note
in `docs/validation/startup-shutdown-followup-20261024.md`, and this report.
Generated changes: `d-i/forky/payload.tar.gz`, `d-i/forky/payload.manifest`,
`d-i/forky/preseed.cfg`.

## Checks actually completed

- Read entrypoints, delegates, installer ordering, vendor package unit and
  activation files, D-Bus API, AppArmor domains and existing recovery callers.
- Inline `/usr/bin/python3 -I -S -B -` using only standard-library source/data
  operations: parsed 11 Python ASTs; decoded both API introspection interfaces;
  rendered and parsed the D-Bus policy and both activation files; inspected
  drop-in resets, three vendor configurations and every hardware asset path.
  No repository imports, GI calls or runtime helper execution occurred.
- The first static pass stopped on an overly strict assumption that checkout
  source modes were 0644. They were 0600, with no execute bits. Modes were
  preserved; the corrected inspection checks non-executable source and the
  archive comparison independently confirms serialized 0644 metadata.
- Focused fixture updates describe service routing, hold precedence and
  cancellation, acquisition failure, inactive-seat refusal, thermal recovery,
  recovery independent of provider configuration and menu cancellation. They
  were **not executed**. No mocked or native test pass is claimed.
- `git diff --check`: exit 0.
- Reviewed pure Makefile/build/publication path, then invoked
  `/usr/bin/timeout --signal=TERM --kill-after=5s 60s make build PYTHON=/usr/bin/python3`:
  final invocation exited 0, producing 1,836 payload members. Earlier builds
  were superseded by the final recovery/deadline source fixes.
- Bounded standard-library streaming tar comparison: all 1,836 regular
  members and 34,896,272 expanded bytes match every current serialized source
  input and the manifest. Fixed uid/gid/mtime/mode and private-input name
  exclusions hold. All preseed archive/manifest/bootstrap pins agree.
- Read-only review sidecars failed initialization with
  `invalid_encrypted_content`; root performed review and integration. No
  independent review is claimed.

Final generated SHA-256:

| Product | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `a82aa9ba02f981c3a7d7d0307cc7d77e1feb660ea3efdeada6bb141b72a6d9cd` |
| `payload.manifest` | `3163370937b09f9942a675ec04652fb17a29ab11105919056fb3e0b881fce888` |
| `preseed.cfg` | `59755c3a19146d39898d25b13c3ee65d9aaf4e2b714ae3f71dfc8ad0eaad12b6` |

## Remaining acceptance and deployment limits

No host/target services, D-Bus managers, package state, hardware controls or
AppArmor policy were queried or changed. No test runner, native validator,
application, private-bus fixture or disposable target was executed. Native
acceptance remains open for GI callback registration, both bus activations,
policy enforcement, client property/hold lifecycle, service restarts, boot
ordering and actual hardware/thermal recovery on the target package set.
Serialization proves byte consistency, not installed-system behavior.

Both root inventories were inspected as data and still pin an older payload.
`inventory.json` and `inventory-apt.json` were not refreshed; they are stale
relative to this build. Offline consumers requiring a current inventory pair
must not use them with this payload until separate inventory generation has
completed. No deployment, commit or push was performed.
