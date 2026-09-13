# Second-pass audit: eight boot/runtime objectives

Date: 2026-09-13

## Outcome and basis

All eight objectives remain incorporated at the source, installer-staging,
firstboot-validation and generated-payload levels. This was a fresh examination
of the delivered `debian-preseed-de-fixed.tar.gz`, not a restatement of the first
report. The original uploaded ZIP was retained separately for completeness checks.

The second pass found and corrected an AppArmor edge case, completed four
Wayscriber controls, and corrected an older regression test that still demanded
the deliberately removed NVIDIA `.path` unit. No unrelated runtime sources were
changed. The final delivery is a complete repository, not a patch-only package.

This is code/integration validation, not certification of a fresh hardware boot.
See the explicit validation limits below.

## Additional corrections made in this pass

### AppArmor: a disabled optional profile must not become falsely label-less

`apparmor_parser -N` can return no labels for a source listed in the configured
profile directory's `disable/` directory. The original fast-path implementation
created an isolated names-only inspection copy when the *requested* mode was
`disable`, but not when the existing source was disabled and the requested mode
was `enforce` or `complain`.

That distinction matters for optional profiles: an empty label set is permitted
for genuine include-only sources. A real disabled named profile could therefore
be cached as label-less, have its disable entry removed, and then be reported as
verified without loading the named profile. Read-only verification could also
misclassify the disabled optional source.

`AppArmor/ManagedModes/LoadedState.pm` now uses the existing isolated label
workspace whenever the requested mode is disabled **or an existing disable entry
is present**. This preserves accurate label identity while re-enabling and while
checking; it does not modify the source during inspection or weaken path checks.
The existing AppArmor policy already allows this exact workspace family, so no
policy permissions were broadened.

Three new regressions failed before the change and pass after it:

- An optional disabled named profile is re-enabled, loaded in the requested mode,
  verified, and becomes a no-op on the next reconciliation.
- Read-only combined source/kernel verification rejects a disabled optional named
  profile when the policy requests it enabled, without modifying the files.
- The installed native parser finds the labels through the isolated workspace
  during re-enablement.

The native parser reproduction is recorded in `disabled-label-probe.json`:
direct inspection of the disabled fixture returned no names, while the isolated
copy returned `alpha`. The names-only command used `-N -Q -K -T`; it did not
compile policy or load anything into the kernel. Editing/loading in regression
tests remained simulated, as documented below.

### Wayscriber: complete documented toolbar/presenter controls

The configuration retains its comprehensive drawing, gesture, preset, tablet,
performance, history, toolbar, presentation, board, rendering, persistence,
capture, export and keybinding settings. Four documented controls were added:

```toml
[ui.toolbar]
backend = "auto"
rebind_modifier = "ctrl_shift"

[presenter_mode]
toolbar_mode = "hidden"
enable_input_hud = false
```

These are additions to the existing tables, not duplicate table declarations in
the actual file. The legacy `layout_mode = "full"` setting is retained; its comment
now correctly explains the accepted alias for `regular`. The environment note
correctly describes `WAYSCRIBER_TOOLBAR_BACKEND` as an override of the TOML setting.

The resulting file has **635 lines and 148 keybinding actions**. Its syntax was
parsed with Python's TOML parser. The relevant controls were cross-checked against
the upstream example; the eventual APT binary was not installed or launched here.

### NVIDIA: align the existing regression with the new design

`tools/tests/test_installed_session_failures_20260913.py` still tried to open the
removed `.path` file and required `PathChanged=/dev`. That expectation directly
contradicted objective 1. The test now requires the watcher to be absent, checks
both NVIDIA-only udev activation rules and the bounded start settings, and retains
its existing helper safety and pre-greeter ordering assertions.

The new integration module also covers the real greeter renderer with a custom
account under both `/bin/sh` and BusyBox ash, the actual bootprofile enabling
helper, the actual primary-account copy loop and final permission normalization,
and NVIDIA absent-device/symlink/event-filtering behavior. Target transport and
paths are redirected to disposable fixture roots.

## Objective-by-objective audit

| Objective | Result and integration checked |
| --- | --- |
| 1. NVIDIA character links | The `.path` source is absent. Installer cleanup removes the obsolete target unit and its old wants link. The helper and boot oneshot remain staged and enabled. Firstboot requires the service/helper/rules, not a path watcher. Both active udev rules are restricted to NVIDIA add/change events and retain direct character-link creation, `TAG+="systemd"` and `SYSTEMD_WANTS`. Start limits remain 30 seconds / 5 starts. Native rule parsing and helper regressions pass. |
| 2. AppArmor fast path, logs and firstboot | Matching source plus matching loaded kernel state returns without mode editing, rewriting or reloading. Source drift and kernel-only drift reconcile only affected sources; changes are verified. Disable/unload and optional/include-only cases remain covered. The second-pass disabled-label correction closes the identified false-success case. Logger output is delivered once through stdout/stderr with the unit's identifier; no duplicate Sys::Syslog call remains. Firstboot uses one `--check-loaded` invocation and no preceding redundant `--check`. |
| 3. Greeter multimedia exclusion | All four PipeWire service/socket templates contain the greeter condition. The actual renderer was run for a nondefault greeter name and produced four valid 0644 drop-ins without unresolved placeholders or a condition-reset directive. Installer/firstboot checks reference the rendered files. Existing WirePlumber exclusions remain unchanged. |
| 4. Bootprofile once-per-boot lifecycle | The oneshot retains `RemainAfterExit=yes`. `install_target_bootprofile_assets()` in `grub.sh` owns enablement through the common helper; zram has no duplicate ownership. The actual helper was run twice in a relocated fixture root and produced one correct `sysinit.target.wants` link. Explicit restart remains an intentional reapplication path. |
| 5. Managed-network readiness | No managed-network dependency on `systemd-udev-settle.service` remains. The unit invokes `validate --wait-seconds 15`. One monotonic deadline is shared across expected adapters, rather than waiting 15 seconds per device. Tests cover delayed/present/unrelated adapters, invalid wait values, timeout, default immediate validation, and MAC/type/wireless mismatches. It does not wait for carrier, DHCP or unrelated hardware. |
| 6. Wayscriber configuration and account delivery | The canonical skeleton TOML is staged explicitly and included in the primary-account directory-copy allowlist. Installer and firstboot check its presence. The actual copy loop followed by the existing final home normalization produced the exact configuration with the fixture account's UID/GID, a 0700 directory and a 0600 file. Four additional documented controls are now explicit. |
| 7. Launcher missing-app observability | Missing optional managed applications are identified in summary output, including the exercised `skipped_missing=2 missing=postman,sleek` case. Missing applications remain nonfatal. Present but invalid desktop files are distinguishable from absent ones. Existing managed override/idempotency tests also pass. |
| 8. GRUB record-failure timeout | All three shell-generated writers and the canonical `05-bootprofiles.cfg.tmpl` use `GRUB_RECORDFAIL_TIMEOUT=500`. No managed writer retains `-1`. |

### Lifecycle interpretation

The NVIDIA helper has no global `/dev` watcher and no restart loop.
`SYSTEMD_WANTS` is acted on when a device becomes active; it is not a request to
rerun a service on every change to an already-active device. Keeping the direct
udev symlink rule is therefore intentional: it repairs links on the matching
add/change event, while device activation may request bounded reconciliation.
A normal boot should no longer produce hundreds of invocations due to unrelated
`/dev` changes. The exact count on this GPU/driver combination still needs a fresh
installed-host boot; this report does not claim it measured exactly one.

AppArmor's pre-login ordering is retained deliberately. The improvement removes
redundant work rather than allowing login before policy reconciliation. No claim
is made that the original 24-second boot measurement was repeated here.

For bootprofile, `RemainAfterExit=yes` prevents another ordinary start from
rerunning a successfully completed oneshot. An explicit restart stops and starts
it, so administrator-requested reapplication remains possible.

## Executed validation

All listed counts are fresh second-pass results, not copied from the first report.

| Check | Result |
| --- | --- |
| Focused boot/runtime suites, two modules | 37 passed |
| Installed-session regression module | 23 passed |
| Desktop/launcher regression module | 11 passed |
| Common unit-enabler / D-Bus integration module | 16 passed |
| Total selected tests | **87 passed; no failures, errors or skips** |
| Shell syntax | 267 files; 545 dash/ash/bash checks passed |
| Preseed validation | 59 files passed; all four generated command values survived private debconf round-trip validation |
| Native service verification | Four actual system units passed with isolated dependency/executable fixtures |
| Native greeter drop-in verification | Four actual rendered drop-ins passed with fixture vendor unit bases |
| Native udev verification | NVIDIA rule file passed `udevadm verify` |
| Python / TOML parsing | Five relevant Python files and Wayscriber TOML passed |
| Payload integrity | All 1,265 manifest entries match the source and archived file bytes; normalized payload modes verified; no duplicate or unexpected entries |
| Generated products | Payload, manifest and preseed regenerated; `tools/build.py --check` passes with matching pins; browser artifacts unchanged |

The native tools available were AppArmor parser 4.1.0, systemd 257.9-1~deb13u1 and
udevadm 257. No kernel, driver, compositor, Wayscriber or other application was
compiled. `tools/build.py` only regenerates the installer distribution products.

### Reproduction

From the repository root:

```sh
MANAGED_TEST_PERL_ADAPTER=1 python3 -B -m unittest discover   -s d-i/forky/tests -p 'test_boot_runtime*.py' -v
python3 -B -m unittest discover -s tools/tests   -p test_installed_session_failures_20260913.py -v
python3 -B -m unittest discover -s tools/tests -p test_scoped_desktop_fixes.py -v
python3 -B -m unittest discover -s d-i/forky/tests -p test_dbus_broker.py -v
python3 -B tools/check_shells.py
python3 -B tools/check_preseeds.py
python3 -B tools/build.py --check
python3 -B validation/boot-runtime-second-pass-2026-09-13/verify_native_units.py "$PWD"
python3 -B validation/boot-runtime-second-pass-2026-09-13/verify_payload.py "$PWD"
```

The account-copy ownership regression requires root; this execution was root and
that test did run. On a production-like test host with real Perl dependencies,
omit `MANAGED_TEST_PERL_ADAPTER=1` to test the real Moo-based constructors instead.

### Validation limits

Moo and the required Moo extensions were unavailable in this container, and
package downloads failed because container DNS/network access was unavailable.
The Perl behavioral tests explicitly used their test-only constructor adapter.
The production modules and runner control flow were executed, but AppArmor mode
editors, kernel state and network sysfs state were fixtures. The native parser was
used for names-only inspection in the new regression; that does not establish
kernel enforcement correctness. The adapter is in tests only and is not included
in the installed payload.

Native systemd checks validate the unit syntax/dependencies supplied to the test
root, not the complete live target graph or user-manager execution. No fresh
Debian installation, physical GPU hotplug, real network device arrival, running
greeter multimedia session, or Wayscriber launch was performed. These limitations
must not be confused with passed hardware acceptance tests.

This pass ran selected scoped and integration regressions, not every historical
repository test. The earlier report and historical logs remain unchanged; their
broader-suite limitations are not represented here as newly passed tests.

## Packaging and scope

Only two runtime/config sources were changed relative to the previous delivery:
`LoadedState.pm` and Wayscriber's `config.toml`. Changes to two existing test files,
one new integration-test file, three generated installer products, this report,
and the accompanying evidence complete the second-pass changes.

Existing repository file modes are preserved relative to the delivered tarball.
Safe extraction stripped group-write bits in the temporary working copy; those
were restored from the input archive before packaging rather than introducing
unrequested permission changes. No additional source file was removed this pass.
Relative to the original user ZIP, the only deliberately removed file remains
`managed-nvidia-char-links.path`.

The source patch and inventory in `validation/boot-runtime-second-pass-2026-09-13/`
show the exact additional changes. The original reports and all unrelated source
files are retained. Payload tests and audit evidence are repository artifacts,
not installed target runtime files.

Publish the complete updated repository atomically. Do not serve the new preseed
with the previous payload or manifest; their pinned hashes changed.

## Installed-host acceptance checks still required

After an installation from the updated repository, review the current boot:

```sh
sudo journalctl -b -u managed-nvidia-char-links.service --no-pager
sudo systemctl show managed-nvidia-char-links.service   -p StartLimitIntervalUSec -p StartLimitBurst
sudo /usr/local/libexec/managed-nvidia-char-links --check
sudo systemctl status managed-nvidia-char-links.path

sudo /usr/local/libexec/apparmor-managed-modes-run --check-loaded
sudo journalctl -b -u apparmor-managed-modes.service --no-pager
sudo systemctl show bootprofile-apply.service -p ActiveState -p SubState -p RemainAfterExit
sudo systemctl cat managed-network.service
sudo journalctl -b -u managed-network.service --no-pager
```

The removed `.path` unit should be reported as not found. Bootprofile should be
`active (exited)` after success. The AppArmor log should show no unnecessary
reconciliations for already matching sources/kernel state. Review the configured
greeter account's user-manager journal to confirm neither PipeWire socket/service
pair nor WirePlumber started, and check the primary account's Wayscriber file and
launcher summary. A deliberate bootprofile restart can be used to test intentional
reapplication, but is not included above because it changes live tunables.

## External references checked

The implementation findings above come from repository inspection and execution.
The references below were used only to verify external interface semantics and
the Wayscriber controls, not as substitutes for testing the supplied code.

- Debian `systemd.device(5)`: https://manpages.debian.org/testing/systemd/systemd.device.5.en.html
- Debian `systemd.service(5)`: https://manpages.debian.org/testing/systemd/systemd.service.5.en.html
- Debian `systemd.unit(5)`: https://manpages.debian.org/testing/systemd/systemd.unit.5.en.html
- Debian `systemd-udev-settle.service(8)`: https://manpages.debian.org/testing/systemd/systemd-udev-settle.service.8.en.html
- Wayscriber upstream example: https://github.com/devmobasa/wayscriber/blob/main/config.example.toml
