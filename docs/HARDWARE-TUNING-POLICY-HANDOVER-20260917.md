# Hardware tuning: confirmed PPD handover and lifecycle correction

Revision: 2026-09-17, follow-up to `HARDWARE-TUNING-REFACTOR-20260917.md`.
Basis: the complete previously delivered `debian-preseed-de-refactored-20260917.tar.gz`.

## Scope and acceptance boundary

This revision implements the requested Fuzzel-to-broker policy handover, PPD service
lifecycle, autostart/reset behavior, notify-send AppArmor permission, and explicit
system/user slice distinction. It does not change hardware values, release pins,
profile enablement, application isolation, resource delegation or unrelated
installer behavior. The entire previous repository is retained, including its
prior fixes, tests and historical validation evidence.

The source implementation and its offline tests are complete for this revision.
Physical Forky/systemd 261.2 execution, a real graphical confirmation, loaded
AppArmor enforcement, reboot, suspend/resume and CPU/GPU stability remain the
installed-host acceptance boundary. They are not represented as container passes.
The exact completed checks and any whole-repository failures are recorded in
`../validation/policy-handover-20260917/summary.json` and its referenced logs.

## User-visible behavior

| Selection | Custom tuning | PPD and boot policy |
|---|---|---|
| Start Automatic Tuning | A second, cancel-first Fuzzel popup requires confirmation. Restore old owned settings, acquire policy ownership, then start arbitration. | Stop and runtime-mask PPD for a temporary start. Existing boot preference is retained; already-enabled boot mode uses persistent exclusion. |
| Stop Automatic Tuning | Stop automatic and manual selections, restore owned controls, stop the active autostart marker. | Remove masks as necessary and start PPD. Retain custom boot enablement if it was enabled. |
| Enable Autostart Tuning at Boot | Confirm, enable and start now. Repeating an already-healthy boot enable avoids hardware reset/reapply. | Disable and persistently mask PPD, verify it is stopped. Enable and start the custom boot marker. |
| Disable Autostart Tuning at Boot | Disable and stop automatic/manual tuning and the boot marker, after verified hardware restoration. | Remove runtime and persistent PPD masks, enable PPD and start it unless already active. |
| Reset Hardware Tuning | Explicitly retry restoration; clear automatic/manual tuning and custom autostart. | Restore enabled, unmasked, active PPD unless already default. |

Cancelling or escaping the confirmation submits no mutating request. Free-form
Fuzzel text is not interpreted as a command. First manual Intel acquisition uses
the same confirmation. An active local seat and authenticated peer UID are still
required for a non-root acquisition; confirmation is not authorization by itself.
The CLI accepts the explicit `--confirm-policy-owner` flag on acquisition actions.

A temporary Stop while custom boot mode remains enabled must remove the persistent
PPD mask because a masked unit cannot start. It starts PPD for this boot but does
not change the saved custom boot preference. On a new boot the broker reinstates
persistent exclusion before applying custom hardware policy. Disable and Reset
instead restore PPD as the persistent boot default. An explicit Stop survives a
broker restart or socket reactivation within the same boot.

Stop also clears manual selections intentionally: restarting PPD while a manual
Intel policy remained active would violate the required single-owner behavior.
Harmless application leases and their applications are not killed. The broker
stays available for status, recovery and further requests; stopping tuning is not
the same as terminating the control-plane service.

## Privilege separation and service operations

The existing desktop client, root broker and hardware worker remain separate.
The new root-only `/usr/local/libexec/hardware-tuning-policy` helper has a fourth
enforced AppArmor profile and one finite operation argument. Its implementation,
`policy_owner.py`, manages only these immutable unit names:

- `power-profiles-daemon.service`
- `hardware-tuning-autostart.service`

It uses libsystemd's typed system-bus API for unit state, unit-file operations,
manager reload, start/stop and bounded job cancellation. It executes no shell or
systemctl and accepts no client-supplied unit names, paths or commands. The
privileged entrypoint removes an inherited alternate system-bus address. No new
sudoers rule, polkit grant, setuid file or desktop system-bus authority is added.

The broker no longer writes the systemd enablement directory. PID 1 applies
unit-file changes in its own namespace, so the broker's writable paths remain
its runtime state and the already-required hardware-worker sysfs paths; AppArmor
separately denies the broker hardware writes. The policy helper can read hardware
journals and take their locks, but cannot write hardware or execute other tools.
AppArmor's D-Bus method rules do not filter argument values; the immutable helper
allowlist is explicitly part of the trusted boundary. Actual D-Bus/AppArmor
mediation support must be checked on the target, not inferred from compilation.

The helper bounds individual bus calls, its aggregate work and start/stop jobs.
It waits for job removal and verifies the required final unit state. It attempts
bounded cancellation of an unfinished job on error. A failed query is not treated
as evidence that a policy owner is absent. Unit-file calls are followed by an
explicit manager reload. Mask operations never force replacement of a foreign
unit file.

## Ordering, recovery and failure behavior

A plain PPD stop is insufficient because it does not prevent later D-Bus
activation. A runtime mask protects temporary ownership without changing its
persistent enablement. A persistent mask protects boot-enabled custom policy.

Systemd can skip a masked unit's installation metadata when disabling it. Boot
handover therefore restores and locks out all custom hardware first, ensures the
custom boot path is enabled, removes old mask layers, disables PPD, then masks
and stops it. Exclusion is verified before any custom hardware apply. The brief
unmasked interval contains no owned custom hardware settings. Permanent handback
enables the default PPD boot path before disabling the custom boot path. This is
ordered, recoverable coordination, not an atomic multi-call systemd transaction.

The broker writes release intent before restoring controls. The policy helper
independently holds every installed vendor's transaction lock through the
empty-journal check and PPD handback. Nonempty, invalid or unsafe recovery files
block handback. Root-owned regular files, ownership/modes, path ancestors,
symlinks, hard links and strict JSON shapes are checked. The helper records its
claim before the first policy mutation; runtime state is preserved through a
broker restart. Existing version-1 broker state is accepted and upgraded to the
version-2 recovery format.

If a restore fails, PPD remains excluded and recovery evidence remains visible.
Polling cannot reapply retained manual intent while handback is pending. A policy
failure is exposed in status/notifications, not hidden by a successful-looking
return message. A failed initial boot activation attempts to undo its new boot
preference and restore the default owner, subject to successful hardware recovery.
Explicit Stop/Reset retries are available; pending journals are never deleted to
silence failures.

Broker termination runs hardware recovery before independent policy recovery.
Policy recovery does not restart PPD while the system is shutting down. Sleep
keeps the existing restoration/paused-state interlock, and resume does not erase
thermal or ownership faults. An Intel fault releases remaining custom controls
before returning PPD. Other policy managers are checked before both acquisition
and PPD handback so PPD's vendor `Conflicts=` cannot implicitly stop them.
Thermald and kernel/firmware thermal protections are retained.

NVIDIA-only installations manage the custom marker but never query or alter PPD.
The common read-only bus metadata module is staged for either installed vendor;
Intel hardware permissions remain gated. A genuinely absent PPD is reported as
absent rather than installed or represented by a phantom masked unit. Recover-all
skips an uninstalled backend unless an existing recovery journal requires it;
unsafe journal symlinks still fail rather than being mistaken for empty state.

## Systemd roles and slices

The socket-activated broker deliberately has no `Conflicts=power-profiles-daemon.service`: a status/report request must not stop the default policy owner as a dependency side effect. The confirmed, journaled handover controls that transition instead.

The system broker, short-lived worker/helper children, system autostart marker
and system sleep service use `system.slice`. Explicit `Slice=system.slice` is
rendered in the three system service units. No new quota, weight, affinity,
delegation or custom system slice is introduced.

Application lease services remain unprivileged in the user manager's
`background.slice`, with their existing Labwc session lifetime. Their Intel/NVIDIA
`.target` units are dependency groups, not process containers, and do not receive
`Slice=`. Moving a target or user lease into the system manager is not a way to
place hardware writers correctly; the writers already belong to the system
broker's cgroup.

The autostart service is a `Type=oneshot`, `RemainAfterExit=yes` marker with
`BindsTo=`/`After=` on the broker. Its root-only marker entrypoint does not call the
broker. This avoids a synchronous StartUnit deadlock in which the broker waits
for a client that is itself waiting for the broker lock. Fresh-boot initialization
reads persistent enablement, while same-boot initialization honors saved Stop.
The marker's active state indicates lifecycle coordination, not successful
physical hardware tuning; status includes actual applied profiles and faults.

## AppArmor denial correction

The desktop profile's existing owner-qualified process metadata rule now includes
`cgroup`:

```text
owner /proc/[0-9]*/{stat,status,cgroup} r,
```

This covers notify-send/libsystemd's UID-owned cgroup metadata read without giving
it proc writes, cross-user reads, unrestricted `/proc/**` access, hardware access
or privileged unit-management rights. The rest of notify-send's inherited
confinement remains intact. Offline policy compilation is not a claim that this
specific denial has been reproduced or cleared under a live target kernel.

## Preservation and deployment

The previous resctl-bench fix remains unchanged: protected release documentation
and provenance use `/usr/local/share/doc/resctl-bench`; `/data/docs` ownership,
permissions and user content are not altered. Release version/digests and all
thirteen profile files remain byte-for-byte unchanged by this follow-up. Main
profiles retain Intel/NVIDIA tuning gates; Flex retains Intel enabled/NVIDIA
disabled; other profiles retain both disabled. Initial boot autostart stays off.

Publish the new repository, `payload.tar.gz`, `payload.manifest` and generated
`preseed.cfg` as one coherent snapshot. The archive is the complete served source,
not a live update applied to already-installed hosts. Existing installations need
the matching runtime modules, helper, enforced policies and regenerated system
units deployed together; copying only the launcher or only a unit is insufficient.
Do not replace a running controller while it owns hardware or discard recovery
journals. Use the normal installation path for fresh hosts and the acceptance
matrix in `hardware-tuning/ACCEPTANCE.md` for target qualification.

## Validation evidence

`validation/policy-handover-20260917/` retains the final focused tuning tests,
resctl regression run, full-repository runs, tooling tests, shell/preseed checks,
generated-unit/AppArmor checks and build consistency results. A full suite was
repeated after the final pending-handback polling guard; its final log is the
one used by `summary.json`. Any pre-existing failures are compared with the
unchanged previous delivery rather than hidden or edited out of unrelated tests.

The native D-Bus tests compile a harmless sd-bus fixture and exercise the actual
ctypes/libsystemd method signatures, message parsing, jobs, errors and deadlines
on an isolated bus. They do not start the target's PPD or substitute for PID 1
integration. The offline systemd checker substitutes harmless executable lines
inside disposable roots; it validates configuration parsing, not boot execution.
AppArmor is compiled without kernel loading. See the machine-readable summary
for available tool versions and the exact acceptance limitations.

### Completed validation results

| Check | Result |
|---|---|
| Hardware tuning, including 52 new handover tests | 168 passed |
| resctl-bench regression suite | 67 passed, 1 skipped |
| Repository tooling | 179 passed |
| Generated systemd/AppArmor checks | 9 passed, offline |
| Shell parsing | 571 checks across 280 scripts passed |
| Preseed | 59 files passed |
| Offline systemctl unit-file semantics | 10 operations passed |
| Final whole-repository suite | 1,452 tests: 7 failures, 2 errors, 28 skips |

8 of the final failure/error entries reproduce in focused runs against the unchanged previous delivery. These cover historical AppArmor fixtures, missing Moo dependencies, an existing scope-drop-in expectation and an unrelated Fuzzel fixture error. Additional final-run entries are recorded verbatim in the validation summary: `test_opposite_role_fails_before_preflight_marker (test_repository_transport.RealBootstrapTests.test_opposite_role_fails_before_preflight_marker)`. No unrelated source or test assertion was edited.

The first whole-suite run also encountered the unchanged bootstrap fatal-record test's eight-second wait limit. A focused unmodified current run retained that failure. Separate, explicitly labeled extended-observation diagnostics found the correct fatal record after 15.523 seconds in the previous snapshot and 8.344 seconds in the new snapshot. Those diagnostic observations are not substituted for a standard test pass.

## Primary references used for implementation review

- systemd `systemctl(1)`: masking, runtime masks, enable/disable and reload behavior:
  <https://manpages.debian.org/unstable/systemd/systemctl.1.en.html>
- systemd manager D-Bus API and typed method contracts:
  <https://manpages.debian.org/unstable/systemd/org.freedesktop.systemd1.5.en.html>
- systemd resource-control and target semantics:
  <https://manpages.debian.org/unstable/systemd/systemd.resource-control.5.en.html>
  and <https://manpages.debian.org/unstable/systemd/systemd.target.5.en.html>
- AppArmor profile grammar and owner-qualified access:
  <https://manpages.debian.org/unstable/apparmor/apparmor.d.5.en.html>

The supplied low-level hardware report's one-policy-owner and saved-rollback
principle is retained. The new code automates the explicitly confirmed lifecycle
rather than bypassing the existing worker's conflict checks.
