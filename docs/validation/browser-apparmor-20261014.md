# Supplied browser and AppArmor incidents, 2026-10-14

Historical report: the subsequent installed-system logs exposed an additional
`no_new_privs` restriction. The plain-profile transitions below were incomplete
and are superseded by [the October 15 correction](browser-apparmor-20261015.md).
That correction also adds Proton VPN to Vivaldi policy and gates Tor GPU actions.

## Scope and evidence

Reviewed all 54 files supplied under `todo/` as data (8,726,805 bytes, including
22 empty files). The current logs use October 15 local time; their Tor failure
occurred at October 14 22:40:50 UTC. The hidden `todo/.~` contains an older
October 13 boot. No installed host configuration, package state, service,
security policy, network, device or user profile was inspected or changed.

The checkout started clean on `mcr/main`. The requested target is Debian Forky
with systemd 262. No source compilation or Xwayland change was made.

## Tor Browser and AppArmor repairs

`todo/apparmor` contains two distinct denials, also present in the supplied
AppArmor log and audit rotation. There are no additional distinct access
denials in the supplied audit files.

1. `labwc-app` cannot list `/proc/13926/fd/`. Permit only the owning process's
   descriptor directory with `owner @{PROC}/@{pid}/fd/ r,`. This supports Python
   subprocess descriptor cleanup; it adds no descriptor-content read or write
   permission.
2. The bundled Tor executable cannot enter its transport profile. The supplied
   AppArmor log records successful loading of
   `labwc-app//tor-bwrap//transport` and `labwc-app//tor-bwrap//browser`, but the
   denied exec requests `tor-bwrap//transport`. The nested named `cx` transition
   drops the outer parent when resolving the target.

Both executable transitions now select the complete loaded label explicitly:

| Executable | Mode | Target |
| --- | --- | --- |
| `/opt/tor-browser/Browser/TorBrowser/Tor/tor` | `rpx` | `labwc-app//tor-bwrap//transport` |
| `/opt/tor-browser/Browser/firefox` | `rPx` | `labwc-app//tor-bwrap//browser` |

Lowercase `px` retains the supervisor's fixed bundled Tor library environment;
uppercase `Px` preserves the existing browser environment scrubbing. Neither
transition has an inherited or unconfined fallback. See Debian's
[directed transition documentation](https://manpages.debian.org/unstable/apparmor/apparmor.d.5.en.html)
and the AppArmor maintainer's
[explanation of named grandchild transitions](https://lists.ubuntu.com/archives/apparmor/2015-September/008549.html).
The supplied loaded/denied labels establish this incident independently of
the older upstream explanation.

The existing network and lifecycle contracts remain intact: the transport uses
the dedicated veth, its child denies IP datagrams, and the browser uses a
separate network namespace and denies IPv4/IPv6. The supervisor retains its
reciprocal signal/ptrace permissions. Runtime cleanup, cgroup shutdown, RAM
state, immutable release verification and private Wayland launch paths are
unchanged.

### Installation wiring

The canonical source is
`d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`.
`scripts/late/security.sh` includes `desktop-wrappers` in
`apparmor_managed_desktop_profile_files()` and stages it to
`/etc/apparmor.d/desktop-wrappers` at mode 0644 through the existing renderer.
The managed mode configuration already owns this profile.

`sandbox.py:bwrap_command()` enters `labwc-app//tor-bwrap` through `aa-exec`.
The authenticated software installer already stages `tor-browser-run`, the
bundle update policy and the desktop entry. The launcher profile already
requires the bundled Tor and Firefox executables. All normal, Intel, NVIDIA
and PurePrivacy Tor actions share this runtime and the repaired policy.

## Vivaldi extension findings and limits

The canonical `browser-config/policies.json` and all four installed browser
policy copies retain user-adjustable `normal_installed` policy for uBlock
Origin Lite, NoScript and Privacy Badger. Vivaldi's policy directory and entire
persistent configuration tree are exposed by its existing sandbox profile;
the AppArmor policy permits those configuration reads and user-owned writes.
There is no supplied AppArmor denial for Vivaldi or its extensions.

The missing ID in `todo/Fail:3-4` is Proton VPN, rather than one of those three
managed extensions. For current vendor evidence, inspected the prebuilt
Vivaldi **8.2.4133.87-1** package as data, without installing or executing it.
The package was 138,284,120 bytes with SHA-256
`0e259d867109ceaa3d011df7fc99fa5cc9484e4c77db33a7055e5dd941cb242f`, matching
the vendor's HTTPS package index. This is not a claim of independently
verified package signing or of the version installed on the reported machine.

The packaged UI still calls `management.setEnabled` for the Proton ID without
checking installation or handling the rejected promise in its VPN policy and
toolbar handlers. Disabling the VPN preference also invokes that function,
so that preference is not a verified repair. No unused VPN extension was added
and no packaged browser JavaScript was modified.

The NoScript messages in `todo/managed/apps/apps.log:188-189` concern the
options-page favicon. The upstream
[options page](https://raw.githubusercontent.com/hackademix/noscript/master/src/ui/options.html)
uses `img/noscript-options.webp`; the upstream
[manifest](https://raw.githubusercontent.com/hackademix/noscript/master/src/manifest.json)
does not expose it to other extensions. Chrome's
[web-accessible resource rules](https://developer.chrome.com/docs/extensions/reference/manifest/web-accessible-resources)
explain that refusal. It does not establish a failure of NoScript's blocking
engine. Changing AppArmor cannot repair a browser-origin resource restriction.

Vivaldi's first-run missing search-cache messages are also present. The current
checkout deliberately leaves those signed caches to Vivaldi, rather than
seeding unsigned JSON; this ownership was preserved. Successful cache creation
and extension installation/function remain unverified without an isolated
browser session. The supplied logs do not include extension inventory or
functional browser evidence. The Proton and NoScript UI messages are **not
claimed fixed**.

During this review the user reported that all three managed privacy extensions
appear to work. That observation is consistent with the UI-only failures above;
it is not an independently executed browser test. Their installation policy
and user settings were preserved.

Vendor references:
[Vivaldi extensions](https://help.vivaldi.com/desktop/appearance-customization/extensions/),
[Vivaldi Proton integration](https://help.vivaldi.com/desktop/privacy/proton-vpn-for-vivaldi/),
[Proton extension identifier](https://github.com/ProtonMail/WebClients/blob/main/packages/shared/lib/constants.ts),
[package index](https://repo.vivaldi.com/archive/deb/dists/stable/main/binary-amd64/Packages.gz),
[inspected package](https://repo.vivaldi.com/archive/deb/pool/main/vivaldi-stable_8.2.4133.87-1_amd64.deb).

## Remaining supplied records

| Records | Disposition |
| --- | --- |
| Fail2Ban startup in `todo/Fail:1-2` | Successful start; the separate Fail2Ban log confirms the SSH jail is running. New database creation is expected on a fresh install. |
| CrowdSec initial CAPI-disabled and unenrolled messages | Later records confirm CAPI registration, core detection/bouncer readiness and Console enrollment request success. Console approval remains external. |
| CrowdSec duplicate grok warnings | Upstream parser registration warnings followed by successful processing; no supplied parser failure. |
| CrowdSec missing qBittorrent log | Acquisition has file-discovery polling enabled; a removable-media application log can be absent before use. The supplied logs contain no qBittorrent launch demonstrating an acquisition failure. |
| Tailscale starting/stopped warnings | Current boot reaches `NeedsMachineAuth`; bootstrap retains state and retries while administrator approval is pending. The hidden older boot's failure is not the current outcome. |
| `netfilter=off` | Existing managed firewall ownership; no supplied Tailscale route failure. |
| `secondboot` multiple trigger candidates | systemd skips trigger-status propagation. Cleanup reads its own explicit markers and does not use `MONITOR_*` trigger variables. |
| Labwc missing global Xwayland | Expected under the required private Zoom/Discord Xwayland design. No Xwayland policy change. |
| Older Waypaper monitor fallback | The same records show successful wallpaper selection, save and swaybg startup on `All`; not a failed launch. |
| USB-C UCSI error 88 / `UCSI_GET_PDOS failed (-5)` | Firmware/driver failure remains unresolved. The logs alone do not establish a safe installer repair or whether charging/display negotiation is affected. No module or kernel workaround was guessed. |
| Failed audit execs under `/usr/local/bin` | Normal PATH search misses followed immediately by successful `/usr/bin/bwrap` or `/usr/bin/vdirsyncer` execs. |
| Other failed audit syscalls | Missing-file cleanup (`rm`, ENOENT), plus the two AppArmor incidents above. |
| Other managed logs, including empty scanner logs | No additional concrete application failure found. Empty files are not proof that a scanner completed. |

## Verification boundary

Read `AGENTS.override.md`, `docs/test-isolation.md`, `tools/isolation.py`, the
Makefile, `tools/build.py` and `tools/publication.py` before choosing execution.
No approved disposable VM/image was provided. No test, validation runner,
native AppArmor parser or GUI browser was executed. No policy was loaded and
no service, firewall or host state was changed.

Added regression coverage to the existing guarded
`test_apparmor_incidents_20261004.py`: full Tor transition targets, lack of
fallback, reciprocal lifecycle rules, separate browser/transport networking,
and effective owner-only descriptor-directory permissions. These tests still
require execution in the documented disposable environment.

Independent review agents failed to initialize because of an encrypted-context
runtime error; no child review or child test result is claimed.

### Completed static inspection and generation

- Parsed the changed test file, `tools/build.py` and `tools/publication.py` with
  the standard-library AST as data, without importing repository modules.
- Compared all four installed extension-policy JSON files with the canonical
  `browser-config/policies.json`; their extension settings agree.
- `git diff --check` completed without findings.
- Reviewed the pure build's complete execution path and ran only:

  ```sh
  /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/timeout 60 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
  ```

  It completed successfully and serialized 1,781 payload files. No test or
  validator ran as part of generation.
- Compared all 1,781 archive entries (34,221,931 source bytes) against canonical
  source and manifest SHA-256 values. Inventories, safe member paths and
  normalized archive metadata agree. Preseed archive, manifest and bootstrap
  checksum pins match.
- The preceding archive differed from current source in exactly one payload
  member: `hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`. The other payload
  members were already current before this task's generation.
- Compared metadata for 2,261 nonproduct checkout paths immediately before and
  after generation; none changed during the build. Existing source modes were
  preserved; the generated archive and installed policy use mode 0644.
- An initial static archive inspection stopped because it incorrectly required
  every existing source input to have mode 0644. Most pre-existing inputs have
  mode 0600. Repeated the inspection using the builder's actual no-symlink,
  no-executable-input contract and the unchanged-metadata comparison. No broad
  permission rewrite was performed.

| Generated file | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `eff15e1248f55a28ecf3b14e90306f5b5537c8038f51cd545b68171442128e72` |
| `d-i/forky/payload.manifest` | `e8d551e18546de9b1d3a1974c99ee9cb3dcf4634ccbb39dfe53817fe932734fe` |
| `d-i/forky/preseed.cfg` | `f816297a05c997fb56fe4a617685884225de8438e5adfca766966461eea68649` |

Generated artifacts are current. Native policy acceptance, a fresh Tor Browser
launch and circuit bootstrap, browser extension functionality, and shutdown of
both Tor children still require the approved disposable environment. This
review did not deploy or repair an already installed host.
