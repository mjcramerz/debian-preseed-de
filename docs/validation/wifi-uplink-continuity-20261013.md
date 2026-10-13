# Wi-Fi, uplink changes and application continuity — 2026-10-13

## Scope and execution boundary

Reviewed the LPL-223 snapshot under `todo/`: all 51 supplied files, totaling
8,471,754 bytes. Read the logs and source as data. No host service, package,
network, firewall, mount or security-policy operation was executed. No test,
test discovery, repository validation runner or native policy parser was run.
No software was compiled. Repository changes preserve the private Xwayland
policy and the existing managed 3proxy configuration ownership.

The repository's `AGENTS.override.md` requires tests to run only in a prepared
disposable environment without access to host state. Such an environment was
not available. The checks below are static inspection and payload comparison;
they do not establish installed kernel, desktop or Internet behavior.

## Evidence

- `todo/managed/network/veth.log:4` records qBittorrent's
  `network_route_changed` with `reason=route_replaced` at 11:58:19.
- `todo/journalctl:1723` records that same event; line 1748 records the launcher's
  fatal `kernel network lease ended; stopping the isolated application`.
  Lines 1755–1756 record the transient application's exit and service failure.
  NetworkManager activates `wifi0` during this interval.
- `todo/managed/security/nftables/nftables.log` contains 59 accepted output
  records and 12 dropped input records. Five output records use `wifi0`,
  including DNS-over-TLS and NFS. The dropped input packets are late HTTPS
  replies to the Ethernet address after the Wi-Fi activation. This snapshot
  contains no forward-drop record or nftables parser/transaction error.
  It does not prove the exact conntrack state of those dropped replies.
- `todo/managed/security/apparmor/apparmor.log` contains 426 `STATUS` records
  and zero `DENIED` records. Status/profile-load records are not access denials.
- `todo/journalctl:1907` and line 1915 record successful mounts of the NFS
  source at `/data/sharing/nfs-client` and its home bind at
  `/home/mcramer/Sharing/nfs-client`.

## Implemented contracts

1. Uplink changes update the existing network lease. Ethernet, Wi-Fi and VPN
   egress are selected from the validated kernel IPv4 route. The broker no
   longer revokes a lease when its route changes or remains unavailable.
2. The private namespace, guest interface and reserved address remain stable.
   Offline launch installs the namespace and static guards; pinned egress
   remains blocked until an Internet route is available. Ordinary leases can
   still use policy-permitted LAN routes.
3. For an egress/source change, the broker lowers the host veth, replaces exact
   egress/SNAT/peer DNAT elements in one nftables transaction, and reserves the
   peer's TCP/UDP port on the new host source address. The guest's own port and
   address remain unchanged. Discord's loopback reservations remain separate
   from uplink reservations.
4. Packaged `conntrack` clears only flows with this guest's original or reply
   source address, before reuse or egress replacement. There is no global
   flush. Flow stdout is discarded; administrative stderr is bounded. Status
   1 is accepted only with the exact empty-deletion summary, so permission and
   command failures remain errors. The Forky 1:1.4.9-1 source confirms these
   filter and empty-result semantics.
5. An administrative update failure retains the application and schedules a
   five-second retry. Healthy and offline leases wait for kernel events;
   self-generated link notifications do not create a busy retry loop.
   An unchanged route performs no administrative work. An MTU-only change
   updates both veth ends without replacing ports or clearing connections.
6. Running supervisors retain their original namespace FD. A lost broker
   connection schedules authenticated reconnection rather than terminating
   the application. Reconnection requests its original address; the broker
   validates application ownership and slot availability. Every attachment
   still checks socket ownership, peer credentials, namespace ownership and
   the managed policy. Startup still requires a successful acknowledgment.
   The Podman adapter uses the same retained-FD lifecycle.
7. Baseline, balanced, performance and hardened sysctl sources use
   `rp_filter=2` for both `all` and `default`. Loose mode validates source
   reachability across any interface, accommodating asymmetric traffic during
   Ethernet/Wi-Fi overlap. Application source/port/LAN isolation remains in
   the nftables policy.
8. `conntrack` is selected in the desktop APT package list, checked during
   target installation and included in desktop/firstboot command inventories.
   AppArmor grants the exact conntrack executable paths and the client event
   module/local logging paths. No unconfined execution fallback was added.

Primary references: [Linux reverse-path filtering documentation](https://docs.kernel.org/networking/ip-sysctl.html),
[Forky conntrack source](https://sources.debian.org/src/conntrack-tools/1:1.4.9-1/src/conntrack.c),
[conntrack filter options](https://sources.debian.org/src/conntrack-tools/1:1.4.9-1/conntrack.8).

## Changed source paths

- `d-i/forky/hooks/target/usr/local/sbin/app-veth`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/network_client.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/network_namespace.py`
- `d-i/forky/hooks/target/usr/local/libexec/app-veth-podman`
- `d-i/forky/hooks/target/etc/apparmor.d/app-veth.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/abstractions/app-veth-client`
- `d-i/forky/hooks/target/etc/sysctl.d/10-baseline.conf`
- `d-i/forky/hooks/target/etc/sysctl.d/profiles/balanced/40-balanced.conf.tmpl`
- `d-i/forky/hooks/target/etc/sysctl.d/profiles/performance/40-performance.conf.tmpl`
- `d-i/forky/hooks/target/etc/sysctl.d/profiles/hardened/40-hardened.conf.tmpl`
- `d-i/forky/classes/class-select/role/desktop.cfg`
- `d-i/forky/scripts/late/security.sh`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`
- `d-i/forky/scripts/firstboot/04-validation.sh.tmpl`
- `d-i/forky/tests/test_kernel_veth_networking.py`
- `docs/app-veth.md`
- This report.

## Verification and generated output

- Parsed 397 Python source/templates/scripts using standard-library AST only.
  No repository module was imported or executed for inspection.
- Inspected route refresh, same-address reconnect, descriptor ownership,
  package/installer/AppArmor consumers, all four sysctl sources and test
  isolation guard ordering as data. Parsed five embedded Python fixture
  strings as data. Updated guarded outage/reconnect/failure fixtures; they
  were not executed.
- `git diff --check` completed without findings.
- Executed only the permitted pure generation command:

  ```sh
  /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
  ```

- Compared checkout metadata before/after generation: exactly
  `d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg` changed.
- Streamed the archive without extracting or executing it. Compared all
  1,754 regular members with canonical source bytes and manifest SHA-256,
  covering 33,942,358 source bytes. Verified normalized archive metadata,
  excluded private-input/test paths, the four changed runtime members' AST,
  and matching archive/manifest/bootstrap-source pins in preseed.

| Generated product | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `d017a377d944c0ed365a8e461b17993074b580787d53a9daa96398f573354146` |
| `payload.manifest` | `2ecbdc750276545275c1704f98fef409c3b92055f180948c2547afbd0c709d7f` |
| `preseed.cfg` | `5424d2cab083dbcb31e974277db8ca72cb59b8911180f7ea2d79859d4d8fe47e` |

## Remaining limits

The installer payload contains these fixes; it has not been applied to the
supplied installed machine. Native nftables/AppArmor acceptance, an actual
Ethernet/Wi-Fi/VPN switch, broker restart with live GUIs and qBittorrent peer
traffic still require the permitted disposable installation environment.
Existing remote TCP connections must reconnect when their source address
changes; retaining the GUI does not preserve TCP across different addresses.
Network reachability and upstream port forwarding remain properties of the
selected connection.

The snapshot also records Vivaldi extension/search-engine/MPRIS warnings,
labwc DRM `Device or resource busy` messages and CrowdSec Console enrollment
errors. These records do not establish a corresponding repository routing or
AppArmor defect. They are not claimed fixed by this change. No vendor browser
or compositor build, extension manifest rewrite or external Console operation
was performed.
