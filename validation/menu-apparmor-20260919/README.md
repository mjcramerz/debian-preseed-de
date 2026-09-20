# Desktop menus and AppArmor release qualification

This report continues from `debian-preseed-de-no-stat-fixed.tar.gz`. It records
the actual completed checks for the menu/AppArmor revision. See `report.json`
for exact command lines, exit codes, failure identifiers, changed-file reasons,
coverage and primary documentation. Logs in this directory are command output,
not rewritten success summaries.

## Implemented integration

The graphical Main Menu now exposes the fixed Computer Management route.
Its six groups and 23 action vectors retain existing validators and isolated
workers. Tests walk all 42 maintenance and 21 recovery menu entries without
executing privileged operations. Explicit free-text WAN prompts, strict picker
output, cancellation/error separation, complete catalog validation and child
cleanup are covered. The independent AI fzf picker uses a closed environment.

AppArmor changes are limited to a strict Main Menu transition, read-only terminal
database access for AI fzf, and matching peer-specific TERM permissions for
Fuzzel cleanup. All 35 managed top-level policies compile offline; required
managed include staging and named transition resolution are checked. All 78
AppArmor payload assets are present and byte-identical to their source.

## Results and baseline qualification

Build, build check, shell checks, focused menu/security/hardware checks, inherited
policy checks, standalone hardware checker and audit complete successfully.
The full test suite and the tests stage of `make validate` retain exactly the
untouched input's six failures and two errors; no new failing identifier appears.
The precise baseline causes and all skips are recorded rather than suppressed.
An earlier overlapping validation run also observed one extra HTTP-bootstrap
request. That successful-bootstrap request-count assertion was not weakened;
its initial output, isolated repeats and the final serial run are retained.
A successful offline parser or unit check is not a claim of live kernel policy
enforcement or a booted unattended installation.

All 13 host profiles remain byte-for-byte unchanged. The external metadata
executable dependency guard still passes; prior BusyBox-compatible installer
corrections, fonts, numeric module policies, Intel policy and IOCost are retained.
Normal payload/preseed products were rebuilt. Old validation records remain
historical evidence and must not be mistaken for this release's results.

## Packaging checks

The complete source archive is verified separately after this report is written:
safe members, exact source bytes/modes, retained input files, generated artifacts,
fresh extraction and repeatable packaging. The archive SHA-256 and those final
checks are supplied beside the archive, avoiding a self-referential checksum.
