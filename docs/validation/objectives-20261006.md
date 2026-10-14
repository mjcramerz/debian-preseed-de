# Managed log, mount, GitOps and dock repairs - 2026-10-06

## Scope and environment

This change implements the requested fstab layout, NFS access and desktop
visibility improvements, scoped AppArmor repairs, GitOps clear operations and
opaque Crystal Dock backgrounds. The Unicode Git fixture uses English words
and a neutral symbol written as a Unicode escape. No package is compiled from
source. The private Xwayland implementation remains restricted to Zoom/Discord.

Validation ran as the ordinary workspace account on Forky with systemd 262-1,
AppArmor 4.1.8-2, Git 2.53.0-1, util-linux/mount 2.42.4-1, nfs-utils 3.1.1-1,
GLib 2.90.0-1, GVfs 1.62.0-3 and Python 3.14.7-3. The intended installed target
is systemd 261.2. Native generator results below were obtained with the host's
262 generator; they are not live acceptance on a 261.2 installation.

## Complete managed-log coverage

All 39 regular files under `todo/managed/` were read, including rotated audit
logs and empty `.raw`, `.dat` and `.expected` files: 15,573 total lines and
22 empty files. The inventory was independently counted again after review.

| File relative to `todo/managed/` | Lines |
| --- | ---: |
| `apps/apps.log` | 560 |
| `models/openai/chatgpt/chatgpt.log` | 0 |
| `models/openai/chatgpt/runtime/codex-login.log` | 0 |
| `models/openai/chatgpt/runtime/codex-tui.log` | 0 |
| `models/openai/codex/codex-login.log` | 0 |
| `models/openai/codex/codex-tui.log` | 130 |
| `models/whisper/whisper.log` | 0 |
| `security/apparmor/apparmor.log` | 1,467 |
| `security/apparmor/modes.log` | 11 |
| `security/audit/auditd.log` | 151 |
| `security/audit/auditd.log.1` | 8,572 |
| `security/auth/auth.log` | 109 |
| `security/chkrootkit/chkrootkit.log` | 0 |
| `security/chkrootkit/daily.log` | 0 |
| `security/chkrootkit/daily.log.raw` | 0 |
| `security/chkrootkit/log.expected` | 0 |
| `security/clamav/clamav.log` | 0 |
| `security/clamav/freshclam.log` | 0 |
| `security/clamscan/clamscan.log` | 0 |
| `security/crowdsec/crowdsec-firewall-bouncer.log` | 19 |
| `security/crowdsec/crowdsec.log` | 95 |
| `security/crowdsec/crowdsec_api.log` | 1,678 |
| `security/debsecan/debsecan.log` | 0 |
| `security/debsums/debsums.log` | 0 |
| `security/fail2ban/fail2ban.log` | 18 |
| `security/lynis/lynis-report.dat` | 0 |
| `security/lynis/lynis.log` | 0 |
| `security/lynis/scan.log` | 0 |
| `security/nftables/nftables.log` | 298 |
| `security/rkhunter/rkhunter.log` | 0 |
| `security/rkhunter/scan.log` | 0 |
| `security/spectre-meltdown-checker/spectre-meltdown-checker.log` | 0 |
| `system/fwupd/security-scan.log` | 0 |
| `system/kernel.log` | 1,152 |
| `system/storage/storage.log` | 0 |
| `system/system.log` | 1,106 |
| `system/timeshift/timeshift.log` | 54 |
| `system/usb/usb.log` | 134 |
| `system/zram/zram.log` | 19 |

### AppArmor findings and treatment

The complete AppArmor log contains 407 STATUS records and 1,060 DENIED records.
Every denial belongs to one of these workloads:

| Profile/request | Denials | Treatment |
| --- | ---: | --- |
| `waypaper//waypaper-pgrep`, per-process `cgroup` reads | 858 | Allow metadata needed by procps. |
| Same child, per-process `environ` reads | 102 | Quietly deny unnecessary environment probes. |
| Same child, ptrace reads against desktop peers | 92 | Quietly deny probes associated with environment inspection. |
| Same child, `sys_ptrace` capability | 2 | Quietly deny the unnecessary capability. |
| Same child, NUMA node directory reads | 2 | Allow this directory's metadata. |
| Same child, `/proc/tty/drivers` reads | 2 | Allow this procps metadata file. |
| `desktop-launcher`, mount `setgid`/`setuid` | 2 | Allow credential dropping in a dedicated `mount-user` child. |

The mount child has no `sys_admin` capability or mount/umount permission.
Privileged mounts retain the existing sudo/Polkit/PID 1 authorization boundary.
The audit log's ordinary real UID and root saved UID corroborate the setuid
mount credential-drop failure. The supplied logs do not establish the cause
of a client's mounted NFS data-access denial.

Other observed messages remain recorded for installed-host diagnosis: CrowdSec
console enrollment/DNS/parser registration (`crowdsec.log`: 3, 10, 17, 30-31),
a failed sudo PAM conversation (`auth.log`: 100), PCI/ACPI/RMI firmware messages
(`kernel.log`: 650, 869-873, 1109), device removal (`system.log`: 673-674),
cross-device hardlink fallback (`apps.log`: 409 onward), and DRM atomic device
busy (`apps.log`: 470, 501). Global Xwayland creation failure (`apps.log`: 48)
is consistent with the requested private compatibility policy. These messages
do not justify changing hardware, credentials, enrollment or Xwayland in this
scoped patch. Empty logs provide no evidence of successful scans.

## Changed contracts

* Final target rendering aligns all six fstab fields using actual field widths.
  Different filesystem sources have an empty separator; Btrfs rows belonging
  to the same UUID remain together. NFS appending reformats the full table while
  preserving fields, ordering, escapes and comments. The partman hook and its
  internal fstab caches have been restored to the pre-formatting version; see
  the storage regression correction below.
* The server export root belongs to the primary account and `nfs-sharing`, mode
  2770, with the existing shared default ACL. Root ownership of protected
  parents and disconnected mount destinations remains. Existing data is not
  recursively re-owned. Active-session group checks reject Connect with a
  useful login instruction before submitting mount jobs.
* Home bind options include `x-gvfs-show` and stable `x-gvfs-name` values.
  GLib ignores bind rows before GVfs enumerates unmounted devices. A native GIO
  fstab fixture reproduces that behavior. Persistent GTK bookmarks are installed
  in the desktop skeleton and copied by the existing user-config stage. They
  keep both home paths in **Places**; persistent **Devices** entries for an
  unmounted bind are not provided by fstab on this stack.
* `mount -a` requires administrator authorization. `sudo mount -a` skips the
  explicit `noauto` client. The existing Connect menu starts the NFS source
  before its home bind, avoiding a bind to the disconnected mode-000 directory.
* GitOps clear commands preview by default, list local and remote tags, and
  require explicit noninteractive tag selection. Tag clear deletes only
  unselected tag refs locally and at origin/managed mirrors. Branch clear
  creates a parentless snapshot or rewrites the descendant graph from the
  oldest retained tag, preserving trees, metadata and tag annotations while
  removing invalid old signatures. Main/staging/release and usable origin
  tracking/fetch mappings are recreated.
* Retained tags need a single oldest tagged commit ancestral to every selected
  tag and HEAD. Incomparable/outside-history/nested/non-commit tags and conflicting
  retained tag OIDs cause safe refusal before remote writes. Dirty checkouts,
  extra worktrees, incomplete/shared object stores and unmanaged history refs
  are also refused.
* Remote writes use atomic pushes with explicit OID leases. Default-branch
  changes may need a separate bootstrap push/provider API update. A private,
  durable journal and candidate refs allow the same command with `--apply` to
  resume a recorded operation after failure. Concurrent changes stop recovery.
  Final local refs publish atomically; reflogs expire and unreachable objects
  are pruned. A private 0700/0600 recovery bundle deliberately retains the old
  history outside the live ref graph. Hosted caches, provider-only refs and
  other clones are not purged. Providers have separate transactions.
* All three dock background keys use Qt's alpha-first `#FF100417`, making
  their alpha fully opaque. The previous `#100417FF` encoded alpha `0x10`.

## Exact validation

Commands ran from the repository root. Tests use disposable fixtures; Git
commits, local bare-repository transport, ref transactions and GC are real.
Failure injection and provider APIs are mocked where identified by the tests.
No hosted Git destination or installed target configuration was changed.

| Command | Result |
| --- | --- |
| `timeout 180s python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_gitops_clear.py -q` | 32 passed, including CLI wiring, multiple retained tags, merge trees, remote/local interruption, actual mirror setup, GitLab/GitHub pruning, an unfetched independent GitHub branch, concurrent-write checks, atomic rejection, Unicode refs and a fetch after clearing a restricted-fetch checkout. |
| `timeout 120s python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_gitops_mirrors.py -q` | 16 passed. |
| `timeout 180s python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_network_sharing.py -q` | 133 run: 112 passed, 21 root-dependent filesystem fixtures skipped. Native GIO, generator, parser and policy checks passed. |
| `timeout 120s python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_apparmor_incidents_20261004.py -q` | 19 passed, including native offline policy parsing and scoped rule checks. No kernel policy load. |
| `timeout 180s python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_security_hardening_20260924.py -q` | Original run: 37 tests, 22 passed and 15 skipped. The formatting fixtures used host awk and missed the BusyBox incompatibility; see the corrected validation below. |
| Focused `ThemeValidationTests.test_dock_and_waybar_render_dark_navy_surfaces` command below | 1 passed. |
| `timeout 180s python3 -W ignore::EncodingWarning -B tools/build.py` | 1,704 payload files; final snapshot rebuilt. |
| `timeout 180s python3 -W ignore::EncodingWarning -B tools/build.py --check` | Snapshot, pins, preseed and browser artifacts current. |
| `timeout 180s python3 -W ignore::EncodingWarning -B tools/check_shells.py` | 350 shell files; all 711 parser checks passed. |
| `timeout 90s python3 -W ignore::EncodingWarning -B tools/check_preseeds.py` | 59 files passed; all four generated commands survived private debconf read-back unchanged. |
| `git diff --check` | Passed. |

The exact focused theme invocation was:

```sh
timeout 60s python3 -W ignore::EncodingWarning -B -c 'import sys,unittest; sys.path.insert(0,"d-i/forky/tests"); import test_themes; suite=unittest.TestSuite([test_themes.ThemeValidationTests("test_dock_and_waybar_render_dark_navy_surfaces")]); result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(not result.wasSuccessful())'
```

## GitLab origin and configured GitHub mirror follow-up

The mirror fixture runs the actual CLI dispatcher for
`mcr-repo-mirror gh fixture-owner --apply`, including native bootstrap pushes,
default-branch ordering, pruning and installation of the managed `mirror-gh`
configuration. Canonical GitLab/GitHub URLs remain in the fixture's Git config;
only the Git transport URLs are redirected to separate disposable local bare
repositories. GitHub provider API replies and the tag-deletion rejection are
mocked. Branch deletion rejection uses a real bare-repository receive policy.
No hosted repository is contacted.

Both clear flows include `mirror-gh` despite its normal push-only promotion
refspecs, absent fetch refspec, `skipFetchAll=true` and `tagOpt=--no-tags`.
Additional fixtures verify:

* Preview preserves local refs, both providers' refs and Git configuration.
* Branch clear removes obsolete branches/tags on both providers and publishes
  the same parentless snapshot or rewritten retained-tag history on both.
* A selected tag found only on GitHub is imported and correctly rewritten by
  branch clear. A retained annotated origin tag is also installed on GitHub.
* Tag clear preserves existing selected tag OIDs and each provider's branches
  and history; retaining none removes all tags from both providers.
  An independent GitHub branch whose commit is absent locally is also preserved
  without fetching that branch into the local object store.
* A rejected GitHub operation after GitLab succeeds leaves the local old refs
  and recovery journal. Both branch and tag clear resume the recorded selection
  after the rejection is resolved, even if a retry supplies different flags.
* A write to GitLab during GitHub publication stops before local publication.
  A write to GitHub during local GC keeps the journal and prevents a success
  report. A local write during final remote verification is also detected.

The review found that per-push verification alone could miss a write to the
earlier provider while updating the later one, or a remote write during local
cleanup. Both cases were reproduced before the production fix. The clear flow
now verifies every destination's configuration and complete planned refs after
remote publication and again before completion. Its final local-ref check runs
after the remote verification, before removing the recovery journal.

## Storage regression correction

The reported partitioning dialog was: "No partition table changes and no
creation of file system has been planned." Inspection found cosmetic formatting
had also been added to the partman finish hook, which writes the internal
`/var/lib/partman/fstab` and `fstab.new` caches before its completion stamp.
This went beyond the requested final-fstab presentation change.

The introduced `printf "%-*s  "` fails with actual BusyBox awk:
`%*x formats are not supported`, exit status 1. Both the partman formatter and
the late renderer contained that expression. The partman hook is now restored
byte-for-byte to commit `1b3e131`, preceding the formatting changes in `2efa2d6`.
Its SHA-256 is
`c7c5d257232f7a8a7cd946a5e424f4c2209f43cb2b552497efec9210d1068bb0`.
Partition recipes, sizing, device selection, filesystem policy and early hooks
are unchanged by this correction.

The final target renderer retains alignment and source separators, using a
format string built from the computed integer width instead of `*`. Its tests
execute the actual publisher with both host awk and BusyBox shell/awk, redirect
the target directory into private temporary fixtures, and copy the real fstab
template locally. They verify identical records and output, aligned columns,
separator rows, repeatability, mode 0644 and staging cleanup. Invalid or empty
records preserve the existing fixture fstab. No installed target is modified.

Corrected validation from the repository root:

| Command | Result |
| --- | --- |
| `timeout 180s python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_security_hardening_20260924.py -q` | 37 tests: 22 passed, 15 declared prerequisite skips. Corrected late-renderer fixtures passed with actual BusyBox awk. |
| `timeout 180s python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_dynamic_storage_sizing_20260921.py -q` | 22 passed, including all profile recipes, preserved-partition budgets and identical Dash/BusyBox layout output. Hardware reads are fixture inputs; no real disk is changed. |
| `timeout 180s python3 -W ignore::EncodingWarning -B tools/build.py` | Rebuilt 1,704 payload files. |
| `timeout 180s python3 -W ignore::EncodingWarning -B tools/build.py --check` | Snapshot, pins, preseed and browser artifacts current. |
| `timeout 180s python3 -W ignore::EncodingWarning -B tools/check_shells.py` | 350 files, 711 parser checks passed. |
| `timeout 90s python3 -W ignore::EncodingWarning -B tools/check_preseeds.py` | 59 files passed; all four command values survived private debconf read-back unchanged. |

This reproduces and removes the formatter failure; it does not constitute a
live reproduction of the reported partitioning dialog. A fresh installer run
must load the corrected snapshot rather than retain the old hook in its RAM
filesystem.

## Deployment limits

This evidence covers source, generated configuration, native offline parsers
and isolated fixtures. Live NFS UID/GID mapping, source/bind pairing, existing
child-file DAC/ACLs, active login groups and loaded AppArmor enforcement still
need checks on the two installed LAN hosts. Root-dependent ownership fixtures
were skipped rather than reported as passed. The intended systemd 261.2
environment and the dock's live visual appearance were not exercised.
GitHub/GitLab authentication, protected-ref permissions and default-branch API
behavior need verification at the intended repositories before an apply run.

The served release must include the refreshed `preseed.cfg`, `payload.manifest`
and `payload.tar.gz` together. The existing snapshot builder and its freshness
check were used; no real network publication was performed by this task.
