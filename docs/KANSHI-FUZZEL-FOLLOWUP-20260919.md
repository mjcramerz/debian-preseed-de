# Opt-in Kanshi and native Fuzzel menus - 19 September 2026

## Scope and baseline

This complete source tree continues `debian-preseed-de-native-thumbnails-20260919.tar.gz`
(SHA-256 `4fbd84c2ccdcad3ed922567d2fa0861d375496bf1f13c5ef89b42887660c5ce1`).
It changes Kanshi installation/activation and menu presentation/routing only.
The preceding native thumbnail compositor patches, green thumbnail selection,
output coordination, KWallet repairs, private Zoom/Discord Xwayland runtime,
IOCost installation paths, and scoped AppArmor policy remain. This is not an
all-hardware-errors-resolved claim: earlier GPU/ELAN and complete native-package
build acceptance limitations still apply.

## Kanshi is opt-in, including installation

`kanshi` was removed from
`d-i/forky/classes/class-select/role/desktop.cfg`. It is not selected by another
class or host package list. The desktop late-command reconciles the package
before staging desktop assets. Only an enabled policy installs it, through
APT's authenticated configured repositories with no recommendations, no
suggestions and no package removals. Existing true/yes/1/on and false/no/0/off
boolean aliases remain supported; omission defaults to false. Invalid values
fail rather than silently enabling the daemon. All 13 supplied profiles keep
their existing explicit false value.

| Installed target artifact | Enabled | Disabled |
| --- | --- | --- |
| Debian `kanshi` package | Installed | Absent; an existing package is purged exactly |
| `/usr/local/libexec/labwc-kanshi` | Staged | Not staged; known old copy removed |
| Skeleton/account `kanshi.service` | Staged | Absent |
| Its `60-resource-class.conf` | Staged with the base unit | Absent; no orphan drop-in |
| Session `.wants/kanshi.service` link | Account-local relative link | Absent |
| Generated/copied Kanshi configuration | Yes | No new copy; existing inert settings preserved |

The true branch disables vendor global activation before installing the
account-local session contract. The false branch removes the old managed unit,
resource drop-in, helper and activation links in the global, desktop skeleton
and primary-account unit roots. Optional templates remain in the repository so
an enabled profile can still install them; their presence in the source does
not install them on a disabled target.

Cleanup uses exact known content hashes, not filename-only ownership guesses.
All planned owned artifacts are validated before mutation. Modified files,
unknown drop-ins, foreign link targets and symlinked parent directories fail
closed without deleting administrator data. There is no recursive deletion,
APT autoremove or forced dependency override. `dpkg --purge kanshi` refuses
reverse-dependency breakage. Unexpected package-query errors are not treated
as absence. Unknown local Kanshi executables are preserved and cause failure.

Package subprocesses have finite deadlines and an owned process group; signal
or timeout cleanup terminates/reaps descendants instead of leaving an apt/dpkg
child running. The temporary installer helper is removed on success/failure.
This is an installer reconciliation path, not a supported live-desktop upgrader.

A narrow target verifier is now called by the real desktop late-command after
staging/enabling units. `scripts/late/desktop.sh` explicitly fetches and sources
the verification definitions. The historical decision to skip the broad
late-command desktop audit is not changed. Firstboot runs the same Kanshi
package/file/link predicate, checking absence when disabled and the complete
account-local contract when enabled. Runtime wrapper/watcher defaults also
agree that omitted Kanshi policy is disabled.

## Native icons in the main menu

Each application row now carries the effective GIO desktop entry's `Icon=`
value using Fuzzel's native dmenu metadata:

```text
label<NUL>icon<US>icon-name-or-absolute-path<NEWLINE>
```

Fuzzel resolves that theme name or path itself, just as it does for application
search. Names, punctuation, spaces and Unicode in valid icon paths remain data.
Missing/invalid metadata falls back to `application-x-executable`; NUL, newlines,
other protocol controls, overlong values and relative icon paths are rejected.
Categories, navigation, fixed settings and session actions use native theme
names rather than font-glyph prefixes. Main-menu and application-search sizing
remain matched in all 13 profiles. The four rendered menu variants retain the
configured base icon theme and now explicitly enable icons.

GIO remains responsible for XDG desktop-ID precedence, visibility, Hidden and
TryExec behavior, and launching with desktop-entry Exec semantics. Duplicate
application names retain distinct desktop-ID mappings and their own icons.
Neither the label nor icon identifier is interpreted as a shell command. No
new icon-resolution daemon, cache, network lookup or application scanner was
introduced.

## Computer Management and child menus

The desktop entry, main menu and other ordinary invocations now open graphical
Fuzzel without a terminal. `--graphical` makes that choice explicit; `--terminal`
retains the existing controlling-terminal fzf adapter. The desktop entry's
`Terminal=false`, fixed Exec/TryExec and `preferences-system` icon remain valid.

All six management groups and 23 fixed leaf routes are retained and tested:
System & Recovery, Network & Remote, Security & Accounts, Devices & Desktop,
Containers & AI, and Files & Documents. The actual routing catalog is retained
in `validation/kanshi-fuzzel-20260919/management-catalog.json`.

Management exports native-icon mode only to its own child process tree, with
explicit root/child navigation state. Its wrapper now emits native icon
metadata, removes only the old display-only glyph prefixes, and maps a selected
presentation row back to the original exact action label. Back, Close, Cancel
and Exit preserve their existing dispatch semantics. Colliding display labels
are disambiguated; injected metadata controls and multirow selections fail.
Explicit text-input paths remain available for the existing validated forms.

All group/leaf entries have specific native theme identifiers. Existing child
menu icon classification is converted to native themed names as well. These
are identifier/protocol checks, not a claim that every third-party icon file or
its optical appearance was inspected in a running desktop.

The action table still consists of fixed argv vectors. Existing privilege
separation, confirmations, input validators and action endpoints are retained.
Managed terminal actions keep the action-wait contract so the next menu does
not steal focus while the action is running. AI & Copilots uses its normal
managed-terminal entry from the graphical menu, and receives `--terminal` only
when invoked from the explicit terminal management mode. Its specialized
terminal UI is not replaced with a new graphical implementation.

No AppArmor allow rule, authentication bypass or unrestricted execution rule
was added for these presentation changes. Existing main-menu, management,
Fuzzel, terminal and action profile boundaries are retained. Offline compilation
is not proof of enforce-mode runtime authorization.

## Validation

See the raw logs and machine-readable results under
`validation/kanshi-fuzzel-20260919/`. Package commands are mocked in disposable
filesystem tests: no real target APT transaction or service start is claimed.
Native icon roundtrips use a controlled Fuzzel protocol endpoint, with separate
real GIO C-library discovery tests. They are not Wayland rendering tests.

| Check | Result |
| --- | --- |
| New Kanshi/menu/loader regressions | 37 passed |
| Categorized menu | 40 discovered: 38 passed, 2 explicit dependency skips |
| Desktop navigation | 36 discovered: 35 passed, 1 fzf skip |
| Menu/AppArmor integration | 27 passed, including all 35 top-level policy compilations |
| Session repair/profile geometry | 11 passed; all 13 profiles rendered |
| Previous native thumbnail/output/KWallet repair harness | 24 passed |
| Workload/resource policy | 16 passed; historical checksum fixture retained |
| Additional resource refinements / desktop overrides / workspace / resctl | 9 / 30 / 27 / 23 passed |
| IOCost rerun with an adequate suite budget | 37 passed |
| Green targeted modules, latest runs | 314 passed, 3 skipped (317 discovered) |
| Independent tool modules | 179 passed across 9 isolated module runs |
| Broad historical desktop sandbox | 68 passed, 1 skipped, 1 missing-fixture assertion failure |
| Shell syntax and generated shell boundaries | 282 files; 575 parser checks passed |
| Native preseed/debconf format and read-back | 59 files passed; four command values preserved |
| Rebuilt serving payload | 1,378 files; build/check passed |
| Whole-tree non-executing source audit | Passed; inventory-only entries are not runtime tests |

The three green-suite skips are missing desktop-file-utils, the Python
GioUnix binding, and fzf. Real GIO C-ABI discovery is tested separately. The
historical sandbox's additional skip is missing rsyslogd. Final archive
byte/mode comparison and extraction verification are in the separately supplied
`kanshi-fuzzel-package-verification.json`.


The broader historical suite is not represented as entirely green. The
`test_desktop_sandbox.py` historical incident test requires `todo/apparmor.log`,
which is absent from the supplied baseline archive; the original unchanged
assertion remains. Initial old glyph/terminal-only expectations were updated to
the requested behavior. The immutable original workload-policy checksum fixture
was not rewritten: only the exact independently hash-checked new Kanshi helper,
its two installer calls and the logger's default are excluded before comparing
original workload bytes. Initial failures and timeouts remain as evidence. The initial IOCost,
bootstrap and debconf aggregate runs reached the runner's 90-second deadline.
The generated HTTP bootstrap was also exercised separately with a 120-second
diagnostic budget: it exited successfully after 66.59 seconds, fetched the
expected five resources, produced the five include paths and published
`preflight.ok`. That is longer than the original unittest's 60-second limit;
it is a distinct diagnostic result, not a relabeled pass for that test suite.
Its stderr was a regular file (zero bytes), so pipe backpressure was not the
cause established by that experiment.

## Deployment and acceptance

Publish the **complete repository** to the existing serving root, including
`d-i/forky/payload.tar.gz`, `payload.manifest` and `preseed.cfg` together. These
products are regenerated and checksum-pinned; mixing revisions is invalid.
Do not run the installer or its package-policy helper in a live desktop session.
Changing a profile and rebuilding applies to subsequent unattended installs;
it is not a live-system migration command.

On a disposable target, verify the default false profile leaves `dpkg-query`
without an installed Kanshi package, `command -v kanshi` finds nothing, and no
Kanshi unit/drop-in/activation link exists in global, skeleton or account unit
roots. With an explicit true profile, verify package installation and one
account-local session service after login. Confirm main/search icons, all six
management groups, child Back/Cancel, representative privileged actions and
terminal wait behavior. Check AppArmor audit under the intended enforcement
mode without weakening policy.

This pass did not boot d-i, run a Wayland session, inspect Papirus rendering,
perform actual enabled/disabled target APT operations, or complete the inherited
native labwc/KWallet package builds. The earlier GPU atomic-commit and ELAN
hardware acceptance blockers are unchanged. The complete codebase is delivered;
these unperformed runtime validations are not reclassified as successful.

## Primary protocol references

- Fuzzel native dmenu icons and cancellation semantics:
  https://manpages.debian.org/testing/fuzzel/fuzzel.1.en.html
- Desktop-entry Icon field, paths and theme-name semantics:
  https://specifications.freedesktop.org/desktop-entry/latest/recognized-keys.html

Repository findings above derive from this code and its tests. The references
support the external protocol contracts, not the outcomes of unperformed target
tests.
