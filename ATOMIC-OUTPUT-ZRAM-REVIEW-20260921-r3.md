# Historical R3 review: atomic output, icons, and storage

Date: 2026-09-21. Base: the complete supplied R2 archive, SHA-256
`94b841298159a20311be23570134c8832560ece530eeb3ee79bd3aeefbd8a2c6`.

This is the current implementation review. R1/R2 reports and validation records
remain historical evidence, not current configuration instructions. The archive
is the complete repository, including rebuilt installer products, not a patch.

## 1. Scope and preservation

The requested legacy-KMS selection has been removed from the session launcher,
installer rendering, installer validation, and desktop defaults template. There
is no replacement hostname exception, no new GPU/backend switch, and no source
patch or new vendor compilation. The existing private-Xwayland implementation
remains unchanged; it has not been expanded beyond the existing Zoom/Discord
configuration. Both helpers removed in R2 remain absent from source and payload:
`labwc-stage-waybar-icons` and `labwc-foot-supervisor`.

The production changes are limited to 13 existing source/configuration files.
The two flex profiles are included in that count. Their provenance records,
six existing test/fixture files, and three generated installer products were
updated. Two focused test modules were added. New review and validation records
are supplementary. No R2 file was removed in R3.

Byte-preservation checks cover all 11 non-flex profiles, both reference SVGs,
all 81 managed AppArmor files, the five files with private-Xwayland names,
the nine named power-flow files, and all five native Waybar menu XML files.
The complete change manifest makes the broader boundary explicit: files not
listed as modified retain their R2 content and mode. All 3,468 files from the
original uploaded ZIP and all 3,691 files from R2 remain present.

## 2. Atomic KMS: removed policy and real lifecycle changes

### Removed, not disabled by another name

The `LABWC_WLR_DRM_NO_ATOMIC` and `LABWC_WLR_DRM_LEGACY_HOSTS` settings, defaults,
renderer placeholders, validation, hostname selector, export, and log message
are removed. The normal wlroots atomic path remains in use on the affected host.

`WLR_DRM_NO_ATOMIC` occurs only in cleanup: it is unset in the login wrapper and
removed from the user-manager activation environment before starting a new
compositor and during logout. It is no longer imported or assigned. Clearing
stale state matters when a manager has previously run R2; simply deleting its
assignment could otherwise leave the old value active. Existing unrelated
renderer/cursor/scanout settings were not changed.

### What the supplied historical evidence establishes

The uploaded journal contains 144 matching atomic-commit failures. Its first is
at line 1069, September 21 at 02:39:26: labwc PID 6611, compositor uptime
00:01:04.206, connector eDP-1, EBUSY. The nearby sequence includes Thunar and its
GVfs/thumbnailing services at 02:39:23, then the managed Foot service startup at
02:39:26 immediately after the error in journal ordering. Earlier, the output
watcher starts at 02:38:23, Waybar at 02:38:24, and Crystal Dock at 02:38:25.

Neither the same-second Foot launch nor the watcher's periodic cadence identifies
a conflicting output transaction. The supplied excerpt has no per-request
watcher trace, DRM ioctl flags, CRTC commit identifier, or page-flip completion
trace for that first error. The kernel audit export starts at 02:48:26 in a later
boot, so it cannot supply the missing first-boot DRM sequence. The earlier
wlsunset startup failure is not evidence of a concurrent successful gamma update.

Consequently, the exact outstanding DRM operation at 02:39:26 remains
unidentified. The kernel documents EBUSY for a nonblocking atomic update when a
previous update remains pending [1]; that establishes the meaning of the failure,
not which component submitted the earlier update. A userspace command returning
success also does not establish that a hardware flip has completed. No claim is
made that these changes have eliminated the target hardware's EBUSY messages.

Evidence is retained in `validation/atomic-output-zram-20260921-r3/`:
`input-evidence.json` records input hashes, counts and relevant line locations;
`first-ebusy-context.txt` preserves the numbered nearby journal excerpt.

### Reproducible problems fixed in the existing output-management path

R2 already had an output lock, no-op comparisons, combined multi-head requests,
a Kanshi authority decision, and rejection without immediate stale replay.
Those are preserved, not presented as new R3 mechanisms.

R3 closes the following concrete gaps:

* **Idle-state check and mutation share one lock.** Previously the periodic
  callback checked idle state and later refreshed through separate locked calls.
  DPMS-off could enter between them, allowing the refresh to re-enable a sleeping
  output. The periodic callback now requests one reconciliation, whose ordinary
  refresh branch checks idle state while holding the mutation lock. Manual
  refresh uses that same guarded path. Pending idle restoration is handled
  inside the existing lock, not by acquiring a second lock recursively.
* **No-op reconciliation is read-only.** When desired and observed topology
  already match, it saves the observation and exits without a second query,
  output command, dock stop, or artificial wait. An unspecified planned mode is
  correctly interpreted as no requested mode change, matching the command
  builder that omits `--mode` in that case.
* **Plans are revalidated after stopping the dock.** That stop may take time.
  A fresh snapshot must still match the one used to construct the plan before
  submitting it. An empty snapshot, session teardown, or intervening topology
  change prevents submission. A stale plan is deferred to the existing later
  event/poll reconciliation, not retried in a tight loop.

Mutating wlr-randr and wlopm requests now record bounded, sanitized begin/end
messages containing a transaction ID, monotonic time, command, and accepted or
rejected result. Read-only no-ops do not produce this transaction noise. DPMS
commands use the same existing bounded subprocess execution path. This adds no
service, dependency, privilege, broad AppArmor rule, or unbounded retry.

The transaction records identify the submission window of our own component.
They are deliberately not labelled DRM commit completion events. They cannot
serialize external programs or the compositor's internal frame/gamma commits.
If EBUSY remains on hardware, the relevant next evidence is a correlated
compositor/kernel trace of submission and completion on the affected CRTC,
together with these requests and the lock/resume/connector timeline. No kernel
tracing or debug mode has been enabled automatically.

## 3. Waybar drawer: explicit 24 x 24

The Applications and Wayscriber reference buttons and all five drawer entries
(Foot, Thunar, FeatherPad, Tuta Mail and Sleek) now use an explicit
`background-size: 24px 24px, 100% 100%` in both normal and hover states. These are
24 logical CSS pixels: 24 device pixels at scale 1 and 48 at scale 2. The display
box does not imply that transparent padding inside an application logo is filled.

This uses R2's direct installed image paths. Papirus application SVGs and the
original package-installed Tuta/Sleek PNGs are not copied, edited, regenerated,
or downloaded. The reference SVG files remain byte-identical. There is no icon
cache, staging helper, runtime conversion, or replacement supervisor.

The installer verifier now checks the applicable size declaration for each
individual normal/hover selector in both managed layouts, in addition to file
presence and decoding. Finding an unrelated 24px declaration elsewhere in the
stylesheet cannot make a missing drawer size pass. Optional-package architecture
and software-bundle handling remain intact. Native menu icon sizing, palettes,
workspace colors, button order and callbacks remain unchanged.

## 4. Historical storage change (superseded by R5)

R3 introduced a fixed flex storage policy. R5 removes that policy and its
implementation, duplicate validator, fixed-capacity regression tests, and
historical production patch. Refer to `DYNAMIC-STORAGE-REVIEW-20260921-r5.md`
for the current RAM/disk-derived profiles and validation. The R3 statements
below describe historical testing, not the current storage specification.

### Physical memory is not logical disk capacity

Raising the logical minimum to 16 GiB exposed a separate calculation problem:
60% of that logical disk would produce a 9,831 MiB compressed-memory cap, even on
a host with only 7,489 MiB of detected RAM. The calculation now applies the
existing percentage to `min(logical_size, physical_RAM)`.

For that detected-RAM example, the compressed-memory limit is 4,494 MiB while the
logical disk remains 16 GiB. When the old logical disk was already smaller than
physical RAM, the prior percentage result remains unchanged. Existing writeback
budget and backing-capacity guards remain intact.

The kernel distinguishes logical disksize from the compressed-memory limit [3].
A larger logical disk is not a reservation of 16 GiB of RAM, nor a guarantee that
arbitrarily incompressible data can occupy that logical capacity within the
memory/writeback policy. No workload throughput or out-of-memory guarantee is
inferred from these configuration tests.

## 5. Validation results and boundaries

Final test results: **2,258 passed, 49 skipped, 0 failed**, across 2,307 cases in
98 runnable modules. The 99th discovered file is the existing zero-test support
module, not a failed test module. Per-module results and skip reasons are recorded
in `VALIDATION-20260921-r3.json` and the included validation directory.

The two new focused modules contribute 24 tests. They exercise the exact
production Perl functions and shell code with controlled external endpoints,
including a real multi-process flock test, idle/restore boundaries, stale/empty
snapshots, no-op behavior, command logging, byte-unit conversion, partition-size
validation, insufficient budget, dual/crypto recipes, memory caps and writeback
bounds. The R2 watcher fails 11 of the 12 new watcher contracts; those diagnostic
counterexamples are retained. This is not a count of 11 historical root causes.
The old ZRAM function also fails the new low-RAM cap case.

Additional completed checks:

| Check | Result |
| --- | --- |
| Repository build and freshness | PASS; 1,405 payload files |
| Browser-artifact freshness | PASS; browser configuration unchanged |
| Preseed validation | 59 files; all four generated command values round-trip |
| Shell parsing | 285 files; 581 parser checks |
| Managed AppArmor offline compilation | All 37 top-level policy files |
| GTK3/Cairo drawer rendering | 40 cases across both layouts, hover states and scales |
| Original/R2 file preservation | All original and R2 files present |

The GTK tests include deliberately large 512px source artwork and check the
24-logical-pixel rendered bounds, allowing normal edge antialiasing. They are
real GTK/Cairo rendering tests with fixtures, not a screenshot of the target
Waybar session.

Initial failures and reruns are not hidden. Old size/graphics-contract assertions
and the two profile provenance records were updated. The historical workload
hash test still validates the original baseline after reversing only the exact
new flex capacity block; the separate new tests validate current policy. One
unchanged Spotify lifecycle fixture returned 137 under parallel load instead of
its expected 1; it passed unchanged when rerun serially. Its first failure remains
in the validation directory. Interrupted harness runs are not counted as passes.

The code inventory separately reports 157 dependency-blocked checks, 509
inventory-only entries, 485 passing checks, 180 structure-only checks and two
templates needing rendering. In particular, missing Moo/MooX dependencies mean
full Perl CLI loads were not established by this environment. Executing selected
production function bodies does not erase that limitation.

No unattended installer was booted, no real partition or ZRAM device was changed,
no physical power action was performed, no target systemd 261.2 user lifecycle was
exercised, and no target GPU or kernel-enforced AppArmor run was available. Offline
policy compilation and fixture results are not substitutes for those checks.

## 6. Publishing and target acceptance

Publish the complete extracted repository atomically through the existing
installer-server process. Keep `d-i/forky/preseed.cfg`, `payload.manifest`, and
`payload.tar.gz` from this revision together. Changing the profile alone on the
server does not resize storage on an already installed machine.

On a fresh flex installation, read-only checks include:

```sh
systemctl --user show-environment | grep -E '^(WLR_DRM_NO_ATOMIC|LABWC_WLR_DRM_NO_ATOMIC|LABWC_WLR_DRM_LEGACY_HOSTS)='
# Expected: no matches in the new session; grep status 1 is normal here.

systemctl --user status labwc-output-watch.service
journalctl --user -b -o short-monotonic -u labwc-output-watch.service
journalctl --user -b -o short-monotonic -u labwc-compositor.service

cat /sys/block/zram0/disksize
cat /sys/block/zram0/mem_limit
cat /sys/block/zram0/backing_dev
lsblk -b -o PATH,TYPE,SIZE
swapon --show --bytes
```

Confirm `disksize` is 17179869184, the measured raw partitions are nominal 20/4
GiB within the documented alignment bound, the expected backing mapping is in
use, and ZRAM retains priority over fallback. Confirm all drawer entries and the
reference buttons are 24 logical pixels in both hover states and display scales.

Exercise ordinary login, connector changes, lock/idle DPMS and resume separately
while observing the journal. An already-current ordinary refresh must not issue
an output mutation. Sleeping outputs must not be re-enabled by periodic or manual
ordinary refresh. New mutation logs should pair begin/end IDs. Should an atomic
failure remain, correlate those logs with actual compositor/CRTC flip evidence;
do not infer completion from command acknowledgement or reintroduce legacy KMS.

## Sources

[1] Linux kernel KMS documentation, `atomic_commit` error and per-CRTC completion
semantics: https://www.kernel.org/doc/html/latest/gpu/drm-kms.html

[2] Debian Installer partman-auto recipe documentation, sizes and recipe maxima:
https://sources.debian.org/src/debian-installer/20250803%2Bdeb13u7/doc/devel/partman-auto-recipe.txt/

[3] Linux kernel ZRAM documentation, disksize, mem_limit, backing and writeback:
https://www.kernel.org/doc/html/latest/admin-guide/blockdev/zram.html

Primary sources consulted on 2026-09-21. Repository-specific claims are supported
by the supplied inputs, source changes, and included test/validation records.
