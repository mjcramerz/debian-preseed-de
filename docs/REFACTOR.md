> Historical report retained from the uploaded repository. For this revision,
> read [REFACTOR-2026-09-06.md](REFACTOR-2026-09-06.md) and [VALIDATION.md](VALIDATION.md).

# Refactor notes: debian-preseed-de

## Boundaries and preserved policy

This tree is self-contained and installs only the desktop role. It has no
cross-repository imports or symlinks. Shared installer and target code is copied
into each repository. Role-only class fragments, metadata, target assets, helper
modules, services, firstboot checks and profiles are retained only where used.
Shared administrative features are not mistaken for a server role merely because
they involve a daemon: SSH, CrowdSec, hardware support and applicable Podman
configuration remain shared.

Original profile contents are preserved byte for byte. Package fragments and
hardware policy are not intentionally redesigned. Hardware detection selects the
same class policy; source locations are resolved through a four-column mapping.
Source-name variants preserve colliding installed filenames. Desktop base-stage
versus final-stage dotfiles and listchanges configuration retain separate source
copies where the old versions differed.

The server repository defaults to `prod;server;standard;static;ssh` instead of the
original desktop defaults; it does not select GitLab Runner automatically. The
desktop repository retains its original default class list. Role mismatch and
unknown classes are errors, not a fallback to the other repository.

## Main path migrations

| Previous source scope | New source scope |
| --- | --- |
| `hooks/shared/` installer subtrees | `hooks/installer/` |
| `hooks/shared/late_command.sh` | `hooks/installer/late_command.sh` |
| all retained `*/target/` payload trees | `hooks/target/` |
| role late-command implementation | `scripts/late/desktop.sh` |
| `hosts/shared/` | `hosts/installer/` |
| named `hosts/profiles/override/*.env` | `hosts/profiles/*.env` |
| family baseline `hosts/profiles/<family>/desktop.env` | `hosts/profiles/<family>-desktop.env` |

`migration-map.json` records every input file as retained (with original and
current destination hashes) or excluded from this repository. Excluded means
out-of-scope or superseded documentation; it does not mean the file belongs in
neither output. `target-layout.md` retains the original role-specific operational
notes with relocated paths.

## Fetch and preflight flow

1. Resolve exactly one local or HTTP(S) preseed source. Follow normal HTTP
   redirects and preserve the final file's complete parent path.
2. Verify and load the canonical transport. Fetch and verify the pinned manifest
   and whole regular-file payload; reject invalid members before extraction.
3. Validate installer shell syntax and class/profile constraints, compose the
   selected environment and stage common/fragment includes as local absolute URIs.
4. Write `preflight.ok` only after repository preflight succeeds. Existing phase
   implementations continue through shared fetch API adapters using the snapshot.

This consolidates repository I/O without changing the independent third-party
application installers' download policy. One resolver GET of the initial preseed
is intentional; subsequent metadata probes and copies share cached bytes. A
missing payload asset is fatal rather than a late network fallback. A source
snapshot is a publishing unit: editing runtime files requires rebuilding it.

Preflight cannot predict future mirror outages, package transitions, disk I/O
failure, firmware behavior, external enrollment success or target service runtime
semantics. Those remain integration/acceptance tests, not claims made by a static
audit or loopback bootstrap run.

## Installer path defects caught during refactor

Literal repository joins are now validated at build time. This caught a duplicated
`generators/` component in APT setup paths after relocation. Hardware-map sources,
class fragments and declared late helpers must exist. All referenced repository
DIR variables must be declared. Old physical shared/role/hardware/profile-family
paths are forbidden by regression tests in active installer code.

The source profiles still contain the original deployment-specific policies and
values. Review them, account settings, class constraints and disk choices before
booting an unattended installer.
