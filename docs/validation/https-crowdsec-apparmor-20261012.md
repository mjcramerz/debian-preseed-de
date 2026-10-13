# qBittorrent HTTPS, CrowdSec and installed audit review — 2026-10-12

## Scope and evidence

Reviewed all 95 supplied files under `todo/`: 9,527,666 bytes, including 22
empty files. The groups contain 43 installer-state files, 49 managed logs,
and one file each for the standalone AppArmor, journal and qBittorrent captures.
Empty scanner logs do not establish that a security scan passed. Private
arguments, environments, tracker credentials and full log contents are not
reproduced here.

The starting checkout was clean. Changes implement the four requested objectives
in the Forky installer. No host packages, host services, host firewall, loaded
AppArmor policy or production systems were changed. No software was compiled
from source. The existing Xwayland policy was not changed.

Validation used Python 3.14.8, systemd 262, qBittorrent 5.2.4,
libtorrent-rasterbar 2.0.14, CrowdSec 1.8.1 and AppArmor 4.1.8.

## 1. HTTPS tracker gate with 3proxy

`classes/class-addon/software.cfg` installs `3proxy` and declares apt-setup
local11 with the HTTPS archive `https://3proxy.org/repo/deb`, suite `current`,
component `main`, its upstream release key, a repository comment and disabled
source packages. The existing `95-normalize-apt` hook invokes the target
normalizer, whose exact host/path classification produces `3proxy.sources`.
Normalization retains the scoped `Signed-By`; it does not add global key trust.
The temporary-file test verifies the actual normalized contents, idempotence
and rejection of lookalike host/path classifications.

All native qBittorrent settings remain in
`hooks/target/etc/qbittorrent/qBittorrent.conf.d/10-managed-security.conf.tmpl`.
The installer renders the persistent profile and a disposable PurePrivacy
profile from that same canonical template. Launchers copy exact rendered bytes;
they do not parse native keys, render templates or merge previous settings.
The disposable profile uses its temporary HOME and its allocated interface;
its IPv4 address is not pinned to the persistent profile's reservation.

Both online launch modes start a foreground 3proxy child in the existing private
Bubblewrap PID/network namespace and transient service. It listens only on
`127.0.0.1:3128` there. The ACL permits only `HTTP_CONNECT` to destination port
443 and denies other requests. There is no SOCKS or administrative listener,
and no proxy request logging that could record tracker passkeys. The packaged
host `3proxy.service` is masked by the desktop service stage.

The session supervisor waits for the proxy before starting qBittorrent. Proxy
failure terminates the torrent process; shutdown gives qBittorrent time to send
stopped announcements, then reaps the proxy. Native profile/configuration
overrides are rejected. Offline launches retain the unshared network namespace
and need no proxy. The native config enables the proxy for BitTorrent, RSS and
miscellaneous requests, retains HTTPS certificate validation and leaves peer
TCP/uTP connections direct inside the existing network isolation.

An independent nftables set blocks TCP and UDP destination port 80 for both
`qbittorrent` and `qbittorrent-privacy` leases, before ordinary or pinned egress
accept rules. Membership is installed before opening the host veth and removed
by normal lease cleanup. Other applications retain their existing egress.
Managed proxy settings are restored on each new launch; the port-80 guard also
applies if the user changes proxy preferences during a session.

HTTP tracker URLs, HTTPS-to-HTTP redirects and UDP trackers cannot announce
through this configured HTTP proxy. An HTTP-only tracker entry is rejected;
the installer does not guess another hostname, rewrite tracker passkeys or
assume that an HTTP endpoint supports TLS. Use the tracker's real HTTPS URL.
HTTPS on nonstandard ports is also rejected by the explicit port-443 ACL.

The supplied qBittorrent log records version, interface, peer port and disabled
DHT/PeX/LSD. It contains no actual tracker announcement URLs, so it does not
independently demonstrate the reported HTTP announcements.

### Native proxy validation

Used the upstream prebuilt 3proxy 1.0.1 amd64 package, extracted in a private
temporary directory without executing maintainer scripts. Its release asset
SHA-256 was checked against upstream release metadata:
`230e63119b0655b0738cd1fcb3cff5f87289d943efb3d2519705548e25c1e908`.
Only the fixture's listening port changed to an ephemeral loopback port; the
destination ACL stayed exactly as authored.

| Request | Observed result |
| --- | --- |
| HTTP GET to port 80 | 403 Forbidden |
| HTTP GET to port 8080 | 403 Forbidden |
| HTTP GET to port 443 | 403 Forbidden |
| CONNECT to port 80 | 403 Forbidden |
| CONNECT to an absent local endpoint on port 443 | 502 Bad Gateway, rather than ACL rejection |
| CONNECT to a public HTTPS endpoint on port 443 | 200 Connection established |
| TLS through HTTP/1.0 and HTTP/1.1 CONNECT to www.debian.org | Certificate verified, TLS 1.3, HTTP 200 |
| Native curl through the proxy to www.debian.org and example.com | Exit 0, HTTP 200, certificate verification enabled |

An initial manual Python TLS attempt ended with an unexpected EOF. Subsequent
checks passed for both CONNECT versions and both native curl destinations;
no proxy configuration change was justified by that isolated failure.

The upstream APT signing-key request returned HTTP 403 in this environment.
Therefore the live APT key/archive path and a fresh d-i package installation
remain unverified. The separately accessible release binary does not prove
that the APT archive is reachable. A local TLS-server fixture on port 443 was
also unavailable because binding that port was denied; the successful public
HTTPS tests exercised the actual destination-port policy instead.

Protocol behavior was checked against the
[qBittorrent 5.2.4 proxy implementation](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.4/src/base/bittorrent/sessionimpl.cpp),
[libtorrent HTTP connection code](https://github.com/arvidn/libtorrent/blob/v2.0.14/src/http_connection.cpp),
[proxy socket binding behavior](https://github.com/arvidn/libtorrent/blob/v2.0.14/include/libtorrent/proxy_base.hpp),
[UDP tracker handling](https://github.com/arvidn/libtorrent/blob/v2.0.14/src/udp_socket.cpp),
and [3proxy configuration documentation](https://3proxy.org/doc/man3/3proxy.cfg.3.html).

## 2. CrowdSec coverage and activation

The existing linux, sshd, auditd, iptables and whitelist-good-actors collections
remain required. Firstboot additionally installs:

- `crowdsecurity/linux-lpe` and its pkexec parser/scenario dependencies;
- `crowdsecurity/base-http-scenarios`, including the requested SQL injection,
  probing, sensitive-file and path-traversal scenarios, plus its maintained
  generic HTTP/CVE dependencies;
- `crowdsecurity/appsec-virtual-patching`;
- `gilbsgilbs/qbittorrent`, including `qbittorrent-logs` and `qbittorrent-bf`;
- the `crowdsecurity/nginx-logs` and `crowdsecurity/docker-logs` parsers.

The desktop acquisition tails the persistent qBittorrent profile's actual
native logfile. Discovery polling handles a storage volume or logfile appearing
after CrowdSec starts. Rotated copies are not independently acquired. A separate
`_COMM=pkexec` journal acquisition covers the authentication records needed by
linux-lpe. WebUI remains disabled by the managed qBittorrent configuration.
Its brute-force collection is ready if the persistent WebUI is enabled and
reachable through an explicitly configured network exposure.

The AppSec acquisition is staged under `acquis-available` first. Firstboot
publishes it atomically into `acquis.d` only after the required Hub collection
has installed, then runs `crowdsec -t` before restarting the engine. Existing
modified, linked, multiply linked or unsafe acquisitions are rejected. The
listener is restricted to `127.0.0.1:7422` and loads
`crowdsecurity/virtual-patching`. The upstream `appsec-default` config also
references experimental rules outside the requested collection; native
validation detected that dependency and the dedicated virtual-patching config
avoids it.

The existing nftables bouncer continues enforcing IP decisions. Its supplied
log shows 15,000 decisions imported successfully. No invented attacker IPs or
static bans were added. HTTP scenarios require application access logs;
AppSec requires an HTTP bouncer to forward requests. The nftables bouncer does
not inspect HTTP requests, and this desktop profile installs no web server.
An AppSec listener and installed rules alone do not establish WAF protection.
Linux LPE scenarios provide detection, not kernel prevention of privilege
escalation. See the
[CrowdSec AppSec integration documentation](https://docs.crowdsec.net/docs/appsec/configuration_creation_testing/).

### Container log acquisitions

The managed Podman configuration uses `k8s-file`, while `docker-logs` expects
Docker JSON. A local raw parser handles complete Podman CRI records, requiring
an explicit `program` label so an application parser can consume their content.
Arbitrary container logs are not automatically classified as web access logs.
Select the real, reviewed container logfile and application before adding an
acquisition. For an nginx container, the formats are:

```yaml
# Docker JSON logfile, selected explicitly by the operator.
source: file
filenames:
  - /srv/reviewed-docker-web-container/nginx-json.log
discovery_poll_enable: true
discovery_poll_interval: 10s
labels:
  type: docker
  program: nginx
---
# Podman k8s-file logfile, selected explicitly by the operator.
source: file
filenames:
  - /srv/reviewed-podman-web-container/ctr.log
discovery_poll_enable: true
discovery_poll_interval: 10s
labels:
  type: podman
  program: nginx
```

These illustrative paths are not installer-created acquisitions. The Podman
decoder accepts complete `F` records and does not reconstruct split `P`
fragments. Choose a complete application access-log source if records are split.

Native CrowdSec configuration validation and five parser fixtures passed:
qBittorrent login failure/scenario, Podman-to-nginx, Docker-to-nginx, auditd
rotation notice, and a genuine audit EXECVE record. Hub downloads and native
parser execution were real. Parser fixtures used fake credentials and a mock
local API in a private directory; they did not contact the installed LAPI or
produce live firewall decisions.

## 3. AppArmor denials

The supplied captures contain nine distinct DENIED events, repeated in the
journal and audit logs. These repetitions were not counted as new incidents.

| Count | Denial | Narrow correction |
| --- | --- | --- |
| 3 | `desktop-launcher` executing `/usr/sbin/aa-status` | Exact transition to a native diagnostic child, with read-only profile/process metadata and no policy-write or general sbin execution permission |
| 6 | `labwc-network-sharing//systemctl` inheriting `/dev/pts/0` read/write | `owner /dev/pts/[0-9]* rw` in that child only |

The aa-status child can read process metadata with reciprocal read permissions
from the existing base.d monitor abstraction. Trace/attachment is explicitly
denied. An AppArmor capability allowance does not confer a capability on the
invoking user; authorized root credentials are still required for the full
kernel profile listing. Rules were traced against the
[AppArmor 4.1.8 native aa-status implementation](https://github.com/apparmor/apparmor/blob/v4.1.8/binutils/aa_status.c).

The qBittorrent supervisor and 3proxy inherit the existing Bubblewrap child
domains under no_new_privs. Firstboot gains only the exact `crowdsec` and `cmp`
executions required by its new configuration check and atomic publication.
All repository profiles passed the native offline parser with private
configuration/cache paths and kernel loading disabled. This does not prove
loaded-policy enforcement on a new installed desktop.

## 4. Audit review and parser repair

Read all four audit files: 31,267 records, including 4,959 SYSCALL records and
the same nine AppArmor denials. The 43 ENOENT exec failures are PATH probes for
programs including bwrap, btop and vdirsyncer, plus shell searches for AppArmor
commands. The three EACCES exec failures correspond to the aa-status alias
denials. PATH probing does not justify changing installed launchers or PATH
defaults. Root and user execve/execveat audit coverage for both ABIs is retained.

Each of the four CrowdSec ParseKV errors occurs at the exact second of an
auditd `Audit daemon rotating log files` message in the system logfile:
12:09:27, 12:12:46, 12:16:18 and 12:19:59 in the supplied +02:00 timestamps.
The new `00-managed-auditd-daemon` parser skips that exact syslog notice before
the upstream audit parser. The native fixture proves that the notice no longer
causes ParseKV errors and genuine `type: auditd` records still parse normally.
The managed guard does not modify or taint the upstream Hub parser.

No failed units were listed in the supplied firstboot snapshots. GTK tray
assertions, the isolated qBittorrent power-management warning, hardware UCSI
messages and Bluetooth identity warnings lack evidence for a deterministic
repository fix. They remain observations requiring a live reproduction.

## Verification and artifacts

From `d-i/forky/tests`:

```sh
PYTHONPATH=. python3 -B -m unittest \
  test_compz_qbittorrent_followup test_kernel_veth_networking \
  test_crowdsec_firstboot_retry test_apparmor_incidents_20261004 \
  test_managed_external_software.ProxyAPTSourceTests -q
```

Result: 200 tests, 198 passed, two skipped. The skips are:

- the live veth/DNS fixture because this environment denies `ip_forward`
  sysctl writes even in its private user/network namespace;
- native Stubby anchor validation because the required packaged Stubby and
  dns-root-data inputs are unavailable.

The native nftables syntax/all-lease transaction check, veth boot batch and
gateway fixtures, real blocked Bubblewrap/pidfd fixture, systemd unit check,
AppArmor offline parser and APT normalization fixture passed. The live routed
veth fixture's skip does not establish installed network behavior. Two proxy
failure/cleanup tests also passed after the final diagnostic-status change.

From the repository root:

```sh
python3 -B tools/check_shells.py --output /tmp/preseed-shell-validation-20261012.json
python3 -B tools/build.py
python3 -B tools/build.py --check
git diff --check
```

Result: 354 shell files, 719 parser checks passed; 1,744 payload files rebuilt;
snapshot, pins and preseed current; whitespace check passed. Six new payload
assets were also compared byte-for-byte with their canonical sources and
manifest hashes. The generated archive has no Squid paths. Browser generation
changed zero artifacts. The generated files are `d-i/forky/payload.tar.gz`,
`payload.manifest` and `preseed.cfg`.

This is repository, fixture and component validation. No fresh unattended
installation, live tracker announcements, live WebUI bans, container deployment
or host AppArmor reload was performed. The live 3proxy APT archive remains the
material installation risk described above. The full unrelated repository test
suite was not run. Independent read-only agent handoffs failed during runtime
context hydration, so inspection and final integration were completed by the
coordinator.
