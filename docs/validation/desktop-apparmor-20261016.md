# Desktop AppArmor and managed logging repairs, 2026-10-16

The later installed-system capture exposed a socket ownership/capability defect
missed by the static audits below. See
[logging startup incident](logging-startup-20261016.md) for the current diagnosis,
correction, failure classification and verification limits. The earlier static
results do not establish successful service startup.

## Installed-system incident: current correction

This section supersedes the earlier journal-wide warning threshold and the
earlier generated hashes below. Those historical changes removed ordinary
diagnostics from the journal and were too broad. They are corrected in source.

### Audit of all uncommitted changes

The follow-up audit inventoried all 64 uncommitted paths: 56 tracked changes
and eight untracked files, with no staged changes. It reviewed the source/test
diffs, new helpers, incident fixture and report, then followed the affected
callers, authenticated template rendering, target staging and generated products.

One runtime defect was confirmed in the newly added Remote Desktop diagnostic
copy. Its libc `syslog()` call ran synchronously inside the FreeRDP output-drain
loop. A full journal socket could block that call, stop pipe draining and stall
the client. The [glibc implementation](https://github.com/bminor/glibc/blob/master/misc/syslog.c)
creates a blocking socket and sends without a nonblocking flag.

The copy now sends bounded, escaped INFO datagrams directly to the existing
catalog-controlled application socket. Each send is nonblocking, the transport
is closed deterministically, and an unavailable/full collector ends only that
best-effort copy. Resolving the socket path on each send also tolerates collector
socket replacement. The private bounded preview is written first and remains
available when collector delivery fails. The Remote Desktop AppArmor change
grants only the application socket needed by this path. The escape operation
now substitutes nonprintable bytes through the regular-expression engine
instead of visiting every printable byte in Python; no measured speedup is
claimed.

Guarded regressions cover escaped/control/percent bytes, complete packet bounds,
the configured destination, preserved exit status/private preview on send
failure, and real fixture sockets that are available, absent or full. The socket
fixtures run a child producing more than one pipe buffer, with a five-second
outer timeout and an explicit minimal environment. They have **not been run**.

Static inspection also found one stale entry in the initial generated snapshot:
`hooks/target/etc/udisks2/mount_options.conf` did not match its current source.
The source's selected NTFS driver order is preserved; regeneration incorporates
it alongside the logging correction. Current generation results are recorded
at the end of this report.

The remaining changes retain the existing service cgroup ownership, bounded
capture/shutdown, private ChatGPT transport, authenticated socket credentials,
separate security routes, native Codex log destinations and shared auth sink.
Both security package selections include the new pyinotify dependency. Both
storage families publish the logging foundation before selected class helpers;
the Codex backend's installer guard agrees with the unit's full command.
Source/data inspection found no further confirmed defect in those changes.

All 22 changed Python inputs and both constant embedded Python drivers parse
with standard-library AST parsing, without importing repository code. Literal
inspection reconciles all 114 logging catalog keys and their schema bounds,
the two auth reader destinations, the backend command guard, and all 191 denials
represented by the incident fixture. The private Xwayland policy and both
compatibility runtime modules match HEAD byte-for-byte. The Fail2ban staging
comment now agrees with the retained INFO journal policy.

No disposable environment was supplied. No tests, benchmarks, native validators,
installed helpers or host-management operations ran. Independent sidecar
reviews failed to initialize with runtime encrypted-context errors, including
the retry with fresh contexts; no independent review result is claimed.
Runtime acceptance on Forky/systemd 262 remains required.

### Second audit pass: preserve the original launch contract

The second pass rechecked capture I/O and shutdown, socket access/routing,
transient-service callers, authenticated template rendering and installer
ordering. It found one additional compatibility defect: the new generic
`rsyslog-app-run` frontend rejected a complete command containing more than
256 arguments. Generic application and terminal launchers preserve the original
argument array and do not impose that limit. The logging prefix therefore made
previously valid launches fail before the application could start.

Only that argument-count predicate is removed. The kernel's normal execution
limits still apply. The wrapper keeps its non-root requirement, bounded safe
identifier, nonempty command and absolute executable requirement. Arguments
remain an explicit list passed directly to `Popen`, without a shell, splitting,
expansion or argument/environment logging. Signal/exit handling, pidfd polling,
bounded output buffers, collector backoff and shutdown/drain behavior are
unchanged.

Two guarded regressions cover a literal argument list with more than 300 entries
and preservation of the returned status, plus rejection of root, an injected
identifier newline, a relative executable and an empty command before spawning.
These fixtures mock only the launch boundary and perform no service or network
operation. They have **not been run** because no prepared disposable environment
was supplied. All 22 changed Python inputs and both embedded Python drivers
were instead parsed as source data. No speedup is claimed without measurements.

Socket/ruleset options were also compared with the
[rsyslog 8.2608.0 imuxsock implementation](https://github.com/rsyslog/rsyslog/blob/v8.2608.0/plugins/imuxsock/imuxsock.c).
The root-owned socket parents, credential-based application admission,
separate security routes and own-PID reflection guard remain in place.
The shared foundation still precedes class-helper validation, and the desktop
staging/verifier and backend command guard agree. No additional confirmed
defect was found in these source contracts. Independent review agents again
failed during runtime initialization; no agent review result is credited.

### Installer failure follow-up: Codex backend command

The reported fatal error, `Codex app-server backend does not use the managed
wrapper command`, came from a stale exact-line check in
`scripts/late/devops/codex-appserver.sh`. The backend unit already starts the
shared logging helper before the canonical Codex wrapper; the installer still
required the former command without that prefix.

The correction changes one production predicate to require the exact existing
logging-helper + Codex-wrapper + backend-endpoint command. It retains the
fixed-string, whole-line check. No runtime service, helper, logging route,
credential policy, sandbox or lifecycle behavior changes in this follow-up.
The two stale unit expectations are updated, and a guarded cross-file
regression now compares the actual installer predicate with the service source.

Data-only inspection confirms that all 16 fixed-line checks in this staging
function match their current environment/backend/proxy/socket source assets.
The readiness helper validates the private listening endpoint and account; it
does not require the Codex payload to remain the unit's MainPID. The desktop
logging stage installs the shared helper, and addon/devops is restricted to the
desktop role. No additional command consumer mismatch was found in the bounded
source search. Native installer execution remains unverified.

### Latest supplied evidence (LPL-514)

The replacement capture contains 91 files / 4,588,960 bytes, including 23 empty
files (excluding `todo/.~`). The evidence was read as data only.

| Evidence | SHA-256 | Finding |
| --- | --- | --- |
| `todo/journalctl` | `a851286b96fa45229c8cfbb2faef7ff618b4622726d1ea466b11980efdf44dfa` | Ten lines, including 408 missed forwarding messages |
| `todo/managed/security/apparmor/apparmor.log` | `3148b9e6597700beae94289d45596827d5a219c1e3df144a9300b2a59a8868a2` | Profile status records; no `DENIED` records |
| `todo/managed/apps/apps.log` | `46c4ccfabba1a890a94f876bccf0968d1bbc6bafddeff13f3038a7442f1f8838` | Desktop session reaches Labwc, Waybar, Crystal Dock and Foot |
| `todo/managed/system/system.log` | `a54a6e0122b84f03b7bc8a1c17b3dca76fea63f9c7b7dfac1443646ae37277a7` | Rsyslog 8.2608.0 starts and firstboot/cleanup complete |

The captured target reports systemd 262-1. Its early firstboot snapshot reports
no failed units and `findmnt --verify` reports no errors/warnings. These are
capture-time observations, not proof of later application or disk health.
The audited user execution records contain no Codex, ChatGPT or browser launch
attempts. Empty native application logs therefore cannot establish successful
launch or establish a new application failure in this capture.

The remaining reported warnings include firmware/device initialization,
CrowdSec console enrollment, and systemd's ambiguous monitor-source warning for
the shared `secondboot.service` success handler. The cleanup log confirms that
handler completed; its script reads completion files, not `MONITOR_*` values.
No policy, device, enrollment or bootstrap-lifecycle changes were made for
these warnings without evidence of a source defect.

### Current logging contract

- Restore `MaxLevelStore=debug`, `RateLimitIntervalSec=30s` and
  `RateLimitBurst=10000`. Preserve the selected storage/sealing/size settings.
  `journal-check` rejects the former journal-wide warning-only policy and
  conflicting native drop-ins.
- Set `MaxLevelSyslog=info`: retain INFO authentication/component inputs for
  existing readers, without copying general DEBUG traffic into rsyslog.
  `ForwardToSyslog` is systemd's literal setting for the local socket consumed
  by **rsyslog**. No other logging daemon or network forwarding is introduced.
- Routine native/generic GUI, Bitwarden, qBittorrent and Codex app-server
  stdout/stderr use one unprivileged `rsyslog-app-run` helper inside their
  existing service cgroup. The helper forwards bounded, escaped lines to
  `/run/rsyslog/apps/apps.sock`; the existing rsyslog queue/rotation writes
  `/var/log/managed/apps/apps.log`. It has no separate service, spool, rotation
  policy, application configuration, or additional userspace record queue.
- Keep the existing private ChatGPT capture and native Codex log-directory
  destinations. Fuzzel's existing structured logger now uses the shared
  application socket. The installed Fuzzel logger filename is unchanged; its
  physical source becomes `.tmpl` for catalog-driven socket rendering.
  Its datagram send and journal fallback are both nonblocking. The
  [Perl Sys::Syslog source](https://raw.githubusercontent.com/Perl/perl5/blead/cpan/Sys-Syslog/Syslog.pm)
  shows that its timeout controls a connection-readiness probe, not the send;
  the helper therefore uses the existing Perl socket primitives directly.
- The ChatGPT capture opens its transport before returning to the host user manager.
  Its private socket now belongs to the configured desktop UID, resolved from
  the installer-published runtime directory and restricted to UIDs 1000..59999.
  Mode `0660` and the `openailogger` group remain; its root-owned parent uses
  `0751` traversal so the mapped account can connect without supplementary
  groups. The target tmpfiles and service directory modes agree. AppArmor
  grants the existing permission helper only the extra `stat` execution and
  exact runtime-directory read required by this lookup. The new shared socket
  permission helper also has its own confined profile in `system-wrappers`.
- The application socket's root-owned directory is `0755`, and its root-owned
  socket is `0666`: user namespaces can hide supplementary groups. The private
  rsyslog ruleset admits only kernel-attested UIDs 1000..59999 and can write
  only the ordinary application sink. It bypasses every security classifier.
  Clients cannot replace the socket's directory entry or write the log file.
- Reflect only application warning/error priorities through the packaged
  `omjournal` module. The template supplies native `PRIORITY=0..7`, source
  identifier/PID and attested UID. `SysSock.IgnoreOwnMessages=on` prevents the
  rsyslog-originated journal copies from reentering the collector. Legacy
  application messages already in the journal are not reflected a second time.
- Raw GUI stderr without an explicit level is retained as a warning; explicit
  INFO/DEBUG headers remain ordinary file records. Managed lifecycle messages
  carry native priority prefixes so informational startup events stay INFO.
- A collector outage falls back to the existing journal stream; it must not
  prevent application startup or change its exit status. Socket waits are
  bounded to 50 ms, repeated outage probes are spaced one second apart, pidfd
  readiness tracks child exit, and pipe drain/termination remain bounded.
- System/service INFO records remain in the journal. The constant system-file
  fallback copies only warnings/errors; kernel and named security/auth/network
  destinations retain their existing ownership. User-manager lifecycle records
  are no longer misclassified as ordinary application output.
- Zoom/Discord compatibility launchers and their private Xwayland modules and
  policy remain unchanged. Their existing journal output remains available.

The [systemd 262 stream source](https://github.com/systemd/systemd/blob/v262/src/journal/journald-stream.c)
and [forwarding source](https://github.com/systemd/systemd/blob/v262/src/journal/journald-syslog.c)
confirm that socket forwarding is independent of journal storage and that a
full datagram socket increments the missed-message count. Restoring journal
retention prevents that transport failure from also erasing the source record.
The existing legacy socket is not a replay protocol; zero loss during arbitrary
collector downtime is not claimed. A fresh target capture must verify startup
delivery after this correction.

[Forky's rsyslog package file list](https://packages.debian.org/forky/amd64/rsyslog/filelist)
includes `omjournal.so`; no new package or compilation is introduced.
The [rsyslog 8.2608.0 implementation](https://github.com/rsyslog/rsyslog/blob/v8.2608.0/plugins/omjournal/omjournal.c)
documents the own-PID loop guard. The explicit journal template avoids its
default facility-combined priority value.

### Source-to-installed wiring and verification boundary

`desktop_stage_logging_policy` stages the app input, capture helper, socket
permission helper and rsyslog service drop-in through `desktop_stage_role_asset`
and the existing authenticated fetch/logging renderer. The new socket value is
declared and bounded in `observability.env` / `observability-schema.tsv`.
The existing target desktop verifier now requires all four installed files.
ExecStartPre creates the root-owned directory; ExecStartPost applies socket
permissions before rsyslog becomes ready. The existing app log directory,
writer queue, size callback and rotation limits are reused.

Updated guarded regressions cover journal policy/drift, unchanged argument
boundaries, direct collector delivery, severity/control-byte handling,
collector-outage fallback and preserved child exit status. These tests have
fixture-only coverage for the ChatGPT owner/range validation as well. They have
**not been run**: no prepared disposable test environment is attached. Only
stdlib AST/source/data inspection and the explicitly permitted pure build may
run in this checkout. No AppArmor parser, rsyslog validator, Perl checker,
systemd runner or host management helper was executed.

### Installation-order repair and capture simplification

The reported installer failure was `module name omjournal is unknown` in
`38-openai-chatgpt.conf`. The module load and `ManagedApplicationJournal`
template were in the main rsyslog configuration, but only desktop setup staged
that file. `software_enable_chatgpt_integration` installs its action and runs
`rsyslogd -N1 -f /etc/rsyslog.conf` earlier, while the target still has Debian's
default main configuration. Complete final-configuration checks missed this
intermediate installation state.

`stage_target_logging_foundation` now stages the existing main rsyslog
configuration and size-rotation callback. Both storage families already call
this foundation after mount preparation and before dispatch runs selected
class helpers. Desktop setup no longer stages duplicate copies. The existing
ChatGPT installer validation remains enabled, and the module/template now
precede both application actions. No package or service is added.

The journal template now uses the documented named-field list directly;
`omjournal` consumes those fields as a structured object, so text JSON escaping
is unnecessary. Warning/error selection and the own-PID loop guard are retained.
The generic capture splits each read buffer once and escapes only bytes outside
printable ASCII; timestamp/PID formatting is shared by chunks of the same line.
These remove repeated work; no benchmark or measured speedup is claimed.

ChatGPT's capture no longer connects permanently to one socket inode or sleeps
through send retries. Each nonblocking datagram resolves the destination path
again, so a replaced rsyslog socket can be used on the next record. The capture
uses only its private rsyslog socket. The briefly added `/dev/log` fallback was
removed at the user's request, and all three original AppArmor deny rules for
`/dev/log` and the journal directory/tree were restored. Warning/error journal
copies remain the responsibility of rsyslog's existing `omjournal` action.
If the private collector is unavailable or full, the affected record is dropped
without blocking or terminating the application. The configured startup socket
creation/readiness/permissions and the earlier foundation staging remain in place.

Guarded regressions now cover the early ChatGPT configuration state, all five
foundation publication/failure points, collector absence, a full private collector
queue, the original journal deny rules, and socket replacement while capture
remains alive. All transport paths in the ChatGPT fixtures are private fixture
paths. These tests have **not been run**: no prepared disposable test
environment is attached. Native rsyslog parsing, Perl checks, AppArmor parsing,
socket/process integration and a fresh install remain unverified at runtime.

The permitted pure build returned zero and printed `built 1788 payload files`:

```json
["/usr/bin/timeout", "60", "/usr/bin/make", "--no-print-directory", "-f", "Makefile", "build", "PYTHON=/usr/bin/python3 -I", "SHELL=/bin/sh"]
```

Its child environment contained only `PATH=/usr/bin:/bin` and `LC_ALL=C.UTF-8`.
All 2,432 nonproduct entries retained their contents, modes and modification
times during generation. Independent stdlib data inspection found all 1,788
archive members equal to current source and manifest hashes, with normalized
metadata; preseed's archive, manifest and bootstrap checksum pins agree.
The four changed Python inputs were parsed as AST data without importing them.
Static inspection traced the five foundation assets and both storage-family
orderings through dispatch to the early ChatGPT validation, and checked the
module/template/action and private-capture/AppArmor contracts. `git diff
--check` returned zero. None of these checks executes the installed runtime.

Current generated SHA-256 values after this repair:

| Product | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `dfa22cdd773764d63f8d5d4c8d13701e8ce4ad5ba7004e123afa5630a2b534ec` |
| `payload.manifest` | `eb69e292dc36b620e427da364613c81c244afea4beb129d4cf5b51596f7d9c55` |
| `preseed.cfg` | `b530c419245837a88523095f379799c5149443b417fd9883fc7806ee2a3aa277` |

### Earlier generated products and static inspection receipt

This receipt predates the installation-order repair above.
The permitted pure build ran with this explicit argument array and only
`PATH=/usr/bin:/bin` / `LC_ALL=C.UTF-8` in its child environment:

```json
["/usr/bin/timeout", "60", "/usr/bin/make", "build", "PYTHON=/usr/bin/python3 -I", "SHELL=/bin/sh"]
```

It returned zero and printed `built 1788 payload files`. Before/after snapshots
confirmed that all 2,370 nonproduct files/symlinks retained identical contents,
modes and modification times. Only the three permitted products were generated.

Independent stdlib data inspection confirmed:

- All 1,788 archive members / 34,341,741 source bytes match current source and
  manifest SHA-256 records; archive metadata is normalized and safe.
- All three generated preseed SHA-256 pins match their current inputs.
- Tests, the incident fixture and `todo` evidence are excluded from the payload.
- The 22 changed Python inputs parse with `ast.parse`; none were imported or run.
- All 114 logging catalog/schema keys agree, with no duplicate keys; all 41
  distinct logging placeholders in changed target templates are declared.
- The three private Xwayland policy/runtime files are byte-identical to `HEAD`.
- `git diff --check` returned zero.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `4c3dc141932272dfbef4a664d79ce155e1bb60c0ce440572fcbc03ab90488235` |
| `d-i/forky/payload.manifest` | `7a1796a38c0afba3a5aeb46edacda07895ffc9ef98eb2d284eadc5c500dcef46` |
| `d-i/forky/preseed.cfg` | `59abe522c46284a069f70c18693f9d85e9df0253a4776b5cc5d143f4d578f420` |

Native rsyslog/AppArmor/systemd/Perl acceptance and GUI startup have not run.
The guarded tests were updated for isolated execution but are not reported as
passing. Attempts to delegate independent review failed during context
hydration, before a review ran; no sidecar findings are credited. No installed
host configuration, service, security policy, network or user data was changed.

## Initial supplied evidence (superseded by the refreshed capture below)

Read all 589 records / 124,075 bytes of `todo/apparmor.log` as data.
The input SHA-256 is
`2d117bcb8f8c72bd02ae5b3d0a9e26043172b864719e2de8396769600883e437`.

| Records | Count | Interpretation |
| --- | ---: | --- |
| `STATUS` | 433 | Two initialization messages, 424 profile loads and seven profile replacements |
| `DENIED`, asset reads | 150 | 136 distinct packaged RetroArch menu asset paths |
| `DENIED`, battery reads | 6 | Three reads each of battery `type` and `status` |

All 156 denials have profile `labwc-app//app-bwrap`, operation `open`,
class `file`, command `retroarch`, requested and denied mask `r`, and different
process/file owners. There are no other access-event types in this initial capture.
Audit line 537 encodes its filename in hex; decoding yields
`/usr/share/libretro/assets/xmb/monochrome/png/Libretro - Pad.png`.
It is included in the asset totals and regression fixture.

## Policy change and installation

`hooks/target/etc/apparmor.d/desktop-wrappers.tmpl` now grants these reads
inside the existing `labwc-app//app-bwrap` child:

```text
/usr/share/libretro/assets/{,**} r,
/sys/devices/**/power_supply/BAT[0-9]*/{status,type} r,
```

The standalone `usr.bin.retroarch` profile already allows the reported
resources. The managed Bubblewrap launch executes `/usr/bin/retroarch` with
inherited execution after `no_new_privs`, so the required rules belong in
the Bubblewrap child. The new rules use read permission without an owner
qualifier because these resources are root-owned. The asset grant covers the
packaged resource subtree; the sysfs grant names only two battery attributes.
The [AppArmor file-rule reference](https://manpages.debian.org/unstable/apparmor/apparmor.d.5.en.html)
documents the read permission and directory/glob syntax used here.

Existing installation wiring is sufficient:

1. `scripts/late/security.sh:apparmor_managed_desktop_profile_files` lists
   `desktop-wrappers`.
2. `stage_target_desktop_apparmor_profiles` stages each listed policy to
   `/etc/apparmor.d/NAME` with mode `0644`.
3. `scripts/common/source.sh:source_fetch` resolves the authenticated snapshot's
   `.tmpl` member to the requested installed filename.
4. `scripts/late/target-assets.sh:stage_target_asset` publishes those bytes
   through the existing target asset path.

The RetroArch change adds no executable mapping, execution, write, capability,
profile transition or networking grant. The existing private Xwayland policy
and launch paths are unchanged.

## ChatGPT follow-up denials

The user additionally supplied audit events `22406` and `22407`: denied
execution of `/usr/bin/getent` and `/usr/bin/cut` by `labwc-chatgpt`.
These two records are separate from the initial 589-record capture. They are
included in the refreshed capture described below.

The ChatGPT launch activates the managed `~/.profile.d/71-devops-de.sh` and
calls `devops_de_apply_environment`.
That function runs the exact account-home lookup pipeline
`/usr/bin/getent passwd "$devops_de_account_uid" | /usr/bin/cut -d: -f6`.
The Python launcher has the same managed-profile activation fallback in
`labwc_managed_app/environment.py:chatgpt_devops_source_environment`.
The failure therefore occurs during the mandatory environment setup before
the application starts.

The existing `labwc-chatgpt` parent profile now grants
`/usr/bin/{cut,getent} rix,`. Both fixed helpers inherit the launcher's existing
confinement. Its existing wrapper-base include and explicit database paths
already allow reading `/etc/passwd` and `/etc/nsswitch.conf`; no extra database
or network grant was added. The native regression now checks both helper
executions, their lack of write permission, read-only account databases, and
the literal inherited-execution rule.

The Codex wrapper also applies that authoritative profile. Its existing parent
profile receives the same two fixed inherited-execution grants, so its service
startup can complete the same mandatory account lookup.

## Regression coverage

`tests/fixtures/installed-apparmor-20261016.json` now retains all 138 distinct
decoded RetroArch paths and all 11 other distinct denied requests from the
refreshed capture, their repetition counts, the input hash and event totals.
The existing native parser regression in
`tests/test_apparmor_incidents_20261004.py`, method
`SuppliedDenialTests.test_native_parser_permissions_cover_nested_documents_usb_and_unclean_journals`,
now requires exactly read permission for every root-owned fixture path and
checks adjacent asset paths, an unrelated battery attribute and an AC adapter
remain outside the new read scope.

These are compiler-expanded permission checks when run in the required
disposable environment. They were added but **not run** during this work.

## Refreshed application failure capture

The user supplied a refreshed `todo/apparmor.log`, `todo/journalctl` and
`todo/managed/` during the follow-up. The refreshed evidence contains 51 files,
8,761,649 bytes and 21 empty files; 49 files are below `todo/managed/`.
All files were read as data. No supplied evidence was edited or packaged.

The refreshed AppArmor file is 135,036 bytes, SHA-256
`08524134e52d2367ad0a6dd34324c003fa46658591427f1bfe050eee5ba662a3`.
Its 815 physical lines contain 624 audit records and 191 human-readable
FSUID/OUID continuation lines. There are 433 STATUS records and 191 DENIED
records, representing 149 distinct profile/operation/path/mask/owner requests.
The managed AppArmor copy has identical bytes. The earlier fixture is updated
to this snapshot; it retains the decoded asset filename containing spaces.

| Denied request group | Events | Source correction |
| --- | ---: | --- |
| RetroArch packaged asset reads | 150 | Existing read-only asset subtree grant retained in `app-bwrap` |
| RetroArch battery type/status reads | 26 | Existing two-attribute read grant retained in `app-bwrap` |
| ChatGPT getent/cut execution | 4 | Existing two-helper inherited-execution repair retained |
| Chromium crashpad execution | 1 | Exact `/usr/lib/chromium/chrome_crashpad_handler rix` in `app-bwrap` |
| Postman zsh execution | 3 | Exact inherited execution plus the existing managed shell's fixed helper/data set |
| Postman date/curl/tar execution, merged-/usr and /bin spellings | 6 | Fixed inherited helper names; gzip included for tar's compressed-archive child |
| Postman timestamped update archive creation | 1 | Owner-only read/write of `/opt/postman/Postman-[0-9]*.tar.gz` |

The fixture matches every refreshed denied request and its repetition count.
The existing native-policy regression replays all 191 events, translating
audit creation mask `c` to AppArmor file-write permission. It adds negative
checks for other helpers, other owners, execution of downloaded update
archives and writes to the installed Postman executable. It was not run.

### Correlated launcher and D-Bus repairs

- `apps/apps.log:555` and `apparmor.log:794` identify the same fatal Chromium
  crashpad spawn. The exact inherited execution grant belongs in the
  Bubblewrap payload; Debian's standalone Chromium attachment already allows
  its package tree.
- `apps/apps.log:878`, `:886` and `:894` correlate Postman's login-shell,
  extraction and archive errors with the recorded AppArmor denials. The direct
  Postman attachment and inherited payload now carry the fixed helper set.
  Postman alone additionally receives read-only `/etc/zsh`, `/etc/profile` and
  `/etc/profile.d` mounts. The shell probe does not receive a host HOME bind.
- Postman's existing directory-bind mechanism maps its private persistent
  `.local/share/Postman/cli-bin` to its sandbox `.local/bin`. Only the fixed
  owner-owned `postman` CLI name receives write/map/inherited-execution access.
  Other account launchers remain hidden. Native CLI options force user-local
  installation and prevent shell startup-file edits. These options and the
  CLI's native path are documented by
  [Postman's CLI installation reference](https://learning.postman.com/docs/postman-cli/postman-cli-installation).
- `apps/apps.log:190` and `:193` identify Bitwarden's denied tray name ownership
  at the filtered D-Bus boundary. Its profile now owns only the exact logged
  `org.freedesktop.StatusNotifierItem-2-1` name. It cannot own the tray watcher.
- `apps/apps.log:920` identifies VS Code's filtered login-manager inhibition
  call. The existing system proxy now receives a per-app policy tuple; Code
  allows only `org.freedesktop.login1.Manager.Inhibit` at
  `/org/freedesktop/login1`, alongside its existing UPower access. The rule
  grants neither unrestricted login-manager calls nor power-control methods.
  The [xdg-dbus-proxy reference](https://manpages.debian.org/trixie/xdg-dbus-proxy/xdg-dbus-proxy.1.en.html)
  documents the exact name and method/path filtering mechanisms.

The package stage already publishes `desktop-wrappers`, the Postman attachment,
`profiles.py` and `sandbox.py`; no new launcher or policy loader is needed.
Guarded mocks cover the D-Bus arguments and private persistent CLI directory
construction, but were not executed.

### Authentication readers follow managed rsyslog output

Both authentication readers consume the existing protected `LOG_AUTH_FILE`.
INFO SSH/PAM/pkexec events are retained in the journal and forwarded to this
shared file sink under the current logging policy.

- The existing SSH Fail2ban jail now uses `backend = pyinotify` and
  `logpath = __INSTALLER_LOG_AUTH_FILE__`. Both security package classes install
  Debian's `python3-pyinotify`. The existing target stage publishes and creates
  `59-log-layout.conf` before running Fail2ban's target configuration check,
  so the file exists even when OpenSSH is not selected. The service orders
  after rsyslog and tmpfiles. Ban ownership, filters, SSH port rendering and
  bounded repeat-ban policy are retained.
- CrowdSec's existing `20-sshd.yaml` becomes a physical `.tmpl` source and
  consumes the managed auth file through inotify. This single acquisition
  covers SSH/PAM/sudo/pkexec; the separate pkexec journal acquisition is removed
  from `23-system-syslog.yaml`, avoiding duplicate ingestion. The kernel file
  acquisition is retained. The existing suffix resolver and logging renderer
  publish `/etc/crowdsec/acquis.d/20-sshd.yaml` without unresolved tokens.
- `bootstrap_fetch_seed_file` delegates to `installer_fetch_seed_path`, whose
  fetch/render transaction applies `installer_render_logging_asset` before
  publication. The Fail2ban target publisher uses that same path before its
  SSH port placeholder map. No new renderer or hard-coded managed path is used.

The [Fail2ban backend reference](https://manpages.debian.org/unstable/fail2ban/jail.conf.5.en.html)
documents event-driven `pyinotify` file monitoring, while the
[CrowdSec file datasource reference](https://docs.crowdsec.net/docs/log_processor/data_sources/file/)
documents its inotify file acquisition. Both native readers still need isolated
acceptance against the installed package versions and rotation behavior.

### Other observed failures and limits

These findings were reviewed; they are not evidence that every application has
passed a launch test:

- qBittorrent fails at `journalctl:1838` before its configured removable volume
  is mounted at `:1862`; a later launch at `:1873` obtains its veth at `:1878`.
  The existing storage guard correctly prevents writing its data into `/run`.
  No fallback storage or automatic mount behavior was added.
- Discord reaches `renderer-full-interactive` in `apps/apps.log:723`, then its
  private display connection breaks at `:746` and reports infrastructure
  failure at `:749`. No Discord AppArmor denial or definite cause of the
  compositor termination appears in these logs. Krisp initialization also
  fails at `:688`. These remain unresolved; private Xwayland and its lifecycle
  are unchanged as requested.
- Vivaldi's missing vendor extension/NoScript resource/EventAck errors and
  Edge's welcome-page JavaScript error have no matching AppArmor denials.
  Vendor/extension resources are not rewritten or bypassed by this repair.
- Postman's app-updater archive denial is allowed, but the installed
  `/opt/postman/app` tree remains immutable and root-owned. Installation updates
  continue through the repository's existing Postman servicing implementation.
  The optional agent-plugin installer reports no supported agent inside this
  sandbox. This repair does not expose Codex credentials or its complete home
  to Postman. Native updater and optional agent integration success is not
  claimed.
- Codex's supplied TUI log reports a reserved marketplace source and missing
  `openai-bundled` plugin bundles. Those external runtime-home plugin inputs
  are not present in this installer tree; no replacement marketplace or
  fabricated plugin installation was added.
- CrowdSec's console synchronization error reports missing external console
  enrollment. Local API and firewall-bouncer startup are present in the
  supplied logs. No enrollment token or remote account change was made.
- Bitwarden's cross-device hard-link probe explicitly falls back to copying.
  Nonexistent Postman lock cleanup, Waybar GTK accelerator assertions, Recoll's
  Vulkan probe, Tor's DRM probe, Bluetooth identity-file and UCSI errors lack a
  correlated repository permission failure. Empty scan logs establish neither
  successful scans nor an actionable scan failure.
- All four audit files were correlated by audit event ID. The 11 EACCES
  syscalls align with the Chromium/Postman denials; the 48 ENOENT execution
  records are missing optional tools or PATH searches. No broad PATH grant or
  speculative package installation was made for those searches.

## Managed log forwarding

The subsequent user requests add all supported application/system forwarding
to the task and require ordinary diagnostics to avoid filling the journal.
The existing path catalog, protected output ownership, routing categories and
rotation owners are retained.

### Shared transport and retention

- Journald keeps `ForwardToSyslog=yes` and `MaxLevelSyslog=debug`, with
  `MaxLevelStore=warning`. Notice/info/debug records pass to rsyslog without
  being retained in journal files. Warnings and more severe records retain
  the selected persistent/volatile backend and its existing size/sealing policy.
- `RateLimitIntervalSec=0` removes journal ingress suppression. The existing
  syslog and private socket interval values are also zero, removing their
  per-process burst suppression. The catalog schema accepts zero only where
  its bounds permit it; positive queue/rotation limits remain mandatory.
- `journal-check` now checks the effective retention, forwarding and rate
  settings as well as storage, sealing and kernel input ownership. A later
  native drop-in that re-enables debug retention or restricts syslog forwarding
  therefore fails the existing install/rsyslog preflight.
- The existing single `imuxsock` input and `imklog` kernel input remain. There
  is no journal database reader, new file-mirroring loop, additional daemon or
  per-application logging service. Existing bounded queues, spool limits,
  asynchronous file output and 2 MiB / four-archive rotation remain intact.

The [systemd retention/forwarding reference](https://www.freedesktop.org/software/systemd/man/252/journald.conf.html)
documents the independent severity controls.
[Rsyslog's imuxsock documentation](https://docs.rsyslog.com/doc/configuration/modules/imuxsock.html)
documents the local socket input and interval-zero behavior. No throughput or
latency benchmark was run. Datagram transport and finite queues do not provide
lossless delivery during collector downtime or unlimited overload; disabling
suppression removes deliberate rate drops, not those physical limits.

### Application capture repairs

| Source | Managed destination / change |
| --- | --- |
| Normal user services, native/generic managed apps, Fuzzel lifecycle/syslog, Waybar and Crystal Dock | Existing UID-based route to `apps/apps.log` |
| Unclassified system/service records | Existing fallback to `system/system.log` |
| Kernel records | Existing `imklog` route to `system/kernel.log` |
| ChatGPT stdout/stderr and environment activation failures | Existing private socket to `models/openai/chatgpt/chatgpt.log` |
| Codex CLI/backend native logs | `models/openai/codex/`; wrapper supplies native `log_dir` in all three raw execution paths |
| ChatGPT bundled Codex native logs | `models/openai/chatgpt/runtime/`; both `/data/codex/log` and native `$CODEX_HOME/log` map to this same directory |
| Screen recording diagnostics | Service stdout/stderr now reach `apps/apps.log`, replacing the private `recording.log` redirect |
| Remote Desktop captured diagnostics | Bounded, control-escaped nonblocking application-socket copy to `apps/apps.log`; existing bounded private UI/error preview remains |

Destinations in the table are relative to `/var/log/managed`. Existing security
and native package destinations remain catalog-controlled. Existing persistent
boot/power exports under `/var/lib/journal` keep their separate state contract.

ChatGPT's shell entrypoint now starts the existing capture runner before
environment activation. The existing Python loader still validates the managed
profile's direct path, owner, permissions, link count and size, and reconstructs
the environment. The removed duplicate shell activation previously discarded
its errors through `/dev/null`. Identity/argument checks and the clean `env -i`
entry remain.

Codex's documented native setting is `log_dir`; see
[OpenAI's log-directory documentation](https://learn.chatgpt.com/docs/config-file/config-basic#log-directory).
The wrapper supplies that setting before the original argument list and also
sets its existing environment variable consistently. Sandboxed execution uses
the `/data/codex/log` bind; explicit `--no-bwrap` execution uses the managed host
directory directly and validates it before executing. ChatGPT's added default
log mountpoint is created by the existing Codex tmpfiles policy before launch.
Native log files keep their existing ownership and copytruncate rotation.

Remote Desktop forwards only captured diagnostic bytes, not command arguments
or askpass input. Each complete datagram is bounded to 1,800 ASCII bytes and
control bytes are escaped. Its profile grants writes to the shared application
socket. The screen recorder keeps its existing transient service and
signal/exit handling; only diagnostic output routing changes.

Updated guarded regressions cover severity-policy drift, zero interval bounds,
ChatGPT capture order/default log binds, all Codex execution modes, recording
output, bounded Remote Desktop forwarding and its explicit mocked syslog sink.
Those regressions were **not run**.

## Inspection and execution limits

No prepared disposable VM/image was supplied. In accordance with
`AGENTS.override.md` and `docs/test-isolation.md`, no test suite, validation
runner, native AppArmor parser, installed helper or host-management operation
was executed. No host security policy was loaded or changed.

Completed source-as-data inspection using bounded isolated-Python-startup
`/usr/bin/python3 -I -S -B -` invocations, without importing repository modules:

- Reconciled every log event with the fixture, including hex decoding, all
  repetition counts, all 149 distinct requests and the exact input SHA-256.
- Matched all 150 asset reads, 26 battery reads and the other 15 denials to
  their source grants. This is static path coverage, not native policy parsing
  or kernel acceptance.
- Parsed all 15 changed Python source/test inputs with the standard-library
  AST; also inspected `tools/build.py` and `tools/publication.py` before generation.
- Resolved all 113 unique logging catalog keys as literal data; schema keys,
  integer bounds, enum values and managed destination roots agree.
- Inspected all 20 rsyslog drop-ins, common inputs, constant fallback paths,
  protected output creation, rotation ownership and installer staging.
- Inspected all three Codex raw launch paths and both ChatGPT native-log binds,
  including creation of the new required mountpoint by existing tmpfiles.
- Followed checkout-owned includes. Distribution/optional includes were not
  read from the host; their target-system interpretation remains a native
  integration check.
- Inspected the installer staging and `.tmpl` resolution paths as data.
- Inspected the Code/Bitwarden/Postman policy literals with AST data extraction
  and the system-proxy call's AST. No runtime modules were imported.
- Resolved the auth file token as literal catalog data and parsed the rendered
  Fail2ban jail with standard-library ConfigParser. Both native readers point
  to the existing protected auth sink; native package validation was not run.
- Compared the private Xwayland AppArmor file and both compatibility runtime
  modules to HEAD byte-for-byte; all three remain unchanged.
- Ran `git diff --check` without findings.

Independent review agents failed to initialize with encrypted-context errors;
no independent agent result is claimed. Policy acceptance and disappearance of
the denials still require an isolated Forky installation and actual affected
application launches.
This work updates the unattended installer repository, not an installed host.

## Earlier generated products (superseded)

The Makefile recipe and complete `tools/build.py` / `tools/publication.py`
execution path were read before generation. The normal build serializes
exactly the archive, manifest and preseed products; it does not execute tests,
validators, shell snippets, browser generators or policy parsers.

Generation and final archive inspection results are recorded below.

Final generation used this explicit argument array, with only
`PATH=/usr/bin:/bin` and `LC_ALL=C.UTF-8` in the child environment:

```json
["/usr/bin/timeout", "60", "/usr/bin/make", "build", "PYTHON=/usr/bin/python3 -I", "SHELL=/bin/sh"]
```

It returned zero and printed `built 1784 payload files`. A snapshot of 2,326
nonproduct files/symlinks before and after generation found no changes to their
content, modes or modification times. Git/cache/build-working directories were
excluded from that snapshot. The builder wrote only its three products.

Independent standard-library archive/hash inspection found:

- All 1,784 regular archive members / 34,325,135 source bytes match the current
  payload source and manifest SHA-256 records exactly.
- Archive and source member inventories, safe relative paths and normalized
  `0644`, root/root, zero-time archive metadata agree.
- The generated preseed contains the matching archive, manifest and bootstrap
  SHA-256 pins.
- Tests, the incident fixture and ignored `todo` evidence are not packaged.
- Generated files have mode `0644`; no generated product is stale.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `18517a6e1f5b7bd82ce72f149db35c3df6d8a0015bb33b83c919b8eacc57dc59` |
| `d-i/forky/payload.manifest` | `085dae7cd27cf772c513ac7bae9e7c003eda2bb3576ab83a79b3ffcce80d2a62` |
| `d-i/forky/preseed.cfg` | `37a8043c4dff6b37fe71bda4272954a0a57c02802b5a0fabfed801030348a63e` |

The source/fixture/catalog/AST/archive inspections used bounded one-off
standard-library programs with `/usr/bin/python3 -I -S -B -`; they did not run a
repository validation module. Build and Git subprocesses used explicit minimal
environments. Repository runtime source was not imported or evaluated during
static inspection. `git diff --check` returned zero.

The generated products include the final AppArmor and logging source changes.
Tests and this report are outside the generated archive. Native acceptance,
actual application startup and actual installed-host log delivery remain
unverified; no host repair, service reload/restart or deployment was performed.

## Exact changed paths

Runtime policy and installer data:

```text
d-i/forky/classes/class-select/security/enhanced.cfg
d-i/forky/classes/class-select/security/standard.cfg
d-i/forky/hooks/target/data/codex/lib/codex.tmpl
d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
d-i/forky/hooks/target/etc/apparmor.d/opt.postman.app.Postman
d-i/forky/hooks/target/etc/apparmor.d/system-wrappers.tmpl
d-i/forky/hooks/target/etc/crowdsec/acquis.d/20-sshd.yaml.tmpl
d-i/forky/hooks/target/etc/crowdsec/acquis.d/23-system-syslog.yaml.tmpl
d-i/forky/hooks/target/etc/fail2ban/jail.d/10-sshd.local.tmpl
d-i/forky/hooks/target/etc/rsyslog.conf.tmpl
d-i/forky/hooks/target/etc/rsyslog.d/21-apps.conf.tmpl
d-i/forky/hooks/target/etc/rsyslog.d/22-apps-socket.conf.tmpl
d-i/forky/hooks/target/etc/rsyslog.d/38-openai-chatgpt.conf.tmpl
d-i/forky/hooks/target/etc/rsyslog.d/44-components.conf.tmpl
d-i/forky/hooks/target/etc/skel-desktop/.config/systemd/user/codex-app-server.service
d-i/forky/hooks/target/etc/systemd/journald.conf.d/10-storage.conf.tmpl
d-i/forky/hooks/target/etc/systemd/system/fail2ban.service.d/40-runtime.conf
d-i/forky/hooks/target/etc/systemd/system/rsyslog.service.d/32-apps-socket.conf
d-i/forky/hooks/target/etc/systemd/system/rsyslog.service.d/35-openai-chatgpt-socket.conf
d-i/forky/hooks/target/etc/tmpfiles.d/61-openai-chatgpt.conf.tmpl
d-i/forky/hooks/target/etc/tmpfiles.d/80-codex-storage.conf.tmpl
d-i/forky/hooks/target/usr/local/bin/chatgpt
d-i/forky/hooks/target/usr/local/bin/labwc-capture.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-fuzzel-log.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-qbittorrent
d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop.tmpl
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/events.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/generic.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/sandbox.py
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/session.py
d-i/forky/hooks/target/usr/local/libexec/journal-check
d-i/forky/hooks/target/usr/local/libexec/labwc-chatgpt-log-runner.tmpl
d-i/forky/hooks/target/usr/local/libexec/rsyslog-app-run.tmpl
d-i/forky/hooks/target/usr/local/libexec/rsyslog-app-socket.tmpl
d-i/forky/hooks/target/usr/local/libexec/rsyslog-openai-socket.tmpl
d-i/forky/hosts/logging/observability-schema.tsv
d-i/forky/hosts/logging/observability.env
d-i/forky/scripts/common/logging-validate.awk
d-i/forky/scripts/desktop/components/logging.sh.tmpl
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/scripts/late/devops/codex-appserver.sh
d-i/forky/scripts/late/security.sh
```

Replaced physical sources (installed filenames are unchanged):

```text
d-i/forky/hooks/target/etc/crowdsec/acquis.d/20-sshd.yaml
d-i/forky/hooks/target/usr/local/bin/labwc-fuzzel-log
```

Guarded regressions and evidence:

```text
d-i/forky/tests/fixtures/installed-apparmor-20261016.json
d-i/forky/tests/test_apparmor_incidents_20261004.py
d-i/forky/tests/test_codex_identity.py
d-i/forky/tests/test_codex_power_20260926.py
d-i/forky/tests/test_computer_management_20260916.py
d-i/forky/tests/test_crowdsec_firstboot_retry.py
d-i/forky/tests/test_desktop_sandbox.py
d-i/forky/tests/test_fail2ban_clipboard_apparmor_20260928.py
d-i/forky/tests/test_installation_fixes_20260912.py
d-i/forky/tests/test_logging_size_20260924.py
d-i/forky/tests/test_managed_app_review_20260921.py
d-i/forky/tests/test_managed_logging_r3.py
d-i/forky/tests/test_native_logging_r4.py
docs/validation/desktop-apparmor-20261016.md
```

Generated products:

```text
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
d-i/forky/preseed.cfg
```

The initial repair phase started with a clean working tree. This follow-up
preserved its uncommitted changes; no unrelated work was overwritten.

## Current generated snapshot after both audit passes

This snapshot supersedes every earlier artifact hash in this report.

The permitted pure generation command was executed with the explicit array
below and only `PATH=/usr/bin:/bin` and `LC_ALL=C.UTF-8` in its environment:

```json
["/usr/bin/timeout", "60", "/usr/bin/make", "--no-print-directory", "-f", "Makefile", "build", "PYTHON=/usr/bin/python3 -I -S", "SHELL=/bin/sh"]
```

It returned zero, reported `built 1788 payload files`, and produced no stderr.
The Makefile and complete normal `tools/build.py` / `tools/publication.py`
execution path were read before execution. This command performs serialization;
it compiles no software and executes no tests or native validators.

Before/after source-data snapshots found no content, mode or modification-time
change in any of 2,370 nonproduct files. Generated products and Git/cache/build
directories were excluded. Source modes also match the task-start inventory.

Independent standard-library archive/hash inspection confirmed:

- All 1,788 regular members / 34,341,838 content bytes agree exactly with the
  source inventory and all manifest SHA-256 records.
- Member paths are safe and relative; archive metadata is normalized to mode
  `0644`, root/root and zero timestamps, with no links or duplicate members.
- Preseed's archive/manifest/bootstrap checksum pins agree with current bytes.
- All three generated products have mode `0644`.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `778cef5ade53dbff99926dcbf6343cfb4d339efe9bfb316b01664c7079b92425` |
| `d-i/forky/payload.manifest` | `fcc21e14df6d1f55e38861e13cef5ff2c84a7c886ed7b9ce515c26a3c5579834` |
| `d-i/forky/preseed.cfg` | `6fdccf5102923723c684d14293f01736daa58a629ec3c71de20d5285fa343921` |

Only these nine paths changed further during the first audit pass:

```text
d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-remote-desktop.tmpl
d-i/forky/scripts/late/security.sh
d-i/forky/tests/test_apparmor_incidents_20261004.py
d-i/forky/tests/test_computer_management_20260916.py
docs/validation/desktop-apparmor-20261016.md
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
d-i/forky/preseed.cfg
```

Only these six paths changed further during the second pass:

```text
d-i/forky/hooks/target/usr/local/libexec/rsyslog-app-run.tmpl
d-i/forky/tests/test_managed_logging_r3.py
docs/validation/desktop-apparmor-20261016.md
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
d-i/forky/preseed.cfg
```

Source/data inspections used `/usr/bin/python3 -I -S -B -`, with no repository
imports or execution. `git diff --check` returned zero. The guarded tests,
native parsers, real application launches and unattended installation were not
run. No installed host configuration, service, package state, networking,
device or security policy was changed. No deployment was performed.
