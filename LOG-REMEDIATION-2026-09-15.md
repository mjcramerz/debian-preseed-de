# Log-driven remediation - 15 September 2026

> Follow-up release: `LOG-FOLLOWUP-2026-09-15.md` supersedes the Spotify output-supervision assurance and validation totals below. This report records the first delivery.

## Delivery and validation boundary

This is the complete supplied `debian-preseed-de` repository with scoped corrections for the September 15 incident. All 1,867 original files/symlinks are retained, with their original types and modes. There are 10 modified implementation/configuration files, four new application-scope drop-ins, one new regression-test file, and three regenerated distribution files (`payload.tar.gz`, `payload.manifest`, `preseed.cfg`). Review documentation and validation results are additional files, not installed runtime components.

The changes address the demonstrated source-level failures. This is **not certification of a clean boot on the target laptop**, a kernel AppArmor enforcement replay, or proof that every upstream/hardware warning has disappeared. No kernel, compositor, application, or package was compiled. The repository's existing packaging generator was used only to refresh the payload and checksum pins. No installer, host service, firewall, kernel policy or target disk operation was run in the validation container.

The incident logs are inputs, not deployment content: no uploaded incident logs were copied into the delivered tree. Original repository files, including original historical documentation and configuration, remain intact. Handle the complete archive with the same confidentiality as the original installer repository.

## Evidence examined

The review covered `apparmor.log`, the extracted `installer-state.zip`, `logs.zip`, and the nested installer/managed-log ZIPs, including the user/system journals, individual application/unit captures, firstboot validation output and kernel warnings. The scan traversed 139 text/evidence files including duplicates. Repeated copies of the same audit event were deduplicated before counting; matching words in ordinary options such as `errors=remount-ro`, successful checks and inactive-condition messages were not treated as failures.

The user journal records six distinct failed application-service instances: three Foot instances whose child shells received HUP, two Timeshift instances reporting `pkexec must be setuid root`, and one Spotify second-instance handoff returning 1. The firstboot log separately records exactly one failed validation component: `managed-git-account-metadata`.

Source locations below are relative to `d-i/forky/`. `TARGET` means `hooks/target`; `PACKAGE` means `TARGET/usr/local/lib/python3.14/dist-packages/labwc_managed_app`.

## Implemented changes

### Firstboot: install the configuration that the validator requires

**Evidence:** `installer-state/logs/firstboot/20-firstboot.log` reports `managed-git-account-metadata status=1`, then `validation_status=fail failures=1`. `data/validation-results.txt` identifies the missing account-side Git metadata. The skeleton had been prepared, but the account copy list omitted both Git configuration directories.

**Change:** `scripts/desktop/components.sh`, `desktop_install_user_config()`, now includes `.config/git` and `.config/gitops` in the existing copy/ownership/permission path. The existing private directory mode 0700, file mode 0600, account ownership and single-link checks are retained. The firstboot validator itself is unchanged; missing or unsafe files still fail.

**Test:** The new regression executes the production copy loop in a disposable home and checks contents, UID/GID and modes. A second test executes the actual firstboot metadata-check shell body: complete metadata passes; missing files, symbolic links, hard links and mode 0644 replacements fail. Fixture key files contain dummy text; no real key generation or decryption is performed.

The earlier `PASS failed-units-absent` entry is a snapshot taken before this later validation failure caused firstboot itself to fail. It does not contradict the eventual firstboot failure and was not changed to hide it.

### Tuta: allow ownership of its own tray item, not the whole bus

**Evidence:** `logs/tuta` and `logs/journalctl-user` show failure to own `org.freedesktop.StatusNotifierItem-2-1`. Existing proxy policy allowed talking to `org.kde.StatusNotifierWatcher`, but not claiming the application's item name.

**Change:** `PACKAGE/profiles.py` adds a Tuta-only ownership tuple containing exactly `org.freedesktop.StatusNotifierItem-2-1`. The existing private PID namespace places the main application at PID 2; this is also the PID in both logged launches. Session-bus filtering, required proxy readiness, secret-service access, UPower filtering and private process isolation remain in place. No `org.freedesktop.*` ownership, watcher ownership, unfiltered bus, or X11 access was added.

The proxy distinguishes TALK from OWN and supports only dot-suffix namespace wildcards, not shell-style `Item-*-*` matching [U1]. This is why the fix does not use a misleading hyphen wildcard. The permission is deliberately tied to the observed single-item naming contract. A future Tuta version that changes its PID/serial naming needs a corresponding targeted policy review, not a blanket ownership grant.

**Test:** The regression checks the actual proxy-argument construction and preserved bus restrictions. A live Tuta/proxy/Waybar tray exchange was not available in the container and remains a target acceptance test.

### Timeshift: retain host authorization rather than a private user namespace

**Evidence:** Both Timeshift transient services exit 127 with `pkexec must be setuid root`.

**Change:** `PACKAGE/generic.py` treats only the canonical `/usr/bin/timeshift-launcher` Wayland launch as a host-administration command, alongside the pre-existing interactive-terminal exception. It omits the three user-service namespace properties `PrivateTmp=yes`, `PrivateIPC=yes` and `ProtectSystem=full` for that command. Those sandbox features can implicitly require a user namespace in a user manager [U2], which is incompatible with obtaining host-root credentials through this launcher.

Polkit authorization remains required; there is no root auto-launch, password bypass, setuid chmod, global policy relaxation, exit-127 suppression, or general exception for similarly named executables. Per-launch service ownership, `ExitType=cgroup`, session dependencies, control-group killing and stop timeout remain. Normal desktop applications retain these namespace properties.

**Test:** Exact-path and launch-kind positive/negative tests, plus preservation of authorization/lifecycle properties. Actual GUI authorization and root-side Wayland presentation still require the target session.

### Foot: classify the logged default-shell close without masking command failures

**Change:** `PACKAGE/generic.py` supplies `SuccessExitStatus=1` only for the exact bare `/usr/bin/foot` Wayland invocation, with no explicit command or flags. The logged status 1 immediately follows the default shell receiving HUP. Foot documents its own internal failure as 230 and otherwise reports its child status [U3].

Explicit commands (`foot -e ...`, positional commands), other terminal executables and internal failure 230 remain failures when appropriate. This is an exit-classification change, not a repair to Foot itself. A manually entered `exit 1` in that bare interactive default shell is also classified as normal; exit status alone cannot distinguish it from the logged HUP case. No global `SuccessExitStatus=1` was added.

### Spotify: recognize only a verified second-instance handoff

**Evidence:** Two launches occur in the same second; the second prints `Opening in existing browser session.` and returns 1 while the original instance remains running.

**Change:** `PACKAGE/cli.py` adds a Spotify-only supervisor. It maps status 1 to success only when that exact complete output line is observed and no stop signal is pending. Other status-1 failures, other error codes, execution errors and signal exits retain failure semantics. Standard output/error are merged into the existing journal stream, with bounded marker buffering; oversized lines or substrings do not qualify.

The supervisor forwards HUP/INT/TERM to the tracked process, escalates after 15 seconds within the existing 20-second unit stop budget, reaps it on abnormal supervisor exits, and does not wait indefinitely for a descendant to close an inherited output pipe. Corresponding narrowly paired signal rules were added between `managed-labwc-managed-app` and `spotify` in `managed-desktop-wrappers` and `usr.bin.spotify`.

**Tests:** Real disposable child processes cover the exact marker, false positives, genuine failures, partial/no-newline output, large output, retained descendant pipes, missing executables and signal forwarding. Spotify itself was not run in the container.

### Native Chromium/Electron scopes: bind application-created scopes to logout

**Evidence:** `logs/vivaldi-service`, `logs/vivaldi-scope` and the user journal show Chromium's native scope creation; the journal also records Code, Chromium and Bitwarden scope names. Chromium can request its own transient scope and move its main PID [U4].

**Change:** Four exact dash-prefix scope drop-ins are staged from the desktop skeleton and copied into the user's existing systemd configuration:

```
app-com.vivaldi.Vivaldi-.scope.d/50-labwc-session.conf
app-code-.scope.d/50-labwc-session.conf
app-org.chromium.Chromium-.scope.d/50-labwc-session.conf
app-bitwarden-.scope.d/50-labwc-session.conf
```

They add `Requisite=`, `After=` and `PartOf=labwc-session.target`, plus control-group killing, a 20-second stop timeout and SIGKILL escalation. Dash-prefix drop-in lookup and `PartOf=` propagation are documented systemd mechanisms [U5]; the scope timeout directive is present in systemd's scope parser [U6]. No broad `app-.scope.d`, fake Snap/Flatpak environment, invented Chromium flag, or blanket D-Bus restriction was introduced.

This fixes **session lifetime association**, not Chromium's design of migrating to a separate scope. It does not promise that every native application always stays in a single launcher-service cgroup. Service-only stop behavior and logout cleanup must be checked on the installed user manager. The new fixtures verify exact scope coverage and execute the production staging loop; they are not a running-systemd scope test.

### FocusWriter and RetroArch desktop consistency

The FocusWriter theme's comma-containing `Font` value is now quoted as one QSettings string in `TARGET/etc/skel-desktop/.local/share/GottCode/FocusWriter/Themes/managed-word.theme`. The unquoted value was interpreted as a list, while FocusWriter reads a string for `QFont::fromString`, explaining the empty-font warning [U7]. The font selection itself is unchanged.

`TARGET/usr/local/bin/labwc-sync-application-launchers` now searches `com.libretro.RetroArch.desktop` before the legacy `retroarch.desktop`. The installed binary was valid, but launcher sync repeatedly reported RetroArch missing. The current Debian file list uses the former ID [U8]. Both current and legacy discovery paths have executable fixture tests. No RetroArch package or runtime settings were changed.

## AppArmor: every observed gap family accounted for

The primary log contains 16,906 raw ALLOWED access records, with three exact repeated records. Deduplicating audit identity plus security-relevant fields, including PID/credentials, yields **16,903 unique access records**: 16,012 file, 783 capability and 108 ptrace records. Copies in the other archives add no distinct access records. All are complain-mode ALLOWED events; the recorded `denied_mask` still indicates missing policy. Normal STATUS load/replace events are not access failures.

| Observed family | Unique records | Scoped correction or existing intended policy |
| --- | ---: | --- |
| Thunar executing `xarchiver.tap` | 3 | Add exact `/usr/lib/thunar-archive-plugin/xarchiver.tap rix,` to `managed-desktop-launcher`. The sibling directory was not covered by `/usr/lib/thunar/**`. |
| Descendants of the resulting empty/null learning profile | 16,773 | Removing that first missing transition allows xarchiver/compression tools to use the existing launcher permissions. Bubblewrap still transitions into the existing `application-bwrap` child, whose shared namespace, file, capability and ptrace policy is retained. Do not generate thousands of permissions for null profiles. |
| Terminal mail-spool read | 1 | `owner /var/mail/* r,` in the launcher only. |
| FocusWriter process metadata | 120 | Owner-only reads of `/proc/[0-9]*/{cmdline,stat}` in `managed-focuswriter`. |
| FocusWriter Qt color configuration | 1 | Read-only `/usr/share/qt6ct/colors/{,*.conf}` in that profile only. |
| GnuPG lock hard links | 2 | Add only link permission for `.gnupg/{.#lk*,pubring.kbx.lock}` in `managed-labwc-ssh-key-load`; retain existing key-data permissions. |
| Discord command inherited PTY | 1 | Owner PTY read/write in `managed-labwc-discord-command`. |
| Compatibility launcher inherited PTY | 1 | Owner PTY read/write in `managed-labwc-managed-wayland-compat-app`. |
| Zoom command inherited PTY | 1 | Owner PTY read/write in `managed-labwc-zoom-command`. |

The cascade includes xarchiver, zip, unrar-free, lrzip, zstd, rm, cpio and Bubblewrap/glycin. Its capability records are Bubblewrap's existing namespace mechanics (`setpcap`, `sys_admin`, `sys_ptrace`, `net_admin`), not evidence that every desktop process needs those capabilities. The existing base abstraction already supplies ptrace `readby`; no redundant broad grant was added.

All six affected top-level profile families are represented in the table. The finite evidence classification is saved in `validation/log-remediation-20260915/apparmor-evidence-summary.json`. The inherited-policy reasoning and source parser checks are not a replacement for enforcement replay. In particular, the kernel log reports suppressed audit callbacks, so unseen operations cannot be certified from this capture.

No profile was globally disabled or switched to complain mode by this patch. No blanket filesystem, capability, D-Bus or unconfined-execution grant was added. Existing broader developer-launcher policy was retained, not redesigned.

## Xwayland preservation

The private Xwayland installer, both compatibility runtime Python modules, the private Zoom/Discord runtime entrypoint, and the separate Discord/Zoom application profiles are byte-for-byte identical to the upload. The three direct-execution guard profiles for Xwayland, cage and xkbcomp are also byte-identical. The compatibility allowlist remains exactly Zoom and Discord.

The only edits touching their command-wrapper profiles are the owner-PTY permissions shown above. No host Xwayland binary, global DISPLAY, additional X11 socket exposure, package rebuild, private-runtime replacement or compositor-wide Xwayland enablement was introduced. The main compositor's complaint about missing `/usr/bin/Xwayland` is deliberately not "fixed" by exposing it globally.

Hashes and comparisons are in `validation/log-remediation-20260915/xwayland-preservation.json`.

## Other logged diagnostics: disposition, not hidden success

| Diagnostic | Disposition |
| --- | --- |
| DRM HDMI-A-2 atomic commits report `Device or resource busy`; NVIDIA reports no compatible format | Still requires target graphics/driver investigation. The capture does not establish a safe source-only remedy. No modesetting flags, kernel or driver versions were changed. |
| ACPI `AE_AML_OPERAND_TYPE`, `\\ADBG`, HIDD `_DSM` | Firmware/kernel interaction remains unverified. No fabricated DSDT, ACPI override or unrelated kernel workaround. |
| MMIO Stale Data CPU warning with SMT enabled | A real residual security warning, not a harmless success message. No change to SMT or mitigation policy without an explicit hardware/security decision. |
| SGX/TDX unavailable, HPET address/IRQ unavailable, empty firmware TPM log area | Hardware/firmware capability diagnostics; no supported repository fix established from this evidence. |
| NVIDIA proprietary/out-of-tree taint and lock-debug disabling | Driver characteristics remain; no claim of an untainted kernel. |
| Resource sanity checks, RMI register descriptor warnings, Bluetooth coded-PHY mismatch | Target firmware/driver diagnostics remain. Do not grant unrelated AppArmor permissions to suppress them. |
| Dummy SPI regulator and deferred ASoC parent binding | Initialization diagnostics; no associated failing managed service established. |
| Overlayfs index/xino fallbacks under Podman capability-probe directories | Capability negotiation/fallback messages, not proof of a failed container service. No filesystem redesign. |
| Tuta GTK scale-factor assertion | May be associated with tray initialization, but its disappearance is not proven by the ownership fix. Target replay required. |
| Tuta Buffer/WASM notices and missing APPIMAGE variable | Application/runtime notices in the managed extracted-AppImage deployment. No invented environment value or vendor patch. |
| Vivaldi search-engine JSON reads, SVG favicon decode and NoScript extension-resource denial | Vendor/profile/extension diagnostics remain unverified. No fake JSON files or weakening of extension resource restrictions. |
| Code reports unknown flags while explicitly passing them to Electron/Chromium | Wrapper diagnostics; no removal of security/graphics options solely to silence the message. |
| Bitwarden native-messaging hard links return EXDEV, then copy instead | The log explicitly records the intended copy fallback across filesystems. No need to alter mounts or key permissions. |
| Spotify indicator deprecation notice | Upstream deprecation, not the recorded transient-service failure. |
| `unrar-free: Archive not specified` during xarchiver initialization | Consistent with compressor/tool probing. No archive-operation failure is established by that no-argument message alone. Runtime archive testing is still required after the AppArmor change. |
| Sudo incorrect password/cancelled conversation | Authentication failure remains a failure. No password or Polkit bypass. |
| `pam_systemd(sudo-i)` cannot inspect `/run/user/0/bus`, "ignoring" | Retained warning; the supplied sequence subsequently opens root sessions. No public root bus or speculative PAM changes. |
| Tailscale stopped/starting health, initial log/profile/interface cleanup warnings; initial Bluetooth identity absence | Initial-state messages followed by service progress in the supplied logs. No evidence justifies forcing enrollment or deleting state. |
| AppArmor reload unavailable inside the installation chroot | Not evidence of a syntax failure on the installed host: the boot capture subsequently loads the managed profiles. Live policy reload remains part of acceptance. |
| FAT codepage 850/UTF-8 conversion warning | Installer-environment warning retained; the ASCII-labeled filesystem is created and later mounted/validated. No speculative locale-package changes in d-i. |
| CUDA legacy archive authentication/date-check exception | Existing explicit archive-class policy retained. It remains a security tradeoff and is not reclassified as fully authenticated. |
| Swap size slightly below nominal, within existing partman alignment tolerance | Existing bounded tolerance, not a failed storage check. No repartitioning changes. |
| Optional installer USB/EFI unavailable for MOK synchronization | Missing optional medium; no invented device or forced enrollment. |
| Workspace-local task strip omitted in the no-broker configuration | Existing intentional no-broker behavior; no compilation or restoration of an unrelated broker. |
| Skipped unit conditions, successful filesystem checks, nftables accept records, empty timer logs | Not failures by themselves. Empty logs do not certify that future scheduled tasks have run successfully. |

## Validation results

**Targeted regressions:** 23 tests pass, including production account-copy and firstboot-check shell fragments, real temporary Spotify child processes, proxy argument formation, exact-path namespace exceptions, desktop-file discovery, scope staging and scoped AppArmor-source assertions. See `regression-tests.log` in the validation directory.

**Source/configuration checks:** 34 managed top-level AppArmor policy files parse, enumerating 230 profiles. This used `apparmor_parser --names --skip-kernel-load --skip-cache` against a disposable include overlay. No policy was installed into a kernel. The container parser emits an expected unavailable-kernel-interface warning; that is not counted as a target runtime test. All 277 shell files pass 565 selected shell-parser checks. All 59 preseed files pass, including actual private debconf read-back of the four generated command values. The distribution build/check reports all 1,290 payload files and pins current.

The wider syntax inventory reports 442 passes, 130 systemd structure checks, 489 inventory-only entries, 155 dependency-blocked entries and two templates requiring rendering. Dependency-blocked Perl checks are **not** passes. The container lacks parts of the target Perl module set, including Moo. A static structure check does not establish live systemd behavior; an attempt to instantiate a static `.scope` with `systemd-analyze verify` was not a valid runtime-scope test and is not reported as a pass.

The initial broader run examined 46 test-bearing modules plus one helper-only module: 1,152 tests, with 26 skips. It was not fully green. Original missing historical raw-log fixtures, unavailable runtime dependencies and legacy test-contract mismatches were retained rather than manufactured away. Comparative and isolated retest details follow in the supplementary validation note below. The new regression file was subsequently extended from 22 to 23 tests and rerun successfully; these independent runs must not be added together as unique test counts.

## Deployment and acceptance

Publish the **entire repository atomically**, including the regenerated `d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg`. Do not combine the new scripts with the old payload or pins. The archive is an installer-server codebase; extracting it does not retrofit or repair a machine that is already installed. Do not rerun destructive installer phases on the current laptop as an update procedure.

On a disposable acceptance installation using the same classes and hardware, record a fresh boot/session before treating the incident as closed. Useful non-destructive inspection commands are:

```sh
systemctl --failed --no-pager
systemctl --user --failed --no-pager
journalctl -b -u firstboot.service --no-pager
sudo /usr/local/libexec/apparmor-managed-modes-run --check --check-loaded
sudo journalctl -k -b --no-pager | grep 'apparmor='
```

The mode check validates the configured modes; it does not itself switch complain profiles to enforce or prove workload coverage. Enforce-mode acceptance requires loading the reviewed profiles according to the existing managed mode policy and rerunning the actual workloads in a recoverable test session, with fresh application processes rather than old null-profile descendants.

Acceptance must include firstboot completion; Tuta tray creation/menu/notifications and secret-service access; FocusWriter launch/theme/document use; SSH/GnuPG key loading; Thunar archive creation/extraction and image thumbnails; Zoom and Discord launched from a terminal while retaining private Xwayland; authenticated Timeshift GUI operation; Foot default close versus explicit command failures; Spotify first/second launch and termination; and native scope/session shutdown. For a running native scope, inspect the effective properties with:

```sh
systemctl --user show ACTUAL_SCOPE_NAME.scope \
  -p DropInPaths -p PartOf -p Requisite -p After -p KillMode -p TimeoutStopUSec
```

Use an actual current scope name from `systemctl --user list-units --type=scope`. Confirm logout leaves no application/private-display processes from that session. Save work before lifecycle tests. Continue collecting the residual graphics, firmware and vendor diagnostics separately; this delivery does not assert that they were repaired.

## Primary technical references

These sources support the implementation mechanisms, not a claim that the target was retested:

[U1] Debian xdg-dbus-proxy manual, TALK/OWN and supported namespace suffixes: `https://manpages.debian.org/unstable/xdg-dbus-proxy/xdg-dbus-proxy.1.en.html`

[U2] systemd execution-environment manual, user-manager namespaces and sandbox properties: `https://manpages.debian.org/unstable/systemd/systemd.exec.5.en.html`

[U3] Foot manual, exit status: `https://manpages.debian.org/unstable/foot/foot.1.en.html`

[U4] Chromium's native systemd scope implementation: `https://raw.githubusercontent.com/chromium/chromium/main/components/dbus/xdg/systemd.cc`

[U5] systemd unit manual, drop-in lookup and dependency propagation: `https://manpages.debian.org/unstable/systemd/systemd.unit.5.en.html`

[U6] systemd v257 directive parser, `Scope.TimeoutStopSec`: `https://raw.githubusercontent.com/systemd/systemd/v257/src/core/load-fragment-gperf.gperf.in`

[U7] FocusWriter theme serialization/read path: `https://raw.githubusercontent.com/gottcode/focuswriter/main/src/theme.cpp`; Qt QSettings format: `https://doc.qt.io/qt-6/qsettings.html`

[U8] Debian forky RetroArch file list: `https://packages.debian.org/forky/amd64/retroarch/filelist`

## Supplementary comparative-test results

The initial background test harness inherited ignored HUP/INT/QUIT dispositions. After correcting those dispositions in the **external validation harness only**, all 33 Codex clone-staging tests pass on both the original and patched trees. No installer signal-handling code was changed for this harness artifact.

The isolated patched ARM64/F2FS debconf test passes (one test, 48.029 seconds); the original full debconf module also passes all 22 tests. The patched transport module passes all 27 tests on a serial rerun. Initial transport/cache/fatal-record assertions were run-sensitive; no transport repair is claimed because its implementation is unchanged. Initial non-green results are retained in the JSON summary rather than erased.

Five older test modules still contain failures/errors reproduced with the same failed test-case names on the untouched upload:

| Module | Reproduced blocker |
| --- | --- |
| `test_desktop_sandbox.py` | Missing historical `todo/apparmor.log` fixture. Other tests in that module run; its unrelated fixture assertion remains unchanged. |
| `test_installed_failures_20260911.py` | Missing historical `todo/managed/apparmor/apparmor.log`. Its separate finite 592-event scoped-grant fixture test passes. |
| `test_managed_external_software.py` | Four tests cannot load Perl Moo in this container. |
| `test_podman_incus_redesign.py` | One legacy Fuzzel terminal-launch mock contract no longer matches the supplied implementation. |
| `tools/tests/test_labwc_power_handoff.py` | Existing notification-socket/live-wlrctl dependencies and old capability/session-state expectations do not match the supplied runtime/test environment. |

Those historical tests and unrelated implementation paths were not rewritten, skipped or loosened to manufacture a green suite. See `comparative-tests.json` for exact failed-case names and original/patched results. The broader suite is therefore **not certified fully green**. All 23 newly added incident-specific regressions pass.
