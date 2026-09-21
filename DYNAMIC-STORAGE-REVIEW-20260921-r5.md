# R5: RAM- and disk-derived storage sizing

Base: `debian-preseed-de-refactored-20260921-r4.tar.gz`. Date: 2026-09-21.

## Delivered behavior

The requested fixed-size override settings and their bypass branches have been removed. Both raw partitions now use the existing RAM/disk sizing controls. No configuration key, runtime environment variable, target helper, package dependency, vendor build, or vendor-source patch was added.

| Profile family | Reference usable RAM | Logical ZRAM result | Fallback swap target |
| --- | ---: | ---: | ---: |
| `btrfs-de-flex`, `btrfs-de-flex-duo` | 7,489 MiB, also covering approximately 7.4 GiB | 16 GiB | 6 GiB |
| Other Btrfs-named profiles | 47,935 MiB, approximately 46.8 GiB | 28 GiB | 8 GiB |
| All five F2FS-named profiles | Nominal 4 GiB; Chromebook fixture also uses 3,424 MiB usable RAM | 6 GiB | 2 GiB |


Logical ZRAM is calculated from detected RAM when the existing setup service initializes it. Disk-backed partition sizes are calculated from detected RAM and disk geometry during installation. This release does not attempt live partition resizing, and changing an already-installed host's profile cannot enlarge its existing partitions.

## Existing controls, no parallel sizing mechanism

| Existing setting | Flex | Other Btrfs | F2FS |
| --- | ---: | ---: | ---: |
| `ZRAM_PCT` | 220 | 60 | 180 |
| `ZRAM_MAX_MIB` | 16384 | 28672 | 6144 |
| `SIZE_PART_SWAP_MAX_MIB` | 6144 | 8192 | 2048 |
| `SIZE_PART_SWAP_RAM_DIVISOR` | 1 | 4 | 1 |
| `SIZE_PART_SWAP_LAYOUT_DIVISOR` | 12 | 12 | 8 |
| `SIZE_PART_RAW_ZRAM_MAX_MB` | 17180 | 30065 | 6443 |
| `SIZE_PART_RAW_ZRAM_DISK_DIVISOR` | 16 | 8 | 4 |
| `SIZE_PART_RAW_ZRAM_BUDGET_DIVISOR` | 4 | 4 | 4 |

Logical capacity is the detected RAM percentage, rounded up in MiB, then clamped between the existing per-profile minimum and maximum. Flex's former minimum equal to its 16 GiB maximum is returned to 4 GiB so smaller-RAM fixtures actually scale down. Other Btrfs minima remain 2 or 4 GiB as already configured. F2FS retains a 2 GiB logical minimum. The 180% F2FS multiplier reaches the requested ceiling even with the original Chromebook profile's firmware-reduced usable-RAM figure; it does not presume all nominal 4 GiB is available to Linux.

Fallback swap is bounded by the RAM/divisor calculation, existing minimum/maximum controls, and the available-layout/divisor cap. Available disk capacity is measured in bytes, converted down to decimal MB, and reduced by each measured preserved partition rounded up to MB, plus the existing safety margin. Swap calculations use MiB and convert exactly once to decimal MB at the recipe boundary. Contradictory bounds and insufficient minimum layouts fail closed.

Raw writeback backing is separate from logical ZRAM and fallback swap. It scales with available Debian disk space and is capped at the table's maximum. Its ceiling is approximately 16, 28, or 6 GiB; no backing partition receives an unbounded remainder. On a small dual-boot Chromebook its backing can be smaller than 6 GiB while logical ZRAM is still 6 GiB. That is intentional disk-budget scaling, not a claim that all three capacities are interchangeable.

For example, the 32 decimal GB Chromebook fixture with 10 GiB preserved has a 5,251 MB backing plan, 6,144 MiB logical ZRAM, and 2,048 MiB fallback. The full-disk 32 decimal GB fixture has a 6,443 MB backing plan and the same logical/fallback targets. The backing-aware writeback budget remains bounded by the measured backing device and its existing reserve.

## Partitioning and memory safeguards

The dual-boot fixtures cover both 380 GiB total with 100 GiB preserved and 480 GiB total with 100 GiB preserved. There is no hardcoded 100 GiB reservation: the real preserved-partition measurements determine the budget. The first case has 299,622 decimal MB available after its profile margin. Both flex and main reach their requested targets in either case.

A reused EFI partition is neither shrunk nor charged twice to the F2FS budget, including the low-space shrink path. Both encrypted and unencrypted root recipes have exactly one growable partition: root. The raw backing and fallback recipe bounds are set to their already-computed sizes. Root's priority has a positive growth weight, so the remaining allocation does not depend on an all-zero priority sum.

Before publishing target storage configuration, both raw devices must exist as block devices and their measured byte sizes must match the computed decimal-MB plans within the existing 2 MiB alignment tolerance. Oversized and undersized deviations outside that tolerance are rejected; a backing partition silently absorbing the rest of the disk cannot pass this check. The existing raw-device validator was generalized rather than adding another helper or another configuration variable.

The actual Perl config validator previously rejected logical RAM percentages above 100. Only the logical-capacity field now accepts a bounded 1..300 integer. Physical compressed-data and writeback percentage fields retain their 0..100 validation. The actual rendered policies for all 13 profiles are passed through that validator in the tests.

The existing compressed-data memory-limit formula is unchanged: it applies the existing percentage to the smaller of logical capacity and physical RAM. At the tested hardware values, its limits remain 4,494 MiB for flex, 14,336 MiB for main, and 1,712 MiB for the Chromebook with 3,424 MiB usable RAM. This does not reserve 16, 28, or 6 GiB of physical memory and does not guarantee arbitrary incompressible data will fit. Existing compression algorithms, writeback controls, encryption, swap priorities (300 for ZRAM and 10 for fallback), and service ordering are unchanged.

## Cleanup and scope

Production edits are limited to 12 profile files, the three shared runtime sizing/recipe shell files, the existing late storage helper, and the Perl config validator: 17 files. The obsolete R3 fixed-policy regression file and its old production patch were removed. Their replacement exercises dynamic RAM/disk behavior instead of freezing a particular geometry. The historical R3 review is marked superseded; the host README and current profile-provenance hashes are updated while historical source/destination hashes are retained. The workload-prefix integrity test still validates unrelated profile policy through narrowly specified reversions; it is not bypassed.

All source files under `d-i/forky/hooks/target` other than `Zram/Config/Validator.pm` are byte-identical to R4. In particular, the 18x18 logical-pixel Waybar configuration, artwork, menus, hover styles, power flows, output watcher, atomic-KMS behavior, AppArmor policies, and private Xwayland implementation are untouched. Neither removed icon-staging nor Foot-supervisor helper is reintroduced. All 3,468 files from the original user ZIP remain present.

## Completed validation

| Check | Result |
| --- | --- |
| Latest outcomes from isolated test modules | 2,270 passed, 49 skipped, 0 failed |
| Unique test cases / runnable modules | 2,319 / 98 |
| New storage tests | 22 passed; many parameterized hardware, profile, encryption and rejection cases |
| Rebuilt payload | 1,405 files; current snapshot and pin checks pass |
| Preseed checks | 59 files and all four command-value debconf round trips pass |
| Shell parser checks | 285 files; 581 checks pass |
| AppArmor | 37 top-level policies compile offline; no policy loaded |
| Scope and cleanup | No new production assignment names or profile keys; retired override tokens absent from the repository and unpacked payload |

The storage tests execute real shell sizing functions and recipe emitters under dash, plus BusyBox parity checks; only hardware reads are injected. The generated INI uses the production scalar renderer and real Perl validator. The exact existing Perl dynamic-sizing method is evaluated with injected hardware/config access, not replaced with a Python sizing approximation. Coverage includes smaller RAM/disk results, decimal/binary conversions, preserved partitions, both nominal 32 GB and 32 GiB Chromebook disks, overflow paths, raw-device measurements, and invalid configuration.

Intermediate failures are retained in `validation/dynamic-storage-20260921-r5/initial-unsuccessful-tests.log`. Current-provenance checks were refreshed and the snapshot was rebuilt after documentation changed. Timing-sensitive unchanged modules were rerun serially without relaxing their assertions or internal deadlines. The module harness alone was raised from 180 to 420 seconds for those reruns. Final counts use the latest completed result once per module, not repeated attempts. One additional discovered module contains test support and no tests; it is not counted as a pass.

The offline audit reports 485 syntax/format passes, 180 lexical unit-structure passes, 157 dependency-blocked checks, 509 inventory-only records, and two templates needing rendering. Blocked, inventory-only, structure-only and template checks are not claimed as passing runtime tests.

No physical installer boot, real partition creation/resizing, target ZRAM setup, pressure workload, swap activation, systemd 261.2 lifecycle, or kernel-enforced AppArmor run was performed. Missing Moo/MooX and other optional validation dependencies remain explicitly recorded. A successful offline suite is not a hardware acceptance claim.

## Deployment and acceptance

Publish the complete extracted repository atomically, keeping `d-i/forky/preseed.cfg`, `payload.manifest`, and `payload.tar.gz` from this build together. These changes govern new installations; they are not a destructive repartitioning command for an installed machine.

For a target acceptance run, inspect the selected profile and installer-computed sizes before committing partitioning, verify preserved dual-boot partition boundaries, and then inspect the installed ZRAM disksize/memory limit, both raw-device capacities, active swap priorities, and storage-service journal. Verify the Chromebook on its actual measured eMMC capacity rather than relying solely on its marketed size. Retain the working R4 deployment separately for rollback; do not combine revisions.

## Primary references

Linux kernel ZRAM documentation distinguishes logical disksize, compressed-memory limit and backing storage, and documents writeback constraints and statistics:
https://www.kernel.org/doc/html/latest/admin-guide/blockdev/zram.html

Debian's official partman-auto recipe documentation specifies decimal MB and the minimum/priority/maximum allocation rules and alignment constraints:
https://sources.debian.org/src/debian-installer/stable/doc/devel/partman-auto-recipe.txt/
