# Installer no-stat fix evidence

Release review: `../../docs/INSTALLER-NO-STAT-FIX-20260914.md`.
Validation interpretation: `../../docs/INSTALLER-NO-STAT-VALIDATION-20260914.md`.

`final-results.json` records both full-suite runs and baseline comparisons.
The initial driver `summary.json` remains unchanged and correctly reports failure.
`pre-fix-no-stat.log` is deliberately failing evidence from the previous source,
not a failure of the corrected allocator. Current focused results are in
`clone-staging-tests.log`.

`minimal-initrd-rootfs-check.py` is a disposable rootfs reproduction, not a boot
installer or a deployment script. Run from a disposable root-capable environment.
The original source modes were preserved, as recorded in
`archive-metadata-preservation.json` and `source-change-inventory.json`.

No credentials or actual private deployment data are present in these fixtures.
