# Scoped Debian desktop and local APT changes

> Historical report: the local APT hook, command names and refresh design below are superseded by [Local APT repository v2](../local-apt-repo-v2/README.md). Other scoped changes remain in place.

Date: 2026-09-12. Basis: the supplied `debian-preseed-de.zip`, six external-software event files, `journalctl`, `whisper-journalctl`, `whisper-record`, and the two rfkill audit records quoted in the request.

## Delivery and qualification

This is the complete source repository, not a patch-only bundle. Changes are limited to the five requested areas, their installer integration, tests, and this report. The four superseded external-software timer/service templates are intentionally removed. Host profiles and unrelated installer logic are unchanged.

No application was compiled or rebuilt, and no application packages were installed during validation. The installer's existing `payload.tar.gz`, `payload.manifest`, and two checksum pins in `preseed.cfg` are synchronized with the changed sources. That operation serializes source files into the existing deployment archive; it does not compile applications. The existing generated-artifact consistency check passes.

The code implements the repository, desktop override, recorder lifecycle, launcher ownership and rfkill changes described below. It does **not** establish that every upstream GTK, tray, compositor, input, or application defect in the journal has been eliminated. These distinctions are important before deploying the changes to a live desktop.

## 1. Local signed APT repository

### Layout and transactions

The new root-only `/usr/local/libexec/local-apt-repository` owns these paths:

```text
/var/lib/software/
  inbox/                         root-private incoming transactions
  rejected/                      invalid inputs and rejection reasons
  repository-signing/            root-private signing key
  state/                         lock and existing vendor receipts
  repo/
    pool/<package>/<sha256>/...   immutable .deb files
    .snapshots/<generation>/     signed indexes and transaction catalog
    current -> .snapshots/...    atomic publication pointer
    Packages -> current/Packages
    Packages.gz -> current/Packages.gz
    Release -> current/Release
    InRelease -> current/InRelease
    Release.gpg -> current/Release.gpg
    by-hash/SHA256/...            immutable indexes for concurrent APT readers
```

The source is a signed flat file repository, using `/etc/apt/keyrings/local-apt-repository.gpg` and `by-hash=force`. There is no `trusted=yes`. The existing repository key is retained when present; an empty signing home gets a local Ed25519 signing key.

An input is copied to a private partial file, validated, assigned its Package/Version/Architecture identity, and published in the immutable pool. The new catalog and signed indexes become current together with a single symlink replacement. Files and directories are synchronized before publication. Signing failure leaves the previous generation selected. APT by-hash indexes and immutable package paths avoid invalidating readers that already fetched older metadata.

Validation checks Debian control fields, version syntax, enabled architectures, payload readability, bounded input size, file types/ownership, symlinks, and changes while copying. Automatic updates are pinned to the registered package and architecture. Downgrades and changed bytes under the same unmodified version are rejected. Dependency edits are confined to the selected `Depends` alternatives; `Pre-Depends` and the compressed data archive remain unchanged. A `+localrepoN` revision distinguishes locally modified metadata.

A local signature authenticates this host's publication, not an unknown upstream vendor. Adding a .deb remains an administrator trust decision: validation is not malware analysis, and later APT installation can execute its maintainer scripts.

### Interactive use

```sh
sudo local-add-deb ./example.deb
sudo apt update
sudo apt install actual-package-name
# Later:
sudo apt update
sudo apt upgrade
```

The wrapper prompts to add the file, optionally displays/removes comma-separated `Depends` names, and asks whether to enable automatic updates. An automatic package gets an HTTPS endpoint prompt. Answering `n` leaves the package static and available through normal APT operations. Removing dependencies carries an explicit warning about missing runtime libraries.

```sh
sudo local-add-deb --delete
```

Deletion lists package identities and versions, accepts a list number or an unambiguous package identity, removes its update policy, and publishes the new catalog. It does not uninstall already installed software. A tombstone prevents default policy initialization from silently reintroducing the deleted package.

Old pool objects and snapshots are deliberately retained, including after deletion, to protect cached/concurrent APT readers. They can accumulate disk usage; automatic garbage collection is not introduced in this scoped change. Removing catalog entries is not secure erasure of retained archives.

### Automatic downloads and APT ownership

`90-local-apt-repository` runs refresh in `APT::Update::Pre-Invoke`. Refresh processes completed local inbox transactions, retrieves enabled updates and atomically publishes them. It does **not** invoke APT recursively, install packages, or acquire APT/dpkg database locks. Installation remains an ordinary `apt install` or `apt upgrade` transaction.

Public GitHub release pages and release API endpoints, GitLab release pages and release API endpoints (including self-hosted GitLab), SourceForge download redirects, and direct/raw HTTPS endpoints are supported. A direct response need not have a .deb suffix. JSON or HTML responses are not accepted as packages. Ambiguous release assets fail closed; use a direct asset URL in that case. This is not an arbitrary website scraper, and private authenticated provider APIs are not configured by this interactive workflow.

An individual unavailable upstream produces a diagnostic and retains its published version. A signing/storage/publication failure is an error rather than being misreported as an upstream outage. Manual static packages never trigger network retrieval.

The existing Discord, Postman, Tuta and Ledger verifiers are reused through `/usr/local/libexec/local-apt-vendor`. Their verified prebuilt payloads are archived as local Debian packages so dpkg owns their installation and future upgrades. AppImages are extracted with the distribution's SquashFS utility rather than executing an AppImage runtime as root. Vendor program bytes are not compiled or patched. Tuta's existing hash-only release receipt uses a local version series instead of inventing a vendor version.

The established managed ChatGPT policy is maintained by the narrow dpkg pre/post hook. Its diversion must already be bootstrapped; the hook verifies rather than creating the diversion while dpkg owns its database lock. Alternate dpkg roots are excluded from host policy changes.

`local-apt-inbox.path` handles completed `.deb` arrivals. The wrapper and downloader publish incoming files by atomic rename. For other producers, write/copy to a `.part` name and rename to `.deb` only after completion; do not stream directly into a watched `.deb` filename. A `.deb` directly dropped in the root-private inbox defaults to static registration. Use the interactive wrapper to select dependency changes or automatic updates.

The old standalone automatic-download and automatic-install timers are removed from the source and retired by installation. Explicit installer/bootstrap and offline repair operations remain explicit; the runtime refresh path does not call them.

### Event interpretation

All six supplied events describe successful ChatGPT or Discord transitions. The word `missing` occupied the previous-version field; it did not identify a missing file. That old event detail is now named `not-installed`. The events do not, by themselves, demonstrate a failed download or failed installation.

## 2. Pristine vendor desktop files

`95-labwc-desktop-apps` still invokes the narrow post-dpkg scanner. Eligible files under `/usr/share/applications` are only read. Generated overrides use the same relative path under `/usr/local/share/applications`, which takes precedence under the normal XDG data-directory order. User overrides remain higher precedence.

The scanner preserves quoting, field codes and desktop actions, and disables D-Bus activation in a generated override when needed to ensure the wrapped Exec path is used. A digest manifest distinguishes owned generated overrides from administrator files. Unmodified stale generated entries are removed; administrator-created or subsequently modified entries are preserved. A durable pending manifest recovers publication interrupted between output and manifest updates.

The hook updates only the local desktop database. The canonical managed ChatGPT desktop entry is likewise published locally. On an already installed host, earlier versions may already have modified vendor desktop files. This change stops future mutation; restoring the exact package-supplied bytes requires reinstalling the affected packages. The scanner does not pretend to reconstruct unknown original vendor content.

## 3. Whisper recording lifecycle

The supplied log shows recording being intentionally stopped, `pw-record` returning status 1, a successful finalizer, and a successful subsequent transcription. GNU timeout is no longer the recording service's main process. A Perl recording supervisor now retains ownership, forwards stop signals, enforces the existing 15-second recording limit, and waits for the child to finish.

A handled intentional stop returning status 1 is accepted only with a complete, finalized WAV and without forced termination. Spontaneous status 1, invalid/incomplete WAV output, exec failure and forced termination remain failures. There is no blanket `SuccessExitStatus=1` workaround. The separate recording lock is retained, while the short-lived control lock is released after worker acquisition so the stop command cannot deadlock behind its own recording process. Existing transcription behavior is unchanged.

The service uses `KillMode=mixed`, `KillSignal=SIGINT`, a 25-second backstop and a 15-second stop allowance. The focused tests execute the production supervision methods against child fixtures, including a real 15-second automatic stop; they are not live PipeWire tests.

## 4. Launcher ownership and journal issues

Ordinary managed native and generic desktop apps now have explicit transient user services, `app.slice`, session lifecycle dependencies, cgroup lifetime/cleanup, null stdin and their own journal streams. Ordinary native launches no longer use `--pipe --wait`, which previously retained the launching panel's streams. ChatGPT's intentional private output-pipe path remains unchanged. The two Waybar FeatherPad actions are routed through the generic transient launcher instead of directly executing the editor.

Tuta additionally receives a read-only bind of its own managed desktop entry into its private home. This addresses the integration file being hidden from that sandbox without granting write access to the real applications directory. It is not a claim to repair Electron's updater or GLib internals.

A small fixed-command panel supervisor coalesces only two exact diagnostic strings: `Plugged` and the quoted LayerShellQt deprecated screen-configuration warning. The first occurrence and periodic repeat counts remain visible; all other output and the real child exit status are retained. Signal forwarding preserves Waybar reload and panel shutdown. The supplied journal contains 13,320 `Plugged` entries. This reduces noise without treating all stderr as harmless.

Waybar's two taskbar configurations no longer enable sorting by app ID, avoiding that configured reorder path. This is a workaround for the observed GTK reorder assertions, not a tested patch to GTK or Waybar internals.

### Not asserted fixed

The remaining blank-ID/missing-icon tray message, Tuta's GLib handler and GTK assertions, and its `APPIMAGE` updater warning are not claimed eliminated. No fake `APPIMAGE` environment or guessed undocumented Tuta setting is introduced. Likewise, the first Crystal Dock deprecated-API warning remains visible: coalescing repeats does not replace the API in a vendor binary.

The journal also has input lag/jump reports, DRM atomic-commit/hotplug failures, a missing Xwayland attempt, a firstboot exit without its failing command, and application-specific browser/extension diagnostics. The supplied excerpt is insufficient to justify a specific safe configuration change for each. These require reproduction on the target and/or an upstream package fix. The Bitwarden cross-filesystem hard-link warning explicitly falls back to copying successfully and is not treated as installation failure. No unrelated hardware, firstboot or browser policy is changed to silence these messages.

## 5. AppArmor

Read-only `/dev/rfkill r,` is added to `managed-session-controls` and `sleek`, covering the two inherited-file audit records supplied. No rfkill write grant is added.

Related profiles are extended for the local repository, private vendor staging, local desktop override manifest, recorder child signals, panel supervisor and its reload signal. Repository maintenance gets inspection/signing/downloading capabilities and narrowly scoped state/source/key paths; it is not given APT execution or dpkg database write permissions. Interactive terminal descriptors are allowed for the root-only add/delete prompts. Existing application isolation policy is otherwise retained.

AppArmor parser checks pass for the changed profile files. This is parser validation, **not** an enforcing-kernel audit of all live app workflows. The supplied two records cannot prove complete coverage of every application action.

## Deployment notes

Fresh unattended installations use the updated source assets and matching pinned payload. Serve the complete extracted repository together; do not combine a new preseed entry with an old payload or manifest.

For an existing host, review `changed-files.tsv` and deploy the corresponding helpers, Perl/Python modules, system configuration, profiles, and affected per-user unit/config changes together. `/etc/skel-desktop` is a template and does not automatically update existing home directories. Do not rerun the entire unattended software installer indiscriminately on a live workstation.

Retire and stop the two old timer/service pairs before enabling the replacement. After deploying the matching files and profiles, `local-apt-repository init` imports old `/var/lib/software/debs` archives once and establishes the new signed source. `adopt-vendors` publishes packages for supported verified existing `/opt` installations and prints their paths; install those explicit paths with APT to transfer ownership to dpkg. `seed-defaults` registers the bundle's known update endpoints without overriding explicit interactive choices. Then reload system units, enable `local-apt-inbox.path`, regenerate desktop overrides, and reload the affected user units/session. These operations should first be exercised on a disposable target representative of the installed host.

The target package lists already include the Perl Moo/MooX dependencies; required GnuPG, Python, curl and SquashFS dependencies are explicitly included for the repository path.

## Validation results and limits

Validation ran in a Debian 13 container, not the user's live Forky desktop.

| Check | Result |
|---|---|
| New scoped tests (`python3 -B -m unittest discover -s tools/tests -v`) | 27 passed |
| Real isolated APT test included above | Signed file repository accepted; candidate advanced from 1.0 to 2.0; no installation occurred |
| Existing installation regression suite | 34 passed |
| Existing lifecycle suite | 22 passed |
| Existing installed-failure suite | 20 passed; 1 error because `todo/managed/apparmor/apparmor.log` was not supplied in the ZIP |
| Existing desktop-sandbox suite | 68 passed; 1 skipped; 1 failure because `todo/apparmor.log` was not supplied in the ZIP |
| Existing repository-integrity suite | 9 tests passed; 1 test had 13 provenance subtest failures already present in the original ZIP |
| Unrelated host profiles | All 13 remain byte-identical to the original ZIP; their existing provenance ledger is not rewritten to hide failures |
| Existing external-software Perl tests | 4 blocked at import because Moo/MooX modules are not installed in this container |
| Changed/new Python and shell syntax | 12 Python files and 5 shell files passed |
| Changed AppArmor profiles | Parse-only checks passed for managed-desktop-wrappers, managed-labwc-session and sleek |
| Systemd unit verification | No unknown-directive/syntax diagnostics; executable-path checks cannot pass because target helpers are not installed at live container paths |
| Installer deployment archive | 1,251 members verified against source content/modes; manifest and preseed checksum pins verified; existing generated-artifact consistency check passed |

Signed/empty repositories, static packages, endpoint resolution, malformed metadata, identity/architecture failures, dependency-only transformations, immutable cache retention, signing rollback, prebuilt payload byte/hardlink preservation, desktop override crash recovery, panel signal/exit behavior, and recorder stop/error distinctions are covered by the new tests.

No full unattended install, actual vendor endpoint downloads, graphical app launches, live PipeWire recording, real `apt upgrade` installation, or enforcing AppArmor session was executed here. Therefore the delivery is not a claim that all five objectives have been proven end-to-end on the user's system. Recorded validation logs are included in the adjacent `validation` directory.

## Primary references checked

The implementation was informed by the supplied source and logs. External checks concerned platform behavior, not replacement of the supplied evidence:

- Desktop file ID precedence: https://specifications.freedesktop.org/desktop-entry/latest/file-naming.html
- Transient services and inherited standard streams: https://manpages.debian.org/trixie/systemd/systemd-run.1.en.html
- APT hook configuration: https://manpages.debian.org/trixie/apt/apt.conf.5.en.html
- Waybar taskbar sorting options: https://manpages.debian.org/unstable/waybar/waybar-wlr-taskbar.5.en.html
- User-service limitations of LogFilterPatterns: https://manpages.debian.org/trixie/systemd/systemd.exec.5.en.html
