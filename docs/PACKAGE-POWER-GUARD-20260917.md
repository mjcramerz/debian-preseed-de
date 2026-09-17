# Package ceilings and package-safe power actions

Release: 17 September 2026. Base: `debian-preseed-de-refactored-20260917.tar.gz`.

## Scope and outcome

This revision implements the requested 2 GiB APT publisher ceiling, the separate
4 GiB retained-archive ceiling, and package-lock-aware managed power actions.
It preserves every file path from the previous release, all 13 host profiles
byte for byte, existing desktop quiescence/guest shutdown policy, and the
previous retained-file hardening. It does not replace the repository with a
patch-only delivery.

Changes are restricted to these limits, their regression tests, managed power
entry points/worker/UI, the required systemd sleep guard, exact-helper greeter
authorization, corresponding AppArmor rules, installer staging/verification,
documentation, and regenerated release products. Historical reports remain
historical rather than being silently rewritten to claim new results.

## Exact size policy

| Boundary | New inclusive maximum | Implementation |
|---|---:|---|
| Python local APT publisher input/output | 2,147,483,648 bytes (2 GiB) | `local-apt-repository: MAX_DEB` |
| ChatGPT download/transport specification | 2,147,483,648 bytes (2 GiB) | `ArtifactLimits::MAX_DOWNLOAD_BYTES` |
| Retained Debian archive validation | 4,294,967,296 bytes (4 GiB) | `ArtifactLimits::MAX_DEB_BYTES` |
| Maximum permitted streaming-digest budget | 4,294,967,296 bytes (4 GiB) | `Atomic::sha256_file` and repository caller |

The publisher and retained ceiling are intentionally different. A retained
package larger than 2 GiB may pass retained-file validation but cannot be newly
published by the 2 GiB publisher. This is not an implicit exception to the
publisher policy. Application-specific smaller transfer/extraction limits
remain smaller; the change does not make every application's budget 4 GiB.
The publisher's existing derived extraction limits scale with its new finite
`MAX_DEB`; the retained 4 GiB ceiling does not replace those limits.

SHA-256 still reads 65,536-byte chunks, not entire archives into memory. The
regular-file, no-symlink, inode-change, header, package-identity, and diagnostic
checks from the previous repair remain. Tests use sparse valid Debian archives
for the large boundaries; no multi-gigabyte fixture is shipped in this release.

## Lock protocol and action ordering

`labwc-admin-action-worker` now implements `PackageLocks`. It opens only the two
fixed root-owned dpkg paths read-only, nonblocking, close-on-exec and no-follow.
It requires regular, single-link files that are not group/other-writable and
checks the opened inode against the pathname. Missing/unsafe/replaced files
fail closed. It never creates, deletes, truncates or repairs dpkg lock files.

The guard obtains **shared, whole-file POSIX record locks** using `fcntl.lockf`,
which conflict with APT/dpkg's exclusive record locks. The BSD `flock`
on `/run/labwc-power/action.lock` serializes managed power requests and the
whole system sleep cycle; it is
not incorrectly used as the package lock. Checking whether a dpkg lock file
exists would not establish whether another process holds its lock.

Both frontend and backend locks are checked. If either is busy, every partial
acquisition is released before waiting, preventing a frontend/backend lock-order
deadlock. The worker retries once per second with journal/status updates at
approximately 30-second intervals. It waits indefinitely: neither an elapsed
upgrade deadline nor a failed lock check permits proceeding with teardown.
It does not signal the lock holder or stop APT/unattended-upgrade services.

Once both locks are obtained, the worker keeps the descriptors and revalidates
them before destructive boundaries. The reservation excludes new package
writers while the managed action prepares and hands off. File descriptors live
in the PID-1-owned worker, not the initiating Waybar/pkexec cgroup. They are
released by normal completion, cancellation/error, or process termination;
there is no stale marker requiring deletion of a dpkg lock file.

### Desktop logout, reboot and poweroff/shutdown

The existing administrative authorization remains. The worker records the
compositor's invocation identity, checks other logged-in sessions, and
acknowledges the serialized request before beginning an unbounded package wait.
The service's startup deadline therefore does not terminate a legitimate long
upgrade wait. `RuntimeMaxSec=infinity` replaces the old 600-second overall
runtime; individual transport, save-dialog, desktop-stop and guest-hook
operations retain their finite timeouts.

While packages are busy, no save/close requests, clipboard clearing, compositor
stop, user-slice teardown or machine power call is performed. A user-session
notification explains the wait. After acquisition, the worker verifies that it
is still the original compositor invocation and rechecks other users. A queued
request cannot apply to a newly logged-in/restarted desktop.

Only then does it enter the existing unprivileged session-save/preparation flow.
Logout drains the invoking account's user cgroups. Reboot/poweroff synchronously
quiesce and verify the managed desktop, stop the existing optional guest hooks,
and perform the established **single** `systemctl --force` handoff. That existing
policy was not changed into a different shutdown transaction, and no double-force
or automatic retry was introduced. The worker holds its package reservation
after an accepted enqueue until PID 1 stops the worker. An uncertain power
handoff is reported, not retried automatically.

The existing single-force policy skips the normal unit shutdown-job sequence;
this release does not claim that every system service now receives a graceful
ExecStop. Its scope is package-lock exclusion plus the existing managed desktop
and guest quiescence policy. Replacing that policy would be a separate design
change.

### Suspend, idle and lid-triggered sleep

The desktop suspend worker locks the screen first, waits for both package locks,
and verifies that the same desktop is still locked afterward. If the user
unlocked it during a long wait, the old request is cancelled instead of
unexpectedly suspending an unlocked session. Suspend does not run the
application-save/close flow. Its systemctl call explicitly checks inhibitors
and does not use the old force option.

A second guard closes the asynchronous-suspend gap:

```
suspend.target
  -> systemd-suspend.service
     -> sleep.target
        Requires + After = labwc-package-sleep-guard.service
```

The new Type=notify guard is ordered before `sleep.target`. It sends READY only
after acquiring both package locks. Its startup and runtime limits are infinite;
`Requires=` makes startup failure prevent sleep rather than proceeding without
protection. It holds the locks throughout sleep preparation, the kernel sleep
operation, and post-resume hooks, and `StopWhenUnneeded=yes` releases them once
the sleep transaction finishes. The guard first acquires the common system power-action mutex, before trying
package locks. This prevents idle/lid sleep from freezing a desktop that is in
the middle of a logout/reboot preparation, and prevents concurrent desktop
actions while a sleep transaction is pending or active. It never holds package
locks while waiting for another action that needs those locks to finish.

The desktop suspend worker releases its action mutex after the asynchronous
systemctl enqueue returns. The sleep guard can then take over and recheck both
package locks; it does not wait for the suspend worker to resume. If a new
package transaction starts between those two reservations, the guard waits
again before allowing sleep. This avoids both a circular wait and an unguarded
sleep boundary.

This is necessary because successful `systemctl suspend` returns after queuing
the request, not after resume. The required target-level guard also applies to
ordinary logind/lid and idle/manual requests that use systemd's sleep targets,
without changing their configured idle or lid policy. Hibernation-family targets
that pull in `sleep.target` encounter the same guard; no hardware hibernation
acceptance claim is made.

### Greeter

The greeter no longer bypasses the guard with a raw login1 power call.
`greetd-power-action` invokes a fixed pkexec helper; the helper accepts only
poweroff/reboot and queues the same PID-1 worker in a greeter mode without
unprivileged desktop-save calls. `shutdown` is normalized to `poweroff` at the
public entry point.

The polkit rule authorizes only that exact helper for the configured, local,
active greeter account and rejects direct greeter login1 reboot/power-off and
ignore-inhibit variants. It does not give the greeter generic root execution.
Other user sessions are rechecked after waiting. The greeter uses the normal,
inhibitor-respecting power path, without a force fallback.

The small GTK power UI says the action is queued, prevents duplicate requests
and does not let its confirmation timer re-enable buttons during the wait.
The fixed frontend uses `systemctl --wait start`; when its unit ends with an
error or administrator cancellation, the UI restores the buttons.

## Installation, confinement and release integration

Installer component staging, target verification and firstboot validation now
include the new guard service, required sleep-target drop-in, and fixed greeter
root helper with their intended 0644/0755 modes. The firstboot report has an
explicit `desktop-package-power-guard` result.

The worker's AppArmor profile adds only `rk` access to the two exact dpkg lock
paths: read plus locking, not database writes. A confined attachment/transition
is added for the greeter helper. The sleep guard retains `ProtectSystem=strict`,
`NoNewPrivileges=yes`, an empty capability set and the worker's confinement; it
does not need `CAP_DAC_OVERRIDE` or writable dpkg directories. Its process/user
namespaces preserve host IPC semantics rather than silently changing identity.

All three generated release products were rebuilt together, then rebuilt again
with identical hashes:

| Generated product | SHA-256 |
|---|---|
| `preseed.cfg` | `9dc7e98a29ef8d34cea29028fa04096313b426dcab653f5113962d3795efdb05` |
| `payload.manifest` | `184c8291681dc3362ac7a3d833fc5497e7cebfaae5c070474ef2096f71c3a603` |
| `payload.tar.gz` | `c4f78d2ed1ce51995c14a66c5880fe75ea47d959b34b564eeeb2e00d6d8c09f7` |

Every one of the **1,358 payload members** matches its source file and manifest
hash. All **2,410 original-upload paths** and **2,452 prior-release file paths** are retained and all **13 profiles**
are byte-identical to the prior release. `source-and-payload-verification.json`, `scoped-source-changes.patch` and the
external tarball verification report provide the inventory/change evidence.
The final external verification also records a fresh extracted release's
build check and scoped regression results.

## Executed validation

| Check | Result |
|---|---|
| New package/power regressions | 38 tests; PASS; zero skipped |
| Archive/publisher boundary regressions | 26 tests; PASS; zero skipped |
| Existing scoped power/lifecycle tests | 90 tests; PASS; zero skipped |
| Greeter authorization rule | 17 cases PASS; isolated JavaScript evaluation |
| AppArmor aggregate compilation | PASS, exit 0; no kernel policy loading |
| Systemd worker/guard/vendor suspend graph | PASS, exit 0; no service activation |
| Browser/build/preseed/shell checks | PASS |
| Installer artifact rebuild | PASS; second rebuild identical |
| Payload contents | All 1,358 files match source and manifest |
| Host profiles | All 13 unchanged |
| Final complete main test suite | 1,335 tests; 17 failures, 2 errors, 28 skipped |
| Final complete tools test suite | 179 tests; PASS; zero skipped |
| Fresh baseline main suite | 1,295 tests; 18 failures, 2 errors, 28 skipped |
| Fresh baseline tools suite | 179 tests; 3 failures, 5 errors, 0 skipped |
| Broad audit limitations | 156 blocked dependency checks; 11 blocked tool checks |

The 38 package/power tests execute the real production lock implementation
against temporary files with independent processes holding real POSIX locks.
They cover frontend and backend contention, simultaneous writers, partial-lock
release, changed/missing/unsafe paths, no forced deadline, cancellation/descriptor
cleanup, session replacement, no teardown before acquisition, suspend readiness,
greeter routing, sleep/desktop action serialization, and UI cancellation/duplicate-click behavior. Power commands,
logind, GTK display startup and readiness endpoints are intercepted explicitly:
no test powers off or suspends the validation host.

The 26 archive tests exercise actual Perl method bodies and real `dpkg-deb`
inspection, including exact 2 GiB/4 GiB boundaries and a retained archive over
2 GiB. Moo constructors/catalogue transport are fixture boundaries in that suite,
not a claim of full application execution with every Perl dependency installed.

The existing scoped power/lifecycle suite contains 90 tests. Its fixtures and
assertions were updated only where the explicit guard and current managed-worker
interface changed. Stale tools-suite expectations
for already-retired process-killing APIs were replaced with assertions for the
actual quiescent managed-unit stop policy, lock reservation and handoff order.
They were not deleted or changed into unconditional passes.

The complete worker/greeter AppArmor aggregate was parsed with
`apparmor_parser -Q -T` against the repository's abstractions and host system
abstractions: exit 0. This was compile-only, not kernel loading or enforcement.
`systemd-analyze verify` accepted the worker, new guard and vendor suspend
dependency graph: exit 0. Only ExecStart paths in temporary verification copies
were remapped to source executables; no host unit was started. Seventeen polkit
cases were evaluated from the actual rule template in an isolated JavaScript
context, not against a live polkit daemon.

### Remaining validation issues and limits

The final main suite ran **1,335 tests**, with **17 failures, 2 errors and 28 skips**. The untouched previous release ran **1,295 tests**, with **18 failures, 2 errors and 28 skips** in this same environment. Counts include unittest subtest failure/error entries. **Every remaining final failure/error entry was also observed in the untouched baseline.** 

The remaining main-suite issues concern the absent original AppArmor audit-event fixture, missing Moo-dependent Perl execution, unchanged profile/provenance/resctl expectations, an existing launcher API expectation and desktop scope inventory. Any additional intermittent Spotify result is recorded by exact test identifier in `baseline-comparison.json`; no unrelated production fix was made to suppress it. The final tools suite result is **179 tests; PASS; zero skipped**, compared with **179 tests; 3 failures, 5 errors, 0 skipped** for the baseline.

One interrupted interim run (before the final sleep/action serialization change) exceeded the unchanged VM-bootstrap test's 70-second deadline. Isolated reruns of the same test passed in both the modified tree (61.074 seconds) and untouched baseline (56.149 seconds). The final full-run VM-bootstrap result was: `test_full_debian_preseed_vm_apply (test_debconf_protocol.DebconfProtocolTests.test_full_debian_preseed_vm_apply) ... ok`. The interim run is explicitly labelled interrupted and is not substituted for the final run. Raw final/baseline logs and the isolated reruns are all included.

The audit reports 156 blocked dependency checks and 11 blocked tool checks. Its exit status is not evidence that those checks ran successfully. The validation environment is Debian 13/trixie with systemd 257; the installer source targets forky. Offline checks in this environment are not a booted forky acceptance test.

An attempt to obtain the missing Perl modules used a separate APT configuration,
state and download cache, with host dpkg status read only and download-only
operation. The container could not resolve `deb.debian.org`; no packages were
installed, and missing dependencies remain explicitly blocked. The download
attempt and its failure are preserved in the evidence directory.

No booted unattended installation, live GTK/polkit session, service activation,
enforced AppArmor execution, real upgrade interrupted by a power request, or
physical suspend/resume was performed. Offline syntax, graph, mocks, and kernel
lock tests cannot certify those deployment properties or an entirely
failure-free repository. The broad audit's inventory-only, lexical structure,
unrendered-template and blocked-tool categories are not runtime passes.

## Deploying this release

Publish the complete extracted release atomically through the existing serving
process. Do not mix this preseed with the previous payload/manifest, and do not
copy only the worker or constants module onto an otherwise old release. Use a
fresh installer boot with the matching generated entry point. Do not bypass
checksum checks or clear the installer's fatal-state marker to resume a mixed
snapshot. The repository's existing destructive-install precautions remain.

This tarball is not a live-host migration utility. On a separately maintained
installed host, service files, AppArmor policy, polkit rule rendering, helper
modes and manager reloads must be handled as one reviewed deployment. Do not
stop/replace a committed power worker during an upgrade or shutdown.

Before deployment to valuable machines, use a disposable VM with the intended
Debian target and enforced profiles. During a genuine long-running package
transaction, separately request logout, suspend, reboot, poweroff and shutdown
through their managed entry points, and verify there is no destructive action
before both locks drain. Test the greeter route, idle/lid suspend, cancellation
while waiting, another session appearing, unlock during a suspend wait and
successful package-lock reacquisition after resume. Repeat with a missing/unsafe
lock path and confirm failure without power or session teardown.

To inspect a pending request on a deployed host:

```sh
systemctl list-units --all 'labwc-admin-action@*.service' labwc-package-sleep-guard.service
journalctl -b -u 'labwc-admin-action@*.service' -u labwc-package-sleep-guard.service
```

An administrator can cancel a **still-waiting, not committed** managed request
with `systemctl stop` and the exact instance shown by `list-units`. Stop the
power request, not dpkg/APT; never delete a dpkg lock file to force progress.
Cancelling a desktop worker after it has enqueued system suspend is not a promise
that the separate system sleep transaction has also been cancelled. For that
stage use the target's ordinary reviewed systemd job-management procedure.

The guard covers this repository's managed desktop/greeter actions and normal
systemd sleep-target paths. It cannot prevent arbitrary privileged direct
shutdown/reboot calls, custom code ignoring POSIX advisory locks, lock files
replaced by root, magic SysRq, firmware shutdown, or physical power loss. It is
not a global wrapper around `/sbin/shutdown`, and hardware-triggered reboot or
power-off outside the managed routes is not silently claimed to be protected.

## Reproduction commands and technical references

From the repository root:

```sh
python3 -B tools/build.py --check
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_retained_package_bounds.py
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_package_power_guard.py
python3 -B tools/validate.py --test-timeout 1800 --output-dir /tmp/package-power-validation
node validation/package-power-guard-20260917/validate-greeter-policy.js
```

The kernel ownership fixtures require root in a disposable validation environment;
non-root skips are labelled, not counted as passes. The optional JavaScript
check requires Node.js only on the validation host, not installed target hosts.

Protocol references consulted: Debian dpkg frontend locking documentation;
Python `fcntl.lockf`; Debian `systemctl(1)`, `systemd.unit(5)`,
`systemd.service(5)` and `systemd.special(7)`. In particular, `Requires` plus
ordering controls failure propagation, sleep calls are asynchronous, and a
single forced shutdown is not a normal unit-stop transaction.

```text
https://sources.debian.org/src/dpkg/1.17.13/doc/frontend.txt/
https://docs.python.org/3/library/fcntl.html
https://manpages.debian.org/trixie/systemd/systemctl.1.en.html
https://manpages.debian.org/trixie/systemd/systemd.unit.5.en.html
https://manpages.debian.org/trixie/systemd/systemd.service.5.en.html
https://manpages.debian.org/trixie/systemd/systemd.special.7.en.html
```
