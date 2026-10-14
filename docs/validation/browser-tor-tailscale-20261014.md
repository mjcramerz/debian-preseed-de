# Supplied logs, Tor Browser and Tailscale — 2026-10-14

## Evidence and execution boundary

Read all 95 non-key-manager files supplied under `todo/`, including the older
`todo/.~` journal, all managed logs, installer/firstboot state, `journalctl` and
the two explicit AppArmor records. `todo/key-manager` is a supplied code tree,
not log evidence. The current journal contains 2,552 lines; the application log
duplicates its browser events. Duplicate copies do not count as separate
incidents.

The target evidence identifies Debian Forky, systemd 262, a Lenovo IdeaPad Flex
5 14ITL05, firmware FXCN49WW and kernel 7.2.10-x64v3-xanmod1. No development-host
package, service, security, network, device, user or systemd state was queried
or changed for testing. No repository module, test, validator, browser, policy
parser or installed management helper was executed. No software was compiled.
Specialist delegation was attempted, but agent content hydration failed; there
is no independent agent-review result.

`AGENTS.override.md` requires a prepared disposable test environment without
host access. None was supplied. The performed inspection uses standard-library
AST/JSON/archive parsing of source/data, and the explicitly permitted pure
`make build` serializer. These are not native runtime acceptance tests.

## 1. Graphics and AppArmor

There are 12 eDP-1 atomic `EBUSY` failures, starting at `todo/journalctl:1733`
and `todo/managed/apps/apps.log:189`. Browser activity precedes them, but the
failure originates in the compositor's DRM atomic commit. Applications already
receive render nodes rather than DRM display-control devices. Direct scanout
and hardware cursors were already disabled; repeating those settings would
not address the observed path.

The two Flex profiles now select `LABWC_WLR_DRM_NO_ATOMIC=1`. The exact 0/1
input is validated, rendered into the desktop configuration/session wrapper,
and imported into the compositor's systemd environment. Inherited overrides
are cleared first. Other profiles default to 0. This selects wlroots' legacy
KMS path while retaining OpenGL application rendering.

This is a targeted workaround, not a proven correction to the kernel atomic
queue. It needs a real Flex display check. An
[upstream wlroots/Sway report](https://github.com/swaywm/sway/issues/9179)
also records atomic EBUSY and a separate legacy-backend black-screen problem on
different Intel hardware with wlroots 0.20. Set the profile value to 0 to return
to atomic KMS if that target's legacy path fails. No source build, global kernel
parameter or Xwayland change was introduced.

Vivaldi's Vulkan/EGL errors at journal lines 1750–1758 explicitly originate in
Dawn adapter discovery. The existing browser arguments already request
`--use-gl=angle --use-angle=gl` and disable Vulkan features. The OpenGL discovery
failure is an unsupported requested context version; it is not evidence that
ANGLE's active rendering context failed. Chromium's
[GPU information implementation](https://raw.githubusercontent.com/chromium/chromium/main/content/browser/gpu/gpu_data_manager_impl_private.cc)
also schedules Dawn information collection independently of normal rendering.
No supported switch that deterministically removes this diagnostic was
established. These warnings remain unresolved upstream; no invented switch,
GPU-sandbox weakening or warning suppression was added.

Both explicit AppArmor denials are in `usr.sbin.tailscaled`: `systemd-run` and
`dpkg` execution from the built-in update flow. The accepted update policy is
implemented by `TS_ALLOW_ADMIN_CONSOLE_REMOTE_UPDATE=false` in its drop-in and
`tailscale set --auto-update=false` before both fresh enrollment and the
already-joined shortcut. Existing signed APT maintenance owns package updates.
The daemon receives no package-manager or service-manager grants.

## 2. Tailscale Wi-Fi

Journal lines 1671–1694 show a rebind to `wifi0` at 19:56:52, Ethernet removal,
the old DERP close at 19:56:55, and a new DERP connection in that same logged
second. Thus Wi-Fi reconnects three seconds after the route rebind; there is no
demonstrated permanent Wi-Fi failure. Existing configured-Wi-Fi/wildcard
interface firewall rules and native Tailscale rebind handling are retained.
No restart hook or extra firewall grant was added.

The older `todo/.~` bootstrap failure is historical evidence. Current bootstrap
already distinguishes pending machine approval, removes the staged key and
uses the bounded retry contract; external tailnet approval cannot be supplied
by an installer code change.

## 3. Other supplied findings

| Finding | Current disposition |
| --- | --- |
| Two uncaught missing-extension promises, journal 1734–1735 | Vivaldi UI requests extension `jplgfhpmjnbigmhklmmbgecoobifkmpa`, which is absent from repository extension policy. Requires vendor handling of the absent extension/profile state; not repaired by an AppArmor grant or installing an unrelated VPN extension. Remains unresolved. |
| 532 unknown extension EventAck messages | Chromium/Vivaldi extension lifecycle diagnostic for `jffbochibkahlbbmanpmndnhmeliecah`. Supplied evidence does not establish a repository-owned cause. Remains unresolved. |
| NoScript icon denied to Vivaldi UI | Chrome extension `web_accessible_resources` boundary, not filesystem AppArmor. The signed extension manifest remains intact. Remains upstream. |
| Three missing guest errors | Internal Vivaldi guest-view lifecycle, without a proven launcher contract failure. Remains upstream. |
| Three Fontconfig missing-default-file messages | Outer launcher already binds `/etc/fonts` and the installed font stack. The records do not identify which vendor child/root lacks the file. Requires child-sandbox reproduction; no guessed path or confinement relaxation. Unresolved. |
| Ten Waybar GTK accelerator-group assertions | Existing menu XML defines accelerator groups; the failing upstream tray/plugin instance is unproven. Requires native packaged Waybar reproduction. |
| Missing Vivaldi search caches | Vivaldi owns its signed caches. Current source intentionally does not stage unsigned copies. Fresh cache generation/vendor fetch remains to be verified. |
| Global Xwayland absent | Matches the requested private-Xwayland-only policy. Zoom/Discord policy is unchanged. |
| Foot hangup messages | Terminal close lifecycle; no failed retained service established. |
| Crystal Dock/LayerShellQt, ksecretd and other toolkit compatibility messages | No supplied fatal startup failure. No component removal or compilation. |
| Older Waypaper monitor-enumerator fallback | The fallback selects All, matching current swaybg configuration. Specific enumerator support requires vendor/native reproduction. |
| CrowdSec console not enrolled and CAPI disabled | Enrollment requires external acceptance; CAPI disabled matches configured policy. Existing local acquisitions and firewall bouncer remain. |
| CrowdSec duplicate grok pattern | Upstream parser diagnostic; no parser startup fatal error in this snapshot. |
| CrowdSec audit ParseKV error on auditd rotation | Current source already stages the local auditd-daemon parser before generic audit parsing. No further policy expansion; native parser result remains untested. |
| qBittorrent acquisition/profile absent early in boot | Its profile exists after the managed application runs; no evidence supports an alternate user acquisition or removal of the data-volume gate. |
| Fail2ban new database warning | Expected fresh database creation; sshd jail starts successfully. |
| Initial Bluetooth identity-file absence | Fresh state initialization, without a retained failed service. |
| Ethernet ifdown cannot find eth0 | Interface was removed; its unit stops successfully and Wi-Fi takes over. |
| ACPI reservation, UCSI error 88/-5 and xHCI slot warnings | Firmware/kernel/device behavior. No deterministic repository repair established; no driver disabling or source compilation. |
| Other HID/I2C/TDX/HPET/aux/uncore/ASoC/SPI probe diagnostics | Hardware/firmware/kernel findings without an established installer cause. |
| Installer Mullvad AppArmor reload warning | Vendor maintainer-script chroot boundary; final managed profile staging/mode reconciliation is a separate installed contract. |
| Installer Glycin bwrap warning | Installer artwork-check boundary; does not establish an installed browser security failure. |
| Installer MOK sync source absent, partition alignment warning | Missing installer EFI source and alignment within logged tolerance; target verification completes. |
| Empty scanner logs | Do not prove completed or successful security scans. |

The supplied firstboot failed-unit inventories are empty and its validation
record reports no failed units. This is evidence from the supplied install,
not a new deployment result for these changes.

## 4. Tor Browser integration

See [the runtime and maintenance contract](../tor-browser.md). The canonical
install module authenticates the requested 15.0.25 binary archive, stages the
desktop actions/runtime and publishes an immutable root-owned bundle. Managed
profiles, veth application selection, broker guard/MAC logic, RAM runtime,
verification assets and AppArmor staging/modes are wired. All four desktop
actions create fresh tmpfs state and copy the immutable bundle into RAM. The
transient service requires zero swap and disables memory content in core dumps.
The browser gets an independent network namespace and private Tor SOCKS/control
Unix sockets. Bundled Tor alone uses the veth for native relay TCP connections.
Tor has no 3proxy, dnsmasq or Stubby path. The firewall rejects DNS and non-TCP
traffic before the shared DNS DNAT hook. Native Wayland is mandatory, with
`MOZ_ENABLE_WAYLAND=1`, `GDK_BACKEND=wayland`, a required private Wayland socket,
no DISPLAY/Xauthority and no X11 socket bind.

The downloaded public archive's SHA-256 matches the upstream release manifest:
`37432d6f4d9b1f1190ba2cfbbd4ab9dad5ccd52c14aa47a21795d08273f4a165`.
It has 247 regular-file/directory members, no links/special nodes, and includes
the expected Firefox wrapper, `firefox.real`, bundled Tor and profile seed.
Its size is 137,994,120 bytes. The pinned public key has the documented primary
fingerprint and SHA-256
`7cec103d0be11b608f61850143101e56f0ba45383b61f44835300ff54ef93032`.
These byte/structure observations do not substitute for the installer GnuPG
verification, which has not been executed here.

Tor has no automatic maintenance-provider integration in this change. The
immutable bundle disables browser self-updates; installed deployments require
authenticated administrator-controlled replacement or updated fresh-install
pins. ANOM does not change the physical network MAC, virtualize CPU instructions
or promise absolute anonymity. Native Tor can reach public TCP relay ports other
than 53, including 9001. External pluggable transports are explicitly denied;
their DNS/bootstrap and UDP requirements have not been integrated. Every RAM
session also resets Tor guard state; see the documented privacy tradeoff.

## Verification record

- Static Python AST inspection of 35 files, including the managed-app modules, new Tor helpers,
  proxy supervisor, veth broker and changed regression fixtures, without
  importing or executing them.
- Static JSON/template/profile/pin and archive-member inspection.
- `git diff --check` inspected patch whitespace successfully.
- Regression fixtures updated for KMS scoping, Tailscale update ownership,
  Tor networking/RAM boundaries, URI/flag rejection and preserved spare veth
  capacity; not run.
- All 24 pre-existing `APPS` entries match HEAD as parsed AST data, including
  Zoom/Discord compatibility policy. Ten host profiles share the same four
  Tor release/key pins; all four desktop Exec actions use the managed launcher.
- Source metadata inspection found new files with private creation modes;
  exactly ten task-created files were normalized to source mode 0644.
  The pre-existing private mode on the unrelated package `__init__.py` was
  preserved. Source mode is distinct from target executable mode 0755.

### Pure generation

Executed the reviewed, permitted serializer with an empty environment:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
```

It reported `built 1781 payload files` and exited 0. Standard-library archive
inspection compared all 1,781 member bytes (34,207,398 bytes total) with canonical
source and manifest hashes. Member paths, deterministic metadata and preseed
payload/manifest/bootstrap pins match. All eight Tor assets are present, with
no Tor proxy asset or private-input/key material in the payload.

Metadata for 3,161 nonproduct checkout paths remained unchanged during
generation. The output parent directory retained its inode, owner and mode;
atomic publication necessarily changed its entry metadata. Only the three
generated installer files were published. An initial metadata assertion
included that parent directory's timestamp; the corrected comparison accounts
for the expected publication metadata change.

| Product | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `14b484e343f56273f14720606badfb57a1696635a9c26f78efca1fe354094e67` |
| `payload.manifest` | `edac949935a8a6b8398c5c08fd96a1874b181bd11f34d09fd250e88ffc7551bc` |
| `preseed.cfg` | `511d3e7ef920b4352133849efc2805d65e17c870542f709fd9f7234b55e743e3` |

Native GnuPG, shell parsing, AppArmor policy parsing, desktop-file validation,
systemd verification, target GPU/legacy KMS behavior, Tor bootstrap/onion access,
direct-network denial and process cleanup remain required disposable/target
acceptance checks. No passing result is claimed for them.

## Changed paths

Canonical/source changes and the three generated installer products:

- `d-i/forky/hooks/target/etc/app-veth.nft.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/abstractions/tor-browser-runtime`
- `d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/tor-browser`
- `d-i/forky/hooks/target/etc/apparmor.d/usr.sbin.tailscaled`
- `d-i/forky/hooks/target/etc/apparmor/modes.conf.tmpl`
- `d-i/forky/hooks/target/etc/labwc/desktop.conf.tmpl`
- `d-i/forky/hooks/target/etc/systemd/system/tailscaled.service.d/override.conf.tmpl`
- `d-i/forky/hooks/target/opt/tor-browser/Browser/distribution/policies.json`
- `d-i/forky/hooks/target/usr/local/bin/labwc-session.tmpl`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/cli.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/commands.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/generic.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/session.py`
- `d-i/forky/hooks/target/usr/local/libexec/tor-browser-install`
- `d-i/forky/hooks/target/usr/local/libexec/tor-browser-run`
- `d-i/forky/hooks/target/usr/local/sbin/app-veth`
- `d-i/forky/hooks/target/usr/local/share/applications/tor-browser.desktop`
- `d-i/forky/hooks/target/usr/local/share/software/tor-browser/developers.asc`
- `d-i/forky/hosts/profiles/btrfs-de-duo.env`
- `d-i/forky/hosts/profiles/btrfs-de-flex-duo.env`
- `d-i/forky/hosts/profiles/btrfs-de-flex.env`
- `d-i/forky/hosts/profiles/btrfs-de-p15s-duo.env`
- `d-i/forky/hosts/profiles/btrfs-de-p15s.env`
- `d-i/forky/hosts/profiles/btrfs-de.env`
- `d-i/forky/hosts/profiles/f2fs-de-hp14-duo.env`
- `d-i/forky/hosts/profiles/f2fs-de-hp14.env`
- `d-i/forky/hosts/profiles/f2fs-de-x360-duo.env`
- `d-i/forky/hosts/profiles/f2fs-de-x360.env`
- `d-i/forky/payload.manifest`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/preseed.cfg`
- `d-i/forky/scripts/common/modules/app-veth-identity.sh`
- `d-i/forky/scripts/desktop/components/core-renderers.sh.tmpl`
- `d-i/forky/scripts/desktop/components/desktop-helpers.sh`
- `d-i/forky/scripts/desktop/detect.sh.tmpl`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`
- `d-i/forky/scripts/firstboot/assets/var/lib/firstboot/bin/tailscale-up`
- `d-i/forky/scripts/late/security.sh`
- `d-i/forky/scripts/late/software.sh.tmpl`
- `d-i/forky/scripts/late/tor-browser.sh`
- `d-i/forky/tests/test_kernel_veth_networking.py`
- `d-i/forky/tests/test_native_contracts_20260923.py`
- `d-i/forky/tests/test_session_reliability_20260921.py`
- `d-i/forky/tests/test_session_repairs_20260920.py`
- `docs/app-veth.md`
- `docs/tor-browser.md`
- `docs/validation/browser-tor-tailscale-20261014.md`
