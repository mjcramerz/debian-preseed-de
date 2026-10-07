# AppArmor notifications and desktop release maintenance: 2026-10-05

## Scope and supplied evidence

The target remains Debian Forky with systemd **261.2**. Changes are confined to
the notification/logging defect, authenticated desktop release pins, the runtime
contracts changed by those releases, their tests, and the required generated
installer snapshot. No new source compilation was introduced. Private Xwayland
installation, launch paths, confinement and profile values remain unchanged.

Every one of the **81 regular files** under the current `todo/` tree was read,
including the firstboot evidence: **2,073,089 bytes**, with **22 empty files**.
A SHA-256 inventory was captured before editing and compared against all files
again afterward. The supplied files were preserved. Earlier incident reports
in this directory describe different evidence samples and remain historical.

| Current evidence group | Files | Bytes | Empty files |
| --- | ---: | ---: | ---: |
| Installer log | 1 | 768,898 | 0 |
| Firstboot logs and captured data | 41 | 154,247 | 0 |
| Installer target validation marker | 1 | 52 | 0 |
| Managed application log | 1 | 54,819 | 0 |
| Managed model/runtime logs | 6 | 31,101 | 5 |
| Managed security logs | 24 | 835,087 | 15 |
| Managed system logs | 7 | 228,885 | 2 |

The captured firstboot results contain **438 PASS**, **one SKIP** for graphics
capture without an active Wayland session, and **zero FAIL**. These are results
from the supplied installation, not a boot of the modified installer. The
captured `systemd-version.txt` reports **262 (262-1)**, as do the local validation
tools; the requested compatibility target has not been raised from 261.2.

## AppArmor signal lifetime and record classification

The current AppArmor mirror contains **406 STATUS records and zero DENIED
records**. Extracting the native AppArmor records from the supplied 2,759-line
audit file reproduces the 70,375-byte mirror exactly. The copied kernel/system
logs do not supply a new AppArmor denial requiring another broad permission.

The source nevertheless contained a concrete lifetime mismatch: category
signals under persistent `/var/lib/labwc-notifications/security/` were created
with non-truncating tmpfiles entries, while the supplied system's `/var/log`
was volatile. A signal could therefore survive the log evidence it referred
to. The fixtures reproduce this failure mode; the evidence sample does not
contain the old signal file needed to prove its exact historical contents.

The repair is:

- Use `f+!` for the five category signal files. Boot creation truncates stale
  signals once; ordinary rsyslog `systemd-tmpfiles --create` preflight preserves
  current signals. Both behaviors were exercised with native tmpfiles in a
  private filesystem root. The syntax is documented in the target version's
  [tmpfiles specification](https://raw.githubusercontent.com/systemd/systemd/v261.2/man/tmpfiles.d.xml).
- Bind notification acknowledgements to the validated kernel boot ID as well
  as the file device/inode and event count. Logging out and back in does not
  repeat an acknowledged event. A new boot cannot conceal an event through
  inode/count reuse. The notifier's AppArmor profile permits the exact boot-ID
  file read.
- Accept signal sizes up to the configured rotation threshold, fixing the
  previous silent omission between 1 MiB and the 2 MiB default threshold.
- Identify actual native audit record types and headers before mirroring or
  signaling. Quoted `apparmor="DENIED"` text in EXECVE/USER records is not a
  policy denial. STATUS records remain available in the mirror but never
  produce a denial signal. Real AVC/1400 and APPARMOR_DENIED records still do.
- Point notifications to the current log and its rotations. Failed notification
  delivery does not acknowledge the pending event.

A separate native rsyslog process replayed the **actual supplied audit file**
through the modified rules in a private directory. It emitted the same **406
records byte for byte**, and **zero denial signals**. The separate synthetic
delivery regression also exercises a 4,096-record backlog, a real denial marker,
live append, auditd-style rename/create rotation and daemon restart. No host
logging service or kernel policy was changed by these checks.

## Current external binary releases

All ten canonical profiles have the same updated release settings. URLs,
versions/tags and SHA-256 values were checked against primary publisher metadata
on 2026-10-05. Each installer validates the actual downloaded bytes before
installation. The build preserves independent profile settings.

| Tool | Previous pin | Current pin | Primary release evidence |
| --- | --- | --- | --- |
| QoreDB | 0.1.38 | **0.1.39** | [Release](https://github.com/QoreDB/QoreDB/releases/tag/v0.1.39), [asset digests](https://github.com/QoreDB/QoreDB/releases/expanded_assets/v0.1.39) |
| Tomat | v2.13.0 | **v2.13.0**, already current | [Release](https://github.com/jolars/tomat/releases/tag/v2.13.0), [asset digests](https://github.com/jolars/tomat/releases/expanded_assets/v2.13.0) |
| Waypaper | 2.8 | **2.9** | [Release](https://github.com/anufrievroman/waypaper/releases/tag/2.9), [exact PyPI wheel metadata](https://pypi.org/pypi/waypaper/2.9/json) |
| Satty | 0.21.1 | **0.22.0** | [Release](https://github.com/Satty-org/Satty/releases/tag/v0.22.0), [asset digests](https://github.com/Satty-org/Satty/releases/expanded_assets/v0.22.0) |
| pdfcpu | 0.13.0 | **0.16.1** | [Release](https://github.com/pdfcpu/pdfcpu/releases/tag/v0.16.1), [asset digests](https://github.com/pdfcpu/pdfcpu/releases/expanded_assets/v0.16.1) |
| Obsidian | 1.12.7, hardcoded in installer | **1.14.4**, owned by each profile | [Release](https://github.com/obsidianmd/obsidian-releases/releases/tag/v1.14.4), [asset digests](https://github.com/obsidianmd/obsidian-releases/releases/expanded_assets/v1.14.4) |
| Sleek | 2.0.26, hardcoded in installer | **2.0.29**, owned by each profile | [Release](https://github.com/ransome1/sleek/releases/tag/v2.0.29), [asset digests](https://github.com/ransome1/sleek/releases/expanded_assets/v2.0.29) |
| Samloader | 2.0.0 | **2.2.0** | [Release](https://github.com/topjohnwu/samloader-rs/releases/tag/2.2.0), [asset digests](https://github.com/topjohnwu/samloader-rs/releases/expanded_assets/2.2.0) |

The current amd64 artifact digests are:

```text
QoreDB     c7c48c1fda8f0fd1eee40d36f0976e176abd241e545d2e8c105262f53a20248c
Tomat      871ee4fd19f3367cf4aa638a2364ae83de6c4ce4550a7ebe5ee6124be86c6aa1
Waypaper   3455cb7b120a3b6bcaeddafb8e18bb415cd40187c9d9be106e528ba93b0e529f
Satty      eb7a028c4a5ce331c2f355add8e2b807a7d697fe4495f7e1965786a4f6bcd5b8
pdfcpu     757e57036e1da56b789d0243ba72b09be4f26b3ec88e781170896ac36ae04d51
Obsidian   85b10dcba6edfc1c0460a6d18260cf31c30447a444bd858a6440b9c9c8806d25
Sleek      a766e7c245eeeba69eab648dd45179724b235833b82a2e464c93fc3bed5fb712
Samloader  f6029dcce75b8a66acc1975529085c53903f7cdb35505e0ac0a973f2652480ff
```

Typst [0.15.1](https://github.com/typst/typst/releases/tag/v0.15.1) and yt-dlp
[2026.08.19](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.08.19) were already current.
The custom [Whisper](https://github.com/mjcramerz/whisper-labwc/releases/tag/whisper-labwc-main),
[Llama](https://github.com/mjcramerz/llama-labwc/releases/tag/llama-labwc-main) and
[resctl-bench](https://github.com/mjcramerz/resctl-bench/releases/tag/resctl-bench-v0.0.2-P15s)
release tags and digests also remain current, as do
the publisher's [terminal fonts](https://github.com/mjcramerz/fonts/releases/expanded_assets/terminal-fonts-v0.0.1)
and [Microsoft fonts](https://github.com/mjcramerz/fonts/releases/expanded_assets/microsoft-fonts-v0.0.1).
Other desktop applications retain their existing vendor latest-resolution or
APT installation paths. Developer SDK/toolchain pins, storage, NFS, networking
and hardware profile choices were preserved.

### Changed runtime contracts

- **Waypaper:** Fetch the exact publisher wheel with a bounded HTTPS-only
  download, private temporary file, size limits, SHA-256 check and atomic
  publication before pipx consumes it. Pipx uses only binary distributions and
  Debian's existing GI packages, runs as the existing transient unprivileged
  account, and retains the final root-owned runtime seal. Version 2.9's
  [process discovery](https://raw.githubusercontent.com/anufrievroman/waypaper/2.9/waypaper/changer.py)
  executes `pgrep -f`; a dedicated child profile grants that executable and
  read-only PID cmdline/stat/status access, with no new ptrace or environment
  grants. The existing stop/start handoff to `swaybg.service` and control-group
  cleanup remain and have a passing argument/lifecycle fixture.
- **QoreDB:** Its [release workflow](https://raw.githubusercontent.com/QoreDB/QoreDB/v0.1.39/.github/workflows/release.yml)
  and [sidecar configuration](https://raw.githubusercontent.com/QoreDB/QoreDB/v0.1.39/src-tauri/tauri.sidecar.conf.json)
  bundle `qore` and `qore-mcp`. Exact inherited execution rules keep version
  probes within the GUI's existing database confinement. No unconfined
  transition was added.
- **Satty:** Set `notification-thumbnail = "app-icon"` explicitly, retaining
  the previous icon behavior and avoiding the release's new screenshot
  thumbnail sharing. The rendered configuration parses as TOML. Its existing
  private glibc runtime pins were preserved.
- **Obsidian/Sleek:** Move authenticated binary settings into every profile;
  validate version, exact official URL, digest syntax and conservative byte
  bounds before download. The existing hash-before-package-install and
  installed-version checks remain.
- **Samloader:** Consume the publisher's flat ZIP without path-based bulk
  extraction. Require exactly one unencrypted regular `samloader` member,
  create the destination exclusively, enforce a streaming uncompressed size
  ceiling and CRC, then retain the existing ELF/architecture/version checks.
  Switch explicit USB arguments to the prebuilt release's `nusb` backend.
  The [pinned USB dependency](https://raw.githubusercontent.com/kevinmehall/nusb/v0.2.7/src/platform/linux_usbfs/enumeration.rs)
  and [configuration reader](https://raw.githubusercontent.com/kevinmehall/nusb/v0.2.7/src/platform/linux_usbfs/device.rs)
  need exact read-only device/configuration/interface attributes below USB
  sysfs paths; those scoped grants are added. No sysfs write is added.
  Existing confirmation phrases, selected-device/model checks, SHA-256/MD5
  checks and HOME_CSC versus CSC selection remain. The confirmation text now
  explains the release's automatic firmware-supplied partition-table update.
  No download, reboot or flash was performed against a real device.

The Samsung tests exposed a real existing reader/writer mismatch: manifest
keys such as `ap_sha256` were written but rejected by the reader's letters-only
key syntax. The reader now accepts digits after the initial letter. Managed
downloads made by either 2.0.0 or 2.2.0 are accepted only after the existing
path and component-integrity checks. Tampered components and unknown download
provenance are rejected before the fixture's vendor-validation stage.

## Other supplied diagnostics

| Observation | Conclusion and remaining boundary |
| --- | --- |
| Missing global Xwayland executable | Expected for the requested private Zoom/Discord arrangement; implementation and pins preserved. |
| Bitwarden hardlink `EXDEV`, followed by successful copy | Existing fallback succeeds across separate filesystems; no AppArmor grant needed. |
| Vivaldi missing optional first-run search JSON | Vendor initialization behavior; no evidence supports fabricating a browser database. |
| HDMI atomic commit busy errors and libinput latency | Require the actual dock/display/driver/session; logs do not identify a deterministic source repair. |
| ACPI/RMI4 firmware warnings | Hardware/kernel interaction remains; no unsupported firmware override introduced. |
| CrowdSec DNS/initial enrollment messages | Later firstboot enrollment and normal operation are present; packaged grok warnings do not establish a new policy denial. |
| Tailscale warming-up and idle network-helper timeout | Later operation is present; no missing desktop permission established. |
| Codex missing bundled plugins/reserved marketplace errors | Definitions come from the separately cloned runtime-home repository. Reconciliation belongs there; this installer does not author those plugin definitions. |
| Empty scanner/model logs | Cannot establish successful scans or failed services without execution evidence. |
| Installer chroot AppArmor/glycin warnings | Later captured firstboot profile validation passes; no new captured DENIED record supports a wider grant. |

## Validation evidence

The selected suites were invoked with Python `unittest discover` from
`d-i/forky/tests`. The common command is below; later runs also added
`-W ignore::EncodingWarning` to suppress interpreter encoding warnings.

```sh
python3 -B -m unittest discover -s d-i/forky/tests -p PATTERN -v
```

| Pattern | Observed result and execution boundary |
| --- | --- |
| `test_security_signals_20261005.py` | **8 passed**; native private-root tmpfiles plus real shell/state-file fixtures with mocked notification delivery. |
| `test_desktop_release_integrity_20261005.py` | **16 passed**; download transport is mocked, real hash/size/symlink checks; native ZIP fixtures; actual Perl manifest validation with real SHA-256 and explicit device/vendor-MD5 stubs. |
| `test_firstboot_audit_20260926.py` | **14 passed**; includes a private native rsyslog process and synthetic backlog/live/rotation/restart inputs. |
| `test_apparmor_incidents_20261004.py` | **17 passed**; includes native offline policy expansion, effective pgrep proc-read permissions and nusb sysfs read-only masks. |
| `test_tomat_release_pins_20260920.py` | **25 passed**; local package/download/install fixtures, no remote vendor binary execution. |
| `test_profile_pin_independence_20260920.py` | **9 passed**; private repository build/check fixtures preserve independent profiles. |
| `test_packaged_native_session_20260920.py` | **9 passed**; actual POSIX shell orchestrator with explicit target-step stubs, no d-i/Wayland boot. |
| `test_log_launchers_20260915_r3.py -k test_wallpaper_state_handoff` | **1 passed**; transient-service argument and confinement handoff fixture, no manager activation. |

The packaged-session fixture initially failed in four assertions because its
step inventory lacked the already-existing Obsidian policy preflight. An
isolated `HEAD` orchestrator reproduced the same missing-function failure.
One explicit fixture step was added; no production orchestrator change was
needed. All **99 selected tests** above passed after these fixes.

Additional checks and their actual boundaries:

- `python3 -W ignore::EncodingWarning -B tools/check_shells.py --output /tmp/debian-preseed-shell-check-final.json`:
  **352 shell files, 715 parser checks, PASS**.
- `python3 -W ignore::EncodingWarning -B tools/check_logging.py`:
  **111 values, 354 templates, 78 logging templates, ten profiles**, valid.
- `python3 -W ignore::EncodingWarning -B tools/check_preseeds.py`:
  **59 files, PASS**; all four generated command values survive private debconf
  read-back.
- `shellcheck -S warning -s sh d-i/forky/scripts/desktop/samloader.sh d-i/forky/scripts/desktop/waypaper.sh d-i/forky/hooks/target/usr/local/bin/labwc-adb-menu`:
  **exit 0**, no warning-level diagnostics.
- `python3 -B d-i/forky/tests/audit_codebase.py --output /tmp/debian-preseed-code-audit.json`:
  **1,632 files inventoried**, including 1,393 installer/target scope files;
  767 parsing/syntax passes, 225 systemd structure passes, 622 inventory-only
  files, 11 unrendered data templates and seven dependency-blocked Perl modules.
  Inventory/structure results are not runtime proof. The seven blocks are
  repository `.pm.tmpl` dependencies, not absent system packages. A subsequent
  private rendered-library check compiled all seven dependents and both
  changed Samsung modules: **nine successful native Perl syntax checks**.
- Private rendered native AppArmor parsing of `desktop-wrappers` and
  `usr.bin.qoredb` succeeds using an empty parser configuration, the repository
  include overlay, `-Q -K -j 1`; no kernel load or cache write. Rendered Satty
  TOML parses and has the intended `app-icon` setting.
- The direct supplied-audit replay described above and final evidence/profile
  preservation checks pass. Private replay/rendering/preservation results were
  recorded under `/tmp/debian-preseed-*.json`, without copying raw private logs
  into published documentation.
- `python3 -W ignore::EncodingWarning -B tools/build.py` regenerates the
  **1,704-member** payload, manifest and preseed pins together; browser outputs
  remain current. `tools/build.py --check` and `git diff --check` verify the
  final generated snapshot and whitespace.

The final manifest comparison has the same **1,704 member names** as `HEAD`,
with exactly **23 changed source/profile hashes**. Private Xwayland member
hashes are unchanged. Tests and supplied `todo/` data are excluded from the
installer archive. Git reports no tracked file mode changes.

## Deployment and runtime limits

Shell downloads were unavailable because DNS failed. Publisher metadata and
source were accessible through browsing;
new vendor assets were **not downloaded and independently hashed locally**.
The committed digests match publisher metadata, and install-time byte checks
remain mandatory. Offline transport tests use stated fixtures.

The local native tools are Python 3.14.7, Perl 5.42.3, rsyslog 8.2608.0,
AppArmor parser 4.1.8, ShellCheck 0.11.0 and systemd 262. Native tmpfiles behavior
and the target's 261.2 documentation agree, but this is not an installed-host
test of systemd 261.2. No unattended VM installation, enforcing desktop GUI
launch, physical USB flash, hardware repair or remote deployment was performed.
Those acceptance boundaries and the external runtime-home plugin configuration
remain visible. Historical broad-suite results were not replaced by a claim
that the whole repository test suite passes.
