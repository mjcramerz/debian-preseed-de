# qBittorrent active peer ingress — 2026-10-14

## Implemented contract

The host firewall has no qBittorrent-specific IPv4 or IPv6 INPUT allowances.
`addon/software` no longer automatically selects a qBittorrent service overlay.
The existing supported `NFT_SERVICES=qbittorrent` name remains accepted, with an
empty `services: {}` overlay. Explicit selection cannot reopen host ports; the
obsolete overlay port renderer and automatic-selection helper were removed.
The empty declaration preserves the existing service-name contract without
introducing another runtime owner for peer ingress.

Peer TCP/UDP permissions now belong to the active app-veth route. The initial
lease-wide setup creates no candidate peer-port `incoming` entries. With an
active validated route, the broker adds exactly one port for TCP and UDP,
together with its DNAT/SNAT maps and route pin, in one `nft -f -` transaction.
The host veth is lowered before this transaction. Old entries are deleted and
new entries added in the same batch. After commit, the exact new cleanup list
is recorded, the guest's stale conntrack entries are removed, and the link is
raised only after the remaining setup and controller notification succeed.

An offline route deletes all route-owned peer ingress and NAT entries and
keeps the pinned veth down. Closing the lease removes the current entries.
A failed nftables commit retains the previous cleanup list; a failure after
commit retains the newly committed list. Both paths use the existing bounded
retry with the packet path blocked. Unchanged routes and MTU-only updates
retain their existing fast paths. Fixed Discord RPC grants remain lease-owned.

Ethernet/Wi-Fi profile assignments and the previously accepted native
save-and-restart behavior are unchanged. Router configuration is unchanged.
The older uplink report describes a historical firewall design and snapshot.

## Verification boundary

`AGENTS.override.md` prohibits running tests, repository validators, native
policy parsers and installed management helpers on the development host. No
prepared disposable environment is available. No test runner, shell fragment,
native firewall parser, policy load or live network operation was executed.
No host services, package state, security policy or networking were inspected
or modified. The pure generation command is the repository's explicit exception.

## Completed source inspection

- Parsed the changed broker and two fixture modules with standard-library AST
  operations, without importing or executing repository code.
- Compared the broker against the pre-task snapshot. Only `Network.__init__`
  and `Network.update_route` changed; the Discord RPC block and other methods
  are unchanged.
- Checked as source data that `incoming`, `peer_snat` and `forwards` are added
  in the same active-route TCP/UDP loop, with one nftables commit. Verified the
  down / commit / cleanup-list assignment / conntrack cleanup / up ordering.
- Checked the empty services declaration, retained explicit service-name token,
  and removal of automatic Software selection and obsolete renderer references.
- Reviewed the generator's INPUT service builder and empty-overlay merge path.
  Empty service mappings add no rules to the supplied canonical base profiles.
- Compared modes against pre-task copies for all eight changed existing files.
- `git diff --check` completed without diagnostics.

## Focused fixtures updated, not executed

Five new tests and updated existing tests cover:

- Initial Ethernet, initial Wi-Fi and initial offline peer ingress.
- Both TCP/UDP ingress entries and NAT maps replaced in exactly one transaction
  between host veth DOWN and UP operations.
- Offline removal, exact cleanup and preserved MTU/unchanged-route behavior.
- NFT rejection retaining old cleanup state and a blocked link through retry.
- Post-commit conntrack failure retaining new cleanup state and exact removal.
- Software selection not adding the qBittorrent host overlay.
- Explicit selection publishing an empty overlay; the isolated generator fixture
  checks that no qBittorrent host-port accept rules are emitted for profile pairs.

These are fixture definitions only. Kernel nftables atomicity, live Ethernet /
Wi-Fi handoff, actual firewall reachability and native qBittorrent behavior have
not been exercised in a disposable target environment. The independent read-only
sidecar also failed to initialize due to encrypted-context hydration; no
independent review result is claimed.

## Exact paths changed for this redesign

- `d-i/forky/hooks/target/usr/local/sbin/app-veth`
- `d-i/forky/hooks/target/etc/nftables/services/qbittorrent.yml.tmpl`
- `d-i/forky/scripts/late/security.sh`
- `d-i/forky/hooks/target/etc/nftables/README.md.tmpl`
- `docs/app-veth.md`
- `d-i/forky/tests/test_kernel_veth_networking.py`
- `d-i/forky/tests/test_compz_qbittorrent_followup.py`
- `docs/validation/qbittorrent-uplink-peer-ports-20261014.md`
- `docs/validation/qbittorrent-active-ingress-20261014.md`

The permitted generation refreshes only `d-i/forky/payload.tar.gz`,
`d-i/forky/payload.manifest` and `d-i/forky/preseed.cfg`.

## Generated snapshot

Reviewed `Makefile`, `tools/build.py` and `tools/publication.py`, then ran the
explicitly permitted pure serialization command:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
```

Observed exit 0 with `built 1781 payload files`. Standard-library archive/hash
inspection compared every member against both the manifest and canonical source
bytes without extraction or execution: all 1,781 members matched, containing
34,221,702 member bytes. Safe unique relative paths, canonical regular-file
metadata, exclusion of private input basenames/private-key headers and all three
bootstrap checksum pins were checked as artifact data.

Metadata comparison across 3,167 checkout paths found 3,163 unchanged. Generation
changed only the three authorized products and the `d-i/forky` parent directory;
product ownership/modes and parent identity/ownership/mode were preserved. No
source or fixture was rewritten by generation.

| Product | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `706ee6c8da855776ffbc7591ebff4f8f3ce9f883e06710820c694b5929faa930` |
| `payload.manifest` | `8432629880a411cec8b647252b6d3b70a75c155d59ea1857b79fef35b0de4933` |
| `preseed.cfg` | `35bad4769ef9c26e85b2bcea2dd8b570af3bc0fe63f3312dc69910cf5b5767ad` |
