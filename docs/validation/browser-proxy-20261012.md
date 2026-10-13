# Browser and qBittorrent namespace proxy integration — 2026-10-12

The managed configuration location recorded below was superseded on 2026-10-13
by `/etc/labwc/3proxy/` to avoid the upstream package directory's ownership and
permission changes. See [the installed failure review](installed-desktop-failures-20261013.md)
for the current paths and new generation evidence. The historical checks and
hashes below describe the earlier snapshot.

## Implemented source contracts

- Chromium, Microsoft Edge, Vivaldi and Mullvad Browser use foreground 3proxy
  inside their existing persistent or PurePrivacy namespaces. Offline launches
  keep their private offline network and start no proxy.
- Shared `/usr/local/libexec/labwc-proxy-session` waits for proxy readiness,
  watches both children using pidfds, stops the application on proxy failure,
  and stops the proxy after application exit or bounded service-stop cleanup.
  Existing singleton profile and shared application temporary-directory paths
  are retained. The separate qBittorrent supervisor was consolidated into this
  helper; no stale call to `qbittorrent-session` remains in executable sources.
- Five distinct install-rendered proxy configs live under canonical
  `hooks/target/etc/3proxy/`. No inline 3proxy configuration or runtime config
  generation is used. The listener map is a separate target JSON template.
- All ten host profiles expose eight `PROXY3_*` fields. Destination allowlists
  default to `443,8443,53443` for browsers and `443` for qBittorrent. Listener
  ports, connection caps and all ten upstream timeout fields are configurable.
- Strict POSIX-shell/awk map validation rejects malformed/injected values,
  duplicate or out-of-range ports, port 80, invalid caps and invalid timeouts.
  Map input is data; no eval or full environment inheritance is used.
- Mandatory Chromium-family policies and Mullvad distribution policy are
  canonical target files. They set a local fixed proxy without DIRECT fallback,
  prevent normal policy changes and disable direct UDP browser protocols.
- Browser lease egress is TCP-only on the same configured destination ports.
  Both firewall input hooks permit HTTPS-port access from allocated browser
  leases to the host LAN address; custom LAN blocking remains effective.
  DNS keeps its exact namespace endpoint. Torrent peers retain direct TCP/uTP.
- The broker static nft configuration moved from inline Python into
  `hooks/target/etc/app-veth.nft.tmpl`, installed as `/etc/app-veth.nft`.
  Opened-file trust/size checks and remaining-token rejection protect the read.
  The existing read-only `app-veth --check-config` also checks this asset now.
- Core desktop package selection owns the signed 3proxy binary repository;
  optional addon package ownership no longer excludes Chromium-only installs.
  The vendor host proxy service stays masked.
- Narrow AppArmor grants cover the new config/helper paths and inherited
  3proxy execution. Existing private Xwayland behavior was not changed.

## Exact evidence collected in this turn

Static inspection only, using source text/AST/JSON and standard data parsers:

- 397 Python source files parsed with `ast.parse`; zero syntax errors.
- All 10 profile inventories contain the complete eight-field settings set.
- 120 substitutions across 12 canonical assets have no unresolved installer
  tokens in the materialized data. This includes 60 JSON documents.
- Both explicit native qBittorrent render calls cover every actual template key,
  including the new proxy listener field.
- `git diff --check` completed without whitespace errors.
- Existing lifecycle, namespace and placeholder fixture sources were adapted;
  a guarded proxy configuration/hostile-input fixture was added. These tests
  were NOT executed.

Permitted serialization command:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
```

Observed output: `built 1754 payload files`.

An owned before/after inventory of 2,369 repository files established that the
build changed exactly `payload.tar.gz`, `payload.manifest` and `preseed.cfg`.
Streaming archive inspection compared all 1,754 entries / 33,931,448 source bytes
against the checkout and manifest. Path inventories and SHA-256 digests agree;
archive entries are regular files with mode 0644, uid/gid/mtime zero. Generated
archive/manifest/bootstrap pins agree. Nothing was extracted or executed.

| Product | SHA-256 |
| --- | --- |
| payload.tar.gz | 80c58ce55cfd58c40a22ad64bfb4f5322a6f31b10e6d10275012acbcc0a533f8 |
| payload.manifest | 833cb259fc83e29072388f093ff57a2f3e09a2f4c1f425229227ffb0fd4d4650 |
| preseed.cfg | eba902146328e0b242bdcd751349f863430fa0d8d27f2f8ae484d8e19ba8a299 |

## Not executed and deployment limits

No tests, discovery/import runners, repository validators, native AppArmor/nft
parsers, host services/helpers, package operations, namespace integration or
live GUI/network checks were executed. No prepared disposable environment was
available. Agent sidecar startup failed with encrypted-content hydration errors;
there is no independent agent review result.

Primary-source GET research confirmed upstream proxy/enterprise-policy syntax
and the Mullvad distribution policy reader. The sibling server's source sets
Technitium HTTPS 53443 and Incus HTTPS 8443. CONNECT transports TCP without TLS
inspection. WebUIs must actually serve HTTPS and present trusted certificates;
adding a plaintext WebUI port would not encrypt it. The local managed qBittorrent
WebUI remains disabled. Host localhost denotes the browser's own namespace;
use the host LAN address/name for services hosted on the desktop.

The official repository page advertises signed binary packages at the configured
`https://3proxy.org/repo/deb` current channel. Public GET requests for
`https://3proxy.org/repo/3proxy-release-key.asc` and
`https://3proxy.org/repo/deb/dists/current/Release` both returned HTTP 403.
Package availability, archive signature acceptance, maintainer-script behavior,
browser policy acceptance, all firewall/AppArmor syntax, proxy death/group-stop
behavior and native singleton activation remain fresh-install acceptance gates
inside a disposable environment. Static success is not a verified installation.
