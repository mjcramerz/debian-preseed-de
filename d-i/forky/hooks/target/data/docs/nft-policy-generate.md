# nft-policy-generate helper guide

This guide is staged only when nftables policy generation is enabled for the
installed host.

## Purpose

`/usr/local/sbin/nft-policy-generate` renders:

- `/etc/nftables.conf`
- `/etc/nftables.d/00-defines.nft`
- `/etc/nftables.d/10-base.nft`
- `/etc/nftables.d/20-filter.nft`
- `/etc/nftables.d/30-nat.nft`
- `/etc/nftables.d/90-local.nft`

from one profile YAML plus zero or more service overlay YAML files.

## Inputs

- default profile link: `/etc/nftables/profiles/default.yml`
- profile catalog: `/etc/nftables/profiles/*.yml`
- service overlays: `/etc/nftables/services/*.yml`
- default generator env: `/etc/default/nft-policy-generate`

## Common commands

Regenerate the installed ruleset from the default profile:

```sh
env NFTABLES_LOG_LEVEL=info /usr/local/sbin/nft-policy-generate \
  --profile /etc/nftables/profiles/default.yml
```

Regenerate from an explicit profile plus overlays:

```sh
/usr/local/sbin/nft-policy-generate \
  --profile /etc/nftables/profiles/server.yml \
  --overlay /etc/nftables/services/ssh-server.yml \
  --overlay /etc/nftables/services/ssh-server.yml
```

Validate before reload:

```sh
nft -c -f /etc/nftables.conf
systemctl reload nftables
```

## Notes

- The YAML files are declarative policy, not raw `nft` fragments.
- The generator writes deterministic managed fragments; edit the YAML inputs,
  not the generated `*.nft` files.
- `NFTABLES_LOG_LEVEL` controls generator diagnostics only. Packet logging is
  still controlled by the selected profile and overlay logging fields. The
  desktop profile enables bounded `nftables accept output` auditing plus final
  input/forward drop logging even when diagnostics are set to `none`.
