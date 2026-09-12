# Desktop isolation and installation fixes - 2026-09-12

## Scope and delivery

This is the complete supplied Debian preseed repository, with changes restricted to the requested DevOps/ChatGPT/Codex environment, generic desktop wrappers and package hook, Tuta launcher relocation, firstboot validation, related AppArmor rules, and regression tests. No software versions, release pins, unrelated service policies, or partitioning policies were changed. The generated `d-i/forky/payload.tar.gz`, `payload.manifest`, and `preseed.cfg` have been rebuilt together.

`CHANGE-MANIFEST-20260912.json` lists every changed/added/removed code file, original and new SHA-256 hashes, and modes. It excludes this report and the manifest itself. The sole removed source is the Tuta launcher, now at its requested skeleton location. Existing unrelated source files are retained.

## 1. DevOps, ChatGPT, Codex and installer state

The Codex backend user unit explicitly seeds HOME, USER, LOGNAME, XDG_RUNTIME_DIR, CODEX_HOME and XDG configuration/cache/data/state paths. Its existing `/data/codex/lib/codex` wrapper remains responsible for reconstructing the complete authoritative `71-devops-de.sh` environment, validating account paths, loading credentials and starting its existing sandbox. The socket proxy does not run development tools and does not need the tool environment.

ChatGPT's native service handoff now forwards the active DevOps environment rather than dropping it. Account and bus identity are validated separately; values are passed through the environment, not printed as command arguments or globally imported into the user manager. Unsafe loader/shell exports are rejected before invoking systemd-run. An ordinary desktop launch without both activation markers loads the current user's trusted `.profile.d/71-devops-de.sh` and calls `devops_de_apply_environment`. A partly active environment is rebuilt. This activates the environment for the application, not every ordinary terminal or unrelated user service.

Starting ChatGPT now requests and orders startup after the existing Codex socket and proxy service. The proxy already requires the backend service and waits for its readiness check. This is explicit application-to-service activation: a socket does not observe process names. Normal connections still use the socket, and the existing idle proxy/backend shutdown design remains. The backend can stop when no longer required; it is not pinned permanently by ChatGPT.

Installer target execution now supplies a real root HOME and XDG directories. Development-tool version probes run with a private temporary HOME/XDG tree and CHECKPOINT_DISABLE=1. Both raw Codex binary version probes use disposable HOME/CODEX_HOME/XDG paths and retain their timeout. The profile rejects HOME=/ and constructs its XDG paths explicitly. These fixes prevent the identified sources of root-level `/.codex`, `/.config` and `/.cache` state; no AppArmor grant for those paths was added. Previously created root-level directories are not automatically deleted: their contents were not supplied for safe classification.

## 2. Generic desktop wrappers and dpkg integration

The following defaults are present in all 13 desktop host profiles and rendered to `/etc/default/labwc-desktop`:

```sh
LABWC_ELECTRON_APP_DEFAULT_EXEC="/usr/local/bin/labwc-electron-app nvidia"
LABWC_WAYLAND_APP_DEFAULT_EXEC="/usr/local/bin/labwc-wayland-app nvidia"
```

Set either GPU selection to `intel` in the desired host profile. Installation resolves unavailable hardware consistently with the existing managed wrapper, falling back to Intel or the existing `launch` mode as appropriate. The two wrappers also accept `auto` for direct use.

Each generic launch creates a unique transient user service with Type=exec, ExitType=cgroup, KillMode=control-group, bounded stop timeout, automatic collection, and session target ordering/lifetime association. Arguments are passed as an argv array with systemd variable expansion disabled. Generic services have private temporary and IPC namespaces and ProtectSystem=full. Native applications reached through labwc-managed-app also now receive a transient service even when invoked from a terminal outside the compositor namespace. Existing dedicated Bitwarden and compatibility launch paths remain intact.

The generic wrappers reuse the repository's Intel/NVIDIA acceleration settings. Both select native Wayland toolkit backends. Only the Electron wrapper adds Chromium/Ozone/ANGLE/OpenGL flags; it keeps the normal multi-process/zygote and user-namespace sandbox and rejects sandbox-disabling flags. NoNewPrivileges is not forced before package AppArmor-to-Bubblewrap transitions, because doing so can break the existing confined launch chain; the application/Bubblewrap sandbox applies its own restrictions at the appropriate stage.

`/etc/dpkg/dpkg.cfg.d/95-labwc-desktop-apps` calls the root-owned `labwc-wrap-desktop-files` helper after applicable dpkg transactions. Installation also runs an initial sweep once the helper and defaults are available. It identifies exact package ownership with dpkg-query and checks read-only `dpkg -L` output for an existing `resources/app.asar`. It handles package-owned entries in `/usr/share/applications` and `/usr/local/share/applications`, preserving the original command, quoting, field codes, and desktop-action arguments. It does not execute user profiles or evaluate shell expressions. NoDisplay=true, Hidden=true, and dedicated managed launchers are left untouched. DBusActivatable is set false on wrapped entries so launchers use Exec. Repeated runs do not stack prefixes, and changing the configured GPU updates this hook's existing prefixes.

For example, a resulting entry is:

```ini
Exec=/usr/local/bin/labwc-electron-app nvidia -- "/opt/Example App/example" %U
```

The wrapper path and GPU are separate arguments, not a single quoted executable name. Updates use locking, bounded reads, metadata validation and atomic replacement. Root-owned vendor symlinks are validated and replaced at the desktop-entry path without rewriting their targets. Foreign DPKG_ROOT/DPKG_ADMINDIR invocations are ignored instead of accidentally modifying the host.

Isolation boundary: these are per-launch cgroup/lifecycle and namespace controls, not separate Unix accounts or a promise that arbitrary applications cannot access all files owned by the same user. Existing package AppArmor profiles and dedicated application sandboxes remain the additional access-control layer. The hook intentionally excludes hidden and already-managed entries. Unsupported Electron shell-command entries and unsafe env options fail explicitly rather than being silently launched without the requested flags. This does not turn an X11-only application into a native Wayland application.

## 3. Tuta launcher

The source is now `d-i/forky/hooks/target/etc/skel-desktop/.local/share/applications/tutanota-desktop.desktop`. Installer staging, template rendering, primary-account copying/ownership, validation, and the Tuta servicing module reference the new location. Installation explicitly copies the rendered file into the primary desktop user's `.local/share/applications/tutanota-desktop.desktop`; it does not merely leave it in a skeleton that has already been consumed. The old system-wide source has been removed.

## 4. Firstboot

`desktop_renderer_policy_matches` contained literal single-quoted grep patterns inside an outer single-quoted `/bin/sh -eu -c` body. They truncated the inner command even though the outer script passed `sh -n`. Those three patterns are now correctly escaped. The new regression captures the actual nested argv, parses the fixed inner shell, and reproduces the original inner-shell parse failure.

The firstboot wrapper now also emits concise stage failures/missing-stage diagnostics to stderr, retaining detailed stage logs, nonzero results, retry behavior and completion-marker semantics. It does not manufacture a successful completion or suppress failed validations. The supplied journal confirms exit status 1 but contains no failing-stage error, so it cannot establish that this was the only failure on the installed machine. A fresh unattended installation is still needed to confirm the full target boot.

## 5. AppArmor

The supplied complain log was reviewed by profile and operation. Changes cover the editor-to-Bubblewrap/glycin transition and its decoding runtime, cgroup quota reads, read-only btop process inspection of Bitwarden/Filen/Vivaldi with reciprocal readby rules, the observed power-supply attributes, compositor rfkill inheritance, and the exact Vivaldi native-messaging directory probe. New wrappers and the package hook have scoped launcher/helper profiles; Tuta servicing can read the relocated skeleton entry.

Complain-mode `null-*` profiles are not added to policy: the missing editor Bubblewrap transition is repaired instead. No rule allows the excluded `/.codex` accesses. The existing AppArmor mode selection is unchanged; offline compilation is not equivalent to testing enforcement on the target kernel.

## Validation actually performed

- 34 new regression tests passed.
- Across five directly relevant suites: 167 selected tests ran, 166 passed, 1 skipped because rsyslogd is unavailable, 0 failures/errors. Two other legacy raw-audit tests were explicitly excluded because their original `todo/apparmor.log` and `todo/managed/apparmor/apparmor.log` fixtures are absent from the uploaded ZIP. The current supplied audit log was not substituted for those different historical incidents.
- All 79 Python `.py` files parsed successfully. The new extensionless Python launchers/helper were also loaded/parsed by their tests and bootstrap review.
- Repository shell checks: 266 files, 543 parser checks, PASS.
- All seven affected top-level AppArmor policy files compiled using apparmor_parser 4.1.0 in a merged, temporary policy tree, without loading policies into the kernel.
- `python3 -B tools/build.py --check`: PASS; browser artifacts, payload, manifest and preseed are current.
- A standalone Perl module compile could not complete because the container lacks the existing Moo dependency. The servicing change is only its desktop-file path; no Perl behavior was otherwise rewritten.

The container filesystem returns EIO for fsync. Atomic-write unit tests mock fsync; they verify replacement and safety logic, not durability. The payload was generated using the unchanged build.build() implementation and published using adjacent temporary files without fsync in an external harness, then checked byte-for-byte by the normal --check command. Production fsync code was not weakened or removed.

No unattended VM/bare-metal installation, live systemd user-manager run, Intel/NVIDIA GPU execution, or AppArmor enforce-mode session was available here. Do not interpret static checks as a guarantee that every possible package or target-kernel combination was exercised.

## Publishing and target acceptance

Publish the complete repository atomically, including all three regenerated preseed/payload products. Editing a host profile afterward requires running `python3 -B tools/build.py` on the publishing host and republishing the generated products together. Re-run `python3 -B tools/build.py --check` before serving it.

After a fresh target install, start ChatGPT from the ordinary desktop session with DevOps initially inactive; inspect the user's Codex socket, proxy and backend units, then inspect a newly wrapped application's cgroup and descendants. Confirm that the selected Intel/NVIDIA renderer is in use, closing/stopping the service and ending the session remove its descendants, firstboot creates its completion marker only after all validations pass, and no new root-level cache directories appear. Exercise the editor image loader, btop, Bluetooth, capture and brightness operations under AppArmor enforcement before general rollout. Keep any new audit records scoped to the responsible profile; do not whitelist root-level development state.

Technical references consulted: Debian systemd-run(1), systemd.service(5), systemd.exec(5), dpkg(1), AppArmor profile syntax, the freedesktop Desktop Entry Exec specification, and Electron process sandbox documentation.
