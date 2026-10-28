# Desktop dispatch and Wi-Fi firstboot follow-up

Date: 2026-10-28. Base revision: `d314d93b0c766e9d7837217cbaa8925ee894dfb3`.
This report describes the uncommitted changes listed below and the current
`todo/` capture. Earlier reports describe different captures and revisions.

## Confirmed failures and source changes

| Failure | Supplied evidence | Change and integration |
| --- | --- | --- |
| WIN and WIN+ALT menus do not open | `todo/managed/security/apparmor/apparmor.log:452-457` contains six denied executions of `/usr/bin/systemd-run` by `labwc-compositor`, with `profile transition not found`. | Add an exact `rix` rule for that controller in the compositor profile and access to the owning user's `/run/user/<uid>/systemd/private` socket. The controller inherits compositor confinement and its session environment. The existing release bindings for `Super_L`, `W-Alt_L/R` and `A-Super_L/R` already submit the intended menu delegates through transient user services. |
| Wayscriber button fails | `todo/journalctl:1380-1384` starts the toggle service, then the helper rejects `XDG_RUNTIME_DIR`. The native daemon previously started successfully. | Remove the incorrect requirement that the runtime **directory** have exactly one link. Keep the exact UID-specific path, no symlink, directory type, owner and mode 0700 checks. Socket and PID record link checks remain. Both Waybar instances and the direct keyboard actions use this helper. |
| Wi-Fi firstboot fails | `todo/journalctl:591-596` reports `BlockingIOError`. The automatic retry at `1325-1331` loads the same profile and finishes successfully. | Wait up to 45 seconds for the existing shared Wi-Fi lock during firstboot. Dispatcher and carrier hooks remain nonblocking and advisory. Interactive configuration reports a busy operation. A lock deadline now produces a specific diagnostic instead of blaming credentials. |
| Firstboot wait must fit its service budget | The firstboot path can load and modify the profile, then reconcile Ethernet preference. | Increase the whole-service start deadline to 240 seconds: 45 seconds for the lock plus at most 158 seconds for the six possible NM subprocess timeouts (32+32+15+32+15+32), with margin for local file work. `KillMode=control-group` and the separate 10-second stop budget remain in place. |

The exact controller rule retains the generic application transition rule.
Its intended precedence follows the
[upstream AppArmor explanation of exact execution matches](https://lists.ubuntu.com/archives/apparmor/2020-August/012143.html).
The profile was inspected as text; it was not compiled or loaded here.

Staging was traced through `scripts/desktop/components/target-assets.sh`,
`scripts/desktop/components/user-session.sh`, `scripts/desktop/components/services.sh` and
`scripts/late/security.sh`. The helper destinations remain executable mode
0755; the system service, native user-service drop-in and AppArmor source remain
mode 0644. The existing installation verification boundary checks the helper
paths and the menu/button command contracts. No service was activated here.

The Wayscriber daemon remains owned by its packaged user service and the managed
session drop-in. The wrapper still starts that service once, waits for its
readiness record, and sends one native toggle. An uncertain response returns 75
without retrying the non-idempotent request. The supplied capture does not
establish the exact installed Wayscriber package version; native compatibility
with this readiness protocol remains unverified.

## Unexecuted regression fixtures

The previous Wayscriber fixture still rewrote and invoked the retired shell
implementation. It has been replaced by selected-function fixtures using mocked
filesystem metadata, environment, process calls and clocks. No stub program,
socket, production lock or manager connection is created by the new cases.

The authored cases cover:

- Runtime directory link counts 2, 8 and 32; wrong owner, mode, type, path and
  symlink rejection; retained socket alias and ownership rejection.
- Start/readiness failure without a toggle, exactly one native toggle after a
  reply failure or timeout, status 75, bounded subprocess cleanup dispatch and
  explicit argument arrays.
- Contention followed by lock acquisition, the bounded boot lock deadline,
  nonblocking advisory hooks and interactive behavior, no retry on permission
  failure, closing the lock and reaching firstboot only after acquiring it.
- The required compositor controller and manager-socket rules in the existing
  desktop policy fixture. The older generic menu fixture now expects `Popen`
  for this Python helper.

All fixture source remains **unexecuted**. AST parsing does not establish that
the fixture assertions or the implementation pass at runtime.

## Other captured diagnostics

| Diagnostic | Disposition |
| --- | --- |
| `eDP-1: Atomic commit failed: Device or resource busy` at 11:05:28 and 11:06:14 (`todo/journalctl:1336,1376`) | **Unresolved.** The capture does not identify the submitted output/gamma state or the client responsible. Output reconciliation source already defers stale state and avoids replaying unchanged topology. The managed wlsunset controller reports `disabled by policy` at `todo/journalctl:1245`; changing that inactive managed client is unsupported by this evidence. Neither timing nor proximity to a user action establishes a repair. |
| Missing global `/usr/bin/Xwayland` (`todo/journalctl:1174-1175`) | Consistent with the existing private two-application Xwayland policy. The compositor continues. No Xwayland package or policy change was made. |
| CrowdSec console synchronization before enrollment | The capture subsequently records CAPI registration complete and console enrollment pending approval, then successful bootstrap (`todo/journalctl:1289-1301`). Console approval is external state, not evidence of a launcher or Wi-Fi defect. |
| ACPI/UCSI firmware errors | Hardware/firmware errors remain outside the demonstrated source defects; no firmware or driver change is justified by this capture. |
| Mullvad installer profile reload warning | The offline installer has a deferred policy activation path in `scripts/late/mullvad.sh` and `mullvad-apparmor.service`. No development-host policy operation was used to suppress the warning. |

The supplied target evidence identifies systemd `262 (262-1)` in
`todo/installer-state/logs/firstboot/data/systemd-version.txt`, NetworkManager
`1.58.1` at `todo/journalctl:415`, and kernel `7.2.13-x64v3-xanmod1` in the
captured kernel log. No development-host package
state was queried. `debian-preseed-de-audit.md` is absent from this checkout;
acceptance is not inferred from unavailable audit material.

## Checks actually performed

1. Inspected current source, its callers, policy and staging, and the relevant
   supplied log records. Independent review agents failed during context
   hydration; their failed turns supplied no findings or validation evidence.
2. Ran `git diff --check`; exit status 0.
3. Ran standalone `python3 -I -B` source-data snippets using standard-library
   `ast.parse` on the two changed Python helpers and three changed fixture
   sources. No repository module, helper or fixture was imported or executed.
4. Parsed the Labwc XML template as data. Inspected the five modifier release
   bindings, transient-service argument boundaries, intended menu delegates and
   cgroup lifetime property. Inspected the controller policy rules as text and
   the firstboot service deadline against the bounded subprocess call graph.
5. Reviewed `Makefile`, `tools/build.py` and `tools/publication.py`, then ran only
   the permitted `make build` serialization recipe. Output: `built 1861 payload
   files`.
6. Read the final gzip/tar archive as a bounded stream without extraction.
   Every one of the 1,861 regular members matched current source bytes and its
   manifest SHA-256. Ownership, mode and timestamp metadata matched the builder
   contract. Expanded content: 19,926,976 bytes. The manifest and archive member
   sets matched the current eligible source inputs. Generated preseed payload,
   manifest and bootstrap source hash pins matched.

| Product or source fingerprint | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `0b525307bb9807c5eb6d458e92c9c131229213d99f0e6f29f7616d64c5de04a5` |
| `d-i/forky/payload.manifest` | `ce6764bdfd40c7ab96396073d894bb684a4930eefe7cad94ef37e1967257b589` |
| `d-i/forky/preseed.cfg` | `37e16ddfc29a82a2cd82bb3df38d1b6df4a83f9e48dd21c542e410ed80c3766d` |
| Four runtime sources below, sorted path/NUL/bytes/NUL | `f288a581d314bb52338a0047c25fe1e3ecaf88d53766b1a994fa7e93518294cf` |
| Three unexecuted fixture sources below, same fingerprint method | `cf1104bb55f98881827f22a46a04ed520e208bfb5e9d5f1b46102cc9ea3c5272` |

## Changed paths and verification limits

Runtime sources:

```text
d-i/forky/hooks/target/etc/apparmor.d/labwc-session
d-i/forky/hooks/target/etc/systemd/system/wifi-firstboot.service
d-i/forky/hooks/target/usr/local/bin/labwc-wayscriber-toggle
d-i/forky/hooks/target/usr/local/libexec/network-wifi-configure
```

Unexecuted fixture sources:

```text
d-i/forky/tests/test_desktop_sandbox.py
d-i/forky/tests/test_fuzzel_python_protocol_20261027.py
d-i/forky/tests/test_menu_apparmor_integration_20260919.py
```

Generated products are the three files in the hash table. This report is
`docs/validation/20261028-desktop-dispatch-wifi-static.md`.

No test or validation runner, native syntax checker, policy parser, service
operation, GUI/Wayland connection, inventory utility, package operation or
disposable environment was run. The generated files are current for this source
snapshot. Nothing was installed, loaded, deployed, committed or published.

The confirmed source fixes and payload integration are complete for this
snapshot. Fresh target evidence is still needed to establish successful boot
reconciliation, the loaded AppArmor behavior, both keyboard workflows and the
Wayscriber interaction. The DRM error remains unresolved. Serialization and
static inspection do not prove the full runtime objective has been achieved.

## Full-objective acceptance audit

The follow-up audit found the declared Wayscriber source is the stable APT
repository in `classes/class-select/role/desktop.cfg`. Neither the supplied
installer log nor journal identifies the installed native package version or
captures a successful toggle after these source changes. The wrapper/service
contract is consistent with the existing integration; native protocol acceptance
remains missing. An attempted upstream source-page retrieval also failed, so
it supplied no additional compatibility evidence.

| Requirement | Current evidence | Acceptance status |
| --- | --- | --- |
| WIN opens the main Fuzzel menu | Release binding, delegate path, exact controller permission and manager socket access inspected; generated bytes match. Old log shows the blocked controller. | Source correction incorporated; successful target interaction missing. |
| WIN+ALT opens Computer Management | Both modifier-release orders and left/right Alt bindings inspected with the same controller contract. | Source correction incorporated; successful target interaction missing. |
| Wayscriber responds to the Waybar button | Both bar commands use the corrected runtime identity helper; daemon service/drop-in and one-request behavior reviewed. | Source correction incorporated; successful target interaction and exact native package evidence missing. |
| Wi-Fi firstboot reconciles successfully | Bounded lock wait, specific failure propagation, shared ownership lock and complete service budget inspected. Old capture succeeds on its later retry. | Source correction incorporated; first-boot success with the new helper missing. |
| AppArmor permits the intended workflows | Six old denials map to the corrected controller path. Source policy inspected as text. | New target policy compilation, loading and absence of relevant new denials unverified. |
| Remaining DRM errors are resolved | Two failures captured; responsible commit/client absent. Managed wlsunset was disabled. Existing topology writer avoids stale and unchanged submissions. | Not achieved; fresh target evidence is required before a justified repair can be selected. |
| Changes are incorporated into the installer | All 1,861 archive members match current sources and manifest hashes; all generated preseed pins match. | Serialization consistency established. |
| Native launch and private Zoom/Discord policy remain intact | Those sources are outside this change set. | Source invariant preserved; native regression behavior unverified. |

The existing `todo/` capture predates the rebuilt artifacts and cannot establish
post-change success. No further specific source correction is demonstrated by
the available evidence. Completion remains unproven pending a fresh capture
from an existing target using this source snapshot; no disposable environment,
host fallback or execution of a prohibited runner is requested or authorized.
