# Explicit NFS client mounting - 2026-10-05

## Supplied evidence and scope

The complete 18-line `todo/nfs-client` file was read. LPL-307 sets up both
`data-sharing-nfs\x2dclient.automount` and
`home-mcramer-Sharing-nfs\x2dclient.automount` at 11:52:43. At 11:54:22 zsh
triggers the home client endpoint. At 11:54:53 both corresponding mount jobs
fail with `dependency`. The log identifies unwanted filesystem activation;
it does not identify the failed prerequisite or show a denied network packet.
The `nfsrahead` messages about skipping non-NFS devices are informational.

This follow-up removes that activation mechanism throughout the installer and
its installed consumers. It preserves the earlier supplied-log repairs and
the current host roles, server address, export ranges and network preference.
Ethernet remains preferred when attached, with configured Wi-Fi fallback.

## Implemented contract

* Shared client source and home-bind options now require `noauto`. `auto` and
  `x-systemd.automount` are rejected by the target policy and build-time gate.
  There are no client path or automount units and no boot activation links.
* Client connections are explicit. The desktop menu waits for the source NFS
  mount before starting its home bind. Disconnect stops the home bind before
  the source; an error stops the sequence. No forced or lazy unmount is added.
* Installed configuration format 2 contains mount units only. The configurator,
  menu, identity helper, report helper and shutdown worker agree on that
  format. The menu and shutdown worker reject legacy automount fields. The
  independently published diagnostics document retains format 1.
* The shutdown worker derives and verifies the installed mount names without
  walking the remote paths. Existing trust checks, busy-stop handling and
  systemd mount dependency ordering are retained.
* `~/Sharing` remains a browsable, root-owned local parent. Its two children
  remain separate server/client endpoints. Only the server source directory
  is exported. Unmounted client endpoints retain mode `0000`, preventing
  local fallback writes until an explicit mount succeeds.
* The server's local home bind remains available through the existing local
  boot mount policy. `hard`, TCP, reserved client ports, identity checks,
  AppArmor requirements and firewall dependencies are retained.

Upstream [systemd v261 mount documentation](https://github.com/systemd/systemd/blob/v261/man/systemd.mount.xml)
explains why `noauto` removes filesystem-target activation and why leaving
`x-systemd.automount` present would defeat that change. The native generator
test checks the resulting units and links.

## LAN firewall verification

The existing managed firewall already generates the required server input
accept rule. No broader export or firewall allowlist was needed. New tests
compile the real desktop and baseline policies and verify an input rule with
TCP destination port 2049, `ct state new`, `accept`, the configured interfaces
`eth0`/`wifi0`, and the exact export CIDRs. The same checks pass with custom port
32049. All 41 allowed addresses are checked on both interfaces. The allowlist
guard precedes the accept, while wrong interfaces, IPv6 and excluded addresses
remain blocked by the existing focused guard checks.

The permitted ranges are:

| Sources | Server export access |
| --- | --- |
| `192.168.50.82-192.168.50.100` | Read/write |
| `192.168.50.112-192.168.50.122` | Read-only |
| `192.168.50.212-192.168.50.222` | Read/write |

The installer automatically selects the `nfs-server` overlay for an enabled
server, even when `NFT_SERVICES` omits it; the corresponding client selection
is also verified. The client output rule remains limited to its configured
server address and NFS port. These checks verify the generated policy. Live
packet delivery and host firewall state require installed-host verification.

## Exact validation

All commands below ran from the repository root. `timeout` bounded the commands;
Python's `-W ignore::EncodingWarning` suppressed existing encoding notices,
without suppressing test failures or skips.

| Command | Observed result |
| --- | --- |
| `timeout 180s python3 -B -W ignore::EncodingWarning -m unittest discover -s d-i/forky/tests -p test_network_sharing.py -q` | 129 run: 107 passed, 22 explicit skips |
| `timeout 90s python3 -B -W ignore::EncodingWarning -m unittest discover -s d-i/forky/tests -p test_shutdown_storage.py -q` | 14 passed |
| `timeout 30s python3 -B -W ignore::EncodingWarning tools/check_network_sharing.py` | All 10 profiles passed the target policy |
| `timeout 180s python3 -B -W ignore::EncodingWarning tools/build.py` | 1703 payload members; 0 browser artifacts changed |
| `timeout 180s python3 -B -W ignore::EncodingWarning tools/build.py --check` | Snapshot, pins, preseed and browser artifacts current |
| `timeout 180s python3 -B -W ignore::EncodingWarning tools/check_shells.py` | 350 shell files; all 711 parser checks passed |
| `timeout 90s python3 -B -W ignore::EncodingWarning tools/check_preseeds.py` | All 59 files passed; four generated commands survived private debconf read-back unchanged |
| `git diff --check` | Passed |

The NFS suite includes the actual fstab generator, actual nfsconf dump behavior,
offline AppArmor parser checks, real bounded child processes and native picker
fixtures. Menu/systemd actions, NSS identities and shutdown host commands are
mocked. The generator produces neither client `.automount`/`.path` files nor
client boot Wants/Requires links, while retaining source dependencies and
30-second initial mount timeouts. Shutdown fixtures cover all ten profiles and
all four server/client role combinations, invalid/legacy configurations, busy
unmounts and failure propagation. No shutdown or reboot command was executed.

Of the 22 NFS skips, 21 require private root-owned filesystem fixtures and one
requires a native systemd condition checker that cannot initialize here. These
are not passes. The available Python is 3.14.7 and systemd is 262 (262-1); the
requested deployment target remains Forky/systemd 261.2. `dpkg-query` did not
provide a package inventory in this environment, so target package versions
and behavior still require installed-host verification.

A read-only archive comparison against HEAD confirmed the same 1703-member
inventory and metadata, with exactly these six changed source members:

```text
hooks/target/usr/local/bin/labwc-network-sharing
hooks/target/usr/local/libexec/labwc-admin-action-worker
hooks/target/usr/local/libexec/network-sharing-identity
hooks/target/usr/local/libexec/network-sharing-report
hosts/installer/hosting.env
scripts/late/network-sharing.py
```

The three publication products (`preseed.cfg`, `payload.manifest`,
`payload.tar.gz`) were regenerated together. No Xwayland member changed and no
software compilation was added. Earlier broad-suite failures remain recorded
in BUILD-STATUS.md; those suites were not rerun for this bounded follow-up.

## Existing-host recovery and remaining acceptance

No installed host, mount, export, firewall ruleset or service was changed.
Active old autofs units survive a repository rebuild and a daemon reload.
The [administrator recovery section](../network-sharing.md#existing-client-with-the-logged-autofs-configuration)
identifies LPL-307's exact units, temporary runtime masks, normal stop order and
the coordinated deployment requirement. Configuration format 2 must be
deployed with every consumer; changing only a JSON version is insufficient.

On the actual Forky/systemd 261.2 hosts, confirm disconnected boot and browse
`~/Sharing` without any NFS start job. Verify immediate ordinary-account denial
at an unmounted client child, then use explicit Connect. Verify the effective
TCP ingress rule and real RW/RO/root-squash behavior from permitted and excluded
LAN addresses, enforcing AppArmor behavior, busy disconnect and server outages.
A deliberately connected `hard` mount can still block file I/O during a server
outage. Publish the complete rebuilt snapshot atomically only after the
required deployment checks.
