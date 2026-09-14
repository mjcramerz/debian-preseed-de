# Validation record index

The authoritative final records are `final-summary.json`, `regressions.log`,
`final-related-integrations.log`, `final-full-tests.log`,
`final-baseline-comparison.json` and the final static check logs/JSON.

`source-change-inventory.json`, `implementation.patch`,
`unchanged-integration-inventory.json` and `payload-source-verification.json`
document scope and deployment consistency.

`pre-fix-reproduction.log`, `baseline-regression-proof.log` and
`pre-publication-fix-proof.log` are intentionally negative reproduction evidence.
`full-validation/` records the initial 300-second wrapper timeout honestly.
`full-tests-complete.log` is the completed initial-patch run, before the four
follow-on publication/umask tests. It is superseded by `final-full-tests.log`.
Other non-final logs are preserved investigation history. No production timeout
or unrelated test was changed. See the two dated documents under `docs/`.
