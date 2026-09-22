# Greeter power and installation-integrity follow-up

Release date: 2026-09-22  
Base: `debian-preseed-de-refactored-2026-09-21.tar.gz`  
Base SHA-256: `0aceadd75af3e9c6b67ceaf121e21d79044d146d42bdfd524b5a62c73674565c`

## Result and scope

The complete prior repository is retained. This follow-up changes five existing
managed runtime/installation source files, adds one focused regression-test
module, and regenerates the three coupled installer products. It does not
replace the previous release with a patch-only archive.

The greeter's poweroff and reboot requests are verified to reach exactly one
`--force` in the privileged worker. The flag already existed in the prior
worker and was not duplicated at the GTK frontend. This pass corrects a runtime
mount conflict, adds greeter-session revalidation, preserves diagnostic output,
and adds a firstboot integration gate.

The final seven-stage validation run passed. These are offline, loopback,
fixture, GTK, namespace and parser checks, not a booted Forky installation or an
actual machine power cycle. Missing dependencies and previous unresolved
hardware/upstream findings remain explicitly outside the accepted test claims.

## 1. Power action wiring

The retained request path is:

```text
managed gtkgreet power panel
  -> /usr/local/sbin/greetd-power-action poweroff|reboot
  -> pkexec --disable-internal-agent /usr/local/libexec/greetd-power-action-root
  -> /usr/local/libexec/labwc-admin-action-root greeter-poweroff|greeter-reboot
  -> systemctl --wait start labwc-admin-action@UID-greeter-ACTION.service
  -> system-manager-owned labwc-admin-action-worker
  -> validated final single-force poweroff or reboot
```

The worker's final argument vectors are:

```text
/usr/bin/systemctl --force --no-ask-password poweroff
/usr/bin/systemctl --force --no-ask-password reboot
```

These lines document the worker implementation, not a request to run power
commands on the review host. Every destructive command was intercepted in the
new execution tests. No real power action was performed.

The public helper accepts one action only. The existing `shutdown` alias
normalizes to `poweroff`; arbitrary arguments, extra flags and injected command
strings are rejected. The fixed polkit rule remains limited to the configured
active, local greeter and the fixed root helper. It does not grant the greeter
an arbitrary `systemctl`, shell, or raw logind power bypass.

The GTK panel retains double-activation confirmation and disables repeat
submission while its helper is running. The root shim retains `systemctl
--wait`, so a failed or cancelled worker can reset the panel instead of leaving
it permanently queued. The worker itself is owned by PID 1, not by the GTK
client's cgroup. Both actions were also exercised through the actual Python
button methods with fake widgets and child transports: six failure, cancellation
and spawn-failure cases passed. The required seven greeter/GTK/polkit packages
are present in the desktop package selection. The review host lacks Python GI,
so this is not represented as a live gtkgreet/Wayland test.

### Meaning of the requested force flag

Exactly one `--force` delegates to the system manager and skips normal shutdown
of the remaining service units; process and filesystem teardown still occurs.
Two force flags bypass the manager and its normal teardown and can lose data.
This release uses neither double-force nor a legacy forced `reboot` command.
Single-force is not equivalent to a full orderly service shutdown. [1]

Before the handoff, the existing worker explicitly checks package locks and
shutdown blockers, stops installed guest shutdown hooks when applicable, stops
user managers, and verifies recursive cgroup emptiness. It retains the system
bus for the final PID-1 request. The existing block/weak-block inhibitor checks
are retained; the logind delay-inhibitor protocol is not provided by this direct
single-force handoff. No automatic escalation or retry is added after a failed
or uncertain final request.

## 2. Corrected runtime mount conflict

The shared worker previously had `ProtectHome=yes`, which makes `/home`,
`/root` and `/run/user` inaccessible. Its desktop branch also needs the
authorized user's runtime directory for systemd user-manager IPC. Those two
requirements conflicted. [2]

The service now uses:

```ini
ProtectHome=read-only
InaccessiblePaths=/home /root
```

This preserves home-directory isolation while retaining a read-only view of
runtime directories. Read-only filesystem mounts do not themselves prevent
communication through existing UNIX sockets. [2]

The worker still checks runtime ownership and mode and drops credentials before
contacting the selected user bus. AppArmor still restricts the sockets. The
service retains its capability bounds, `NoNewPrivileges=yes`, strict system
filesystem protection, restricted socket families, seccomp settings and
control-group cleanup. No writable home or runtime-tree bind mount was added.

The isolated namespace probe first reproduced inaccessible runtime IPC and then
verified that a read-only runtime mount allowed a temporary UNIX-socket
connection while denying new regular-file creation. The probe did not use the
host's real user/system bus and did not start the production unit.

## 3. Greeter session lifetime validation

An indefinitely package-blocked greeter request must not silently transfer to a
later greeter or interactive session. The worker now records the initial logind
session ID and leader PID, then rechecks that identity after acquiring package
locks and before runtime teardown.

The greeter must be a unique active, local session with the authorized UID/name,
class `greeter`, and PAM service `greetd-greeter`. Malformed, missing, duplicate,
or unexpected selected properties fail closed. A changed session ID or leader
fails closed. An interactive session cannot use the greeter branch to bypass
desktop save preparation. Other interactive users still veto machine power.

A separate same-account user-manager session is not mistaken for an extra
greeter. A fixture reproducing the supplied journal's `_greetd` UID 989,
`greeter` session and `manager-early` session passed. The implementation does not
hardcode that account or UID; it derives them from the authorized system account.

This does not claim an atomic transaction with every possible future logind
session change. The existing final runtime snapshot and no-new-manager checks
remain in place, and target-machine concurrency acceptance is still required.

## 4. Diagnostics and installation gate

Two stderr redirections previously discarded power-helper failures. The shell
client now preserves the power panel's stderr, and the panel lets the privileged
helper inherit that stream. The existing greetd journal configuration captures
those messages. Stdout remains discarded and privileged output is not buffered
inside the GTK process.

Firstboot now includes `desktop-greeter-power-handoff`. It checks the fixed
pkexec entry, greeter root dispatch, waited service start, single-force worker
handoff, session-revalidation marker and the corrected sandbox settings. A
mismatch increments the existing failure count and makes validation fail.

A disposable staged-file test executes this actual check block. The intact
configuration passes; reverting the sandbox or removing the forced handoff
fails. No production firstboot script or power command was executed by that
fixture.

## 5. Sweep and validation results

| Check | Accepted result |
|---|---|
| Browser generation, installer generation and preseed checks | All passed |
| Main regression suite | 2,295 tests run; 49 skipped; zero failures/errors |
| Tools regression suite | 179 tests run; 0 skipped; zero failures/errors |
| New greeter-focused module | 23 tests passed, included in the main total |
| Shell parser stage | Passed; detailed file/check counts in `final/shell-check.json` |
| Whole-source syntax/inventory sweep | 2,111 files; no reported syntax errors |
| AppArmor offline parsing | 37 top-level policy files; 0 failures; no kernel load |
| Shared worker unit parser | Passed with a disposable executable-path fixture; no service activation |
| Runtime mount probe | Prior conflict reproduced; read-only socket access and write denial verified |
| Firstboot gate probe | Intact configuration passes; both injected regressions fail as expected |
| Greeter button-method probe | Six reboot/poweroff error, cancellation and spawn-failure cases pass |
| Payload manifest | All 1,403 entries match source and archive contents |
| Prior repository preservation | All 4,054 prior files present |
| Protected prior files | All 28 protected hashes match, including private-Xwayland assets |

The main suite exercises installer transport/bootstrap, role staging, systemd
session ownership, transient lifecycle, native GTK menus, package-power locks,
inhibitors, runtime teardown, AppArmor source policy and other repository
contracts. Tests are not a substitute for running every target application.

The code audit classifies 482 executable checks as passing,
180 as structural checks,
509 as inventory-only,
158 as dependency-blocked,
0 as tool-blocked, and
2 as templates needing rendering.
Classification is deliberately retained: inventory or blocked checks are not
silently relabelled as successful runtime tests.

### Validation environment and attempts

The review host is Debian 13.3, systemd 257.9, Python 3.13.5, Perl 5.40.1,
AppArmor parser 4.1.0 and Node 22.16.0. Target configuration is for the requested
Forky/systemd 261.2; relevant semantics were checked against version-tagged
systemd 261.2 documentation/source. [1][2]

The first pre-change run of the newly added regressions failed as expected and
is preserved as `regression-before-fix.log`. The baseline power tests passed
before these corrections; the new cases specifically expose the gaps.

An initial broad run used `/usr/bin/python3`, which lacks the pre-existing
PyYAML test dependency on this host. That attempt's output is retained under
`full/`. The accepted, fresh complete run under `final/` uses the provisioned
Python environment containing PyYAML. No test was removed or made to skip to
hide that import failure.

Missing Moo/MooX/Type::Tiny-related dependencies and ShellCheck could not be
installed in the review container: repository name resolution failed and APT
could not obtain the packages. The attempt and exit status are retained. No
stubbed Perl modules or upstream source builds were used to manufacture a pass.
The shell parser checks still ran; ShellCheck did not. These dependency limits
must not be interpreted as proof that the target lacks those packages, or as
proof that all Perl behavior is validated.

The unit parser check replaces only the staged unit's ExecStart with
`/usr/bin/true` in a temporary file, avoiding an unavailable installed target
path. All sandbox/lifecycle directives remain intact for parsing. This checks
syntax on the available systemd, not service activation under systemd 261.2.

## 6. Change inventory and preservation

| Existing file | Disposition |
|---|---|
| `d-i/forky/hooks/target/etc/systemd/system/labwc-admin-action@.service` | Narrow managed-source correction |
| `d-i/forky/hooks/target/usr/local/bin/labwc-greeter-power` | Narrow managed-source correction |
| `d-i/forky/hooks/target/usr/local/libexec/labwc-admin-action-worker` | Narrow managed-source correction |
| `d-i/forky/hooks/target/usr/local/libexec/labwc-greeter-client` | Narrow managed-source correction |
| `d-i/forky/payload.manifest` | Generated installer product rebuilt |
| `d-i/forky/payload.tar.gz` | Generated installer product rebuilt |
| `d-i/forky/preseed.cfg` | Generated installer product rebuilt |
| `d-i/forky/scripts/firstboot/04-validation.sh` | Narrow managed-source correction |

New test: `d-i/forky/tests/test_greeter_power_followup_20260922.py`.

All earlier Waybar styling, native menu icons, wlsunset, AppArmor, networking,
and process-lifecycle changes are preserved. No upstream software source was
patched or compiled. No AppArmor permission was widened in this follow-up.
Private Xwayland remains limited to the existing Zoom/Discord architecture.
The greeter client's X11/Xwayland environment-scrubbing code is unchanged.

The existing builder explicitly sets regenerated `payload.tar.gz`,
`payload.manifest` and `preseed.cfg` to mode 0644. These three generated products
were 0600 in the supplied previous tarball; their normalized modes are recorded,
not hidden. No managed runtime source file's permissions changed.

Detailed old/new SHA-256 values and the source-only diff are in
`source-change-inventory.json` and `source-changes.diff`. Archive verification
is performed after packaging and supplied separately with the release.

## 7. Remaining target acceptance

No new runtime defect was observed in the accepted checks. Nevertheless, a
booted target acceptance test is necessary before treating the greeter's two
power actions as hardware-verified. On a disposable target or during a planned
maintenance window with all work saved, verify both actions separately, including
an APT/dpkg wait and a greeter-session replacement. Confirm that authorization,
block inhibitors, journal errors and failed cleanup do not trigger a force
fallback. Do not perform destructive validation on an active workstation.

The accepted target trace should show the package reservation, runtime cleanup
with empty descendant cgroups, and one `power handoff: systemctl --force ...`
entry for the selected action. A cancelled or rejected request should have no
such handoff. Use the journal for `labwc-admin-action@*.service` and the greetd
service; the actual greeter UID comes from the installed account, not a fixed
number in this report.

After reboot, verify firstboot validation, failed units, the user-session bus,
AppArmor enforcement behavior, networking and display startup. No actual
Forky boot, destructive power cycle, firmware/GPU test, Wi-Fi/EAP authentication
or full enforcement-mode desktop run was performed in this environment.

The prior report's unresolved Waybar tray accelerator defect, DRM/UCSI hardware
errors, and findings requiring more certificate/security-scan evidence are not
fixed by this greeter follow-up. Its firewall-state acceptance requirement also
remains. No warning suppression or speculative driver change was introduced.
Refer to the retained previous review for the evidence and dispositions; this
follow-up makes no new claim about whether a newer distribution package now
resolves that upstream tray defect.

## Evidence locations

The accepted run is `validation/followup-20260922/final/summary.json`. Supplementary
files include the 23-case greeter log, original failure reproduction, parser
reports, namespace and staged-contract probes, source-change hashes and payload
integrity report. The three supplementary probes are retained as reproducible
scripts in that directory. The prior review and all earlier evidence remain in
the complete repository.

## Primary references

[1] systemd v261.2, systemctl manual and power dispatch implementation:
https://github.com/systemd/systemd/blob/v261.2/man/systemctl.xml
https://github.com/systemd/systemd/blob/v261.2/src/systemctl/systemctl-start-special.c

[2] systemd v261.2, execution environment and filesystem namespace semantics:
https://github.com/systemd/systemd/blob/v261.2/man/systemd.exec.xml
