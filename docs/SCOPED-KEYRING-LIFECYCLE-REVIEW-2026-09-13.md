# Scoped keyring, desktop isolation and helper-lifecycle review

Date: 2026-09-13 (Europe/Oslo)

## Delivered scope

This revision addresses the reported APT keyring failure and confirmed lifecycle,
launch-routing, package-import and AppArmor wiring gaps in the requested trees.
It is not a general refactor or a claim that every installed application has been
exercised on real hardware.

The review inventory covers all 151 Perl library files, all 33 Python modules and
all 71 libexec files. Installer references are recorded for every file in
`validation/scoped-keyring-lifecycle-2026-09-13/requested-scope-inventory.json`.
The Python regression also checks the exact package trees against their staging
manifests and the managed-app integrity module list. Installer references alone
are not proof that an installation or a service has run successfully.

Compared with the uploaded ZIP, 17 runtime/policy files, two existing tests and
three generated files changed. One new regression-test file was added. All 1,503
original files are retained: 1,481 are byte-for-byte unchanged and 22 are modified.
No original file permissions were changed. The additional files are this report,
the regression test, and dated validation evidence. The necessary adjacent wiring
changes are limited to `usr/local/bin/labwc-terminal` and two AppArmor policy files.
No kernel, application, driver or other native binary was compiled. The existing
Python payload generator packages source files; it does not compile them.

Paths below are relative to `d-i/forky/hooks/target/` unless stated otherwise.

## 1. APT normalization and forky-backports

### Root cause and repair

`usr/local/libexec/local-apt-normalize-sources` used the same `O_NOFOLLOW` reader
for source-list files and package-managed keyrings. Linux returns `ELOOP` when the
last component is a symlink with this flag, even when the link is valid and not
cyclic [1]. The test environment has the normal package-managed layout:

```
/usr/share/keyrings/debian-archive-keyring.gpg -> debian-archive-keyring.pgp
```

The old open flags reproduced errno 40 against that file. The new reader consumed
55,918 validated bytes and GnuPG returned equal trust identities for the `.gpg`
and `.pgp` names. Neither the keyring nor the host's APT sources were modified.
See `real-keyring-check.json` in the dated validation directory.

The repair deliberately does not remove the source-file symlink guard or replace
Debian's keyring symlink. It adds a separate keyring reader with target-root-anchored
directory descriptors, no-follow opens, ownership/type/mode validation, bounded
reads, and a 40-link limit. Relative and absolute package links are supported;
absolute links remain relative to the supplied target root. Actual loops, dangling
links, escapes above that root, unsafe ownership, writable directories/keys and
nonregular final objects are rejected before source files are rewritten.
GnuPG reads the already-validated bytes through standard input rather than
reopening the original path. The prior unstaged, directly missing-key behavior is
preserved; a dangling symlink is not silently treated as an unstaged key.

### Signed-By policy

Recognized Debian entries without an explicit key retain the Debian archive
keyring policy, including `forky-backports` and both `deb` and `deb-src` records.
The normalized `debian.sources` backports stanza contains:

```
Suites: forky-backports
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg
```

An existing plain `.pgp` spelling is converted to the requested `.gpg` alias only
when both identities are equal. Custom keys, embedded keys and fingerprint
restrictions are not broadened. Repeated normalization is tested as idempotent.
APT's `Signed-By` selects the allowed repository keys; package-owned keys belong
under `/usr/share/keyrings` and must remain readable by `_apt` [2]. This change
does not disable signature verification, import a new key or change key ownership.
It also does not establish that a remote mirror currently publishes every suite;
remote repository availability was not tested here.

## 2. Perl and Python lifecycle corrections

### Perl subprocess adapters

`Managed::Process` was already the repository's shared bounded process supervisor
and is already staged by `scripts/late/core.sh`. The duplicated capture routines
in these callers now delegate to it, preserving their deadline limits:

- `lib/perl5/site_perl/whisper/WhisperMode/Systemd.pm`
- `lib/perl5/site_perl/labwc-adb/AndroidADB/Command.pm`
- `libexec/labwc-output-watch`

This removes duplicate blocking post-KILL waits and uses the existing supervisor's
monotonic deadline, multiplexed bounded output, inherited-SIGCHLD handling,
process-group termination and bounded reaping. The shared supervisor itself was
not rewritten. Real, short-lived Perl fixture processes exercised exit status,
both output streams, signal handling, inherited pipe writers and cleanup.

`zram-writeback/Zram/Setup/Mapper.pm` now uses bounded shared capture for its short
storage-control commands instead of sequential unbounded stdout/stderr reads.
A child killed by a signal is no longer misreported as successful by shifting the
wait status alone. No storage device or cryptsetup operation was run during review.
`digital-assets/DigitalAssets/Context.pm` uses a five-second bounded notification
command, so an unresponsive notification server cannot hold a completed action
open indefinitely.

Interactive payloads and intended long-lived daemons were not indiscriminately
converted to detached subprocesses. A helper inside an existing service should
remain supervised by that service unless its launch contract requires a new one.

### Python changes

`labwc_managed_app/session.py` explicitly passes validated environment-variable
names to `systemd-run`, rather than relying on the environment of the client
process to become the service environment. Bitwarden also validates its Wayland
socket before handoff. Working directories are preserved. Passing `--setenv=NAME`
uses the client's value without embedding that value in the argument vector [3].
This is an argv-leak reduction, not a claim that a same-user environment is secret.

Bitwarden, native and compatibility launch paths now name each service uniquely.
Re-entry markers are consumed and accepted only in the expected service cgroup;
an inherited or manually set marker alone no longer skips the handoff. Explicit
stop/escalation, no-restart and private-umask settings are added where missing.
Existing ChatGPT private logging pipes and its dedicated profile transition are
preserved.

`labwc_managed_app/dbus_proxy.py` reads teardown diagnostics nonblockingly after
reaping the proxy. A descendant retaining the stderr write end can no longer
hold teardown waiting for EOF. Output remains bounded and sanitized. This fixes
that teardown path; it is not a redesign of live proxy logging.

`labwc_firewall/nftables.py` now rolls back candidate files on command-runner
exceptions during validation. A raised reload error also attempts to restore
both the prior on-disk configuration and live rules, since a timed-out reload may
have partially completed. Restore failures remain explicit errors.
`labwc_firewall/files.py` refuses symlink, nonregular, multiply-linked, foreign-owned
or incorrectly permissioned lock files. Firewall effects were mocked in tests;
no live ruleset was changed.

## 3. libexec, terminal and AppArmor integration

### Desktop launch routing

`libexec/labwc-wrap-desktop-files` no longer treats `NoDisplay=true` as a reason to
skip an application. Such entries remain launchable as MIME handlers [4]. Hidden
or non-application entries remain untouched. Managed-executable recognition checks
the executable rather than arbitrary arguments. An already-managed main `Exec`
no longer prevents unmanaged Desktop Actions from being wrapped.

Where there is a usable `Exec`, D-Bus activation is disabled in the local override
so desktop launchers do not bypass that command. The specification otherwise
allows `DBusActivatable=true` to bypass `Exec` [4]. Package-owned files and
administrator-owned local overrides retain the existing protection rules.

`Terminal=true` applications now launch through `labwc-terminal -e`, and the local
override becomes `Terminal=false`. This starts the terminal in the service and
keeps its interactive child attached to its PTY, rather than sending the child
into a separate noninteractive service.

`usr/local/bin/labwc-terminal` now uses standalone Foot rather than footclient and
routes Foot, Kitty and the terminal fallback through the generic Wayland service
launcher. Each terminal launch can therefore own its shell descendants instead
of adding them to a persistent Foot server's cgroup. The existing Foot server
units were not deleted. The three standard terminal executable paths retain
host administration access; additional filesystem/IPC sandbox properties are not
applied to them. Other generic application policies are unchanged.

The launch contract remains a user **service**, not a compositor-owned scope:
`Type=exec`, `ExitType=cgroup`, `KillMode=control-group`, session-target dependencies,
bounded stop escalation and collection. Systemd specifically supports
`ExitType=cgroup` for graphical applications with an unknown process tree [5].
These are lifecycle boundaries; they do not make mutually hostile applications
under the same UID into separate security principals. Direct manual execution
outside managed launchers and vendor single-instance IPC to an already-running
application are not transformed into per-window isolation by this change.

### Import and policy wiring

`libexec/labwc-ai-model-info` explicitly imports the staged Python 3.14 package
under isolated Python, validating the system-owned parent chain and its three
source modules. It no longer relies on the host interpreter's default minor-version
search path. `libexec/labwc-firewall-action-root` also validates the full package
parent chain before privileged import.

`etc/apparmor.d/managed-desktop-wrappers` now permits the already-imported
`recovery.py` in both exact module allowlists. The affected Perl profiles receive
only the shared module's required directory/file read permissions. The terminal
profile makes the explicit transition to the generic launcher profile.
`managed-system-wrappers` adds the zram setup module read and self-signal rules
needed by its shared capture supervisor. No profile was disabled or globally
relaxed. Policy source checks are not a substitute for enforcing-mode testing.

The regenerated files are `d-i/forky/payload.tar.gz`, `payload.manifest` and
`preseed.cfg`. All 1,257 payload files were checked against both the manifest and
the current source tree, and the generator's `--check` passed. Deploy those files
with the extracted repository as one revision, not as a mixture with an older
payload or preseed pin.

## Validation results and limitations

| Check | Observed result |
| --- | --- |
| Complete `tools/tests` suite, four completed batches | 152 passed, no failures or skips |
| New targeted regressions, included in the preceding total | 43 passed; also rerun independently |
| Focused existing installer/lifecycle tests | 185 run: 182 passed, 1 failure, 1 error, 1 skip |
| Missing-fixture comparison against pristine upload | Both problematic tests also fail on the original ZIP |
| Shell parsing | 267 files, 545 parser checks passed |
| Preseed checking | 59 files passed; four generated command values survived private debconf read-back |
| Requested Python package files | All 33 passed syntax checks; staging/integrity manifests matched |
| Requested Perl library files | 18 syntax checks passed; 133 dependency-blocked |
| Requested libexec files | 53 syntax checks passed; 18 dependency-blocked |
| Broader audit including hooks/installers | 428 syntax/data checks passed; 120 unit lexical checks; 155 dependency-blocked; no actual syntax failures |
| Payload and generated pin checks | Passed; 1,257 source/payload/manifest byte matches |

The two pre-existing problematic tests require `todo/apparmor.log` and
`todo/managed/apparmor/apparmor.log`, which are absent from the uploaded archive.
They were not fabricated, and their assertions were not disabled. The skipped
focused test requires `rsyslogd`, unavailable here. See
`baseline-missing-fixtures.log` and `focused-existing.json` for exact test IDs.

The environment supplies Python 3.13, not 3.14, and lacks Moo-related Perl
prerequisites. Dependency-blocked checks are not passes; runtime tests of the
changed core-Perl capture adapters do not replace full dependency-loaded module
checks. An isolated attempt to obtain test prerequisites could not resolve the
Debian mirror; no package or binary build was used as a workaround.

Broader installer sweeps exceeded command execution windows during bootstrap and
root-login tests. Their partial logs are retained but are not counted as completed
passes. The initial unbatched tools run also exceeded its window; the subsequent
four complete batches establish the 152-test result above. Native compiler tests
were excluded and native compiler/build-tool subprocess invocations were guarded
in the batch runner. No native compiler was invoked.

There is no live systemd user manager, Labwc session or Debian Installer in this
container. No end-to-end installation, real GUI launch/cgroup cleanup, AppArmor
policy compilation/loading/enforcement, GPU or storage acceptance was performed.
Unit lexical checks do not resolve all vendor dependencies or prove service start.
The implementation and offline regressions are delivered; these environmental
limits must not be read as successful live acceptance.

### Reproduce non-build checks

Run the tests in a disposable root environment with Python, Perl and the normal
repository test prerequisites. Ownership-specific tests skip without root.
These commands do not build native programs:

```sh
python3 -B -m unittest discover -s tools/tests -p test_scoped_lifecycle_keyrings.py -v
python3 -B -m unittest discover -s tools/tests -p 'test_*.py' -v
python3 -B tools/build.py --check
python3 -B tools/check_shells.py --output /tmp/scoped-shell-check.json
python3 -B tools/check_preseeds.py
```

Do not use an unrestricted whole-repository test target under a no-compilation
constraint: the original repository contains two NVIDIA compiler-based tests.

### Installed-host acceptance still needed

On a disposable machine installed from this revision, verify that source
normalization completes and the backports records in
`/etc/apt/sources.list.d/debian.sources` contain the requested key. Launch a native
application, Bitwarden, a compatibility application, a MIME-only entry, a Desktop
Action and two terminals through their normal managed entry points. Inspect their
units and control groups, then stop one test application's unit and verify that
only its descendants disappear. Check session logout cleanup, terminal privilege
elevation behavior and enforcing-mode AppArmor logs. Firewall rollback should be
exercised only in a disposable VM with console access.

Useful read-only inspection commands in that session:

```sh
systemctl --user list-units --all --type=service 'labwc-*'
# Replace this with one of the application service names listed above.
unit=labwc-wayland-foot-REPLACE_WITH_ACTUAL_ID.service
systemctl --user show "$unit" -p Type -p ExitType -p MainPID -p ControlGroup \
  -p KillMode -p TimeoutStopUSec -p PartOf -p Requisite
```

## Evidence and references

The dated validation folder includes the complete requested-scope inventory,
old/new file hashes, runtime/test diff, actual keyring check, completed test logs,
explicitly incomplete logs, broader audit and payload content verification.
The original historical reports elsewhere in the repository were retained and
should not be mistaken for new validation runs.

Primary documentation consulted for the relevant contracts:

1. Linux `open(2)`, `O_NOFOLLOW` and `ELOOP`:
   https://www.man7.org/linux/man-pages/man2/open.2.html
2. Debian Forky `sources.list(5)`, `Signed-By`:
   https://manpages.debian.org/forky/sources.list%285%29
3. systemd `systemd-run(1)`, transient services and `--setenv=NAME`:
   https://www.freedesktop.org/software/systemd/man/259/systemd-run.html
4. Desktop Entry Specification, recognized keys:
   https://specifications.freedesktop.org/desktop-entry/latest/recognized-keys.html
5. systemd `systemd.service(5)`, `Type=exec` and `ExitType=cgroup`:
   https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
