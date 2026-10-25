# Native GPU, sharing, SSH and status source review — 2026-10-25

## Evidence boundary

Base revision: `304c079` (`mcr/main`); the checkout was initially clean.
This report records source inspection and permitted serialization. No test,
fixture, discovery import, native syntax checker, policy parser, service,
desktop application, GPU probe or host management helper was executed. No
disposable environment was created, requested or used. No installed system
was changed or deployed. `AGENTS.override.md` and `docs/test-isolation.md`
require this boundary permanently.

The referenced root `debian-preseed-de-audit.md` is absent. Historical reports
were treated as provenance for their snapshots. Independent read-only sidecar
review was attempted, but agent startup failed with encrypted-context hydration
errors; it supplies no review evidence for this working tree.

## 1. Native application GPU selection

The supplied `todo/installer-state/installer.log:18` and `:19` identify Intel
`0000:00:02.0` (`0x8086`) and NVIDIA `0000:2d:00.0` (`0x10de`). The user reports
Intel at `/dev/dri/renderD128` and Quadro P520 at `renderD129`. The old native
sandbox helper exposed every render node; generic NVIDIA environment hints did
not bind a Chromium/Firefox client to one node. This permits the reported wrong
renderer, but the logs do not prove which API selected Intel in every client.

The new `labwc_managed_app/gpu.py` resolves device, sysfs vendor, driver and PCI
identity together, validates GLVND vendor metadata, bounds enumeration, and
checks device identity again before appending sandbox binds. Native managed
and qBittorrent sandboxes expose the selected render node; NVIDIA adds only its
matching `/dev/nvidiaN` and `/dev/nvidiactl`. Generic launches receive matching
environment and Chromium flags. Conflicting selectors are removed before
publication. The ordinary qBittorrent launch now consumes the managed default.

The same selection supplies exact PCI `DRI_PRIME` for Mesa, the EGL vendor file,
Firefox `MOZ_DRM_DEVICE`, NVIDIA VA-API device and Chromium
`--render-node-override`. Explicit missing/ambiguous selection returns failure
before startup. The profiles, staging manifest, package trust manifest and
AppArmor source include the new delegate and its read-only discovery paths.
An unselected adapter without its driver does not block an explicit selection
of another adapter. An unspecified launch without a supported PCI GPU retains
the software-capable path; explicit vendor requests still fail unavailable.

Primary API references inspected:

- [Mesa environment selectors](https://docs.mesa3d.org/envvars.html).
- [GLVND vendor enumeration](https://github.com/NVIDIA/libglvnd/blob/master/src/EGL/icd_enumeration.md).
- [Chromium Ozone switches](https://github.com/chromium/chromium/blob/main/ui/ozone/public/ozone_switches.cc).
- [Firefox DRM device selection](https://searchfox.org/firefox-main/source/widget/gtk/DMABufDevice.cpp).
- [NVIDIA multi-GPU guidance](https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/latest/optimus-laptops-and-multi-gpu-desktop-systems.html).

Existing Vulkan restrictions and Qt compositor policy are retained. GPU API
support, DMA-BUF interchange, video decoding, single-instance application reuse
and actual hardware acceleration remain unverified. A process already running
with another renderer retains it until exit. The private Zoom/Discord Xwayland
implementation, configuration and two-application eligibility remain unchanged.

## 2. Empty sharing mount destination

`todo/journalctl:125` and `:2436` contain the reported nonempty destination
warning. The supplied fstab uses a self-bind at `/data/sharing`, while installer
NFS/Filen provisioning populates that same directory before boot. Inspection of
[systemd v262 mount.c](https://raw.githubusercontent.com/systemd/systemd/v262/src/core/mount.c)
confirms the nonempty-directory warning is issued before the bind mount.

The public destination now stays empty offline. A root-owned `0700` parent
holds `/data/.sharing-store/root`, which is bound at `/data/sharing` with the
existing `shared,nosuid,nodev,noexec` options. The home view retains
`rbind,rslave` and its dependencies. NFS and Filen provision their children in
the backing tree; exports, service paths, ACL semantics and public names remain
at the mounted path. The private parent prevents ordinary accounts bypassing
mount restrictions through the source path.

Installer reruns reject mismatched layout, a nonempty public destination,
unexpected backing ownership or links. This implements fresh installation;
there is no live data migration. An interrupted installation can leave its
private backing tree for inspection and will refuse an unproven retry rather
than conceal or overwrite that state. Boot mount ordering, propagation, NFS and
Filen service behavior remain unverified.

## 3. Profile-controlled OpenSSH

All ten profiles declare a literal boolean and a unique five-digit port from
32001 through 32010. Both P15s profiles are false; the other eight are true.
The complete mapping is in `d-i/forky/hosts/README.md`.

Before package fragment collection, the installer fetches the canonical profile
and parses only these literal fields as data. Enabled profiles add `addon/ssh`
to the effective class/cache/context/debconf plan, selecting the existing
`classes/class-addon/ssh.cfg` and `openssh-server`. Runtime hooks require the
same boolean, selected class and profile port. No SSH boot argument is needed;
legacy values must agree with the profile. Conflicting explicit SSH classes on
disabled profiles are rejected.

The existing `ssh/lan_ed25519.pub` provisioning path remains the primary
account's authorized_keys path. The authored target installer now requires
successful key/config verification and the packaged `ssh.service` before
offline enablement. The daemon, nftables overlay and Fail2ban jail share the
profile port. No target SSH server, authentication or network behavior was
tested. Tailscale SSH remains independent; tailnet authorization was not
available as evidence and was not queried or changed.

## 4. Status process churn and service detection

The second supplied attachment reports 66,010 audit records, 11,184 events,
9,681 EXECVE records and 16,245,156 bytes over 1,832.284 seconds. It attributes
repeated launches to five-second brightness, capture, battery and notification
status, ten-second Bluetooth status, thirty-second keyboard status and output
policy queries. These are supplied observations, not new measurements.

Both Waybar layouts now use native Bluetooth and backlight modules. Recording
and notification mode use a continuous Gio reader with one asynchronous call
in flight, bounded replies, producer ownership tracking, obsolete-reply fences,
100 ms event coalescing, four-second calls and a five-second connection budget.
Only mode names and recording ActiveState are consumed; no notification body or
service command line is emitted. Battery uses bounded kernel power-supply
events with a one-second scan throttle. Both reader types cache JSON output
and reconcile once a minute without creating another process. Broken output
pipes, manager disconnects and shutdown are handled; reader restart is bounded
by Waybar's 30-second restart interval.

Keyboard status retains its startup/change signal and drops the timer. Obsolete
brightness/Bluetooth/capture refresh signals are removed. The output watcher
retains startup reconciliation, explicit actions and settled DRM events and
drops unconditional 30-second policy execution. Its existing monitor ownership,
bounded cleanup and process-capture API are unchanged.

For the six changed status modules, the old configuration scheduled 56 custom
status launches per minute per bar. The new configuration schedules none of
those periodic custom launches during healthy idle operation; it starts three
continuous readers and performs keyboard updates on demand. This is a source
configuration calculation, not an observed EXECVE, CPU or power measurement.
Native reconciliation, signals, explicit actions and failure restarts still do
work. Other modules and application activity are outside that calculation.

Fail2ban's SSH jail follows actual profile-selected OpenSSH enablement. With no
SSH/web jail the target daemon is masked offline. CrowdSec removes its generic
Linux umbrella collections and installs their non-SSH parser/LPE components
explicitly; SSH collection installation is conditional. Its readiness marker
also records the SSH policy. No force-removal of tainted policy is requested.
Audit, firewall, local privilege escalation and qBittorrent detection remain
selected. Authentication acquisition remains because it also carries local
privilege escalation signals. Audit execution rules and logging limits remain
unchanged; no Python or shell executable is exempted from telemetry.

Primary interfaces inspected:

- [Waybar custom streams](https://github.com/Alexays/Waybar/blob/master/man/waybar-custom.5.scd),
  [native Bluetooth](https://raw.githubusercontent.com/Alexays/Waybar/master/src/modules/bluetooth.cpp),
  [native backlight](https://raw.githubusercontent.com/Alexays/Waybar/master/src/util/backlight_backend.cpp).
- [Mako mode API](https://raw.githubusercontent.com/emersion/mako/master/dbus/mako.c).
- [CrowdSec Linux dependencies](https://raw.githubusercontent.com/crowdsecurity/hub/master/collections/crowdsecurity/linux.yaml)
  and [Linux LPE dependencies](https://raw.githubusercontent.com/crowdsecurity/hub/master/collections/crowdsecurity/linux-lpe.yaml).
- [CrowdSec collection removal](https://docs.crowdsec.net/docs/cscli/cscli_collections_remove/).

The authored installer verification boundary checks the new delegates' presence,
root ownership, exact modes, link count, size, unresolved tokens and Python AST.
It also requires packaged Gio/GLib APIs before consumer activation. That target
verification code was inspected as data and was not invoked here.

## Static evidence and remaining gates

Performed: source/caller/policy inspection; stdlib AST data parsing of changed
Python and the edited embedded installer Python; JSON shape parsing of both
Waybar layouts with inert placeholder substitutions; profile literal/port
inspection; Git whitespace checking; generated archive/manifest/pin comparison.
No managed module was imported for these inspections.

Fixtures were authored/updated for GPU node enumeration reversal, ambiguity,
driver/manifest mismatch, identity replacement, selector conflicts, preserved
Chromium operands, nonempty/symlinked sharing state, profile/class/port conflicts,
continuous-reader coalescing, obsolete replies, reply bounds, unavailable states,
subscription races, unchanged-output caching, pipe closure, signal shutdown,
kernel event filtering, missing sockets and CrowdSec failure propagation. Every
fixture remains **unexecuted**. No passing suite or native acceptance is claimed.

The target contract is Debian Forky, Python 3.14 and systemd 262. Supplied capture
versions are evidence only for that capture; no new image or installed package
set was inspected. Native launch/shutdown, rendering, loaded AppArmor policy,
boot mounts, SSH login, event delivery and CrowdSec behavior remain unverified.
Before/after CPU, EXECVE, audit bytes, CrowdSec load and power results are absent.
The repository prohibition does not authorize executing those checks elsewhere
or substituting development-host execution.

Artifact hashes, source and fixture fingerprints, generated inventory state and
the exact final static outcomes are recorded below after serialization.

## Final serialization receipt

Full base revision: `304c079b1a4cf61a703fb063b0dfaf7b50d4b5ea`.

Changed payload input files: 48; fingerprint `76b2796426fcd6a19c37b31819d24157614e23fc8c2b02ebaa1d6b258870a738`.

Changed fixture files: 15; fingerprint `30357cc2a3eaa2edad0a13d9b4e4b745ab134f774bb218f3a2840318ea059393`.

Each fingerprint is SHA-256 over sorted repository-relative paths encoded as
`path + NUL + binary SHA-256(file bytes)`. Generated products and this report
are excluded; fixture bytes are fingerprinted separately.

| Product | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.tar.gz` | 26646747 | `d00007ba1e2b564fa6a1add889348bbd021a3c8f6ce45affd055dd37abb39620` |
| `d-i/forky/payload.manifest` | 226713 | `014c9ae79568630d9e6b477428b4a779191ad862b307220089f38de74f6ba69c` |
| `d-i/forky/preseed.cfg` | 96407 | `5878b9b5df8834021b01d138cae3bfb794f9149d10ba54a5ccc93f859e843328` |
| `inventory.json` | 2489932 | `6a97e7efee5c3931faacc23862c3fa1089d97cc7b693aff7dbb5381a6af40ae8` |
| `inventory-apt.json` | 19194589 | `f7f7f319bd1eb6eef7c7f2919e067ce7f7e858fedc47456109f9cbb39b6fbefc` |

Exact generation outcomes:

- `make build` completed after the final source correction: **1,840 payload files**.
  It invoked `python3 -B tools/build.py`; no tests or validators were invoked.

- `make inventory` initially failed during Microsoft Debian 13 package-index
  acquisition (`apt-2ddaebee56dc7f42`) before publication. Both old inventories
  were byte-identical to HEAD; no recovery/scratch path remained. One explicit
  bounded retry completed after the final build: 1,840 members, 1,810 text
  files, 353 relevant source files and **21,370 package candidates**.
  The final pair has zero acquisition errors and no missing declared package
  requests. It is current for the payload hash above. These are indexed
  candidates, not dependency solving, package installation or verified vendor
  signatures. The collector records that OpenPGP verification was not performed.

- Final stdlib AST-as-data inspection parsed **27 changed Python files**
  plus the edited embedded runtime-contract Python. No repository imports.

- Final archive comparison inspected **1840 members / 35,001,764 expanded
  bytes**. Member names, source bytes, manifest digests, normalized headers and
  complete source inclusion agree. The preseed archive, manifest and transport
  pins agree. Neither archive members nor embedded shell text were executed.

- Waybar JSON shape inspection with inert substitutions succeeded for both
  layouts; it checked native status fields, continuous reader restart fields
  and the absence of the removed periodic custom status intervals. This is not
  a rendered UI, native Waybar parse or event-delivery result.

- All ten profile booleans and unique ports were inspected as literal data.
- `git diff --check` completed without whitespace diagnostics.
- Seven private Xwayland implementation/configuration files and audit
  execution rules remain byte-identical to the base revision.

The supplied systemd capture reports **262 (262-1)**; the supplied NVIDIA
kernel log reports **580.142** at lines 886–887. These are historical capture
versions, not a new target result. The refreshed metadata includes systemd
262-1/262.1-1, Python 3.14.8/3.14.9, Waybar 0.15.0-1+b1 and
`libnvidia-gl-580` 580.142-0xanmod1 among its amd64 candidates. Repository/class
pins, architecture and APT solving still determine a real installed image.

### Fixture revisions (all unexecuted)

| Path | SHA-256 |
| --- | --- |
| `d-i/forky/tests/test_compat_gpu_portal.py` | `a4c3f74016cecdac227f124c37600ec4b1cb3f97b3ac68b9da586ad0be0feb97` |
| `d-i/forky/tests/test_compz_qbittorrent_followup.py` | `30edc173ab7a34903856a4f6ec4d3d1be0d09a50fbb067b529eafe09e3ca4bab` |
| `d-i/forky/tests/test_config_safety.py` | `eadd6e221edc88ff33c6c637022ed9dd52881ab96ac87416cf9940353705aee8` |
| `d-i/forky/tests/test_crowdsec_firstboot_retry.py` | `e25acd21c4c4cb079c22875aea5e776f665a0d22bc636d300b20d5891c8c211e` |
| `d-i/forky/tests/test_fail2ban_clipboard_apparmor_20260928.py` | `6ea549403b29210d0ad2be90d2e794a2a56318c50c173985be769d734050c098` |
| `d-i/forky/tests/test_filen_sync_20261017.py` | `b2cb85e97d7a68b93ead71cddca847f91a4cafe7cf8ba37c825d71cc28332aec` |
| `d-i/forky/tests/test_firstboot_audit_20260926.py` | `10e3d2befd58665f68fd5069078073d3d46055c1a97e6ec46d43df360bcc1da2` |
| `d-i/forky/tests/test_installation_fixes_20260912.py` | `ab4ad9c7ff6d2c0fbdb643173f393f581adab164d0ad3e74a6ce42e908bcbf49` |
| `d-i/forky/tests/test_kernel_veth_networking.py` | `f5f8a638142a7d646e74c02a099a019a0a423ee660cb613fa3684740e226d120` |
| `d-i/forky/tests/test_native_gpu_selection_20261025.py` | `c9aa0c983909a7a6622c8333fe1041d4d36bce85b183aae7a4367d9ee4383912` |
| `d-i/forky/tests/test_network_sharing.py` | `6c9f2c23b09ab3d0910cac2e8eece5d8b513e8526359f6e4e4d1a97745c4b35d` |
| `d-i/forky/tests/test_power_keyboard_20260913.py` | `83d9e5c0f62ad1582995074b49aa4dfb2c74bd6ddb4a18b71303df887cc84ef7` |
| `d-i/forky/tests/test_profile_ssh_policy_20261025.py` | `cd18923273a142526179f6626d2d2670df52b6c94968ddbb7f2856556ababc4e` |
| `d-i/forky/tests/test_themes.py` | `550cdfcfed2a5b74bf4ce6b041147009283ac0c687271c72cf224f3ed18a93c6` |
| `d-i/forky/tests/test_waybar_events_20261025.py` | `f668d0272c9d4c483d4aedc81eb9c7cb13805bb14d94abdde0b8b53fdfde2883` |

### Exact changed paths

```text
d-i/forky/hooks/target/etc/apparmor.d/abstractions/native-gpu-selection
d-i/forky/hooks/target/etc/apparmor.d/desktop-utilities
d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
d-i/forky/hooks/target/etc/apparmor.d/labwc-session
d-i/forky/hooks/target/etc/fail2ban/jail.d/10-sshd.local.tmpl
d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl
d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/style.css.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-bluetooth.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-brightness-control.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-capture.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-qbittorrent
d-i/forky/hooks/target/usr/local/bin/labwc-system-action.tmpl
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/cli.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/generic.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/gpu.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/integrity.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/mounts.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py
d-i/forky/hooks/target/usr/local/libexec/labwc-output-watch
d-i/forky/hooks/target/usr/local/libexec/labwc-waybar-battery
d-i/forky/hooks/target/usr/local/libexec/labwc-waybar-events.tmpl
d-i/forky/hooks/target/usr/local/libexec/labwc-waybar-exec
d-i/forky/hosts/README.md
d-i/forky/hosts/installer/account.env
d-i/forky/hosts/profiles/btrfs-de-duo.env
d-i/forky/hosts/profiles/btrfs-de-flex-duo.env
d-i/forky/hosts/profiles/btrfs-de-flex.env
d-i/forky/hosts/profiles/btrfs-de-p15s-duo.env
d-i/forky/hosts/profiles/btrfs-de-p15s.env
d-i/forky/hosts/profiles/btrfs-de.env
d-i/forky/hosts/profiles/f2fs-de-hp14-duo.env
d-i/forky/hosts/profiles/f2fs-de-hp14.env
d-i/forky/hosts/profiles/f2fs-de-x360-duo.env
d-i/forky/hosts/profiles/f2fs-de-x360.env
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
d-i/forky/preseed.cfg
d-i/forky/scripts/common/modules/context-target.sh
d-i/forky/scripts/common/modules/profiles.sh
d-i/forky/scripts/common/ssh.sh
d-i/forky/scripts/desktop/components/apps.sh
d-i/forky/scripts/desktop/components/desktop-config.sh
d-i/forky/scripts/desktop/components/target-assets.sh
d-i/forky/scripts/desktop/filen-install.py
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/scripts/firstboot/assets/var/lib/firstboot/bin/crowdsec-firstboot.tmpl
d-i/forky/scripts/late/crowdsec.sh
d-i/forky/scripts/late/network-sharing.py
d-i/forky/scripts/late/security.sh
d-i/forky/scripts/runtime/modules/classes.sh
d-i/forky/ssh/sshd_config
d-i/forky/tests/test_compat_gpu_portal.py
d-i/forky/tests/test_compz_qbittorrent_followup.py
d-i/forky/tests/test_config_safety.py
d-i/forky/tests/test_crowdsec_firstboot_retry.py
d-i/forky/tests/test_fail2ban_clipboard_apparmor_20260928.py
d-i/forky/tests/test_filen_sync_20261017.py
d-i/forky/tests/test_firstboot_audit_20260926.py
d-i/forky/tests/test_installation_fixes_20260912.py
d-i/forky/tests/test_kernel_veth_networking.py
d-i/forky/tests/test_native_gpu_selection_20261025.py
d-i/forky/tests/test_network_sharing.py
d-i/forky/tests/test_power_keyboard_20260913.py
d-i/forky/tests/test_profile_ssh_policy_20261025.py
d-i/forky/tests/test_themes.py
d-i/forky/tests/test_waybar_events_20261025.py
docs/validation/native-gpu-sharing-ssh-status-20261025.md
inventory-apt.json
inventory.json
```

No native acceptance or before/after performance result is available. The
source implementation and generated data are reviewable; the full runtime
outcome remains unproven under the permanent static-only execution boundary.

## Completion audit follow-up

The next goal continuation re-read the configured generic worker, continuous
reader lifecycle and the attachment requirements. A fresh byte comparison
confirmed all 48 changed payload inputs, all 15 changed fixtures and all five
generated products still match the recorded fingerprints/hashes above. No
runtime check was substituted for the prohibited acceptance work. This bounded
review found no additional source defect in the worker forwarding or reader
lifecycle paths.

| Requested outcome | Current authoritative evidence | Acceptance evidence still missing |
| --- | --- | --- |
| Correct Intel/NVIDIA rendering for defaults and explicit actions | PCI/device/environment/Chromium selection source and unexecuted private fixtures; generated archive matches current inputs | Actual renderer used by newly launched applications, acceleration and native launch/shutdown behavior on the target |
| Remove the nonempty sharing mount warning | Empty public destination and backing-tree provisioning source; matching generated payload | Target boot with the new layout, absence of the warning and working NFS/Filen propagation |
| Profile-driven OpenSSH, key and high port | Ten literal profile declarations, class planning and key/config/firewall source; current generated products | Fresh target installation, enabled/disabled service state, installed key/config and successful authorized authentication |
| Reduce churn without reducing telemetry and align detection | Native/continuous status configuration, removed timers, unchanged audit rules, conditional Fail2ban/CrowdSec source | Before/after helper CPU, launches, audit bytes, CrowdSec CPU and idle power; actual Tailscale authorization policy and access results |

### Tailscale SSH access-path inspection

The attachment explicitly requests evaluation of Tailscale SSH through its
actual policy/access path. Source tracing establishes the following local
configuration, without querying a daemon or installed helper:

- Every shipped profile explicitly sets `TAILSCALE_RUN_SSH_SERVER="true"`,
  including both P15s profiles that disable conventional OpenSSH. All declare
  empty advertised tags and `TAILSCALE_SHIELDS_UP="false"`.
- `scripts/late/tailscale.sh` renders that separate boolean into the firstboot
  unit; `tailscale-up` passes it as `tailscale up --ssh=...`.
- `etc/nftables/services/tailscale.yml.tmpl` retains Tailscale SSH on TCP 22,
  independently of the new conventional OpenSSH ports.
- The tailscaled unit runs the existing netkit delegate. Its AppArmor policy
  gives only the named `login`/`su` transition to `tailscale-ssh-host`; that
  helper restores validated fixed host namespace identities and then executes
  the packaged login/su path. It does not implement tailnet authorization.

Upstream specifies that Tailscale SSH intercepts tailnet TCP 22 and requires
both network access and SSH access rules for the source, destination and local
SSH users. It does not obtain that authorization from OpenSSH authorized_keys.
See [Tailscale SSH documentation](https://tailscale.com/docs/features/tailscale-ssh).

Filename/content inspection found no actual tailnet SSH policy in the checkout
or supplied `todo/` data. A redacted policy export covering the applicable SSH
rules, network grants/ACLs, groups and tags has been requested. No private API,
live host state, remote access attempt, credentials or tailnet configuration
was queried or changed. This evidence gap is independent of OpenSSH class and
port selection, and prevents an authorization acceptance claim.
