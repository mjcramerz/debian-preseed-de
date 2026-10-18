# Tailscale and AppArmor followup: 18 October 2026

## Current evidence and scope

This continuation starts from commit
`23e7c403ac536c8846b524309236cacadf8b36c4`. The current `todo/` tree contains
three regular files totaling 488,579 bytes: `apparmor.log`, `journalctl`, and
the unchanged older `.~` snapshot. These replaced the earlier 95-file evidence
set. The earlier [review](todo-20261018-review.md) and its hashes remain
historical evidence, not acceptance of this continuation.

[todo-20261018-followup-inventory.json](todo-20261018-followup-inventory.json)
records the current byte counts, physical line counts, hashes and each denial.
No supplied log was modified.

The current AppArmor log contains **69 DENIED events**, all the same contract:
`usr.bin.tailscale` opens
`/sys/fs/cgroup/system.slice/tailscaled.service/cpu.max` for reading. They occur
at physical lines 441 through 509. No other denied profile/path/operation is
present in this file.

The current journal separately shows:

- Lines 953-954: upstream best-effort legacy firewall cleanup cannot find the
  `iptables` and `ip6tables` tools.
- Lines 964 and 968-970: the initial router has no explicit backend selection,
  probes iptables, then falls back to nftables.
- Line 962: the private uplink is classified as `v4=false v6=true` despite its
  usable NAT-backed IPv4 path.
- Lines 1081-1082 and later repetitions: UDP probes fail or are skipped, followed
  by recurring send-error rebinds at lines 1096, 1347 and 1377.
- Lines 1095 and 1107-1109: Tailscale nevertheless reaches `Running`, completes
  bootstrap and establishes its DERP connection. This is a degraded transport
  path, not a failed enrollment.
- Lines 1083 and 1085: both Filen accounts reach `sync-initializing`. The current
  AppArmor log has no Filen denials. This does not prove completed cloud sync.

## Source repairs and installation path

### Exact CLI cgroup permission

`hooks/target/etc/apparmor.d/usr.sbin.tailscaled` already allowed the daemon to
read its own `cpu.max`, while the separately attached CLI allowed only the
bootstrap service cgroup. The netkit supervisor runs `tailscale status --json`
in `tailscaled.service` every two seconds. The CLI profile now grants read-only
access to that exact additional file. No cgroup write or wildcard grant was
added.

### Explicit nftables backend survives environment sanitization

The service template now selects `TS_DEBUG_FIREWALL_MODE=nftables`.
The `daemon()` delegate in `hooks/target/usr/local/libexec/tailscale-netkit`
constructs a fresh environment, so it also explicitly sets the same value at
`execve`. Adding only the unit environment would have been ineffective.
The existing remote-update prohibition remains in that private environment.

Tailscale documents this selector and uses its nftables Netlink implementation
when selected. Its backend detector then bypasses iptables probing. See
[Tailscale firewall modes](https://tailscale.com/docs/features/firewall-mode)
and [the pinned v1.104.1 detector](https://github.com/tailscale/tailscale/blob/v1.104.1/util/linuxfw/detector.go).

The daemon profile no longer grants inherited execution to legacy firewall
tools or access to `xtables.lock`. It explicitly denies execution of the
iptables/ip6tables variants and both xtables multi-call implementations in the
merged `/usr` binary directories. The package's nftables backend does not need
an `nft` subprocess grant.

There is an upstream limitation: v1.104.1 calls both legacy and nftables cleanup
before starting, independently of the chosen backend. The legacy cleanup can
still look for the tools and report a missing/denied executable. The profile
prevents actual legacy execution. Those diagnostics have not been filtered or
represented as eliminated. See
[the pinned router cleanup](https://github.com/tailscale/tailscale/blob/v1.104.1/wgengine/router/osrouter/router_linux.go)
and [legacy cleanup implementation](https://github.com/tailscale/tailscale/blob/v1.104.1/util/linuxfw/iptables.go).

`TAILSCALE_NETFILTER_MODE=off` remains the existing policy: the repository owns
the firewall rules. This controls rule management, independently of backend
selection. The upstream CLI's generic `configure iptables yourself` warning
under `off` is text, not an executed command. The named CrowdSec
`crowdsecurity/iptables` collection also remains: the source acquisition
`22-nftables.yaml.tmpl` feeds it nftables kernel packet logs.

### IPv4 transit must be private unicast

The old pair `169.254.253.1/30` and `169.254.253.2/30` is link local. Tailscale
v1.104.1's `isUsableV4` excludes that range on Debian, making `HaveV4=false`.
The initial netcheck planner gates IPv4 probes on that flag; a report with no
IPv4 send then drives the repeated magicsock rebind. This ties the supplied
`v4=false` and recurring rebinds to a concrete source contract. See
[netmon address classification](https://github.com/tailscale/tailscale/blob/v1.104.1/net/netmon/state.go),
[netcheck probe planning](https://github.com/tailscale/tailscale/blob/v1.104.1/net/netcheck/netcheck.go)
and [magicsock report handling](https://github.com/tailscale/tailscale/blob/v1.104.1/wgengine/magicsock/magicsock.go).

The pair is now `10.255.253.1/30` and `10.255.253.2/30`, on the fixed private
`10.255.253.0/30` transit network. Both runtime packet policy and the managed
firewall generator use the same peer address. DNS redirection, NAT, source
validation and routing selectors follow those constants. The existing route
overlap check still rejects a conflicting transit network before setup mutation.
The IPv6 transit, physical interface ownership and production netkit link type
are unchanged.

The installer path remains `scripts/late/tailscale.sh`: it renders the service,
stages the two root-owned delegates and profile, and runs the existing offline
asset verification before activation. The payload and manifest contain the
updated canonical files. No installer token or new configuration option was
introduced for this fixed transport contract.

### Requested stop and an interrupted polling command

One native attempt returned a failed service stop after becoming active. A
later run stopped successfully, so the original stop's exact internal failure
was not established by the captured pre-stop output. Review identified a
concrete cancellation gap: systemd's `KillMode=control-group` also terminates a
currently running ip/CLI child, and `supervise()` propagated that command
failure even when its signal handler had already recorded a requested stop.

`supervise()` now treats only `CommandFailed` after `STOP` as cancellation.
The same command failure without a stop still propagates. Other exception
types, pinned termination uncertainty, cgroup draining and ExecStopPost's
identity/ownership cleanup verification keep their existing failure behavior.
No service kill mode, deadline or cleanup ownership rule was relaxed.

## Verification

### Changed paths

- `d-i/forky/hooks/target/etc/apparmor.d/usr.sbin.tailscaled`
- `d-i/forky/hooks/target/etc/systemd/system/tailscaled.service.d/override.conf.tmpl`
- `d-i/forky/hooks/target/usr/local/libexec/tailscale-netkit`
- `d-i/forky/hooks/target/usr/local/sbin/nft-policy-generate.py`
- `d-i/forky/tests/test_apparmor_incidents_20261004.py`
- `d-i/forky/tests/test_native_contracts_20260923.py`
- `d-i/forky/tests/test_tailscale_netkit_20261017.py`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/payload.manifest`
- `d-i/forky/preseed.cfg`
- `inventory.json`
- `docs/validation/todo-20261018-review.md`
- `docs/validation/todo-20261018-followup.md`
- `docs/validation/todo-20261018-followup-inventory.json`

### Static and serialization evidence

Five affected Python sources parsed as AST data without executing/importing
repository code. `git diff --check` is clean. The installed entrypoint,
constructor/delegate, service, profile and both nftables consumers were traced.
All 2,102 entries in the VM's source-hash list were compared with current
checkout bytes. The source-bundle fingerprint is
`86e214a86f16248c6c341baf7fefeda89e4f892981f1464cee25b1b2addb7630`.

The reviewed serialization commands completed successfully:

```text
/usr/bin/make --no-print-directory build 'PYTHON=/usr/bin/python3 -I -S'
/usr/bin/make --no-print-directory inventory 'PYTHON=/usr/bin/python3 -S'
```

The inventory reported 1 source rescanned, 1,806 cached and 1,817 manifest
members. `inventory-apt.json` was not refreshed and remains SHA-256
`96314d9227e24e04aaf8577258cbc7c8bc575fe36cb855b49dda89c9ffc83318`.

Data-only verification compared all **1,817 archive members** with their current
source bytes, manifest hashes and normalized tar metadata. The expanded payload
is 34,697,719 bytes. The preseed's archive and manifest pins match these bytes.

| Product | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.tar.gz` | 26,561,427 | `8c598731cc8c442ec630fd9942002c1f2b10190cd9ed61e65902619eb1be0e06` |
| `d-i/forky/payload.manifest` | 223,955 | `65f1d823d8392966ec56e3d96a4f7a3620f9d2252b8214806d2190154ca45266` |
| `d-i/forky/preseed.cfg` | 96,407 | `86292f51fd1817a3f1780d5d872d9d4f28ca277c1644b739de69f853a6d76626` |
| `inventory.json` | 26,014,589 | `8d2e0612a6504c6e0b12216fac3a937e6c4778efe4020cd1af81c08807482e01` |

### Disposable native fixture

The fourth run completed the old/new transit comparison with two successful
service starts and stops, using the source before the cancellation guard
(fingerprint `a099f6640ac4a171dd1af51a755f15ce0c1cd409c8bbedbc69c76f3e333249e3`).
The fifth run used the exact final source fingerprint recorded above, completed
the six separate cancellation-injection cases, and passed one final native
private-unicast startup/netcheck/stop cycle. Both completed runs emitted
`FOLLOWUP_NATIVE=success` and `FOLLOWUP_FINAL_STATUS=0` and have no AppArmor
DENIED events in their full console logs. QEMU exit zero alone was not used as
acceptance evidence.

The first followup attempt loaded all four updated profiles but exceeded the
production constructor's 15-second connection deadline under single-CPU TCG.
It ended with `FOLLOWUP_FINAL_STATUS=1` before daemon startup and is not counted
as acceptance. Its console and ISO are retained. The rerun uses two emulated
CPUs and warms packaged code/module pages before starting the unchanged
production constructor; no production deadline was increased.

The second attempt reached an active native Tailscale service, then stopped at
the fixture's explicit `cpu.max` existence check. The minimal guest had not
enabled the CPU controller, so it could not exercise the reported cgroup read.
That partial result is not aggregate acceptance. The next fixture adds only
`CPUQuota=200%` to its test unit to enable the controller on the two-vCPU guest;
the production service does not gain a CPU quota.

The third attempt reproduced skipped IPv4 probes with the old link-local
transit, then returned a failed native service stop. Its pre-stop output did
not identify that stop's internal failure. The fourth run added post-stop
diagnostics and both stops succeeded. The cancellation gap described above was
then reproduced deterministically with explicit command-failure injection
against the before/after sources in the fifth VM. This does not establish the
exact cause of the third attempt's intermittent stop result.

The fixture uses the existing private Forky image documented in the prior
review, with systemd 262-1, kernel 7.2.11-1, AppArmor 4.1.8-2 and actual
Tailscale 1.104.1. QEMU has no NIC, host shares, host management sockets or
physical device passthrough. A temporary snapshot overlay protects the existing
private image. The simulated WAN, local STUN responder and replacement DERP-map
API are wholly within the guest. No cloud credentials are used.

The fixture preserves the actual source service properties while using the
previously documented minimal-boot dependency exception. Native netcheck runs
the actual Tailscale CLI in the daemon network namespace with a fixture API/map;
that standalone network probe is separate from the confined supervisor's real
CLI polling. The generated transport forwarding rules are loaded with a default
drop forwarding chain, alongside actual netkit NAT and source-guard policy.

| Check | Observed result |
| --- | --- |
| Actual target AppArmor parser/load for all four Tailscale profiles. | Success in the final guest; no unexpected DENIED events during startup, polling, probe or shutdown. |
| Actual CLI polling in `tailscaled.service` with its CPU controller enabled. | The exact `cpu.max` existed with `200000 100000`; repeated supervisor CLI calls completed without denials. |
| Final daemon's real process environment and backend log. | `TS_DEBUG_FIREWALL_MODE=nftables` survived the delegate; the router reported nftables without backend iptables probing/fallback. |
| Legacy executable tripwires installed in the guest. | Neither executed; the daemon's explicit policy denied their use. Upstream legacy-cleanup lookup diagnostics remained visible. |
| Actual Tailscale netcheck, old link-local transit (fourth run). | `IPv4CanSend=false`, `IPv4=false`, `UDP=false`; reproduced the skipped-IPv4 defect. |
| Actual Tailscale netcheck, private transit (fourth and final fifth runs). | `IPv4CanSend=true`, `IPv4=true`, `UDP=true`; a full IPv4 STUN round trip completed through source-generated forwarding/NAT policy. |
| Final source service lifecycle. | Active startup; stop returned `Result=success`, then owned state and route rules were absent. |
| Six explicit cancellation failure-injection cases inside the fifth VM. | Before the guard, both ordinary and requested-stop command failure propagated. After the guard, ordinary failure still propagated and requested-stop interruption returned zero. Pinned termination uncertainty remained `unknown` in both versions. These are isolated mocks, separate from the actual service/network checks. |

All five QEMU processes were powered off and reaped. Evidence is retained under
the private directory `/tmp/preseed-tailscale-followup-20261018-z03elhyp/`:

| Evidence | SHA-256 |
| --- | --- |
| `qemu-console.log` (constructor deadline, failed) | `57366fd9878e2fe3a195a1fcb331c3228530298b58bad9aa46829906154cbe8f` |
| `qemu2-console.log` (missing fixture CPU controller, incomplete) | `3ace708846bae442c23aecfdd580388791a40aac7bb8634fea197f3818589ed3` |
| `qemu3-console.log` (baseline probe passed, native stop failed) | `f4ea176d5543975481ad29f8cc69eee0519962635743cf664c8faea1f2c73e57` |
| `qemu4-console.log` (completed old/new native comparison) | `675b5aca3e461f8337b3e6ca89a1915deff6b9a2e10fa977329a9e659abe2f92` |
| `qemu5-console.log` (final source, native cycle and six injection cases) | `eff1a279bfb524b7d9c3dbcd850a485645047b123998d59241030f9f24b43cad` |
| `fixture5.iso` | `eca68b30c45d11935d4493c4a78ac2f1d36a0fd83168c66a8ca24940f9e48c27` |
| `bundle/native-followup.py` (final probe script) | `bf992852df2a308be04a4027238086ed6d0744f177acaad1acf8530d766a5ddb` |

The private `final-native-evidence.json` additionally pins all five retained
fixture ISOs and the source-hash list. The final source bundle's 2,102 hashes
were compared to current checkout bytes after native execution.

Added guarded regression cases cover the forced private daemon environment,
private/unicast address class, collision rejection before mutation, shared peer
address across runtime/generator, exact cgroup permission and legacy execution
prohibition, plus requested-stop command failure. The guarded unittest suites
were not executed: the prepared VM is
a native integration fixture, not the rootless suite image required by the
test guard. Independent reviewer startup again failed before work with an
encrypted-context hydration error; no child findings were counted.

## Acceptance limits

No development-host services, firewall, AppArmor policy, package state or
configuration were changed. These are installer-source and generated-product
repairs. The running supplied installation has not been deployed or repaired.
Full installer boot, authenticated tailnet/SSH/DNS operation, real uplink/NAT
conditions and GUI/hardware acceptance remain separate target gates. There is
no measured production throughput or latency claim. The Xwayland/Zoom/Discord
implementation and eligibility policy remain unchanged.
