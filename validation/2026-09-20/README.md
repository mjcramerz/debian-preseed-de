# Release verification - 2026-09-20

**Historical snapshot of the preceding delivery.** The wlsunset follow-up
supersedes its indicator implementation. Current results are in
`../2026-09-20-wlsunset/`; the original results below are retained unchanged.

This directory contains actual results for this revision, not a claim of booted
Forky/systemd 261.2 acceptance. The full suites ran on a frozen release candidate.
A final review then removed the added duplicate Labwc suspend binding, retaining
logind as the sole power/suspend handler. The payload was rebuilt, all 26 new
tests and 42 directly affected integration/rendering tests were rerun and passed,
and the final build/pin check passed. See `final-hotkey-review.json` for the exact
sequence and final runtime-product hashes. The full suite was not rerun after
that XML/test-only review. `first-complete-run/` retains the earlier pre-candidate
run; its corrected provenance/comment checks and concurrent-build checksum
mismatch are not the release-candidate result.

## Full candidate suite and final scoped results

- tests: 1852 run, 1792 passed, 13 failed, 47 skipped.
- tools-tests: 179 run, 178 passed, 1 failed, 0 skipped.
- All 26 new regression tests and the 42 post-review integration/rendering tests
  passed on the final source. New coverage includes real private D-Bus calls,
  real inotify with a stub wallpaper backend, controlled child-process teardown,
  safe state-file handling, exact menu identities/geometry, and PAM staging.
- Browser-artifact, payload/pin, preseed and shell checks passed. Shell validation
  covers 286 files with 583 parser checks; this is syntax checking, not execution
  of every branch.
- All nine changed AppArmor policy files compile with AppArmor parser 4.1.0 in
  offline mode. The kernel interface/cache diagnostic is expected in this
  container; no policy was loaded into the host kernel.
- The original 13 protected private-Xwayland files and every non-ChatGPT Electron
  launch/intel/nvidia argument list compare unchanged.
- All 3,165 original files remain present; 3,118 retain byte-identical contents.
  All original assignments in the 13 host profiles remain unchanged; only the
  requested geometry variables and Gammastep boolean were appended.

## Existing failures and skipped coverage

The full suite is **not green**. Every remaining failure was reproduced against
an independently extracted, untouched baseline:

- Three IOCost-related checks expect `btrfs-de-flex-duo` to enable calibration;
  the supplied profile explicitly sets it to false. Its value is preserved.
- Ten workspace-verifier fixture checks stop at the existing native-switcher
  contract mismatch before reaching their individual assertions. The relevant
  production verifier and those fixture tests are unchanged.
- One older panel test expects 58 click commands, while the supplied configuration
  contains 56. Neither the panel template nor this historical expectation was
  changed for these objectives.

See `unchanged-baseline-reproduction.log` for the direct reproduction. Tests were
not disabled, marked expected-failure or rewritten to conceal these mismatches.
The 47 skips include missing Perl/Moo and other environment dependencies; a skip
is not a pass. The wider source audit also reports 156 dependency-blocked items,
11 tool-blocked items and two unrendered templates. Inventory/lexical checks do
not count as runtime coverage.

## Deployment gates

The KMS atomic-commit error has **not** been conclusively fixed or reproduced in
this container. Physical ThinkPad keys, real wallpaper rendering, GeoClue location
acquisition, the requested Thunar decoration appearance, and all applications
under enforced AppArmor still require the target acceptance checklist in
`docs/repairs-20260920/TARGET-ACCEPTANCE.md`.

The AppArmor review covers all 10,423 ALLOWED/DENIED records in the supplied log,
including intended denials. It is not proof that unexercised application features
will work under enforcement. No unsupported claim of zero remaining target
failures is made.
