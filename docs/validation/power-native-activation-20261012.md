# Power actions and native application activation — 2026-10-12

## Execution boundary

This repair changes checkout sources and the three generated installer products.
Repository modules, tests, validators, native parsers, installed helpers and host
services were not executed. Source inspection used text, Python AST, XML, JSON
and archive bytes as data. The disposable environment required by
`AGENTS.override.md` was unavailable, so the updated regression tests were not run.

## Poweroff and reboot

The authenticated root frontend still selects a fixed system-manager worker
instance from the Polkit invoking UID and the allowed action. Once that worker
starts, poweroff/reboot take a separate path:

1. Acknowledge worker readiness and send one user-owned Wayland close request.
2. Attempt the established guest, NFS, external-drive, greeter, account, zram,
   fallback-swap and sync cleanup, with a shared 45-second cleanup deadline.
3. Submit exactly one `/usr/bin/systemctl --force ACTION` request from a `finally`
   block, even if cleanup fails.

Cleanup commands receive at most ten seconds or the remaining deadline. Readiness
notification, close-request transport and final power transport have their own
bounded timeouts; 45 seconds is the cleanup budget, not a measured total shutdown
time. Package activity, retained service results, other-login inventory,
inhibitors and compositor health do not veto this already authorized machine
action. A failed or lost final acknowledgement remains uncertain and is not
automatically retried or escalated.

The worker retains its AppArmor domain, fixed transport environment,
`CAP_SYS_BOOT` boundary and seccomp prohibition on direct reboot/kexec. The unit
logs to the journal with `SyslogIdentifier=labwc-admin-action`; it no longer
requires a writable power-log mount before starting. Existing rsyslog routing
still selects that identifier.

Logout retains package reservations and waits only for actual Wayland windows
after one native close request. Background processes do not produce a generic
save warning. Suspend retains package reservations and the screen-lock lifetime
check. Neither operation captures a session.

## Session replay removed

The restore service, autostart start, installer staging and installed-file
verification references were removed. The state helper no longer inventories
services, saves launch descriptors, writes persistent session JSON, or replays
commands. Managed launchers no longer create or export `LABWC_SESSION_RESTORE`.

`labwc-session-state` still sends close requests, checks actual windows for
logout, clears the clipboard on logout, validates the screen-lock lifetime for
suspend, and owns the temporary closing marker. A new compositor clears that
marker through the fixed autostart path. Its AppArmor profile retains home
directory read access for the user unit's default working directory. Actual
desktop launchers retain their `systemd-run` permissions.

## Native reuse of existing applications

| Application | Canonical change | Intended native behavior |
| --- | --- | --- |
| Thunar | `misc-open-new-window-as-tab=true` in `thunar.xml` | Ordinary directory and file-manager activation opens a tab in an existing window. |
| FeatherPad | `[window] openInWindows=false` in `fp.conf` | Native D-Bus activation prefers tabs in an eligible existing window. |
| VS Code | Three `window.open*InNewWindow` settings set to `off` | Ordinary file, folder and argument-free activation prefers the existing window. Workspace-trust policy still applies. |
| FocusWriter | Shared user-manager `RuntimeDirectory=labwc-focuswriter-tmp`, mode `0700`, preserve `yes`, and fixed UID-derived `TMPDIR` | Separate transient launches can find the primary application's native Qt socket and lock. A short-lived secondary launch cannot delete the primary's directory. |

FocusWriter retains `PrivateTmp=yes`, `PrivateIPC=yes` and its existing
application lifetime/security settings. Its AppArmor grant is limited to the
same-owner `labwc-focuswriter-tmp` tree with `rwk`, including socket creation and
lock-file access. The importer already dispatches through the same generic
launcher. Browser/Electron managed sandboxes already use stable per-application
temporary directories for native singleton IPC.

These choices use the applications' native interfaces. Explicit new-window
commands and application-specific restrictions still apply. The inspected qimgv
upstream launcher has no native forwarding interface for opening a file in an
existing process; this repair does not claim universal window reuse.

Primary-source contracts inspected as data:

- [Thunar 4.20.5 window/tab preference handling](https://github.com/xfce-mirror/thunar/blob/thunar-4.20.5/thunar/thunar-application.c) and [current FileManager1 ShowItems handling](https://github.com/xfce-mirror/thunar/blob/master/thunar/thunar-dbus-service.c).
- [FeatherPad native D-Bus forwarding](https://github.com/tsujan/FeatherPad/blob/master/featherpad/singleton.cpp) and [window preference reader](https://github.com/tsujan/FeatherPad/blob/master/featherpad/config.cpp).
- [VS Code file/folder settings](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/browser/workbench.contribution.ts) and [argument-free window setting](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/electron-browser/desktop.contribution.ts).
- [FocusWriter instance forwarding](https://github.com/gottcode/focuswriter/blob/master/src/main.cpp), [KDSingleApplication socket/lock paths](https://github.com/KDAB/KDSingleApplication/blob/master/src/kdsingleapplication_localsocket.cpp), and [systemd 262 runtime-directory contract](https://github.com/systemd/systemd/blob/v262/man/systemd.exec.xml).
- [qimgv launcher](https://github.com/easymodo/qimgv/blob/master/qimgv/main.cpp).

## Reported Mullvad Browser AppArmor events

The reported `labwc-app//app-bwrap` requests for `/usr/bin/id`, `/usr/bin/ln` and
`/run/user/1000/wayland-proxy-12` already have these rules in HEAD, the current
canonical source, and the preceding generated archive:

```apparmor
/usr/bin/{id,ln} rix,
owner /run/user/[0-9]*/wayland-proxy-* rw,
```

Inherited execution keeps both shell helpers in the payload domain. The owner
write rule covers creation of the reported same-owner socket. No conflicting
deny for these paths was found in the checkout-supplied transitive abstractions. The
policy files remain in the installer's managed desktop policy list. Comments
and guarded regression coverage now identify the exact requests and reject
broad executable/runtime-socket grants.

The audit records do not identify the bytes loaded by the affected machine.
Their contradiction with the already published rules requires target-side loaded
policy evidence to explain; this workspace review cannot establish whether the
machine loaded a different policy or an additional local rule. No policy reload
or installed-machine repair was performed.

## Inspection and generation evidence

Guarded regression sources now cover cleanup-failure handoff, absence of replay,
native reuse settings, FocusWriter directory lifetime, and the exact Mullvad
requests. Obsolete shutdown-veto, native-append-log and foreground-lifetime
assertions were updated where they referred to the changed contracts.

| Inspection or generation | Observed result |
| --- | --- |
| Data-only AST parsing of Python sources, templates and guarded regression files | 394 files, no syntax errors; no repository module imported or executed. |
| Active source search for replay contracts | No `LABWC_SESSION_RESTORE`, restore-service or `restore_arguments` references. |
| Machine-action AST inspection | Separate first branch, no package/session/inhibitor gate, final request in `finally`. |
| XML/JSON/source inspection | Thunar native tab preference enabled, VS Code reuse settings `off`, workspace trust retained, exact Mullvad and FocusWriter scoped grants present. |
| `git diff --check` | Completed with no whitespace diagnostics. |
| `/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh` | Completed successfully; serialized 1,743 payload members. No validation runner or test invoked. |
| Comparison with a private pre-build inventory of 2,357 checkout files | Exactly `payload.tar.gz`, `payload.manifest` and `preseed.cfg` changed during generation. |
| Streaming comparison of source, manifest and archive | All 1,743 paths and 33,911,339 source bytes agree; no hash or metadata mismatch. All archive entries have mode `0644`, UID/GID zero and mtime zero. |
| Preseed pin inspection | Archive and manifest pins match; both bootstrap-source pins match the current source. Removed restore service is absent. |

An initial archive inspection stopped at its eight-MiB member limit on the
existing wallpaper archive. A second inspection used bounded 64-KiB reads and
completed the entire source/archive/manifest comparison. No archive was
extracted and neither inspection executed payload contents.

Generated SHA-256 values:

```text
payload.tar.gz   8639cc37813f34cde2ca11b490c589aa0fd55de863af640a344e1929d3ed1b8f
payload.manifest bb7f365a623cc56a1872a98e9df042a556124acff43689f2e48fc71ce7f10002
preseed.cfg      ca05768ccc7f15b54163be33fc563ce13a523d55e884720efeae297a3c610331
```

Native AppArmor compilation, kernel enforcement, authentication, application GUI
activation and actual power transitions remain unverified in this turn. The
private Zoom/Discord Xwayland configuration and policy were preserved. The
updated installer products serve future installations; these checkout changes
do not establish that an existing machine has installed or loaded them.
