# Desktop theme wiring — work in progress, 2026-10-30

## Scope and completion state

The original request is the attachment `pasted-text-1.txt` in attachment
`22544627-074d-429c-8d03-9ef4d13e38f6`. Its four ordered objectives remain:

1. Complete Waybar styles, configuration, buttons, actions and menus under
   `d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/`.
2. Verify all host profiles and shared theme inputs, including `base.env`,
   `apps.env` and `theme-schema.tsv`, through their consumers.
3. Complete the Appearance and Reminders GTK applications, including reading
   actual installed component values and customizing colors.
4. Complete the affected codebase wiring and shared assets under
   `d-i/forky/hooks/target/usr/local/share/labwc-appearance/`.

**The broader goal remains in progress.** Source changes and static contract
reviews cover portions of all four objectives; native target installation and
integrated GTK behavior remain unverified. The latest continuation resolves the
reported installation parser failure, the paused-reminder cleanup race, dropped
Reminder activation requests and discarded Appearance component drafts.
Existing uncommitted implementation across all four objectives was preserved.
This report records bounded changes and evidence, without claiming acceptance
of the entire working tree.

The target remains Debian Forky with systemd 262. No installed target image,
package versions, GTK rendering, loaded AppArmor policy or live launches were
observed. No source compilation or Xwayland change was made.

## Corrections made in this continuation

- Waybar includes now name `~/.config/waybar/actions/` explicitly. Both
  independent installer verification processes contain their own include
  loader and reject paths outside the managed action directory. Previously
  the menu verifier called a function defined in another Python process.
- All eight native menus, including System, participate in the installer
  verification. System callbacks must name their matching fixed dispatcher
  action. All system-menu services use the same ten-second startup budget.
- Removed a redundant second rendering of `buttons/taskview.css`.
- Waybar and Crystal Dock status entries use read-only status actions through
  the existing terminal report adapter. Reload uses the Waybar reload action.
  The notification settings entry opens the GTK Appearance editor.
- Interactive dispatcher delegates replace the dispatcher process, retaining
  their transient service ownership without a three-minute UI timeout.
  Audio mute feedback recognizes wpctl's bracketed mute marker.
- WireGuard activate/deactivate/import and DNS status/restore/custom/flush
  enter the named existing workflow directly. Confirmation and selected UUIDs
  remain with the existing NetworkManager adapter. A failed backend retains
  its status; an observation timeout returns outcome-unknown (4) without retry.
- Existing Waybar fixture sources now understand action includes, CSS imports
  and nested menu paths. Raw rendered files keep their relative paths so
  `buttons/menu.css` and `menus/menu.css` cannot overwrite one another in the
  fixture dictionary. The aggregate fixture view resolves the real includes.
- Added unexecuted fixture cases for independent verifier loaders, menu leaf
  mappings, read-only status routes, interactive process replacement, mute
  feedback, selected connection identity, cancellation, confirmation and
  uncertain network outcomes.
- The permitted changed-file audit now parses Python shebang entrypoints,
  changed Waybar JSON/XML/SVG templates, and staged whitespace errors.
- Capture actions now validate output identity before claiming success, record
  the last capture under a private lock, copy only a pinned path, and feed OCR
  a private bounded snapshot. Decoder termination failures retain that snapshot
  as outcome-unknown evidence.
- Timed Do Not Disturb now uses one UID-owned lock and tokenized expiry record.
  New requests replace old expiry ownership, manual controls invalidate it, and
  expiry workers are session-bound cgroup services that verify their token before
  disabling Mako. Signal and wait failures retain the state as outcome unknown.
- System menu aliases now reach dedicated CPU, battery, listening-socket,
  app-veth policy/status, unattended-upgrade and session-diagnostics reports.
  Wayland output information reads `wlr-randr`; audio testing uses the fixed
  test sound; NVMe entries return to the existing device picker; Timeshift opens
  the recovery workflow. Reminder filters, selected-item operations and expired
  cleanup are real GTK manager actions rather than generic manager aliases.
- Appearance source wiring stages the field/editor modules and registry, reads
  current installed native values for the GTK editor, and records unexecuted
  source fixtures for that read/write contract. Local reminders expose bounded
  upcoming/overdue filters, selected-item actions and atomic expired cleanup.
- The Waybar renderer no longer performs an unmapped first render of
  `config.tmpl`. It now calls the same mapped config helper for `config` and
  each action asset exactly once. A changed-file contract inventory covers all
  44 Waybar templates and all 121 installer tokens; the current inventory has
  no unresolved map names. The style renderer covers all 18 button templates;
  `buttons/menu.css.tmpl` is reached through its explicit `button-menu.css`
  alias.

## Evidence recorded so far

- Source base revision: `db34c5b97e18208b8ecb9a1e38be940bb430b413` on `mcr/main`,
  with an uncommitted working tree.
- Inspected `Makefile`, `tools/build.py` and its `tools/publication.py`
  delegate before the permitted `make build` serialization.
- `make build` completed and reported **1,908 payload files**.
- A separate standard-library data comparison read every archive member,
  compared its bytes with the current source and manifest hash, checked the
  exact source path set and archive metadata, and checked all three preseed
  hash pins. All compared data matched. No repository module was imported.
- Static source inspection parsed 13 Waybar JSON templates and 10 XML/SVG
  templates, checked 21 CSS brace structures and import destinations, and
  matched **195 action keys across eight menus** to their XML leaves. Both
  embedded verifier programs parsed as Python and contained an include loader.
  This substitutes numeric placeholders as data; it does not execute the
  installer renderer or validate GTK runtime behavior.
- The post-regeneration `python3 -B tools/post_change_check.py` passed for **133 changed
  files**, including 53 Python sources, 12 shell sources, 27 structured files,
  614 appearance registry mappings and 1,908 generated payload members. It
  checked changed-file Python, shell, ShellCheck, theme markers, structured
  data, AppArmor structure/allow-execute qualifiers and `git diff --check`.
- No test, fixture, test discovery, kernel policy loader, host management
  helper, service manager or disposable environment was executed. The
  explicitly authorized offline AppArmor parser was run as recorded below.
  Attempted read-only sidecar agents failed initialization and supplied no
  review evidence.

Generated SHA-256 values after the final permitted serialization:

| Artifact | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `1a62e231d7d66565fb3883293bc1f7db182bfabff78c048fb31eda17c7f73de4` |
| `d-i/forky/payload.manifest` | `022e6585ffd114ced61187e8be850726a2b1c67f1c0a7ec1741b91a9163da5b7` |
| `d-i/forky/preseed.cfg` | `11817be6e55ab91b30d63ba969ac5deb9f62b7389b5ffe3b07489fa648f0d0f8` |

These hashes identify serialization consistency; they do not establish target
installation success or acceptance of the entire task.

## Reported AppArmor installation failure

The user reported `waybar-menus` line 18 failing with an invalid execute
permission. Both directory allow rules at lines 18–19 used `rwx`. These now use
`rw`; an AppArmor allow rule's `x` requires an execution qualifier, and neither
directory needs an executable transition. The changed-file static audit now
rejects unqualified allow execution in conventional path-first file rules and
preserves explicit `deny ... x,` rules. This targeted check is not a complete
AppArmor grammar parser.

At the user's explicit request, `AGENTS.override.md` and
`docs/test-isolation.md` now permit bounded offline parsing with kernel loading
and all parser caches disabled. The parser remains separate from `make build`.

Actual offline evidence:

- Parser: `/usr/sbin/apparmor_parser`, version **4.1.8**.
- Include/tunable/ABI support: public Debian
  [apparmor 4.1.8-3 amd64 package](https://deb.debian.org/debian/pool/main/a/apparmor/apparmor_4.1.8-3_amd64.deb),
  SHA-256 `ca1f7e9ff3e23bd1ba8d02b76879301eecbc25d580bbfdfec5774b2557b5537a`.
  This records the downloaded bytes and HTTPS origin; no package installation,
  maintainer-script execution or archive-signature verification was performed.
- Support files were read as data into the private directory
  `/tmp/apparmor-offline-policy-4tqtnm16`, then overlaid with checkout policy
  includes. This is a policy data directory, not an execution environment.
- Parsing used an empty private `parser.conf`, explicit staged `--base` and
  `--Include` paths, `--skip-kernel-load --skip-cache`, package feature data for
  both `--kernel-features` and `--override-policy-abi`, and
  `--jobs 1 --max-jobs 1`. Each subprocess had a 30-second timeout, a fixed
  minimal environment, no stdin and captured output. The installed source ABI
  path `/usr/share/apparmor-features/features` was relocated to the staged
  package copy only in private candidates.
- A private copy with the two original `rwx` rules returned **1**, reproducing
  `line 18: Invalid perms, 'x' must be preceded by exec qualifier 'i', 'p', or 'u'`.
  The corrected complete `waybar-menus` profile returned **0**, with no output.
- The other changed policies `calendars`, `labwc-appearance`, `labwc-session`
  and `network-sharing` also returned **0**, with no output.
- A fresh current-source parse of `waybar-menus` (SHA-256
  `8cd85a2cc5aeaa9fa3c90f78180ff1dc15919edd3acaa4541da1904b53cb4560`) and
  `calendars` (SHA-256
  `c725d8c5856364f14e091675a69e48374f1e5a014fa6c4a552ed6a37677472f5`) also
  returned **0**, with no output. The parser reported version **4.1.8** for
  this run and used the same private support tree and relocated ABI path.
- Raw `desktop-wrappers.tmpl` initially returned **1** at its unresolved
  `__INSTALLER_LOG_POWER_DIR__` placeholder. A private data-only substitution
  using `hosts/logging/observability.env` and the wallpaper path in
  `hosts/themes/base.env` resolved all 15 distinct placeholders. That candidate
  returned **0**, with no output. No installer renderer was executed; this
  covers the configured defaults rather than every possible host override.

The parser results and default substitutions remain in that private directory
as `parser-results.json` and `desktop-wrappers-defaults-result.json`. Target
package versions and the installed kernel's policy acceptance remain unknown.

## Reminder concurrency and failure-case source

- The notification command places `--` before reminder title/body, retaining
  option-like text as content.
- State operations acquire the shared writer lock through the same pinned
  directory descriptor used for reads and publication. They reject a replaced
  lock inode instead of silently switching lock ownership.
- `Store.clear_paused()` reads, filters and publishes under one shared writer
  lock. The GTK manager calls it once, preserving reminders resumed before
  cleanup acquires that lock.
- Added **unexecuted** cases to
  `d-i/forky/tests/test_waybar_button_runtime_20261027.py` for AppArmor allow/deny
  execute syntax, resumed reminders, busy cleanup, directory/lock replacement,
  descriptor closure, retained candidates after replace failure, uncertain
  publication after directory-sync failure, and notification option text.
  The new Reminder cases use a private tree, empty inherited environment,
  explicit home and blocked external commands/account lookups; timezone
  validation is mocked because these cases cover locking/publication.

The current source review also covers atomic linked-calendar upsert/removal,
event-anchor preservation, all 14 recurrence presets and 13 lead-time values,
named-zone DST gaps/folds, invalid monthly dates, bounded catch-up, UTC sort
order, and durable notification receipts. A reservation is written before
`notify-send`; accepted, proven-not-sent and outcome-unknown results are
recorded before a reminder is advanced. Reserved and uncertain snapshots remain
reviewable after edits/deletes, and only a proven execution failure can retry.
The worker returns outcome-unknown to its service wrapper, which has
`RestartPreventExitStatus=4`; both GTK and worker AppArmor profiles grant only
the owned ledger and fixed temporary-file patterns. These are source findings,
not delivery or service-runtime evidence.

The guarded Waybar fixture now contains 7 local-state, 12 delivery, 7 calendar
and 6 activation cases in these classes. All 32 cases remain unexecuted under
the repository static-only rule and use source extraction or private fixture
data rather than the installed desktop.

Installation-fix fixture snapshot SHA-256, before the GTK cases below:
`70f8c9c0e49e02904ef2a40678bf4347f39831e8c896aed1b85c7b4655e2ae9b`.

Installation-fix source snapshot fingerprint, before the GTK changes below:
`552f2df4ca8c7f70f3ae5a459df7c87bf015fa6410b13e08dc30f5b878b31e48`.
It is SHA-256 over sorted UTF-8 lines `SHA256  relative-path\n` for exactly:

- `d-i/forky/hooks/target/etc/apparmor.d/waybar-menus`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_local_reminders.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_calendar_reminders_gtk.py`
- `d-i/forky/tests/test_waybar_button_runtime_20261027.py`
- `tools/post_change_check.py`

The payload manifest above separately pins every serialized source input.

## GTK activation and component drafts

The Reminder application's previous default activation handler closed over its
first `mode` and `action`. Later launches with the same application ID could
only present that original window. The source now uses
`Gio.ApplicationFlags.HANDLES_COMMAND_LINE`, forwarding fixed positional
request names and validating mode/action again in the primary process. The
manager reconfigures filters and selected-action controls for every request,
returns explicit bulk-action/expired-cleanup failures to the launching process,
and keeps an existing unsaved new-reminder window. Removed windows clear their
cached references. An editor only refreshes its manager if that manager still
belongs to the application.

The [Gio command-line flag](https://docs.gtk.org/gio/flags.ApplicationFlags.html)
and [primary-instance command-line handler](https://docs.gtk.org/gio/vfunc.Application.command_line.html)
document this forwarding contract. `printerr_literal` requires Gio 2.80 or
later; actual installed target library versions were not observed. The role
manifest declares Python GI and GTK4 introspection packages. The existing
`desktop-runtime` package abstraction includes `dbus-session`, which grants
session-bus communication; this continuation adds no policy permissions.

Appearance previously discarded the old rows when changing components and
submitted every field of only the visible component on Save. It now remembers
drafts before replacing widgets and validates/submits changed fields across
components. Unchanged values cause no transaction or refresh. Successful saves
reread installed values and rebuild the visible rows; validation, transaction
failure and successful-commit/readback failure have distinct messages. Removed
windows clear their cached reference, and new windows read current installed
values when constructed.

The existing guarded fixture files now contain **11 additional unexecuted
logic cases**: five Reminder activation/routing cases and six Appearance
draft/failure cases. They AST-extract only the affected logic into fake
application/widget objects, without importing GTK or a repository runtime
module. They clear the inherited environment and prohibit external commands.
These authored cases have not been executed and do not prove real D-Bus or
GTK behavior.

Current fixture source SHA-256 values:

| Fixture | SHA-256 |
| --- | --- |
| `test_waybar_button_runtime_20261027.py` | `119d344b72c924bab0d4d28d84aa2bdb09fc5f9e288ed6473b4067f03535cce0` |
| `test_appearance_picker_contract_20261027.py` | `732d2f51c4e355fc43384e596ad4b936a3bf4f8dfdc55f2a9aed5ffdcc348e0f` |

GTK continuation fingerprint:
`de3f10569c4261488ef26f88230579cd2646b96845676517bf6c3691c8e7d989`.
It uses the same sorted `SHA256  relative-path\n` format for exactly:

- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_calendar_reminders_gtk.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_appearance/editor.py`
- `d-i/forky/tests/test_waybar_button_runtime_20261027.py`
- `d-i/forky/tests/test_appearance_picker_contract_20261027.py`

After the Waybar renderer, Reminder and isolation-document edits, `make build` serialized
**1,908 members**. A bounded
standard-library data comparison matched every current source byte, manifest
hash, archive path/type/metadata and preseed hash pin. Expanded member bytes:
**20,904,298**. The current source fingerprint for the Waybar renderer and
reviewed AppArmor,
Reminder, service, calendar-action, fixture, isolation and override files is
`1d2dd9d9995757b5384648b8ab2f69e782bfa608f5350525d2e6714027b2b122` for the
Waybar renderer subset. The earlier Reminder subset remains
`7ddeff44cfe379ebb43828747b21c9f170a00aa519fd3865a95af34295bdf8c5`.
No repository module was imported by that comparison.

## Current requirement coverage

| Original objective | Current authoritative source evidence | Remaining limits |
| --- | --- | --- |
| 1. Waybar separation and wiring | Two named bars, 12 existing action includes, 20 existing CSS imports, eight menus and 195 exact action/leaf pairs; unique IDs per XML menu. | Installed geometry, native menu interaction, compositor focus, DND timing and capture/OCR behavior remain unverified. |
| 2. Profiles and theme inputs | Exact unique ownership of 1,346 base, 360 app and 362 office keys by the 2,068-row schema. All 1,894 distinct theme marker names in target sources resolve to a schema key or its derived target path. All ten profiles have 1,328 common keys and preserve tray/atomic-KMS invariants. | Full native grammar acceptance and rendering/consumption of every profile value were not executed. Filesystem, network and hardware behavior remain unverified. |
| 3. Appearance and Reminders GTK | Native-value reads, field updates and entrypoint/staging contracts inspected; 546 fields, 614 mappings, 34 paths and eight components. Every one of the 15 Waybar categories is present in the editor order; no field mixes privileged greeter and user paths. Activation, draft, recurrence, linked-state and durable-delivery source contracts reviewed. | Thirty-two Reminder and activation logic cases remain unexecuted. Real GTK interaction, bus forwarding, notification delivery, CalDAV behavior and service/runtime recurrence remain unverified. |
| 4. Codebase reliability/security/wiring and shared assets | Changed-file syntax/structured-data/marker/registry checks, raw-render exemptions, staging paths/modes and generated source consistency inspected. Reported AppArmor syntax failure reproduced and corrected offline. | This is partial source coverage; it does not establish correctness of every affected recovery, concurrency, lifecycle or result-propagation path, or live acceptance of the full working tree. |

The first profile comparison assumed identical key sets within a filesystem
family and stopped on the Flex hardware key. Inspection of `hosts/README.md`
and actual key differences confirmed intentional policy: Btrfs layout keys,
F2FS app-veth/layout overrides and concrete `SYSTEM_HARDWARE_SPEC` declarations
remain with their owners. The corrected data review preserves these differences
and found no duplicate profile assignments. No profile was changed to satisfy
the invalid initial assumption.

## Next source review, preserving objective order

The four objectives remain the completion scope. Source coverage above does
not prove complete profile/schema consumption or GTK editor/reminder behavior,
recovery, concurrency, identity preservation and failure propagation at runtime.
The recurrence/date and linked-calendar routes are source-reviewed but still
need permitted target evidence if they are to be accepted as live behavior.
The repository-root `debian-preseed-de-audit.md`
referenced by guidance was absent when inspected; its acceptance gates were
not reviewed.

Rebuild whenever payload inputs change, run the required changed-file audit
after edits and regeneration, and compare final source/archive/manifest bytes
again. Keep the goal active until the full original scope passes a concrete
requirement-by-requirement completion audit within the permitted static and
offline-parser boundary.
