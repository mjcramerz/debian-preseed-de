# Debian preseed desktop: installed-session incident fixes

Date: 2026-09-13

## Delivery and acceptance status

This release contains the complete supplied `debian-preseed-de` repository, with narrow installer-side corrections and regenerated deployment artifacts. All **1,534 original regular files are retained**. The two explicit firstboot validation failures and the code-side causes represented in `Fail` have corresponding implementations and offline regressions.

**This is not a claim that the installed host has been repaired or that a fresh hardware boot has passed.** No target host, GPU, live user manager, compositor or enforcing AppArmor kernel was available here. Firmware, application-internal and authentication diagnostics are distinguished below rather than hidden or declared fixed. The final runtime acceptance gate is a new boot/session using these staged files.

No software binaries were compiled. The existing `tools/build.py` was used only to regenerate the deployment tar archive, manifest and preseed checksum pins. Existing NVIDIA sources, kernel/driver patching, prebuilt binaries, private Xwayland assets and compositor/session executables were not changed.

## Evidence reviewed

The review scanned all 82 files / 55,331 lines from `managed.zip`, `installer-state.zip`, `journalctl` and `Fail`. SHA-256 inventories are in `validation/installed-session-fixes-20260913/evidence-inventory.json`; original upload checksums are in `input-checksums.json`. Repeated AppArmor events in both the AppArmor and kernel-audit logs are duplicates, not separate incidents.

The supplied `installer-state/logs/firstboot/data/validation-results.txt` contains exactly two explicit FAIL records:

| Evidence | Finding | Correction |
|---|---|---|
| Line 186 | `desktop-nvidia-char-device-links: status=1` | Maintain aliases for existing NVIDIA character devices, including late/manual device creation; validate every expected alias read-only. |
| Line 351 | `desktop-renderer-policy` | Recognize the actual guarded export statements and the existing combined cleanup environment list. Renderer settings and the cleanup list itself remain unchanged. |
| Line 447 | `validation_status=fail failures=2` | Consequence of those two checks, not an additional independent defect. |

`Fail` lines 1 and 3 are the same firstboot failure. Lines 2 and 4–6 are the same user-session restore bus failure. Line 7 is the Waybar stop/restart status defect described below. They have not been treated as seven independent failures.

## Implemented corrections

### 1. NVIDIA device aliases without driver changes

Added `/usr/local/libexec/managed-nvidia-char-links` and the system-level `managed-nvidia-char-links.service` / `.path` units. Root scope is appropriate only for this device-filesystem maintenance operation; it does not manage desktop session state.

The helper enumerates only the supported top-level NVIDIA device names, requires root-owned character devices and protected root-owned directories, and creates relative `/dev/char/MAJOR:MINOR` symlinks atomically. It rejects symlink device entries, unsafe directories and existing non-symlink destinations. Correct links remain untouched. It does not create device nodes, open GPU devices, load/unload modules or change device permissions. Its public command line accepts no paths. `--check` performs no repairs and reports bad aliases with a failure exit code.

The boot service runs after module/device-trigger setup and before greetd/firstboot. The path unit watches `/dev` for later device entries, without polling or `PathExistsGlob` retrigger loops. The service's generic five-start limit is disabled so ordinary hotplug bursts cannot exhaust it; the path unit retains its independent trigger limit. Reconciliation modifies `/dev/char` children, not the watched `/dev` entries, apart from initial creation of the `char` directory. No `RemainAfterExit` prevents future invocations. Existing udev rules remain in place.

The assets are staged and enabled only when NVIDIA acceleration is selected. The non-NVIDIA path removes these new assets and their enablement links. Firstboot now checks helper/unit presence, active watching, and real link correctness. A machine with no matching devices still behaves as the original check did; this check is not substituted for GPU/driver availability validation.

### 2. Desktop state operations are explicitly user units

Added the account-local `labwc-session-state@.service` template and retained `labwc-session-restore.service` as an account-local user unit. Neither is installed under `/etc/systemd/system`, and neither uses system-service `User=` impersonation.

The root power worker now invokes `systemctl --user --machine=ACCOUNT@.host start labwc-session-state@ACTION.service`, with an action allowlist, instead of generating a separate state-helper transient service. Machine power authorization remains in the existing root worker; desktop enumeration, save/close preparation, clipboard handling and restoration remain inside the invoking user's manager.

Both units explicitly set `XDG_RUNTIME_DIR=%t` and `DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus`, have bounded timeouts, private umasks and control-group lifecycle handling. The helper independently validates the canonical `/run/user/UID` directory and bus socket, their types, owner and directory mode, rejects foreign environment paths and refuses root execution.

The supplied restore failure was already emitted by the user manager. Moving it to root would not address the defect. The repository's `PUx` execution rule for `systemctl` was inconsistent with systemd's secure environment lookup. It is replaced by `rix` inheritance inside the existing bounded session-state profile, with explicit user-manager socket and necessary D-Bus permissions—not by an unconfined `ux` fallback or disabling AppArmor.

Existing safety behavior remains: pending save dialogs and live application cgroups block destructive teardown; document restoration uses validated launch descriptors, not arbitrary root commands or memory snapshots. Reboot/logout preparation is not run by the offline tests against any real session.

### 3. Waybar stop/restart status remains truthful

The journal shows Waybar being stopped/restarted at the time of the reported failure, followed by a successful start. The panel supervisor had converted a child terminated by SIGTERM into an ordinary exit status 143, which systemd correctly treats differently.

The supervisor now retains the signed child status and re-raises the child's terminating signal. SIGTERM is therefore observable as SIGTERM; an actual `exit(143)` remains a failure. Fatal signals such as SIGABRT also remain fatal. AppArmor grants only the supervisor's own profile the self-signal access needed for this propagation. No blanket `SuccessExitStatus=143` or suppression of unrelated errors was added.

### 4. Panel launch isolation and descriptor inheritance

All 56 external click callbacks across the Waybar template's two bar configurations now dispatch through transient **user services**, with `Type=exec`, `ExitType=cgroup`, `KillMode=control-group`, `app.slice`, collection and explicit membership/dependencies on `labwc-session.target`. They do not use `--scope` or inherit panel standard streams through `--pipe`. The manager creates the payload process; panel-owned `/dev/rfkill` descriptors are not handed to launched applications.

Internal Waybar actions (`activate`, `minimize-raise`, `close`) remain unchanged. High-frequency volume/brightness scroll controls remain unchanged. Existing native/Electron/managed application launchers continue to create their own application services. Standalone terminal/PTY behavior and intentional administrative access are preserved; no foot server sharing was introduced.

The Waybar profile receives the specific owned user-manager private-socket permission required for the handoff. Generic app launchers receive owned PTY standard-I/O access for explicit terminal launches, rather than broad device permissions.

### 5. Observed AppArmor process-inspection gaps

The supplied events say `apparmor="ALLOWED"`: they are missing-rule reports from complain-mode execution, not proof of enforced denials or application crashes. Modes were not relaxed or changed.

Added read-only ptrace permission for the seven exact observed btop peer profiles, including the ChatGPT bubblewrap/proxy profiles and panel supervisor. Added the corresponding `readby` permission for the ChatGPT slirp helper. No ptrace trace/write permission or wildcard process peer was introduced. Inherited rfkill events are addressed at the service launch boundary, not by granting the affected application wrappers access to rfkill.

### 6. Two secondary installer diagnostics

The CrowdSec bouncer package install receives `LC_ALL=C` only in that child package-maintenance command. This avoids the observed unavailable target-locale warning without changing the user's desktop locale or host locale configuration.

The network collector labels networkctl status `NOT_APPLICABLE` only when systemd-networkd is both inactive and explicitly disabled/masked. This matches the supplied host, whose active network services are recorded separately. The state queries are bounded. A failed backend, an enabled-but-inactive backend, or an unknown state still invokes the original diagnostic and retains its failure status. No network backend was enabled, disabled or replaced.

## Diagnostics intentionally not represented as repaired

| Diagnostic in the supplied evidence | Disposition |
|---|---|
| Labwc cannot find public `/usr/bin/Xwayland`, then continues | Public Xwayland absence is intentional under the requested policy. No public package, binary, path, environment, compositor switch or private Discord/Zoom compatibility code was changed. This log message can remain. |
| ACPI `AE_AML_OPERAND_TYPE`, `ADBG` / `HIDD._DSM`; RMI register descriptor warning | Firmware/kernel/device diagnostics. No evidence supports a safe installer-only correction; no speculative ACPI flags, kernel parameters or driver patch was applied. Remain unresolved at hardware level. |
| Foot's missing XDG bell protocol | Client/compositor capability notice. No compositor rebuild or protocol-emulation change was made. |
| Bitwarden EXDEV hardlink messages | The application explicitly reports its copy fallback across filesystems. Isolation/mount boundaries were not weakened to make hardlinks succeed. |
| Bitwarden `sshagent.clearkeys` has no handler | An application-internal IPC failure. It is not proven to be repaired by these installer changes; the bundled vendor application was not modified. |
| ChatGPT HTTP 401 with `hadToken=false`, missing telemetry identity and deprecated endpoint messages | Authentication/application/service diagnostics. No credentials were fabricated, no authentication bypass or unsafe Electron flags were added, and no successful sign-in is claimed. |
| Tailscale initially stopped/warming up; later PollNetMap unexpected EOF | Initial connection recovery is visible; the later EOF alone does not establish a local firewall defect. No speculative network-policy change was made. Continued recurrence requires target-side observation. |
| Initial Bluetooth identity-file message | Missing persisted first-use state, without evidence of persistent failure. No fabricated identity or device state was installed. |
| mkfs.fat CP850 conversion warning | The next line explicitly says it uses its internal CP850 table, and formatting continues. No storage recipe or formatter change was justified. |
| AppArmor reload while target packages are installed in a chroot | Installer-stage context; post-boot validation records loaded profiles. No profile enforcement was bypassed to suppress a chroot reload message. |
| Selected CUDA-legacy authentication exception; partition alignment tolerance; no installer USB EFI for MOK sync | Explicit existing policy or detected installer-media/hardware conditions, not new repairs. These messages and their security implications remain visible; policies are unchanged. |

## Validation results and limits

The authoritative outputs are in `validation/installed-session-fixes-20260913/`.

| Validation | Result |
|---|---|
| Focused session, application isolation, power, keyring and process-lifecycle regressions | **97 passed**, including **23 new incident regressions**. |
| Additional desktop, D-Bus and process-capture selection | **148 passed**, **1 skipped** (`rsyslogd` unavailable). Two historical incident tests are explicitly excluded because their original `todo/` log inputs were not in the supplied source ZIP. The current incident was not substituted for different historical evidence. |
| Shell parsing | **267 files / 545 parser checks passed**. |
| Preseed validation | **59 files passed**; all four generated command values survived private debconf read-back unchanged. |
| Deployment payload | **1,261 files**; archive, manifest and preseed pins regenerated and `tools/build.py --check` passed. |
| New/changed state and device units | **4 units passed** offline systemd-analyze verification with fixture executable/dependency paths. No actual unit was started. |
| Changed AppArmor policy files | **3 files preprocessed successfully**, without policy compilation or kernel loading. The container's missing kernel interface warning is retained in the log. This is not enforcement validation. |
| Broad source inventory/syntax audit | 429 syntax checks passed and 123 unit structures passed; 155 checks blocked by missing dependencies, 480 inventory-only items and 2 unrendered templates are explicitly **not** counted as passes. |

Two attempts at the unpartitioned tools suite exceeded the execution time limits; neither is claimed as a completed pass. The final completed scoped selections above are the reported test results. Compiler-dependent and hardware integration suites were not run. The legacy terminal test was corrected to expect the existing `auto` mode; terminal runtime source was not changed. Power tests now assert the actual named user-unit handoff and retain teardown-abort checks.

NVIDIA regression cases operate on real temporary directories and symlinks with synthetic character-device metadata. They do not create devices or test a real GPU. Panel tests use real subprocesses and signals to distinguish SIGTERM, SIGABRT, exit 7 and exit 143. Renderer tests execute the actual validation function against the real source templates in a temporary filesystem, including negative cases. User-bus tests validate rejection behavior using mocked identity/socket metadata.

## Publishing and target acceptance

Publish the **entire repository atomically**, including the regenerated `d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg`. Do not mix these files with an older served tree.

This repository update does not hot-patch the existing installed host. On a new unattended installation the existing staging/account setup installs the changed assets and copies the user units into the managed account. `/etc/skel-desktop` alone does not update an already-existing home directory. Any existing-host application must include the corresponding account-local unit/config files as well as root-owned helpers, policies and system units; do not run the session helper as root.

After the updated installation and desktop login, inspect as the desktop user:

```sh
systemctl --user cat labwc-session-state@prepare.service labwc-session-restore.service
systemctl --user is-active labwc-session.target
systemctl --user --failed
journalctl --user -b -u labwc-session-restore.service -u waybar.service
systemctl --user list-units --type=service --all
```

On an NVIDIA-selected host, inspect as administrator:

```sh
systemctl status managed-nvidia-char-links.path --no-pager
journalctl -b -u managed-nvidia-char-links.service --no-pager
/usr/local/libexec/managed-nvidia-char-links --check
```

Launch representative terminal, native, Electron and managed applications from both the menu and panel. Inspect their actual unit `ControlGroup`, `ExitType`, `KillMode` and `PartOf` values and confirm that stopping/restarting Waybar does not terminate them. Exercise save/cancel/logout/restore only with disposable documents: a Save dialog must block teardown, cancellation must keep the session usable, and restored apps must again be owned by user services. Inspect new AppArmor events under the installed policy mode. Do not clear failed-unit history or erase logs as a substitute for testing.

Fresh target acceptance remains outstanding until these checks, firstboot validation and the hardware/application-specific observations are collected.

## Primary technical references

These references explain mechanisms, not proof of behavior on the supplied host:

- Debian/systemd `systemd-run(1)`: clean manager-owned service execution versus inherited scope execution, `--user`, `--machine`, `--pipe`, `--expand-environment`. https://manpages.debian.org/trixie/systemd/systemd-run.1.en.html
- Debian/systemd `systemd.service(5)`: cgroup lifetime and distinction between normal termination signals and numeric exit statuses. https://manpages.debian.org/trixie/systemd/systemd.service.5.en.html
- Debian/systemd `systemd.path(5)`: path triggers, immediate checks and rate-limit behavior. https://manpages.debian.org/trixie/systemd/systemd.path.5.en.html
- Debian/systemd `systemd.exec(5)`: API filesystems excluded from `ProtectSystem=strict`. https://manpages.debian.org/trixie/systemd/systemd.exec.5.en.html
- Debian/AppArmor `apparmor.d(5)`: execution inheritance and secure environment transitions. https://manpages.debian.org/trixie/apparmor/apparmor.d.5.en.html
- systemd source, `bus_connect_user_systemd`: `secure_getenv` use for the runtime directory and session bus. https://raw.githubusercontent.com/systemd/systemd/main/src/shared/bus-util.c
- NVIDIA-owned issue concerning missing NVIDIA device aliases: https://github.com/NVIDIA/nvidia-docker/issues/1730
