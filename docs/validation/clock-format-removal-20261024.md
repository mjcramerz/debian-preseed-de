# Remove alternate clock formatting — 2026-10-24

## Requested behavior

The user reported that clicking still changed the clock format and requested
complete removal of the alternate format. This supersedes the earlier
middle-click alternate-format contract.

| Clock input | Current source action |
| --- | --- |
| Left click / normal touchpad click | Open the native GTK dropdown |
| Middle click | No clock action |
| Right click | Toggle the managed Waycal popup |
| Hover | No tooltip or popup |

Both internal and external clock definitions retain only the normal
`format: {:%a %H:%M}`. Both `format-alt` and `format-alt-click` are removed
entirely. No replacement format-switch command or module action is installed.
The optional verifier and existing menu-contract fixture now require both
alternate-format keys to be absent. Other modules' alternate formats are
outside this clock-only correction.

Base revision: `93f9b44bc5dd8dd8c4faba1e6a486ff6c21e0237` (`mcr/main`).
The worktree was clean before this correction. The preceding Waycal theme,
task labels, AppArmor and GVFS/XFS/Calix corrections remain in that revision.

## Changed paths

- `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl`
- `d-i/forky/scripts/desktop/verify.sh.tmpl`
- `d-i/forky/tests/test_native_menu_contract_20260920.py`
- `docs/calendar-and-wifi.md`
- `docs/validation/waycal-click-20261024.md` (supersession notice only)
- `docs/validation/clock-format-removal-20261024.md`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/payload.manifest`
- `d-i/forky/preseed.cfg`
- `inventory-apt.json`
- `inventory.json`

## Verification and generation receipt

Completed static inspection without importing or executing repository modules:

- Parsed both clock definitions as JSON with unrelated installer tokens replaced by numeric stand-ins; each has the normal format and neither alternate-format key.
- Confirmed the native left-click menu, fixed right-click Waycal toggle and disabled tooltip remain, with no middle-click command or action mapping.
- Parsed the updated existing fixture and the affected embedded Python verifier as AST data, including the enclosing shell single-quote boundary.
- `git diff --check` returned exit status 0.

Both permitted generation commands returned exit status 0:

```text
make build PYTHON=/usr/bin/python3
make inventory PYTHON=/usr/bin/python3
```

The payload contains **1839** regular members and **34,897,183** expanded bytes.
A bounded streaming archive read, without extraction, compared every member
against its current source bytes and manifest digest, checked the complete
member set and normalized metadata, and confirmed the preseed hash pins. The
two packaged clock definitions were parsed and confirmed to have no alternate
format or middle-click command.

The paired inventories reference this payload's exact hash/size, and the APT
metadata digest matches its paired JSON file. All candidate indices are valid
and canonical. Public metadata refresh retained **21,359** candidates with zero
unavailable metadata requests. All 691 package requests have indexed
candidates. Metadata coverage is not a solved installation, and the collector
does not perform Release OpenPGP signature verification.

| Generated path | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.manifest` | 226692 | `c733088b16511583c5a65ee4b7d157054d6265282c6b5a7e48daba1c071e724d` |
| `d-i/forky/payload.tar.gz` | 26621075 | `6a370d066a9c7d7af4e97418b6a492a8487a160a078ec32eece0c4afabbbb128` |
| `d-i/forky/preseed.cfg` | 96407 | `803b68f9e4fdd84504d2f9a4b7a92841657b845605a9d6acf34e2bdf424f8b82` |
| `inventory-apt.json` | 19190436 | `02509f93560af2976a16a7c469ab99e7135067483f45e7498a902039cf5a381e` |
| `inventory.json` | 2489201 | `27c7e699e47b538a47d0ec553a429f89c50debd2f15275cb61b7fca6a57e0995` |

Changed payload-input fingerprint: `db6328cfe96a502bf37ac1cbac7b5c9a1101a6672550c279073293387d405520`.
This SHA-256 hashes the two changed payload source paths listed above in sorted
order as repository-relative UTF-8 path, NUL, current file bytes, NUL.
Updated fixture SHA-256: `9cb42dc011b938a8e5edbb3774e7ee98c3d8ab599bafad459d49d9a01d63c4fd`.

The independent sidecar review could not start because of a content hydration
error; it supplied no findings. The root performed the source and artifact
inspection recorded here.

No tests, native syntax runner, policy parser, GUI client, host management helper
or service operation was executed. The updated fixture remains unexecuted under
the mandatory disposable-target rule. No target image or installed package
versions were observed. The required Waybar version remains 0.15.0.

This correction updates installer source and generated output. It does not edit
an already installed user's Waybar configuration or restart their session.
Native acceptance remains separate from the static removal proved above.
