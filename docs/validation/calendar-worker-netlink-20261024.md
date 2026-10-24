# Calendar worker netlink permission — 2026-10-24

The user supplied seven AVC denials on LPL-715, audit serials 3027, 3040,
3041, 3043, 3047, 3048 and 3049. Each names profile
`labwc-calendar-worker`, operation `create`, family `netlink`, socket type
`raw` and protocol `0`. The source profile had IPv4/IPv6 stream and datagram
permissions but no netlink allowance.

`d-i/forky/hooks/target/etc/apparmor.d/calendars` now contains the following
rule inside `profile labwc-calendar-worker`:

```apparmor
network netlink raw,
```

This permits the family and socket type in the reported denials. It adds no
IP raw-socket rule, network capability or unrestricted `network,` rule. The
worker's HTTPS acquisition path and the other calendar profiles are unchanged
by this correction. The same netlink rule syntax is already used by existing
repository profiles. The included `nameservice-strict` is a target vendor
abstraction, not a source file in this checkout.

## Recorded checks

- Inline `/usr/bin/python3 -I -S -B -` read the policy as data and confirmed
  the rule occurs once, inside the worker profile, with no added capabilities
  or unrestricted network rule. Policy SHA-256:
  `1447abb896885315281279db5617214afb5c4dc7bb55abe39dddeeb50886a610`.
- `git diff --check` completed without errors.
- `make build PYTHON=/usr/bin/python3` completed: 1,830 payload files.
- Separate bounded standard-library archive/hash inspection matched every
  member to current source and manifest bytes: 34,862,156 expanded bytes.
  Preseed archive, manifest and bootstrap-source pins match; private input
  names are absent.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `2bb0f0768807eaa8c5f9c35c7e8da5ec0eb3abf6acd5426638928389c290b498` |
| `d-i/forky/payload.manifest` | `d6420370725b7d95647014eb9a902da134e842e7070a63541f5486eeb06d4b82` |
| `d-i/forky/preseed.cfg` | `934de22f3ef3a1a43f7ab2ebd994676089b5eab972ef5ba7c9a122f88fa851c7` |

No test runner, native policy parser, policy reload, remote Fruux operation or
deployment was run. The independent sidecar failed encrypted-content
hydration; no independent review is claimed. A read-only public kernel-header
lookup timed out and is not used as evidence. The declared target remains
Debian Forky/systemd 262; no installed target package state was read. Loaded
policy and live operation on LPL-715 remain unverified. Root offline inventories
remain separate, stale generation products.
