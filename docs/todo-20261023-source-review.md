# October 23 installer source review

## Scope and execution boundary

This work addresses the supplied `todo/fail`, `todo/failing`, `todo/journalctl`
and `todo/managed/` observations, saved Wi-Fi reconnect, and the requested
Waycal/Calix replacement. The starting revision was
`29f808142c19449f9859ac7bb1286f30c4d4f044` on `mcr/main`; the worktree was clean.
All changes remain uncommitted.

The user explicitly requested **no VM or validation runs**. No tests, fixture
discovery/imports, validation runners, native shell/Perl/AppArmor/systemd
validators, installed helpers, services, managers, reboot, firewall, storage or
package operations were executed on the development host. No real `preseed.env`,
URLhaus key or Fruux login was read or used. The two requested public release
archives were read as bounded data to establish their layout and hashes; neither
binary nor vendor installation script was executed.

Static inspection traced the affected entrypoints, delegates, renderer/staging,
installed paths and policy. Standalone standard-library parsing treats changed
Python and embedded Python source as data; it does not import repository code.
The permitted `make build` command only serializes the three
snapshot products. Serialization is not an installation or runtime acceptance
result. Newly added or updated fixtures remain **unexecuted**.

## Reported issues and source decisions

| Observation | Source change / disposition |
| --- | --- |
| Absent `nfs-server.service` / `nfs-mountd.service` caused stop transaction errors on a client | The power worker queries each optional fixed unit's `LoadState`, skips `not-found`, reports individual probe errors and stops the present units. Server-only, client-only, both and neither roles have explicit fixture cases. |
| Propagated NFS home-view unmount raced the real client and invoked the NFS helper on a bind source | The validated root-owned sharing policy derives a separate real-client stop transaction, followed by the home view and shared root. An earlier uncertain/failed unmount skips parent transactions. No hard NFS paths are statted. |
| Preserve Waybar and gtkgreet forced power actions | Both existing authorized flows retain the PID-1-owned worker and **exactly one** `systemctl --force <poweroff/reboot>` handoff. The common 45-second best-effort cleanup deadline and separate external-drive budget remain. Optional cleanup failures cannot veto that handoff. |
| AppArmor staged mode compilation printed “Failed to create cache” | The offline candidate compiler gets `--config-file=/dev/null` with explicit policy features and its existing `-Q -K -T` flags. This prevents packaged parser `write-cache` configuration leaking into a no-cache staged compile. Production reload/cache behavior and transactional mode recovery remain. |
| Scheduled network-dependent operations ran while offline | A fixed, bounded current DNS/TLS/HTTPS readiness probe guards Lynis, unified ClamAV/Fangfrisch, packaged freshclam, apt daily/upgrade, list/local-repository refresh, ACME renewal and optional hourly Obsidian Git synchronization. The packaged hourly daemon-user debsecan cron contract gains the same guard while retaining its internal daily cadence. Offline service conditions skip without restart loops. |
| Repeated systemd-resolved DNSSEC failures with localhost Stubby | Stubby's configured validation and trust anchor remain the validating resolver boundary; the redundant global resolved validation is disabled for that local hop. VPN per-link policy is not changed. No live DNS claim is made. |
| URLhaus anonymous endpoint returned HTTP 410 | Optional private `PRESEED_URLHAUS_AUTHKEY` controls the explicit authenticated export. Missing/empty disables that provider while official ClamAV and Sanesecurity continue. Private publication, complete-line redaction, bounded capture and distinct cancellation/timeout/unknown statuses protect the key. Logged provider errors cannot be mistaken for a successful update when packaged Fangfrisch exits zero. See [the credential contract](clamav-urlhaus.md). |
| Lynis DEB-0880 expected `jail.local` even with active `jail.d/*.local` policy | Add a minimal local entry file without copying/freezing packaged jails or replacing the existing per-jail policy. |
| Wi-Fi required manual reconnect after every reboot | Remove the pre-start radio reset, persist system-owned autoconnect/empty-permissions configuration, preserve a user's saved SSID, and require saved secrets for pre-login reconnect. Existing static addresses and Ethernet metric 100 / Wi-Fi metric 200 remain. See [the Wi-Fi contract](calendar-and-wifi.md#wi-fi-reconnect-and-ethernet-preference). |
| Replace terminal calendar/task operations | Pin Waycal 0.2.1 and Calix 0.8.0 in all ten profiles; install reviewed archive members with bounded acquisition, use explicit session services/AppArmor, enable Waycal on the clock tooltip event, right-click date/week formatting, and GTK Open calendar → native Calix. Existing private Fruux inputs feed a one-time user keyring/SQLite bootstrap. Old khal/todoman/vdirsyncer configuration, packages and sync timer/actions are removed. See [the calendar contract](calendar-and-wifi.md). |

The current readiness probe intentionally requires an HTTP 200 from
`https://deb.debian.org/debian/` with valid TLS. It proves that fixed path at the
instant of the condition. A vendor can still be unreachable later, and connectivity
can disappear during a job. A failed condition retains each timer's normal next
run; this change does not add an immediate reconnect dispatcher. Interactive
network operations and applications retain their own user-initiated behavior.

The AppArmor parser behavior was reviewed against the
[4.1.8 parser source](https://gitlab.com/apparmor/apparmor/-/blob/v4.1.8/parser/parser_main.c).
The global/local DNS distinction follows the configured Stubby code and the
[systemd 262 resolver contract](https://www.freedesktop.org/software/systemd/man/262/resolved.conf.html).

## Observations without a justified source repair

These are dispositions of the provided evidence, not claims that external events
have disappeared:

| Observation | Remaining external condition / evidence limit |
| --- | --- |
| CrowdSec console reports not enrolled / sharing settings pending | Enrollment requires the configured optional token and remote console approval. The source already preserves the enroll-then-console-enable flow. Console approval was not performed; CAPI was not disabled to hide the message. |
| CrowdSec duplicate IPv4 workaround grok definitions | The inspected upstream SSH parser definitions repeat identical compatibility expressions. The warning does not establish failed parsing; no local replacement of the upstream parser was justified. |
| Optional qBittorrent acquisition path absent | The source already enables polling discovery. An absent external volume/log is not repaired by creating fake data. |
| One expired CA in the Lynis aggregate count | The supplied count does not identify a subject or path. No certificate was guessed, deleted or read from host configuration. |
| Lynis root Docker CLI probe failed | The managed engine remains rootless and locked to its existing devops account/socket authority. No rootful fallback or store reset was added. |
| UCSI `GET_PDOS` error `-5` | The log is a firmware/kernel/hardware observation and does not identify a safe repository correction. No speculative module blacklist or kernel change was made. |
| Overlayfs file-handle/index/xino feature probes | These are capability/fallback observations from the existing rootless storage path. No existing store was reset or reconfigured. |
| labwc global Xwayland executable warning | The existing intentional two-app private Xwayland policy remains; native launches and Zoom/Discord are not broadened to a global X server. |
| Failed sudo conversation for arbitrary benchmark commands | No authorization bypass was added. |
| Empty managed scanner output files | Empty logs do not demonstrate successful scans; no success claim is inferred. |

## Evidence and material limits

The target contract is Forky with systemd 262. This work did not measure an
installed target's package versions. The installer now checks minimum native
calendar libraries/APIs and the rendered asset authority before activation, but
that future installation check was not run here. Reboot reconnect, actual power
handoff, loaded AppArmor behavior, the GTK tooltip/Waycal interaction, Calix
activation, user-keyring storage, Fruux synchronization and authenticated feed
retrieval are not live verified results.

Root `inventory.json` and `inventory-apt.json` were not regenerated and are stale
relative to this changed payload. They must not be presented as coverage for the
new snapshot. No commit, push, publication, deployment or source compilation was
performed.

Snapshot and changed-path evidence is recorded below after the final pure build.

## Final serialization and source evidence

Exact final build command (exit status 0):

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 HOME=/nonexistent /usr/bin/make build 'PYTHON=/usr/bin/python3 -I -S'
```

- Builder output: **built 1,822 payload files**.
- Bounded archive-as-data inspection compared every member with current source bytes and its manifest digest, and checked exact source/manifest/archive membership, metadata and both preseed pins: **1,822 members, 34,738,656 expanded bytes**. No archive member was executed or extracted into a target filesystem.
- Standalone `ast.parse` inspected **20 changed Python sources** and **6 embedded desktop Python blocks** as data. No repository module or fixture was imported. Embedded block source lines: 1776, 1895, 2070, 2170, 2372, 2628.
- Source-as-data reads confirmed two clock objects, the single Open calendar GTK leaf, and all ten profile release blocks. The initial inspection expression omitted digits from variable names and stopped at `SHA256`; the corrected expression includes digits and completed.
- `git diff --check` completed with exit status 0.
- Fixture source revision: starting HEAD above plus **13 changed fixture/test files**, fingerprint `78b3385755db939adaccd796462aaa9be1112e07dff2a0cde9af766626106764`. The fingerprint hashes each sorted porcelain record path, NUL, and file SHA-256 bytes (or the deletion marker), for `d-i/forky/tests/` and `tools/tests/` only. All fixtures are unexecuted.
- The payload manifest digest below fingerprints the serialized installer source snapshot.

| Generated path | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `dbb2f59f42c0967c26d2f621d8c42144ae1436e6e88cad24f6ad89d932d3d298` |
| `d-i/forky/payload.manifest` | `adf2060f9aabb31dd567178197b1c574eb82a2b606c30dc5f6ba1148958b8780` |
| `d-i/forky/preseed.cfg` | `c8513a54f9ba36f63ca13b9d40cabd86414f4385b00035e71b768b0d7a491fe8` |

Both root inventories still record payload SHA-256 `ebe3ab9e1c0769164903d72ac399bbe18f5835626f3fec7672e4f110d2b5b67b`; they are stale.

## Exact changed paths

`M` = modified, `D` = removed, `A` = new untracked file; no files were staged or committed.

```text
D d-i/forky/hooks/target/etc/skel-desktop/.config/khal/config.tmpl
D d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.service
D d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.service.d/60-resource-class.conf
D d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-calendar-sync.timer
D d-i/forky/hooks/target/etc/skel-desktop/.config/todoman/config.py
D d-i/forky/hooks/target/etc/skel-desktop/.config/vdirsyncer/config.tmpl
D d-i/forky/hooks/target/etc/skel-desktop/.local/share/calendars/personal/color.tmpl
D d-i/forky/hooks/target/etc/skel-desktop/.local/share/calendars/personal/displayname
D d-i/forky/hooks/target/etc/skel-desktop/.local/share/calendars/tasks/color.tmpl
D d-i/forky/hooks/target/etc/skel-desktop/.local/share/calendars/tasks/displayname
D d-i/forky/hooks/target/etc/systemd/system/NetworkManager.service.d/30-wifi-manual.conf
M README.md
M d-i/forky/classes/class-select/role/desktop.cfg
M d-i/forky/hooks/target/etc/NetworkManager/system-connections/wifi.nmconnection.tmpl
M d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
M d-i/forky/hooks/target/etc/apparmor.d/labwc-session
M d-i/forky/hooks/target/etc/apparmor/modes.conf.tmpl
M d-i/forky/hooks/target/etc/fangfrisch.conf
M d-i/forky/hooks/target/etc/skel-desktop/.config/labwc/menu.xml.tmpl
M d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/obsidian-git-sync.service
M d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/waybar.service
M d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/calendar-menu.xml.tmpl
M d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl
M d-i/forky/hooks/target/etc/skel-desktop/.recoll/recoll.conf
M d-i/forky/hooks/target/etc/systemd/resolved.conf.d/60-app-veth.conf.tmpl
M d-i/forky/hooks/target/etc/systemd/system/apt-daily-upgrade.service.d/50-unattended-upgrades-notify.conf
M d-i/forky/hooks/target/etc/systemd/system/apt-daily.service.d/override.conf.tmpl
M d-i/forky/hooks/target/etc/systemd/system/apt-refresh-lists.service.tmpl
M d-i/forky/hooks/target/etc/systemd/system/apt-repo-local-refresh.service
M d-i/forky/hooks/target/etc/systemd/system/clamav-freshclam.service.d/40-logging.conf.tmpl
M d-i/forky/hooks/target/etc/systemd/system/clamav-signature-update.service.tmpl
M d-i/forky/hooks/target/etc/systemd/system/key-manager-acme-renew.service.tmpl
M d-i/forky/hooks/target/etc/systemd/system/lynis.service.d/40-logging.conf.tmpl
M d-i/forky/hooks/target/etc/systemd/system/wifi-firstboot.service
M d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/apparmor-modes/AppArmor/ManagedModes/Transition.pm
M d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/network/ManagedNetwork/Validator.pm
M d-i/forky/hooks/target/usr/local/libexec/clamav-signature-update
M d-i/forky/hooks/target/usr/local/libexec/labwc-admin-action-worker
M d-i/forky/hooks/target/usr/local/libexec/labwc-calendar
M d-i/forky/hooks/target/usr/local/libexec/labwc-wrap-desktop-files
M d-i/forky/hooks/target/usr/local/libexec/network-wifi-configure
M d-i/forky/hosts/profiles/btrfs-de-duo.env
M d-i/forky/hosts/profiles/btrfs-de-flex-duo.env
M d-i/forky/hosts/profiles/btrfs-de-flex.env
M d-i/forky/hosts/profiles/btrfs-de-p15s-duo.env
M d-i/forky/hosts/profiles/btrfs-de-p15s.env
M d-i/forky/hosts/profiles/btrfs-de.env
M d-i/forky/hosts/profiles/f2fs-de-hp14-duo.env
M d-i/forky/hosts/profiles/f2fs-de-hp14.env
M d-i/forky/hosts/profiles/f2fs-de-x360-duo.env
M d-i/forky/hosts/profiles/f2fs-de-x360.env
M d-i/forky/hosts/themes/apps.env
M d-i/forky/hosts/themes/theme-schema.tsv
M d-i/forky/payload.manifest
M d-i/forky/payload.tar.gz
M d-i/forky/preseed.cfg
M d-i/forky/scripts/common/credentials.sh
M d-i/forky/scripts/desktop/components/desktop-config.sh
M d-i/forky/scripts/desktop/components/desktop-helpers.sh
M d-i/forky/scripts/desktop/components/services.sh
M d-i/forky/scripts/desktop/components/target-assets.sh
M d-i/forky/scripts/desktop/verify.sh.tmpl
M d-i/forky/scripts/firstboot/04-validation.sh.tmpl
M d-i/forky/scripts/late/network-generate.pl
M d-i/forky/scripts/late/security.sh
M d-i/forky/scripts/late/storage-maintenance.sh
M d-i/forky/tests/fixtures/contracts/theme-names.tsv
M d-i/forky/tests/test_boot_runtime_20260913.py
M d-i/forky/tests/test_desktop_sandbox.py
M d-i/forky/tests/test_fail2ban_clipboard_apparmor_20260928.py
M d-i/forky/tests/test_initrd_credentials.py
M d-i/forky/tests/test_installation_fixes_20260912.py
M d-i/forky/tests/test_kernel_veth_networking.py
M d-i/forky/tests/test_native_menu_contract_20260920.py
M d-i/forky/tests/test_power_force_contract.py
M d-i/forky/tests/test_systemd_resource_policy.py
M d-i/forky/tests/test_todo_network_incidents_20261017.py
M tools/tests/test_installed_session_failures_20260913.py
A d-i/forky/hooks/target/etc/apparmor.d/calendars
A d-i/forky/hooks/target/etc/cron.d/debsecan
A d-i/forky/hooks/target/etc/fail2ban/jail.local
A d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-calix.service
A d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-waycal-hover.service
A d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/labwc-waycal.service
A d-i/forky/hooks/target/usr/local/libexec/calix-fruux-bootstrap
A d-i/forky/hooks/target/usr/local/libexec/clamav-fangfrisch
A d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-hover
A d-i/forky/hooks/target/usr/local/libexec/network-online-check
A d-i/forky/hooks/target/usr/local/share/applications/com.ianswope.Calix.desktop
A d-i/forky/scripts/desktop/calendar-install.py
A d-i/forky/scripts/desktop/fangfrisch-configure.py
A d-i/forky/tests/test_urlhaus_credentials.py
A docs/calendar-and-wifi.md
A docs/clamav-urlhaus.md
A docs/todo-20261023-source-review.md
```
