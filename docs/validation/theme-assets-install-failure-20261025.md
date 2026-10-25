# Desktop theme and wallpaper release archives — 2026-10-25

## Scope

The installer no longer carries the desktop theme source tree or the wallpaper
archive in the Debian preseed payload. Both archives are downloaded during the
desktop late installation phase from the pinned GitHub release.

The unrelated edits in `AGENTS.override.md`, `tools/inventory.py`,
`tools/inventory_apt.py`, and `tools/tests/test_download_inventory.py` were
preserved. The inventory utilities were not executed or integrated into the
installer.

## Pinned release inputs

Every active file under `d-i/forky/hosts/profiles/` carries the same release
tag, URL, SHA-256, and transfer-size limit.

| Input | Tag | URL | SHA-256 |
| --- | --- | --- | --- |
| Desktop themes | `themes-v0.0.1` | `https://github.com/mjcramerz/themes/releases/download/themes-v0.0.1/desktop-themes.tar.gz` | `3954a7573afeb6f47a2bb2ee22c690a84bd9d7ea538aa2ad8909702516105b03` |
| Wallpapers | `themes-v0.0.1` | `https://github.com/mjcramerz/themes/releases/download/themes-v0.0.1/wallpapers.tar.gz` | `62dd913c8c68d7bfaf472c103260c0eb4dbf1226d218083033a53fb55b8db890` |

The installer binds each URL to its profile tag and expected filename, downloads
over the existing HTTPS external-source transport, checks the downloaded file's
SHA-256 against the profile value, and enforces the profile transfer-size limit.

## Installation wiring

### Desktop themes

`scripts/desktop/components/release-assets.sh` contains the shared pinned-release
download helper. `appearance.sh` downloads `desktop-themes.tar.gz` into the
private installer workspace, verifies the tarball hash, and extracts it into the
target's private `.installer-themes` staging directory before invoking
`labwc-appearance-themes --install`.

The outer release tarball is not compared with the former checkout tree. The
installer does not inspect its member list, archive metadata, MIME types, or
extracted-file inventory. The extracted release supplies its own
`sources.json`, which remains the input consumed by the existing theme installer.

The old repository-generated `desktop-theme-assets.list` staging path was
removed. Theme cleanup now derives the source paths from the extracted
`sources.json` inventory and no longer requires `.files.list`.

### Wallpapers

`artifacts-identities.sh` downloads `wallpapers.tar.gz` from the pinned release,
checks the profile SHA-256, copies the verified tarball into the target's
temporary installer path, and extracts it into
`/usr/share/backgrounds/desktop`. The temporary archive is removed after
extraction. The existing fallback desktop, lock-screen, and greeter images are
still staged separately, preserving the selected wallpaper paths and defaults.

The wallpaper extraction path does not inspect the archive's member contents;
the profile SHA-256 is the archive integrity check.

The obsolete source variable `LABWC_WALLPAPER_ARCHIVE` and its
`source-archive` schema entry were removed. Verification now checks the fixed
temporary target path `/tmp/installer-desktop-wallpapers.tar.gz` is absent after
extraction.

## Removed checked-in inputs

These paths are no longer present in the checkout or generated payload:

- `d-i/forky/assets/desktop-themes/`
- `d-i/forky/hooks/target/usr/share/backgrounds/desktop/wallpapers.tar.gz`
- `d-i/forky/scripts/desktop/desktop-theme-assets.list`

The release archive hashes observed before removal were:

```text
desktop-themes.tar.gz  3954a7573afeb6f47a2bb2ee22c690a84bd9d7ea538aa2ad8909702516105b03
wallpapers.tar.gz      62dd913c8c68d7bfaf472c103260c0eb4dbf1226d218083033a53fb55b8db890
```

## Static and generation evidence

- The two public release files were downloaded to private `/tmp` inspection
  paths and their SHA-256 values matched the profile pins.
- `make --no-print-directory PYTHON='python3 -I' build` completed with
  `built 1845 payload files`.
- The generated manifest and payload no longer contain
  `assets/desktop-themes/` or the checked-in wallpaper archive.
- The source tree and wallpaper archive paths above are absent.
- The ten active host profiles each contain both release tags, URLs, SHA-256
  values, and maximum-byte values.

Generated products:

| Product | Bytes | SHA-256 |
| --- | ---: | --- |
| `d-i/forky/payload.tar.gz` | 11,291,713 | `e545e9c00de7e16df910befbe6e0436972403ccdf502cc5728e5a295250fd690` |
| `d-i/forky/payload.manifest` | 227,459 | `2c59751b6e21211643cd3ba4962569c2753e9bd5a717d9f9a19857b2d8ac75b8` |
| `d-i/forky/preseed.cfg` | 96,407 | `931b1a2f902c4c8b6e0050f3358fd57771f40458146d1b7c813b3235d01f59d6` |

## Verification limits

Repository policy prohibits running the test suite, test discovery, native
syntax checkers, installer helpers, Gio loaders, package managers, host
services, or disposable environments. The fixture sources remain unexecuted.
Pure payload serialization and static source inspection do not prove a live
Debian Installer run, remote download completion in the installer image,
archive extraction behavior on the target, GTK/Qt rendering, or desktop startup.
