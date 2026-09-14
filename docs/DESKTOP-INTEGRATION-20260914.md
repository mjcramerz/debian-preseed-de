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
