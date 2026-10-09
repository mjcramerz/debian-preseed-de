# Installed startup repair — 2026-10-08

## Scope and evidence

The task repairs the existing private kernel networking and managed application
integration in `debian-preseed-de`. The requested target is Debian Forky with
systemd 261.2. The supplied `systemd-version.txt` and local native analyzer both
report systemd 262 (262-1); Python is 3.14.8. The capability boundary was also
checked against the official systemd 261.2 service documentation.

Every file under `todo/` was read as bytes and strict UTF-8 text. Every one of
the 18,842 lines has exactly one source-file/line entry in the local evidence
index. Repeated log context was normalized for review while retaining all source
locations. There are 91 files, 22 of them empty, totaling 2,549,400 bytes and
9,445 normalized records. The final accounting check verifies that every input
still matches its original SHA-256 and no line was omitted or counted twice.
[todo-inventory.tsv](todo-inventory.tsv) records all file hashes and sizes.
Raw logs and the detailed source-line index remain private under `todo/` and
`.build/repair-review/`.

The starting working tree contained 91 changed paths: 88 existing files and
three deletions. The original 6,308-line diff and hashes were retained locally
before repairs. Changes were reviewed through their callers, publication maps,
service dependencies, policy includes and affected regression fixtures.
[preservation.json](preservation.json) records the final checks against that
starting state, including the three existing deletions and protected private
display sources.

## Repairs

| Defect | Evidence or reproduction | Change |
| --- | --- | --- |
| Broker JSON never rendered | `todo/managed/network/veth.log:1` reports `JSONDecodeError` at column 52. The original template used unprefixed account/port tokens. The production scalar renderer replaces only `__INSTALLER_*__` tokens. | Use the validated installer account and qBittorrent port tokens. Add a read-only broker `--check-config` command and invoke it on the staged target before enabling the service. |
| Networking and Podman dependency cascade | `validation-results.txt:20` has the single firstboot failure, `failed-units-present`. The broker and Podman socket failed; `journalctl:690` reports the unavailable Podman API socket. | Correct the common broker startup blocker and validate the same parser during installation. Preserve Netavark, rootless devops identity, socket permissions and helper lifecycle. |
| Thunar volume-monitor service cannot start | `todo/journalctl:1897` reports failure to drop capabilities; the next line reports `218/CAPABILITIES`. Thunar requires this monitor. | Remove the empty `CapabilityBoundingSet=` directive from this user service. Keep its host mount/UID view, `NoNewPrivileges=yes`, address-family restriction and existing AppArmor domain. |
| Broker cannot execute Forky's real `ip` path | Local packaged `/usr/sbin/ip` resolves to `/usr/bin/ip`. The native expanded policy had no execute grant for the resolved path; a new permission assertion reproduced the failure before the repair. | Permit only `/usr/{bin,sbin}/ip rix`. Keep fixed administrative arguments and the existing capability bounding set. No general executable grant was added. |
| Podman namespace file can be rejected by owner-qualified policy | Netavark persists the namespace at `rootless-netns/rootless-netns`; nsfs inode ownership differs from the surrounding devops-owned directory. This is a code-review finding, not a denial observed after successful broker startup. | Add non-owner-qualified read permission only for `/run/podman-devops/**/rootless-netns/rootless-netns`. Native expanded-policy checks verify read-only access to that endpoint and no access to another account's ordinary runtime data. |
| Codex signal cleanup releases networking too early | The signal cleanup path closed its lease before sending SIGKILL to the pinned PID-namespace init, unlike normal cleanup. | Send the final namespace signal before closing the lease. A regression verifies the sequence `SIGTERM`, `SIGKILL`, lease close. |
| Invalid configuration can block during open | Opening a FIFO for read can wait for a writer before the regular-file check. | Add `O_NONBLOCK` to the existing no-follow, close-on-exec open. A real FIFO fixture is rejected within a bounded child process. |

Only six production source paths were edited during this repair:

- `d-i/forky/hooks/target/etc/managed-veth.json.tmpl`
- `d-i/forky/hooks/target/usr/local/sbin/managed-veth`
- `d-i/forky/hooks/target/etc/apparmor.d/managed-veth`
- `d-i/forky/hooks/target/etc/systemd/user/labwc-gvfs-volume-monitor.service`
- `d-i/forky/hooks/target/data/codex/lib/codex.tmpl`
- `d-i/forky/scripts/late/security.sh`

Eight existing or already untracked test modules received configuration/policy
regressions or corrections to stale fixtures. Power fixtures now model completed
session/storage teardown and drive re-inventory; the worker's safeguards are
unchanged. The storage assertion follows the existing scoped variable. The
wallpaper fixture follows the configured shipped JPEG. The private-display
fixture verifies capability-free application exec independently of the
constructor's permissions. The ChatGPT inert child's PID readiness file is
published atomically so the observer cannot read an empty file.

## Validation

[results.json](results.json) retains the actual command arguments, outcomes,
skip reasons, policy results and coverage accounting. [contracts.log](contracts.log)
retains the final regression transcript. No software was compiled from source.
AppArmor parsing produced policy representations offline and did not load host
policy or write parser caches.

| Check | Observed result | Scope |
| --- | --- | --- |
| Twelve selected integration modules | 584 tests; 532 passed, 52 skipped, no failures/errors | Real local IPC, Bubblewrap startup gating, inert processes, shell publication and native parsers, with administrative operations and successful network setup modeled where required |
| Kernel networking module | 52 tests; one skip | Actual POSIX renderer, configuration parser/FIFO rejection, FD transfer, namespace rejection, nftables transaction parsing, helper readiness/exit protocol and process cleanup |
| Native AppArmor parser | 46 top-level policy files accepted | Disposable rendered tree, native rule expansion and effective file permission masks; no kernel enforcement test |
| `python3 -I -B tools/check_shells.py` | 352 shell files; 715 parser checks passed | dash, BusyBox ash, Bash and both generated preseed command boundaries |
| `python3 -I -B tools/check_preseeds.py` | 59 files passed; all four generated commands survived read-back unchanged | Disposable private debconf database |
| `python3 -I -B tools/build.py` | 1,724 payload files rebuilt; zero browser artifact changes | Existing offline pin, module, theme, logging, AppArmor mode and network-sharing publishing gates |
| `python3 -I -B tools/build.py --check` | Snapshot, pins and preseed current | Deterministic regeneration comparison |
| Independent archive read-back | All 1,724 members match source and manifest | Member set, SHA-256, regular-file type, mode, owner/group and timestamps; archive/manifest hashes present in preseed |
| Starting-state preservation | 69 unrelated initially changed files preserved; three deletions preserved; ten protected private-display sources preserved | Content hashes against the starting working tree |
| `git diff --check` | Passed | Whitespace/error-marker gate |

The final integration command used `/usr/bin/python3 -I -B` with an explicitly
inserted test directory and `unittest.main(module=None)`, followed by these
modules:

```text
test_kernel_veth_networking
test_thunar_native_drive_actions
test_codex_power_20260926
test_podman_incus_redesign
test_desktop_sandbox
test_managed_app_review_20260921
test_compz_qbittorrent_followup
test_apparmor_incidents_20261004
test_zoom_discord_private_xwayland
test_desktop_integration_20260914
test_computer_management_20260916
test_network_sharing
```

The 52 skips are environment limits: one isolated veth/DNS packet fixture cannot
write sysctls here, six private session-bus fixtures require the absent
`dbus-daemon`, 44 filesystem fixtures require actual root-owned test data, and
one historical audit replay requires the absent original `todo/apparmor.log`.
Its independent policy/fixture checks remain enabled.
No denied operation was retried through a different execution tool.

## Second review of the requested installed evidence

The implementation was reviewed again against `todo/fail`, `todo/Failing`,
`todo/journalctl` and every file below `todo/managed/`: 49 files, 11,503 lines,
1,650,916 bytes, including 22 empty files. The review retains source locations
for all 6,098 normalized messages. An expanded diagnostic scan includes exception
class names, missing forwards, deprecations and unavailable optional components;
all 112 matching records have exactly one reviewed disposition in
`results.json` under `second_review`. These are diagnostic records, including
informational matches, rather than 112 independent failures. Occurrence counts
include overlapping copies of the supplied logs.

The second implementation review covered:

- Broker configuration, caller credentials, namespace ownership, descriptor
  transfer, startup readiness, route selection, source validation and lease
  cleanup, including partial administrative failures.
- DNS DNAT, host and cross-namespace filtering, qBittorrent route/port pinning,
  and Discord's fixed loopback relay rules.
- Firewall reload ownership. It replaces only `labwc_filter`/`labwc_nat` and
  preserves the separate `managed_veth` guard table and active leases.
- Podman's configured helper probe, readiness/exit descriptors, persistent
  rootless namespace endpoint, Netavark bridge configuration and API activation.
- Native application handoff to the user manager, startup gating and pinned
  PID-namespace cleanup before lease release.
- Thunar's required monitor, D-Bus registration and policy, bounded fresh device
  inventory, fixed worker arguments, client cancellation and orderly stop.

No additional demonstrated production startup defect was found beyond the
repairs above. This review added evidence and validation records without further
production source edits. It reran the same twelve integration modules: 584 tests,
532 passed and 52 skipped, with no failures or errors. The current bundle passed
`tools/build.py --check`; independent archive read-back and starting-state
preservation checks also passed again.

| Remaining diagnostic class | Evidence and disposition |
| --- | --- |
| Broker, Podman and firstboot failures | Same rendered-JSON blocker and dependency cascade; source repairs and regression checks remain present. Live recovery is unverified. |
| GVFS/Thunar failures | Same capability-drop blocker in the user service; the service directive is repaired. Native device removal still needs actual hardware. |
| Public Xwayland missing | Expected under the private-only display contract. Labwc continued, and all ten protected compatibility sources remain unchanged. |
| Netavark timeout | The DHCP proxy stopped after 30 seconds of inactivity; the next journal line records successful deactivation (`todo/journalctl:1108`). |
| Tailscale initial stopped/warming state | Both health conditions later report `ok` (`todo/journalctl:802`, `:864`). The managed firewall owns filtering with `netfilter=off`. |
| Launcher synchronization reports zero processed files | The publisher counts changed outputs. Zero changes with no missing/invalid entries is an idempotent successful run. |
| CrowdSec early CAPI/reload/parser messages | Provisioning and packaged-parser notices; the firewall bouncer subsequently receives 15,000 decisions. Console synchronization separately requires external enrollment approval. |
| WirePlumber item activation abort | Follows the configured HDMI-node disables. Internal speakers are selected afterward (`todo/managed/apps/apps.log:103`). This establishes continued service startup, not live playback/capture success. |
| Crystal Dock deprecation | A packaged LayerShellQt API notice; the dock service starts. No package build or display change was introduced. |
| Kernel/ACPI/PCI/Bluetooth/UCSI notices | Hardware capability and firmware/resource messages. The UCSI failures and device capabilities remain hardware acceptance items. |
| Empty model/scanner files | No execution result can be inferred from an empty file. |

The raw audit file contains 998 syscall records, all `success=yes`. Across the
requested subset, 840 AppArmor messages are `STATUS` records; no `DENIED`,
`ALLOWED` or `ERROR` records were supplied. Those counts describe this capture
only; the failed broker did not exercise its later setup or enforced payload
paths.

### Syslog forwarding gap

`todo/journalctl:1094` reports **159 missed forwards to syslog**. Rsyslog starts
successfully at `:687`. The systemd 261.2 implementation increments this counter
when its nonblocking socket send returns `EAGAIN`, then reports the accumulated
count periodically. The warning's timestamp does not identify the exact period
of the missing forwards. [systemd 261.2 forwarding implementation](https://raw.githubusercontent.com/systemd/systemd/v261.2/src/journal/journald-syslog.c).

The current collector intentionally uses one credential-annotated socket input
without journal replay. Journal storage and the existing boot snapshot are
separate retention paths. This historical gap cannot be recovered into category
files by the startup repairs; complete category-file capture needs measurement
on the installed target. No speculative global queue tuning or duplicate input
was added. Empty per-category logs are not treated as successful application or
scanner execution.

The additional logging validation passed 18 catalog/routing tests and the native
rsyslog 8.2608.0 `-N1` parser over every rendered fragment. The parser used a
temporary include tree/spool and modeled owner/group names with the local
fixture account because the target-created `logreader` group is absent here.
It did not start a collector or establish target group provisioning, packet
delivery or loss-free logging. Commands and parser output are retained in
`results.json` and `contracts.log`.

## Remaining installed-host acceptance

The repository and generated installer bundle contain the repairs. They have
not been applied to or booted on the previously installed machine. This record
does not claim live application startup, live Podman container networking or
kernel AppArmor enforcement.

The supplied logs already show successful labwc/Waybar/Crystal Dock startup and
the NFSv4.2 client mounted at both its system and home locations
(`mounts.txt:31` and `:44`). No NFS mount-policy change was justified by this
incident. The complete indexed evidence contains no AppArmor `DENIED` or
`ALLOWED` audit records. That absence does not prove future enforcement success;
the broker failed before its administrative setup reached those paths.

On the intended installed target, acceptance still needs to establish:

1. Broker readiness and successful lease setup with IPv4 forwarding, the extra
   systemd-resolved listener and the enforced managed AppArmor profile.
2. Native application and ChatGPT/Codex launch, DNS/HTTPS access and complete
   process/link/rule removal after normal exit, stop and broker loss.
3. Rootless Podman API, Netavark container DNS/egress and published-port access.
4. qBittorrent incoming TCP/UDP through the selected router or VPN route.
5. Thunar native mount, sync, unmount and eject with actual removable hardware.
6. Zoom and Discord private-display launch and cancellation, with ordinary
   Wayland applications still unable to start public Xwayland.

CrowdSec's separate remote-console synchronization message requires remote
enrollment/approval; it is not a local engine or firewall-bouncer startup
failure. The official enrollment command also requires acceptance in the web
console. [CrowdSec enrollment reference](https://docs.crowdsec.net/docs/cscli/cscli_console_enroll/).
No enrollment token or credential was changed. Hardware UCSI,
Bluetooth and firmware/CPU capability notices remain hardware acceptance
items. No speculative kernel, display, firmware or router modification was
introduced.

## Primary references checked

- [systemd 261.2 execution documentation](https://raw.githubusercontent.com/systemd/systemd/v261.2/man/systemd.exec.xml)
  and its [system/user namespace availability note](https://raw.githubusercontent.com/systemd/systemd/v261.2/man/system-or-user-ns.xml).
- [Podman 5.8.6 rootless bridge and port-mapping callers](https://raw.githubusercontent.com/containers/podman/v5.8.6/libpod/networking_linux.go)
  and [helper invocation](https://raw.githubusercontent.com/containers/podman/v5.8.6/libpod/networking_slirp4netns.go).
- [Upstream Netavark namespace persistence and configured helper integration](https://raw.githubusercontent.com/containers/common/main/libnetwork/internal/rootlessnetns/netns_linux.go).

These references establish API/namespace contracts. They supplement the local
source/fixture checks and do not replace installed-host execution.
