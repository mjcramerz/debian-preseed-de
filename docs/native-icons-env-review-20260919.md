# Native Fuzzel menus and late-command environment publication

Review date: 2026-09-19. Input: the supplied `debian-preseed-de.tar.gz`.

## Scope and retained behavior

This is a complete source-tree delivery, not an overlay. Production changes are
limited to native menu presentation, the Computer Management -> Hardware Tuning
route and its AppArmor transition, and host/runtime environment loading. Host
profiles, storage/partition policy, external release pins, tuning algorithms,
root broker authorization, package selections, and application service lifecycle
policies are not changed. The existing Waybar tuning shortcut is retained.

The upload already contained native-icon support in the main menu and shared
picker, and did not contain an active `icons-enabled=no` override in those paths.
The changes complete that design rather than replace the launcher or introduce
another icon renderer.

## Objective 1: native main-menu icons

`labwc-main-menu` emits UTF-8 rows of the form
`visible label\0icon\x1ficon-name\n`. Application icons continue to come from
GIO's effective desktop entry, with the existing validated fallback. Menu labels
containing protocol controls or invalid Unicode are rejected before the picker
is launched. Exact returned labels, rather than displayed decoration or arbitrary
input, remain the only dispatch keys.

Computer Management, Display, and Audio use `computer`, `video-display`, and
`audio-card`. The launcher/main-menu template now explicitly enables native icons,
as the shared base and management templates already do. The selected
`LABWC_ICON_THEME` is still rendered into the shared Fuzzel configuration; no
hardcoded replacement theme, downloaded image, or per-row icon conversion is used.
No Fuzzel `--override` flag was added: Debian's Fuzzel 1.12 does not support it.
The native newline-delimited dmenu path remains separate from `--dmenu0`.

Font packages and the terminal-only fzf presentation are not removed. Their
presence is not used as a substitute for native icons in graphical Fuzzel menus.

## Objective 2: Computer Management and Hardware Tuning

The new route is:

`Main Menu -> Computer Management -> Devices & Desktop -> Hardware Tuning`

It executes exactly `/usr/local/bin/labwc-hardware-tuning menu` as the desktop
user. The entry is displayed only when the gated client exists and is executable.
The catalogue now has six categories and 24 unique action routes. Existing
hardware/class installation gates are unchanged.

Every category and action has an explicit native icon. Hardware Tuning also has
specific icons for all seven top-level operations, all four profiles for each
of Intel and Nvidia, reset-all, policy handover confirmations, cancellation, and
Back. The client explicitly selects choice mode and managed icon encoding, so
it behaves consistently when opened from Management or directly from Waybar.
The complete verified mapping and fixed argument vectors are in
`validation/native-icons-env-20260919/menu-icon-inventory.json`.

The management profile includes a new optional, hardware-gated AppArmor bridge:
`abstractions/managed-hardware-tuning-management-parent`. It grants only the
strict `rPx` execution transition to the installed tuning client and the matching
child-completion signal permission. The client has the reciprocal signal rule.
No unconfined fallback, sudo launch, shell execution, or new kernel-control
permission is added to the graphical menu. Mutating tuning operations still go
through the existing broker and policy-ownership confirmations. The menu returns
to the same management category after an action.

## Objective 3: complete environment publication and error propagation

Previously, composite fetching truncated `host.env` before all required fragments
were fetched. A late failure could leave a nonempty partial file, which later
`-s` cache checks would accept. A failed fetch now cannot replace the previous
complete file.

The composer runs in a subshell to contain its variables and traps, stages under
a private same-directory temporary directory, validates every nonempty fragment
with `/bin/sh -n`, inserts newline boundaries, validates the composed file, sets
its final mode, and then renames it into place. It rejects symlink/nonregular
file destinations, cleans up on errors and handled termination signals, and identifies the failing
fragment without logging its values. There is no new Python dependency in d-i.
The installer runtime directory remains an installer-owned trust boundary.

The order remains profile -> identity -> runtime defaults -> common layout ->
family layout -> boot. All 13 real profiles have been resolved, fetched, composed,
and sourced with fresh strict shells; both dash and BusyBox ash were exercised.
No profile value or partition sizing default was altered.

`late_command_load_runtime_env` now explicitly propagates errors from profile and
runtime library loading, saved runtime environment loading, layout/capture/write,
context setup, and system identity setup. This also works when a conditional or
OR-list caller disables normal shell `errexit` behavior. The saved runtime state
path now comes from `installer_runtime_state_dir` instead of hardcoding the
default state directory. The legacy `/tmp/install-env/runtime.env` preference is
preserved.

A before/after fault-injection check against the actual uploaded source is
recorded in `validation/native-icons-env-20260919/regression-sensitivity.json`:
failed final-fragment fetches previously changed the existing host environment;
now they preserve it. A conditional layout failure previously continued to
success; now it returns the original injected status 37 before later work.

## Regression maintenance and limits

The new tests exercise native byte protocol, exact action mappings, availability
gates, confirmations, cancellation, AppArmor staging, all-fragment fetch failure,
empty/malformed fragments, file/append/publish failures, strict profile sourcing,
and runtime load/capture/context failures. Existing tests were updated for the
new route count and optional bridge.

Three pre-existing test contracts were stale relative to the supplied implementation:
the Podman terminal wrapper already uses synchronous `subprocess.run`, app scopes
already have a separate resource-class drop-in, and the desktop module list
already includes `verify` and a separate Kanshi policy installation step. Their
tests now verify those existing contracts; the
corresponding production code is unchanged.

Two raw audit logs referenced by historical tests were not included in the
upload. Only those raw-source comparison checks are skipped when their inputs are
absent; the supplied parsed audit fixture and all independent policy checks are
retained. Four Perl integration tests now explicitly report a missing dependency
rather than claiming a behavioral failure before their code can be imported.
Installed-but-broken dependencies still fail. Other pre-existing capability gates
remain intact. These skips are not passing tests.

Validation here is not a booted Debian installation, an optical Wayland/Fuzzel
check, a loaded-kernel AppArmor enforcement test, or a live Intel/Nvidia tuning
exercise. No disk was partitioned and no target service was activated. External
mirrors and release downloads were not exhaustively availability-tested.
Offline systemd structure checks do not resolve every vendor dependency.
Missing Perl dependencies block some compilation and runtime tests and must not
be interpreted as successful coverage. See the final validation report for
measured totals and every skip/block reason.

## Rebuild, publish, and acceptance

The delivery includes regenerated `d-i/forky/preseed.cfg`, `payload.manifest`, and
`payload.tar.gz`. The preseed pins and payload manifest must travel with the same
source tree; do not deploy individual updated files over an old payload snapshot.
Publish the complete directory atomically at the existing seed URL.

From the extracted repository root:

```sh
python3 -B tools/build.py --check
python3 -B tools/check_preseeds.py
python3 -B tools/check_shells.py
python3 -B tools/validate.py --output-dir validation/local-rerun --test-timeout 900
```

A full validation host needs the repository's documented test tools, including
BusyBox, AppArmor's parser/system abstractions, and Perl's `libmoo-perl`,
`libmoox-strictconstructor-perl`, and `libmoox-types-mooselike-perl` dependencies.
Review actual skip/block reasons for other missing optional tools.

Before broad deployment, boot representative Btrfs, VM, and F2FS profiles in a
disposable installation environment. Confirm the selected theme in a real Labwc
session, exercise menu/Back/Escape behavior, and check the target audit journal
for the management-to-tuning transition. Hardware mutations require controlled
validation on the intended hardware, not a desktop-menu test fixture.

## Protocol references

- Debian Fuzzel 1.12 manual: https://manpages.debian.org/trixie/fuzzel/fuzzel.1.en.html
- Debian Fuzzel configuration: https://manpages.debian.org/trixie/fuzzel/fuzzel.ini.5.en.html
- Debian AppArmor profile syntax: https://manpages.debian.org/trixie/apparmor/apparmor.d.5.en.html
- Debian Installer late-command context: https://d-i.debian.org/manual/en.amd64/apbs05.html

## Final measured results

The final validator completed with 1,748 installer/desktop tests passed, 37
explicit skips, and all 179 tooling tests passed; zero final failures or errors.
The 282 shell files passed 575 parser/dependency checks. Full coverage limits,
blocked audit checks, and the retained earlier attempt are explained in
`docs/native-icons-env-validation-20260919.md`. The original strict HTTP request
count assertion remains enabled; its prior anomaly is documented, not concealed.
