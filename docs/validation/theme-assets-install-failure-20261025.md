# Pinned theme installation failure — 2026-10-25

## Scope

This records the archive-level correction against HEAD
`1bf8491d3c368b6099d15e6852dd547c9bf2e02c` for the fatal installer step
`install pinned GTK3/GTK4 and Qt desktop theme data`.

The requested fix is in the checked-in theme bytes. The installer no longer
calls a runtime image repair module. The strict local CSS/resource reference
checks remain in place.

The unrelated edits in `AGENTS.override.md`, `tools/inventory.py`,
`tools/inventory_apt.py`, and `tools/tests/test_download_inventory.py` were
preserved. The inventory utilities were not executed or integrated into this
work.

## Cause and corrections

The first reported Arc failure was in compiled GResource CSS, so checking only
loose GTK stylesheets was incomplete. A complete bounded archive scan found
the following defects:

- Arc GTK3 CSS in the embedded resource bundles referred to
  `assets/thumbnail-frame.png`; Arc GTK4 resource CSS also referred to the
  missing text-selection and marked-slider PNG families.
- WhiteSur GTK3 resource CSS referred to the missing
  `thumbnail-frame.png`.
- ChromeOS, Matcha, Qogir, and Vimix source GTK CSS contained missing or
  incorrectly named image references.
- Rosé Pine GTK3 bundles contained stale embedded CSS references and raster
  data stored under `.svg` resource names. The resource payloads now use the
  corresponding native SVG bytes from the same pinned archive.
- Three loose Kvantum files contained malformed color literals:
  Matcha Sea Dark selection text and the two WhiteSur alpha colors.

All modified GTK archives were repacked as data with Python's standard library.
No upstream build system, compiler, renderer, Gio loader, maintainer script,
package manager, service, host helper, or disposable environment was used.

| Archive | Archive-level correction |
| --- | --- |
| `arc-theme_20221218-3_all.deb` | Repack Arc and Arc-Dark compiled GResources with complete embedded CSS asset sets and generated native SVG replacements. Debian control `md5sums` was refreshed for the changed data members. |
| `WhiteSur-Light.tar.xz`, `WhiteSur-Dark.tar.xz` | Repack the GTK3 resource bundles with the thumbnail frame SVG and corrected embedded CSS URLs. |
| `rose-pine-gtk3.tar.gz` | Repack all six GTK3 GResources, replace mislabeled raster payloads with the archive's native SVG members, and correct the embedded GTK3.20 disabled-control references. |
| `ChromeOS-b80a8b77f189.tar.gz` | Correct light/dark disabled and colored slider references in the source GTK stylesheets. |
| `Matcha-4f18ea92d53d.tar.gz` | Add the Sea variant's native SVG replacements for selection, slider, check-symbolic, and thumbnail assets and update the Sea CSS references. |
| `Qogir-619f33047877.tar.gz` | Add native SVG replacements for check, thumbnail, and title-button assets, add the logo aliases consumed by the GTK CSS, and update both selected stylesheets. |
| `Vimix-c11aca86854d.tar.gz` | Add native marked-slider SVG replacements and update the Doder GTK stylesheets. |
| `Ant-79ddc06b40ad.tar.gz`, `Dracula.tar.xz`, `Nordic.tar.xz`, `Sweet-Dark.tar.xz` | Preserve the earlier archive repacks for their missing control-state images and automatic-color swatches. |
| `sources.json` | Record every new local length/hash and the upstream length/hash plus modified and added members under `repack`. |

The corrected loose Qt inputs include:

- `qt/Matcha-sea-dark/Matcha-sea-dark.kvconfig`
- `qt/WhiteSur/WhiteSur.kvconfig`
- `qt/WhiteSur-opaque/WhiteSur-opaque.kvconfig`
- `qt/WhiteSur/WhiteSur.svg`
- `qt/WhiteSur-opaque/WhiteSur-opaque.svg`
- `qt/WhiteSurLiquid/WhiteSurLiquid.svg`

`theme_repairs.py` was removed from the target package and from the
appearance staging and verification lists. `theme_assets.py` now materializes
the pinned archive output directly. Its `Candidate.repairs` field remains an
empty compatibility inventory field; no runtime repair records are produced.

## Static verification

The following checks were run as static data inspection or pure serialization:

- `python3 -I` AST parsing of the changed production and fixture Python
  sources: passed for four files.
- `git diff --check`: passed.
- `sources.json`: all 193 pinned files match their recorded byte lengths and
  SHA-256 hashes.
- The standalone GResource decoder and serializer round-trip accepted the
  corrected Arc, WhiteSur, and Rosé Pine bundles. Final resource CSS scans
  reported zero missing local references and zero invalid SVG payloads in all
  corrected compiled bundles.
- Final selected source scans reported zero missing references for ChromeOS,
  Matcha, Qogir, and Vimix after applying each archive's actual asset mapping.
- The standalone catalog scan covered all 50 variants, 11,198 materialized files, 222 CSS stylesheets, and 14,319 CSS URLs. It found zero missing local references and zero XML parse errors in materialized SVG assets.
- A separate XML parse of all 70 pinned Qt SVG files completed with zero XML errors.
- The rebuilt Arc Debian control `md5sums` contains 672 entries; all entries match the rebuilt data archive.
- The pure generation command
  `make --no-print-directory PYTHON='python3 -I' build` completed with
  `built 2040 payload files`.
- A standard-library payload comparison found 2,040 manifest entries and 2,040
  payload members, with zero manifest mismatches and zero source-byte
  mismatches.

The generated products are:

| Product | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.tar.gz` | 60,972,966 | `064c115e9c4b83de85ba2ef057926e345dac053736df695ceac7c17cdfbca1f4` |
| `d-i/forky/payload.manifest` | 252,094 | `75567a97ea48fe3da32c931402ba53e73ba4bc9a389d9b6d757128a1b26400db` |
| `d-i/forky/preseed.cfg` | 96,407 | `8d4e3258c31bd862ad4e246b4afce00a39fea5aa7eab23d043522451c8cea59c` |

### Corrected archive hashes

| Archive | SHA-256 |
| --- | --- |
| `ChromeOS-b80a8b77f189.tar.gz` | `2ef1f94611d594597a1100cb5ee755b2be88a66e64b756fa53f5b1c94d6c5c38` |
| `Matcha-4f18ea92d53d.tar.gz` | `0b217012cbc07e38d0bd1112544ebc2a40a99f6dca08e41a45f9d0484fb7d617` |
| `Qogir-619f33047877.tar.gz` | `8fca09d0964b7385b6bfbb73551c98d750117c5a99a83204345ff80decd8e4c8` |
| `Vimix-c11aca86854d.tar.gz` | `6f368bfe94ea57e246b826fdb10b7a87290f6474e39005b57694407f14287f02` |
| `WhiteSur-Light.tar.xz` | `69d9025f63ff1a7115cc329788cf39784738effd35c3fefc8d5c750df56caea6` |
| `WhiteSur-Dark.tar.xz` | `97a0c008f4a83c448df73e4f7386383d2f13548856734dafcc6626a328a4d453` |
| `arc-theme_20221218-3_all.deb` | `75b47948387d58b4735d481229cc00fff3786fa0405ad492c3538b2678b222fe` |
| `rose-pine-gtk3.tar.gz` | `758f1872c700e45339d8aafc8c66d951cd0bd63e1c206f2c2159f735a781d14b` |

## Verification limits

The repository explicitly prohibits running the test suite, test discovery,
native syntax checkers, Gio loaders, installer helpers, host services, package
managers, or any disposable environment. The fixture sources remain
unexecuted. Static archive consistency and pure payload serialization do not
prove live Debian Installer completion, GTK/Qt rendering, boot behavior,
policy loading, or application launches. No target image or installed package
versions were available as live evidence.

