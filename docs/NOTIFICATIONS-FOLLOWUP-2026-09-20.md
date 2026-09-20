# Notifications placement and removal of the dedicated Tomat upgrade path

## Scope

This is a narrowly scoped follow-up to the complete `debian-preseed-de-refactored-2026-09-20.tar.gz` release. The new tarball contains the complete repository, not a patch. Runtime changes are limited to removing the Tomat-specific upgrade transaction and revising the Notifications button's position, mouse bindings, tooltip and shared sizing/hover rules. Regression tests, installer verification and affected documentation are updated with those contracts.

Tomat's validated upstream download adapter, local repository publisher, initial installation, foreground transient user service, hooks, AppArmor policy and configuration are retained. Hardware policies, Xwayland implementation, Zoom/Discord restrictions, Crystal Dock and unrelated applications are unchanged. No upstream source patches, new source compilations or replacement notification daemon are introduced.

## Removed upgrade implementation

The following target assets are deleted, together with their installer staging and verification requirements:

- `etc/systemd/system/local-apt-tomat-upgrade.service`
- `etc/systemd/system/local-apt-refresh.service.d/70-tomat-upgrade.conf`
- `etc/apt/tomat-unattended.conf`
- `usr/local/share/software/tomat/apt.conf`

Their now-empty parent directories are removed where applicable. They are absent from the regenerated payload and manifest. No replacement Tomat-specific upgrade service, timer, success hook or private APT configuration is added.

The existing `local-apt-refresh.service` and weekly timer remain byte-for-byte unchanged. They still discover, validate and publish local packages, including Tomat, without initiating an install transaction. The normal `20auto-upgrades` and `52unattended-upgrades` policies are also byte-for-byte unchanged.

### Existing normal-policy caveat

The checked-in `52unattended-upgrades` approves named remote repository sites but does not include the managed `file:/var/lib/software/repo` source or its `Managed External Software` release origin. Publishing Tomat to that source therefore does not, by itself, make a Tomat upgrade eligible for normal unattended installation. An installed host may already have an additional administrator-managed policy allowing it. This revision intentionally does not broaden the global policy or create another Tomat exception.

On an installed host, `apt-cache policy tomat` and `sudo unattended-upgrade --dry-run --debug` expose the candidate and normal-policy decision. No live APT upgrade was run while preparing this archive.

## Notifications button

Both internal and external Waybar compositions now end with:

```text
... | Tray | System controls | Notifications | Lock | Power
```

Notifications is an always-visible top-level module, not a member hidden inside the System controls drawer. It appears exactly once and is immediately before Lock.

| Mouse action | Behavior |
| --- | --- |
| Left click | Open Waybar's native GTK menu |
| Middle click | Toggle Mako's do-not-disturb mode |
| Right click | Open the existing native notification center |

The existing menu offers DND, Clear notifications, and Open notification center. `menu: "on-click"` has no competing `on-click` command or click-release command. Menu item IDs and actions remain matched in both bars; callbacks preserve the existing session-bound transient-service confinement.

The status helper keeps the normal bell and DND bell-with-slash icons, and its tooltip now describes the actual mouse bindings. The Notifications button shares font sizing, weight, minimum width, padding, margins and border geometry with Lock and Power. The old narrower notification-specific rule is removed. Internal output sizing continues to come from each profile's existing session-button variables; external output sizing remains the existing 28-pixel content minimum with 8-pixel horizontal padding. Lock and Power retain their colors and geometry.

The notification hover background is the existing palette's warm gold `#ecb860`, with a dark foreground and gold border/shadow. The rule also overrides muted DND foreground styling during hover, without changing dimensions. Other buttons' hover colors are unchanged.

The notification center's existing semantics are unchanged: Clear dismisses active notifications; it does not claim to purge Mako's saved history.

## Validation and delivery

The current validation records are under `validation/notifications-followup-20260920/`. The previous `validation/tomat-native-menus-20260920/` records and original scoped diff are retained as historical evidence, not presented as tests of this follow-up. A scope audit compares this revision against the previous complete archive.

The new regression tests invoke the real shell functions that compose both bars, exercise status output for normal/DND states, and test all 13 desktop profiles. A standard-library `ctypes` probe loads the rendered CSS in installed GTK 3 under Xvfb and measures labels with Waybar's CSS names/classes. It checks actual button dimensions, font sizing, padding, margins and borders in 104 combinations: 13 profiles, two output layouts, two notification states, and normal/hover states. All three buttons must match in every case, and hover must resolve to the requested gold in both notification states.

This GTK measurement is not a claim that a live Waybar/labwc desktop, Mako bus, Forky installer, physical machine or enforcing AppArmor session was exercised. Existing dependency skips and baseline failures remain explicitly reported in the final validation summary.

Extract into a fresh empty directory rather than overlaying an older checkout: archive extraction cannot delete retired files left in an existing directory. Publish the regenerated `preseed.cfg`, `payload.manifest` and `payload.tar.gz` together with the complete repository. This installer-source archive is not a hot migration tool for an already-installed host: replacing the served tree does not remove units already installed on a host or replace its existing per-user Waybar configuration. Such a host needs a deliberate deployment of these exact removals/configuration changes; the entire unattended installer should not be rerun as a desktop migration.

## Interface references

- Waybar native menu contract: https://github.com/Alexays/Waybar/blob/master/man/waybar-menu.5.scd
- Waybar event/menu dispatch: https://github.com/Alexays/Waybar/blob/master/src/AModule.cpp
- GTK 3 CSS properties: https://docs.gtk.org/gtk3/css-properties.html
- Unattended-upgrades origin policy and dry-run inspection: https://github.com/mvo5/unattended-upgrades/blob/master/README.md

## Current validation outcome

| Check | Result |
| --- | --- |
| Full installer suite | 1,930 tests: 1,878 passed, 48 skipped, 4 failures reproduced in earlier code, 0 errors |
| Tools suite | 179 passed |
| Focused hardware/Tomat/native-menu suite | 27 passed, 1 missing-Perl-dependency skip |
| New Notifications suite | 5 passed, including 104 GTK cases |
| Shell validation | 285 files, 581 parser checks, passed |
| Browser, generated-build and preseed checks | Passed |
| Payload verification | All 1,400 members match the manifest/source hashes and the builder's executable-mode normalization; removed assets absent |
| Scope audit | 12 modified, 3 added, 4 removed files outside the new validation directory; no undeclared changes |

The full suite is **not all-green**. Three failures match the existing IOCost test/profile disagreements recorded in the previous archive. No test is disabled to hide them. The preserved original-ZIP reproduction logs are in `validation/tomat-native-menus-20260920/baseline-iocost*.log`. The affected IOCost tests are:

- `test_all_profiles_complete_and_exact_enable_matrix (test_iocost_20260919.IOCostTests.test_all_profiles_complete_and_exact_enable_matrix)`
- `test_both_enabled_profiles_native_staging_and_query (test_iocost_20260919.IOCostTests.test_both_enabled_profiles_native_staging_and_query) (profile='btrfs-de-dual-flex')`
- `test_reported_profile_native_iocost_transaction_through_real_bridge (test_target_debconf_boundary.TargetDebconfBoundaryTests.test_reported_profile_native_iocost_transaction_through_real_bridge)`

The fourth failure is `test_opposite_role_fails_before_preflight_marker`: its unchanged eight-second fatal-record observation deadline expires in this environment. Running the unmodified test alone against both this revision and a fresh extraction of the previous complete archive reproduces the same failure. A separate diagnostic harness, without editing the repository test or production code, allowed thirty seconds. The fatal record appeared after 10.812 seconds in this revision and 13.096 seconds in the previous archive; both then passed the remaining original process-hold and missing-preflight assertions. These diagnostics explain the deadline failure but do not replace or relabel the failed full-run test. Reproduction logs, the diagnostic harness and `bootstrap-deadline-diagnosis.json` are included.

The full validator correctly reports failure. This revision's focused tests and all other full-validation stages pass. See `validation/notifications-followup-20260920/release-result.json` for machine-readable counts and qualifications.
