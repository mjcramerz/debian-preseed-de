# Desktop launcher and document incidents: 2026-10-05

## Scope and evidence

The deployment target is Debian Forky with systemd **261.2**. This repair changes
installer sources and their generated snapshot. It does not apply changes to
the installed LPL-820 host or establish that its hardware freeze is resolved.

All 41 current regular evidence files were read: `todo/check`, `todo/fail`,
`todo/journalctl`, and the 38 files under `todo/managed/`. They contain 3,501,377
bytes, including 21 empty files. The review covered application, model/runtime,
kernel/system/USB/maintenance, AppArmor/audit/authentication, firewall, CrowdSec,
fail2ban, and scanner logs. Repeated events were correlated across files. Empty
logs do not establish successful scans or working integrations. The earlier
[installed-host record](installed-incidents-20261005.md) describes an older,
different evidence sample; its results remain historical.

No supplied log, host profile, private Xwayland implementation, or software
compilation recipe was changed. The ten files in `hosts/profiles/` remain the
canonical Fuzzel geometry inputs.

## Native launch and Vivaldi graphics

The missing `WAYLAND_DISPLAY` failures are explicit in `todo/fail` at 14:26:13
and 16:54:40. Native managed and generic launchers now recover an omitted value
from the current user's already-active Labwc manager:

- Validate the account, private runtime directory, and existing owned bus.
- Require both `labwc-session.target` and `labwc-compositor.service` to be
  active, using separate bounded queries. A combined `is-active` query would
  accept one active unit while the other was inactive.
- Read at most 64 KiB from the manager environment and retain only the display,
  runtime directory, session type, and Labwc owner identifiers. Each subprocess
  has a three-second timeout. The temporary capture is private and removed;
  its contents are never logged or printed.
- Require the matching native session identity and an actual current-user-owned
  Wayland socket. An explicitly malformed display or bus remains an error.

This path never guesses `wayland-0`, starts a desktop/bus, or enumerates other
compositor sockets. Private Zoom/Discord entrypoints retain their existing
requirements. The existing independent transient-service ownership, cgroup
lifetime, logout dependencies, and cleanup contracts remain.

The Vivaldi launcher previously bypassed Chromium's GPU blocklist, forced GPU
rasterization, ignored VAAPI driver checks on NVIDIA, and disabled GPU driver
workarounds on NVIDIA. Those Vivaldi overrides are removed. Native Wayland,
the managed ANGLE/GL path, and the selected Intel/NVIDIA/default mode remain.
Other browsers retain their existing arguments. Chromium documents the driver
workaround switch in its [native GL switches](https://chromium.googlesource.com/chromium/src/+/master/ui/gl/gl_switches.cc).

### What the freeze evidence does and does not establish

`todo/journalctl:1627` records Vivaldi exiting with `status=5/TRAP` at 14:17:53,
with Crashpad ptrace I/O errors nearby. The service reports a 2 GiB memory peak.
The desktop continues and Vivaldi relaunches afterward. Later entries extend
to 15:45:32, followed by the 15:56:37 boot. These are distinct observations;
the browser crash alone does not establish the cause of the forced power-off.

The supplied records identify kernel 7.2.9-x64v3-xanmod1, Intel i915 graphics,
NVIDIA 580.142, and HDMI-A-2 at 1920x1080/120 Hz with eDP-1 disabled. Atomic
commits return EBUSY repeatedly in both boots. They are not confined to initial
output configuration: the output-watch transaction succeeds, and errors recur
later. No supplied kernel panic, OOM kill, or NVIDIA Xid identifies the freeze.
The translation operation is the user's observation; the logs do not identify
its exact GPU/kernel failure mechanism.

The source already disables direct scanout and keeps its configured cursor and
GLES2 policy. No evidence establishes that disabling atomic modesetting,
changing all refresh rates, or selecting a different DRM device is the correct
repair. The new menu query reads topology without performing modesetting,
refreshing outputs, or restarting desktop components. The actual translation
operation and HDMI stability still require installed-host acceptance.

## Fuzzel geometry and monitor selection

Previously a keyboard launch without an output name selected compact DEFAULT
geometry while the compositor could place it on the external monitor. The
external Waybar supplied EXTERNAL geometry, explaining different sizes for the
same menu on that monitor.

`labwc-fuzzel` now resolves unnamed launches through the existing
`labwc-output-watch --menu-output` helper. The helper reads a bounded native
`wlr-randr` snapshot with a three-second deadline. It accepts only enabled
outputs with a valid current mode. An explicit connector or `WAYBAR_OUTPUT_NAME`
takes precedence; a named Waybar class filters the candidates. With multiple
candidates, the output at `0,0` is preferred, followed by stable connector
ordering. This is a primary-output selection policy, not a cursor/focus query.

The picker is explicitly pinned to the selected connector, and the same
installed internal-prefix policy chooses INTERNAL versus EXTERNAL geometry.
Launcher, main menu, Computer Management, and management child pickers share
their profile-owned font, padding, line height, border, width, and row settings.
The existing validator requires matching launcher/menu geometry within each
class. Profile changes propagate through the installed `desktop.conf`; the
builder does not overwrite profiles. Power confirmation retains its existing
compact confirmation layout.

A native topology-query failure stops the picker with an explicit error; it
does not silently choose laptop geometry. Existing fixtures without a Wayland
display retain DEFAULT handling. On the supplied external-only topology, both
Waybar and hotkeys select HDMI-A-2. Multiple external connectors use the same
EXTERNAL geometry; a caller requiring a particular connector can pass it
explicitly. Fuzzel's [native output option](https://manpages.debian.org/unstable/fuzzel/fuzzel.1.en.html)
supports pinning the picker so geometry and placement refer to the same output.

All five managed Waybar GTK menus now provide a `GtkAccelGroup`, including
nested submenus. Native GTK property metadata and XML fixtures validate the
references. This corrects the missing group in repository menu definitions;
the supplied assertions can also originate from vendor tray menus, and their
absence after deployment still needs a running Waybar session.

## AppArmor and document access

### Tuta attachments and downloads

The supplied nested PDF denials name **`labwc-app//app-bwrap`**, so adding only
permissions to Tuta's direct vendor profile would not repair them. The managed
parent and actual bubblewrap child now include the existing document
abstraction. Tuta's namespace exposes Desktop, Documents, Downloads, Music,
Pictures, Public, Templates, Videos, Workspace, and Syncthing read/write. Its
separate application state and desktop-integration mounts remain.

The namespace also binds only `/run/media/<current-user>`. It requires a real,
accessible parent with safe ownership/mode and rejects symlink traversal,
foreign ownership, or group/world-writable parents. Root-owned UDisks parents
authorized through a traversal ACL are supported. The installer already
creates a stable account media parent through `25-desktop-media-runtime.conf`;
the launcher does not create root-managed mountpoints. Bubblewrap uses recursive
slave mount propagation to receive host mounts without propagating mounts back
to the host; see its [native mount setup](https://raw.githubusercontent.com/containers/bubblewrap/main/bubblewrap.c).
Hotplug behavior while Tuta is already running remains a live acceptance item.

The common document abstraction also includes a new rendered account media
rule. This permits DAC-authorized reads/saves/locks on files owned by another
UID in that account's USB tree, supporting shared Linux volumes. The account
map rejects blank names, traversal, globs, reserved accounts, unsupported
characters, and names over 32 characters. Rendering is atomic; a rejected map
preserves the previous file. The additional non-owner write grant does not
match another account's media tree. DAC/ACL, filesystem read-only state, and
the namespace still apply. No execution permission or blanket home grant is
added.

### Other supplied denials and editors

- `desktop-launcher` permits read-only `user-*.journal` and `user-*.journal~`
  files in both `/run/log/journal` and `/var/log/journal`, including rotated and
  unclean-shutdown files owned by root. It does not add system-journal access or
  journal writes.
- qBittorrent now inherits its bubblewrap child profile when executing the exact
  `/usr/bin/qbittorrent` payload. This avoids the observed `no new privs` profile
  replacement denial. The child already includes `qbittorrent-runtime`; the
  namespace, no-new-privileges, dropped Linux capabilities, and direct-launch
  qBittorrent profile remain. No unconfined transition is added.
- FocusWriter, Zathura, and the shared Gnumeric/micro/FeatherPad editor profile
  already include `document-runtime` and `user-documents`. Effective native
  parser masks now verify nested read/save/lock access and account-scoped USB
  access for all these domains. FocusWriter's text-only DOCX importer gains
  the missing USB read permission. Its bounded ZIP/XML parsing, private drafts,
  and preservation of the original DOCX remain.

The installed `aa-logprof` entries contain only a generic draft-generation
failure. The source already retires the superseded distribution `msedge`
profile that collides with the managed Edge attachment. The existing native
reader regression reproduces that collision and verifies the source repair;
the exact installed stderr is unavailable, so attributing those failures to
the collision remains an inference.

## Zathura defaults

The configuration has explicit interface, theme, rendering/layout,
history/state, integration, and shortcut sections. It uses the managed text
font, the existing complete UI palette, regular clipboard selection, fit-to-width
opening, bounded page/thumbnail caches, incremental search, a larger jump list,
directory completion, and confirmed external links. Following a document link
keeps the current zoom. Normal document colors and optional recoloring remain.

Ctrl+O opens a path, Ctrl+F searches, Ctrl+0 fits width, Ctrl+plus/minus zoom,
and F9 opens the index. Native mouse selection and native bindings remain.
Bookmarks and position history retain their SQLite state; SyncTeX does not run
an external editor command. Options were checked against
[zathurarc(5)](https://manpages.debian.org/unstable/zathura/zathurarc.5.en.html).
Native Zathura/girara 2026.07.18 was available for version identification;
no graphical document session was started.

## Other reviewed entries

| Observation | Evidence and remaining requirement |
| --- | --- |
| Waypaper reports no enumerators and falls back to All | Wallpaper selection succeeds afterward. Upstream swaybg monitor selection uses screeninfo; its DRM enumerator assumes a connected connector has a usable CRTC. A disabled but connected panel is a possible explanation, not a proven root cause. The fallback remains functional; no vendor monkeypatch was added. See [Waypaper monitor selection](https://raw.githubusercontent.com/anufrievroman/waypaper/main/waypaper/options.py) and [screeninfo DRM enumeration](https://raw.githubusercontent.com/rr-/screeninfo/master/screeninfo/enumerators/drm.py). |
| Tuta `server_type_models.json` ENOENT | A missing application-state file, not an AppArmor denied read. Tuta must populate its real state; a fabricated model file would not be a correct repair. |
| Tuta scaling assertion and duplicate status notifier registration | Multiple native instances are present in the supplied session. The file access repair does not prove resolution of vendor scale/single-instance behavior. Live vendor acceptance remains. |
| Bitwarden clipboard format unavailable/empty | The message explicitly reports empty or incompatible clipboard content. No corresponding file denial establishes an installer access defect. Actual copy/paste behavior needs the vendor client and a running Wayland clipboard. |
| Bitwarden EXDEV then copy success; missing authentication state | The cross-filesystem copy fallback succeeds. Actual account login state is required; no credentials or synthetic refresh state are introduced. |
| Vivaldi missing first-run search-engine files, NoScript resources, fontconfig message | Vendor initialization and subprocess behavior remain. The managed source already supplies font paths/mounts; these records do not establish an additional font AppArmor denial. No browser database or extension security bypass was fabricated. |
| CrowdSec CAPI DNS failure, optional unenrolled console, duplicate packaged grok warnings | Local API/bouncer operations succeed. Remote DNS/connectivity, optional enrollment, and packaged parser behavior need their actual runtime/vendor configuration. |
| greetd/sudo authentication failures | The logs contain a mistyped login name and a cancelled sudo authentication. These are not evidence to weaken authentication. |
| Missing global Xwayland | The requested private Zoom/Discord arrangement remains. No global server or fallback was added. |
| fail2ban startup, firewall, Timeshift/zram, USB/firmware, scanner/model logs | Nonempty records were reviewed; no further source repair is established by these entries. Empty scanner/runtime files are not successful checks. External Codex home/plugin errors belong to the separately cloned home repository. |

## Validation

Python 3.14.7, AppArmor parser 4.1.8, Perl/Moo/MooX dependencies, GTK3 property
metadata, and Zathura/girara 2026.07.18 were available. Local systemd is **262**;
these checks do not establish runtime acceptance on target **261.2**.

The following selections ran from the repository root using
`python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests`,
followed by the listed arguments:

| Arguments | Final observed result and boundary |
| --- | --- |
| `-p test_apparmor_incidents_20261004.py` | 14 passed. Effective expanded native file masks, exact denial/NNP contracts, identity rejection, and actual scalar publication in dash/BusyBox. No policy load. |
| `-p test_atomic_output_r3_20260921.py` | 14 passed. Actual Perl method execution with disposable snapshots/process fixtures; menu query cannot modeset or restart chrome. |
| `-p test_installed_failures_20260911.py -k SessionOwnershipTests` | 7 passed. Transient service/lifecycle arguments and ownership fixtures. No manager activation. |
| `-p test_installed_failures_20260911.py -k NativeSessionBusTests` | 9 passed. Real private temporary files, 0600 mode/cleanup, explicitly mocked socket metadata and manager replies. No bus contact. |
| `-p test_native_multimonitor_20260924.py` | 25 passed. Topology/geometry/CLI/GTK XML fixtures, including changed profile values and identical visual arguments across entrypoints. No physical pixel measurement. |
| `-p test_menu_apparmor_integration_20260919.py -k AppArmorIntegrationTests` | 5 passed, including offline parsing of all 45 managed top-level policies. No kernel load. |
| `-p test_managed_app_review_20260921.py -k TutaDocumentMountTests` | 4 passed. Namespace configuration and current-user/root-ACL/malformed/absent media-parent fixtures. No real bind mount. |
| `-p test_managed_app_review_20260921.py -k ManagedArgumentReviewTests` | 8 passed, including all Vivaldi modes and removed unsafe driver overrides. No browser launch. |
| `-p test_security_incidents_20261005.py` | 10 passed. Existing Edge/native AppArmor reader collision repair and security source fixtures. No installed policy retirement. |
| `-p test_desktop_sandbox.py -k DocumentImportTests` | 19 passed. Real ZIP/XML/private-draft fixtures; original preservation and malformed/bounded input checks. No GUI editor. |
| `-p test_compz_qbittorrent_followup.py` | 5 passed. Dedicated launcher/storage/symlink/profile contracts. No torrent client or network activity. |

Seven additional tests passed using `python3 -W ignore::EncodingWarning -B -c`
with `sys.path.insert(0, "d-i/forky/tests")`,
`unittest.defaultTestLoader.loadTestsFromNames(names)`, and
`unittest.TextTestRunner(verbosity=2).run(...)`. The exact `names` were:

```text
test_desktop_sandbox.SessionAndIntegrationTests.test_zathura_selection_uses_regular_clipboard
test_desktop_sandbox.SessionAndIntegrationTests.test_docx_default_remains_focuswriter
test_desktop_sandbox.SessionAndIntegrationTests.test_new_desktop_assets_are_explicitly_staged
test_desktop_sandbox.SessionAndIntegrationTests.test_new_policies_are_staged_and_required
test_zoom_discord_private_xwayland.EnvironmentAndDisplayTests.test_unrelated_applications_keep_wayland_and_cannot_select_compatibility
test_zoom_discord_private_xwayland.EnvironmentAndDisplayTests.test_separate_outer_namespace_contains_local_x11_socket_only
test_zoom_discord_private_xwayland.EnvironmentAndDisplayTests.test_private_server_wrapper_preserves_arguments_and_has_no_fallback
```

That is **127 selected tests passed**, with no skips in these selections. An
initial combined-policy permission fixture incorrectly concatenated ABI
headers; it was corrected to parse the actual policy files separately. A named
test invocation without explicitly restoring the test import directory failed
under PYTHONSAFEPATH; the explicit loader above ran those tests successfully.
These setup failures are not reported as passing tests.

Additional final checks:

- `python3 -W ignore::EncodingWarning -B tools/build.py`: 1704 members;
  zero browser artifact changes. Packaging only, no software compilation.
- `python3 -W ignore::EncodingWarning -B tools/build.py --check`: snapshot,
  pins, and preseed current.
- `python3 -W ignore::EncodingWarning -B tools/check_shells.py`: 350 shell
  files, all 711 parser checks passed.
- `python3 -W ignore::EncodingWarning -B tools/check_preseeds.py`: all 59
  files passed; all four commands survived private debconf read-back unchanged.
- `perl -c d-i/forky/hooks/target/usr/local/libexec/labwc-output-watch`:
  syntax OK, without executing output-management actions.
- ShellCheck JSON comparison against HEAD for `labwc-fuzzel.tmpl` and
  `scripts/late/security.sh`: respectively 8 and 18 existing diagnostics,
  with no new diagnostic code/severity occurrences. Those existing diagnostics
  remain; this is not a claim that ShellCheck is clean.
- Archive comparison against HEAD: exactly 19 edited members and one added
  account-media policy template; all eight Xwayland-specific members unchanged.
  Every member is a regular file with mode 0644, UID/GID/mtime zero, and empty
  owner/group names. No extra member change was found.
- `git diff --check`: no whitespace errors.

The generated products are `d-i/forky/payload.tar.gz`, `payload.manifest`, and
`preseed.cfg`. The complete checked repository must be deployed atomically;
editing source or rebuilding does not update an installed desktop's policies
or user configuration. Earlier broad-suite failures in `BUILD-STATUS.md` were
not rerun or declared fixed.

Live acceptance must cover Vivaldi translation and HDMI stability, missing-env
native launch, menus on actual internal/external outputs, Tuta attach/save and
USB insertion while already running, enforcing qBittorrent launch, and normal
document opening/safe-save/clipboard/printing behavior. The hardware freeze,
remaining vendor/account issues, and exact systemd 261.2 runtime behavior are
unverified. No live policy load, mount, host restart, installation, or deployment
was performed.

## WIN+F and qBittorrent follow-up

The additional user-supplied audit events 1147–1150 identify the same request:
`labwc-compositor` executing `/usr/bin/env`, denied because its required profile
transition was not found. The old WIN+F and Ctrl+Alt+F bindings and the Labwc
Files menu ran `env GDK_DEBUG=nogl thunar`. The compositor's generic
`/usr/bin/* rPx` rule required an attachment for env, which is a launcher
utility rather than the final application.

The exact `/usr/bin/env rix` rule now keeps env under compositor confinement
until its final executable's normal transition. It does not add an unconfined
fallback or relax the generic payload transition rule. It also supports an
existing installed shortcut while user configuration is updated.

Both file-manager hotkeys and the Labwc Files menu now execute the same command:

```text
/usr/local/bin/labwc-wayland-app auto -- /usr/bin/thunar
```

The existing managed native launcher already applies `GDK_DEBUG=nogl` to the
exact Thunar executable, supplies the native Wayland environment, and creates
the session-owned transient service. Its startup timeout, logout dependency,
cgroup lifetime and cleanup remain. Waybar already uses this launcher and
unwraps its env assignments internally, so it does not need a compositor env
exec or another configuration change.

The repeated qBittorrent event 997 is the same no-new-privileges transition
denial addressed above. No further qBittorrent production change is needed.
The native AppArmor rule reader now independently verifies `exec_perms=ix`
and no directed target for both env and the exact qBittorrent payload rule.
The native compiler's expanded qBittorrent child mask confirms read/execute
access. These are separate checks because the compiler's ordinary debug file
mask does not include the execution-mode character. A command-construction
fixture additionally verifies `--unshare-all`, `--cap-drop ALL`,
`--new-session`, `--die-with-parent`, `--clearenv`, and the Wayland backend.
Socket availability, optional binds and GPU discovery are explicitly mocked;
no real namespace or application is started.

### Follow-up validation

All commands ran from the repository root. The same unittest discovery prefix
above was used for:

| Arguments | Final observed result |
| --- | --- |
| `-p test_apparmor_incidents_20261004.py` | 16 passed, including native rule-reader execution modes and effective qBittorrent permissions. |
| `-p test_compz_qbittorrent_followup.py` | 6 passed, including namespace/capability command construction. |
| `-p test_menu_apparmor_integration_20260919.py -k AppArmorIntegrationTests` | 5 passed, including offline compilation of all 45 managed policies. |

The explicit unittest loader described above ran these three selections;
all passed:

```text
test_log_launchers_20260915_r3.AppArmorCoverageTests.test_gtk_apps_follow_appearance_mode_and_thunar_disables_gl
test_log_launchers_20260915_r3.AppArmorCoverageTests.test_thunar_hotkeys_and_files_menu_use_the_same_managed_entrypoint
test_log_review_20260921.GenericExecBoundary.test_preparation_is_bounded_without_killing_long_running_apps
```

That is **30 follow-up tests passed**, with no skips. During test development,
an assertion assumed an unexpanded literal rule rather than the existing
brace-group rule; the assertion was corrected. The execution-mode check was
also corrected to use the installed native reader's `create_instance` API
and to distinguish execution mode from the compiler's r/x/m mask. Those
initial failed checks are not counted as successes.

The snapshot was rebuilt and `python3 -W ignore::EncodingWarning -B
tools/build.py --check` confirms current pins and products. The final native
preseed check again passes all 59 files and preserves all four commands through
private debconf read-back. `git diff --check` passes. Archive comparison now
finds 1704 members with **22 edited members and one new template** relative to
HEAD, exactly three additional member edits: `labwc-session`, Labwc `rc.xml`,
and Labwc `menu.xml`. All eight Xwayland-specific members and required archive
metadata remain unchanged. The previous 19-member edit count above describes
the initial repair, not this final follow-up snapshot.

These results establish the source and snapshot contracts. The logged host
must receive the updated compositor/application policies and user bindings;
rebuilding the repository alone does not reload its running policy or update
its home configuration. Actual WIN+F window opening and qBittorrent execution
under the installed enforcing policy remain live acceptance requirements.

## Waypaper process inspection follow-up

The user-supplied events 1429-1469 repeat nine missing `ptrace (read)` peer
grants in `waypaper//waypaper-ps`: the ChatGPT log runner, ChatGPT launcher,
ChatGPT D-Bus proxy, ChatGPT bubblewrap payload, ChatGPT slirp4netns helper,
managed application launcher and payload, and Codex wrapper and payload.
The slirp4netns event also explicitly denies the reciprocal `readby` request.

The reader now names those nine exact labels. The ChatGPT D-Bus proxy and
slirp4netns helper explicitly permit `readby` from that exact observer. The
other seven already inherit the scoped reciprocal rule through `wrapper-base`
or `desktop-runtime`; their include chains are unchanged. Only eleven ptrace
rules and one comment were added to `desktop-wrappers.tmpl`. No capability,
signal, filesystem, execution transition, or Xwayland rule was changed.

The added regression uses the native parser to expand the actual rendered
includes, separates parent and child scopes, and uses the native AppArmor
ptrace-rule reader to check both endpoints for every supplied peer. It checks
that outgoing reads retain exact peer labels and that these reciprocal grants
authorize only `readby`. Distribution `base` already supplies incoming
`readby`/`tracedby` rules; an initial test assertion was corrected to account
for those existing defaults. The corrected regression reproduced all nine
missing reader grants before the source fix, then passed after it.

Final checks, from the repository root with Python 3.14.7 and AppArmor parser
4.1.8:

- `python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_apparmor_incidents_20261004.py -v`: 17 passed, no skips.
- `python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_menu_apparmor_integration_20260919.py -k AppArmorIntegrationTests -v`: 5 passed, no skips; all 45 managed top-level policies compiled offline.
- `python3 -W ignore::EncodingWarning -B tools/build.py`: rebuilt 1704 payload members; zero browser artifact changes.
- `python3 -W ignore::EncodingWarning -B tools/build.py --check`: snapshot, pins and preseed current.
- `python3 -W ignore::EncodingWarning -B tools/check_preseeds.py`: 59 files passed; all four generated commands preserved through private debconf read-back.
- `git diff --check`: passed.

Comparison against the private pre-edit snapshot finds exactly one changed
payload member, `hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`, with no
added or removed members and unchanged deterministic archive metadata. The
existing wallpaper sources and theme selection retain their captured hashes.
The three generated snapshot products were refreshed. These are source,
expanded-policy, compiler, and disposable-fixture checks; no live AppArmor
policy was loaded and no Waypaper/ChatGPT/Codex process was started. The
installed host must receive and reload the rendered policy before live
acceptance of these process-listing events.
