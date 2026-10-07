# NFS validation record - 2026-09-30

## Follow-up audit of the delivered codebase

This section records the subsequent audit against the previously delivered
`debian-preseed-de-nfs-refactored-20260930.tar.gz`, not against the original ZIP.
The original delivery evidence below is retained as history. The follow-up
keeps every one of the previous archive's 2,038 regular-file paths and all
1,991 original ZIP file paths. No Xwayland/Zoom/Discord source is changed.
Only NFS deployment code/configuration, its tests/profile-hash metadata, its
existing guide/validation record, and generated installer snapshots change.
New files under `follow-up/` are validation evidence, not deployment code.

### Corrections verified during this pass

* Persistent home binds: root ownership did not prevent the home owner from
  renaming the dedicated parent and redirecting the generated mount through a
  symlink. A real unprivileged/native-generator fixture reproduces this. All
  endpoints are now created before `chattr +i` locks each dedicated first-level
  parent. An unsupported/failed lock aborts before managed fstab and completion
  publication. The share contents are not marked immutable. `e2fsprogs` is
  recorded in both role dependency variables in all ten profiles. Existing
  unmanaged fstab destination aliases are rejected, including decoded octal
  escapes and lexical path normalization; ambiguous leading `//` settings are
  rejected too.
* NFS server: v2 is explicitly disabled as well as v3, v4.0, UDP and RDMA.
  Mountd retains AF_NETLINK for the kernel's export/authentication caches.
  The vendor's ignored export-refresh errors are replaced by required
  `exportfs -r` start/reload commands. Completion/configuration/firewall
  assertions are staged before package installation, so package-preset unit
  enablement cannot start a partially configured server successfully.
* Export-root permissions: an exact access/default ACL replaces inherited
  named grants. Existing children are not modified recursively. Native libacl
  fixtures confirm the intended ACL/mode semantics; the actual `setfacl` CLI
  is unavailable here and its exact invocation is unit-tested instead.
* Installer command lifecycle: a real fixture reproduced a subprocess child
  surviving the old timeout handler. Each command now has its own session and
  process group. Timeout/exception cleanup signals the owned group before
  reaping the direct child and restoring package-service inhibition. The
  regression verifies the descendant started, is killed, and cannot perform
  a post-timeout write. This is lifecycle cleanup for trusted package tools,
  not containment of malicious maintainer scripts or package-state rollback.
* Profile provenance: current profile hashes track the narrow dependency
  edits. Original/historical hashes and the previous explanations remain
  intact; the previous current values are recorded as follow-up history.
  No test assertions or unrelated release gates were relaxed.

### Successful final checks

| Check | Follow-up result | Evidence |
| --- | --- | --- |
| Focused NFS suite | 65 tests, PASS (19 more than the prior delivery) | [nfs-final.log](follow-up/nfs-final.log) |
| Standalone NFS wiring checker | PASS | [network-sharing-check-final.log](follow-up/network-sharing-check-final.log) |
| Repository integrity after metadata synchronization | 10 tests, PASS | [repository-integrity-final.log](follow-up/repository-integrity-final.log) |
| Current profile provenance case | PASS | [profile-provenance-after.log](follow-up/profile-provenance-after.log) |
| Rebuilt installer payload | 1,689 files; manifest bytes and preseed pins match | [payload-integrity.json](follow-up/payload-integrity.json) |
| Repeated builds | All three generated products byte-identical | [repeated-build.json](follow-up/repeated-build.json) |
| Snapshot/shell checks | 705 checks across 347 shell files, PASS | [check-final.log](follow-up/check-final.log) |
| Preseed checks | 59 files; four command values preserved, PASS | [preseed-final.log](follow-up/preseed-final.log) |
| Codebase audit | Exit 0; categorized coverage, not all runtime passes | [audit-summary.json](follow-up/audit-summary.json) |
| Protected private-Xwayland stack | All 16 recorded original hashes unchanged | [protected-xwayland-preservation.json](follow-up/protected-xwayland-preservation.json) |

The focused tests include native systemd fstab generation, native assertion
semantics, and AppArmor parser checks, together with fixture-based installer,
menu and daemon configuration tests. The audit categories remain 609 pass,
222 structure-pass, 159 blocked-dependency, 616 inventory-only and 11
template-needs-render. They must not be counted as 1,617 runtime passes.

### Complete regression coverage: still not a green release

| Suite | Prior delivered archive | Follow-up final coverage |
| --- | --- | --- |
| Complete installer discovery | 3,185 invocations; 118 failures, 9 errors, 72 skips | 3,204 invocations; 117 failures, 7 errors, 72 skips |
| Complete tools suite | 244 tests; 3 failures | 244 tests; the same 3 failures |

Failure counts include failing subtests. Final installer coverage was divided
by module into four disjoint isolated-copy partitions. The final multiset was
checked against full discovery: 3,204 invocations, 3,197 distinct IDs; seven
inherited imported tests are each discovered twice. No cases were dropped.
After synchronizing current profile metadata, partition 0 was rerun in full.
All ten repository-integrity module tests were rerun on the final source and
replace that same module's results in partition 2. Its raw log deliberately
retains ten pre-correction provenance subtest failures; the aggregate does not
pretend those were a final result. Partitions 1 and 3 do not consume that ledger.

There are **no new failing case IDs or subtest identifiers** after normalizing
only temporary-directory names in the comparison. Existing outcome differences
are not attributed to unrelated fixes. Existing failures remain out of this
NFS audit's scope, and the repository cannot be described as a green release.
The unchanged tools failure IDs are listed in the historical record below.

See [full-suite-comparison.json](follow-up/full-suite-comparison.json) for exact
IDs, raw input names, replacement-module provenance and complete coverage.
[tools-comparison.json](follow-up/tools-comparison.json) records the tools
comparison. Raw baseline/final logs and machine-readable partition outputs are
included in `follow-up/`; no skipped dependency tests are claimed to pass.

### Evidence boundaries and deployment requirements

The target remains Forky/systemd 261.2. This container is Debian trixie with
systemd 257.9 and Python 3.13.5. Additional NFS/nftables/setfacl/chattr test
binaries could not be installed because the Debian mirror was unavailable by
DNS. Native `libacl.so.1` was usable, but `CAP_LINUX_IMMUTABLE` and network
namespace creation are denied. The attempted immutable operation returned
EPERM; there is **no claim of a successful immutable enforcement test here**.
See [kernel-capabilities.json](follow-up/kernel-capabilities.json).

There was no real NFS client/server mount, reboot, target GUI authorization,
native nftables ruleset load, or enforcing AppArmor session. The mount-parent
change fails closed on unsupported target filesystems; its Btrfs/F2FS runtime
behavior and ordinary-user rename denial still need target-side verification.
The guide's live acceptance matrix and rollback procedure were updated,
including the requirement to remove/stop all persistent bind definitions
before clearing a parent's immutable flag. Keep roles/binds disabled until
that acceptance and the existing release-gate failures are reviewed.

No new source-build workflow or global Xwayland dependency was introduced.
[Source preservation](follow-up/source-changes.json) records every changed
baseline path and verifies unrelated files and historical ledger values.
[Rendered examples](follow-up/rendered-final-example/) are fixtures, not a
standalone firewall ruleset or an installed-target capture.

### Reproduction

From the repository root, use the commands in the historical reproduction
section, plus the complete installer suite:

```sh
python3 -B -m unittest discover -s d-i/forky/tests -p 'test_*.py'
PYTHONPATH=d-i/forky/tests python3 -B -m unittest -v test_repository_integrity
python3 -B -m unittest discover -s tools/tests -p 'test_*.py'
```

The complete suites currently return nonzero for the documented failures.
The partition/module runners are retained in `follow-up/` for reproducing the
coverage method; run each partition in a separate complete source copy. The
ordinary sequential command above remains the repository's release gate.

## Initial delivery: historical validation record

The following sections and adjacent original evidence files describe the
previous delivery. Their test counts and historical source comparison have
not been rewritten to imply that they describe this follow-up.

### What this record proves

The supplied ZIP was extracted as the pristine comparison tree. The modified
repository includes all original file paths, the NFS implementation and tests,
configuration documentation, and regenerated installer products. No software
was compiled from source for this addition. Existing Xwayland-specific assets
were preserved; the byte comparison covers 16 named Xwayland/Zoom/Discord/Cage/
clipboard files. Shared AppArmor changes add only the new menu's transitions
and lifecycle signal rules. All original lines in the ten profile files remain.

The implementation targets Debian Forky / systemd 261.2, as requested. The
container used for these checks runs systemd 257.9 and Python 3.13.5. This is
an offline validation record, not an assertion of live target acceptance.

### Successful checks

| Check | Result | Evidence |
| --- | --- | --- |
| Installer rebuild | 1689 payload files; generated snapshot current | [build.log](build.log) |
| Snapshot and shell parsers | 347 shell files, 705 parser checks, PASS | [check.log](check.log) |
| Preseed checks | 59 files, four command values preserved in debconf read-back, PASS | [preseed-check.log](preseed-check.log) |
| Focused NFS suite | 46 tests, PASS | [nfs-tests.log](nfs-tests.log) |
| Existing firewall/installer integrations | 7 tests, PASS | [integration-regressions.log](integration-regressions.log) |
| Updated menu route contracts | 3 tests, PASS; six groups and 26 routes | [menu-contracts.log](menu-contracts.log) |
| Codebase audit | Exit 0; categories below | [audit-summary.json](audit-summary.json) |
| Private-Xwayland preservation | 16 named files byte-identical to the upload | [protected-xwayland-preservation.json](protected-xwayland-preservation.json) |

The focused suite covers all ten profile definitions; exact coverage of 41
allowed IPv4 addresses without neighboring addresses; role/bind/read-only
combinations; firewall rendering across managed profiles; dash/BusyBox behavior;
invalid booleans, paths, dependencies, identities and exports; symlink/hardlink/
FIFO and unmanaged-configuration rejection; atomic writes and identical reruns;
package-start policy restoration; restrictive installer umask; server-only and
client-only configuration; real `systemd-fstab-generator` output; fixed menu
arguments, role gating, cancellation, stale-report rejection, and AppArmor
parser/transition contracts. Tests use fixtures and subprocess stubs where a
live target would otherwise be required; they are not network mount tests.

The audit categories are **609 pass, 222 structure-pass, 159
blocked-dependency, 616 inventory-only, and 11 template-needs-render**. A
structural/inventory check or an unavailable dependency is not a runtime pass.
[Rendered examples](rendered-example/) show a both-roles/both-binds profile,
including real generated mount/automount units, exact exports, sysctls, and NFS
firewall excerpts. Excerpts are not a standalone nftables ruleset.

### Existing failing regressions: explicitly not a green release

An exploratory full installer-suite run during development ran 3139 tests and
reported 158 failures, 13 errors and 72 skips. That run was neither a pristine
baseline nor the final stable tree, so its failures are not all asserted to be
inherited. Ninety-two distinct failing case identifiers from it were selected
for a stable original-versus-final comparison.

| Stable comparison | Original ZIP extraction | Final modified tree |
| --- | --- | --- |
| Selected installer regression cases | 92 tests; 133 failures, 6 errors | 92 tests; 114 failures, 6 errors |
| Complete tools suite | 244 tests; 3 failures | 244 tests; 3 failures |

Failure totals include subtests, which explains totals larger than the number
of selected cases. **There are no new failing case identifiers in either
comparison.** This does not prove the full final installer suite is green or
exclude failures outside the selected cases. It records the actual tested
scope. Some existing provenance cases now pass with the new recorded profile
hashes. Three menu cardinality assertions were necessarily updated for the
requested new route; their historical test function names are retained.

The unchanged failing tools cases are:

- `test_installed_session_failures_20260913.PanelAndWiringTests.test_all_panel_click_commands_use_session_bound_user_services`
- `test_labwc_power_handoff.WiringTests.test_all_modified_launchers_have_cgroup_exit_and_session_ownership`
- `test_theme_editor.ThemeTests.test_catalog_covers_only_all_target_color_keys_once`

Machine-readable details: [regression-comparison.json](regression-comparison.json)
and [selected-regression-tests.json](selected-regression-tests.json). Raw logs:
[original selected cases](pristine-selected-regressions.log),
[final selected cases](refactored-selected-regressions.log),
[original tools](pristine-tools-tests.log), [final tools](refactored-tools-tests.log).
These failures were not bypassed with skips or unrelated source edits.

### Environment and live acceptance gaps

See [environment.txt](environment.txt), the [dependency install attempt](dependency-install-attempt.log),
and the [kernel network test](kernel-network-test.log). The environment could
not fetch additional packaged NFS/nftables test binaries because Debian mirror
DNS lookup failed, and it could not create a network namespace. No real NFS
server/client mounts, native nftables kernel load, reboot, target GUI, or live
AppArmor policy-enforcement tests were performed. AppArmor parser success and
systemd 257.9 unit generation do not certify Forky/systemd 261.2 behavior.

Before production enablement, carry out the live acceptance matrix in
[the deployment guide](../../network-sharing.md#live-acceptance-before-enabling-production-sharing):
actual RW/RO/root-squash and excluded-peer tests, matching identities, effective
service and firewall policy, absent-server boot and recovery, busy disconnect,
mount/bind ordering and teardown, authorization cancellation, report freshness,
and every menu action under enforcing AppArmor. Check existing desktop and
private Zoom/Discord Xwayland behavior too. Remaining project release-gate
failures must also be reviewed and resolved on the release host.

### Reproduction commands

From the repository root:

```sh
python3 -B tools/check_network_sharing.py
python3 -B -m unittest discover -s d-i/forky/tests -p test_network_sharing.py -v
PYTHONPATH=d-i/forky/tests python3 -B -m unittest -v \
  test_config_safety.NftablesCatalogTests \
  test_xanmod_regdb_20260927.XanmodRegdbTests
PYTHONPATH=d-i/forky/tests python3 -B -m unittest -v \
  test_desktop_navigation_20260918.NavigationTests.test_exactly_six_top_level_groups_and_twenty_five_unique_routes \
  test_kanshi_fuzzel_followup_20260919.NativeShellProtocolTests.test_all_six_management_groups_and_twenty_five_actions_have_native_metadata \
  test_menu_apparmor_integration_20260919.ActionContractTests.test_all_twenty_five_management_routes_execute_only_their_fixed_argv
make build
make check
python3 -B tools/check_preseeds.py
make audit
python3 -B -m unittest discover -s tools/tests -p 'test_*.py'
```

For the selected comparison, pass the JSON array in
`selected-regression-tests.json` as separate arguments to `python3 -B -m
unittest -v` with `PYTHONPATH=d-i/forky/tests`, once in each built tree. The tools
suite's nonzero exit is expected from the documented existing failures, not an
accepted production release gate. Run the complete `make test` and `make
validate` as well on the release host, with an adequate validator test timeout.

### Scope and archive evidence

[source-changes.json](source-changes.json) records uploaded-file SHA-256 hashes,
changed original paths, added paths and the absence of missing original files.
Generated installer products are identified separately from source changes.
Ephemeral `.build/`, `__pycache__/` and `.pyc` files are excluded from the release
archive; none were present in the uploaded source. The published tarball's
separate SHA-256 file identifies the exact downloadable artifact.
