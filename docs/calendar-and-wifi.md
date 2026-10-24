# Calendar and saved Wi-Fi behavior

This describes the October 23–24 source changes for new Forky installations. The
behavior below is the implemented contract; it has not been demonstrated in a
running desktop. See [alternate clock format removal](validation/clock-format-removal-20261024.md)
for the latest Waybar 0.15.0 controls and artifact receipt, and
[October 24 click mapping and Waycal theme](validation/waycal-click-20261024.md)
for the preceding integration and acceptance limits. The earlier
[log, hover and MOK report](validation/todo-waycal-mok-20261024.md) records the superseded hover approach.
See [Calix install ordering correction](validation/calix-install-order-20261023.md)
for the latest install changes, and [Calendar and recorded-log fixes](validation/calendar-firstboot-20261023.md)
for the firstboot implementation and runtime limitations. The earlier
[Agenda, Fruux and Tor report](validation/agenda-fruux-tor-20261023.md) records
the previous implementation.

## Clock and native calendar applications

All ten host profiles pin these public x86-64 releases:

| Application | Version | Source commit | Archive SHA-256 |
| --- | --- | --- | --- |
| Waycal | 0.2.1 | `b9b5abd73fbaebf0756157ad141e509410ff181c` | `b2d7a98129f3b5444d9597e8e263b0f590dfc268e38c30b5ae6c78a832b1004b` |
| Calix | 0.8.0 | `56fb3aae672384af2a304f69815c3a8d601e7f35` | `935257aed019834e3d79f127bb14b575ee2cbb32b33baa8f4b9c12e50efedb64` |
| Agenda | 1.2.1 | `5276daf526fd29bf7166fda0ea00996ae8e28310` (release tag) | `22c2c9bb03f77225710cacb947ad36bbb08b302f7d6ed3b923d51b67abcdc719` |

The installer checks each configured URL, version, commit, byte limit and digest
against the supported release contract, checks the target architecture, and
checks the downloaded ELF architecture. HTTPS redirects are checked before
following them. Downloads, expansion, member count and individual files have
limits. Only the selected binary, icon and license are published; vendor install
scripts are not executed and no application is compiled. The receipt under each
`/opt/<application>/release.json` (Waycal/Calix) or
`/usr/local/share/agenda/release.json` also pins the installed executable bytes.
These hashes establish byte consistency; they are not vendor signatures.

Agenda's binary is installed as `/usr/local/bin/com.github.dahenson.agenda`.
Its dedicated desktop entry and `labwc-agenda` command use the shared managed
launcher and transient `labwc-native-agenda-*.service` units, with native
Wayland and GApplication activation. The command is an installed alias of
`labwc-app`, with no separate shell wrapper. Its
scoped GSettings defaults provide a 600×680 window, pending tasks first, and
Noto Sans 12 for printing; GTK follows the existing desktop theme. Translations
retain the archive's compiled `/usr/share/locale` prefix. Icons, license,
metadata and the private schema cache are installed as data. No vendor install
script or application source build runs.

The published Agenda archive records build commit
`e7a71a506b8452e307b908c55d4d63237a7113cb` and `working_tree_modified=true`.
This differs from its release tag. The installer records both facts and does
not claim that the binary was built from a clean tagged tree.

Both Waybar layouts use the following controls:

| Control | Action |
| --- | --- |
| Hover over the clock | No tooltip or popup; the former `Calendar` text is disabled. |
| Left click the clock | Open the native GTK dropdown without changing the clock format. |
| Middle click the clock | No clock action. |
| Right click the clock | Open Waycal when closed; close it when open. |
| Dropdown → Open calendar | Open/activate Calix through `labwc-calendar`. |
| Dropdown → Open agenda (directly below Open calendar) | Open/activate the actual Agenda application through `labwc-agenda`. |
| Dropdown → Events | Create Event…, or select an event to edit/delete on Fruux. |
| Dropdown → Tasks | Pending tasks, all tasks, create, edit, details, complete, delete on Fruux. |

The user's latest instruction removes alternate clock formatting entirely.
Both clocks retain the single `format: {:%a %H:%M}` and `tooltip: false`.
Neither defines `format-alt` or `format-alt-click`; no left-click command or
action competes with the native GTK menu, and middle-click has no action.
The fixed right-click command starts
`labwc-waycal-toggle.service`. This on-demand oneshot serializes state reads
and start/stop requests for `labwc-waycal.service`, which owns the popup's
process cgroup and is stopped with the desktop session. There is no process-name
kill, PID-file scan, accessibility bridge or automatic retry of an uncertain
mutation. The former hover helper, autostart unit and ptrace permission have
been removed. The native month popup starts on Monday; Escape also closes it.

Waycal 0.2.1 has no native user config or CSS-file option. Its embedded style is
loaded at GTK's application priority. GTK4 supports the higher-priority user
stylesheet `~/.config/gtk-4.0/gtk.css`, so the installer supplies an import of
`~/.config/waycal/style.css`. This is the editable user styling drop-in. Every
selector is scoped to `window.waycal`; other GTK4 applications retain their
styles. Both sharp and rounded variants get a dark purple background at 94%
opacity, a purple border and today highlight, and opaque light text. Only the
background has slight transparency. The files are staged into the skeleton and
copied to the primary account before activation. Reopening Waycal loads edits.

Task operations that prompt for a selection, form or confirmation use
`Create task...`, `Edit task...`, `Delete task...` and
`Mark task completed...` in the GTK submenu.

Calix uses the same managed native launch path and transient
`labwc-native-calix-*.service` units. `labwc-calendar` is an alias of `labwc-app`;
desktop entries and application search resolve to the same managed application.
Both applications use native GApplication single-instance activation. Closing
the desktop session stops each service cgroup. The normal Calix launch opens
its window; synchronization follows the pinned application's native lifecycle.
Agenda uses Labwc's server decorations. Its managed profile loads Debian's
`libgtk-nocsd0` library for Agenda only: the GTK header bar's application menu
stays in the window content, while Labwc supplies the title bar, borders and
window buttons. The package's global preload snippet is overridden by the
comment-only `/etc/environment.d/50-gtk-nocsd.conf`; the managed Agenda launch
sets the library explicitly. The existing native Wayland backend is retained.
Calix owns calendar event operations;
the old terminal actions, calendar sync timer and khal/todoman/
vdirsyncer payload configuration and packages have been removed. Taskwarrior and
Sleek retain their separate existing roles. The new GTK event/task actions use
direct CalDAV operations. Agenda remains a local task list: it has no CalDAV
backend, and its local tasks are separate from the Fruux Tasks submenu.

The apps and bootstrap/toggle delegates have explicit AppArmor profiles.
Installation prepares the account home, installs the calendar binaries and
private Fruux input, then synchronizes the account launchers before enabling
desktop services. The separate `verify.sh` module is not fetched, sourced or
called during installation. Release downloads retry transport failures up to
three times, with a 300-second socket stall timeout and no total transfer or
calendar installation duration cap. Hash, release and publication checks are
part of installing the actual files. The existing private Xwayland eligibility
remains Zoom and Discord only.

Primary release contracts:
[Waycal 0.2.1](https://github.com/ForrestKnight/waycal/releases/tag/v0.2.1),
[Calix 0.8.0](https://github.com/ianswope/calix/releases/tag/v0.8.0),
[Waybar 0.15.0 label click handling](https://github.com/Alexays/Waybar/blob/0.15.0/src/ALabel.cpp),
[Waybar 0.15.0 clock module](https://github.com/Alexays/Waybar/blob/0.15.0/src/modules/clock.cpp).

### October 24 log corrections

The click integration uses no a11y bridge. The hover-only direct package
requests for `gir1.2-atspi-2.0` and `at-spi2-core` were removed; GTK packages
may still depend on accessibility libraries for their own purposes.

Calix's managed launch now sets `GDK_WAYLAND_DISABLE=wp_presentation` for Calix
only, alongside its existing native Wayland backend. This selects GTK's frame
callback timing fallback for the duplicate presentation-feedback warning.
It is a compatibility workaround, with less precise presentation timestamps;
native reproduction and visual acceptance remain open.

The GVFS user-service drop-in now uses `KillMode=control-group` with its
existing 15-second stop budget, so FUSE cleanup receives the grace period
instead of `mixed` escalating when the main daemon exits. The XFS healer
starter gets a staged, bounded `ExecStartPre` manager reload before its native
mount scan starts per-mount healers. The installer performs no live manager
operation for this drop-in. These source corrections still require native
logout and boot acceptance; details and primary sources are in the
[current log review](validation/waycal-click-20261024.md).

## Fruux credential handoff

The existing private `PRESEED_FRUUX_USERNAME` / `PRESEED_FRUUX_PASSWORD` installer
inputs and existing installer fallback contract are retained. The password is
written into a private target staging file, never passed as a command argument
or environment assignment to the target calendar installer. The installer
creates the primary account's `.config/calix/fruux-bootstrap.json` as that user,
mode 0600, inside its mode-0700 Calix directory. It is credential-bearing data;
Recoll excludes Calix configuration and its local event database.

`fruux-firstboot.service` runs as the configured desktop UID before greetd. Its
`--provision` mode creates the Fruux CalDAV account in Calix's private SQLite
database, commits and synchronizes it, and publishes a durable non-secret
`fruux-state.json` receipt. This phase has no network, display, D-Bus or keyring
dependency. It uses `https://dav.fruux.com`; native CalDAV discovery resolves the
actual principal and collections rather than baking private resource IDs into
the image. Calix completes its own additive schema on normal startup.

At desktop login, `labwc-calendar-credentials.service` starts automatically
after the existing KWallet Secret Service provider is ready. The helper's
`--install-secret` mode checks the already-provisioned account without modifying
it, writes the password to Secret Service, and reads it back. It uses the exact
pinned Calix identity: service `com.ianswope.Calix`, username attribute
`caldav-password:https://dav.fruux.com|<trimmed-lowercase-username>`. Only after
readback does it publish readiness and unlink/synchronize the private password
input. Normal desktop authentication supplies the existing keyring unlock;
opening Calix or a clock dialog does not run account setup or secret delivery.

Account provisioning, credential delivery and cleanup readiness share one
stable owner lock. Ambiguous/different existing keyring entries, incompatible
account identities, unsafe paths and invalid inputs retain the private input
when present and fail with fixed diagnostics. Existing accounts and calendars
are preserved. Failed provisioning leaves no completion receipt and retries
on the next boot. Credential delivery retries automatically within the user
service's bounded start policy and on later logins. No network is needed for
either local step; offline remote synchronization uses Calix's normal retries.

On subsequent boots the completion receipt skips firstboot provisioning.
The login service checks the receipt and returns without opening Secret Service
when no password input remains. Calix uses its saved database and keyring entry.
Secondboot cleanup waits for successful credential delivery and durable password
input removal. Its root-owned delegate drops all root/group authority before
checking user state under the same lock. Cleanup then removes
`fruux-firstboot.service`, its enablement link, the greetd ordering drop-in and
the temporary cleanup delegate. Pending delivery retains these artifacts and
the existing secondboot retry infrastructure. The database, non-secret account
identity/receipt and stable lock remain permanent integration state. Calix does
not depend on the removed firstboot unit. No live Fruux login was attempted.

The seed is tied to the pinned
[Calix account schema](https://github.com/ianswope/calix/blob/56fb3aae672384af2a304f69815c3a8d601e7f35/src/store.rs)
and [credential key format](https://github.com/ianswope/calix/blob/56fb3aae672384af2a304f69815c3a8d601e7f35/src/icloud/credentials.rs).
Future Calix upgrades must review both contracts before changing the release pins.

### GTK event and task actions

Both clock layouts dispatch fixed actions to `labwc-calendar-actions` in
session-owned cgroups. A same-UID runtime lock prevents competing dialogs.
Each action checks the automatic login service's readiness through the user
manager, then loads the saved account identity and Secret Service
credential. The non-secret identity file is `.config/calix/fruux-account.json`,
mode 0600; no password is placed in command arguments or inherited environment.

The GTK controller uses plain text widgets, searchable selection lists and
explicit destructive/series confirmations. Worker input/output is private JSON,
bounded during streaming. The worker uses packaged `python3-icalendar` and
`python3-defusedxml`, verified TLS, no inherited proxy, and only
`https://dav.fruux.com`. Discovery redirects are checked before the next request;
writes never redirect or retry. Each operation rediscovers the selected
collection, checks privileges and binds an item to its URL, UID and strong ETag.
Creates use `If-None-Match: *`; updates/deletes use `If-Match`. A changed item
fails with a conflict. A successful HTTP write acknowledges a remote change;
it is not a local-only task-file update.

Dates accept ISO all-day dates or date/time values. Timed writes use UTC;
ambiguous/nonexistent daylight-saving times require an explicit offset. All-day
event end dates are exclusive. Unknown iCalendar properties, alarms and
timezone components survive edits. Recurring series details can be edited
without moving recurrence dates or exceptions. Deleting a series requires an
explicit series confirmation. Completing a recurring task, moving its dates,
and editing/deleting organizer/attendee items require a richer native editor
and return unavailable through these dialogs; no partial mutation is attempted.

Network work has a total 50-second controller deadline and a separate bounded
termination/reaping budget. The read-only credential readiness check has a
five-second deadline. Interactive forms have no
arbitrary expiry. Read cancellation, unavailable, failure and outcome-unknown
results remain distinct. Calendar contents and credentials are excluded from
diagnostics; logs contain fixed action/error codes and request IDs.

Before every remote write, the worker durably writes a private
`.config/calix/fruux-pending.json` intent under `.fruux-actions.lock`. It retains
this record until the controller receives the server acknowledgement and
confirms local completion. A lost connection, killed worker or lost IPC reply
therefore leaves evidence. The next dialog reads the current remote object and
requires review before discarding that evidence; it does not replay the write.
Writers and acknowledgement/cleanup use the same lock. Malformed or unsafe
recovery files fail closed and require private inspection, never broad cleanup.

## Wi-Fi reconnect and Ethernet preference

The managed Wi-Fi profile now enables autoconnect and has empty connection
permissions, making the saved system connection eligible before login. Native
nmtui still prompts for the SSID/password. After editing, the helper checks that
secrets are saved in the system profile and normalizes autoconnect and connection
permissions without putting the secret in command arguments. NetworkManager may
omit its default `autoconnect=true` property; the consumers accept that default.

The old NetworkManager pre-start action that wrote `WirelessEnabled=false` at
every boot has been removed. Firstboot publishes a configured profile even when
the SSID is temporarily invisible; it preserves an existing saved profile. Boot
does not toggle the radio or override rfkill. A deliberate radio-off or hardware
block remains respected. An explicit desktop Wi-Fi request still enables the
radio and opens native nmtui.

Existing static addressing, interface/MAC binding and DNS policy remain in force.
Ethernet's route metric stays **100**, and Wi-Fi's stays **200**, for both address
families. Thus connected Ethernet has route preference. Link availability alone
does not prove that the Ethernet path can reach the Internet; this change does
not implement connectivity-based failover between simultaneously connected links.

No reboot, radio, NetworkManager, route or graphical operation was run on the
development host. Historical manual-radio reports describe older snapshots.
