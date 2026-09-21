# debian-preseed-de

## I/O-aware zram and managed-application safety - 21 September 2026

The current inventory has **ten profiles**, with generic Btrfs, P15s, Flex,
HP14 and x360 variants and a `-duo` suffix for multi-OS installations. Retired
profiles have no compatibility aliases. Virtual storage remains supported by
the generic Btrfs profile; its capacity checks and minimums apply. Duo classes
still require the preservation addon and explicit partition-slot arguments.

Zram samples host I/O PSI before planning and again after recompression, just
before writeback. High or unavailable I/O telemetry reduces both concurrency
and the shared per-pass page budget, including a bounded emergency path. Normal
memory maintenance remains recompression-only. Existing cold-page eligibility,
queue limits, quotas, memory thresholds, logging route and privilege policy are
retained. The previous disk-alignment, dynamic-sizing and PSI timing repairs
remain included.

All 23 managed-application modules were reviewed. Four have narrow argument or
user-file/path safety fixes. Private Zoom/Discord Xwayland configuration,
compositor arguments and lifecycle functions are unchanged. No new third-party
source compilation, source patching or dependencies are introduced.

See [the R7 review, configuration and acceptance notes](REVIEW-20260921-r7.md),
[canonical profile selection](d-i/forky/hosts/README.md), and
`validation/2026-09-21-io-psi-r7/` for current evidence. The [R6 report](REVIEW-20260921-r6.md)
and other dated material below describe earlier revisions. Profile-specific
records for the retired environment were pruned from retained historical
reports; their aggregate counts are historical, not current validation proof.

## Native wlsunset and matching switcher hover - 20 September 2026

The managed Gammastep indicator and its GeoClue dependency are replaced by
Debian's packaged wlsunset in a guarded, session-bound transient user service.
All thirteen profiles include configurable coordinates, temperatures and output
selection, enabled with Malmo defaults. The Waybar window-switcher now shares
the other action buttons' existing hover style. Private Zoom/Discord Xwayland
and unrelated desktop repairs are unchanged.

See [design, settings and target checks](docs/WLSUNSET-FOLLOWUP-20260920.md)
and `validation/2026-09-20-wlsunset/` for this revision's evidence.

## Debian packages only; native thumbnail switcher - 20 September 2026

Labwc and KWallet are installed from the existing Debian binary package selection
(`labwc` and `kwallet6`). The installer no longer fetches, patches or compiles their
sources. The source-builder, source-patcher and their staging hook are removed,
not bypassed on failure. The compositor uses its native thumbnail-grid switcher;
classic-list mode and its fallback fields are rejected. Alt+Tab, Shift+Alt+Tab
and the Waybar F13 launcher remain native compositor actions.

See [changes, verification and deployment notes](docs/PACKAGED-NATIVE-SESSION-20260920.md).
Dated source-build reports describe a superseded revision, not this installer.

## Opt-in Kanshi and native Fuzzel icons - 19 September 2026

Kanshi is no longer part of the unconditional desktop package class. The host
policy controls its package, wrapper, generated configuration, resource drop-in
and account-local activation together. Disabled installs validate absence;
known previous managed activation can be reconciled without deleting custom
configuration. Computer Management now defaults to graphical Fuzzel; explicit
`--terminal` retains the terminal adapter. Categorized application rows use the
effective desktop entry's native `Icon=` metadata, with safe fallback and exact
selection-to-desktop-ID mapping.

See [implementation, validation and deployment notes](docs/KANSHI-FUZZEL-FOLLOWUP-20260919.md).
The private Zoom/Discord Xwayland boundary is retained. The earlier labwc/KWallet
source-build path is removed by the 20 September revision above. Earlier hardware
acceptance limitations are not reclassified as passing by these changes.

## Hardware tuning and protected resctl documentation - 17 September 2026

See [the current scoped refactor and validation report](docs/HARDWARE-TUNING-REFACTOR-20260917.md), [operator guide](docs/hardware-tuning/README.md), and [on-host acceptance](docs/hardware-tuning/ACCEPTANCE.md). Intel tuning is selectable on the two main and two Flex profiles; NVIDIA tuning only on the main pair. Other profiles retain the same values with both enable flags false. Autostart and higher-risk tuning permissions remain off. CPU policy requires an explicitly chosen single owner; thermal protection is retained.

The resctl installer now publishes release documentation to root-controlled `/usr/local/share/doc/resctl-bench`, not the account-owned `/data/docs`. Its trust checks, release pins, noexec protections, credential-dropped probes and no-clobber publication remain intact. Current evidence is under `validation/tuning-refactor-20260917/`; dated reports below remain historical.

## Independent per-profile release pins - Revision 5, 20 September 2026

Each desktop profile owns its resctl-bench release pins. Different profiles may
use different URLs, SHA-256 digests, tags, versions and size/member limits.
`python3 -I -B tools/check_resctl_bench.py` validates each profile independently
using the target installer's existing policy; it never compares profiles.
Both `make build` and `tools/build.py --check` retain this offline validation.

All 13 shipped profiles currently use the requested `resctl-bench-v0.0.2-P15s`
release, version `2.2.6`, the `-fe7971477fed192a` asset, and SHA-256
`5521053cd583b6d01c608a9deff7dabe4ebb5e07eb314d8819a9833ff5684d12`.
These are initial defaults, not an equality constraint or a locked release.
To change a single profile, update its related pins coherently; no other profile
needs changing. Tomat's tag, URL and SHA-256 are also independently configurable.

Each profile still requires literal, unique, complete assignments and a URL
consistent with its own tag/version and the supported origin/architecture.
Malformed configuration stops publication. The installer still hashes the
actual downloaded archive before extraction or installation; the offline build
does not confirm remote availability or that a digest matches remote bytes.
No downloaded installer executes and native-target smoke checks remain intact.

See [the Revision 5 report](FOLLOWUP-20260920-r5.md) and
`validation/profile-pin-independence-20260920-r5/`. Earlier dated reports,
including [the 17 September repair](docs/RESCTL-RELEASE-REPAIR-20260917.md),
describe historical behavior; their cross-profile equality requirement is
superseded. Resource limits and power/session behavior are unchanged.

## Package limits and package-safe power actions - 17 September 2026

The local APT publisher now accepts packages up to **2 GiB**. Retained Debian
archive validation and streaming digests have a separate **4 GiB** ceiling;
ChatGPT transport uses the publisher's 2 GiB limit. Existing application-specific
lower transport and extraction budgets are unchanged.

Managed desktop logout, suspend, reboot and poweroff (including the `shutdown`
alias), plus greeter reboot/poweroff, now wait for the actual POSIX locks on both
`/var/lib/dpkg/lock-frontend` and `/var/lib/dpkg/lock`. No applications are closed
while waiting, and no timeout authorizes an upgrade-interrupting fallback. A
required `sleep.target` guard also reserves these locks through sleep/resume for
idle/lid/systemd suspend paths. Administrator bypasses and physical power loss
are not covered.

See the [implementation, deployment and validation report](docs/PACKAGE-POWER-GUARD-20260917.md)
and `validation/package-power-guard-20260917/` for this revision's evidence and
remaining inherited validation failures. The payload, manifest and preseed pins
are rebuilt together. The [earlier archive repair](docs/RETAINED-ARCHIVE-REPAIR-20260917.md)
and its 1 GiB policy are historical; its file-hardening repairs remain included.

Current desktop power lifecycle and resctl-bench integration:
[implementation and deployment checks](POWER-RESCTL-2026-09-16.md),
[current validation](POWER-RESCTL-VALIDATION.md). Reboot/poweroff synchronously
quiesce the desktop, keep D-Bus available, and perform one direct single-force
handoff without intermediate shutdown targets. All 13 profiles install the
pinned resctl-bench release. This supersedes R6 power dispatch only; the
[R6 independent I/O policy](POWER-AND-IO-POLICY-R6.md) remains unchanged.
Earlier dated reports, manifests and validation logs are historical.

Current SSH/GitOps/debugsys lifecycle review and selective PID namespace changes:
[14 September 2026 review](docs/LIFECYCLE-ISOLATION-REVIEW-20260914.md).
Its validation records are in `docs/validation-lifecycle-20260914/`; earlier reports
remain historical, not acceptance results for this revision.


## Broker-free labwc workspaces

The workspace taskbar broker has been retired; the native current-workspace
window switcher is retained. Stock labwc/Waybar does **not** provide separate
per-workspace taskbars without the removed observer. Consequently, the native
task strip is enabled only for a single workspace and is omitted for 2--12
workspaces rather than showing a global list. See the current
[broker-retirement and workspace behavior report](WORKSPACES-NO-BROKER.md) for
removal details, validation results, deployment limits and the outstanding
per-workspace-taskbar requirement.

Local APT policy, source normalization and desktop power changes: see [`local-apt-init` and session handoff](docs/local-apt-session-policy/README.md) for commands, migration, validation and safety limits.

## R4 CUDA-legacy compatibility repair

Explicit `addon/cuda-legacy` selection now authorizes the NVIDIA Debian 12 amd64
archive as trusted/insecure. SHA-1 signatures, missing keys and stale metadata
are not installation gates for that one archive. No extra flag is needed.
All earlier bootstrap, debconf, fatal-state and target repairs remain included.
The current [metadata portability correction](docs/INSTALLER-METADATA-PORTABILITY-20260919.md)
removes the external metadata-command dependency from both installer and target
helpers, including IOCost and the private environment-file path.
See [the current report](docs/ENGINEERING-REPORT.md),
[the CUDA trust scope](docs/CUDA-LEGACY-TRUST-R4.md), and
[the retained R3 debconf repair](docs/DEBCONF-TRANSPORT-R3.md).
Run `make test-cuda` for real APT compatibility and isolation regressions.
All generated payloads and pins are supplied together.


Debian unattended-install repository for desktop systems. The 2026-09-07 R2 repair
retains all 13 supplied profiles and the intentional mixed-suite package policy.
Partitioning remains destructive: only an explicit safe device or a unique safe
candidate is accepted. Read the deployment prerequisites before using real disks.

Read **[the R2 bootstrap portability repair](docs/BOOTSTRAP-PORTABILITY-R2.md)**
for the startup regression and the new execution tests.

Start with **[the repair and operations guide](docs/INSTALLER-HARDENING-2026-09-07.md)**,
**[the sanitized incident inventory](docs/INCIDENT-2026-09-07.md)**, and
**[the security boundary](SECURITY.md)**. Executed validation results are in
`validation/summary.json` and `validation/release-checks.json`.
The earlier dated reports are historical, not current deployment instructions.
No physical installation or firmware acceptance result is implied by local tests.

**Private build:** browser configuration and coverage data contain personal
bookmarks. Do not publish this personalized tree to a public repository or an
unrestricted web server. No reusable credentials are supplied by this refactor.

The Labwc desktop, desktop application classes, workstation developer tools, and their user units stay here. GitLab Runner, server-suite, web/database service classes and server-only profiles are not included. SSH, Podman, CrowdSec and workstation Aptly publishing remain where the original desktop used them.

## Build before publishing

The supplied snapshot is already built. After changing **any** runtime file,
profile, class, installer script or target asset, run from this repository root:

```sh
python3 -B tools/build.py
python3 -B tools/validate.py
```

Builds require Python 3.11 or newer, a POSIX shell and BusyBox on the publishing
host. Complete validation also needs Bash, Dash and Debian debconf tools; the
isolated bootstrap tests need root/CAP_SYS_CHROOT on a disposable test host.
The installer transport itself does not require Python or curl.

Commit or deploy the entire repository, including these generated files:

```text
d-i/forky/preseed.cfg
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
```

The generated preseed pins the bootstrap transport and complete payload with
SHA-256 hashes. Publish them together; do not deploy individual edited files over
a running installation, omit the payload, or replace the payload with a Git LFS
pointer. `python3 -B tools/build.py --check` detects stale generated files.
The complete pinned snapshot is fetched and validated before partitioning. Later
phases read its local cache instead of repeatedly downloading repository files.
The browser generator runs as part of this build. Its editable inputs are in
`browser-config/`; generated policies and exports live under `hooks/target/`.
Explicit `addon/cuda-legacy` selection uses the NVIDIA Debian 12 amd64 archive
with a source-local trust exception, without a key download, Signed-By fingerprint
pin or signature/freshness gate. It is still fetched over verified HTTPS, and APT
still checks downloaded package content against the acquired index. This is an
intentional archive-authentication risk, not proof of package provenance. The
temporary source is removed after package repair and at finish-install. Modern
CUDA, Debian suites and other repositories retain their independent policies.


## Repository layout

```text
.
|-- README.md
|-- SECURITY.md
|-- Makefile
|-- browser-config/            # private normalized bookmark and export inputs
|-- tools/                     # deterministic build and validation
|-- docs/                      # migration ledger, architecture and validation notes
|-- validation/                # actual offline test and audit results
`-- d-i/forky/
    |-- repo.env               # role, defaults and repository path contract
    |-- preseed.cfg            # generated entry point; do not edit directly
    |-- payload.manifest       # generated per-file SHA-256 inventory
    |-- payload.tar.gz         # generated immutable runtime source snapshot
    |-- common.cfg
    |-- fragments/
    |-- classes/
    |   `-- configs/target-assets.tsv
    |-- hosts/
    |   |-- installer/         # shared identity, runtime, account, layout and boot envs
    |   `-- profiles/          # all profile .env files, without family subdirectories
    |-- hooks/
    |   |-- installer/
    |   |   |-- apt-setup/
    |   |   |-- base-stage.d/
    |   |   |-- d-i/
    |   |   |-- finish-install.d/
    |   |   |-- partman/
    |   |   |-- pre-pkgsel.d/
    |   |   `-- late_command.sh
    |   `-- target/            # shared + this role + hardware payloads
    |-- scripts/               # common, preseed, early, partman, late, runtime, firstboot
    `-- tests/
```

Desktop build/install helpers additionally live in `scripts/desktop/`.

## Serve over a trusted lab network

Prefer validated HTTPS on a private installation network, or trusted local media.
The following HTTP example is only for an isolated, trusted lab. It authenticates
neither the initial preseed nor its replacement by a network attacker; SHA-256
pins inside that preseed cannot repair that trust boundary. Restrict access to
installation clients and publish one complete snapshot atomically.

```sh
python3 -m http.server --bind 0.0.0.0 8000 --directory .
```

For the example lab server, the source portion of the installer boot arguments is:

```text
auto=true priority=critical url=http://192.168.50.122:8000/d-i/forky/preseed.cfg
```

Add the appropriate original class selection and deployment-specific account,
network and storage configuration. These source examples are not a claim that an
arbitrary host can safely use a fixed-disk profile. The current role default is:

```text
classes=prod;desktop;standard;static;software;timeshift;podman;crowdsec;whisper;btrfs-de
```

An explicit minimal role selection suitable for a bootstrap smoke test is:

```text
classes=prod;desktop;standard;dhcp;ssh
```

Hardware detection and profile constraints still apply. Enter boot arguments in
the bootloader, not as an unquoted shell command containing semicolons.

## Local media (`file=`)

Copy the **whole tree**, not just `preseed.cfg`, onto the mounted media:

```text
auto=true priority=critical file=/hd-media/debian-preseed-de/d-i/forky/preseed.cfg
```

`preseed/file=` is also supported. `file=` names an absolute preseed file, not a
directory. Repository-relative includes are staged as absolute `file:///...`
locations. Local profile edits without rebuilding fail early instead of silently
installing an old snapshot. Use local paths without spaces or shell metacharacters.

## Required private deployment configuration

Review `d-i/forky/hosts/installer/` and the selected disk profile before booting.
The original desktop integrations still require deployment-specific credentials,
including the account password, primary GPG passphrase, Fruux username/password
and Telegram token/chat ID when that desktop setup runs. This refactor does not
invent credentials, remove integration requirements, or make late desktop checks
happen before partitioning.

Supply trusted shell assignments through `/preseed.env` in a private initrd,
owned by root and preferably mode **0400 or 0600**. Root-owned files with extra
read bits (such as 0644) are made private before loading; unsafe ownership, links,
write/execute permissions or parent directories are rejected. The reader uses d-i
applets without requiring `stat`. Recognized names include `PRESEED_ROOT_PASSWORD`,
`PRESEED_PRIMARY_PASSWORD`, `PRESEED_PRIMARY_GPG_PASSPHRASE`,
`PRESEED_GIT_SSH_PASSPHRASE`,
`PRESEED_FRUUX_USERNAME`, `PRESEED_FRUUX_PASSWORD`, `PRESEED_TELEGRAM_API_KEY`
and `PRESEED_TELEGRAM_CHAT_ID`. Optional integrations have additional fields;
consult `d-i/forky/scripts/common/credentials.sh` for the complete mapping. Use single-quoted shell assignments with proper escaping; this is a
trusted shell file, not an untrusted data import. An exact command-line parameter
overrides its corresponding env value for the legacy credential inputs; absent
parameters use `/preseed.env`. The managed Git SSH passphrase is deliberately
read ONLY from `/preseed.env`, never from the command line or inherited environment.
An explicitly empty root_password is an error, not permission to ignore the override.
Local root login is enabled; SSH root login remains prohibited. Keep secrets out of source
control, public URLs, command lines and the distributable payload.

For the desktop Git identity, also inject root-owned `/git_ed25519` and
`/git_ed25519.pub` (0600) into that **private** initrd. The private key must be
passphrase-encrypted Ed25519, and `PRESEED_GIT_SSH_PASSPHRASE` must unlock it.
Keep all three inputs and private boot media OUTSIDE the served checkout.
They are never fetched over the seed URL or included in the generated payload.
The build refuses known private input filenames and private-key headers.

The installed desktop uses a GPG-sealed SSH passphrase and a Labwc-owned agent;
`git-ssh unlock`, `git-ssh status` and `git-ssh lock` provide the daily controls.
GitOps protection is editable in `~/.config/gitops/gitops.env`. Codex home clones
over SSH on tracking branch `mcr/main` without a home commit pin. `debugsys`
provides root-only, multi-select diagnostics and explicitly opt-in reversible
initramfs capture. See [the integration and operations guide](docs/MANAGED-GIT-DEBUGSYS-20260914.md),
also installed at `/usr/local/share/doc/managed-git/README.md`, for exact alias
semantics, recovery, security boundaries and live-target acceptance checks.

After installation, the three extension exports, `bookmark-coverage.json` and
`BROWSER-IMPORTS.md` are staged as user-owned, mode-0600 files in the configured
account's Downloads directory. Import the three exports through the extensions'
own interfaces. See `d-i/forky/hooks/target/usr/local/share/browser-imports/`.
Use `browser-devtools vivaldi --port 9222` as the ordinary user for an isolated,
loopback-only debug profile; Chromium, Edge and Chrome are also supported.

## GitHub raw URLs and redirects

For a sanitized, non-personalized build, a public raw URL can point to a matching
repository snapshot; the
full path prefix, including slash-containing refs, is retained. For example:

```text
url=https://raw.githubusercontent.com/mjcramerz/debian-preseed-de/refs/heads/mcr/main/d-i/forky/preseed.cfg
```

This is a URL-shape example, not a verified live deployment. Standard HTTP
redirect links are supported: the effective final **preseed file** URL determines
the sibling asset base, not the shortener's domain. For example:

```text
url=https://tinyurl.com/fdsgdf5
```

The short link must actually redirect to the published generated preseed; HTML
preview, JavaScript, login or CAPTCHA pages are not installer sources. Redirect
loops, non-HTTP(S) destinations and HTTPS-to-HTTP downgrades are rejected before
fetched content is accepted. Initial network setup and the first preseed download
are performed by the Debian installer image, before repository code can run.

TLS certificate validation is mandatory for repository HTTPS fetches. Legacy
`allow_unauthenticated_ssl=true` and equivalent bypass requests now fail closed.
Provision the installer image with correct CA trust and clock. Initial preseed
retrieval is performed by the image before this repository executes; this code
cannot retroactively authenticate an insecure initial download. See `SECURITY.md`.

## Profiles

Ten canonical profiles are served from `d-i/forky/hosts/profiles/`:

| Family | Normal | Multi-OS |
| --- | --- | --- |
| Generic Btrfs | `btrfs-de.env` | `btrfs-de-duo.env` |
| P15s | `btrfs-de-p15s.env` | `btrfs-de-p15s-duo.env` |
| Flex | `btrfs-de-flex.env` | `btrfs-de-flex-duo.env` |
| HP14 | `f2fs-de-hp14.env` | `f2fs-de-hp14-duo.env` |
| x360 | `f2fs-de-x360.env` | `f2fs-de-x360-duo.env` |

The logical `override-<name>` identifier resolves to
`hosts/profiles/<name>.env`. Btrfs and virtual-storage defaults select
`btrfs-de.env`; eMMC selects `f2fs-de-x360.env`. Virtual storage retains its
existing disk candidates, `/dev/vda` default and VM hooks, but has no separate
host profile or VM-specific sizing. Its generic profile still uses measured disk
and RAM capacity. Small test disks must satisfy that profile's minimum layout.
See `d-i/forky/hosts/README.md` for environment precedence and duo safeguards.

## Diagnostics and validation limits

Bootstrap failures print a `[repository] fatal:` message to stderr and the
installer diagnostic console when available. Inspect `/tmp/installer.log`,
`/tmp/install-runtime/bootstrap/`, and private `*.fetch-error` response logs.
No `preflight.ok` marker is written on repository/class/profile preflight failure.
Early, partitioning and late phase runners require that marker.

The delivered validation reports cover regression tests, loopback HTTP/HTTPS
transport, complete generated bootstrap commands, relocation integrity and
syntax/inventory checks. They do **not** certify a booted Debian installer,
partitioning, package downloads, graphical login, Secure Boot, GPU suspend or
systemd/AppArmor behavior on real hardware. See `docs/VALIDATION.md` and run the
hardware acceptance matrix before deployment to valuable disks.
