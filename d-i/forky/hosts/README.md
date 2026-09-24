# Host environments

Every deployable profile is directly in `profiles/`. Named profile classes map
to `profiles/<class-name>.env`; the internal logical identifier is
`override-<class-name>`. Removed class names and duplicate desktop profiles are
not aliases and are no longer supported.

| Disk family | Default | Hardware choices | Preserving other installed systems |
| --- | --- | --- | --- |
| NVMe / Btrfs | `btrfs-de` | `btrfs-de-p15s`, `btrfs-de-flex` | Append `-duo` to any of these three names |
| eMMC / F2FS | `f2fs-de-x360` | `f2fs-de-hp14` | Append `-duo` to either name |

The `-duo` suffix denotes a multi-OS profile, not a limit of two operating systems.
These profile classes require `addon/dualboot` (the short class token is
`dualboot`). Supply the existing `dualboot_efi=<slot>` and
`dualboot_debian=<first-Debian-slot>` parameters. The installer preserves the
existing slots before that first Debian slot and reuses the explicitly selected
ESP; it does not discover or relocate arbitrary interleaved operating systems.
Never guess these slot numbers. A duo class without the preservation addon is
rejected before partitioning rather than silently becoming a whole-disk install.

## Composition order

```text
profiles/<selected>.env
installer/identity.env
installer/runtime.env
installer/layout.env
installer/btrfs.env OR installer/f2fs.env
installer/boot.env
```

The VM family uses the Btrfs layout environment. Account configuration is read
separately. With no named profile, the NVMe and eMMC defaults resolve to the
canonical profiles listed above; no duplicate fallback files are required.

Partition sizing uses measured disk capacity and, for multi-OS installs, measured
preserved partitions. Profiles provide preferred sizes and caps, not a claimed
physical drive size. Filesystems shrink to their configured minimums on smaller
media, then grow toward their preferred sizes on larger media; root absorbs the
remaining recipe space. A disk below the minimum layout budget is rejected.

After any profile or environment change, run `python3 -B tools/build.py` from the
repository root and publish the complete result. Treat account and enrollment
configuration as sensitive. Historical review paths have been normalized to the
current names; their old hashes and logs are provenance, not fresh validation.

Virtual storage uses the canonical generic Btrfs environment, with the existing
VM disk candidates and hooks. There is no separate VM host profile.
