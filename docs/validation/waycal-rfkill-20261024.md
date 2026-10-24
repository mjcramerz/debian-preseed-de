# October 24: Waycal rfkill inheritance and Agenda dark appearance

## Supplied evidence and source revision

The user supplied two LPL-365 AppArmor AVC records, audit serials 2262 and
2290. Both identify `labwc-waycal-control`, operation `file_inherit`, path
`/dev/rfkill`, requested and denied mask `r`, filesystem UID 1000 and object
UID 0. These are new supplied events, separate from the earlier LPL-128
service-cascade capture. No live host log or device was queried.

The checkout was clean on `mcr/main` at
`0429cd45c55cdfcfa7fd947f0d6d259f9c28a575` before this repair.

## Correction and affected path

Added `/dev/rfkill r,` inside the `labwc-waycal-control` profile in
`d-i/forky/hooks/target/etc/apparmor.d/calendars`. The permission is read-only
and applies to the exact reported device path. It is unqualified by `owner`
because the supplied events identify a root-owned device and a UID-1000
controller. The same rule covers both reported read inheritance requests.

The reviewed invocation path is the Waybar calendar action calling
`/usr/local/libexec/labwc-waycal-control`. Desktop target staging installs
that helper, and the managed security stage includes the `calendars` policy.
The controller uses the user service manager to own the popup's lifecycle.
The wrapper include chain contains no conflicting rfkill deny in the checked-in
managed abstractions. The inherited descriptor's original opener is not
established by the two AVC records alone.

The existing rfkill policy fixture in
`d-i/forky/tests/test_apparmor_incidents_20261004.py` now includes this
profile in its check for the exact read-only grant. The fixture remains
unexecuted, including its imports and discovery path.

## Agenda dark appearance

The user also requested dark appearance for Agenda. Its managed application
profile now supplies `GTK_THEME=Adwaita:dark`. The local Agenda 1.2.1 source
sets `gtk_application_prefer_dark_theme` from Granite's color-scheme
preference during activation and on preference changes. That can select light
appearance when no dark preference is provided by the Labwc session.
GTK's [documented theme variant override](https://docs.gtk.org/gtk3/running.html#environment-variables)
selects the dark variant explicitly for this application.

The desktop entry uses `labwc-app auto agenda`; the `labwc-agenda` command is
an alias to the same managed entrypoint. `build_environment` applies the
application environment before executing Agenda. Its existing native Wayland
backend, app-local GTK-NoCSD loader and private schema directory remain in
that environment. The schema override's introductory comment now describes
the launcher-selected dark appearance. Its settings are otherwise unchanged.
The existing Agenda policy already permits the toolkit/library and theme data.
No source build, new dependency or extra theme download was introduced.

## Static inspection and generation

- Fixture source and the managed profile template parsed with standard-library
  `ast.parse` as data, without importing or executing them. Literal AST
  inspection confirmed Agenda's environment and the existing Zoom/Discord-only
  compatibility eligibility.
- `git diff --check`: exit 0 after the source edit.
- `make build PYTHON=/usr/bin/python3`: exit 0, 1,838 members.
- Bounded archive-as-data comparison confirmed every member's bytes against
  its source and manifest digest, the complete input set, canonical
  mode/UID/GID/mtime 0644/0/0/0 and the preseed archive/manifest/bootstrap pins.
  The final combined payload includes both changes. Expanded content is
  34,944,124 bytes; the archive is 26,630,052 bytes.
- `make inventory PYTHON=/usr/bin/python3`: exit 0 after the final combined
  build, with 97 acquired indexes, 21,357 retained package candidates and zero
  unavailable metadata requests. Both root JSON payload hash/size pins match
  the final archive, and the metadata cross-pin matches `inventory-apt.json`.
  The metadata collector does not verify APT Release OpenPGP signatures or
  perform a package installation transaction.
- Final source and fixture hashes still match the serialized inputs, and
  `git diff --check` remains exit 0.

| Source / generated product | SHA-256 |
| --- | --- |
| `hooks/target/etc/apparmor.d/calendars` | `d88620081f8c2bc32892d6721eb0058e180cdcceb31d8b9e77cb6012ecdb20f3` |
| `labwc_managed_app/profiles.py.tmpl` | `8b75badeae211630bc7bcaf38f4d536525215e41125ece1133d7a8c068bda226` |
| `usr/local/share/agenda/schemas/90-desktop-agenda.gschema.override` | `3ab994a6d8b950001a67ac82904b917ddcf07d97f42fa48356423257d15aaf0d` |
| `tests/test_apparmor_incidents_20261004.py` | `57a873ac51ad318c4996814a15d6e3dda8c9292ef0a8fb8fd122dd3e20670849` |
| `d-i/forky/payload.tar.gz` | `f5ddfddf6f195db43291a9b6fc468b248813c00031c70ff5f2e5774927f69558` |
| `d-i/forky/payload.manifest` | `3ac4d0ec1ae833a4a68f1a887f317b33ae9677e39982c06f8bc45b12a9ac9578` |
| `d-i/forky/preseed.cfg` | `87603a6cbe34269f09e84fc9cb78c217f5e141162d73753f3984808b944722d4` |
| `inventory.json` | `a1b90e1b5a865c39bbaf361676ece4752af459b906129b86f14ca6cf425d2c7f` |
| `inventory-apt.json` | `ee44fc74985f2d56f4e884cef44df38572d3d7e77527cfbc7e11dbb85d80f888` |

## Acceptance limits

No native AppArmor parser, test runner, service manager, policy reload, device
access, disposable environment or deployment was used. The installed AppArmor
package version and a post-fix event capture were not supplied. Source and
artifact consistency establish the repository changes; loaded-policy behavior,
Agenda's visible appearance and the broader service-recovery goal remain
unverified. The installed Agenda/GTK package versions were not queried.
