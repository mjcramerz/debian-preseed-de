# qBittorrent uplink peer ports — 2026-10-14

> The host firewall design and generated hashes below are historical. The later [active peer-ingress redesign](qbittorrent-active-ingress-20261014.md) removes host INPUT allowances and records the replacement snapshot.

## Accepted contract

Each profile has exactly one Ethernet port and one Wi-Fi port. Existing Ethernet
values are preserved. P15s Wi-Fi uses 50408, Flex uses 50409, and the other six
profiles use 50410. The user selected saving state and restarting qBittorrent
when the selected port changes. The WebUI remains disabled.

`LABWC_QBITTORRENT_PORT="Ethernet,Wi-Fi"` renders the broker's exact two-key
`peer_port` object. Legacy scalar values remain supported. Actual wireless
egress is detected through sysfs `wireless`/`phy80211`, not interface names.
Non-wireless and VPN egress keep the primary port. Only the active TCP/UDP
DNAT/SNAT maps and source-address port reservations are installed. The host
firewall overlay has separate Ethernet/wireless allowances.

The owning lease receives a bounded, validated event over its private Unix
seqpacket socket. Its supervisor passes the selected port through an inherited
private seqpacket descriptor. The namespace-local process asks qBittorrent to
exit with SIGINT and waits at most 15 seconds for status 0. Only after that exit
are exact installed native-policy bytes restored and qBittorrent restarted with
`--torrenting-port`. Original launch inputs are not replayed. Native resume
files remain in the existing private profile. `Session\AnnouncePort=0` follows
the active listener. A failed save or timeout refuses automatic restart.

The 15-second timeout is a bounded attempt to let the native application save;
no live evidence establishes successful saving under every storage condition.
Router TCP/UDP forwards still need to match each port and uplink address.

## Evidence and limits

- Reviewed the source contract from profile reader through installer maps,
  native policy/firewall staging, broker route replacement, lease recovery,
  namespace callback, private descriptor and payload lifecycle.
- Standard-library AST parsing of six changed Python runtime sources and four
  changed fixture files succeeded. Source was parsed as data; no repository
  module, helper, fixture, shell snippet or native policy parser was executed.
- Compared all ten profiles to the private pre-task snapshot: each Ethernet
  value is unchanged, the requested Wi-Fi assignment is exact, and every other
  profile field is byte-for-byte unchanged after removing the new port comment.
- Confirmed file modes against the pre-task snapshot for all 30 changed existing
  paths. Reviewed the AppArmor diff: wireless sysfs metadata and the nested
  qBittorrent controller/policy grants only. Existing Xwayland assets unchanged.
- `git diff --check` completed with no diagnostics.
- Added 11 guarded regression tests and updated existing assertions/fixtures:
  typed policy/rendering, actual overlay publisher, private IPC framing, owning
  supervisor handoff, lease reconnection, TCP/UDP map replacement, retry with a
  blocked packet path, clean restart, failed save and simultaneous user close.
  **These tests were not run.** No disposable environment is available, and
  `AGENTS.override.md` prohibits host test or validator execution.
- AppArmor loading/parsing, firewall execution, real qBittorrent GUI/resume
  behavior and physical Ethernet/Wi-Fi switching were not run. No host service,
  networking, package or security configuration was inspected or changed.
- Independent read-only review agents could not start because encrypted context
  hydration failed. The source review above was performed by the coordinating
  agent; no independent review result is claimed.

## Primary upstream contracts

- [qBittorrent 5.2.4 startup port override](https://raw.githubusercontent.com/qbittorrent/qBittorrent/release-5.2.4/src/app/application.cpp): startup applies the native torrenting port; existing-instance parameter serialization does not carry that port.
- [qBittorrent 5.2.4 SIGINT handling](https://raw.githubusercontent.com/qbittorrent/qBittorrent/release-5.2.4/src/app/signalhandler.cpp): SIGINT requests normal application exit.
- [libtorrent announce-port contract](https://raw.githubusercontent.com/arvidn/libtorrent/RC_2_0/include/libtorrent/settings_pack.hpp): zero uses the listening port.

These are upstream source contracts, not confirmation of an installed package
version or live target behavior.

## Changed paths for this port task

Earlier Tor, browser, graphics and Tailscale work remains in the checkout. The
following list records only this port task's changes relative to its snapshot:

- `d-i/forky/hosts/profiles/btrfs-de-duo.env`
- `d-i/forky/hosts/profiles/btrfs-de-flex-duo.env`
- `d-i/forky/hosts/profiles/btrfs-de-flex.env`
- `d-i/forky/hosts/profiles/btrfs-de-p15s-duo.env`
- `d-i/forky/hosts/profiles/btrfs-de-p15s.env`
- `d-i/forky/hosts/profiles/btrfs-de.env`
- `d-i/forky/hosts/profiles/f2fs-de-hp14-duo.env`
- `d-i/forky/hosts/profiles/f2fs-de-hp14.env`
- `d-i/forky/hosts/profiles/f2fs-de-x360-duo.env`
- `d-i/forky/hosts/profiles/f2fs-de-x360.env`
- `d-i/forky/scripts/common/modules/app-veth-identity.sh`
- `d-i/forky/hooks/target/usr/local/sbin/app-veth`
- `d-i/forky/hooks/target/usr/local/libexec/labwc-proxy-session`
- `d-i/forky/hooks/target/usr/local/bin/labwc-qbittorrent`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/app_veth_policy.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/network_client.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/network_namespace.py`
- `d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/app-veth.tmpl`
- `d-i/forky/hooks/target/etc/nftables/services/qbittorrent.yml.tmpl`
- `d-i/forky/hooks/target/etc/nftables/README.md.tmpl`
- `d-i/forky/hooks/target/etc/qbittorrent/qBittorrent.conf.d/10-security.conf.tmpl`
- `d-i/forky/scripts/late/security.sh`
- `d-i/forky/scripts/desktop/components/target-assets.sh`
- `d-i/forky/scripts/desktop/detect.sh.tmpl`
- `d-i/forky/tests/test_kernel_veth_networking.py`
- `d-i/forky/tests/test_compz_qbittorrent_followup.py`
- `d-i/forky/tests/test_proxy3_configuration.py`
- `d-i/forky/tests/test_workspace_no_broker.py`
- `docs/app-veth.md`
- `docs/validation/qbittorrent-uplink-peer-ports-20261014.md`

Generation also refreshes exactly `d-i/forky/payload.tar.gz`,
`d-i/forky/payload.manifest`, and `d-i/forky/preseed.cfg`.

## Generated snapshot

Executed the explicitly permitted pure serialization command after reviewing
`Makefile`, `tools/build.py`, and `tools/publication.py`:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
```

Observed exit 0 and `built 1781 payload files`. Compared all archive members
with both canonical source bytes and manifest SHA-256 records using only Python
standard-library archive/hash operations, without extracting or executing them.
All 1,781 members matched, with 34,222,810 bytes of member content. Member names
were unique and safe, regular-file metadata was canonical, private input
basenames and private-key headers were absent, and the archive/manifest/source
bootstrap pins matched `preseed.cfg`.

Compared metadata for 3,166 checkout paths immediately before/after generation:
3,162 were unchanged. Only the three permitted artifacts and the parent
`d-i/forky` directory changed; artifact ownership/modes and parent identity,
ownership/mode remained unchanged. No source or fixture was rewritten.

| Product | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `ad350355b3f1d1f6b8ee83dd0977dddd24fbc443056d23a664d72802c48088e5` |
| `payload.manifest` | `a2a160b6aaf82ecc3812abbd729a78089cb3ca1139192730b809d19c6c856a48` |
| `preseed.cfg` | `6f59ecd970a3a6664084d7a3ded925bacc6e683256affd281a7c7b3620c0918b` |
