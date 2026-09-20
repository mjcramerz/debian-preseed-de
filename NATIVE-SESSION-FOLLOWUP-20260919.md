# Native desktop follow-up - 19 September 2026

> Historical report: the labwc/KWallet source builds and patches described here
> were removed on 20 September 2026. Their custom input and Qt behavior is not
> part of the current installer. See
> [the replacement report](docs/PACKAGED-NATIVE-SESSION-20260920.md).

## Release status

This is the complete source repository based on the preceding
`debian-preseed-de-session-repair-20260919.tar.gz`, not a replacement window-list
application or a partial patch bundle. It retains the previous menu, IOCost,
SSH-unlock, desktop-entry, Waybar and scoped AppArmor changes.

**Not an all-failures-resolved release:** the native input and KWallet repairs
are implemented as source patches and integrated authenticated Debian package
builds. Their complete native package builds and a booted target session were
not executed in this environment. The specific eDP-1 EBUSY event is not proven
resolved on the laptop, and the ELAN touch-jump has no established root-cause
repair in this release. Do not promote this archive to all hosts as a validated
production release before the target acceptance tests below.

This document supersedes the earlier report's window-list workaround. Earlier
reports and their validation evidence are retained as historical records, not
claims about the new native switcher.

## Native thumbnail switcher

The panel helper still sends exactly one F13 press/release using `wtype`. It
does not hold a synthetic Alt/Super modifier, keep an input helper alive, launch
a second switcher, or use a `ShowMenu` client list. F13 invokes native
`NextWindow`; the existing renderer defaults to thumbnail style. Existing
workspace/output filters and Alt-Tab bindings remain in place.

The installer patches labwc's native implementation, rather than pretending
that a different menu fixes its input handling:

* On a modifierless cycle start, retain the active eligible view selected by
  labwc. CapsLock and NumLock do not count as shortcut modifiers. A shortcut
  with Alt/Ctrl/Shift/Super still advances normally. When the active view is
  excluded by native filters, labwc's first eligible view remains selected.
* Capture both halves of a click begun while the OSD is open. Do not send those
  clicks, ordinary motion, client drag bindings, or scroll actions to Waybar's
  stale pointer focus. A client press begun before the OSD is still allowed its
  matching release without selecting a thumbnail.
* Left-clicking a thumbnail selects it. An outside click or another mouse
  button dismisses the OSD without activating the underlying application.
  The next ordinary click works normally; dismissal deliberately does not
  click through to a potentially destructive control.
* Enter/keypad Enter accepts, Escape cancels through the existing handler, F13
  cancels an already-open switcher, and wheel movement advances the native
  selection. Existing arrow and Alt-Tab operation is retained.

The exact green theme entries are:

```text
osd.window-switcher.style-thumbnail.item.active.border.color: #50C878
osd.window-switcher.style-thumbnail.item.active.bg.color: #50C87826
```

The background alpha is 38/255 (approximately 15%). This colors the selected
thumbnail card, not the entire compositor or the application content. These
are native labwc theme keys. Waybar's previous icon alignment and hover styles
are retained. Optical appearance and pointer interaction still require a real
Wayland session; the C fragment harness is not a screenshot or a GUI test.

Files: `hooks/target/etc/skel-desktop/.config/labwc/{rc.xml.tmpl,themerc-override}`,
`hooks/target/usr/local/bin/labwc-window-switcher`, and the new native source
patcher under `hooks/target/usr/local/share/labwc/native-repairs/` (all relative
to `d-i/forky`). The installer verifier now rejects the previous F13 list-menu
substitution.

## Output ownership and atomic-commit handling

`labwc-output-watch` now submits a changed multi-output fallback topology in
one wlr-randr transaction instead of a sequence of per-head writes. Unchanged
fallback plans issue no mode-setting transaction. An idle restore compares the
actual current geometry first and does not reapply an already-restored mode;
changed heads are restored together. Missing heads are detected before writes.
A rejected transaction retains its diagnostic and is not immediately replayed
against the same stale snapshot. A later reconciliation reads fresh state.

When Kanshi is configured, the output watcher treats that configuration as the
authority decision. It no longer falls back to its own mode writes merely
because the Kanshi service is activating, restarting, or temporarily inactive.
Idle power/restore operations publish an owner-private runtime pause marker and
synchronously stop Kanshi before mutation. Its launch helper respects the
marker. The existing refresh lock serializes these coordinator operations;
Kanshi is resumed only after the idle snapshot is cleared, and error cleanup
preserves the original failure. Session shutdown does not restart it.

**Causal limit:** all 13 supplied profiles explicitly set
`LABWC_ENABLE_KANSHI="false"`. A journal entry saying the service started does
not establish that its gated wrapper kept a Kanshi daemon running. The observed
18:12:42 EBUSY therefore cannot honestly be attributed to two confirmed live
Kanshi/watcher writers from these materials. The batching and no-op changes are
valid corrections, but they do not prove the reported kernel/driver event is
gone. Manual wdisplays and arbitrary third-party clients are not brought into
a new universal output-authority protocol by this patch.

No blanket legacy-DRM switch, DRM log suppression, random driver parameter,
global compositor restart, or blind atomic-ioctl retry was added. The existing
scanout/cursor policy was retained.

## KWallet/Qt repairs

The authenticated KWallet source build applies four narrowly scoped changes:

1. Replace a QWizard field registered against a QWizardPage with no writable
   value property with an explicit QObject dynamic property containing the
   selected GpgME key. Empty selection or a missing item clears that property;
   the null item is never dereferenced.
2. Make the GPG page's `validateCurrentPage()` depend on a complete page and a
   valid selected key, instead of unconditionally returning false. This is
   necessary for Finish to complete the GPG wallet wizard.
3. Remove only the translated Designer placeholder containing an unfilled
   `%1`. The constructor still supplies the real translated text with the
   escaped wallet name.
4. On Wayland, configure a native application-modal/nonmodal top-level dialog
   as appropriate, instead of treating a foreign numeric X11 WId as a usable
   parent. The existing X11 branch is retained. This is not cross-client
   xdg-foreign parenting or a guarantee of activation/focus on every compositor.

Encryption backends, key-trust filtering, password checking, GPG pinentry,
wallet contents, cancellation and user consent are not disabled. No wallet is
automatically created with an empty password. Full Qt/GPG runtime validation
remains required.

## Authenticated package build and private-only Xwayland

New support files are `patch_sources.py` and `build_native.py`. The desktop role
runs them before its existing private-Xwayland installation/purge step.

The builder derives deb/deb-src entries only from already configured network
sources authenticated by the Debian archive keyring. It rejects insecure source
options and does not invent a mirror, enable unauthenticated APT, modify global
APT sources, add a package hold, or download an arbitrary binary. It requests
source matching the installed binary's source package and source version.

Build dependencies are installed through authenticated APT. Source extraction,
patching, changelog updates and compilation run as a dedicated temporary
unprivileged account, additionally under `setpriv --no-new-privs`. Root does not
execute source-tree Python or shell build code. Commands use argument arrays,
finite deadlines and owned process groups. A pre-existing build account or
unsafe staging path fails closed. Failed build evidence is retained root-only.

Every source replacement must have exactly one expected context. All contexts
are checked before source files are written. Changed layouts, missing source
versions, missing dependencies, or build failures stop installation rather than
silently falling back to the broken binary. Reviewed contexts came from labwc
0.20.2 and the KWallet ksecretd sources referenced below; this is not proof of
compatibility with every future Debian source revision.

The local package version adds `+managed20260919.2`. The main binaries and any
already-installed companion packages produced by the same source build are
installed together, preserving exact-version KWallet dependencies. A root-only
receipt at `/var/lib/managed-native-repairs/receipt.json` records source versions,
artifact hashes, patcher hash, installed versions and hashes of labwc/ksecretd.

The labwc build forces `HAVE_XWAYLAND=0`. The existing, separate Cage/private
Xwayland runtime is not rebuilt or weakened. Public Xwayland may be required
transiently by Debian build dependencies; the existing subsequent installer
step purges it and verifies the public executable is absent. The installed host
compositor has no Xwayland startup path. Zoom/Discord retain their private
compatibility runtime and existing isolation rules.

**Operational costs/limits:** these are source builds during installation, not
prebuilt packages delivered in this archive. Build dependencies remain installed;
no unsafe blanket autoremove was introduced. Future Debian upgrades can supersede
the local versions; do not interpret the receipt as an apt pin. Review/rebuild
these repairs for the new source before relying on the behavior after an upgrade.
A failed staging directory requires inspection and deliberate cleanup before
retry, not silent reuse of half-written state.

## ELAN and other remaining diagnostics

The supplied ELAN line says libinput detected and discarded a touch jump on
`ELAN06FA:00 04F3:3140 Touchpad`. The log contains neither the raw input sequence
nor the device's axis descriptors needed to establish the cause. Upstream Linux
already lists ELAN06FA in its forced-100-kHz ACPI I2C handling; that existing
quirk addresses reported excessive smoothing and is not evidence that it fixes
this particular jump or that the supplied XanMod kernel lacks it.

**No root-cause ELAN fix is claimed or fabricated.** The existing bad-jump
filter remains enabled. No generic threshold override, I2C unbind/reset loop,
input-device disabling, guessed firmware update, or suppression of the libinput
error was introduced. Reproduce with a `libinput record` capture of this exact
touchpad only, plus the kernel/libinput versions and device descriptors. Do not
record the keyboard or an unrestricted set of input devices.

Earlier log families remain accounted for: missing Bluetooth identity may be
initialization state rather than a persistent fault; EVIOCSKEYCODE EINVAL still
needs the actual device/scancode evidence; the VS Code log explicitly says its
extra flags are forwarded; Tailscale warm-up later recovers in the original log.
No fake identity files, command-line policy weakening, or blanket warning
filters were added to make an empty journal appear to be a repaired system.

## AppArmor

The earlier seven normalized missing-permission groups from the supplied audit
are preserved. This follow-up adds only the runtime directory/marker reads to
the existing managed Kanshi wrapper profile. Output-watch already has its
scoped runtime-state and systemctl permissions. No unrestricted filesystem,
ptrace, execution or Xwayland allowance was added.

All 35 shipped top-level policies compiled in the offline integration check.
The supplied profiles' complain/enforce choices were not changed. Compilation
is not an enforce-mode workload test, and neither this report nor the package
claims universal enforced coverage.

## Validation and evidence

Evidence is in `validation/native-session-followup-20260919/`.

| Check | Outcome |
| --- | --- |
| New native follow-up tests | 24 passed |
| Existing targeted installer suites | 255 discovered: 252 passed, 3 skipped |
| Tool tests, one isolated process per module | 179 passed across 9 modules |
| Shell syntax/dependency scan | 282 files, 575 parser checks, passed |
| Offline AppArmor native parser | 35 top-level policy files compiled |
| Rebuilt installer payload | 1,377 files; build/check passed |
| Native debconf/preseed checks | 59 files; four generated command values preserved |
| Whole-tree shell/Python syntax and inventory | Passed; inventory-only items are not runtime tests |

The C test compiles and executes the exact injected input-handler fragments with
C11, warnings-as-errors and UBSan, using small seat/view stubs. It tests current
selection, lock modifiers, Alt-Tab, press/release pairing, thumbnail acceptance,
outside cancellation, scroll and keyboard acceptance. It is not a full labwc
build. Perl tests execute the real main-package policy functions with external
endpoints stubbed; the full Moo-based CLI is not exercised here.

Three explicit skips: desktop-file-utils, the required Python GIO/GioUnix
binding, and fzf were unavailable on the test host. The all-modules-in-one-process
tool sweep exceeded the 200-second execution limit. Each of its nine modules
then passed independently; the timeout and original log are retained, not
renamed into a successful combined run. Initial stale verifier/assertion/hash
failures were corrected and re-run; the result history retains those attempts.
No broad historical all-repository test sweep is claimed green.

A complete authenticated Debian labwc/KWallet package build, actual d-i boot,
GPU modesetting, the ELAN device, real thumbnail rendering, actual KWallet
secrets, Bluetooth pairing, and AppArmor-enforced desktop use were **not** tested
in this container. The delivered source tree and its generated installer
products are complete; hardware and full native-build acceptance is not.

## Deployment and acceptance

Publish `payload.tar.gz`, `payload.manifest`, `preseed.cfg`, and the accompanying
repository together through the existing serving workflow. This is a rebuilt
installer source repository, not a tested live-session upgrade script. First
use an expendable installation of the affected hardware/profile.

Before wider rollout, require: both native package builds finish and the receipt
matches installed binaries; no `/usr/bin/Xwayland` or host Xwayland session;
Zoom and Discord private runtimes still start and stop cleanly; F13 opens
thumbnails with the current eligible view and the green selection; repeated
thumbnail/outside/Waybar clicks do not stick; Alt-Tab still advances; KWallet
GPG Finish, cancel, unlock and stored-secret access all work; hotplug, suspend,
DPMS and manual display configuration do not produce recurring atomic failures;
and the touchpad's reproduced sequence no longer contains the fault before
calling the ELAN objective resolved. Also repeat the desktop workload with the
intended AppArmor enforcement state and inspect new audits rather than inferring
coverage from parser success.

## Primary source references

- labwc native input and cycling: `https://github.com/labwc/labwc/tree/0.20.2/src/input`,
  `https://github.com/labwc/labwc/blob/0.20.2/src/cycle/cycle.c`
- labwc native thumbnail theme: `https://labwc.github.io/labwc-theme.5.html`
- KWallet implementation: `https://github.com/KDE/kwallet/tree/master/src/runtime/ksecretd`
- Debian source/binary relationship: `https://packages.debian.org/sid/kwallet6`
- libinput touch-jump explanation: `https://wayland.freedesktop.org/libinput/doc/latest/touchpad-jumping-cursors.html`
- Linux ACPI I2C quirk: `https://github.com/torvalds/linux/blob/master/drivers/i2c/i2c-core-acpi.c`

Upstream copyright and the licenses marked in each file remain applicable.
