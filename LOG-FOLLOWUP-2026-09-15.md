# Debian preseed desktop: follow-up audit and release r2

15 September 2026

## What this release changes

This is a complete replacement installer-server snapshot, based on `debian-preseed-de-fixed-20260915.tar.gz`, not a patch-only archive or an in-place upgrade for the installed laptop. It retains the first delivery's fixes and adds **one production correction: nonblocking Spotify output supervision**. It also adds nine regression tests (eight executable process tests pass here; the optional real D-Bus proxy test is explicitly skipped), refreshed packaging, and this audit record.

`LOG-REMEDIATION-2026-09-15.md` and `validation/log-remediation-20260915/` describe the first delivery. This follow-up supersedes that report's Spotify shutdown assurance and validation totals. Historical results have not been edited into passing results.

The scope remains narrow. No kernel, compositor, application, driver, or package was compiled. No installer phase was applied to the container or the laptop; no disk, firewall, host service, or kernel AppArmor policy was changed. Python and Perl source/interpreter checks are not application builds. The repository's existing `tools/build.py` only refreshed the distributable archive, manifest, and preseed checksum pins.

**This is not certification that every target runtime error has disappeared.** The supplied captures predate the patches, and hardware/vendor diagnostics remain explicitly classified below. Kernel-enforced application replay, real user-manager scope cleanup, and fresh-install acceptance remain required.

## Evidence identity and coverage

The new `installer-state(1).zip` is byte-identical to the original `installer-state.zip`, SHA-256 `0c0e67a56b39430ad8a00eb6a5d368a8224d1119a0859b4d8ddfda48814f49ba`. The nested `logs.zip:logs/installer-state.zip` is also identical, including all 49 member-file contents.

The new `managed.zip` is byte-identical to `logs.zip:logs/managed.zip`, SHA-256 `f40e64e7de6cf3f70bf670f8d6c125274bf63d67ee53a9ed6aaf38ece2978a77`. Neither upload supplies a post-fix boot or application session.

The second pass scanned **90 text-file instances / 51,261 lines**, without needlessly re-extracting the identical nested installer capture. Raw/journal copies of the same AppArmor event were deduplicated by audit identity and access fields; logger prefixes and optional node labels were excluded from comparison. This reproduces the first delivery's **16,903 unique access records**, including **16,773 null-profile descendant records**, across six affected top-level profile families. The inventory lists file hashes, sizes, line counts and event totals, not the private raw incident logs.

The source paths and evidence classifications in the first report were rechecked. The user journal still identifies six failed transient application instances: three Foot, two Timeshift, and one Spotify. Firstboot's validation results still contain exactly one failed component, `managed-git-account-metadata`. The earlier failed-unit snapshot predates that firstboot failure; it is not proof that firstboot ultimately succeeded.

## New defect reproduced and corrected

### Spotify: blocked output could prevent shutdown escalation

The first implementation checked a 15-second stop deadline but then called blocking `sys.stdout.buffer.write()` / `flush()`. An undrained stdout pipe could stop the supervisor inside that write indefinitely. This is especially important where Chromium moves its main process into an application-created scope rather than remaining in the launcher's service cgroup.

A disposable Python child was configured to ignore SIGTERM and continuously write output while the supervisor's stdout pipe was deliberately left undrained. With the first delivery's code, the supervisor was still blocked after 17 seconds. With the final r2 source and the real production deadline, it stopped after approximately **15.45 seconds**, killed and reaped the tracked child, and returned **137**. That status is a forced SIGKILL result, not a newly accepted success code. These are local fixture observations, not results from running Spotify or journald on the target laptop.

The change is confined to `_run_spotify()` in:

```
d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/cli.py
```

It now uses nonblocking descriptors, a **256 KiB maximum pending-output queue**, and `PollSelector` read/write readiness. A full output pipe pauses child-output reads rather than blocking signal handling and the stop deadline. Normal output continues to be forwarded; a real-process test verifies a 2,000,000-byte stream plus stderr without loss. Regular-file stdout is supported, and the previous descriptor blocking flags and signal handlers are restored on exit. Output/setup errors still terminate and reap the tracked child. No external dependency or additional AppArmor permission is introduced.

The existing **0.2-second post-exit drain bound** remains. When a log consumer does not recover, pending output may be abandoned after that bound rather than hanging shutdown; the actual child status is preserved. This is a bounded shutdown tradeoff, not a promise that undeliverable logs can always be retained. An undelivered handoff message cannot convert status 1 into success. Cancellation is also kept separate from successful existing-instance handoff.

The exact marker `Opening in existing browser session.` remains necessary, together with exit status 1 and no cancellation. Genuine failures, other exit codes, oversized/sub-string matches, and signal deaths remain failures. The paired Spotify signal rules from the first delivery remain unchanged.

`validation/log-followup-20260915/implementation.diff` contains the production change. `production-deadline-reproduction.json` records the baseline archive hash, final source hash, and before/after observations.

## Previously implemented corrections rechecked

| Area | Integration and boundary verified |
| --- | --- |
| Firstboot Git account metadata | `.config/git` and `.config/gitops` are in the actual account-copy loop. Production copy and validation fragments are executed by tests. Ownership, 0700 directories, 0600 files, single-link checks and rejection of unsafe replacements remain. The validator was not weakened. |
| Tuta tray D-Bus | Its private `org.freedesktop.StatusNotifierItem-2-1` name is an OWN permission, while the tray watcher and secret service retain TALK permission. UPower filtering and required proxy readiness remain. No broad ownership namespace or raw bus exposure was added. The permission deliberately matches the observed PID/serial contract; a future naming change needs a targeted review. |
| Timeshift | Only the canonical Wayland `/usr/bin/timeshift-launcher` receives the host-administration namespace exception. Polkit authentication, service lifetime, control-group killing, and stop timeout remain. Similar names under other paths do not receive the exception. |
| Foot | Only bare default-shell `/usr/bin/foot` receives `SuccessExitStatus=1`. Explicit commands, different terminals and internal error 230 are not normalized. The unavoidable ambiguity remains: a manually entered `exit 1` in that bare shell is also accepted. |
| Native application scopes | The four existing Vivaldi, Code, Chromium and Bitwarden prefix drop-ins are staged and included in the payload. They associate application-created scopes with the Labwc session; they do not prevent Chromium's cgroup migration. Effective dependencies and logout cleanup require an actual user manager. |
| FocusWriter and RetroArch | The scalar quoted QSettings font is preserved. RetroArch discovers the current desktop ID with the old filename fallback. Source tests verify the real discovery and staging paths. |
| AppArmor | The Thunar archive helper inherits its intended profile instead of entering generated null profiles. Existing Bubblewrap child transitions remain. Scoped Git lock links, own mail-spool reads, FocusWriter process/Qt reads and inherited owner PTYs remain present in the staged policies. No global allow-all, complain-mode switch, or profile disablement was added. |

Complain-mode `ALLOWED` records with denied masks represent missing policy permissions, not proof that enforcement would succeed. Correcting the initial helper transition is preferable to granting permissions to thousands of generated null-profile descendants. The captured audit stream also reports suppression, so no static review can claim coverage of operations that were never recorded.

## Private Xwayland preservation

All six dedicated private-runtime/profile files and all three direct-execution guard blocks are byte-identical to the original upload and/or the first delivery as recorded in `xwayland-preservation.json`. The allowlist is still exactly `discord` and `zoom`.

No host-wide Xwayland, additional compatibility application, compositor rebuild, extra X11 socket, or change to the private runtime was introduced. The existing host-Labwc missing-Xwayland diagnostic remains classified as an intentional absence; it was not silenced by enabling global Xwayland.

## Validation results and limitations

| Check | Result |
| --- | --- |
| First-delivery incident regressions | 23 passed |
| New process-supervision regressions | 8 passed |
| New optional real filtered-D-Bus test | 1 skipped: `xdg-dbus-proxy` is not installed in the container |
| Broad test-bearing modules | 47 modules; 1,160 tests counted; 27 skips; no module timeouts |
| Broad failures | 8 failure reports and 7 error reports in five existing modules; all affected test identities reproduce on the unmodified first-delivery baseline |
| Compiler-based tests | 2 explicitly not run, not counted as passes, to respect the no-compilation constraint |
| AppArmor source parsing | 34 files / 230 named profiles; names/preprocess only, no compiled policy or kernel load |
| Shell checks | 277 files / 565 parser checks passed |
| Preseed | 59 files passed; four generated command values survive private debconf read-back unchanged |
| Payload | All 1,290 member files match source bytes, manifest hashes and normalized payload modes |
| Generated packaging | `tools/build.py --check` passes after refresh |
| General source inventory | 431 syntax/configuration passes; 130 structural unit checks; 155 dependency-blocked entries; 11 tool-blocked JavaScript entries; 489 inventory-only entries; two templates needing rendering |

The five broader failing modules are unchanged legacy conditions: missing historical raw-log fixtures in `test_desktop_sandbox` and `test_installed_failures_20260911`; absent Perl Moo dependencies for `test_managed_external_software`; an older subprocess mock in `test_podman_incus_redesign`; and pre-existing notification/wlrctl/confinement expectations in `tools/tests/test_labwc_power_handoff`. No legacy assertion or fixture was changed to manufacture a green result. Comparative logs are included. `test_environment.py` is a helper module with zero test cases; separate discovery returns 5 under this interpreter and is recorded as no tests, not a passing test module.

The container has Python 3.13.5, Perl 5.40.1, AppArmor parser 4.1.0 and systemd tooling 257.9; the supplied target uses newer systemd/kernel versions. Node and parts of the target Perl dependency set are unavailable here. Those blocked checks are not passes. A static `.scope` probe cannot substitute for creation of a real transient scope and is not counted as runtime validation.

The added live D-Bus test is ready to run where the preinstalled proxy exists. It creates a private bus with no service-activation entries, invokes the production proxy lifecycle and policy-argument construction, and checks that the configured tray name can be owned while the watcher, secret service, notification service and another item name cannot. It does not use the host bus. Here only the private unfiltered-bus fixture and call syntax were independently exercised; **the filtered exchange was not run**.

To repeat the incident tests from the repository root:

```sh
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_log_regressions_20260915.py'
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_log_followup_20260915.py'
python3 -B tools/build.py --check
python3 -B tools/check_preseeds.py
python3 -B tools/check_shells.py
```

Do not run the complete unfiltered suite when compilation is prohibited: the retained NVIDIA-interface module contains two compiler-based tests. This review selected around those two tests without changing them. Standard library parsing, interpreter execution, tar/gzip generation and private fixture processes were the only relevant mechanisms used for this correction.

## Diagnostics not claimed repaired

The detailed classification table in the first report remains applicable. In particular, ACPI/firmware operand errors, RMI descriptor parsing, MMIO/SMT warnings, HDMI atomic-commit failures, Vivaldi resource/extension errors, and Tuta's GTK assertion are not demonstrated fixed. No firmware/kernel/graphics or vendor application changes are justified by this offline follow-up alone.

The installer FAT codepage message is followed by its internal CP850 fallback and successful filesystem progress. Bitwarden explicitly copies after cross-filesystem hard-link failures. Code explicitly forwards the reported Chromium options despite its CLI warnings. Initial vault creation, absent optional browser integrations, startup-state notices and skipped conditions are not independently demonstrated failures.

The Mullvad package's chroot AppArmor-reload warning does not include the underlying parser diagnostic. Later boot records load the profile, but that does not retroactively prove a particular cause for the earlier warning. It is retained in the evidence classification, not erased or counted as a repaired syntax defect.

Incorrect-password and cancelled sudo authentication remain failures. The root-bus inspection warning is not grounds to expose `/run/user/0/bus`. Empty security/timer logs do not establish that their future workloads have run successfully. Private Xwayland remains intentionally unavailable to the host compositor and other applications.

## Publish and accept

Publish this **entire r2 repository atomically**, including `d-i/forky/payload.tar.gz`, `payload.manifest`, and `preseed.cfg`. Do not mix either delivery's generated payload with the other delivery's source or pins. The external SHA-256 sidecar covers the complete tarball, and the external verification JSON verifies archive members against the final working tree.

Extraction does not update an already-installed machine. Do not rerun destructive unattended-installer phases on the laptop as an update mechanism. Validate with a disposable fresh installation of the intended classes and hardware, or an independently reviewed non-destructive deployment procedure.

Acceptance still needs firstboot completion, Tuta tray/menu/notifications and secret-service access, authenticated Timeshift operation, Foot ordinary close versus explicit command failure, Spotify first/second launch and stop, FocusWriter, Git key loading, Thunar archive operations and thumbnails, and session logout. Replay with the reviewed AppArmor policies actually enforcing and with fresh application processes, not old null-profile descendants. Verify Zoom and Discord retain their private display and all other applications remain outside that compatibility allowlist.

Useful read-only inspection commands, run in the intended installed session, are:

```sh
systemctl --failed --no-pager
systemctl --user --failed --no-pager
journalctl -b -u firstboot.service --no-pager
sudo /usr/local/libexec/apparmor-managed-modes-run --check --check-loaded
sudo journalctl -k -b --no-pager | grep 'apparmor='
systemctl --user list-units --type=scope --no-pager
systemctl --user show ACTUAL_SCOPE_NAME.scope \
  -p DropInPaths -p Requisite -p After -p PartOf -p KillMode -p TimeoutStopUSec
```

Use an actual current scope name in the final command. The mode-check command reports the configured mode; it does not switch complain profiles to enforcement or establish workload coverage. Save work before testing termination or logout.

## Primary technical references

These support the mechanisms, not a claim that the installed laptop was retested.

* Python descriptor blocking flags: `https://docs.python.org/3.14/library/os.html#os.set_blocking`
* Python selector readiness and PollSelector: `https://docs.python.org/3.14/library/selectors.html`
* xdg-dbus-proxy TALK/OWN permissions and readiness/lifetime descriptor: `https://manpages.debian.org/unstable/xdg-dbus-proxy/xdg-dbus-proxy.1.en.html`
* systemd dash-prefix drop-ins and dependency semantics: `https://manpages.debian.org/unstable/systemd/systemd.unit.5.en.html`
* Scope lifecycle and externally created processes: `https://manpages.debian.org/unstable/systemd/systemd.scope.5.en.html`

The first report retains the AppArmor, Foot, Chromium, QSettings and package-file references used for its changes.
