# Pre-implementation review: Btrfs options and locale boundary

Baseline: debian-preseed-de-gpg-recipient-fixed.tar.gz
SHA-256: 727a50673f808e0062ac760772ba8cbb31fdf50de58eaa8fdf1b47ffcbcc51ac
Date: 2026-09-15

The baseline build check passes. It contains 1,837 regular files and 467 directories.

## Source findings

1. `hosts/installer/layout-btrfs.env` has three canonical format option values
   (ROOT, HOME, OPT). Each supplies `--features extref,skinny-metadata,no-holes`
   followed by deprecated `--runtime-features free-space-tree`. The shared
   storage hook passes these values to mkfs.btrfs. No other production source
   invokes the deprecated option. All Btrfs and VM compositions use this policy.
2. `scripts/common/target.sh:target_exec` already has a partial previous fix:
   the in-target branch removes LOCPATH and LANGUAGE and exports LC_ALL=C;
   the target env sets LANG/LC_ALL=C.UTF-8. However inherited LANG and individual
   LC_* categories remain in the bridge, categories persist into the target,
   and the chroot executable itself runs before its clean target environment.
   Therefore the earlier claim of a complete boundary repair was too broad.
3. Debian's chroot-setup.sh sets LANG from IT_LANG_OVERRIDE or installer debconf.
   The managed call must set IT_LANG_OVERRIDE=C for the bridge and remove this
   installer-only override from the target environment. An env -i change on
   the in-target path would discard the passthrough Debconf environment and
   proxy setup and is not appropriate.

## Planned narrow changes

- Move free-space-tree into the existing --features list, retaining checksums,
  data/metadata profiles, labels, nodesize, mount options and formatting gates.
- Make target_exec's environment changes local to a subshell. Clear LANGUAGE,
  all twelve glibc LC_* categories and locale/catalog/conversion search paths;
  set LANG/LC_ALL=C before either bridge. Set IT_LANG_OVERRIDE=C for in-target.
  Explicitly remove category/path variables inside the target env too, retain
  target LANG/LC_ALL=C.UTF-8 and allow intentional command-level env overrides.
- Preserve Debconf transport, proxy behavior, arguments, stdin, exit status,
  custom target paths and caller environment. Add executable regression tests,
  rebuild generated payload/pins, and verify a fresh extraction of the tarball.

## References checked before implementation

- Btrfs upstream mkfs.btrfs documentation: --runtime-features was merged into
  --features in 6.3; free-space-tree is a supported filesystem feature.
  https://btrfs.readthedocs.io/en/stable/mkfs.btrfs.html
- Debian installer-utils 1.155 in-target and chroot-setup.sh, including
  passthrough descriptors and LANG=${IT_LANG_OVERRIDE:-...}:
  https://sources.debian.org/src/debian-installer-utils/1.155/in-target
  https://sources.debian.org/src/debian-installer-utils/1.155/chroot-setup.sh
- C is the portable bridge locale:
  https://www.gnu.org/software/libc/manual/html_node/Standard-Locales.html

No security policy, service lifecycle, private credential, hardware tuning,
partition size or installed desktop locale change is planned. No compilation.
