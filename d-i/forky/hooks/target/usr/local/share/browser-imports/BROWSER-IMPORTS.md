# Browser privacy imports - 2026-09-06

These files are configuration starting points, not a claim that every website,
login flow, video, payment, CAPTCHA or download has been exercised. Keep your old
exports before importing. Import through each extension's own settings page;
do not edit its LevelDB, browser Preferences or managed storage database.

## Import into the regular Vivaldi profile

1. Open `vivaldi://extensions`. NoScript, uBlock Origin Lite and Privacy Badger
   are installed as `normal_installed`: you can disable them and change settings.
   Open each extension's Details / Extension options, or use its toolbar menu.
2. In **uBlock Origin Lite**, open the dashboard, then its backup/restore import
   control and select `my-ubol-settings.json`. Grant the requested HTTP(S) site
   access for Optimal mode; enterprise policy does not silently grant it.
3. In **NoScript**, open Options / Import and select `noscript_data.txt`.
4. In **Privacy Badger**, export a backup first. For a reproducible clean start,
   use a new extension profile or its reset-data control before importing
   `PrivacyBadger_user_data-9_6_2026_1_50_43_PM.json` through Manage Data.
   **Privacy Badger merges imported state. Empty exception arrays do not erase
   old exceptions or user slider actions.** Check Disabled Sites and tracker
   overrides after import. Resetting intentionally discards prior learned data.

After importing, re-export once and compare the effective settings. Browser
builds and extension schemas can change. Do not assume that JSON syntax alone
proves a GUI import succeeded. The supplied exports target the uploaded NoScript
13.6.20 and uBOL 2026.901.1442 formats and the inspected Privacy Badger schema.

## What is covered

`bookmark-coverage.json` accounts for all 691 bookmark entries: 543 eligible web
entries, 338 distinct web origins, 100 entries beneath Entertainment/Imported,
and 48 other browser-internal or non-web entries. Folder exclusion includes all
nested descendants. A host bookmarked both inside and outside an excluded folder
is configured because of the eligible occurrence. Excluded entries are not
exempted from the global blockers; they simply receive no bookmark-derived grants.

All eligible web origins use uBOL's global Optimal mode and enabled Privacy Badger,
without a bookmark-based filtering bypass. NoScript grants app capabilities to
exact first-party origins only in their own top-level context, plus a small,
explicit set of contextual CDN/login candidates. These candidates were reviewed
but **not observed in live network traces**. Inspect their entries before relaxing
anything further. Internal `chrome://` and extension pages are not DNS sites and
must not be inserted in a web-host allowlist.

NoScript retains script blocking for other contexts. No blanket TRUSTED Google,
Microsoft or generic CDN domains are added. Object, ping, LAN and unchecked CSS
are not granted. The app baseline permits scripts, fetches, fonts, frames and
ordinary rendering; only selected media/graphics origins receive media/WebGL/Wasm.
This is a practical initial profile, not empirically established minimum access.

uBOL retains its six upstream default rulesets, adding URL-tracker removal,
Block LAN, Swedish filters, cookie notices and notification annoyances. It uses
Optimal instead of Complete to reduce generic cosmetic filtering work/breakage.
Complete remains user-selectable. All regional, experimental and aggressive
annoyance lists are deliberately NOT enabled together. Cookie-banner filtering
can hide a required consent flow: adjust that list or that site when observed.

Privacy Badger keeps upstream pre-trained protection enabled, turns local learning
off, and adds 29 reviewed explicit tracker blocks from the uploaded data. It does
not copy browsing/snitch/fingerprinting history or invent tracker observations.
It does not globally allow bookmarked sites when embedded as third parties.

## No DNT and permission defaults

Privacy Badger's `sendDNTSignal` and `checkForDNTPolicy` are false. Upstream uses
`sendDNTSignal` for BOTH DNT and GPC, so both signals are disabled by that setting.
Per-domain `dnt` metadata is not itself a request-header setting. The initial
browser profile has `enable_do_not_track=false`; Edge also gets its supported
`ConfigureDoNotTrack=false` policy. There is no invented Chrome `EnableDoNotTrack`
policy. Existing browser profiles are not rewritten; check their privacy toggle.
Disabling these signals is not a promise that the browser cannot be fingerprinted.

Policy only uses supported recommended keys. Per-site notification, sensor and
popup initial preferences remain user-changeable; file, clipboard, geolocation,
USB/HID/serial access remains prompt-based rather than broadly allowed or denied.
Sandboxing, TLS certificate verification and malware/download protections are not
turned off to make a website work. Edge keeps its native SmartScreen defaults;
Chrome-only Safe Browsing enterprise keys are not copied into Edge policies.

## Resolving a site that still breaks

Use the NoScript popup to inspect the blocked origin and required capability.
Temporarily allow only that resource in the current top-level site's context,
reload, and test the actual login or task. Persist only necessary grants. Check
uBOL and Privacy Badger one at a time to identify a second blocker; never solve
this by globally trusting Google, Cloudflare, all CDNs or every bookmark.

A local router such as `www.asusrouter.com` may require local-network permission
and a valid certificate. Block LAN is intentional; local administration needs a
reviewed narrow exception. Do not globally disable TLS validation or LAN blocking.
An HTML bookmark export cannot reveal authenticated resource dependencies.

## Developer tools

Close the browser before testing a changed remote-debugging policy. Use the
installed helper as your regular desktop account, not with sudo:

    browser-devtools vivaldi --port 9222
    browser-devtools chromium --port 9223
    browser-devtools edge --port 9224
    browser-devtools chrome --port 9225

Each command opens a dedicated profile under `~/.local/state/browser-devtools/`,
NOT the everyday profile. It listens on loopback and is opt-in, not a systemd
service. The debugging endpoint grants extensive control without authentication:
never expose it to the LAN, forward it publicly, or attach to untrusted tooling.
For a remote trusted machine, use an authenticated SSH tunnel to loopback.
Close the debug browser when finished. Profiles do not inherit manually imported
extension settings from your everyday browser; import separately when needed.

Check `vivaldi://policy`, `chrome://policy`, or `edge://policy`: expected values
are DeveloperToolsAvailability=1, RemoteDebuggingAllowed=true and
ExtensionDeveloperModeSettings=0. Other management sources may still override
local files. Review conflicts rather than deleting unrelated organizational policy.

## The other reported Vivaldi errors

A failing `VivaldiDirectMatchIcons/372.svg` decode is not the DevTools policy
error. These policies do not fix the SVG decoder. With Vivaldi fully stopped,
back up and rename the `VivaldiDirectMatchIcons` cache directory in the affected
profile so the browser can regenerate it. Do not delete the profile. A recurring
error needs a vendor bug report with browser version and the problematic icon.

The old policy that forcibly removed Proton VPN extension
`jplgfhpmjnbigmhklmmbgecoobifkmpa` is gone. A persisted Vivaldi panel, shortcut or
extension reference can still point to a missing extension. Remove that stale
reference through the UI, or deliberately reinstall the trusted extension.
The installer does not silently install a VPN or fabricate an extension ID.

## Publication and safe re-runs

`install-browser-imports --user NAME` runs as root inside the installed target,
uses the account database for its home directory, and writes user-owned mode-0600
files in Downloads. Re-running does not overwrite user edits; a different payload
is published as `.install-update`, or fails without replacing either edited copy.
Symlinks, FIFOs and unexpected ownership are rejected. No script automatically
imports extension state or launches a browser as root.

These exports and the coverage report reveal personal bookmarks. Keep the build
and installation server private; serve only to authorized installation clients.
