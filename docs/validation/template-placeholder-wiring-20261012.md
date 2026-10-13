# Installer placeholder wiring review — 2026-10-12

## Failure and correction

`qbittorrent-session.tmpl` contains no named installer placeholders. Its
`b"__INSTALLER_"` literal rejects unrendered managed configuration at runtime.
The shared installer detector matched that bare prefix, then failed to find a
named token for its error message. Desktop staging therefore rejected a valid
session helper with an unknown-placeholder diagnostic.

The shared detector now requires a name character after the prefix. Named
placeholders, incomplete named markers and lowercase names remain errors.
Missing/unreadable inputs and grep errors fail the assertion. Diagnostics show
incomplete or invalid names when no complete named token exists. The runtime
guard remains byte-for-byte intact. The software renderer uses the same
assertion so it also propagates inspection errors.

## Source inventory and production providers

Static inspection covered all 436 production `.tmpl` files in the checkout;
all are under `d-i/forky`. Named installer tokens occur in 277 templates and
use 938 distinct keys. No unaccounted provider keys remained after reviewing
literal maps, generated inventories, composed maps and deferred blocks.

| Contract | Source/provider review |
| --- | --- |
| Desktop scalar templates | Inspected all 47 explicit rendering calls; every required scalar key is supplied. |
| Dynamic desktop templates | Waybar schema plus command/output map; GTK 3/4 loop; PipeWire unit loop; Fuzzel theme-only templates. |
| Labwc XML blocks | Three workspace/recording blocks are filled after scalar rendering, followed by the final assertion. The matching strings in the installer module are intentional deferred token literals. |
| Logging | All 112 referenced LOG keys exist in observability.env; catalog references have no missing or forward dependencies. Fetch renders logging before asset-specific maps. |
| Themes | All 2,028 referenced keys across 101 templates exist in both theme data and schema, including TARGET_PATH normalization. Fetch/tree rendering removes theme tokens before publication. |
| Generic storage/templates | Generic scalar map, multiline initramfs module blocks, all generated sysctl profile keys, APT refresh keys and tmpfs pre-clean scalar/block stages. The unprefixed zram policy uses the same scalar map. |
| Network | Network input map and Perl renderer cover Ethernet/Wi-Fi identity, derived CIDRs, IPv4/IPv6 stanzas, DNS search, performance and all Wi-Fi security fragments. Adjacent markers remain separate tokens. |
| App-veth, DNS, nftables | Identity map plus DNS map; actual nftables service selector and composed profile maps; Stubby custom renderer consumes the complete DNS policy map. |
| D-Bus/systemd | Fixed D-Bus loop inventory; resource/journal map covers all 31 keys in the 14 resource templates. SYSTEMD_LOG_LEVEL belongs to the generic runtime map. |
| Secure boot/GRUB | Generic fragments, display/os-prober maps, GRUB profile snapshot map and secure-boot config map. |
| Hardware tuning | Broker/vendor JSON keys are generated from validated dictionaries; service/socket and application drop-in maps are explicit. |
| Addons/firstboot | DevOps, software launchers, QEMU/Incus, firmware, IOCost, swap fallback, Timeshift, crypto/TPM2, CrowdSec and Tailscale/Syncthing use their owned maps. SSH clone markers are constructed explicitly. |
| Other native templates | AppArmor state, NFS/export/idmapd, llama and whisper use their dedicated renderers; their named keys have providers. |
| Suffix-free SSH inputs | ssh/config and ssh/sshd_config use the common SSH renderers; ACCOUNT_USERNAME, ACCOUNT_HOME and SSH_PORT are explicitly supplied and checked before publication. |

The earlier CrowdSec identity correction is retained: its separate desktop
addon shell reads the effective late account metadata before rendering the
qBittorrent acquisition. It does not substitute a policy file for resolved
private identity.

## Regression coverage and execution boundary

`test_template_placeholder_contracts.py` is gated before runtime imports. It
adds detector fixtures and source/map contracts for desktop, networking,
security, storage, logging and themes. The nftables contract reads the actual
production selector. Fixtures use private paths and a minimal environment.

The qBittorrent staging regression now uses the real desktop renderer, shared
assertion and target-path implementation. Only transport, logging and target
parent-mode normalization are fixture seams. It checks both native profiles,
the proxy configuration and exact session-helper bytes/mode. Its previous
renderer stub bypassed the assertion responsible for the installation failure.

No tests, discovery, repository validation runner, shell syntax checker,
installer helper, policy parser, service action or source compilation was run
on the host. Python source was parsed as data with the standard library; map
inventories and callers were inspected as text. Regression fixtures have not
been executed: no approved disposable test environment is available.

Normal `make build` remains generation only. The three regenerated publication
files carry the source corrections; templates deliberately remain templates
inside the payload and are rendered by their installer owners. Existing
installer snapshots and installed host policy are not updated by rebuilding
the checkout. Static wiring evidence does not establish a completed native
installation or a passing integration suite.

`make build PYTHON=/usr/bin/python3` completed with exit status 0 and reported
1,744 payload files. A metadata inventory before and after generation found
exactly the three allowed files changed. Standard-library archive inspection
matched all 1,744 members against current source bytes and manifest SHA-256
entries, checked fixed archive metadata and confirmed both preseed pins. The
archive includes the corrected detector, retained CrowdSec identity fix and
previously supplied AppArmor grants. No archived code was executed.
