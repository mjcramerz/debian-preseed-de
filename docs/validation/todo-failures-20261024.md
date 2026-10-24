# Todo log failures and source corrections — 2026-10-24

The later [startup/shutdown follow-up](startup-shutdown-followup-20261024.md)
adds source changes for the quoted PAM, dispatcher and IPv6 bind messages.
It supersedes those dispositions below and records the newer payload hashes;
the checks and hashes in this report describe its original snapshot.

## Scope and evidence

Read all 43 regular files under `todo/`, including the hidden historical
`todo/.~`: 16 nonempty files, 27 empty files, 3,372,200 bytes. The current
snapshot is principally LPL-715 on October 24; the hidden backup is LPL-584
on October 13. Logs were treated as data, with no logged commands executed.
The aggregate SHA-256, sorted as `path + NUL + bytes + NUL`, is
`ad511d21f32a166c130ff127d98de18208363bc2d35bc13bc2d98c008096200b`.

The user explicitly excluded Xwayland. No Xwayland implementation, private
compatibility configuration, policy or eligibility change was made in this
task. Earlier uncommitted fixes were preserved. CrowdSec Console enrollment
remains manual. No host service, package, security policy, credential, device
or firmware operation was performed.

## Corrected source causes

### AppArmor mode application races secondboot cleanup

`todo/journalctl:2306` reports `/etc/apparmor.d/firstboot` disappearing during
mode application. Lines 2360–2367 record `apparmor-modes.service` exiting with
status 2 and the dependent hardware tuning units failing. Cleanup was running
concurrently and removed the file without the mode writer's lock. The same
boot's later manual mode application skips the absent optional file and
succeeds (`todo/managed/security/apparmor/modes.log:2`, 81–82).

- `d-i/forky/hooks/target/usr/local/libexec/apparmor-modes-run` now accepts one
  private root-only operation, `--retire-firstboot`. It uses the existing
  `Managed::PolicyLock` inode, validates root-controlled ancestry and the fixed
  regular single-link source, removes only `/etc/apparmor.d/firstboot`, and
  synchronizes the parent directory. Absence is idempotent. It neither unloads
  live policy nor accepts a caller-selected path. A busy writer returns 75.
- `d-i/forky/scripts/firstboot/assets/var/lib/firstboot/bin/secondboot-cleanup`
  calls that operation before removing itself and its retry units. Busy state
  preserves retry infrastructure and uses the unit's existing successful
  status-75 restart path. Other failures retain cleanup artifacts and fail.
  The existing bootstrap-process exit and completion-marker checks remain.
  Console targets do not install managed modes or this helper; their original
  cleanup path is preserved. An explicit fixture root never calls the real
  management helper or reads the host's managed-mode configuration.
- `d-i/forky/scripts/firstboot/assets/etc/apparmor.d/firstboot.tmpl` permits the
  secondboot profile's mandatory transition to `apparmor-modes`. That profile
  now has three unique named executable targets; `labwc-app` is unchanged.

An `After=secondboot.service` change to mode application would conflict with
firstboot's existing ordering after mode application. The shared ownership
lock addresses the file race without adding that ordering cycle.

### Calendar cancellation incorrectly marks a menu service failed

`todo/journalctl:1456` starts `labwc-calendar-actions tasks-all`; lines
1494–1496 record its status 2 after the dialog closes. The controller's source
returns 2 exclusively for its `cancelled` result. Real failure, unavailable
and outcome-unknown results retain their distinct nonzero statuses.

- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl` adds
  `--property=SuccessExitStatus=2` to the eighteen calendar action service
  commands across both layouts. Calix and Agenda launch commands receive no
  such exception. The clock still uses left-click for its menu and button 3
  for format switching.
- `d-i/forky/hooks/target/usr/local/libexec/labwc-calendar-actions` emits a
  structured `status=cancelled` line while retaining exit 2 for CLI consumers.
  No real error is mapped to success.

### Hover helper raises during accessibility-bus shutdown

`todo/journalctl:1623–1630` identifies `listener.deregister()` raising
`GLib.GError: atspi_error: Connection is closed` during session shutdown.
Lines 1653–1654 mark the helper failed.

`d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-hover` now catches the
cleanup-time `GLib.Error` and always calls `Atspi.exit()` in the nested
`finally`. This changes teardown only; event filtering, process identity,
popup deadlines and startup errors retain their existing behavior.

## Remaining log catalogue

| Evidence | Finding and disposition |
| --- | --- |
| `todo/managed/system/usb/usb.log:56–59` | Actual unresolved USB-C/ACPI controller reports: `unknown error 88`, `UCSI_GET_PDOS failed (-5)`. Logs identify Lenovo 82HS, BIOS FXCN49WW dated 2024-09-05 and kernel 7.2.12-x64v3-xanmod1. They do not establish a safe installer correction or distinguish a kernel defect from controller/firmware behavior. No controller disablement, warning suppression or firmware flash was substituted for diagnosis. |
| `todo/journalctl:1356`, 2187–2190 | Thermal interlock refusal; the snapshot also records CPU/package temperatures of 92–93°C. Preserve thermal protection. The broker's existing fault path restores owned controls and returns CPU-policy ownership; the later PPD starts are logged. Physical temperatures were not changed or verified here. |
| `todo/journalctl:1323`, 1366–1367 | A client requests PPD while it is masked for custom tuning ownership; PPD subsequently starts successfully. Existing ownership exclusion and handback are intentional. No unmasking that could create competing owners was added. |
| `todo/journalctl:2180`, 2226 | XFS healer units report changed-unit warnings while secondboot reloads the manager. Both healer services start and log their autofsck policy. This is not a failed healer or evidence of filesystem damage. |
| `todo/journalctl:1738`, 1774 | Shutdown-time PAM session release after removal and NetworkManager dispatcher's STOPPING notification after the receiver closes. No repository-owned failed startup is established by these teardown notices. |
| `todo/journalctl:2788` | Tailscale explicitly reports its peerAPI IPv6 listen failure as harmless because netstack is available. Current enrollment responses report `machineAuthorized=true`; transient warming-up warnings clear. |
| `todo/.~:1511–1563` | Historical October 13 Tailscale bootstrap timeout follows `machineAuthorized=false`. Current October 24 registration succeeds; the older machine's authorization is not evidence of a current installer failure. |
| `todo/.~:1434` | Historical Waypaper monitor enumeration falls back to All. No corresponding current capture failure or failed wallpaper unit is present. No new live GUI acceptance is claimed. |
| `todo/managed/security/crowdsec/crowdsec.log:3`, 10 | Console enrollment is intentionally manual, as requested by the user. Local API and bouncer start, and the bouncer adds 14,995 decisions. |
| Same log, 35–36, 89, 94 | Duplicate upstream grok registrations are warnings; all parsers/scenarios load. The qBittorrent log does not yet exist, and file-discovery polling is enabled every 30 seconds. Do not remove the acquisition or security parser to hide these notices. |
| `todo/fail`, Fail2Ban log | The word “fail” matches successful Fail2Ban startup. Configuration succeeds and the sshd jail starts. |
| `todo/managed/security/apparmor/apparmor.log` | All 442 records are STATUS records; no DENIED or complain-mode ALLOWED event appears in this snapshot. The preceding calendar-worker netlink correction remains in the payload. |
| Audit log unsuccessful syscalls | Correlated PATH records identify nonexistent earlier PATH candidates for `sh`, `bwrap`, `systemctl` and `dbus-update-activation-environment`; the log also contains successful executions of their real packaged paths. Cleanup's `rm` returns ENOENT for already absent artifacts, and systemd's directory removal encounters an existing nonempty wants directory. These do not justify creating shadow executables or removing additional directories. The failed SERVICE_START is the AppArmor mode race corrected above. |
| `todo/journalctl:1351` | Launcher synchronization deliberately reports optional Code as absent; no failed Code launch is recorded. No unrelated application installation was added. |
| Netavark, NetworkManager and XFS informational lines | Netavark exits after its stated idle period; initial link unavailable/disconnected transitions precede connectivity; XFS “Only logging errors” states its configured reporting mode. These are not failed services. |
| Kernel log firmware/resource notices | BIOS `_OSI(Linux)` handling, unavailable memory ranges, resource reservations and a dummy regulator are platform reports. No source-owned failed operation was established that could safely be repaired by changing global kernel or device policy. |
| Auth logs | Verified login/session records and the existing quarantine of unverified sudo-origin messages preserve the authentication provenance boundary. No authentication failure is recorded. |
| The 27 empty logs | They contain no failure evidence. Empty security/model/storage logs do not establish that their scheduled operations have run or passed. |
| Xwayland lines | Excluded explicitly by the user; no related change was made. |

## Fixtures and checks

`d-i/forky/tests/test_native_menu_contract_20260920.py` checks that only
calendar action services accept cancellation status 2.
`d-i/forky/tests/test_firstboot_audit_20260926.py` adds focused private-copy
fixtures for writer contention returning 75 without deleting the file,
successful retirement after release, stable lock inode, repeated absence,
and symlink/hardlink replacement rejection. All paths in those fixtures are
redirected to their private tree. Neither fixture was executed.

Checks actually completed:

- Read-only log scans, audit-event correlation and source/caller inspection.
- Inline `/usr/bin/python3 -I -S -B -`: `ast.parse` on two changed Python
  helpers and two fixtures; `shlex` data tokenization of the cleanup shell;
  JSON parsing of the Waybar template after neutral installer-token
  substitution. No repository module was imported. The Perl action and
  AppArmor rules were inspected as source data, not natively parsed.
- The source inspection confirms lock acquisition before unlink and durable
  parent synchronization, preservation of process-exit checks and retry
  artifacts, the desktop/console/fixture branch, the mandatory transition,
  eighteen cancellation-aware menu services and right-click-only format
  switching.
- `git diff --check`: completed without errors.
- Reviewed pure `make build PYTHON=/usr/bin/python3`: completed, 1,830 members.
- Separate bounded standard-library archive/hash comparison: all 1,830
  members match current source bytes and manifest digests; 34,865,656 expanded
  bytes. Preseed archive, manifest and bootstrap-source pins match. Private
  input names are absent.

The eight production/fixture paths listed in the corrected-causes and fixture
sections, sorted as `path + NUL + bytes + NUL`, have fingerprint
`20fc4543bca9bfad2cc409e9917c9ca2fa7662609865e3151aa3b53ef6bce40f`.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `8b4134fcf88f3934539a9abb568568d07665826b39a7b49d98456f63135750e4` |
| `d-i/forky/payload.manifest` | `203f191930922f3d8ac7109165b44f6cc8870e62d43cbc75c893e561010aa15c` |
| `d-i/forky/preseed.cfg` | `164dcfec300090982027f114842067bee64d7ba06152497ef011d10e662c7b34` |

No test runner, native Perl/shell/AppArmor parser, installed management helper,
live target operation or deployment was run. Requested read-only sidecars
could not initialize because of encrypted-content hydration; no independent
review is claimed. The named `debian-preseed-de-audit.md` is absent in this
checkout; historical reports are not used as current acceptance evidence.
The declared target remains Debian Forky/systemd 262; no installed host or
target package state was queried. Root offline inventories remain separate,
stale generation products. Fresh boot, live GTK teardown and policy-load
acceptance remain unverified. The USB-C/controller errors and physical thermal
condition are not claimed resolved by these source fixes.
