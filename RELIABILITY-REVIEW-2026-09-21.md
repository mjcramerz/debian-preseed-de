# Debian Preseed Desktop - reliability review, 2026-09-21

> **Superseded by R3 for graphics, icon size and flex storage.** See [ATOMIC-OUTPUT-ZRAM-REVIEW-20260921-r3.md](ATOMIC-OUTPUT-ZRAM-REVIEW-20260921-r3.md). The legacy-KMS policy below has been removed; drawer icons are now 24px. This document records the earlier revision, not current deployment instructions.

> **Historical R1 report.** The Foot supervisor and generated drawer-icon cache described below were removed in R2. See [SIMPLIFICATION-REVIEW-20260921-r2.md](SIMPLIFICATION-REVIEW-20260921-r2.md) for the current implementation and `VALIDATION-20260921-r2.json` for current results. R1 counts and manifests below remain historical evidence.

## Delivery and scope

This is the complete supplied repository, not a patch-only distribution. The installation payload, payload manifest and preseed digest were rebuilt together. All 3,468 original files remain present. Before adding this review and validation evidence, 49 existing files changed and seven files were added. The changes are concentrated in the requested session/power flow, panel/menu assets, installer wiring, tests and their generated payload. Original file modes are retained; archive ownership is normalized to root.

The intended installed platform is Debian Forky with systemd 261.2, as specified by the user. No vendor source was patched, no new vendor source compilation was introduced, and no global Xwayland server was added or enabled. The existing private-Xwayland implementation for Zoom and Discord, compositor isolation unit and all 13 host profiles are byte-identical to the input. Existing build recipes and application release pins are unchanged. The change manifest contains before/after hashes and the protected-file checks.

This review records implemented behavior and completed offline tests. It does **not** certify a successful boot on the target laptop, a physical reboot, live editor dialogs, or live enforcement of the target's AppArmor policy. The DRM change is an explicitly scoped mitigation, not a proven diagnosis of the GPU/driver's internal failure.

## Evidence reviewed

Inputs: the complete `debian-preseed-de.zip`, `journalctl`, `fail`, and the logs extracted from `managed.zip`. Journal line numbers below refer to the supplied standalone `journalctl`; audit line numbers refer to `managed/audit/kernel-audit.log`. Raw private system logs are deliberately not copied into this served codebase.

| Observation | Supplied evidence | Disposition |
|---|---|---|
| eDP atomic commits return EBUSY | Journal 1069 at 02:39:26; 144 occurrences overall | Exact-host legacy-KMS mitigation; hardware acceptance still required |
| wlsunset rejects `/etc/default` before its service starts | Journal 1015, 2861, 3365 | Run its strict validator outside the compositor's implicit user namespace |
| Foot services fail after window close | Journal around 1214 and 1265: client HUP/status 1; around 1515: shutdown status 230 | Supervise normal terminal close separately from genuine failures |
| Missing/collected Tomat unit aborts shutdown | Journal 3108 | Stop authoritative session boundaries, not every stale member name |
| logind cannot obtain a short-lived peer PID | Journal 2932, 2941, 2959 | Remove the PAM/machine transport from user-bus calls; no guarantee that unrelated callers can never race |
| Notification center imports Gdk without a version and loses its accessibility policy | Journal 1184-1186 | Require Gdk 3.0; retain the existing session's disabled-bridge policy in the clean environment |
| Crystal Dock cannot resolve notification-center application ID | Journal 1187 | Install matching hidden desktop metadata with a session-owned relaunch command |
| freshclam has a missing NotifyClamd target | Journal 5615 | Remove only the exact stale default directive when that default file is absent |
| AppArmor inherited-descriptor and directory-read records | Audit 3510, 3512, 3636, 3644, 3652, 3932, 3934, 8068, 11976, 12217, 13066, 13332, 13345, 13347 | Close inherited descriptors before transitions; narrowly permit the observed home-directory read |

The supplied kernel audit log begins at 02:48:26 in a later boot. It cannot establish what happened inside the kernel at 02:39:26. Nearby application launches are correlation, not proof that Thunar, Foot, or AppArmor caused the first DRM error.

The audit file contains 14 relevant AppArmor complain records: 11 `file_inherit` and three `open`; no `DENIED` records. An `ALLOWED` record in complain mode is not proof that the requested access belongs in an enforcing profile. In particular, notification/capture/brightness helpers should not need inherited rfkill, unrelated menu files, or network counters.

The `rd-sideloader`, `rd-balloon` and workload-slice messages are associated with the externally run iocost-lab/rd-agent experiment. No evidence justifies changing the installed host's I/O tuning or patching that external source tree. Tailscale shutdown/reconnect messages and intentionally unavailable global Xwayland were not treated as reasons to rewrite working unrelated policy.

## 1. Save-aware power and logout transaction

### Preparation while the compositor is still alive

The power worker first reserves the existing package locks and checks the caller/session identity, other interactive sessions and shutdown inhibitors. Existing authorization and package-lock protection remain intact.

For a desktop power/logout request, `labwc-session-state prepare` creates the existing launch-closing marker, inventories managed editor/browser services and visible Wayland windows, and records validated editor restart descriptors. When windows are present, a Fuzzel confirmation offers **Cancel by default**. The affirmative option states that browser work is saved and asks editors to close. This gives the user a chance to return to forms, downloads and documents before any close request is sent.

The implementation does not invent a universal unsaved-document flag, parse asterisks in window titles, read application documents as root, simulate Save/Discard keystrokes, or kill an editor to make shutdown progress. It sends one normal toplevel-close request. FeatherPad, FocusWriter and Gnumeric own their Save/Discard/Cancel dialogs. Remaining windows, including unidentified windows and save dialogs, block teardown. Protected managed editor/browser services must also finish, even after their windows disappear. A second quiet observation catches a late dialog before teardown.

The confirmation has a 120-second bound; the subsequent close/save wait has its own 120-second bound. A timeout cancels power/logout rather than force-killing unsaved work. Cancellation returns status 77 from the preparation helper. It is classified as a user veto, not a failed power service. Already-closed applications are not magically rolled back; the remaining desktop is left running, and the existing restart records remain available.

**Durable veto result:** the prepare instance has a narrowly scoped `RemainAfterExit=yes` drop-in. The worker clears an old result before starting preparation, reads and strictly verifies `ActiveState`, `SubState`, `Result` and `ExecMainStatus`, and only then stops the retained instance. This prevents garbage collection of an inactive successful oneshot from losing status 77 and presenting a misleading fresh-unit status 0.

### Ordered destructive phase

After successful preparation, poweroff/reboot follow this sequence:

1. Synchronously stop `labwc-session.target` and `labwc-compositor.service`. `PartOf` and existing dependency ordering propagate stops. Snapshot membership before and after the operation, then verify members have no active state, pending job, main PID or control PID. Missing collected transient units are accepted as absent, but are never passed as failing explicit StopUnit operands.
2. Complete existing optional guest shutdown hooks while their user IPC still exists. This is before the final all-user-manager boundary, not a new general root-service shutdown barrier.
3. Recheck session/inhibitor/package safety. Queue `greetd.service` stop without waiting for its root stop hook, preventing ordinary new logins while managers drain.
4. Stop all loaded `user@*.service` managers through PID 1, using their normal teardown ordering. Verify states/jobs/PIDs and recursive cgroup-v2 `populated` values. A new user manager, a live descendant, malformed or incomplete status, or failed transport cancels the forced handoff. There is no blanket early SIGKILL fallback for machine power.
5. Submit exactly one `systemctl --force --no-ask-password poweroff` or `reboot` to PID 1. Never use two `--force` options, `--no-sync`, a direct reboot syscall, a system-bus kill, or an automatic retry of an uncertain handoff.

After step 4, the code waits for no root service's normal stop transaction. One `--force` intentionally bypasses remaining ordinary root-unit shutdown ordering. PID 1 still performs its final process/filesystem shutdown work: this is not an assurance of zero kernel/storage latency. Root services other than explicitly completed guest hooks do not get their normal ordered `ExecStop` opportunity at that boundary. That is the tradeoff of the requested workaround.

The workaround avoids creating the ordinary root shutdown-target transaction while user-manager cleanup is still being driven. It does not hide log messages or disable legitimate sound/rfkill udev activation rules, and cannot promise that unrelated udev/exit races will never log a warning.

Logout remains a logout, not a forced machine power action. Suspend retains the existing lock/inhibitor behavior and is not converted into a force path.

### User-bus transport and confinement

Root now invokes fixed systemctl arguments with a direct credential-dropped child: target UID/GID, empty supplementary groups, canonical `/run/user/UID/bus`, controlled environment, closed inherited descriptors, and a private transport process group. No `--machine=user@.host` bridge or additional PAM login session is created. On timeout, only the worker's own transport process group is killed/reaped. The root service retains `NoNewPrivileges`, uses only SETUID/SETGID/KILL capabilities needed for that operation, and AppArmor limits those transport signals to the worker profile.

## 2. DRM EBUSY: targeted policy, not a source patch

`LABWC_WLR_DRM_NO_ATOMIC` accepts `auto`, `0`, or `1`. In `auto`, an exact allowlist in `LABWC_WLR_DRM_LEGACY_HOSTS` enables legacy KMS only for `LPL-264`; other hosts remain on atomic KMS. Host names are validated and matched exactly, not as shell patterns. The derived environment is explicitly set/imported and cleaned up so a stale inherited value does not choose policy.

The mechanism is wlroots' documented `WLR_DRM_NO_ATOMIC=1`, not a driver patch, source build, global kernel option, global renderer downgrade, or repeated modeset retry loop. Existing hardware profiles and the private-Xwayland path remain unchanged.

This bypasses the failing atomic path on the reported host, but the logs do not prove the underlying GPU/driver reason. Test normal display use, external monitor changes, locking/unlocking and suspend/resume on LPL-264. To revert the mitigation, set `LABWC_WLR_DRM_NO_ATOMIC="0"` in its trusted `/etc/default/labwc-desktop` (or the desired installer policy override) and start a fresh login session. Do not try to switch the DRM backend in a running compositor. To opt another host in deliberately, change the exact allowlist rather than enabling it globally.

## 3. Terminal and transient-service lifecycle

Only canonical `/usr/bin/foot` launches use the new `labwc-foot-supervisor`. The supervisor runs unprivileged, validates the trusted system executable, forwards TERM/INT/HUP to its own terminal child, and reaps it. The service uses `KillMode=mixed` so the supervisor owns graceful signaling while systemd retains the existing bounded final cgroup cleanup.

An argument-free default-shell terminal's observed window-close status 1 is treated as normal terminal lifecycle. Explicit commands/options retain nonzero command statuses. Foot status 230 is **not** globally added to `SuccessExitStatus`: without an explicit stop signal it remains a failure, as do crashes and unrelated errors. During an explicit supervised stop, the bounded set of known stop results is successful. The original return value remains visible in the informational lifecycle log.

Other applications retain `ExitType=cgroup`, session membership, the closing-marker launch gate, no unconditional restart, and their actual failure statuses. This change does not make arbitrary broken programs appear successful. Private Zoom/Discord session code is unchanged.

## 4. Native menus, panel order and hover styling

The five menus remain native Waybar GTK menus, with the existing action IDs and callbacks. Every actionable item and every submenu header uses a real themed `GtkImage` and label in a GTK box. This avoids deprecated image-menu-item behavior and avoids using text glyphs as a substitute for theme icons. Separator rows intentionally are separators, not fake actionable items.

Menu labels are 16 CSS pixels, weight 700. Selection uses brighter orange `#ff9f36` with dark readable text. The native submenu arrow node uses a properly sized themed directional arrow; left/right direction and disabled styling remain available. Icons were checked for actual theme lookup availability, not just nonempty XML attributes.

Left-side order is now:

`Main menu -> Workspaces -> Tomat -> Wayscriber -> Window switcher -> Applications`

The original single-workspace native task strip still follows the Applications group. The installer verifier was corrected to accept that intentional single-workspace suffix while enforcing the requested six-button order. Workspace color rules are unchanged.

Main-menu hover is dark amber with an amber rim/glow, not filled orange. Tomat uses dark burgundy with a muted crimson rim and does not override its state/icon foreground colors. Wayscriber uses dark blue and a blue rim/glow. Window switcher uses dark green and a green rim/glow. The Applications button has a lavender icon and a dark lavender hover with a lavender rim/glow.

## 5. Papirus-Dark drawer and bounded Tuta/Sleek icons

GTK3's CSS `-gtk-icontheme` drawing path can paint a bitmap at its intrinsic pixel dimensions because its lookup does not force scaling. A `background-size: 18px` declaration alone was therefore insufficient for 512-pixel application artwork. The real GTK test reproduced this failure before the correction.

The installer-only `labwc-stage-waybar-icons` resolves the five drawer icons against the installed **Papirus-Dark** theme using system search paths only. It explicitly requires Thunar's resolved source to come from Papirus, not the old hicolor fallback. It decodes with `FORCE_SIZE` into 72-pixel PNGs; CSS then scales these real URL images to an 18-logical-pixel display area. Tuta and Sleek use their themed application artwork rather than oversized direct vendor bitmaps. The large source files and global theme remain untouched.

The output directory is root-owned and checked component by component without following symlinks. Files are atomically published with explicit permissions; the manifest records resolved source paths. The helper runs once in the installer after applications/themes are available and before final user configuration verification. It is not a resident daemon or panel polling task. Non-software/non-amd64 variants use explicit optional-icon fallbacks rather than failing for intentionally absent applications.

After a deliberate manual icon-theme or vendor-artwork update on an existing installed machine, refresh the cache with the trusted root helper, then restart Waybar normally. The argument is `1` when the software addon is selected (normal Tuta/Sleek installation), otherwise `0`:

```sh
sudo /usr/local/libexec/labwc-stage-waybar-icons 1
systemctl --user restart waybar.service
```

Do not run that command against an incomplete theme/software installation and ignore its errors; the installer treats missing required icons as a verification failure.

## 6. wlsunset without weakening ownership checks

The reported startup failure happens before `labwc-wlsunset.service` is created: the validator sees host-owned `/etc/default` through the compositor's implicit user namespace and rejects the remapped ownership. The original strict policy/socket checks should not be weakened to accept overflow UIDs or arbitrary directories.

Autostart instead requests `labwc-wlsunset-start.service` from the user manager. This short-lived validator unit explicitly uses the host UID/PID view, is required to belong to an active session, and then calls the existing controller. The actual sunset service remains the existing managed transient service. Existing geographic/color policy, singleton and compositor-peer validation are retained. Failure is exposed in the startup unit's journal, rather than only in a compositor child log.

Useful installed-system checks are:

```sh
systemctl --user status labwc-wlsunset-start.service labwc-wlsunset.service
journalctl --user -b -u labwc-wlsunset-start.service -u labwc-wlsunset.service
```

## 7. AppArmor and inherited descriptors

`labwc-waybar-exec` shares Waybar's existing profile during the cleanup step. It accepts only the six exact configured status/watch command pairs. Before entering a narrower helper profile it closes all descriptors numbered 3 and above, enumerating the actual `/proc/self/fd` table instead of assuming a reduced RLIMIT bounds inherited descriptors. Only fixed argv is executed; no shell expansion, eval, arbitrary executable or profile override is accepted.

This removes the cause of the 11 `file_inherit` records without adding rfkill, unrelated menu, battery-type, CPU or network-counter permissions to helpers that do not need them. The observed administrative frontend home-directory read is narrowly allowed. Other new grants cover the canonical user-bus transport, its own child signals, the bounded drawer-cache PNG reads, and the preparation dialog's existing Fuzzel transition. Existing explicit denies and enforcement policy are not replaced with the installed complain-mode profiles.

All managed top-level AppArmor policy files were compiled offline against the available parser and base abstractions. This verifies syntax/include/transition consistency, not that every path on a running Forky host has been exercised. Enforce-mode acceptance must still exercise each menu, editor-save workflow, terminal and power action and review fresh target audit records.

## 8. Remaining narrowly corrected inconsistencies

The notification center explicitly selects Gdk 3.0 before import. Its clean environment now matches the existing `GTK_A11Y=none` / `NO_AT_BRIDGE=1` session policy instead of accidentally asking for an accessibility bus the session does not provide. This does not newly disable accessibility across the desktop or add another daemon; the original policy is preserved. A future accessibility-enabled deployment should change that policy deliberately and install/configure its bus as a separate change.

`labwc-notifications.desktop` matches the observed Wayland app ID. It is hidden from general launch menus but provides Crystal Dock with an icon and a valid relaunch action. Relaunch creates a session-owned transient service with cgroup lifecycle rather than an orphaned dock child.

The freshclam repair only comments the exact stale default `NotifyClamd /etc/clamav/clamd.conf` when that target is absent. A present ClamD installation, custom target or other freshclam content is retained. Trusted-directory/file checks, bounded input, atomic replacement, ownership and original file mode are preserved, including mode 0600.

Two older I/O-cost tests assumed both disk profiles enabled calibration, but the supplied dual-disk profile already sets `IOCOST_CALIBRATE_ENABLE="false"`. Only test expectations/fixture choice were corrected: the matrix now preserves the original opt-out, the staging test checks enabled-to-disabled cleanup, and the real debconf bridge test uses the already-enabled single-disk profile. No production I/O policy was changed to make a test pass.

## 9. Validation results and reproducibility

- **2,230 passed, 49 skipped, zero failed** across 2,279 test cases in 96 runnable test files. A 97th discovered file is a helper module with no test cases; its unittest status 5 is recorded explicitly, not hidden as a pass.
- **35** new reliability tests cover cancellation, durable veto state, root credential-drop transport, protected app classification, Foot signal/status behavior, descriptor closure, scoped DRM, wlsunset and notification wiring, and trusted freshclam repair.
- Rebuilt payload: **1,407 files**. Build/manifest/preseed consistency check passes.
- **59 preseed files** pass; all four generated shell-command values survive private debconf read-back unchanged.
- **285 shell files / 581 parser checks** pass.
- **37 managed top-level AppArmor policy files** compile offline; all named managed transitions and staged includes pass the integration checks.

The complete per-file test results and logs are under `validation-20260921/`. The main run used fresh processes per test module to avoid cross-module state contamination; affected modules were rerun after final review. One earlier parallel root-login test hit its 15-second fixture timeout and passed on the final lower-concurrency rerun. A complete monolithic `tools/validate.py` run is not claimed.

The real GTK3/Cairo fixtures used a disposable Xvfb display on the validation host. They verified all menu images and bold 16-pixel text, real submenu arrows and selection geometry, and drawer paint bounds at 1x/2x with 512-pixel mock vendor artwork and conflicting legacy icons. This is a real toolkit rendering test, not a screenshot of the installed Waybar session or proof that the target's Papirus package is available. No Xvfb/Xwayland changes were made to the installed-system configuration.

The current source audit inventories 1,335 files including installer/host support: 487 syntax passes, 180 unit-structure passes, 157 blocked dependency checks, 509 inventory-only entries and two templates needing their render context. The blocked checks are largely missing Perl/Moo dependencies and are not counted as passes. The 49 skipped unit cases additionally cover unavailable binaries, GI/GioUnix, historical incident fixtures and environment capabilities. Original September 21 logs were separately read and mapped above; they are not substituted for older fixtures with different expected contents.

For a fresh validation environment with the repository's declared dependencies installed, use the existing `tools/validate.py`. To reproduce an isolated module, for example:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -v \
  -s d-i/forky/tests -p test_session_reliability_20260921.py
python3 -B tools/build.py --check
python3 -B tools/check_preseeds.py
python3 -B tools/check_shells.py
```

No test in this work actually powered off the validation host, loaded an AppArmor policy into its kernel, partitioned a disk, or booted d-i. Power transport and application interactions are mocked where destructive/live behavior would otherwise be required.

## Deployment and target acceptance

Publish the **entire extracted repository atomically** through the existing installer-server deployment process. Do not combine the new preseed with an old payload or manifest, or copy only new executables while leaving old templates, units or AppArmor policy. Preserve the existing server access controls and credential-file handling. This deliverable updates future unattended installs; it is not a separately tested live-upgrade script for an already-running desktop.

Before broad rollout, complete an unattended test install on the intended hardware. Open unsaved FeatherPad, FocusWriter and Gnumeric documents together with a browser form/download. Exercise initial Cancel, each editor's Cancel, Save and deliberate Discard, and the save timeout. Cancel must leave the compositor running and must never reach the force handoff. Confirm normal Foot window close does not create a failed unit, while an explicitly launched failing command and a natural internal Foot failure retain their status. Test missing Tomat, concurrent package activity, another interactive user, pending inhibits and a deliberately slow user unit: none may bypass a failed safety gate.

After saving and closing all applications, test reboot/poweroff from the panel and the greeter. The worker journal must show desktop/compositor quiescence and verified empty user-manager descendant cgroups before the single force handoff. Check the new boot's journal and audit log for relevant failures. Observe that remaining root services intentionally do not receive normal ordered shutdown after the forced boundary.

On LPL-264, repeat display mode/monitor changes, idle lock, resume and sustained normal use with the scoped DRM policy. Confirm wlsunset's real color change and its service restart/stop behavior. Visually exercise every menu/submenu and the Applications drawer at the deployed monitor scales. Run the same actions with managed AppArmor policies enforced and inspect newly generated denials rather than converting every complain event into an allow rule.

## Primary technical references

References establish protocol/tool behavior; they are not evidence of successful execution on the user's hardware.

- systemctl, single and double force semantics: https://manpages.debian.org/unstable/systemd/systemctl.1.en.html
- systemd service lifecycle / RemainAfterExit: https://manpages.debian.org/unstable/systemd/systemd.service.5.en.html
- wlroots DRM environment policy: https://sources.debian.org/src/wlroots/0.19.3-1/docs/env_vars.md/
- Foot's own error status 230 versus child status: https://manpages.debian.org/unstable/foot/foot.1.en.html
- GTK3 icon-theme CSS renderer (lookup/drawing implementation): https://raw.githubusercontent.com/GNOME/gtk/gtk-3-24/gtk/gtkcssimageicontheme.c
- wlr foreign-toplevel close request and closed event: https://wayland.app/protocols/wlr-foreign-toplevel-management-unstable-v1
