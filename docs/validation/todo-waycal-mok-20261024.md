# Log, Waycal hover and first boot MOK corrections — 2026-10-24

> Earlier October 24 snapshot. The user's later instruction replaces hover
> with right-click Waycal toggling and middle-click format switching. Current
> implementation, current saved-log dispositions and replacement artifact
> hashes are recorded in [Waycal click mapping and theme](waycal-click-20261024.md).
> The fingerprints, logs and acceptance table below describe the earlier tree.

## Scope and evidence

The three requested objectives were handled in order: saved log failures and
the explicit AppArmor denial, Waybar **0.15.0** / Waycal hover and clock clicks,
then the first boot MOK countdown and duplicate automatic entry.

Base revision: `e1f929c73033bfed247e51b90a2574880503c786` on `mcr/main`.
The checkout was clean when work started. The target contract remains Debian
Forky, Python 3.14 and systemd 262; no development-host package or service state
was used as target evidence. No application was compiled or deployed.

Changed source fingerprint, including the four changed fixture files and
excluding the three generated products and documentation: 10 paths,
`eeab31f85b035e8956f4560377e40d1512448dd9017de92693006ae2783db52e`.
Changed fixture fingerprint: four paths,
`035a9d92ed7435db21093211eac6214de5cef5defc8a884aff1f51f63f7e8287`.
Each digest covers sorted path, NUL, current bytes, NUL. These identify the
reviewed working tree; they are not runtime acceptance evidence.

No tests, fixtures, shell syntax runners, policy parsers, GUI programs, service
managers or UEFI commands were executed. The repository's mandatory isolation
contract requires an approved disposable target environment for those checks;
none has been supplied for this work. The independent agent reviews could not
start because the agent runtime returned content hydration errors. Source
inspection and final integration were completed by the root agent.

## 1. Supplied logs and AppArmor

All 50 regular files in `todo/` were reviewed as data; 27 are empty. The hidden
`todo/.~` file is an older October 13 journal, distinguished from the October 24
managed logs. The current audit file contains 450 AVC records but exactly one
denied operation. The remaining AVC records are policy status records.

| Evidence | Correction or disposition |
| --- | --- |
| `todo/apparmor`, `managed/security/apparmor/apparmor.log:450` and `managed/security/audit/auditd.log:8168`: Agenda is denied read access to `/proc/10155/cmdline`, where the process PID is also 10155. | Add `owner @{PROC}/@{pid}/cmdline r,` in the Agenda profile only, using the existing procfs convention. Its native launch and confinement remain in place. The saved logs establish the denial; loaded-policy acceptance remains open. |
| Audit syscall 59 returns `ENOENT` while searching for `sh`, `bwrap`, `systemctl` and `dbus-update-activation-environment` in earlier PATH directories. | These records are executable search misses, not additional AppArmor denials. No speculative launcher or PATH change. |
| Agenda writes `GTK-NoCSD: LibHandy not found, will try GModule.` | This reports the library's fallback attempt, without a corresponding application error in the current apps log. The actual denied read above is addressed. |
| CrowdSec reports that the machine is not enrolled in Console. Its local API/bouncer requests return HTTP 200. | Console approval remains an external manual operation. No remote approval, credentials change or disabled synchronization was introduced. The warning remains unresolved until that external enrollment is accepted. |
| CrowdSec's optional qBittorrent log is absent; vendor grok names are registered twice. | No local acquisition failure or bouncer failure is demonstrated. Preserve the optional acquisition and vendor parsers. |
| Fail2Ban creates database version 4, then starts the SSH jail with the verified authentication log. | Normal first startup; no error requiring a policy change. |
| USB-C/UCSI reports unknown error 88 and `UCSI_GET_PDOS failed (-5)`. | Hardware/controller evidence is insufficient to identify a repository correction. No unverified driver, power or firmware workaround. Native hardware investigation remains open. |
| Empty scanner/model/network logs; successful GRUB Btrfs refresh. | Empty logs do not prove acceptance. No invented scan or application result. |
| Older hidden journal: Tailscale machine authorization pending, monitor enumeration fallback and missing public Xwayland. | Historical evidence does not establish a new failure in this snapshot. The current Tailscale helper already handles pending authorization. The requested private Zoom/Discord Xwayland boundary and implementation remain unchanged. |

## 2. Waybar 0.15.0 hover and click contract

The exact upstream [0.15.0 clock implementation](https://github.com/Alexays/Waybar/blob/0.15.0/src/modules/clock.cpp)
uses `GtkTooltip.set_custom` with its own label. GTK's
[tooltip window name lookup](https://github.com/GNOME/gtk/blob/gtk-3-24/gtk/a11y/gtkwindowaccessible.c)
can find a different hidden built-in label first. The previous adapter required
the tooltip window itself to have name `Calendar`; a correctly visible custom
clock label therefore did not satisfy its condition.

The adapter now accepts a showing tooltip containing a visible `Calendar`
label, or a showing `Calendar` label whose ancestor is a showing tooltip. Tree
inspection is limited to 16 nodes, three child levels or four parent steps,
with a 1.5-second matching budget and existing per-call AT-SPI deadlines. The
same-UID executable check still requires `/usr/bin/waybar`. Ordinary panel
labels, hidden labels, hidden tooltips, oversized trees and expired matching
budgets are rejected. Only the fixed `labwc-waycal.service` start request is
submitted, with the existing three-second command timeout and one-second rate
limit. No pointer polling, injection or source compilation was introduced.

Both bar configurations now enable the tooltip explicitly. Their existing
`format-alt-click: 3` remains correct for
[Waybar 0.15.0's button handler](https://github.com/Alexays/Waybar/blob/0.15.0/src/ALabel.cpp):

| Input | Configured result |
| --- | --- |
| Hover | Recognize the clock's custom label and request the existing native Waycal month popup. |
| Left click | Open the GTK calendar dropdown; no format toggle. |
| Right click | Toggle the existing alternate date/week/time format; no secondary command. |

The pre-change payload already contained button 3 in both clock definitions.
The current logs do not include the running target's rendered Waybar config,
so they cannot explain why that installed system reportedly still toggled on
left click. A separate source defect was definite: the optional rendered-config
verifier still required button 1. It now requires button 3, no competing click
actions, and the hover tooltip marker. It also checks the packaged AT-SPI APIs
and Waycal code paths. The separate `verify.sh` module remains outside the
installation entrypoint; this change does not restore its broad installation
audit. The existing asset staging still rejects unresolved installer tokens.

The popup service still runs the pinned prebuilt Waycal 0.2.1 with Monday as the
first weekday and native Wayland. Its pinned
[layer-shell implementation](https://github.com/ForrestKnight/waycal/blob/b9b5abd73fbaebf0756157ad141e509410ff181c/src/main.rs)
uses the top layer, top anchor and on-demand keyboard mode. The existing
session service cgroup owns it. No Waycal binary, release pin, application
startup policy or private Xwayland eligibility was changed.

The existing menu fixture now covers the custom-label shape, hidden/default
label mismatch, ordinary panel labels, hidden tooltips, an oversized tree, a
cycle and an expired deadline. These fixtures were authored but **not run**.
They model accessibility nodes; they do not prove GTK/AT-SPI event delivery.

## 3. One automatic MOK route and a 900-second countdown

The final installer reset now requests `mokutil --timeout 900` after confirming
the reset request. This sets the first boot MokManager keypress countdown.
The separate 15-second subprocess deadline bounds the EFI-variable write; the
existing 30-second reset command deadline and private password input remain.
The supported timeout range is documented by
[Debian mokutil](https://manpages.debian.org/unstable/mokutil/mokutil.1.en.html).
[MokManager's countdown implementation](https://github.com/rhboot/shim/blob/main/MokManager.c)
consumes that firmware variable. It controls the initial prompt, not a forced
900-second termination of the user's interactive management session.

Previously, the installer queued both firmware `BootNext` through shim and
GRUB `next_entry=installer-mok-enrollment`. Shim can enter MokManager before
GRUB runs; the queued GRUB entry survives that visit and creates a second
automatic visit. The automatic GRUB queue helper has been removed. Only the
existing selected-ESP-bound firmware route remains. A failed firmware readback
also cannot queue an alternative, because it may follow a completed write.

The manual GRUB MOK Enrollment entry, certificate on the ESP, native reset and
enrollment choices, once-per-install reset claim and warn/continue behavior
remain. No uncertain reset is retried. A failed timeout write warns explicitly
that the 900-second value was not confirmed; it does not falsely undo or repeat
the reset. Firmware failure retains the manual recovery instructions. The
actual firmware countdown, reset/enrollment interaction and absence of a second
visit still require native UEFI acceptance.

Existing MOK fixtures were updated to expect 900 and to reject any second
automatic GRUB route for both successful and failed firmware handoffs. They
were **not run**.

## Checks performed and generated products

1. `git diff --check`: exit 0.
2. Ad hoc `/usr/bin/python3 -I -S -B -` static data inspection: five changed
   Python source/fixture files parsed with `ast.parse`, plus both changed
   embedded Python blocks in `verify.sh.tmpl`. No repository module was imported
   or executed. The first runtime-block extraction included a shell comment
   containing `import` and failed parsing; using the exact Python start marker
   corrected the inspection command and the actual block parsed successfully.
3. JSON data inspection of both clock definitions: tooltip enabled, fixed
   `Calendar` marker, left-click menu and integer button 3 for format changes,
   without competing click actions. Unrelated installer/theme tokens used
   numeric parser stand-ins; the renderer was not executed.
4. Reviewed pure serialization command `make build PYTHON=/usr/bin/python3`:
   exit 0, `built 1836 payload files`. The Makefile, `tools/build.py` and its
   publication helper were inspected before invocation. No validation or test
   recipe was invoked by generation.
5. Ad hoc standard-library archive/hash inspection: all 1,836 members,
   34,897,350 expanded bytes, match the current source and manifest; member
   metadata matches serialization policy; archive and manifest pins match
   generated preseed. The expected complete source member set also matches.
6. Completion review identified that the root inventory pair still pinned the
   prior payload. After reviewing `Makefile`, all of `tools/inventory.py`,
   `tools/inventory_apt.py` and the publication helper, ran the separately
   permitted generation command:
   `/usr/bin/timeout --signal=TERM --kill-after=20 1800 make inventory PYTHON=/usr/bin/python3`.
   It exited 0 after acquiring 29 Release records and completing 97 index jobs,
   retaining 21,381 package candidates with zero acquisition errors. Discovery
   read 1,836 archive members as data, with 1,806 text files and 353 relevant
   files. This was public HTTPS metadata acquisition and generation, not an
   APT invocation, package installation, installer execution or test.
7. Ad hoc `/usr/bin/python3 -I -S -B -` JSON/hash inspection confirmed both
   root inventories identify the current payload, `apt_metadata_sha256`
   matches the exact paired snapshot, repository scope matches, and every
   direct/dependency/preferred candidate reference is valid and consistent.
   All 693 direct requests have candidates; missing selectors remain an empty
   list. These are indexed candidates, not a verified dependency transaction.
   The three payload product hashes remained unchanged by inventory generation.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `c1a81a41b255084f09d8cb3f33147c53a64913aa240d88e5d8fa269d1467f3fd` |
| `d-i/forky/payload.manifest` | `8c15bdce04ba02055066bbfe0016846e097fed876b4445d38d5f88067af95cf7` |
| `d-i/forky/preseed.cfg` | `c06eb0539f728b5776bf596b756d5da5631a1d5a195af9ddaac0491971aae4ee` |
| `inventory.json` | `53c2b397f0cdf7acead85068fcf5768ccd021c865ccb17aa44a9cff93f990eca` |
| `inventory-apt.json` | `4cd90bcd65ce4f53bdc870b5eef642d2ca86edadc03645d50137970fc2adb316` |

The initial payload build left the root inventory pair stale. The continuation
above corrected that gap using the documented build-then-inventory generation
sequence. Both now pin payload
`c1a81a41b255084f09d8cb3f33147c53a64913aa240d88e5d8fa269d1467f3fd`.
The collector checks HTTPS transport and Release/index SHA-256 consistency;
it does not perform OpenPGP verification, and the generated trust fields retain
that limitation. Downstream package consumers must authenticate metadata.

Serialization and inventory consistency do not prove a successful installation,
loaded AppArmor policy, GUI interaction or firmware operation. The full goal
remains open pending native target evidence and the external log dispositions
above. No approved disposable target image or access details have been supplied.

### Remaining acceptance evidence

| Requirement | Current evidence | Missing evidence |
| --- | --- | --- |
| Agenda denied command-line read | Scoped source permission and current payload bytes | Target AppArmor compile/load and native Agenda startup without this denial |
| Waycal popup on clock hover | Waybar 0.15.0 custom-label handling, fixed service dispatch, configured layer-shell binary | Actual GTK/AT-SPI showing event delivery and visible Waycal popup in a disposable native Wayland session |
| Left click never toggles; only right click toggles | Both JSON clock definitions use integer button 3, left-click menu only, and a corrected optional verifier | Rendered target configuration and repeated native left/right click interactions |
| MOK initial prompt waits 900 seconds | `mokutil --timeout 900` source and rebuilt payload | Actual target EFI variable write and observed firmware countdown |
| No second automatic MokManager entry | Only the firmware route remains; automatic GRUB next_entry writer removed | Native first boot/reset/enrollment/reboot sequence, including firmware failure behavior |
| Existing native launches and private Zoom/Discord behavior | Unchanged implementation/eligibility paths in this diff | Native launch/shutdown regression checks in disposable targets |
| Published generation identifies one payload | Archive/manifest/preseed data comparison and current paired inventories | Completed as data consistency only; no deployment claim |

## Exact changed paths

```text
d-i/forky/hooks/target/etc/apparmor.d/calendars
d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl
d-i/forky/hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl
d-i/forky/hooks/target/usr/local/libexec/labwc-waycal-hover
d-i/forky/scripts/desktop/verify.sh.tmpl
d-i/forky/scripts/late/grub.sh
d-i/forky/tests/test_comprehensive_contracts_20261017.py
d-i/forky/tests/test_desktop_sandbox.py
d-i/forky/tests/test_installer_hardening.py
d-i/forky/tests/test_native_menu_contract_20260920.py
d-i/forky/payload.tar.gz
d-i/forky/payload.manifest
d-i/forky/preseed.cfg
inventory.json
inventory-apt.json
docs/calendar-and-wifi.md
docs/validation/todo-waycal-mok-20261024.md
```
