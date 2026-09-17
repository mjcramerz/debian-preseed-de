# Hardware tuning and resctl-bench follow-up - 2026-09-17

This release continues the complete `debian-preseed-de-hardware-tuning.tar.gz` codebase. It is not a replacement design or a partial patch. All prior files are retained. Two production Python files change; profile values, installation gates, application mappings, Waybar left-click actions, power policy, delegation and AppArmor permissions are not broadened.

## resctl-bench: fix the noexec staging failure

The supplied Flex and P15s audits both show `/var/tmp` on an ext4 filesystem mounted `nosuid,nodev,noexec`. The earlier installer extracted executables under `/var/tmp/resctl-bench-*/stage/.../bin/` and invoked `--version` there after dropping credentials. It already assigned the executable files mode 0755 and made its work directory traversable. Those mode changes cannot override the filesystem's `noexec` policy, so `rd-agent` could fail with `EACCES` / `Errno 13` before publication.

Exact audit archive members, line numbers and mount records are preserved in `validation/followup-20260917/audit-noexec-evidence.json`. The Linux `execve(2)` error documentation explicitly includes a filesystem mounted `noexec` among the reasons for `EACCES`: https://www.man7.org/linux/man-pages/man2/execve.2.html .

### Corrected installation sequence

1. Download and verify the unchanged pinned archive in a private, root-owned 0700 workspace under `/var/tmp`.
2. Validate archive paths, member types, sizes, checksum inventory and executable architecture as before. Never execute the release's installer or runtime tuning scripts.
3. Validate `/usr/local/bin` and its ancestors using the existing root-ownership/no-symlink/no-group-or-world-write guard. Reject an executable destination that itself has `ST_NOEXEC`; do not change its mount policy.
4. Create a unique root-owned `.resctl-bench-smoke-*` directory under `/usr/local/bin`. Copy only the verified, allowlisted executables into its `bin` directory. Recheck every copy's SHA-256. Only these temporary copies are executable for the version probes; the original download/extraction workspace stays private.
5. Set the staging directory to 0711 and the copied binaries to 0555. Run only `--version`, with the existing nobody UID/GID, empty supplementary groups, isolated environment, separate nobody-owned 0700 home and 20-second per-command timeout. Permission failures identify traversal, `noexec` and AppArmor as diagnostic checks rather than suggesting that protection be disabled.
6. Remove the temporary probe tree on normal completion and handled exceptions. Publish the original verified release only after all probes succeed, retaining existing provenance, ownership, mode, no-clobber and rollback checks.

No remount, mount namespace, direct ELF-interpreter bypass, `chmod 777`, root-run release binary, AppArmor relaxation, benchmark, release repinning or downloaded installation policy is introduced. Final binaries remain root-owned 0755 under `/usr/local/bin`; documentation/provenance remain under `/data/docs/resctl-bench`.

The temporary probe tree needs space for the verified executable files on their eventual destination filesystem. A read-only, full, inaccessible or `noexec` executable destination is an explicit installation failure, not a reason to bypass policy. As with other context-managed temporary directories, an uncatchable process kill or power loss can leave a root-owned staging directory; it is never reused as verified input by a subsequent invocation.

## NVIDIA: require complete temperature coverage for risky changes

A follow-up regression demonstrated that a valid temperature from one NVIDIA GPU previously masked a missing or invalid temperature on another enumerated GPU. That could let the shared overclock/power-increase interlock treat incomplete coverage as monitored.

The NVIDIA backend now returns an unknown aggregate temperature unless every enumerated GPU has a valid reading. When coverage is complete, it still returns the hottest GPU's reading. Existing engine safeguards consequently block positive offsets/above-default power before any write when coverage is incomplete, and detect loss of coverage while such controls are owned. No offsets, power limits, thresholds, profile values or driver permissions were increased. This deliberately conservative policy also applies when an enumerated but otherwise idle GPU lacks a sensor.

The added tests cover complete/missing/invalid readings, pre-write rejection, and health-interlock restoration. `hardware-before-fix.log` records the deliberately failing pre-fix reproduction; `hardware-tests.log` records the corrected results. All hardware writes in these tests are fixtures.

## Preserved integration

All thirteen host profiles retain their existing Intel/NVIDIA enable gates and values. The four requested main/flex profiles remain opted in for installation, with the other nine disabled. Hardware/class detection still decides which vendor assets are installed. Boot autostart remains independently opt-in.

The existing lifecycle wiring remains: actual systemd dash-prefix drop-ins for native browsers/Electron and additional apps; `Wants=`/`Upholds=` requests; `PartOf=` lease services; `StopWhenUnneeded=` profile targets; and per-activation pidfd-backed DevOps sidecars. Reset/manual/automatic semantics and the Waybar/Fuzzel menu are unchanged. CPU/cpuset/I/O delegation is unchanged.

Rechecked areas include the 32 gate combinations, all-profile configuration schemas, one-/two-vendor menus, left-click preservation, profile arbitration, multiple application/terminal lifetimes, recovery, report generation, native/Pascal/Ampere feature probing, and generated system/user units and AppArmor policies. See `validation/followup-20260917/README.md` for actual results and limits, not a hardware-acceptance claim.

## Publishing and installed-host acceptance

Publish the complete extracted repository atomically using the existing deployment workflow. The updated `payload.tar.gz`, `payload.manifest` and pinned `preseed.cfg` belong together; do not serve only a changed Python helper against the previous payload pins. The resctl-bench release URL/version/hash are unchanged.

On the next installation, leave `/var/tmp` mounted `noexec`. Check that the installer finishes all companion version probes and logs its successful resctl-bench installation before continuing desktop setup. Confirm root-owned 0755 `/usr/local/bin/{resctl-bench,rd-agent,rd-hashd}` files, provenance at `/data/docs/resctl-bench/INSTALLATION.json`, and no `.resctl-bench-smoke-*` tree remaining after ordinary success. No benchmark should run during unattended installation.

For hardware tuning, follow `docs/hardware-tuning/ACCEPTANCE.md` on the actual Flex/P15s hosts, using stock settings first. Native-build CPU/loader compatibility, systemd 261.2 runtime behavior, actual driver writes, enforced AppArmor and the graphical menu remain installed-host checks. This offline environment cannot honestly certify those operations on the target hardware.
