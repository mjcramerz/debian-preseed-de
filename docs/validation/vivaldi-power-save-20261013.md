# Vivaldi warnings and desktop power save window — 2026-10-13

## Scope and execution boundary

Reviewed the Vivaldi records in the LPL-223 snapshot under `todo/`, the managed
browser profile, filtered D-Bus proxy, installed AppArmor includes, target asset
staging/account copying, and desktop/greeter power entry points. Preserved the
existing uncommitted changes and the private Xwayland policy.

No test, discovery/import hook, repository validator, native policy parser,
browser, compositor or installed management helper was executed. No host service,
package, D-Bus, firewall, networking, mount or security-policy state was changed.
No software was compiled. The repository's `AGENTS.override.md` permits tests
only in a prepared disposable environment without host access. That environment
was unavailable, so regression fixtures were authored and inspected as data,
then left unexecuted.

## Desktop power contract

The authenticated desktop poweroff/reboot worker invokes the corresponding
`labwc-session-state@poweroff.service` or `@reboot.service` through the authorized
user's manager before it closes applications or stops anything in the desktop.
The existing user unit owns the compositor environment and executes the helper
without root privileges. Its existing AppArmor rules already permit the exact
`wlrctl` and `notify-send` operations used here.

1. A successful empty Wayland toplevel inventory proceeds without a save warning
   or delay. Background services and layer-shell panels do not trigger the grace
   period. The existing `find` fallback covers unidentified toplevels.
2. With open windows, a critical notification gives the user 15 seconds to save.
   All windows remain usable, including terminals running micro, FeatherPad,
   FocusWriter, Gnumeric and browsers. The helper does not close windows, set the
   launch-blocking marker, clear the clipboard, stop units, inspect document
   titles or signal applications during this stage.
3. One monotonic deadline bounds the wait. Window queries use at most one second
   of the remaining deadline. Closing every application window permits an early
   continuation. Saving a document while leaving its window open does not extend
   the deadline. Wayland does not supply a reliable universal dirty-document flag.
4. A failed inventory still allows the bounded grace period. A failed user-helper
   transport gives the remaining part of a conservative 15-second period; the
   manager call is independently bounded at 25 seconds, including startup/probe
   overhead. Neither a helper failure nor a remaining window vetoes shutdown.
5. After this stage, the existing one-time native close request and bounded
   cleanup run. The 45-second cleanup budget starts after the save opportunity.
   The final request remains exactly one `systemctl --force poweroff` or
   `systemctl --force reboot` from the worker's `finally` path. Total shutdown time
   includes cleanup and PID 1's filesystem/process handling; 15 seconds is the
   save opportunity, not a measured total shutdown time.

Greeter requests retain their existing direct bounded cleanup path. Logout keeps
its existing native close/dialog cancellation contract, and suspend keeps its
lock contract. Session capture and restoration were not reintroduced.

## Vivaldi warning contracts

### MPRIS

`todo/journalctl:1539` and `todo/managed/apps/apps.log:175` record a failed request
for `org.mpris.MediaPlayer2.vivaldi.instance6`. The persistent Vivaldi sandbox had
no session-bus OWN permission. It now passes only
`org.mpris.MediaPlayer2.vivaldi.*` to the existing filtered proxy. The existing
reader converts this to its `--own` argument. The suffix covers the base name
and its instance descendants under the proxy's documented matching semantics.
See the [upstream xdg-dbus-proxy policy documentation](https://raw.githubusercontent.com/flatpak/xdg-dbus-proxy/main/xdg-dbus-proxy.xml).

The browser's existing AppArmor desktop/D-Bus includes already cover the native
IPC path. No broader AppArmor or session-bus grant was introduced.

### Search-engine files

`todo/journalctl:1507-1508` records missing `search_engines.json` and
`search_engines_prompt.json` under the user's Vivaldi configuration directory.
Complete native default data is now canonical configuration under:

- `d-i/forky/hooks/target/etc/skel-desktop/.config/vivaldi/search_engines.json`
- `d-i/forky/hooks/target/etc/skel-desktop/.config/vivaldi/search_engines_prompt.json`

Both files have explicit target staging at mode 0600, installed readability/mode
checks, and account-owned readability checks. The existing recursive account
copy already transfers `.config/vivaldi`; the persistent sandbox already binds
that directory, and its existing AppArmor rule permits the cache reads/writes.
No installer or launch-time network fetch is needed to seed these files.

The defaults preserve 98 engine definitions, 54 locale groups and 52 country
associations. Search-data version 10000175 satisfies prompt version 6's minimum
search-data version 10000174. Existing search/privacy policies remain authoritative.

#### Resource provenance

Inspected the public vendor package **8.2.4133.84-1 (amd64)** as archive data only,
using the vendor's [APT package index](https://repo.vivaldi.com/archive/deb/dists/stable/main/binary-amd64/Packages.gz)
and [package archive](https://repo.vivaldi.com/archive/deb/pool/main/vivaldi-stable_8.2.4133.84-1_amd64.deb).
It was 138,324,052 bytes with SHA-256
`df086f893f85776ab68eaf6db991deede134d280fdb2d6c7493fa3ff30c8301e`, matching
the HTTPS index. No package installation, executable invocation or source build
was performed. This data inspection did not independently verify the repository
signature or establish the exact version on LPL-223.

The two native search resources embedded in the packaged browser carry Vivaldi
Technologies AS copyright notices dated 2021 and 2025 respectively. Their JSON
values were retained; line comments were removed with string/escape-aware
parsing and the data was formatted as strict JSON for checked-in configuration.
There are no installer placeholders in these assets; single-brace search URL
tokens are native browser syntax.

| Canonical cache | SHA-256 |
| --- | --- |
| `search_engines.json` | `1a01b18cd937944fffbcd3d4f250107669b45e736d50230f5014c448eaf5cf45` |
| `search_engines_prompt.json` | `691a879567324012258a798ce43fea0b7c3c2310d3b15434e86160521ff28b43` |

### Extension warnings still requiring an upstream repair

- `jplgfhpmjnbigmhklmmbgecoobifkmpa` is Proton VPN's browser extension ID. The
  inspected packaged Vivaldi UI unconditionally calls `management.setEnabled`
  for that ID when its VPN preference is disabled, without first checking for an
  installed extension or catching that promise. Disabling the preference alone
  therefore cannot be claimed to fix the supplied missing-extension warning.
  The packaged UI was not patched, and an unused VPN extension was not installed
  as a workaround. [Proton's published extension identifier](https://github.com/ProtonMail/WebClients/blob/main/packages/shared/lib/constants.ts)
  and [Vivaldi's VPN documentation](https://help.vivaldi.com/desktop/privacy/proton-vpn-for-vivaldi/)
  identify the feature.
- The NoScript warning requests its options-page favicon from Vivaldi's UI.
  NoScript's [options page](https://raw.githubusercontent.com/hackademix/noscript/master/src/ui/options.html)
  identifies that image, while its [manifest](https://raw.githubusercontent.com/hackademix/noscript/master/src/manifest.json)
  does not expose it as a web-accessible resource. The browser's refusal follows
  [Chrome's resource-access rules](https://developer.chrome.com/docs/extensions/reference/manifest/web-accessible-resources).
  AppArmor cannot override this extension boundary. NoScript and its manifest
  restrictions were retained.
- The `EventAck` records for `jffbochibkahlbbmanpmndnhmeliecah` remain unresolved.
  The supplied logs show the browser's extension event-dispatch warning; they do
  not establish a local policy defect or a safe repository fix.

These three warning classes are not claimed fixed. No logging suppression,
signed-extension rewrite, component removal or browser-security downgrade was
used to hide them.

## Changed canonical paths and fixtures

- `d-i/forky/hooks/target/usr/local/libexec/labwc-admin-action-worker`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-session-state.tmpl`
- `d-i/forky/hooks/target/etc/systemd/system/labwc-admin-action@.service.tmpl`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl`
- The two Vivaldi cache files listed above.
- `d-i/forky/scripts/desktop/components/target-assets.sh`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`
- `d-i/forky/tests/test_browser_repository.py`
- `d-i/forky/tests/test_kernel_veth_networking.py`
- `d-i/forky/tests/test_power_force_contract.py`
- `d-i/forky/tests/test_power_keyboard_20260913.py`
- `tools/tests/test_labwc_power_handoff.py`
- This report and the three generated installer products.

## Static inspection and generated output

- Parsed eight changed Python runtime/template/test files using the standard
  library AST as data. No repository module was imported or executed for this
  inspection. Inspected isolation-guard ordering in the changed fixtures.
- Inspected fixed deadline values, lack of destructive calls in the user save
  function, worker stage order/final handoff, exact proxy ownership propagation,
  duplicate-free cache JSON and its staged/copy/mode contracts.
- The initial metadata inspection detected mode 0600 on edited source files.
  Restored mode 0644 on the task's eleven edited existing source files and
  repeated the inspection successfully. Installed cache modes remain 0600.
- Compared canonical source with the preceding generated archive: exactly six
  existing payload members changed and two cache members were added. Every
  other prior member remained byte-identical, including previous network fixes.
- `git diff --check` completed without findings.
- Ran only the permitted pure serialization command:

  ```sh
  /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
  ```

- Compared checkout metadata across that command: exactly `payload.tar.gz`,
  `payload.manifest` and `preseed.cfg` changed. No test, validator, policy parser,
  browser generator or source rewrite was invoked by the build.
- Streamed all 1,756 archive members without extraction or execution and
  compared 34,002,675 source bytes against the canonical checkout and manifest
  SHA-256 values. Inspected normalized archive metadata, private/test exclusions,
  the three changed runtime members' AST, both cache JSON members, and matching
  archive/manifest/bootstrap-source pins in preseed.

| Generated product | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `6dbc2078df97a2c4743d167f0d5b40dcea5cd7531c1dd718b9de7cb6b3b4a018` |
| `payload.manifest` | `75d4074ca88ef2f3ed89ac170a178abc38d988fe9ca8f26b06afdd33ff4f6873` |
| `preseed.cfg` | `594e5efc0eec6bdb9ac2cc397d72b558598a79e91d80c3af8e628d524d19b1cb` |

## Deployment limits

The rebuilt installer contains the scoped changes. It has not been applied to
the supplied installed machine. The new save-window fixtures, installed native
window/notification behavior, actual power handoff, MPRIS registration and cache
acceptance still require the authorized disposable environment. Static inspection
and archive equality do not establish those live outcomes. No measured browser
performance improvement is claimed.
