# Debian Forky unattended desktop installation

Preseed sources, target configuration and deployment helpers for the labwc
Wayland desktop. The deployment target is Debian Forky with systemd 262.
Review the selected host profile, disk identifiers and credentials before use;
installation repartitions the selected disks.

The desktop role clones the Obsidian vault from the managed GitLab SSH
repository into `~/Syncthing/obsidian-md`. An account-local Labwc timer
commits settled edits and forwards the main branch to staging and release
hourly while the managed SSH key is unlocked. Setup and conflict behavior are
documented in `d-i/forky/hooks/target/usr/local/share/doc/git/README.md.tmpl`.

The [2026-09-26 firstboot and AppArmor repair](docs/validation/firstboot-audit-20260926/README.md)
records the reproduced audit delivery failure, focused fixes, validation results,
and remaining installed-host checks for this snapshot.

The [2026-09-24 logging repair](docs/validation/history/LOGGING-REPAIR-20260924.md) documents the
shared tmpfiles prerequisite fix, unified `apps.log`, 2 MiB writer-driven rotation,
and current validation limits. It supersedes older logging descriptions.

The current [security repair and operating gates](docs/security-hardening.md)
cover A01-A09, rsyslog tmpfs, and the installer module/loading contract. Run `python3 -B tools/build.py`
after editing sources; run `python3 -B tools/build.py --check` before publishing.

## Network sharing

All ten profiles have explicit NFS server/client and home-bind controls.
`btrfs-de-p15s` enables its server and server home bind; `btrfs-de-flex-duo`
enables its client and client home bind to `192.168.50.82:/`. The other eight
profiles disable both roles. Review the selected profile before installation.
`/data/sharing` and `~/Sharing` are parents for separate server/client children;
only the configured server child is exported. The existing Computer
Management menu includes **Network & Remote -> Network Sharing**.
Client source and home bind use `auto` and start in dependency order at boot.
Disconnected client directories remain navigable, root-owned and unwritable
by the ordinary account. **Connect to NFS Server** retries a failed connection;
there is no autofs or path activation layer. The
[2026-10-07 client access repair](docs/validation/nfs-client-access-20261007.md)
records the permission, boot mount and retry regression checks. Read the
[configuration, trust model and deployment guide](docs/network-sharing.md) and
[validation record](docs/validation/network-sharing-20260930/README.md) before
enabling a role. `make build` validates NFS profile policy before publication.
The generated installer snapshot is included; see [build status](BUILD-STATUS.md)
for the non-passing broad regression suite and outstanding live acceptance.

The [2026-10-05 supplied-log repair](docs/validation/installed-incidents-20261005.md)
records the NVMe correctable-log workaround compatible with kernel lockdown,
Ethernet/Wi-Fi fallback, NFS identity startup, P15s speaker policy, the exact
`ksecretd` denial, and the remaining hardware/account/vendor incidents.

The [desktop launcher and document repair](docs/validation/desktop-incidents-20261005.md)
records shared Fuzzel output/geometry selection, Tuta attachment/download and
USB policy, document app access, native display recovery, Vivaldi driver safety,
and Zathura defaults. It separates the verified repository fixes from the
HDMI/translation freeze and remaining installed-host acceptance.

## Source layout

- `d-i/forky/repo.env`: repository role, path contract and default selections.
- `d-i/forky/classes/`: package selections, class metadata and hardware assets.
- `d-i/forky/hosts/installer/`: shared settings, including `btrfs.env` and `f2fs.env`.
- `d-i/forky/hosts/profiles/`: ten directly editable host environments; the builder never overwrites them.
- `d-i/forky/hooks/installer/`: installer hooks and pre-pkgsel APT policy.
- `d-i/forky/hooks/target/`: target-side files and renderable configuration.
- `d-i/forky/scripts/`: small installer entrypoints and shared runtime modules, detailed below.
- `d-i/forky/tests/` and `tools/`: executable regression tests and build checks.
- `browser-config/`: browser policies; extension exports are cloned over SSH into `~/Workspace/netscape` from `git@gitlab.com:core-assets/helpers/netscape.git` on `mcr/main`. Extension settings remain user-editable; exports are imported manually in each extension. Current Chromium-family browsers use uBlock Origin Lite (Manifest V3).

### Installer implementation

All executable installer sources live in `d-i/forky/`; there is no parallel
root authoring tree or profile generator. Edit the `.env` files where they are.
Shared paths, filesystem and logging policy remain in `hosts/installer/` and
`hosts/logging/`; per-host choices remain in `hosts/profiles/`.

```text
scripts/common/bootstrap.sh      shared, snapshot-backed module loader
scripts/common/lib.sh            ordered common entrypoint
scripts/common/modules/          paths, logging, profiles and class resolution
scripts/runtime/common.sh        shared storage-runtime entrypoint
scripts/runtime/modules/         arithmetic, identity, crypto and recipe helpers
scripts/desktop/components.sh    ordered desktop component entrypoint
scripts/desktop/components/      application, session and service definitions
scripts/late/devops.sh.tmpl       DevOps entrypoint and explicit main invocation
scripts/late/devops/             validation, toolchain and publication modules
```

Modules are actual runtime dependencies in the pinned payload, not fragments
concatenated back into large generated scripts. The explicit entrypoints define
load order. Missing dependencies fail closed; templates use the existing logging
renderer. The credential and debconf helpers are shared by the common and storage
runtimes instead of being embedded into both.

Custom launchers are sourced from
`hooks/target/usr/local/share/applications/`. Package-owned launchers remain in
`/usr/share/applications`; synchronization reads local overrides first. Dynamic
DevOps configuration templates are under
`hooks/target/usr/local/share/devops/templates/` and are rendered into their
configured state directories, not installed as unresolved templates.

Application tuning uses systemd dash-prefix drop-ins:
`labwc-native-.service.d/`, `labwc-wayland-.service.d/`,
`labwc-electron-.service.d/` and `labwc-devops-.service.d/`.
These are prefix directories, not literal wildcard names. `labwc-session.target`
owns the desktop lifecycle and is bound to the compositor. Session clients
require an already-active target and stop with it rather than starting a new
compositor themselves. Private Xwayland remains limited to Zoom and Discord.
Firefox, Blender and Kdenlive are excluded by the pre-pkgsel APT policy.

Zoom and Discord bridge text selections between the host and their private
Cage session. The host uses `wl-paste --watch`; Cage does not expose the
data-control protocol, so the reverse direction polls the selection through
its already-private Xwayland socket with the packaged `xclip` tool. The bridge
validates both compositor sockets, caps text at 8 MiB, suppresses echoes and
stops with the managed application service. Native Cage clipboard behavior
still requires a logged-in desktop acceptance test.

Fail2ban uses Debian's packaged `fail2ban.conf`, `jail.conf`, paths, filters and
nftables action, with installer-owned `.local` overrides under
`hooks/target/etc/fail2ban/`. Both security profiles install `nftables` and
`fail2ban`. The SSH journal jail runs even before OpenSSH is installed; it uses
the selected OpenSSH port or port 22 by default. Repeat bans increase up to
one week using the persistent database. CrowdSec, when selected, acquires the
SSH journal independently and owns separate nftables sets. Tailscale SSH uses
tailnet identity controls and does not produce OpenSSH authentication failures
for the SSH jail. Installation validates the effective configuration with
`fail2ban-client -t` in the target.

### Archive menu and Packer plugins

Run `compz` as the desktop user from a directory under `/home`, `/data` or
`/pool` containing the files or archives. Its menu selects compression,
extraction, verification or listing;
extraction creates a folder named for each archive, resolves split volumes and
can unpack nested archives. It keeps source files and refuses to replace an
existing destination. Compression uses a tar container, with an optional GPG
AES-256 envelope. `compz --check` reports missing managed prerequisites, which
prevent the interactive menu from starting. RAR creation is offered
only where Debian provides the `rar` archiver; RAR extraction remains available
on arm64. The archive worker requires its AppArmor profile and an active systemd
user manager.

The managed qBittorrent desktop entry starts `labwc-qbittorrent` in a session
service. It uses `/run/media/<user>/bittorrent` when present; if that transient
volume is absent, it creates private persistent storage in `~/bittorrent`.
The launcher's TCP/UDP listener, both kernel DNAT forwards and the `addon/software`
firewall overlay use the profile's `LABWC_QBITTORRENT_PORT`. Ports are canonical
decimal integers in `1024..65535`; the default is `50309`. The current P15s
profile selects `50308`. Forward both TCP and UDP from the router to the same
selected port on the system's LAN address.

qBittorrent runs in a private Bubblewrap network with a dynamically allocated
`eth0` veth address.
The launcher selects the active IPv4 Internet route, excludes loopback and
Tailscale, and pins kernel-routed outbound traffic and both host peer listeners
to that route's source address. Both forwards must succeed before the payload
starts. An explicit readiness gate prevents payload execution on startup-pipe
EOF; failed setup also kills the pinned namespace. A bounded startup lock
serializes concurrent first launches, and later requests use the existing
application's local IPC socket.
Relaunch after changing the route or VPN. Router forwarding works when the
Internet route uses the router connection; a VPN route needs forwarding at its
own public endpoint. This forwarding contract requires IPv4. DNS uses an extra
loopback listener of the host systemd-resolved service, including its active VPN
and split DNS policy. DHT, PeX, LSD, automatic port mapping and the Web UI remain disabled;
HTTPS tracker certificates are checked and normal tracker failover is used.

Managed qBittorrent launches use Qt's built-in Fusion style to avoid the supplied
Adwaita focus-paint crash. Its direct and Bubblewrap AppArmor profiles share the
same runtime grants for read-only disk classification metadata in sysfs,
account-owned process metadata and account-owned terminal I/O. Mounted torrent
storage needs no raw block-device access. Disk devices and writable sysfs are
not exposed to the torrent payload. The root network service constructs veth
interfaces through netlink; it does not use a TUN/TAP device.

### Managed private networking

The managed Chromium, Edge, Vivaldi, Mullvad Browser, Code, Postman, Bitwarden,
Obsidian, QoreDB, Sleek, Spotify, Filen, Ledger Live, Telegram, KeePassXC,
RetroArch, MPV, Liferea and FreeRDP launchers use private kernel veth networks.
ChatGPT/Codex, Tuta, Zoom and Discord use the same broker. Ordinary online
PurePrivacy launches also use veth; the existing offline KeePassXC and
RetroArch PurePrivacy policies remain offline. Generic desktop wrappers route
known package executable paths back through these managed launchers.

`app-veth.service` pre-creates 32 separate veth pairs at boot before publishing
readiness or starting the greeter and Podman API service. Idle host adapters
are `veth0-app` through `veth31-app`, with matching `vethN-peer` endpoints;
both ends stay DOWN until assigned. NetworkManager leaves these reserved slots
to the service. Each authenticated lease moves an existing peer into the
caller's namespace. Host names stay fixed for the entire pool lifetime; app
names are recorded in structured lifecycle logs. Current and future managed
policies need no interface-name mappings. Apps never create host adapters.

The service validates each namespace FD and its owning account before
attaching the existing veth. Firewall changes commit before the payload startup
gate opens. Source validation rejects spoofed addresses, host services and
other managed namespaces are blocked, and cleanup removes the packet path
before its rule elements, then returns the DOWN, address-free peer to the
pool. A cleanup failure keeps the default-deny guards
installed until recovery succeeds. Recovery handles tagged service endpoints
and an interrupted creation of an exact, mutually paired, DOWN, address-free
idle pair; it preserves other untagged or foreign-tagged interfaces.
The uplinks are IPv4; route
interface MTU is preserved and no traffic shaper or userspace packet router is
introduced. Actual throughput still needs measurement on the installed host.

Private DNS requests at `10.0.2.3:53` are sent to systemd-resolved's extra
loopback listener, `127.0.0.1:53053`, over TCP or UDP. The main host stub and
the host's DNS/VPN policy remain authoritative. Lifecycle records go to
`/var/log/managed/network/veth.log` through the managed logging/rotation policy.
Application state and selected document/device paths are retained explicitly;
each application's private temporary IPC directory supports subsequent launches.
The capability-free FreeRDP sandbox retains askpass and ordinary clipboard IPC;
privileged FUSE clipboard mounts are outside that sandbox's permissions.

Podman's internal bridges use Netavark with nftables, behind the kernel veth
uplink. Its configured helper is `/usr/local/libexec/app-veth-podman`.
The `default_rootless_network_cmd` compatibility selector in Podman's config
selects the custom helper ABI; it does not install or execute that selector's
namesake program. Codex and ChatGPT retain the existing
`/run/podman-devops/podman.sock` Unix API binding for container/custom MCP work.
User-installed MCP configuration is independent of this installer networking.

The installer renders the broker's account and peer port through the validated
scalar map, then runs `app-veth --check-config` before enabling the service.
Malformed or non-regular configuration fails during installation. The broker's
enforced AppArmor profile permits Forky's resolved `ip` executable, its immutable
iproute2 lookup files, and the adapter's exact root-owned Netavark namespace
endpoint. Broker and client profiles permit the exact nsfs root read mediated
as `/` by `attach_disconnected`, with literal namespace-name brackets escaped;
this read grants no child paths. Supervisors can inspect their caller-owned
child namespace and send the confined child SIGTERM/SIGKILL, with the existing
explicit ptrace peer rules and host capability restrictions retained. The Podman helper also supports its
side-effect-free `--version` probe. The
[installed startup repair record](docs/validation/installed-startup-20261009/README.md)
and [LPL-746 firstboot follow-up](docs/validation/installed-startup-20261009/lpl746-namespace-read.md)
document the supplied failure evidence, regression results and installed-host
acceptance requirements.

Mako starts after a five-second wait in its session-bound user service. The wait
also applies to D-Bus activation; notification producers ordered after Mako wait
for the daemon to acquire its notification bus name. Later notifications use
the existing delivery and timeout settings. The canonical activation file now
selects `SystemdService=mako.service`; the package refresh helper preserves that
selection. Login and D-Bus activation share the same service owner.

Ctrl+Win+L runs the idle toggle through the desktop user manager so it reads
the root-owned policy in the host namespace. Policy ownership validation stays
strict; the override remains session-only and preserves explicit/manual locking.

ChatGPT binds existing standard save directories into its private home and
activates the document portal before binding `/run/user/<uid>/doc`. Exported
portal documents have confined write permissions for saving. Missing optional
save directories are skipped; an unavailable document portal produces an
actionable launch error. See [the runtime validation record](docs/validation/desktop-runtime-20261007.md)
for evidence and installed-desktop acceptance requirements.

The DevOps installer authenticates the exact Packer plugin releases, installs
their binaries into the account's private plugin directory, then checks local
checksums and the managed HCL constraints. The installation does not invoke
`packer init`, which would repeat remote plugin discovery.

## Build and verify

Run from the repository root with Python 3 and the standard Debian tools:

```sh
make build
make check
make test
make audit
make validate
```

The builder refreshes `d-i/forky/preseed.cfg`, `payload.manifest` and
`payload.tar.gz`, checks module references, and refreshes the existing browser
artifacts and self-contained lifecycle bootstrap. **It never generates, repairs
or overwrites environment files or runtime modules.** Editing an environment
requires rebuilding the payload/pins before publishing; rebuilding packages your
edited bytes, it does not replace them with defaults. Do not hand-edit the three
snapshot products. The validation
runner records results under `.build/validation/` by default. Parser checks
need the corresponding tools and Perl modules; missing dependencies must be
reported as blocked or skipped, not treated as successful execution.

Optional root-only, offline hardware-policy fixture checks:

```sh
python3 -B tools/check_hardware_tuning.py
```

These checks never start target units or load AppArmor policy into the kernel.
They do not replace an unattended VM install, boot/logout tests, enforcement
checks or testing on the intended GPU and storage hardware.

## Publish

Publish the complete rebuilt snapshot atomically. Prefer validated HTTPS or
trusted local installation media. This example is only for an isolated,
trusted lab network:

```sh
python3 -m http.server --bind 0.0.0.0 8000 --directory .
```

Point the installer at `/d-i/forky/preseed.cfg` on that server and supply the
appropriate class selection and deployment-specific credentials. Plain HTTP
does not authenticate the initial preseed: checksums embedded in it do not
repair that trust boundary. Restrict access to the repository and browser
inputs. Read `SECURITY.md` before deployment, especially the retained,
source-specific legacy CUDA authentication exception.
