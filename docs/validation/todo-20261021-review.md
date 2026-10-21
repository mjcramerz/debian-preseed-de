# Supplied log review and source repairs — 2026-10-21

## Scope and evidence boundary

Reviewed all 53 regular files under `todo/` as data, including the older
`todo/.~` journal. Twenty-one files are empty; they cannot establish successful
execution or the absence of failures. The main journal covers October 20–21;
the backup journal covers October 13.

Initial checkout: clean `mcr/main`, commit
`92ee334d663ba02961f512d9d282bf3af0812763`.

No tests, repository imports, shell syntax checks, native validators, package
operations, service operations, policy loads, device operations or host network
operations were executed. The only repository program executed was the reviewed
pure serialization build. No running installation was updated. The earlier
host-impact report and test stop remain in force.

The referenced `debian-preseed-de-audit.md` is absent from this checkout.
Relevant existing acceptance notes in `docs/validation/grub-timeshift-mok-20261018.md`
and `docs/validation/todo-20261018-review.md` were read as historical evidence;
they do not establish acceptance of these changes.

## 1. GRUB refresh activation burst

`todo/journalctl:3158–3310` records daily and weekly Timeshift jobs catching up
after resume. Path events, native backup hooks and managed completion hooks
request refreshes. Five refresh executions start during approximately four
seconds: four defer while the shared snapshot lock is held, and one completes.
The next requests hit the service start limit, which also fails its path unit.
The final daily snapshot completes, but its completion request is rejected.
`todo/managed/system/system.log:1–7` records the same terminal failure.

The source repair is confined to
`d-i/forky/hooks/target/etc/systemd/system/grub-btrfs-refresh.service`:

- Explicit finite activation budget: five starts per ten seconds.
- A five-second `ExecStartPre=/usr/bin/sleep 5` coalesces requests while the
  existing oneshot is activating. It runs before either Perl lock is acquired.
  Normal repeated requests therefore cannot consume that budget, including
  refreshes that defer immediately after preparation.
- The existing three-minute start deadline includes preparation. The separate
  fifteen-second stop deadline, service cgroup, private mount namespace,
  snapshot/refresh locks, atomic menu publication, hooks, edge watcher and
  fifteen-minute reconciliation timer remain intact.

This uses a packaged coreutils command and adds no daemon, compilation,
interpreter code or AppArmor permission. The service's managed Perl executable
retains its existing AppArmor attachment. Installation still stages the unit
through `scripts/late/btrfs-family.sh` with mode 0644.

The [systemd 262 path documentation](https://www.freedesktop.org/software/systemd/man/262/systemd.path.html)
describes start-limit propagation to path units. The
[service documentation](https://www.freedesktop.org/software/systemd/man/262/systemd.service.html)
defines preparation before `ExecStart`; the
[unit documentation](https://www.freedesktop.org/software/systemd/man/262/systemd.unit.html)
defines the finite activation budget. Native event-coalescing acceptance remains
unexecuted.

## 2. Scheduled Lynis logging and APT ordering

`todo/journalctl:3613–3622` shows the scheduled scan checking APT as
`apt-daily-upgrade.service` starts after resume. PKGS-7390 reports a nonzero
`apt-get check` result. This establishes overlap; the supplied logs do not
distinguish lock contention from dependency inconsistency. Upstream
[Lynis 3.1.7 PKGS-7390](https://raw.githubusercontent.com/CISOfy/lynis/3.1.7/include/tests_ports_packages)
discards that command's stderr, so the journal cannot supply the missing cause.

The managed native Lynis log and report are empty. The desktop menu already
passes managed paths; the package's scheduled service did not. Inspected the
Debian `lynis_3.1.7-1_all.deb` archive entirely as data, without extraction to
disk or execution. Its unit is `Type=simple` and runs
`/usr/sbin/lynis audit system --cronjob`. Its archive SHA-256 matches the existing
repository inventory:
`05c4390d8ff521773f6f9f4ae1813dc04f6cc2969ba35399086004062b69e6b9`.
This comparison establishes consistency with the recorded package bytes;
no new Release-signature verification was performed.

Added `hooks/target/etc/systemd/system/lynis.service.d/40-logging.conf.tmpl`:

- Preserve the package's cronjob mode and scheduling/resource settings.
- Order the scheduled scan after concurrently queued `apt-daily.service` and
  `apt-daily-upgrade.service`; do not pull either job into the transaction.
- Preflight existing protected native log paths with the existing helper.
- Pass the existing native log/report paths and disable terminal colors.
- Use umask 0027 with the existing root-owned, adm-readable log layout.

`scripts/desktop/components/logging.sh.tmpl` stages the drop-in through its
existing logging-unit loop and propagates publication failures explicitly.
The existing fetch/logging renderer resolves the two logging tokens before
publication. `scripts/desktop/verify.sh.tmpl` requires the installed drop-in and
rejects symlinks, multiple links, incorrect ownership or a mode other than 0644
in `desktop_verify_runtime_contracts`, before the account-only early return
and before service enablement. It also rejects oversized files, unresolved
installer tokens and missing or untrusted executable delegates. The broader
staged-file audit is deliberately skipped during installer late-command; the
new security checks are in the active verifier. The inspected Debian package
contains `/usr/sbin/lynis` as a root-owned regular executable with mode 0755,
which is compatible with this check.

This fixes missing scheduled native evidence and the observed scheduled-job
overlap. Ordering is not a lock against a later interactive package transaction.
It does not repair unknown package state or prove that PKGS-7390 now succeeds.
The collector-owned `scan.log` remains the desktop-menu capture path; scheduled
stdout retains the package's journal behavior. Native log/report files are the
scheduled diagnostic outputs.

## 3. Code inhibitor signal forwarding

`todo/journalctl:2990` records logind waiting thirty seconds for a delay
inhibitor attributed to an application D-Bus proxy before suspending. The
retained records do not conclusively attribute that proxy PID to Code.

Source review nevertheless establishes a defect in Code's system-bus filter:
it permits `org.freedesktop.login1.Manager.Inhibit`, but does not forward
`PrepareForSleep` or `PrepareForShutdown`. Electron subscribes to these signals
to close its delay-inhibitor file descriptor before the operation and acquire
a new inhibitor after resume or cancellation. See
[Electron's Linux power observer](https://raw.githubusercontent.com/electron/electron/main/shell/browser/lib/power_observer_linux.cc)
and [systemd inhibitor semantics](https://systemd.io/INHIBITOR_LOCKS/).
The filtered proxy requires explicit matching broadcast rules; a name-visibility
or method-call rule alone does not forward these broadcasts. See the
[xdg-dbus-proxy policy documentation](https://raw.githubusercontent.com/flatpak/xdg-dbus-proxy/main/xdg-dbus-proxy.xml)
and [filter implementation](https://raw.githubusercontent.com/flatpak/xdg-dbus-proxy/main/flatpak-proxy.c).

Added exactly those two broadcast rules to Code's existing policy in
`hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl`,
each restricted to the existing login1 destination, manager interface, signal
member and `/org/freedesktop/login1` path. The existing Inhibit method rule is
unchanged. No unrestricted login1 access, power-action method, inhibitor bypass
or timeout change was added. Existing proxy delegates and AppArmor execution
policy already support these filtered arguments.

An AST comparison against HEAD, reading both versions as data, proves that the
entire profiles module differs only by those two string constants in Code's
policy tuple. All other application entries, including Zoom and Discord, are
unchanged. This repairs the source contract; proving that it resolves the
historical timeout requires isolated native acceptance and PID attribution.

## 4. Other supplied findings

| Finding and evidence | Disposition |
| --- | --- |
| `network/veth.log:1–5`: Code route setup, readiness and ordinary cleanup | No failed veth event is recorded. No network source or host network change. This snapshot does not diagnose the earlier reported host veth incident. |
| AppArmor logs and all audit rotations | 443 AppArmor STATUS records, no supplied DENIED or ALLOWED records. The only recorded failed audited syscall is a glycin helper path probe returning ENOENT. This is not proof of complete live policy coverage. |
| Tailscale bootstrap failure in `todo/.~:1516–1563` | The node reports `NeedsMachineAuth` with an existing node key. Current source already returns 75 for pending approval, with matching systemd success/retry handling. External administrator approval remains required for that older node. |
| Tailscale connection resets after resume | Rebind/reconnection activity is recorded. No deterministic local route or veth defect is established. The nftables configuration remains selected. |
| CrowdSec console synchronization errors and initially disabled CAPI | Startup subsequently enables CAPI and the local bouncer processes decisions. Console approval is a separate remote state. Duplicate grok registrations and an absent external qBittorrent log do not establish failed local enforcement; later external-log discovery still needs target evidence. |
| Fail2Ban timestamp warning at resume | The old entry is a logind event immediately before an eleven-hour suspend. The jail starts successfully. This does not prove a timezone error or justify altering authentication timestamps or weakening the filter. |
| Lynis Docker status error, journal line 3787 | Upstream invokes `docker version` as root. The installed Docker wrapper delegates to `podman-devops-client`, which intentionally rejects root access and preserves the shared rootless service. Rootful fallback and borrowed account credentials would violate that contract. Rootless container auditing remains separate coverage. |
| Lynis expired certificate count and PKGS-7390 | The journal reports one expired certificate but does not identify it; the managed native evidence is empty. Neither arbitrary certificate removal nor automatic package repair is justified. These target-state findings remain open. |
| Lynis suggestions and long-running checks | Suggestions are not failed services. Existing policy choices, including account policy, compiler availability and sysctl differences, are not changed to raise a scanner score. DNS and certificate checks took approximately 37 and 50 seconds in this snapshot. |
| Chkrootkit suspicious files and `chkdirs` warnings | Listed dotfiles have package-attribution annotations; those are not content-integrity verification. `chkdirs` reports unsupported filesystems and cannot establish clean coverage there. Findings and the empty expected baseline remain visible; no blanket exclusions or generated clean baseline. |
| USB `UCSI_GET_PDOS failed (-5)` and BIOS/I2C diagnostics | Firmware/device acceptance remains open. No evidence establishes a safe repository-only correction. No driver disabling or firmware mutation. |
| Bluetooth identity-key warning | Missing controller state on first initialization is not evidence authorizing invented keys or changes to Bluetooth state. Native controller behavior remains unverified. |
| Sleep-inhibitor timeout, journal line 2990 | Code's missing lifecycle-signal forwarding is repaired as described above. Exact historical proxy attribution and native FD release/reacquisition remain unverified. No inhibitor bypass or timeout weakening. |
| Libinput processing lag immediately after resume | Two roughly 200–300 ms delays occur as the session thaws. No persistent compositor performance defect is established. |
| Code Chromium-option and Node deprecation warnings | The options are explicitly forwarded to Electron; the application starts. Node reports an upstream deprecation. No launcher failure or missing managed permission is established. |
| Crystal Dock deprecation | Upstream LayerShellQt API warning, without a recorded dock startup failure. No source build or vendor patch. |
| Older Waypaper monitor-enumerator fallback | The October 13 backup records fallback to All. [Waypaper 2.9](https://raw.githubusercontent.com/anufrievroman/waypaper/2.9/waypaper/options.py) explicitly implements that fallback. It is not evidence of a current failed wallpaper operation. |
| Native Labwc Xwayland messages | Existing behavior and exactly the private Zoom/Discord eligibility boundary are preserved. No Xwayland file, configuration or implementation is changed. |
| ClamAV, Timeshift snapshots, zram, initramfs and empty scanner/model logs | Freshclam records successful database checks/updates; snapshots complete; zram skips maintenance below pressure thresholds; no additional initramfs failure signature was found. Empty logs are inconclusive, not passing acceptance results. |

## 5. Serialization and static inspection

Executed `make build PYTHON='python3 -I'` after reading the Makefile,
`tools/build.py` and its `tools/publication.py` dependency. It reported
`built 1820 payload files` and regenerated only the three authorized products.

An independent Python standard-library data reader compared every archive
member with its current source bytes and manifest SHA-256, checked the complete
source/member set, canonical archive metadata and all three embedded preseed
pins. Result: 1,820 matching members, 34,731,887 uncompressed bytes. No payload
member or repository module was executed. The changed profiles module and the
embedded runtime verifier were parsed with `ast.parse` as source data; neither
was imported or executed. Static call-order inspection confirms that the Lynis
check precedes the account-only early return and service enablement.
`git diff --check` returned status 0.

| Generated product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `7c40b05bcd73e2be069780a0eac09bb94785979abe62dddc5a31dd157867be3e` |
| `d-i/forky/payload.manifest` | `a5a7d2a31a3b0760da600ba01dc5a6b7ff8ed0993a4a9abcff68f3f46e4f1bdb` |
| `d-i/forky/preseed.cfg` | `bd5dfabdd8904a7dc49f4141c9fb67d69c06ed3747e7895f6e7467af99b7d86b` |

Fingerprint of the five changed source files, hashing sorted seed-relative
name + NUL + bytes + NUL for each:
`280f46eb89371282f3baa06e9e604e181571c560add6c78e17840ab72e50e24d`.

Both root inventories still describe payload hash
`d32ffcba99151be9095d5014d5afefbb7bee6bcf88a97322424e7e9cc4cb50f7`.
They are stale relative to this build and were preserved. Inventory refresh is
a separate generation command; it was not run for this repair.

## 6. Unexecuted acceptance gates

No disposable target was prepared or used, no fixture revision or target image
was exercised, and no installed package version was queried. The required
target remains Debian Forky with systemd 262. Supplied logs identify Lynis 3.1.7
and kernel `7.2.11-x64v3-xanmod1`; the package archive inspection is separate
evidence and does not verify the running target's package revision.

Remaining acceptance, only after the test stop is lifted and a fully reviewed
disposable target is available:

1. Exercise simultaneous daily/weekly catch-up and bursts from all three GRUB
   request sources under systemd 262. Confirm the final menu includes both
   completed mutations, neither unit enters a start-limit failure, and genuine
   refresh errors remain visible.
2. Exercise lock contention, cancellation during preparation, helper failure,
   private-mount cleanup and periodic reconciliation. Verify last-good-menu
   preservation and the existing cgroup/start/stop deadlines.
3. Render and install the Lynis drop-in; reject unsafe policy/log destinations
   and unresolved tokens before activation. Queue scheduled APT and Lynis jobs
   together and confirm ordering plus native output paths and permissions.
4. Obtain the target's actual APT failure diagnostics and expired-certificate
   identity; determine their causes before selecting any target-state repair.
5. In Code's filtered bus, verify delivery of both prepare signals, inhibitor
   FD release when their argument is true and reacquisition after false. Verify
   unrelated login1 methods and broadcasts remain blocked. Attribute the
   historical proxy where evidence permits and measure suspend completion.
6. Verify firmware/controller behavior and native desktop launch/shutdown,
   retaining private Zoom/Discord launch/shutdown invariants.

Source serialization and static inspection do not establish these runtime,
hardware, policy or fresh-install acceptance gates. No deployment, publication,
commit or push was performed.
