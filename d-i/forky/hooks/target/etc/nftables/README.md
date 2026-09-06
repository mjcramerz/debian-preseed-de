# nftables YAML policy bundle

This version removes service-level `ipv4_groups`, `ipv6_groups`, and `interface_groups` from the YAML files.

Service overlays now use explicit, deterministic fields:

```yaml
allow:
  ipv4:
    - 203.0.113.10/32
  ipv6: []
  interfaces:
    - eth0
    - wg0
```

Outbound rules use the same idea:

```yaml
allow_to:
  ipv4:
    - 0.0.0.0/0
  ipv6:
    - ::/0
  interfaces:
    - eth0
```

The generator is still backward-compatible with the old group keys, but this bundle does not use them.

## Generate profile only

```bash
/usr/local/sbin/nft-policy-generate \
  --profile /etc/nftables/profiles/server.yml \
  --write \
  --check
```

## Generate profile plus service overlays

```bash
/usr/local/sbin/nft-policy-generate \
  --profile /etc/nftables/profiles/desktop.yml \
  --overlay /etc/nftables/services/ssh-client.yml \
  --overlay /etc/nftables/services/kdeconnect.yml \
  --overlay /etc/nftables/services/syncthing.yml \
  --overlay /etc/nftables/services/qbittorrent.yml \
  --write \
  --check
```

## Installer Boot Policy

Concrete `hosts/profiles/<family>/<role>.env` files control installer staging:

- `NFT_PROFILE=none` skips nftables profile, service overlay, and unit staging.
- `NFT_PROFILE=default` maps to the selected role profile:
  `server` classes use `profiles/server.yml`, and `desktop` classes use
  `profiles/desktop.yml`.
- `NFT_PROFILE=baseline|desktop|server` applies that explicit profile.
- `NFT_SERVICES=none` applies only the selected profile.
- `NFT_SERVICES=ssh-server,qbittorrent` applies those service overlays, but only when `NFT_PROFILE` is not `none`.
- Selecting `addon/software` on a desktop automatically adds the qBittorrent
  overlay and opens the fixed TCP/UDP peer port `50309`.
- Selecting the installer addon class `ssh` automatically merges the
  `ssh-server` service overlay into the effective staged firewall policy.
- `NFTABLES_LOG_LEVEL=none|error|warning|info|debug` controls only
  generator diagnostic output. It must not change generated nftables policy.
  Packet logging is controlled only by explicit profile or service overlay
  `logging.*.enabled` fields. The desktop profile keeps bounded final
  input/forward drop logging and bounded accepted-output auditing enabled even
  when generator diagnostics are set to `none`.

During d-i late command, the installer writes the generated nftables files but
does not run `nft -c`. The `nft` checker opens nf_tables netlink sockets even
for syntax checks, and some installer/chroot contexts do not expose that kernel
protocol. The staged `nftables.service` override performs `nft -c -f
/etc/nftables.conf` on first boot before loading the ruleset.

Profiles are full base policies only. They generate default-deny inbound and
forwarding rules, state handling, loopback, DHCP client exceptions, separated
martian/bogon source drops, ICMP/ICMPv6 handling, optional bounded packet
logging controlled by profile or overlay `logging` fields, optional egress
audit or strict egress modes, and local extension chains. Profiles do not enable
or declare service exposure. Service exposure must come from explicit
`NFT_SERVICES` entries whose names match files in `services/*.yml`. Service
overlays are standalone and are not pinned to a specific profile.

The desktop egress audit rule is placed after the local output hook and before
application-specific outbound accept rules. It therefore records bounded
`nftables accept output` events for new application flows without changing the
accept verdict or allowing established traffic to flood the managed log.

Output policy modes are generator-validated:

- `allow_all` keeps output policy `accept`.
- `audit` and `allow_all_with_audit` keep output policy `accept` and add bounded
  unmatched-output audit logging.
- `enforce`, `strict`, and `deny_by_default` switch output policy to `drop` and
  require explicit egress rules or builtin DNS/NTP/HTTP(S) allowances.
- The strict `services/egress.yml` overlay also enables bounded output-drop
  logging when it changes a profile from audit mode to enforced egress.

Container overlays do not open forwarding by default. Docker/Podman forwarding
requires both a selected container overlay with `allow_container_outbound: true`
and a profile/overlay that enables `forwarding.enabled` or
`forwarding.router_mode`. Outbound internet access from bridged container
subnets also needs `nat.enabled: true` with masquerade enabled, otherwise the
generator leaves a diagnostic comment instead of a live masquerade rule.

The installer stages the full YAML catalog under `/etc/nftables/profiles/` and
`/etc/nftables/services/`. `NFT_SERVICES` only controls which overlays are
applied during installation. After first boot, run `/usr/local/sbin/nft-policy-generate`
with any staged profile plus any staged service overlay to regenerate
`/etc/nftables.conf` and `/etc/nftables.d/*.nft`.

## Generated files

The profile controls these outputs. `/etc/nftables.conf` includes these exact
fragments in order rather than a wildcard, so stale or host-local `.nft` files
cannot be pulled into the active ruleset accidentally:

```text
/etc/nftables.conf
/etc/nftables.d/00-defines.nft
/etc/nftables.d/10-base.nft
/etc/nftables.d/20-filter.nft
/etc/nftables.d/30-nat.nft
/etc/nftables.d/90-local.nft
/etc/nftables.d/95-firewall-security.nft
```

`90-local.nft` is generated and includes the persistent
`95-firewall-security.nft` fragment managed by Computer Management. Its
validated rule state is stored in `/etc/nftables/firewall-security.rules`;
neither file is an unrestricted hand-written override.

## Important edits before production

Replace documentation/example values such as:

```yaml
203.0.113.10/32
2001:db8::/32
```

with real host, LAN, VPN, or monitoring CIDRs.

Also verify interface names. Defaults include common names such as:

```yaml
eth0
en*
wlan0
wl*
wg0
lo
docker0
podman0
```

If your Debian host uses names like `enp1s0`, `eno1`, or `wlp2s0`, edit the YAML before applying.
Static managed-network installs also include the managed names `__INSTALLER_MANAGED_NETWORK_ETHERNET_IFACE__` and `__INSTALLER_MANAGED_NETWORK_WIFI_IFACE__`
because `/etc/systemd/network/10-managed-ethernet.link` and
`/etc/systemd/network/11-managed-wifi.link` pin generated ifupdown stanzas to
MAC-matched installed adapters.
