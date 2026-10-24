# Calendar firstboot and recorded-log source fixes — 2026-10-23

## Scope and evidence

This report supersedes the lifecycle description in
`agenda-fruux-tor-20261023.md`. It records source inspection and pure payload
generation for new Debian Forky installations. No test suite, fixture execution,
policy parser, native application, keyring operation, remote Fruux request or
host management command was run. No software was compiled or deployed.
CrowdSec Console approval remains an intentional manual operation. The private
Xwayland eligibility and implementation remain unchanged.

Base revision: `5926f21a0ac7c8ef331cc4011c3e7fc06c01cffa`.

Changed `d-i/forky/` source fingerprint, excluding the three generated products:
`baa57c346e30278afeb6e1401a33b51fdae0787f59cbc047a768596e9b4edd40`
(39 paths). The digest covers sorted path, NUL, current file bytes or
`<deleted>`, NUL. Documentation is outside that fingerprint. The saved target
snapshot records systemd 262; the existing installation boundary requires
systemd 262 and Python 3.14. These target checks were not executed here.

## Installation failure correction

The target installation subsequently rejected `labwc-app` with
`has too many specified profile transitions`. The previous change added two
named executable transitions, increasing the parent profile from 11 unique
named executable targets to 13. Earlier source/data inspection missed this
compiler limit and did not establish that the installed policy compiled.

The correction uses ordinary mandatory `rpx` rules for Agenda and Calix. Their
existing exact executable attachments in `calendars` select the same confined
profiles. Neither rule gains an inherit or unconfined fallback, and lowercase
`px` preserves the existing managed environment behavior. The parent's unique
named executable targets are back to the original 11. The existing policy
fixture expectations were updated for both calendar executables but not run.
This is source evidence; the target AppArmor parser and a new installation
were not executed during the correction. See Debian's
[directed-transition documentation](https://manpages.debian.org/unstable/apparmor/apparmor.d.5.en.html#Directed_profile_transitions).

## Implemented lifecycle

| Stage | Source contract |
| --- | --- |
| Installation | Existing private Fruux inputs produce user-owned mode-0600 bootstrap and non-secret identity files in the mode-0700 Calix configuration directory. Passwords are not command arguments or environment variables. |
| Firstboot, before greetd | `fruux-firstboot.service` runs `calix-fruux-bootstrap --provision` as the desktop account. It commits the pinned Calix account schema and publishes the synchronized `account-provisioned` receipt. This mode returns before importing Secret Service and needs no network, bus, display or keyring. |
| First desktop login | The session automatically starts `labwc-calendar-credentials.service` after KWallet readiness. `--install-secret` validates the saved account read-only, stores and reads back Calix's exact Secret Service credential, publishes `credentials-ready`, then unlinks and synchronizes the temporary password input. |
| Setup failure or interruption | Failed provisioning publishes no completion receipt and is eligible on the next boot. Credential delivery uses bounded automatic service retries and runs on subsequent logins. Plaintext still present always prevents cleanup, including interruption after keyring storage or receipt publication. Existing different keyring entries are not overwritten. |
| Later boots/logins | The receipt suppresses repeated firstboot provisioning. With the password input gone, the login helper checks non-secret completion and returns without opening Secret Service. Calix and the clock actions use the saved native account and existing keyring entry. |
| Secondboot cleanup | The existing cleanup waits for all bootstrap processes to exit. Its rendered root-owned Fruux delegate drops root and supplementary groups before checking the desktop receipt and password absence under the same owner lock. Cleanup removes the firstboot unit/enablement link, greetd ordering drop-in and temporary cleanup delegate. Incomplete delivery retains the existing retry infrastructure. |

Permanent state consists of the native SQLite database, non-secret account
identity/completion receipt and stable lock, plus the installed runtime
credential service/helper. Cleanup never removes the native account or its
keyring entry. The runtime service/helper remain installed so credential
readiness has a stable session dependency; subsequent successful sessions do
not repeat setup or keyring delivery. Calix has no dependency on the removed
system firstboot unit.

All three phases use `.fruux-bootstrap.lock`; cleanup does not unlink that lock.
SQLite commits, directory creation, receipt publication and password removal
have explicit synchronization boundaries. Failure retains private input when
present. greetd is ordered after the provisioning attempt through `Wants` and
`After`; a provisioning failure does not lock the user out of the entire desktop.

## Native launches and clock operations

- Agenda and Calix are managed application entries using transient
  `labwc-native-agenda-*.service` and `labwc-native-calix-*.service` units.
- `labwc-agenda` and `labwc-calendar` are installed symlink aliases to the
  existing managed launcher. The small shell launchers and fixed app services
  have been removed from the payload.
- Both Waybar layouts open the GTK dropdown on left click and use
  `{:%a, %d %b %Y W%V - %H.%M}` for the alternate clock format.
- Events and Tasks read the permanent Fruux username from
  `.config/calix/fruux-account.json` and the same Calix Secret Service entry:
  service `com.ianswope.Calix`, username
  `caldav-password:https://dav.fruux.com|<lowercase-username>`.
- The existing CalDAV worker discovers the principal/home/collections from
  `https://dav.fruux.com`, selects `VEVENT` or `VTODO` support and validates
  privileges. Private resource IDs are not hardcoded.
- Creates send conditional `PUT` requests with `If-None-Match: *`; edits,
  completion and deletion bind UID/resource/strong ETag and use `If-Match`.
  Uncertain writes retain the existing durable intent and are not replayed.
- Opening an application or clock action does not provision an account or
  trigger credential delivery. The clock action's five-second service check
  is read-only. Remote actions remain available after firstboot cleanup.
- The existing installation verification boundary now checks the alias/code
  authority, rendered Fruux boot assets and packaged GTK/Secret/GLibUnix,
  icalendar and defusedxml interfaces before activation.

## Recorded failures and remaining warnings

| Saved evidence | Source action or conclusion |
| --- | --- |
| Agenda abort while executing glycin's Bubblewrap decoder; secondary activation reports NoReply | Add a confined Agenda glycin child and the required decoder/icon/cache access. Launch through the existing managed native path. The decoder crash is observed; its relationship to the reported NoReply is an inference. |
| Calix and calendar worker UDP socket denials preceding discovery transport errors | Allow IPv4/IPv6 datagram sockets needed by DNS in the two affected profiles. Existing HTTPS access remains. |
| Calendar dialog glycin temporary-file denial | Allow its owner-only pixbuf temporary files and transition to the existing session glycin child with reciprocal termination signals. |
| Editor glycin inherited `l3afpad.png` descriptor denied | Allow that exact packaged image in the editor child. |
| Crystal Dock cannot resolve `labwc-calendar-actions` desktop identity | Install the hidden desktop entry matching that identity. |
| Deprecated `GLib.unix_signal_add` | Use `GLibUnix.signal_add`. |
| Native audit files rotate at 2 MiB | Change the shared audit size to 20 MiB; retain auditd as the only native audit-file rotator and the existing four-file retention. |
| rsyslog 8.2608 `poll_tree cannot stat ... auditd.log` | The snapshot includes a live `auditd.log` and rotated predecessors. The warning is consistent with auditd's rename/recreate window in the upstream imfile implementation. Inotify following remains enabled. The larger native file reduces rotation frequency; it does **not** eliminate the upstream diagnostic. No ineffective `MissingFileError` setting, second rotator or full audit-to-journal forwarding was added. |
| Intel thermal interlock refusal | The engine explicitly refuses profile application at the configured temperature threshold. Preserve that protection; the snapshot does not justify changing thermal limits or writing hardware controls. |
| ACPI/UCSI, HPET, TDX, controller/firmware notices and overlayfs fallback | These are target/kernel capabilities or fallbacks, with no demonstrated repository correction. No speculative driver/firmware/storage policy change was made. |
| ARP/martian messages on Ethernet/Wi-Fi and a Tailscale source | The saved packet headers show ARP traffic, and source policy already uses loose reverse-path filtering. The snapshot does not establish the peer/address or packet-path cause. No addressing or source-validation weakening was applied. |
| Fresh Bluetooth identity absent; Tailscale stopped/warming messages followed by healthy status | Retain native initialization and startup behavior. |
| CrowdSec Console enrollment error | Explicitly excluded by the user: Console approval is manual. Optional external qBittorrent log absence and vendor grok redefinition warnings also do not justify changing Console enrollment. |

The upstream imfile source inspected for the race is
[rsyslog v8.2608.0 imfile.c](https://github.com/rsyslog/rsyslog/blob/v8.2608.0/plugins/imfile/imfile.c).
The saved logs establish the original failures, not success of the changed
AppArmor profiles or live GTK/keyring/CalDAV behavior.

## Checks performed

1. `git diff --check`: passed.
2. Ad hoc `/usr/bin/python3 -I -S -B -` data parsing: 13 changed Python
   files/templates and seven embedded Python blocks parsed with `ast.parse`.
   Repository modules were neither imported nor executed.
3. JSON/XML/argument data comparison: both clock layouts matched all 11 GTK
   menu leaves and their exact delegates. Installer/theme tokens used numeric
   parser stand-ins; this did not execute the renderer or prove rendered GTK
   behavior. The first comparison used guessed expected menu IDs and failed
   that assertion; correcting the expected IDs against the actual XML produced
   the successful comparison above.
4. Reviewed pure generation command `make build PYTHON=/usr/bin/python3`:
   completed twice, reporting 1,829 payload files on each invocation; the final
   generation includes the directory-synchronization recovery correction.
   An additional successful rebuild incorporates the named-transition correction
   above. No generation invoked a test/validation runner.
5. Ad hoc standard-library archive inspection: every archive member matched
   its manifest SHA-256 and current checkout bytes; member metadata matched
   serialization policy; generated preseed pins matched archive/manifest hashes.
   The archive contains no `preseed.env` member.

| Generated product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `0db7d051bfb22b4267ec7555d3a47e826a7807e9b9f34d608742dc0c5b988e55` |
| `d-i/forky/payload.manifest` | `8fc99330af1b6436f73c2735b7c9d884a6f03453b8dee2c468e76a5f9726b89a` |
| `d-i/forky/preseed.cfg` | `d25349922e9a3ab0103a458fdc142092777717e94498b2c0cc8ec90010e5f47c` |

`inventory.json` and `inventory-apt.json` were not regenerated and do not contain
the new payload hash. Fixtures were updated only for retired/replaced contracts;
none were run. Native boot, login/keyring handoff, secondboot cleanup, AppArmor
enforcement, GUI launches and remote writes remain unexecuted deployment gates.

## Exact changed paths

Under `d-i/forky/hooks/target/`:

```text
etc/apparmor.d/calendars
etc/apparmor.d/desktop-utilities
etc/apparmor.d/desktop-wrappers.tmpl
etc/apparmor.d/labwc-session
etc/rsyslog.d/30-apparmor.conf.tmpl
etc/skel-desktop/.config/systemd/user/labwc-agenda.service (deleted)
etc/skel-desktop/.config/systemd/user/labwc-calix.service (deleted)
etc/skel-desktop/.config/systemd/user/labwc-calendar-credentials.service (new)
etc/skel-desktop/.config/waybar/config.tmpl
etc/systemd/system/fruux-firstboot.service.tmpl (new)
etc/systemd/system/greetd.service.d/40-fruux-firstboot.conf (new)
usr/local/bin/labwc-agenda (deleted; alias installed by staging)
usr/local/bin/labwc-calendar (deleted; alias installed by staging)
usr/local/bin/labwc-sync-application-launchers.tmpl
usr/local/lib/python3.14/dist-packages/labwc_managed_app/cli.py
usr/local/lib/python3.14/dist-packages/labwc_managed_app/generic.py
usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl
usr/local/lib/python3.14/dist-packages/labwc_managed_app/session.py
usr/local/libexec/calix-fruux-bootstrap
usr/local/libexec/labwc-calendar (deleted)
usr/local/libexec/labwc-calendar-actions
usr/local/libexec/labwc-waycal-hover
usr/local/share/applications/com.github.dahenson.agenda.desktop
usr/local/share/applications/com.ianswope.Calix.desktop
usr/local/share/applications/labwc-calendar-actions.desktop (new)
var/lib/firstboot/bin/fruux-cleanup.tmpl (new)
```

Other paths:

```text
d-i/forky/hosts/logging/observability.env
d-i/forky/scripts/desktop/calendar-install.py
d-i/forky/scripts/desktop/components/services.sh
d-i/forky/scripts/desktop/components/target-assets.sh
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/scripts/firstboot/04-validation.sh.tmpl
d-i/forky/scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl
d-i/forky/scripts/firstboot/assets/etc/systemd/system/secondboot.path
d-i/forky/scripts/firstboot/assets/etc/systemd/system/secondboot.service
d-i/forky/scripts/firstboot/assets/var/lib/firstboot/bin/secondboot-cleanup
d-i/forky/tests/test_desktop_sandbox.py
d-i/forky/tests/test_menu_apparmor_integration_20260919.py
d-i/forky/tests/test_native_menu_contract_20260920.py
d-i/forky/payload.tar.gz
d-i/forky/payload.manifest
d-i/forky/preseed.cfg
docs/calendar-and-wifi.md
docs/validation/calendar-firstboot-20261023.md (new)
```
