# Desktop integration incident: 14 September 2026

## Delivery and validation status

This is a scoped source correction for the supplied unattended-install repository. It includes the complete original repository, updated installer payload, matching manifest and preseed pins, new regression tests, and this report. It is not an in-place upgrade of the machine that produced the logs.

**Implemented:** the demonstrated Tuta filesystem/integration faults, inconsistent mail-handler IDs, persistent private integration storage, shared private singleton IPC, notification/activation plumbing, menu-to-transient-service waiting, terminal inheritance rules, and all four classes of missing AppArmor permission in the supplied audit data.

**Not certified:** an error-free boot, real email delivery/click-through, every possible management backend operation under enforcement, or vendor/hardware diagnostics disappearing. No target Wayland session, real Tuta account, firmware, or enforcing target kernel was available. A pre-existing single-instance Thunar can still accept a folder-opening request and return before that particular window closes; its CLI supplies no per-window completion acknowledgement. This limitation is not represented as fixed.

No application, kernel, native helper, or AppArmor policy binary was compiled. The installer packaging tool regenerates an archive and checksums; the AppArmor check used names-only source parsing without loading policy.

## Evidence examined

The complete supplied `journalctl`, `apparmor.log`, `kernel-audit.log`, `systemd`, `tuta-fail`, `tuta-fail2`, `tutanota-run`, `tutanota-run-2`, and `firmware` files were inspected programmatically and relevant records traced into source. Raw machine logs are not redistributed in this patch. Existing repository content is retained.

The Tuta journal contains two independent errors:

* `EROFS` opening `.local/share/applications/tutanota-desktop.desktop`, followed by an unhandled rejection in `DesktopIntegratorLinux.askPermission`.
* `EBUSY` when GLib renames a temporary MIME file over `.config/mimeapps.list`.

The previous sandbox exposed these as read-only, individually bind-mounted files. Additional AppArmor write permission cannot make a read-only mount writable, and making an individual bind mount writable still does not permit replacing its mount-point inode. The integration blacklist under `.config/tuta_integration` also lacked persistent backing.

The service dumps show two contemporaneous Tuta transient services using the same persisted account data but private temporary namespaces. Chromium's singleton implementation uses a temporary socket and cookies; a private, shared per-user Tuta temporary directory allows its native second-instance forwarding mechanism to operate without exposing the general host `/tmp`.

The management journal shows the firmware action's menu returning before the terminal/authorization/backend completed. The supplied `firmware` output explicitly ends with `Action finished with status 0` and a prompt to press Enter. Its HSI findings are not a failed launcher.

## Tuta and desktop integration

### Persistent, narrowly writable integration

`labwc_managed_app/profiles.py` and `sandbox.py` give Tuta three dedicated host-side state directories:

```
~/.local/state/tutanota-desktop/desktop-integration/config
~/.local/state/tutanota-desktop/desktop-integration/applications
~/.local/state/tutanota-desktop/desktop-integration/icons
```

They are mounted at the corresponding sandbox XDG locations. The private `.config` parent is mounted before the genuine `.config/tutanota-desktop` account directory, so existing account data remains visible. These are directory mounts, permitting atomic replacement of `mimeapps.list`. Tuta's integration/remember-state is persistent. Host launchers and the host-wide MIME configuration are not made writable by the mail sandbox.

The private MIME file and canonical desktop entry are seeded only when absent, using validated regular files, restrictive permissions, complete temporary writes, and first-writer-wins publication. Subsequent starts do not overwrite Tuta's remembered choice. Unsafe symlinks are rejected. Existing credentials, databases, encryption state and singleton locks are not deleted. No undocumented Tuta JSON setting is invented.

A 0700 `/run/user/UID/labwc-tutanota-tmp` is reused for Tuta's temporary IPC. Existing PID/network/mount isolation and Chromium sandboxing remain in place. The wrapper, Bubblewrap context, and Tuta policy receive matching path permissions.

### Canonical handlers

The managed desktop ID is consistently `tutanota-desktop.desktop` for:

```
x-scheme-handler/mailto
x-scheme-handler/tuta
```

Both system and user defaults, desktop MIME declarations, and launcher synchronization agree. The synchronizer can use the existing root-owned, rendered `/etc/skel-desktop` Tuta entry when the vendor has no system desktop file. It preserves the managed launcher rather than publishing a direct executable that bypasses it.

The MIME repair is atomic and idempotent, preserves unrelated entries/comments, and clears obsolete Tuta removal masks for these two schemes. The old unsupported `message/rfc822=tuta-mail.desktop` association is removed; an unrelated EML handler is preserved. This change does not assert that Tuta accepts arbitrary `.eml` filenames on its command line.

### Notifications and activation

The existing filtered notification and portal routes are retained for all managed applications. Tuta additionally receives access to `org.kde.StatusNotifierWatcher`, matching Electron's Linux tray implementation. The unfiltered session bus is not exposed and no broad KDE-name ownership grant is added.

Mako keeps `actions=1`; clicking or touching invokes the application's own default callback. Tuta notifications are not grouped, avoiding replacement of distinct message callbacks by a group action. There is no generic “start Tuta” shell action masquerading as message-specific navigation. The original Tuta notification callback is responsible for selecting the correct message.

Validated, bounded `XDG_ACTIVATION_TOKEN` values are forwarded through the managed/native launch boundaries. They are not inserted into saved restore arguments. Delivery and foreground activation still require the actual client/compositor behavior to be exercised on the target. Tuta must be running, logged in and permitted to notify. This patch does not create server-side notifications after the client is fully quit, and does not force desktop autostart or alter user do-not-disturb settings.

## Computer Management lifecycle

The root Computer Management and maintenance menus request foreground action completion using `LABWC_MENU_ACTION_WAIT=1`. Managed and generic launchers translate this into `systemd-run --wait` while retaining `Type=exec`, `ExitType=cgroup`, `KillMode=control-group`, journal output and existing isolation. Ordinary desktop launches remain detached. This timing request is not an authorization or sandbox-bypass switch and is removed from payload services and restore commands.

The originating menu waits for the service, including the terminal window, instead of treating service creation as action completion. The existing nested shell menu loop then restores the same submenu. Failure, canceled authorization and terminal closure remain real results rather than being rewritten as success.

The fuzzel retry buffers the menu input once; retries no longer read an already exhausted pipe. Podman terminal actions, Remote Desktop connections/help and profile-folder launches no longer deliberately detach. Remote Desktop returns to its own menu after completed actions. Wireshark's `setsid` path now waits for its child and explicitly requests managed-launcher waiting.

Known boundary: a pre-existing single-instance Thunar may receive a folder request over D-Bus and let the new process exit immediately. Waiting on the launching process cannot identify when that reused window closes. No unsupported `--disable-server` switch, private replacement desktop bus, or termination of unrelated Thunar windows was introduced. This remains an outstanding edge case of the requested universal per-window behavior.

## AppArmor assessment and changes

The supplied complain-mode data has 10,124 missing-rule references across overlapping logs, representing 5,034 distinct policy signatures. These are not 10,124 unique denied kernel operations: all relevant entries are `ALLOWED` because complain mode was active.

| Profile/class | Distinct signatures | References | Correction |
|---|---:|---:|---|
| `managed-desktop-launcher`: `ncdu` directory reads | 5,031 | 10,062 | Directory-only `/**/ r,` in the existing file-manager/terminal domain |
| `managed-firstboot`: read-only inspection of `managed-crowdsec-firstboot` | 1 | 58 | Specific `ptrace (read)` plus reciprocal `readby` |
| `managed-labwc-security-action`: inherited terminal | 1 | 2 | PTY read/write inheritance |
| `managed-labwc-security-action-root`: inherited user-owned terminal | 1 | 2 | Same PTY rule without an incorrect owner restriction |

A new `managed-wrapper-terminal` abstraction grants `/dev/tty rw` and `/dev/pts/[0-9]* rw`. It is explicitly included in 34 relevant management/action/worker profiles, including the AI terminal menu, and explicitly staged by `scripts/late/security.sh`. Root actions need to inherit the invoking user's PTY, so the rule cannot be owner-qualified. Existing Polkit authorization and filesystem permissions still apply.

The broad-looking `/**/ r,` rule matches directories only, not every file's contents. It is confined to the existing general-purpose desktop launcher/file-manager domain and does not grant execution or writes. Read-only firstboot process inspection is peer-specific, not unrestricted tracing. Tuta and launcher synchronization receive matching permissions for their new runtime and atomic-update paths.

No global allow-all policy, global complain mode, blanket `/** rwix`, disabled AppArmor service, disabled Chromium sandbox or arbitrary root launcher was added. Covering every supplied signature and reviewing backend paths is not a proof that every future optional tool/plugin/hardware operation will succeed in enforce mode.

## Other log findings and disposition

The 88 other `success=no` syscall audit records divide into three classes: three `ss` getxattr probes returning `EOPNOTSUPP`, five systemd directory-pruning attempts returning `ENOTEMPTY`, and 80 `rm -f` unlink attempts returning `ENOENT` during idempotent secondboot cleanup. These do not indicate missing AppArmor grants. The patch does not introduce racy existence checks merely to suppress those records.

The following are not falsely presented as repaired by a desktop policy change:

| Finding | Disposition |
|---|---|
| Firmware HSI: BIOS rollback protection, pre-boot DMA, suspend policy, UEFI memory protection, unsupported hardware features, kernel taint | Genuine firmware/hardware/kernel assessment. The command completed successfully. Requires target-specific decisions; no firmware/kernel rebuild or security-policy reversal performed. |
| Labwc cannot execute host `/usr/bin/Xwayland` | Existing pure-Wayland host policy intentionally omits it. No verified runtime disable switch was established for the installed compositor. No recompilation or fake switch added. |
| Unmerged-bin layout warning | Existing installation layout; no broad filesystem migration within this incident patch. |
| Libinput touch-jump warning | Device/kernel behavior; no evidence the launcher or AppArmor can repair it. |
| Vivaldi first-run files, SVG decode and extension resource restrictions | Vendor/profile/extension behavior, not matching audit denials. Signed application and extension contents left untouched. |
| GTK scale-factor/GObject warnings, Electron Buffer/Wasm warnings | Upstream runtime diagnostics. Fixing Tuta integration and tray access is not evidence that all such messages disappear. |
| APPIMAGE missing during updater probing | Extracted application with an existing managed external-update path. No fake AppImage identity or competing updater enabled. |
| Tailscale initial profile/warming-up, Bluetooth first-run identity and netavark idle exit | Initialization/normal lifecycle records; no unnecessary daemon changes. |
| Foot SIGHUP/nonzero service result on closed terminal | Preserve real exit reporting, rather than declaring all exit code 1 results successful. |

## Offline validation

The included validation summary records the final checks. No target services, mount changes, firmware operations or enforcing policy loads were run.

| Check | Result |
|---|---|
| New incident suite | 28 passed |
| Existing installation-fixes suite | 34 passed |
| Existing lifecycle suite | 22 passed |
| Existing D-Bus suite | 16 passed |
| Existing second-pass boot suite | 6 passed |
| Existing boot-runtime suite | 8 passed, 23 dependency skips |
| Existing desktop-sandbox suite | 68 passed, 1 skip, 1 failure due to missing historical fixture |
| Existing installed-failures suite | 20 passed, 1 error due to the same missing historical fixture |
| Shell/preseed parsing | 268 shell files, 547 parser checks, all passed |
| AppArmor source parsing | 34 policy files, names-only parser, all passed |
| Installer consistency | Payload/manifest/preseed regenerated; `tools/build.py --check` passed |
| Whitespace/error-marker diff check | `git diff --check` passed |

Across the eight selected suites: **202 passed, 24 skipped, one failure and one error**. Both failing historical tests require `todo/managed/apparmor/apparmor.log`, which is absent from the original ZIP. A different incident log was not substituted and the tests were not weakened. A general discovery run was stopped on timeout; no claim of a passing full suite is made. Native compiler tests were not run.

The scope-wide inventory covers 1,194 files: 430 syntax passes, 126 systemd structural passes, 155 missing-dependency blocks, 481 inventory-only files and two templates requiring rendering. Missing Perl modules are not counted as successful Perl validation. Names-only AppArmor parsing is not kernel enforcement or compiled-policy semantic verification.

The new regression suite includes real temporary-filesystem atomic replacement tests and a real shell-menu round trip with a delayed action returning status 7. It checks that the parent remains hidden, the same Security Auditing submenu returns, and back-navigation works. Service/D-Bus launch boundary tests use mocks rather than pretending to run the target desktop.

Reproducible scoped commands, from the repository root:

```sh
python3 -B -m unittest discover -s d-i/forky/tests -p 'test_desktop_integration_20260914.py'
python3 -B -m unittest discover -s d-i/forky/tests -p 'test_installation_fixes_20260912.py'
python3 -B -m unittest discover -s d-i/forky/tests -p 'test_lifecycle.py'
python3 -B tools/check_shells.py
python3 -B tools/build.py --check
```

## Publication and target acceptance

Publish the **whole repository atomically**, not an isolated `preseed.cfg` or a few edited scripts. `payload.tar.gz`, `payload.manifest` and preseed hashes are a matched set. Existing host settings, secrets, package choices and unrelated policies were not redesigned.

For a fresh unattended install, the normal staging/rendering paths install the changes. Copying this archive to a serving host does not update the already-installed desktop. An existing-system rollout must deploy the changed target files through the normal renderer, install the new abstraction before loading the referring profiles, update the account's managed desktop/MIME/mako files, and retain existing ownership. Do not run the entire installer/firstboot workflow blindly against a working system or copy unresolved `__INSTALLER_*__` templates directly into `/usr/local/bin`.

Quit existing Tuta processes and start a fresh desktop session after deployment. Already-running processes keep their old mount namespaces and environment. Do not remove Tuta account state to clear the integration prompt.

Acceptance checks on the target:

1. Query `xdg-mime query default x-scheme-handler/mailto` and `xdg-mime query default x-scheme-handler/tuta`; both should return `tutanota-desktop.desktop`. Verify the resulting desktop Exec uses the managed wrapper.
2. Launch Tuta, complete its integration choice, quit normally, and launch twice more. Verify the choice persists, mailto links work, and repeated invocation reaches the running account rather than a second independent main instance. Check for no new EROFS/EBUSY integration errors.
3. While logged in with notifications enabled, receive real test messages. Click and touch separate mako notifications; confirm the correct message opens. Verify other desktop applications still notify. Neither static D-Bus allowances nor a synthetic notification prove Tuta's message-specific callback.
4. Navigate Computer Management through each category. Run the firmware check, leave its terminal open, and confirm no parent menu appears. Press Enter and confirm the same submenu returns. Repeat for nonzero actions, canceled Polkit prompts, terminal-close, Wireshark, Podman, Remote Desktop and nested back-navigation. Include the documented existing-Thunar edge case.
5. Validate the deployed policy with the target's own parser and audit controlled enforce-mode runs. Check new audit entries for additional capabilities/files/devices rather than globally granting everything. Preserve the original diagnostics and compare fresh timestamps.

## Primary references checked

These explain the external semantics; the uploaded logs and repository establish this incident's facts.

1. systemd-run: default start-job completion versus `--wait`, and journaling/pipe behavior: https://manpages.debian.org/unstable/systemd/systemd-run.1.en.html
2. Mako actions, activation and grouping: https://manpages.debian.org/unstable/mako-notifier/mako.5.en.html
3. Filtered D-Bus talk policy: https://manpages.debian.org/unstable/xdg-dbus-proxy/xdg-dbus-proxy.1.en.html
4. Electron Linux status-notifier tray behavior: https://www.electronjs.org/docs/latest/api/tray
5. Chromium singleton socket/cookie implementation: https://raw.githubusercontent.com/chromium/chromium/main/chrome/browser/process_singleton_posix.cc
6. fwupd Host Security ID interpretation: https://fwupd.github.io/libfwupdplugin/hsi.html
7. util-linux `setsid --wait`: https://manpages.debian.org/testing/util-linux/setsid.1.en.html
8. Thunar command-line handling and single-instance application implementation: https://raw.githubusercontent.com/xfce-mirror/thunar/master/thunar/thunar-application.c

## System desktop overrides and categorized menus: 17 September 2026

This section describes the current launcher architecture. The incident report and
its dated validation results above are historical, not results of this change.

### Responsibility boundaries, before and after

Before this change, the dpkg post-invoke helper already maintained system desktop
overrides with a common lock, atomic writes, a digest ownership manifest and a
pending journal. It rescanned and classified package entries on each invocation.
There was no root path/service trigger or persistent unchanged-source gate.
Waybar's Menu button and application-search controls both used `labwc-run`.
The separate user synchronizer maintained only its explicit managed applications.

The boundaries remain separate:

| Component | Responsibility |
|---|---|
| `labwc-run` | Search all applications, through the existing configured `labwc-fuzzel launcher` workflow. It does not parse categories. |
| `labwc-fuzzel` | Common hardened Fuzzel execution, locks, child cleanup, logging and output placement. Both menu and launcher modes reuse it. |
| `labwc-main-menu` | On-demand category selection, exact-choice validation and GIO-backed application discovery/launch. It refuses root execution. |
| `labwc-sync-application-launchers` | Selected per-user managed entries: wrappers, GPU actions, lifecycle, MIME, DBus/autostart policy. Not an application index or mirror. |
| `labwc-wrap-desktop-files` | The one authoritative root reconciliation implementation, from trusted package entries to managed system overrides. |
| `labwc-system-desktop-overrides.path` | Supplementary changes to system inputs, never user homes or generated output. |
| `labwc-system-desktop-overrides.service` | Hardened root oneshot running the same reconciler; also enabled for an initial boot check. |
| `95-labwc-desktop-apps` | Thin, synchronous final dpkg trigger: the same helper with `--post-invoke`, including in a chroot. |
| Native `menu.xml` | Separate Openbox-compatible Labwc interface with the existing custom actions. It is not Fuzzel's menu format. |

```text
PACKAGE CHANGE
  dpkg Post-Invoke -> labwc-wrap-desktop-files --post-invoke
                   -> /usr/local/share/applications

SUPPLEMENTARY INPUT CHANGES
  /usr/share/applications, /etc/default/labwc-desktop, reconciler executable
    -> root .path -> root oneshot -> same reconciler

USER MANAGED LAUNCHERS
  selected vendor/project applications -> labwc-sync-application-launchers
    -> $XDG_DATA_HOME/applications (normally ~/.local/share/applications)

MENUS
  Waybar Menu -> labwc-main-menu -> labwc-fuzzel menu --dmenu
  Search Applications -> labwc-run -> labwc-fuzzel launcher
```

### System reconciliation, ownership and crash recovery

The root helper has fixed system inputs. It never honors user XDG search paths,
walks `/home`, or edits `/usr/share/applications` in place. Read-only dpkg ownership
and Electron classification run only after the gate misses. A length-framed
SHA-256 fingerprint covers source paths/content, relevant file identities and
ownership/modes, the trusted defaults file and the reconciler implementation.
Inode identity additionally catches a same-content replacement. No date, mtime
age or package-installation-time heuristic is used. Source files are read again
after a pass; a moving snapshot is retried, not certified as final.

`/var/lib/labwc-desktop-files/source-state.json` stores this gate, the output
fingerprint and the manifest digest. The ownership authority remains
`overrides.json` plus the existing `pending.json` journal, not the cache. The
helper holds `/run/lock/labwc-desktop-files.lock` with a blocking exclusive flock
through scanning, publication, MIME database work and state commit. All trigger
paths share it; it is never unlinked on service shutdown. State is root-owned
0700/0600; new public application directories/files are 0755/0644 even under the
private service umask. Existing administrator directory permissions are not
relaxed.

Unmanaged entries are never overwritten or removed. A former generated entry
whose content or safe ownership no longer matches is preserved and dropped from
managed ownership. Output symlinks are not followed, including links into a home.
Unmanaged invalid UTF-8 data remains opaque administrator data. Only exact owned
digests are eligible for stale removal. Pending publication recovery adopts only
an exact journaled digest; an edited file is not adopted. Publication is via
private validation, fsynced temporary file and atomic rename with a final metadata
check. Temporary public filenames cannot be mistaken for desktop IDs.

`database-dirty` is a durable pre-change output fingerprint. It keeps MIME update
intent across crashes, including a crash after output publication but before
manifest commit. `update-desktop-database` runs only when effective generated
output changed; failed updates leave intent for the next run. Identical source,
output and committed ownership state is quiet: no dpkg ownership/classification,
validation, output rewrites or database command. Administrator output edits or a
missing generated output invalidate the cheap gate too. Malformed source entries
and failed validation are reported, while unrelated valid entries can proceed.
An invalid update retains its last owned, validated wrapper rather than deleting
it and exposing an unwrapped vendor entry.

A non-dpkg reconciliation commits *provisional* state. The first following final
`--post-invoke` pass must classify again even if desktop bytes match: a path event
may precede installation of executable/resources. Subsequent identical dpkg/path
invocations coalesce. A path unit is not transaction-aware, and watching a
directory is not recursive monitoring of every nested file. The final dpkg hook
therefore stays authoritative after package processing. Manual deep changes not
observed by the path watch can use `--force`.

The root path never watches `/usr/local/share/applications`, its own writer's
output. The user path likewise does not watch `$XDG_DATA_HOME/applications`.
Its existing selected-vendor, defaults and managed-autostart watches are retained.
Neither component runs a background polling daemon.

### XDG lookup, visibility and categories

GIO's `Gio.AppInfo` / `GioUnix.DesktopAppInfo` implementation owns desktop ID
calculation, nested application paths, precedence, localized names, visibility
and Desktop Entry launch expansion. Each category opening and each launch uses
a fresh short-lived worker of the same user, so a GLib process-local cache cannot
outlive the selection. Applications are not copied for Fuzzel discovery.

Lookup starts with the absolute `$XDG_DATA_HOME/applications`, defaulting to
`$HOME/.local/share/applications`, then each absolute `$XDG_DATA_DIRS` entry plus
`applications`, in the given order. Unset/empty data directories default to
`/usr/local/share:/usr/share`. Relative directory settings are ignored; an
explicit list with no absolute members searches no system data roots. A desktop
ID occurs once. The highest-precedence ID wins; a higher `Hidden=true` entry,
including a minimal tombstone, suppresses the lower version. The specification
leaves collisions between `foo-bar.desktop` and `foo/bar.desktop` within one data
root undefined; this implementation delegates that case to GIO rather than
inventing a second ID algorithm.

Only visible `Type=Application` entries are offered. `NoDisplay=true`, failing
`TryExec`, and mismatched `OnlyShowIn` / matching `NotShowIn` hide entries.
`XDG_CURRENT_DESKTOP` is respected; the session's normal value is
`labwc:wlroots`, used as a fallback only when absent. Root wrapping deliberately
retains NoDisplay/OnlyShowIn/NotShowIn/TryExec instead of applying root's desktop
or PATH. MIME-only applications still need launch isolation. Root boolean parsing
accepts exactly `true` or `false`; absent keys are not true. Hidden vendor entries
are not wrapped and stale owned overrides are removed.

`CATEGORY_RULES` in `labwc-main-menu` is the single declarative mapping. Display
order is Development, Internet, Office & Productivity, Graphics, Multimedia,
Games, Education, Utilities, System, Settings, Other. Placement priority is:
**Settings, Development, Internet, Office & Productivity, Graphics, Multimedia,
Games, Education, System, Utilities, Other.** Settings wins first; standard
additional tokens then refine broad main tokens, with the same priority among
matches. Only one display category is returned for each desktop ID.

Main tokens map `Development`, `Network`, `Office`, `Graphics`, `AudioVideo`,
`Game`, `Education`/`Science`, `System`, `Utility` and `Settings` to their display
names. Additional tokens cover the standard IDE/build/debug/database tools,
web/chat/network tools, calendar/mail/productivity, image/photography, media,
math/languages, file utilities, system/terminal and settings groups. The current
Freedesktop registry includes `ArtificialIntelligence`; it maps to Education.
No nonstandard `AI` token is invented. Examples: `Settings;System;` is Settings,
`Development;Utility;` is Development, `Network;Email;` is Office & Productivity,
and `System;FileManager;` is Utilities. Missing/unrecognized categories go to
Other. Existing project-owned Categories metadata was already standards-based;
no category-only overrides or package-owned rewrites were added.

Localized names sort by case-folded name with desktop ID as the stable tie-breaker.
Duplicate labels display their desktop IDs, with deterministic suffixes if needed.
Control characters are escaped for Fuzzel's line protocol; ordinary punctuation,
quotes, shell metacharacters, XML characters, Unicode and emoji are plain data.
The returned line must exactly match the generated choice map. Arbitrary typed
text does nothing. Escape is successful cancellation; Back returns to the main
menu and a later category opening re-enumerates current applications.

GIO launches the effective desktop ID afresh, not a reconstructed shell command.
It handles Exec quoting/field codes, working directory, terminal and DBus
semantics. Existing project-managed Exec wrappers remain effective. The Python
menu never evaluates Exec or executes a returned Fuzzel line. Its fixed desktop
actions use reviewed argv vectors, including the existing terminal, lock, logout,
power and settings helpers. Static convenience actions are not duplicate entries
in multiple application categories.

### Waybar, native menus, confinement and installation

Both internal/external Waybar Menu buttons now start `labwc-main-menu`. The
existing transient service, session Requisite/After/PartOf, app slice, cgroup
lifetime, group cleanup, collection and stop timeout are retained. The click
passes `WAYBAR_OUTPUT_NAME` explicitly to retain Fuzzel output placement.
Application-search controls/keybindings and `labwc-run` are unchanged. The session
also imports `XDG_DATA_HOME` alongside its existing XDG variables into the user
manager. All 13 desktop profiles now distinguish the menu policy from the
unchanged searchable launcher policy; their current provenance hashes are updated.

Debian Forky's reviewed `labwc-menu-generator` version is 0.2.0-3, upstream 0.2.0
with no Debian patch series. Source inspection found NoDisplay/TryExec handling
but no Hidden/OnlyShowIn/NotShowIn handling and incomplete XDG lookup semantics.
It is therefore **not installed or used** for a native pipe menu. Existing valid
native XML, custom management submenus, and its Applications search action remain.
The native menu is separate from the new Fuzzel category interface.

Waypaper's owned desktop template now renders exactly
`Exec=__INSTALLER_LABWC_WAYLAND_APP_DEFAULT_EXEC__ -- /usr/local/bin/waypaper` from
the active profile, both into the staged skeleton and the installed account.
The native Wallpaper action and categorized Desktop Settings action use the same
generic wrapper's `auto` mode. Existing `backend=none` and
`labwc-wallpaper-save --apply` integration remain: the helper atomically persists
the selected managed image and restarts the independent `swaybg.service`. Closing
Waypaper's isolated service does not own or terminate that wallpaper service.
Live wallpaper/persistence acceptance still requires a real target session.

The existing AppArmor file gains one menu profile and the root validator execute
rule. The menu has read-only application/MIME metadata access and explicit Python
GI runtime reads. GIO's fixed `gio-launch-desktop` trampoline transitions into the
existing confined desktop-launcher domain; injected GI/module/trampoline
environment overrides are removed. There is no new unrestricted execution rule
or XDG directory write grant. The system oneshot uses NoNewPrivileges, PrivateTmp,
PrivateDevices, ProtectHome, ProtectSystem=strict, explicit output/state/lock
write mounts, kernel/control-group protection, SUID/realtime/personality
restrictions, AF_UNIX only, and an empty capability bounding/ambient set. Existing
AppArmor permissions further restrict the writable `/run/lock` mount to one lock.
No syscall filter that would disrupt read-only dpkg inspection was guessed.

Arbitrary user XDG layouts are supported by discovery, but **AppArmor is still an
allowlist**: custom application roots outside the standard paths require narrow
read rules in `/etc/apparmor.d/local/usr.local.bin.labwc-main-menu` (and the
existing launcher/synchronizer local policies as applicable). The implementation
does not grant `/**` reads/writes to bypass that boundary. Custom user-sync data
roots must be user-owned, non-symlink and not shared-writable; existing custom
parents are not chmod/chowned. Root installation ignores inherited user XDG roots.

The existing desktop package selection already includes `python3-gi` and
`desktop-file-utils`; GLib introspection supplies GioUnix. No new package is
added. The late installer verifies the target GIO binding, stages the menu 0755
and units 0644, renders Waypaper, retains the existing initial direct root
reconciliation and enables both root units through the existing offline enabler.
Boot activation covers pre-existing inputs, with the fingerprint avoiding repeated
heavy work. User unit staging/enabling remains separate and unchanged. No running
systemd manager or interactive post-install setup is required in d-i/chroot.

### Diagnosis and acceptance

Run these as the indicated user; do not run the application menu with sudo:

```sh
# Desktop user: inspect effective visible IDs, localized names, source paths/categories.
labwc-main-menu --list
printf '%s\n' "$XDG_DATA_HOME" "$XDG_DATA_DIRS" "$XDG_CURRENT_DESKTOP"
systemctl --user show-environment
systemctl --user status labwc-sync-application-launchers.path
labwc-run
labwc-main-menu

# Root: force a full pass without deleting ownership or recovery state.
sudo /usr/local/libexec/labwc-wrap-desktop-files --force --post-invoke
systemctl status labwc-system-desktop-overrides.path labwc-system-desktop-overrides.service
journalctl -u labwc-system-desktop-overrides.service
```

For a missing/category-mismatched application, inspect `--list` first, then its
highest-precedence desktop file, Hidden/NoDisplay, current desktop, TryExec and
standard Categories. Validate the effective file with `desktop-file-validate`.
Check AppArmor denial logs before changing permissions. A new or removed effective
entry appears/disappears on the next submenu opening without a daemon restart;
user tombstones/overrides intentionally continue to win over system entries.

Focused regression commands are `python3 -B -m unittest discover -s d-i/forky/tests
-p 'test_system_desktop_overrides.py'` and the same command with
`test_categorized_menu.py`. Their filesystem/GIO probes are separate from a real
Wayland/systemd/AppArmor acceptance run. The [validation ledger](DESKTOP-MENUS-VALIDATION-20260917.md) delivered with this
change distinguishes real libgio C-ABI tests from unavailable Python GI bindings,
external validation tools, historical fixture failures and timed-out old suites.

References reviewed: Freedesktop Desktop Entry (file naming, values, recognized
keys, Exec); XDG Base Directory specification; Menu Specification main/additional
category registry; GLib GioUnix.DesktopAppInfo and Gio.AppInfo API documentation;
systemd.path and systemd.exec manuals; Debian Forky package metadata and upstream
labwc-menu-generator v0.2.0 `desktop.c`/`main.c`. No inference that a systemd path
watch is a package transaction boundary is made.

## Desktop navigation and pinned fonts (18 September 2026)

This follow-up retains the root override reconciler, synchronous dpkg final
pass, system path/service, selected per-user synchronization, GIO category
placement, application search and Waypaper isolation described above. The
changes below extend the UI and installer; they do not create another desktop
indexer, background menu daemon or unconfined action launcher.

### Category icons and terminal management navigation

**Historical 18 September behavior:** the glyph-only/terminal-default design
in this section is superseded by the [19 September Kanshi/Fuzzel follow-up](KANSHI-FUZZEL-FOLLOWUP-20260919.md).
The six groups, 23 allowlisted routes and action boundaries remain; default
presentation now uses graphical Fuzzel and native icon metadata. Explicit
`--terminal` still uses the terminal adapter.


`labwc-main-menu` gives every display category a distinct Font Awesome symbol:
code, globe, briefcase, image, play-circle, gamepad, graduation cap, wrench,
display, cog and grid respectively. Search and fixed desktop/settings actions
also have explicit symbols. The icon is presentation data in the exact-choice
map, never part of a desktop ID or command. Application names are not reclassified
or rewritten as category labels. Categorized menus explicitly select the graphical
Fuzzel backend, even when invoked from a terminal management action.

Computer Management now opens one existing `labwc-terminal` window and presents
six groups rather than the former eleven. It reuses the existing action programs:

| Group | Entries |
|---|---|
| System & Recovery | Maintenance & Health; Recovery & Repair |
| Network & Remote | Connection Profiles; VPN Connections; WireGuard Connections; DNS Configuration; Network Discovery; Remote Desktop |
| Security & Accounts | Protection & Firewall; Users & Groups |
| Devices & Desktop | Displays & Layout; Refresh Display Layout; Power Profile; Keyboard Layout; Audio Control; Restart Dock; Android Devices; Bluetooth Devices; Brightness |
| Containers & AI | Containers; AI & Copilots |
| Files & Documents | Documents & Media; Drives & Backups |

These are **23 distinct top-level action routes**. The duplicated former drive
management routes are consolidated. The child catalogs, action-specific
privilege checks, confirmations, lifecycle wait and logging remain in place.
AI & Copilots enters its existing `--terminal` interface in the same terminal.
Applications requiring a GUI still use their established isolated wrappers.

The 42 system maintenance actions are grouped into Overview & Health (4),
Services & Logs (9), Packages & Firmware (8), Storage & Filesystems (11),
Audio & Desktop (6), and Network & DNS (4). The 21 recovery actions are grouped
into Desktop & Services (9), Packages & Boot (5), Snapshots & Storage (2), and
Memory & Cleanup (5). Every original action is offered once in its respective
maintenance/recovery catalog; no destructive operation loses its confirmation.

The management process sets `LABWC_MENU_BACKEND=fzf` only after entering its
managed terminal. `labwc-fuzzel` delegates explicit dmenu calls to the new
`labwc-fzf-menu` data adapter in this context; its ordinary graphical launcher
and menu execution path is unchanged. The adapter owns no actions: it decorates
labels, invokes fzf, validates the returned label and restores the original data
for the caller's fixed dispatch. It strips inherited `FZF_*` options, forbids
shell-based bindings/previews and escapes terminal-control/bidirectional text.

Enter selects; Escape or Alt-Left returns one level; Exit closes the management
menu. After a child action completes, its menu returns at the same level.
Arbitrary filter text cannot become an action. Separately marked data prompts
(`LABWC_MENU_INPUT_MODE=text`) retain custom host, path, port, CIDR, container and
checksum input: Enter accepts a suggestion or unmatched query; Ctrl-Y accepts
the typed query. Existing downstream field validators remain authoritative.
An empty action list is never implicitly converted into a free-text prompt.

### Green native window-switcher button

Both Waybar variants now order their left modules as Menu, workspaces, the green
overlapping-windows button, Wayscriber, and the application drawer. A native
single-workspace taskbar, where configured, retains its existing later position.
The new button keeps the established user transient service, session
Requisite/After/PartOf, cgroup lifetime/cleanup, collection and stop timeout.

Left click runs the fixed desktop-user command
`labwc-window-switcher` -> `/usr/bin/wtype -k F13`. F13 is a normal press binding
for native `NextWindow`, with the same current-workspace and profile-selected
output/identifier policy as Alt+Tab. It does not synthesize Alt. The original
Alt+Tab and Alt+Shift+Tab bindings remain native and unchanged. The normal F13
press binding deliberately avoids an `onRelease` action: the reviewed 0.20.2
keyboard code retains its current release binding across cycle-specific keys.

**Right-click-anywhere cancellation is not implemented.** In the reviewed stock
Labwc 0.20.2 cycle implementation, ordinary configurable mouse bindings are
bypassed while cycling, and release on an OSD item selects it without a separate
right-button cancellation branch. A root mouse hook, compositor fork or fake
universal binding would not preserve the requested native behavior. Use Escape
to cancel without selecting. A right click on an OSD item must not be assumed to
cancel; it can select the item. Left-click selection and arrow-key cycling remain
native. No overlay or extra window-manager process is installed. Actual graphical
behavior still requires acceptance on the target session.

The target verifier now checks F13, both Alt+Tab bindings and the button's position
and launch contract in the rendered skeleton and primary account configurations.
`wtype` is explicitly selected by `classes/class-select/role/desktop.cfg`.

### Five profile-pinned font archives

All 13 profiles explicitly define URL/SHA-256 pairs for these archives from
`https://github.com/mjcramerz/fonts/releases/download/terminal-fonts-v0.0.1/`:

| Archive | SHA-256 |
|---|---|
| FiraCode.tar.xz | `68e3bd6164864b8b514605bc34e3a87ac401c8c48682fcce6478c70263340207` |
| NerdFontsSymbolsOnly.tar.xz | `01172f37db8543edb102e5cb5c64101c9f4686630804d49b419aa07b23a69996` |
| ProFont.tar.xz | `186917bff8fe3d7aaf6a0151e7caf76ef2962f2dd825454dc42c3c7285c8f821` |
| MicrosoftAptosFonts.tar.xz | `54f4cae474cfa96dfb30f9f39fa947959bb2fbda40aea46420299f22ff7c12aa` |
| microsoft-fonts.tar.xz | `c37f2ebeca338f0c35c19957fa0671ecdeb7ea2a8a58397e963f22c87ce32c6a` |

Profile variables are `LABWC_FONT_{FIRACODE,SYMBOLS,PROFONT,APTOS,MICROSOFT}_{URL,SHA256}`.
The late desktop module sources `fonts.sh` and calls it after user configuration
exists. It stages a repository-controlled installer helper temporarily, runs it
with a fixed clean environment and timeout, and removes the consumed helper.
The helper verifies each download before reading archive members. Release metadata
matches these pins; the actual external release bytes were not downloadable in
the development execution environment. Installation must fetch the bytes and
match the pins or fail closed. No font archives or font binaries are distributed
inside this source delivery. Administrators remain responsible for applicable
font licenses before deployment.

Fonts are published in both requested trees:

```text
/etc/skel-desktop/.local/share/icons/terminal-fonts/
$ACCOUNT_HOME/.local/share/icons/terminal-fonts/
  releases/<content-and-policy-id>/<archive-name>/...
  current -> releases/<content-and-policy-id>
  .cache-ready
```

Root's verified source cache is `/var/cache/installer-desktop-fonts/`. Downloads
use private temporary paths and HTTPS-only transfers. Archive traversal,
absolute paths, links, devices, sparse files, duplicate entries and excessive
member/expanded/archive sizes are rejected. Complete validated generations are
published atomically; a relative `current` symlink activates them. The manifest
records all archive pins and extracted-file SHA-256 hashes. A common root lock
serializes installation. Identical verified generations reuse the existing data
and avoid downloads and unnecessary cache refresh. Modified managed generations
or an unmanaged activation/configuration entry are preserved and rejected rather
than silently overwritten. Old generations are not deleted during activation.

Root owns the trusted cache and skeleton. Before the account handoff, it repairs
only the install-created `.local` and `.local/share` parent ownership using pinned
`O_DIRECTORY|O_NOFOLLOW` directory descriptors and `fchown`, never a recursive or
symlink-following ownership command. Foreign-owned or writable parents fail closed.
Publication then permanently drops supplementary groups, gid and uid. All account
font files, configuration and cache are created as that account. Generation
directories/files are 0755/0644; private stages and lock/cache markers remain
restricted. Target staging checks the manifest, fontconfig rule and ready marker.

An icons directory is not a default font source. Each tree therefore receives
`.config/fontconfig/conf.d/60-labwc-terminal-fonts.conf` containing a narrow
`<dir prefix="xdg">icons/terminal-fonts/current</dir>` rule. Fontconfig resolves
that relative to XDG_DATA_HOME. `fc-cache --force` runs for the skeleton with an
external root cache and separately as the primary account with its user cache.
Future accounts inheriting the skeleton obtain the fonts and rule; their own
Fontconfig cache can be populated normally rather than copying root's cache.

Foot and Fuzzel include `Symbols Nerd Font Mono` as a fallback; Kitty maps the
private-use icon range to that font. Existing primary font-family choices remain
unchanged. The narrow AppArmor `abstractions/fonts.d/labwc-terminal-fonts` rule
allows only reading the user's managed font tree and is explicitly staged by the
security installer. New selector/window-button profiles use existing Python,
terminal and Wayland abstractions; wtype receives only its specific temporary
keymap allowance. No XDG application-directory writes or broad AppArmor bypasses
are added.

The desktop package list now explicitly covers all requested families:
`fonts-liberation2`, `fonts-crosextra-carlito`, `fonts-crosextra-caladea`,
`fonts-noto`, `fonts-noto-cjk`, `fonts-dejavu`, `fonts-dejavu-extra`,
`fonts-noto-ui-core`, `fonts-noto-ui-extra`, and `fonts-texgyre`. Already selected
packages are not added again. Forky's `fonts-liberation2` is a compatibility
package pulling in Liberation. Existing `fzf`, `fontconfig`, `curl`, Python and
XZ support satisfy the new runtime/installer code; no new GUI framework is used.

### Diagnosis and target acceptance

```sh
# Run as the desktop account, not root.
labwc-computer-management --catalog
labwc-computer-management
labwc-main-menu
labwc-window-switcher
fc-match 'Symbols Nerd Font Mono'
fc-list | grep '/icons/terminal-fonts/'
fc-cache --force "$HOME/.local/share/icons/terminal-fonts/current"
```

On a real Forky install, check both bars, F13, both Alt+Tab directions, Escape
cancellation, management Back/action-return behavior, typed data and destructive
confirmations. Check AppArmor denial logs without relaxing profiles. Confirm fonts
in the primary account and a new skeleton-based account, and recheck Waypaper
application/persistence after closing its isolated GUI and after login. The
[follow-up validation ledger](DESKTOP-NAVIGATION-FONTS-VALIDATION-20260918.md)
records executed unit/static checks and explicit live-runtime limitations.

Source references reviewed for the new behavior:

- [Labwc 0.20.2 keyboard handling](https://github.com/labwc/labwc/blob/0.20.2/src/input/keyboard.c),
  [cursor handling](https://github.com/labwc/labwc/blob/0.20.2/src/input/cursor.c), and
  [cycle handling](https://github.com/labwc/labwc/blob/0.20.2/src/cycle/cycle.c).
- [wtype implementation](https://github.com/atx/wtype/blob/master/main.c).
- [Fontconfig configuration reference](https://fontconfig.pages.freedesktop.org/fontconfig/fontconfig-user.html).
- [Pinned release metadata](https://github.com/mjcramerz/fonts/releases/tag/terminal-fonts-v0.0.1).
- [fzf internal query actions](https://github.com/junegunn/fzf/issues/4487).
