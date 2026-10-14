# Managed Tor Browser

## Authenticated installation

The amd64 desktop Software class installs the requested official Tor Browser
15.0.25 archive. It does not compile Tor or the browser. Each desktop host
profile supplies `SOFTWARE_TOR_BROWSER_VERSION`, `SOFTWARE_TOR_BROWSER_URL`,
`SOFTWARE_TOR_BROWSER_SHA256` and `SOFTWARE_TOR_BROWSER_KEY_SHA256`.

The installer requires the exact HTTPS release path on `dist.torproject.org`,
bounds the archive/signature downloads, checks both pins and verifies the
OpenPGP signature in a private temporary keyring. It requires the Tor Browser
Developers primary fingerprint
`EF6E286DDA85EA2A4BA7DE684E2C6E8793298290`. Verification failure stops installation;
no account keyring is modified. See the [official signature instructions](https://support.torproject.org/tor-browser/getting-started/verifying-tor-browser/).

The extraction helper accepts bounded regular files/directories under one
archive root and rejects links, special nodes, traversal, duplicates and
privileged modes. It publishes the checked bundle at `/opt/tor-browser` from a
private staging directory. Its root-owned executable/directory modes are 0755;
other files are 0644. The desktop file is canonical source at
`hooks/target/usr/local/share/applications/tor-browser.desktop` and installed at
`/usr/local/share/applications/tor-browser.desktop`. Every action uses
`labwc-app`; Tor Browser does not become the default browser.

## RAM runtime and process boundaries

All four actions use a fresh RAM session. The existing managed transient unit
owns the complete process tree. Its Tor-specific properties are
`MemorySwapMax=0`, `MemoryZSwapMax=0`, `LimitCORE=0` and `CoredumpFilter=0x0`.
Before sandbox creation, the launcher requires its own service's
`memory.swap.max` to contain zero. It fails closed if that contract is absent.
No other service's swap or core policy is changed. The [systemd 262 memory-controller documentation](https://raw.githubusercontent.com/systemd/systemd/v262/man/systemd.resource-control.xml)
defines these memory controls.

The outer Bubblewrap sandbox provides a fresh tmpfs HOME/runtime, synthetic
machine identity and the dedicated application veth. `tor-browser-run` verifies
that state/runtime reside on tmpfs and copies only the authenticated immutable
bundle into that private RAM filesystem. Copying is bounded to 2,048 nodes and
512 MiB of file data. There is no disk fallback. The current bundle copy uses
about 333 MiB plus filesystem overhead; browser, Tor, cache and page memory are
additional. RAM copying has a startup cost; no speedup has been measured.

The supervisor starts two child Bubblewrap sandboxes, each with its own PID,
mount, IPC and UTS namespaces:

- **Tor transport** shares the outer veth network, uses bundled Tor and has no
  GUI/audio/GPU device access. Its RAM bundle and every alternate path to those
  files are read-only. Only private Tor data and socket/cookie IPC are writable.
- **Tor Browser** has a separate network namespace with no IP connectivity. Its
  AppArmor domain also explicitly denies inet/inet6. It sees the RAM bundle
  read-only, a writable RAM HOME, the specific Wayland/audio sockets and
  read-only Tor IPC. The original writable RAM-copy path is hidden by a fresh
  runtime mount. It cannot execute the transport binary or inspect its PID tree.

Private Unix SOCKS and cookie-authenticated control sockets connect the browser
to bundled Tor. Its native SOCKS authentication/circuit isolation remains in
place. PID descriptors supervise both children without periodic session polling.
Failure of either child stops the other; bounded graceful/kill waits and
Bubblewrap parent/PID-namespace lifetime rules prevent a surviving daemon.

The release includes `Browser/start-tor-browser`. That portable launcher rewrites
desktop files, changes HOME to its portable installation and performs cache
cleanup. The managed runtime supplies the corresponding private-HOME,
GSettings-memory and shader-cache controls, and invokes the release's own
`Browser/firefox` wrapper and `firefox.real` binary with an explicit RAM profile.
Those are Tor Browser's internal executable names. No generic Firefox package
is installed or launched, and no signed vendor file is patched.

## Native Tor networking, with host DNS denied

The runtime path is:

```text
Tor Browser -- private Unix SOCKS --> bundled Tor -- dedicated veth --> Tor relays/circuits
```

Tor Browser has two reserved veth slots and gets its own pair for each active
session. Tor is appended to the built-in reservation order, preserving existing
application addresses. The default policy retains 81 spare slots. All four
F2FS application filters include Tor. Each Tor lease randomizes its private
veth MAC as a locally administered unicast address.

Tor is excluded from `BROWSER_PROXY_POLICIES` and the shared CONNECT supervisor.
It has no 3proxy configuration, transport proxy or dnsmasq/Stubby integration.
Its resolver file has no nameserver/search entries. The lease-owned
`tor_transport` nftables set rejects TCP/UDP port 53 and all non-TCP egress in
prerouting **before shared DNS DNAT**. The host guard also rejects DNS. Host,
LAN and other-application access remain blocked. The transport AppArmor domain
explicitly denies datagrams. Tor's reachable-address policy skips port 53 while
retaining other native relay ports, including 9001; it is not restricted to
HTTPS/443 proxies.

Tor bootstraps from native authority/fallback IP information and authenticates
its directory data. Website hostnames travel in SOCKS requests and are resolved
through Tor; onion services use Tor's onion-service protocol. Neither goes to
host DNS. See [Tor's SOCKS specification](https://spec.torproject.org/socks-extensions.html).
Native IP bridges can fit this model. External pluggable transports are explicitly
denied: their DNS/bootstrap/UDP methods are outside this runtime's no-host-DNS
contract. A censored network that requires those transports fails closed.

## Actions and data lifetime

| Action | Rendering and privacy |
| --- | --- |
| Tor Browser | RAM bundle/profile, synthetic local identity, vendor rendering/security defaults. |
| Intel OpenGL | The same RAM isolation with WebRender and the existing Intel render-device selection. |
| NVIDIA OpenGL | The same RAM isolation with WebRender and the existing NVIDIA selection. |
| ANOM | RAM state, Tor's Safest security level, software rendering, no GPU/audio-device or host-home binds, no sysfs and no D-Bus proxies. |

All actions omit host-home/document/workspace binds and D-Bus proxies. Cookies,
profile, downloaded files and Tor state disappear on exit. Two independent
RAM sessions can use the two reserved slots; each has its own state and sockets.
Native Wayland is required: the runtime validates its private socket before
starting Tor, forces `MOZ_ENABLE_WAYLAND=1` and `GDK_BACKEND=wayland`, removes
DISPLAY/Xauthority and binds no X11 socket. There is no X11 fallback.
Normal GPU actions expose only the selected rendering devices and required
read-only graphics metadata, with physical identity/network sysfs masked.
ANOM additionally supplies generic CPU-info and a fresh boot-id. Machine-id,
hostname and account files are synthetic for each session. No physical interface
or host identity is modified; the private veth MAC is not the Wi-Fi/Ethernet MAC
seen by the local network.

Tor's circuit-selection and isolation defaults are retained. Fresh RAM state
also means guard/directory state is not retained across launches; it requires
fresh bootstrap and does not provide the guard continuity of a persistent Tor
installation. RAM does not virtualize CPU instructions, protect against a
compromised host/root, prevent host hibernation from saving memory or promise
absolute anonymity. Ordinary Tor relay use remains visible to the access
network. Tor's [fingerprinting guidance](https://support.torproject.org/tor-browser/features/fingerprinting-protections/)
continues to apply, especially to hardware-rendering actions.

## Maintenance and acceptance

The source bundle and RAM executable mounts are immutable to the browser. The
enterprise policy disables binary self-updates. This change implements pinned
fresh installation, not an automatic Tor maintenance provider. Installed hosts
need authenticated administrator-controlled replacement or a fresh install
from updated release/key pins; an obsolete security release must not be retained.

No native signature, shell, AppArmor, systemd, GPU or onion integration test was
executed here. `AGENTS.override.md` requires a prepared disposable environment
without host access, which was unavailable. Static inspection/payload generation
cannot certify leak prevention. Acceptance must verify native Tor bootstrap and
onion requests, direct browser/DNS denial (including shared DNAT), RAM/no-swap
mounts, read-only bundle aliases, both child domains, all four actions and cleanup
after each child's failure. No passing runtime result is claimed.
