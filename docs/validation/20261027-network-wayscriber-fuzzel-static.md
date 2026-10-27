# Boot, Wi-Fi, Wayscriber and Python Fuzzel source changes

Date: 2026-10-27. Base revision: `6ec809060c9baf9c93d4a47edfdd72ac9ec426fb`.
This report describes an uncommitted working tree. The pre-existing
`AGENTS.override.md` change belongs to the user and was preserved.

## Evidence and disposition

| Requirement | Supplied evidence | Source disposition |
| --- | --- | --- |
| Failed Wi-Fi shutdown service | `todo/journalctl:581-588`: mount namespace setup fails because `/run/network-wifi` does not exist. | Shutdown and carrier services declare private runtime/state directories. Runtime preservation keeps the shared suppression marker between oneshot invocations; `/run` still resets at boot. |
| Failed Wi-Fi firstboot | `todo/journalctl:597-602` and `1334-1339`: NM loads/updates the profile, then the helper rejects `wifi.mac-address`. The policy uses lower case. | Both Python and Perl validators compare canonical MAC spelling; a different address remains a mismatch. Other profile fields remain strict. The firstboot deadline is 120 seconds for two bounded NM operations; carrier reconciliation allows 90 seconds for its possible modify/down or modify/up sequence. |
| Automatic carrier preference | The source udev rule uses `SYSTEMD_WANTS`; the Ethernet interface is managed by ifupdown. | Add a timer for the configured Ethernet instance, 20 seconds after boot and 15 seconds after each reconciliation. Read kernel carrier for Ethernet preference. Retain restoration intent before disabling autoconnect, retry a failed disconnect, and avoid repeatedly rewriting unchanged autoconnect values. Explicit manual Wi-Fi sessions remain exempt. |
| Initramfs health | `todo/installer-state/logs/firstboot/data/validation-results.txt:20-21` reports one failed-unit check, naming the shutdown service. All seven captured stage logs exist. | Repair the service responsible for the health failure. Require all seven stage logs at the existing firstboot boundary. No initramfs boot failure is demonstrated by this capture. |
| Wayscriber click | `todo/journalctl:1375-1379`: the toggle rejects the active Wayland socket. The daemon started at `1223-1241`. | Use the caller's UID and exact private runtime directory; reject directory/socket aliases, wrong ownership and socket hard links. Accept compositor-selected socket modes within that private parent. |
| Wayscriber hover and invocation | The module uses only `on-click-release`; the backend is invoked through a transient user service. | Set `cursor: true` on both bar definitions. Keep release dispatch, use the absolute helper path, return asynchronously to Waybar, and bound the service runtime to 30 seconds with cgroup cleanup. Add an installed-source verification gate. |
| Wayscriber request lifecycle | The helper retried a non-idempotent toggle and imposed a five-second timeout on a native control path with an eight-second response window. Keyboard bindings also call the helper directly. | Start the managed service once, wait up to five seconds for its published native readiness record using a fixed observation loop, and send one toggle. Bound the three control phases to 5/5/12 seconds; the start and toggle commands each have a separate two-second cleanup budget. Preserve the service start limit. Return 75 with a sanitized `outcome-unknown` diagnostic when completion is unconfirmed; never retry that request. AppArmor grants read-only access to the published PID record while leaving native identity authorization in Wayscriber. |
| SSH binding the derived Wi-Fi address | `todo/journalctl:583`: sshd cannot bind the configured Wi-Fi address during startup. Wi-Fi IPv4 is always Ethernet IPv4 +1; the address is known even when it is not currently assigned to the interface. | Stage explicit-address `ssh.socket` listeners with socket-local `FreeBind=yes`, clear vendor default listeners, enable only `ssh.socket`, and remove the managed `ssh.service` enablement. Preserve Ethernet +1 and the configured port, independent of carrier, association or credentials. |
| DRM atomic failures | `todo/journalctl:1369-1370`: eDP-1 atomic commits return EBUSY at 22:30:09 and 22:30:13. The captured Wayscriber click is at 22:30:41. | **Unresolved.** The capture does not identify the failing client/commit or establish a causal connection to the click. No global atomic-KMS workaround or Xwayland change was made. |

BlueZ reports that it generated the missing identity key successfully immediately
after the warning (`todo/journalctl:349-352`). Tailscale startup health messages
and the missing global Xwayland diagnostic were reviewed in their startup
context. The existing private Zoom/Discord policy was preserved. CrowdSec and
ACPI/UCSI errors were excluded as requested.

The captured target identifies systemd `262 (262-1)` in
`todo/installer-state/logs/firstboot/data/systemd-version.txt`. The journal's NM
plugin path identifies NetworkManager `1.58.1`. No host package query or target
image execution was performed. `debian-preseed-de-audit.md` is absent from this
checkout; no acceptance claim is made from an unavailable audit document.

The kernel capture identifies Linux `7.2.13-x64v3-xanmod1`, build
`#0~20261026.gf11b168` (`todo/managed/system/kernel.log:1`). The display driver
identifies i915 Tigerlake, display 12.00 C0, and DMC firmware 2.12
(`kernel.log:684-693`). The audit records near the two DRM errors show Waybar's
image loader at 22:30:10 (`todo/managed/security/audit/auditd.log:7662-7672`),
without evidence identifying which atomic commit failed. Temporal proximity
does not establish its cause. Exact installed Labwc/wlroots/Wayscriber package
versions are not established by the supplied text evidence.

The address rule is deterministic: `network-generate.pl:721-724` gives Wi-Fi
offset 1; the Python and Perl runtime validators reject a dual-link policy that
does not use Ethernet IPv4 +1 in the same subnet. SSH's resolver uses the same
increment. For Ethernet `192.168.50.82`, Wi-Fi is `192.168.50.83`, independent of
carrier, credentials or association. Selection of a managed adapter and whether
the kernel currently has its address assigned are separate from that calculation.

## Fuzzel contract

`d-i/forky/hooks/target/usr/local/bin/labwc-fuzzel.tmpl` is a self-contained
`#!/usr/bin/python3 -IB` adapter using only the packaged standard library.

- `launcher` selects the application launcher; `action` selects an action-row
  picker with action lifecycle logging; `menu` selects a menu-row picker.
  `computer-management` and `power-confirm` remain supported entrypoints.
- Installed geometry, output classification, palette, prompt and log scope are
  retained. Relevant desktop settings are parsed as literal assignments rather
  than sourced as shell code. Geometry overrides remain forbidden.
- The Computer Management icon rules retain their order and all 216 theme-token
  occurrences, comprising 180 distinct token names.
- Managed rows use `visible-label + NUL + icon + US + icon-name`. Legacy section
  markers are presentation only. Duplicate visible labels get deterministic
  suffixes and recover the original raw choice. An appended Back row participates
  in disambiguation and maps to the empty raw choice. A native selection that
  returns one complete NUL/US metadata row is reduced to its visible label before
  raw-choice recovery; malformed metadata is rejected.
- Unmanaged metadata and native `--dmenu0` input are passed to Fuzzel without
  managed decoration. Input is bounded to 1 MiB, 1,024 rows and 4,096 bytes per
  row. Selection and diagnostic streams have separate byte budgets and are
  drained concurrently. Multiple selected rows are rejected.
- Native custom-1 status 10 maps to public Back status 1. Silent native 1/2/130
  map to workflow-close status 3. Error or malformed diagnostics remain failure
  status 2; output is published only on successful selection.
- Lock descriptors are not inherited by child processes. PID cleanup checks the
  published file identity. TERM and KILL waits each have a two-second budget;
  unconfirmed termination retains the private runtime evidence and reports
  `outcome-unknown`. Interactive picker time remains intentionally unbounded.
- AppArmor includes the Python runtime, exact native input-file access and both
  signal endpoints needed for bounded cancellation. No policy was loaded.

The five existing Fuzzel fixture callers were updated to the Python interpreter.
`test_fuzzel_python_protocol_20261027.py` adds unexecuted cases for mode parsing,
protocol controls, aggregate limits, duplicate/decorated rows, raw-choice
recovery, statuses, multiple results, bounded termination, retained PID evidence,
identity replacement, MAC spelling and Wi-Fi suppression publication order.
The same unexecuted fixture source includes mocked Wayscriber start/readiness
failures, one dispatch after a failed reply or timeout, outcome propagation, the
bounded start/toggle commands, and the fixed readiness observation budget. Every
management/native command is replaced by a private stub; the readiness
observation is mocked, not a native readiness test. No real manager, daemon or
desktop connection is used by those cases.

## Static checks and generation actually performed

1. Inspected source, callers, service staging, AppArmor endpoints, supplied logs,
   `Makefile`, `tools/build.py` and `tools/publication.py` as data.
2. Ran `git diff --check`; exit status 0.
3. Used standalone `python3 -I -B` snippets with standard-library `ast.parse` on
   the changed Python sources and six changed fixture sources. Parsed the two
   edited embedded Python verifier bodies and the new Wayscriber mock program
   as data. No repository module or fixture was imported or executed.
4. Compared the old/new Fuzzel template-token multisets: 180 names, 216
   occurrences, no differences. Substituted literal values read from the three
   theme environment files as data and parsed the resulting Python AST.
5. Ran only the reviewed `make build` generation recipe. Final output:
   `built 1861 payload files`.
6. Used a standalone AST/literal contract check to confirm the Python Fuzzel
   helpers, launcher modes, public statuses, input/row/diagnostic limits,
   NUL/US metadata marker, environment settings and outcome handling are present.
7. Read the final gzip/tar archive as a stream, without extraction or execution.
   Compared every regular member's bytes against its source and manifest hash,
   checked archive ownership/mode metadata, and checked the preseed's payload
   and manifest pins. All 1,861 members matched; expanded bytes: 19,929,018.

The payload manifest fingerprint below identifies the serialized source inputs;
it is not runtime acceptance evidence.

| Artifact | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `a684302810c125be56e08ab5bac38b1d608b99e45ad07589dbb5ec2840526251` |
| `d-i/forky/payload.manifest` | `d48487780da07b71f1ade2ae65a5a769d051b2f8a35278f9e353ed36ea6d4067` |
| `d-i/forky/preseed.cfg` | `7c7c53462da6cd0139e4b4464601ced1395b1964969f6f1babc82d21bdf81b3b` |
| New protocol fixture source | `5851b6f09ade426595299e646252b3d5be78900c55d02e52891ac23e7c5cd33c` |
| Six changed fixture sources, sorted path/NUL/bytes/NUL fingerprint | `9a1c343f9a9bcb991a4025e50bf819b0ebcbe11d3f146e6eeb46b16f434402d4` |

## Socket-activation sweep

The system and user unit inventory was reviewed for services that are idle until
an occasional request. Existing request-driven endpoints already use sockets:
hardware tuning, Podman DevOps, Incus, D-Bus, PipeWire, the user SSH agent,
foot-server, the Codex app server and the packaged SSH server. Their clients
already speak the corresponding protocol, so no second activation path was
introduced.

`network-wifi-shutdown.service` remains a lifecycle unit. It is ordered after
NetworkManager and before `shutdown.target`, stays resident after its no-op
start, and performs the state capture from `ExecStop`; a socket would have no
client request to trigger and cannot provide that shutdown ordering or stop
hook. `network-wifi-carrier@.service` is a udev/dispatcher/timer-triggered
reconciliation, and `wifi-firstboot.service` is a boot reconciliation. Neither
has a request protocol that would make socket activation meaningful. The other
one-shot units in the sweep are boot, device, timer, path or shutdown lifecycle
actions, or already have a more appropriate activation mechanism. No additional
socket units were added.

## Verification limits and open work

No test, validation runner, native syntax checker, service operation, desktop
connection, package-management operation or disposable execution environment was
run. Fixtures are authored source, not passing test results. Nothing was
installed, loaded, deployed, committed or externally published by this work;
the three generated checkout artifacts were refreshed by the permitted build.

Wi-Fi cable transitions and reconnect, SSH inherited sockets, boot health,
Wayscriber interaction, Fuzzel rendering/launches and loaded AppArmor behavior
remain unverified on the target. Serialization proves byte consistency only.
Wayscriber's readiness path, publication ordering and response window were
reviewed against upstream source; compatibility with the exact installed native
package remains unverified. The wrapper leaves identity authorization to that
native client and does not read or replay its control token.
The DRM atomic EBUSY cause remains open; the full user objective is therefore
not marked complete.

## Changed paths

Runtime/staging sources:

```text
d-i/forky/hosts/README.md
d-i/forky/hooks/target/etc/apparmor.d/desktop-utilities
d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl
d-i/forky/hooks/target/etc/systemd/system/network-wifi-carrier@.service
d-i/forky/hooks/target/etc/systemd/system/network-wifi-shutdown.service
d-i/forky/hooks/target/usr/local/bin/labwc-fuzzel.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-wayscriber-toggle
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/network/ManagedNetwork/Validator.pm
d-i/forky/hooks/target/usr/local/libexec/network-wifi-configure
d-i/forky/scripts/common/ssh.sh
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/scripts/firstboot/04-validation.sh.tmpl
d-i/forky/scripts/late/network.sh
```

Unexecuted fixture sources:

```text
d-i/forky/tests/test_desktop_sandbox.py
d-i/forky/tests/test_fuzzel_python_protocol_20261027.py
d-i/forky/tests/test_kanshi_fuzzel_followup_20260919.py
d-i/forky/tests/test_menu_apparmor_integration_20260919.py
d-i/forky/tests/test_network_sharing.py
d-i/forky/tests/test_session_repair_edges.py
```

Generated products are `d-i/forky/payload.tar.gz`, `d-i/forky/payload.manifest`
and `d-i/forky/preseed.cfg`. This report is
`docs/validation/20261027-network-wayscriber-fuzzel-static.md`.

## Primary references used for contract review

- [systemd device activation semantics](https://www.freedesktop.org/software/systemd/man/258/systemd.device.html):
  `SYSTEMD_WANTS` acts on initial device activation.
- [systemd 262 socket semantics](https://www.freedesktop.org/software/systemd/man/latest/systemd.socket.html):
  explicit listeners, list reset, descriptor passing and `FreeBind`.
- [Debian OpenSSH socket activation guidance](https://sources.debian.org/src/openssh/1%3A10.5p1-1/debian/README.Debian):
  packaged sshd supports systemd socket activation.
- [Waybar 0.15 module event/cursor implementation](https://github.com/Alexays/Waybar/blob/0.15.0/src/AModule.cpp):
  release events and explicit Boolean cursor configuration.
- [Wayscriber runtime paths](https://github.com/devmobasa/wayscriber/blob/main/src/paths/mod.rs)
  and [daemon readiness publication](https://github.com/devmobasa/wayscriber/blob/main/src/daemon/core.rs):
  the runtime record is at `$XDG_RUNTIME_DIR/wayscriber/wayscriber.pid` and is
  published after control setup. This is a readiness hint; the native client
  authorizes the request against its own runtime identity.
- [Wayscriber native control](https://github.com/devmobasa/wayscriber/blob/main/src/daemon/control.rs):
  the legacy response window is eight seconds; a v2 admitted or committed request
  can have an indeterminate result. A wrapper must not retry an uncertain toggle.
