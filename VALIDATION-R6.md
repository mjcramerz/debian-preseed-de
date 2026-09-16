# R6 validation record

> Historical power design/results: superseded by [the current power and resctl-bench revision](POWER-RESCTL-2026-09-16.md). Do not deploy the R6 shutdown-target finalizers described below. The independent I/O policy is unchanged.

Date: 16 September 2026. Working baseline: the full R5 archive. Current design
and deployment boundaries are in `POWER-AND-IO-POLICY-R6.md`.

## Completed checks

| Selected test group | Tests | Outcome |
| --- | ---: | --- |
| New independent I/O and power transaction tests | 15 | passed |
| Existing resource policy | 16 | passed |
| Resource refinements and offline systemd fixtures | 9 | passed |
| Broker stop policy and offline ordering fixtures | 8 | passed |
| Power worker, keyboard and save-preparation | 36 | passed |
| GitOps mirrors | 16 | passed |
| Managed Git/debugsys | 56 | 55 passed, 1 skipped |
| Repository integrity/profile composition | 10 | passed |
| Retained policy/AppArmor structural assertions | 13 | passed |
| **Total** | **179** | **178 passed, 1 skipped; no failures/errors** |

The skip is an existing test requiring unavailable OpenSSH client binaries.
The two slow AppArmor compilation test methods were not rerun; the retained
13 policy assertions include nine AppArmor structural checks. No policy was
loaded into the kernel. Production AppArmor files are unchanged from R5.

`validation/r6/test-summary.json` and adjacent per-group logs record these runs.
The full repository aggregate suite was not run. Historical aggregate failures
and earlier compilation results remain in the older reports; they are not
represented as current successful runs.

## Configuration and lifecycle coverage

All 13 real profiles were staged in all four combinations of the accounting
and weight flags: **52 combinations**, with repeated publication into the same
temporary target. Tests assert the actual content and mode of both manager
files, six enabled weight lines or none, unchanged compositor CPU weight,
WirePlumber placement, no unrendered placeholders, and no stale staging files.
The desktop-only publication test replaces pre-existing incorrect manager
values. Literal weight filtering and strict malformed/missing-flag rejection
are also tested. Dash and BusyBox render maps agree in all four combinations.

Both fixed power action units are staged through the real component publisher.
They have no boot enablement, exactly one force flag in the final executable,
and dependency/ordering barriers for shutdown, unmount and final hooks. The
worker's allowlist, preflight checks, guard/save order, one irreversible
nonblocking submission, and no-retry handling of a lost reply are tested with
mocked subprocess calls. Nothing shuts down the development host.

Systemd parsing and offline graph checks used **257.9-1~deb13u1**, not 261.2.
They include the new fixed targets/finalizers with local standard barriers,
plus retained broker-client ordering and resource fixtures. These are not
booted 261.2 tests or an emulation of every target-specific dependency. Actual
user manager teardown, filesystem operations, broker exit, late executable
availability, and the observed intermittent watchdog delay need acceptance on
an installed host. The implementation deliberately does not promise a fixed
whole-machine shutdown duration.

## Build and source preservation

- **277 shell files / 565 parser checks:** passed.
- **59 preseed files:** passed; all four generated command values survived
  private debconf read-back unchanged.
- **1,336 payload files:** rebuilt; two final independent builds produced
  byte-identical payload, manifest, and preseed artifacts.
- Build freshness check: passed.
- All **2,003 original file paths and original modes** are retained.
- All **13 original profile prefixes** remain byte-for-byte unchanged. New
  resource-policy additions live after those prefixes.
- **182 selected AppArmor/Podman/zram/GitOps files** match R5 byte-for-byte and
  by mode; the exact selected paths are in `validation/r6/preservation.json`.

The publisher rewrites three generated products with mode 0644. Their original
source-archive mode 0600 was restored after building, without changing content
or changing the builder. Installer asset publishers still install configuration
files with their explicit target modes (normally 0644), and user-private files
retain the existing home-copy behavior.

Source-template paths are intentionally not confused with rendered target
files. Examples under `validation/r6/rendered-defaults/` show actual default
render output: both manager files use `DefaultIOAccounting=no`.

## Archive verification

The release process packages the entire tree, then extracts it separately and
compares every regular file's content and mode. Selected tests and build
freshness are run again from that extracted tree. The external
`ARCHIVE-VERIFICATION-R6-20260916.json` records the final archive digest, exact
file count, and the completed extracted-tree results. It is external to avoid
a circular archive hash. The tarball's `.sha256` file is also external.

Use a clean extraction and publish the complete tree, not only edited drop-ins.
No existing installed host is upgraded or rebooted by creating this archive.
