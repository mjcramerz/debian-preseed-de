# LPL-746 firstboot namespace-read repair — 2026-10-09

This follow-up covers the complete replacement capture and the installer-state
folder copied from the installed machine. All **45 files and 8,936 physical
lines** were read, including all 4,935 lines of `installer.log`. File hashes,
line counts and the current validation results are in [lpl746-results.json](lpl746-results.json).
Captured command strings were treated as evidence; none were executed.
Credentials and signed URL parameters were redacted during diagnostic reads.

The [earlier LPL-948 record](README.md) retains its five-file inventory, test
results and original payload hashes. The earlier 91-file `todo/managed/`
review remains in the [October 8 record](../installed-startup-20261008/README.md).
Those files are absent from the current TODO tree.

## Installed failure and cause

| Evidence | Recorded result |
| --- | --- |
| `todo/fail`, 97 lines | Repeated `network_service_failed` events: `PermissionError` opening `/proc/self/ns/net`. Later Podman API dependency requests repeat the failed start. |
| `todo/journalctl`, 1,116 lines | The broker fails before readiness, hits its start limit, and the Podman socket hits its trigger limit after repeated dependency failures. The desktop services subsequently start. |
| `todo/apparmor.log`, 428 physical lines | Nine enforced `DENIED` records, all `profile="app-veth" operation="open" name="/" requested_mask="r" denied_mask="r" fsuid=0 ouid=0`. The remaining profile records are status/load events. |
| `todo/installer-state/`, 42 files, 7,295 lines | Installer configuration/staging completes. `20-firstboot.log` identifies `04-validation.sh` as the failed stage. `validation-results.txt` records exactly one failed gate and one session-capture skip. |

The firstboot gate is `FAIL failed-units-present`, listing only
`app-veth.service` and `podman-devops.socket`. Its final status is
`validation_status=fail failures=1`. The other recorded validation checks pass;
`desktop-session-graphics-capture` is skipped because the capture runs before
an active Wayland session. Firstboot validation has not been weakened.

The broker opens its host network-namespace FD at the beginning of
`EndpointPool.__init__`. With this enforced profile's existing
`attach_disconnected` flag, AppArmor mediates the nsfs handle as the exact
path `/`. Numeric procfs rules alone do not match that object. The previous
`/net:[0-9]*` pseudo-path rule also treats square brackets as a pattern class,
rather than the literal brackets in a real namespace name.

The resulting failure chain is:

1. The host namespace FD read is denied.
2. The broker exits before creating any `vethN-app` pair or publishing readiness.
3. Managed clients cannot obtain a namespace lease; Podman service activation
   fails its required broker dependency.
4. Repeated activation reaches the broker start and Podman socket trigger limits.
5. Firstboot rejects the failed units and leaves installation success pending.

## Narrow shared policy repair

The broker profile and common namespace-client abstraction now permit **only
read access to the exact nsfs root path**. Literal brackets are escaped for
network, PID and user namespace names as applicable:

```apparmor
/ r,
/net:\[[0-9]*\] r,
/pid:\[[0-9]*\] r,
/user:\[[0-9]*\] r,
```

The broker needs net/user forms; the shared client needs net/pid forms. The
Podman helper's explicit net form is corrected too. The exact root read grants
no child paths. Existing namespace ownership checks, transferred-FD checks,
host-namespace rejection, explicit ptrace peers, capability bounding and child
sandbox rules remain in effect. The mediation and pattern semantics are
documented in [apparmor.d(5)](https://manpages.debian.org/unstable/apparmor/apparmor.d.5.en.html);
the supplied denial establishes the actual path on this installed machine.

The common abstraction reaches the generic launcher, Codex wrapper/runtime,
ChatGPT, qBittorrent, Podman and Zoom/Discord compatibility parent. Native
compiler-mask checks cover **eight domains**, root-owned `/` and literal nsfs
reads, and absence of unrelated host-file permissions. The regression failed
before the policy repair and passes with it. The historical test expecting
7,223 complain-mode events skips when that old capture has been replaced; the
new enforced namespace regression remains active.

The privileged boot service still creates the full **32-pair pool before its
socket and `READY=1`**. Host names remain `veth0-app` through `veth31-app`; idle
peers are `vethN-peer`. Applications only lease pre-existing peers. The prior
shared capability/SIGTERM repair, `dpkg-deb` tar rule, fixed-name NetworkManager
exclusion, firewall and cleanup contracts are retained and covered by the
current integration selection. Private-display runtime behavior is preserved.

## Verification on the current sources

Exact command arguments, outcomes, transcript hashes and policy/source hashes
are recorded in [lpl746-results.json](lpl746-results.json).

| Check | Observed result and boundary |
| --- | --- |
| 12-module integration selection | **593 tests: 541 passed, 52 skipped**, no failures or errors. Includes the current native namespace permission regression. |
| Native compiler-mask regression | Exact root read is read-only in eight domains. Literal net/pid/user forms match as applicable. Unrelated root/other-user files and procfs FDs remain inaccessible to the broker/Podman helper. No policy is loaded. |
| Kernel networking selection within that run | Includes real isolated creation of all 32 DOWN pairs, stable indexes, recovery, native nftables transactions, and a blocked Bubblewrap init with namespace-FD and pidfd inspection. The full packet fixture is skipped. |
| Offline AppArmor parser | **46 policies pass**, with `-Q -K -j 1` in a private rendered tree; kernel loading and cache writes are disabled. |
| Canonical payload builder | `python3 -I -B tools/build.py` and `python3 -I -B tools/build.py --check` pass. This generates installer assets and archives; no software is compiled from source. |
| Archive read-back | **All 1,725 members** match source bytes and manifest hashes; archive metadata and preseed pins match. |
| Preservation | Starting unrelated source changes, identifier-only changes, three user-owned deletions and ten private-display/compatibility sources pass the preservation check. |

The skips are **44 root-owned filesystem fixtures**, **6 unavailable private
session-bus fixtures**, **1 replaced historical complain capture**, and **1
isolated packet fixture blocked by denied sysctl writes**. No alternate
privileged path was used to bypass a denied operation. Existing root-owned,
session-bus and full packet cases still need installed-target verification.

Current generated payload SHA-256:

```text
51f4e1cf96fdade52c56ecc4a6d0c54ed22bfda3358f401ed43b33183e3313ae
```

## Other diagnostics and installed acceptance

Host networking, DNS and NFS have affirmative capture evidence: routes exist,
resolved listens on `127.0.0.1:53053` over TCP/UDP, both configured NFS mounts
are active, and `findmnt --verify` reports no errors or warnings. AppArmor,
managed mode reconciliation, auditd and nftables start successfully. SecureBoot
is enabled and the enrolled certificate is present. Disabled networkd and
boot timing/target diagnostics taken while boot is still running are not
additional failed validation gates.

Vendor AppArmor reload attempts and icon sandbox warnings in the installer
chroot are followed by successful offline validation and deferred boot loading.
The installed journal and AppArmor status confirm enforced profiles. The
firstboot folder does not identify an independent package-staging failure.
UCSI, HID, firmware/resource and Bluetooth warnings, plus a Tailscale synthetic
DNS martian record, remain hardware/network observations without a demonstrated
repository cause. They do not establish a safe firmware or kernel change.

The supplied installed version is **systemd 262 (262-1)**. The requested target
remains **Forky/systemd 261.2**; the local parser and isolated checks do not
prove execution on that exact target version.

The source policies and fresh-install snapshot are repaired. This work did not
reload policy or recover the installed LPL-746 machine. Target acceptance must
show an enforced, ready broker with the pre-created pool, successful Podman
activation and a passing firstboot validation, followed by actual native,
privacy, qBittorrent, Codex, ChatGPT and private Zoom/Discord launches, DNS and
packet traffic. Those live outcomes are not inferred from offline compilation
or isolated fixtures.
