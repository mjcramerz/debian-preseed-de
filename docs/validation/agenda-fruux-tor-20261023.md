# Agenda, Fruux actions and Tor Browser — October 23 implementation record

## Status

Source implementation is complete. The user explicitly requested **no VM or
validation**; no executable fixture, native target check, GUI launch, AppArmor
load, target APT transaction, browser decode or live Fruux operation has run in
this task. No environment or further validation is being requested. Earlier
source-as-data inspection is recorded below. The permitted pure payload and
inventory generation commands are separate from tests and runtime acceptance.

### Subsequent installer failure and removal of late checks

The user reported a later installation failure after Whisper with
`theme rendering: malformed/unresolved token`, and explicitly instructed that
no additional installation verifications be introduced.

The previous Agenda/Fruux changes added a literal reserved theme prefix to
`scripts/desktop/verify.sh.tmpl` (then line 2735), in a check intended to inspect
the installed worker. `scripts/late/desktop.sh` fetches the verifier along with
the desktop modules before sourcing them. The shared `fetch_hook` in
`scripts/late/core.sh` theme-renders desktop sources during that fetch. The
literal prefix therefore aborts rendering before the verifier can even run.
This source path explains the quoted error; a fresh failed install's log was
not supplied or inspected.

The dedicated `desktop_verify_calendar_stack` function and its staging call
have been removed, together with the added Agenda service/file checks, worker
checks and exact calendar action verification block. The application installer,
profile pins, desktop entry, services, menu dispatch and Fruux implementation
remain incorporated. No new verification stage or fixture was introduced for
this correction, and no tests, validators or VM were run.

The existing theme renderer now reports its input filename and line for errors.
Its caller also reports the logical asset being rendered. These are diagnostic
changes to the existing rendering path, with no additional check or stage.
Failed rendering still leaves the original file intact.

The user's clock clarification supersedes the original click assignment:
**right click opens the GTK menu; Open agenda directly follows Open calendar
and launches the Agenda application.** Left click toggles the full date/week.

## Owning implementation paths

- `d-i/forky/hosts/profiles/*.env`: all ten active profiles declare Agenda's
  version, URL, release commit, archive SHA-256 and maximum download bytes.
- `d-i/forky/classes/class-select/role/desktop.cfg`: Agenda's native Granite/Gee
  runtime, schema compiler, and packaged iCalendar/defused XML dependencies.
- `d-i/forky/scripts/desktop/calendar-install.py`: bounded release acquisition,
  archive member selection, `/usr/local/bin/com.github.dahenson.agenda`, scoped
  schemas, translations, icons, receipts and private Fruux account identity.
- `scripts/desktop/components/{desktop-config,target-assets,stage-assets}.sh`
  under `d-i/forky/`: pin handoff, assets, public schema directory modes.
- Target `usr/local/bin/labwc-agenda`,
  `usr/local/share/applications/com.github.dahenson.agenda.desktop`,
  `usr/local/share/agenda/schemas/90-desktop-agenda.gschema.override` and
  `etc/skel-desktop/.config/systemd/user/labwc-agenda.service` under
  `d-i/forky/hooks/target/`: Agenda activation, defaults and session lifetime.
- Target `usr/local/libexec/labwc-calendar-{actions,worker}`: native GTK forms,
  bounded private worker IPC, direct conditional CalDAV writes and recovery.
- Target `etc/skel-desktop/.config/waybar/{calendar-menu.xml,config}.tmpl`:
  both clock layouts, two submenus and eleven fixed leaf actions.
- Target `etc/apparmor.d/calendars`, `usr/local/libexec/labwc-wrap-desktop-files`
  and skeleton `.recoll/recoll.conf`: confinement, dedicated launcher handling
  and private Agenda task data exclusion.
- `d-i/forky/scripts/desktop/verify.sh.tmpl`: the added late Agenda/Fruux checks
  were removed following the subsequent installer failure and user instruction.
- `d-i/forky/scripts/late/{theme-render.awk,themes.sh}`: filename/line and
  logical asset diagnostics on the existing rendering failure path.
- `d-i/forky/classes/class-addon/software.cfg` and
  `d-i/forky/scripts/late/tor-browser.sh`: explicit compatible FFmpeg libraries
  and their installation/check ordering.

The existing Zoom/Discord private Xwayland implementation and eligibility were
not edited by this task. Unrelated worktree edits, including earlier calendar
and Wi-Fi work, remain present.

## Agenda release evidence

Primary [release](https://github.com/mjcramerz/agenda/releases/tag/agenda-v1.2.1)
and GitHub API metadata identify release tag commit
`5276daf526fd29bf7166fda0ea00996ae8e28310`.

The exact requested archive was downloaded as data. Its observed length was
125,787 bytes and SHA-256 was
`22c2c9bb03f77225710cacb947ad36bbb08b302f7d6ed3b923d51b67abcdc719`, matching
the API asset digest. Its member layout includes
`agenda-1.2.1-debian-amd64/rootfs/usr/bin/com.github.dahenson.agenda`, the
GSettings schema, namespaced icons/translations, license and build metadata.
No archive executable or installer script was run.

`BUILD-INFO.json` records build commit
`e7a71a506b8452e307b908c55d4d63237a7113cb`, `working_tree_modified=true`,
amd64, prefix `/usr`, GTK 3.24.52, GLib 2.90.1 and Granite 6.2.0. The receipt
keeps the release tag and dirty build identity distinct. Archive hashes prove
byte consistency, not clean-source provenance or a vendor signature.

The pinned [schema](https://github.com/mjcramerz/agenda/blob/5276daf526fd29bf7166fda0ea00996ae8e28310/data/com.github.dahenson.agenda.gschema.xml)
and [local file backend](https://github.com/mjcramerz/agenda/blob/5276daf526fd29bf7166fda0ea00996ae8e28310/src/Backend/FileBackend.vala)
were inspected as source data. Agenda has local tasks, not a CalDAV backend.
The Fruux Tasks submenu therefore uses the dedicated remote worker and does
not claim to synchronize Agenda's local task files.

## Tor Browser failure and fix

The reported path is `/usr/lib/x86_64-linux-gnu/libavcodec.so.62`. The current
Tor installer's post-install `ctypes.CDLL` call loads exactly that ABI. The
desktop package list previously requested only unversioned `libavcodec-extra`.
Current [Forky metadata](https://packages.debian.org/forky/libavcodec-extra)
selects FFmpeg 9 / `libavcodec-extra63`, which does not supply the requested
ABI. The repository's stored candidate metadata independently records that
same Forky dependency and ABI 62 packages in its configured Sid source.

The pinned Firefox ESR 140
[runtime linker](https://github.com/mozilla-firefox/firefox/blob/esr140/dom/media/platforms/ffmpeg/FFmpegRuntimeLinker.cpp)
and [library wrapper](https://github.com/mozilla-firefox/firefox/blob/esr140/dom/media/platforms/ffmpeg/FFmpegLibWrapper.cpp)
support ABI 62 and reject unknown future versions. Substituting ABI 63 in the
probe would not establish browser compatibility.

The software class now requests `libavcodec62`, `libavutil60` and
`libswresample6`. Before downloading/publishing Tor Browser, its target stage
explicitly installs those packages through the existing signed APT policy,
with `--no-remove`, no recommendations/suggestions, a 60-second APT lock
budget and a 300-second transaction deadline. Restart handling is suspended
for this installer transaction, following the surrounding installer convention.
No source/repository/keyring or global release preference is changed.

The subsequent dropped-privilege probe checks configured package status,
loads ABI 62 with immediate symbol resolution, checks `avcodec_version()` and
the required decoder APIs, under a separate 20-second deadline. Loader failures
produce a fixed actionable diagnostic instead of a raw `OSError` traceback.

Public package archives were inspected as data against stored candidate byte
hashes. The three compatible runtime packages were version `7:8.1.2-2+b3`
from Sid; their control archives contained `activate-noawait ldconfig` triggers
and no preinst/postinst/prerm/postrm scripts. This inspection did not execute
dpkg, APT, ldconfig or any shared library. It does not prove a successful native
APT solver transaction. That behavior remains unexecuted. Package availability
can change as the Debian archive moves.

## Static evidence and unexecuted fixtures

Source-as-data inspection performed before the user's no-validation instruction
includes the following. Some source edits followed that inspection; these are
not claims of executable checks or acceptance of the final working tree.

- Python AST parsing of the installer, both new calendar delegates, changed
  test modules, and the affected embedded target Python blocks. No repository
  module was imported to perform these parses.
- XML parsing of the calendar menu and literal JSON parsing of both clock
  action maps: eleven leaves match eleven actions in each layout; the Agenda
  action targets `/usr/local/bin/labwc-agenda`.
- Primary release/schema/backend inspection and public Debian package control
  archive inspection described above.

Fixtures added or adapted, **not executed**:

- `d-i/forky/tests/test_calendar_actions_20261023.py`: remote VTODO creation,
  edits preserving opaque data, ETag/UID replacement, complete/delete identity,
  scheduling/recurrence refusal, URL escape, DST gap/fold, all-day boundaries,
  hostile XML/aggregate limits, durable intent and fsync failure, unknown-write
  retention, no replay, review acknowledgement identity, shared writer/cleanup
  lock, and bounded child cancellation.
- `test_native_menu_contract_20260920.py` and
  `test_native_tomat_20260920.py`: right-click clock/menu mapping and all 82
  fixed leaf actions across both Waybar layouts.
- `test_browser_media_20261015.py`: explicit target ABI dependency installation
  before the download, missing loader/dependency reporting, wrong ABI and
  missing decoder rejection, with the loader and package queries mocked.

## Runtime evidence not claimed

Per the user's instruction, these operations were not performed: executable
fixtures; target APT dependency solving and shared-library/decoder loading;
installer staging and schema compilation; native Agenda/Calix/GTK menu use;
AppArmor policy loading; keyring bootstrap; session lifecycle; and live Fruux
create, list, edit, complete, delete or recovery. The added fixtures remain
unexecuted. Successful serialization establishes generated bytes only.

The versioned ABI 62 packages depend on continued availability in the configured
signed repositories. Actual target dependency resolution and native application
behavior remain runtime limitations of this source-only delivery.

## Initial generated artifacts (superseded by the correction above)

Base revision: `29f808142c19449f9859ac7bb1286f30c4d4f044`, with existing and
task-specific uncommitted work preserved.

Pure serialization command, completed with exit status 0 and
`built 1829 payload files`:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent LC_ALL=C.UTF-8 /usr/bin/make PYTHON=/usr/bin/python3 build
```

Generated SHA-256 values read as artifact data:

| Artifact | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `790e5dc858999c0a4ec7ef9ae0c91bcf2b4ee798baab9a0376cfd7b5786bfd67` |
| `d-i/forky/payload.manifest` | `a818487a3f489bb10224203817ec0703b1db03b46ca88e8e629722fe02902265` |
| `d-i/forky/preseed.cfg` | `df5f21f74f93ae956b6da183d20b4298fa494531776f4f3326447901c7c9a711` |

The separate inventory generation also completed with exit status 0:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent LC_ALL=C.UTF-8 /usr/bin/make PYTHON=/usr/bin/python3 inventory
```

It acquired 97 package indexes, retained 21,381 package candidates, reported
zero unavailable metadata requests, and generated from 1,829 payload members
(1,799 text files scanned; 351 relevant files). No host package state or package
manager was used. The collector reads public HTTPS metadata and checks index
bytes against Release hashes; it does not perform OpenPGP signature verification
or prove a successful package solver transaction.

| Artifact | SHA-256 |
| --- | --- |
| `inventory-apt.json` | `a98ebe28b52d5c101841f2940932f287d6f85e813d5e48203ff50789861bcad1` |
| `inventory.json` | `9cc7aaed9de6d6a38a87737bffc6b35b0c3275493506ebdb591a537c3974b710` |

## Corrected artifacts after removing the late checks

The same pure `make PYTHON=/usr/bin/python3 build` command, with the clean
environment shown above, completed with exit status 0 and
`built 1829 payload files`. This operation serialized source data only.

| Artifact | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `a3e80ef5f01567254d5d70e766712fa03d499c2c10a8faa76f5ac388cbdea8db` |
| `d-i/forky/payload.manifest` | `e574b55a8e2c5141231206ee5a58d1613395cebb86866a116ace00e21a6ea38b` |
| `d-i/forky/preseed.cfg` | `14debcf885f4988ca509bdb35ad08f93c66d08dd6bc1b5b701aaafa76557afa1` |

The separate `make PYTHON=/usr/bin/python3 inventory` command also completed
with exit status 0: 97 indexes, 21,381 retained candidates, zero unavailable
metadata requests, and generation from 1,829 payload members (1,799 text files;
351 relevant files). The paired inventories now describe the corrected payload.

| Artifact | SHA-256 |
| --- | --- |
| `inventory-apt.json` | `e8641e4d94cbf43de09d5db479a5e728a3b86e01975223410668d0cd4e9329e5` |
| `inventory.json` | `c339e62aa427b916f5841b6008e5aefd2b24766a931da77176f1cb22d1ab35af` |
