# Current R7 validation evidence

`summary.json` contains final suite counts and limitations. `steps.json` records commands and exit codes; the matching logs contain the final rerun after profile-count/provenance and test-fixture corrections. Both final full suites ran serially. The focused logs exercise the 48 added tests and are already included in the full runtime-suite count. Earlier failed development iterations are not relabeled as passing.

`managed-app-audit.json` records all 23 reviewed modules, exact hashes and protected-function/file comparisons against R6. `static-audit.json` distinguishes syntax, structure, dependency-blocked and inventory-only checks. `inventory-checks.json` records the ten profiles/classes, retired-name search, test-module syntax and runtime artifact hashes.

None of these records constitutes a live Forky/systemd 261.2 installation or physical-device/AppArmor enforcement test. See `../../REVIEW-20260921-r7.md` for policy, integration and target acceptance.
