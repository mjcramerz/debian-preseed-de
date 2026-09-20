# Current validation evidence: 20 September 2026

`summary.json` is the current corrected-tree result. All seven stages completed
with zero exit status. The repository suite ran 1802 tests (37 skipped), and
the tooling suite ran 179 tests (0 skipped). No suite reported failures
or errors. Skips and audit-blocked categories are not counted as passing checks.

* `tests.log`, `tools-tests.log`: full unittest outputs.
* `skipped-tests.json`: all actual skipped tests and reasons.
* `shell-check.json`, `shell-check.log`: 581 parser checks, 285 shell files.
* `audit.json`, `audit.log`: per-file static audit and blocked/inventory categories.
* `focused-*.log`: additional focused runs; they overlap the full suites.
* `initial-build.log`, `repeat-build.log`, `publication-integrity.json`: regenerated
  payload, manifest, preseed pins, and byte-identical repeat generation.
* `change-manifest.json`, `scope.patch`: exact comparison against the supplied ZIP;
  the binary payload diff is represented by before/after hashes.
* `source-inventory.sha256`: every release file outside this evidence directory.
  Run `sha256sum -c validation/packaged-native-session-20260920/source-inventory.sha256`
  from the repository root to verify it.
* `baseline/`: the unmodified uploaded tree's independent offline validation.
  Its passing mocks/static tests do not mean the deleted root source build ran.

The delivered outer tarball has a separate checksum and release-verification
report beside the download. Its safe paths, members, modes, full content hashes,
repeat-generation equality and extracted-tree checks are verified there. An
archive cannot contain its own final digest without a circular dependency.

No unattended installer boot, live compositor/thumbnail interaction, wallet
unlock, real target-kernel AppArmor enforcement or hardware acceptance run was
performed. Refer to the change report for deployment and on-host acceptance.
