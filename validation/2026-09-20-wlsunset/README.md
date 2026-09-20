# Final follow-up validation - 20 September 2026

This directory describes the wlsunset/Waybar follow-up. Older validation directories
are retained historical evidence; they do not describe the current payload.

## Final results

| Check | Result |
|---|---|
| New wlsunset tests | 41 passed, no skips |
| Session repair and retirement tests | 41 passed, no skips |
| Repository integrity checks | 10 passed, no skips |
| Full installer suite | 1897 run; 1837 passed; 13 inherited failures; 47 skipped |
| Full tools suite | 179 run; 178 passed; 1 inherited failure |
| Combined full suites | 2076 run; 2015 passed; 14 inherited failures; 0 errors; 47 skipped |
| Changed AppArmor policy files | 2 compiled offline |
| Equivalent transient-unit structure | Offline systemd verification passed |
| Shell syntax/checks | Passed |
| Preseed round-trip checks | 59 files passed |
| Rebuilt payload/manifest/preseed pin check | Passed; 1,388 payload files |
| Protected private-Xwayland files | 13 byte-identical to the supplied previous release |
| Managed application/browser argument sources | 24 byte-identical to the supplied previous release |
| Host profile assignment scope | All 13 checked; only old indicator key replaced by 10 WLSUNSET settings |

The full suite is **not green**. Its fourteen failed test names AND final assertion
messages match the previous release: three IOCost-related expectations, ten
workspace-verifier fixtures, and one panel-command count expectation. There are
no new failed tests. No unrelated test was disabled or rewritten to hide these
failures. The original-input reproduction evidence from the previous release is
retained at `validation/2026-09-20/unchanged-baseline-reproduction.log`.

There are 45 newly added test methods (41 wlsunset, four retirement-edge cases).
The 41-test session-repair suite includes existing tests as well as the retirement
additions. Scoped results overlap with the full suite; do not add their totals.

The initial candidate's full output is retained under `initial-candidate/`.
Its additional 26 profile-provenance failures were corrected by updating current
checksums, preserving historical source/migration checksums. The final full run
started after the final gamma-FD permissions/peer review and payload rebuild.
Runtime and test source files were not edited during or after that final run.

## Evidence and limits

`final-validation.json` records counts, exact inherited failures and limitations.
`scope-preservation.json` records protected file hashes and per-profile comparisons.
The full logs, AppArmor parser output and equivalent-unit fixture are retained here.

This is Debian 13/systemd 257.9 offline/fixture validation, not the requested
Forky/systemd 261.2 hardware desktop. Real Unix peer credentials, flock and SCM_RIGHTS
transfer were exercised. The latter verifies that an O_RDWR descriptor remains
O_RDWR when received; it is not an AppArmor kernel enforcement test. No AppArmor
policy was loaded, and no native wlsunset process or graphical compositor was run.
Live gamma adjustment, monitor acceptance, suspend/DPMS/output hotplug, logout,
Waybar visual hover and enforced-AppArmor operation remain target acceptance checks.
See `docs/repairs-20260920/TARGET-ACCEPTANCE.md`.
