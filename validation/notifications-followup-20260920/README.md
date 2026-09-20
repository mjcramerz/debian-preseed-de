# Current follow-up validation

`final/summary.json` and adjacent logs are the full current repository-validation run. Its runtime-product hashes must match the delivered `d-i/forky/preseed.cfg`, `payload.manifest` and `payload.tar.gz`. The overall result remains nonzero when baseline failures occur; tests are not disabled to obtain a green summary.

`notifications-tests.log` is the new placement/click/icon/style suite, including 104 native GTK layout/font/hover combinations across all 13 desktop profiles. `gtk-session-buttons.json` records the individual measurements from an additional direct probe. `native-tomat-tests.log` covers the retained hardware, Tomat, packaging, menu and AppArmor contracts, with the dedicated-upgrader tests replaced by absence/shared-maintenance checks.

`normal-upgrade-policy.json` records an isolated `apt-config` parse of the unchanged normal policies, including the local-repository origin caveat. It is not a live upgrade dry run.

`scope-audit.json` and `scoped-changes.diff` compare the delivered source with the previous complete archive. This directory is excluded from that comparison to avoid self-reference. `payload-verification.json` independently checks the generated archive/manifest and the absence of retired upgrade assets.

Historical test logs and baseline IOCost reproductions remain in `../tomat-native-menus-20260920/`. They are not claimed as execution evidence for the current revision. See `docs/NOTIFICATIONS-FOLLOWUP-2026-09-20.md` for scope, normal unattended-upgrade policy caveat, and live-host limitations.

The full suite also reports the existing bootstrap fatal-record deadline test. Its unchanged eight-second deadline failed when run alone against both this revision and a fresh extraction of the previous complete archive. `transport-*-recheck.log` preserves both failures. The separate `diagnose-bootstrap-deadline.py` harness changes only its in-memory observation deadline to thirty seconds: both revisions then preserve the fatal record, remain held and do not write the preflight marker. Those diagnostic passes are not relabeled as passing unmodified tests. The timings and source hash are in `bootstrap-deadline-diagnosis.json`.
