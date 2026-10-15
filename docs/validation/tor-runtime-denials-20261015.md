# Tor runtime denial and Wayland follow-up, 2026-10-15

> The later user-directed Proton VPN removal and current artifact hashes are
> recorded in the final section. The earlier generation hashes are historical.

## Evidence and scope

Reviewed `todo/tor` (two accessibility warning records), `todo/tor-browser`
(248 lines), the newly supplied audit records, and the preceding journal and
AppArmor investigation. The new journal reaches Tor `Bootstrapped 100% (done)`.
Its earlier microdescriptor and no-consensus notices precede successful
bootstrap; they are not a demonstrated transport failure.

This report supersedes the previous static incorporation conclusion. New
installed-system evidence showed missing permissions after the exec stack
repair, an accessibility bus connection removed by Tor's inner sandbox, and
uninitialized Vivaldi signed search caches.

The work changes installer sources and generated artifacts. No installed host
configuration, policy, service, package, device, networking or browser profile
was read or changed. No software was compiled from source. Existing private
Xwayland integration for Zoom and Discord was not changed.

## Tor AppArmor and desktop corrections

| Supplied operation | Source correction |
| --- | --- |
| Read the root-owned `/proc/sys/kernel/random/uuid` | Exact read rule in both `tor-bwrap` and its `transport` child. Both components of the exec stack must permit the access. |
| Create a raw route netlink socket | `network netlink raw,` in `transport`, matching the existing parent allowance. No IP raw, IP datagram or packet socket grant was added. |
| Read Glycin configuration | The Tor runtime abstraction permits the packaged `2+/conf.d/` directory and its `.conf` files. The outer and browser profiles both include it. |
| Decode GTK icons through Glycin | The same abstraction permits inherited execution of the two fixed packaged Glycin helpers, `bwrap` and its `true` probe, plus the owner-only temporary input file. Executable names are not unrestricted. |
| Read Tor's icon in Labwc and Crystal Dock | Each profile receives read access to the exact installed `default128.png` path. No broader `/opt` access is added. |

The browser retains its IPv4/IPv6 denies. The transport retains its IPv4/IPv6
datagram denies. The existing exec stacks retain the `no_new_privs` profile.

The ANOM action's `Name` is now `ANOM (temporary state, Safest security)`.
Fuzzel's existing application/action composition therefore includes the
application name once. The base desktop entry remains accelerator-neutral;
the existing launcher synchronizer adds Intel/NVIDIA actions according to the
installed class and hardware availability booleans and preserves ANOM.

## Native Wayland and filtered D-Bus

Compared Tor with Mullvad Browser's managed environment, sandbox construction,
filtered bus lifecycle, graphics mounts and policy includes. Both use the
existing environment builder and render-node mount helper. Tor additionally
has a separate transport worker and an IP-isolated browser worker.

Tor already forced `MOZ_ENABLE_WAYLAND=1` and `GDK_BACKEND=wayland` and removed
`DISPLAY`/`XAUTHORITY`. The X11 text came from GLib's session-bus autolaunch
fallback during Firefox's accessibility proxy initialization. Setting
`NO_AT_BRIDGE=1` alone is insufficient: it was already present, and Firefox's
accessibility preinitialization still creates that proxy.

`sandbox.py` now starts the existing `xdg-dbus-proxy` with `--filter` and no
service allowlist for Tor. The existing desktop bus remains managed by
dbus-broker. No new broker, bus daemon or accessibility service is introduced.
The proxy is checked for readiness and cleaned up using the existing bounded
lifecycle. The outer sandbox binds only the proxy socket as its session bus.

`tor-browser-run` requires that exact private runtime socket and verifies its
type and user ownership. After clearing the inherited bus/display environment,
it passes the filtered address and socket into the browser worker only. The
transport receives neither: its runtime directory is masked with private tmpfs
before its own Tor IPC directory is rebound. The browser still has no IP
network access and receives no X11 socket or display address.

Upstream [xdg-dbus-proxy filtering](https://github.com/flatpak/xdg-dbus-proxy/blob/main/flatpak-proxy.c)
hides names without an allow rule and returns `ServiceUnknown`/`NameHasNoOwner`.
[GLib's proxy initialization](https://gitlab.gnome.org/GNOME/glib/-/blob/main/gio/gdbusproxy.c)
treats those absent-service replies as normal, avoiding bus autolaunch without
granting access to the host accessibility bus. These are source-derived
expectations; the target browser was not executed.

## Graphics warning and remaining verification

Mozilla's [Wayland EGL probe](https://github.com/mozilla-firefox/firefox/blob/main/toolkit/xre/gfxtest/glxtest.cpp)
uses the same `glxtest` helper name for Wayland. That name is not evidence of
an X11 connection. Its DRM lookup first matches the primary card path and can
log `Cannot find DRM device` when only render nodes are visible. It then queries
`EGL_DRM_RENDER_NODE_FILE_EXT` as a fallback. This explains a possible warning
with the repository's existing render-node-only device boundary.

The supplied record does not show the selected renderer or prove that fallback
failed. No card/control device access, fabricated GPU probe result, disabled
probe or forced software rendering was added to remove that warning. Its
disappearance and actual hardware acceleration remain unverified. This warning
is not claimed fixed. A disposable installed-system graphics check is still
required; native Wayland, successful acceleration and absence of that warning
are separate observations.

## Vivaldi signed search cache initialization

Inspected the vendor's prebuilt 8.2.4133.87 package as archive data and the
matching C++ files from the [8.2.4133 source release](https://vivaldi.com/source/).
No package or source code was executed or installed. The vendor factory tries
the regular cache first, logs a missing-file error, then loads embedded defaults
and optionally promotes a verified `.update` file. Its updater and cache reader
both verify ECDSA/SHA-256 signatures.

The native package supplies the key creation identifier `1709752345` used in
the vendor URL template. Added unchanged vendor data from:

- [Search engine data](https://downloads.vivaldi.com/search/1709752345/search_engines.json)
- [Search prompt data](https://downloads.vivaldi.com/search/1709752345/search_engines_prompt.json)

| Source asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `etc/vivaldi/search-engines/search_engines.json.signed` | 56,884 | `246b5ae4d57d635d715d9eb2ee51d7007ad212554f18c047a31e1ec1fbbf1777` |
| `etc/vivaldi/search-engines/search_engines_prompt.json.signed` | 1,213 | `c5dbbd21149371b33ac3834bf07c2b55317ab28294d2498dcf93582cff8b1b05` |

The signature lines, comments and JSON bytes are preserved. The `.signed`
source suffix keeps these vendor files distinct from plain JSON policy inputs.
The engine data version is `10000175`; the prompt requires `10000174` and
includes the required `kType`. Signature encoding and byte parity were inspected;
cryptographic acceptance is left to Vivaldi's unchanged native verifier and was
not executed here.

Existing asset staging installs both public files under `/etc/vivaldi` as
root-owned mode 0644, and the installer verifier checks their presence and mode.
The launcher validates their root ownership before entering either sandbox;
both sandbox modes already bind `/etc/vivaldi` read-only. Existing AppArmor
rules permit those reads and private Vivaldi cache publication.

The existing `labwc-proxy-session` initializes only absent cache files before
starting Vivaldi. It checks the destination directory and existing cache types,
ownership and modes; reads the immutable source with the existing no-follow,
bounded reader; and publishes private mode-0600 temporary copies with an atomic
no-replace hard link. Concurrent cache creation is preserved and temporary
copies are removed on failure. Existing browser-owned cache updates are not
overwritten. This happens inside both persistent and disposable sandboxes, so
temporary sessions do not write to the host browser profile. No launch-time
download, signature bypass or unsigned replacement is added.

The Vivaldi-only Proton VPN ID remains in the canonical generator input and
installed policy, with `installation_mode: removed` as directed in the follow-up
below. The three existing privacy extension policies are preserved. NoScript's
separate inaccessible favicon
message remains an upstream signed-extension resource issue; no extension
manifest or browser resource-access protection was changed.

## Verification boundary and results

`AGENTS.override.md` prohibits host test/validator execution. No prepared
disposable environment was available. No tests, native AppArmor parser, browser,
installed helper or service manager were run. Added regression cases remain
unexecuted: stacked file permissions, route netlink scope, GPU action filtering,
ANOM labels, filtered bus lifecycle across all four Tor modes, and Vivaldi cache
creation, update preservation, unsafe paths, publication races and failure
cleanup. Agent initialization failed; no independent child review is claimed.

Source inspection uses standard-library AST, JSON, text and archive reads;
repository modules are not imported or executed. An initial ad hoc permissions
inspection stopped on an overbroad cross-line regex assertion. It was replaced
with line-scoped inspection, which completed successfully. No native validation
was interrupted.

Current static inspection and generation results are recorded below.

### Completed static inspection

- Parsed 12 Python source/test/build inputs with standard-library AST only.
- Compared all 20 generated browser policy files byte-for-byte with the
  canonical JSON and Vivaldi-only extension merge; duplicate keys are rejected.
- Compared both signed data assets byte-for-byte with the downloaded vendor
  files and their recorded hashes. Checked signature encoding, asset staging
  and both readable/mode verification references.
- Inspected the empty Tor bus allowlist, validation before use, transport
  environment copy before browser-only bus assignment, runtime masking and
  browser socket bind ordering.
- Inspected exact AppArmor grants in both stack components, preserved network
  denies, image-helper execution, desktop icon grants and the neutral ANOM
  launcher. This is not native policy parser/kernel acceptance.
- Restored the 14 existing owned source/test/report inputs' original modes.
- `git --no-pager diff --check --no-ext-diff` completed without findings.

### Generated installer artifacts

After reviewing the Makefile and the complete `tools/build.py` /
`tools/publication.py` execution path, ran the permitted pure serializer:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/timeout 60 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
```

It exited 0 and built 1,783 payload files. No test, validator, browser generator,
shell snippet or host management helper ran within this build. Compared 2,975
nonproduct paths before and after serialization: only the product parent
directory metadata changed from atomic publication.

Standard-library archive inspection compared every member's bytes and SHA-256
with source and manifest: all 1,783 files and 34,286,197 source bytes agree.
Member inventories, safe relative names, regular-file types, normalized
metadata and preseed archive/manifest/bootstrap checksum pins also agree.

| Generated file | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `d8a49a4d2da5723b4ef84759b6a3493a9a8881bb3f0b54b6b420f1f91a2eb7f1` |
| `d-i/forky/payload.manifest` | `04133130a57fd8cecd5d325d8210e1c8566ecfeaf53dd88a51e80c67b19cb146` |
| `d-i/forky/preseed.cfg` | `a412f6a26aa290131560f4665ab94c4b7c1c432895d91579974700c80e5b7337` |

These artifacts contain the current implementation. No live claim is made for
Tor window startup, accessibility warning disappearance, image decoding,
hardware acceleration, browser extension downloads, vendor cache signature
acceptance or process cleanup. They still require execution in a prepared
disposable installed system. The supplied journal's successful Tor bootstrap is
user-provided evidence, not an execution performed during this work.

## User-directed follow-up: remove Proton VPN

Set Proton VPN ID `jplgfhpmjnbigmhklmmbgecoobifkmpa` to the exact entry
`{"installation_mode": "removed"}` in `browser-config/policies.json` and
`hooks/target/etc/vivaldi/policies/managed/extensions.json`. Removed its install
URL and toolbar pin. The generator now accepts only that removal entry in the
Vivaldi-specific section. Its existing Vivaldi-only merge and installer
staging/verification paths remain wired. The three shared privacy extensions
retain their previous installation policies; other browser policy outputs do
not gain a Proton VPN entry.

Updated the two existing regression consumers for removal, Vivaldi-only scope,
and rejection of installation modes or extra fields inconsistent with removal.
These tests were not run: the mandatory disposable environment is unavailable.
No host browser, policy, service or package was read or changed. A sidecar review
agent failed to initialize; no child review result is claimed.

Completed source-as-data AST inspection of the three changed Python inputs,
strict generator-guard inspection, canonical/generated byte comparisons for all
20 policy files and three profile seeds, and existing target staging and
readable/mode verification inspection. The browser generator was not executed.
`git --no-pager diff --check --no-ext-diff` completed without findings.

Ran the permitted pure serializer using the same bounded, empty-environment
`make build` command recorded above. It exited 0 and built 1,783 files. Compared
2,975 nonproduct paths across generation: only the product parent directory's
metadata changed. Standard-library archive inspection confirmed every member
against source and manifest, including the exact packaged Proton removal entry:
1,783 files and 34,286,078 source bytes agree. Safe names, regular-file types,
normalized metadata and all preseed checksum pins also agree.

| Current generated file | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `2ebc08c6478e2fc82536c870237d44a031b277ca2d21872ef46f88491c576336` |
| `d-i/forky/payload.manifest` | `3721559c271a0ca4ec846c82f1d97a5dc16cf2cb09af9de7deb536cc930b85f2` |
| `d-i/forky/preseed.cfg` | `536d77c45db3f62b748429c5c9648416192ddb52abaa8670b63f7c67abd4a92e` |

The generated installer payload now carries the removal policy. Applying it in
Vivaldi and observing removal remain unverified runtime behavior; this follow-up
does not deploy policy to the installed machine.
