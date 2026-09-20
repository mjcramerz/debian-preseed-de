# debian-preseed-de

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

## resctl-bench release pin repair - 17 September 2026

All 13 desktop profiles now pin `resctl-bench-v0.0.2-P15s`, version `2.2.6`,
including the `-aa3786abb93aa646` asset build ID and the requested archive SHA-256.
The installer accepts the upstream 16-hex build-ID filename and reports URL
validation separately from malformed or mismatched SHA-256 values. Archive and
member checksum verification remain mandatory; no downloaded installer executes.

`python3 -I -B tools/check_resctl_bench.py` validates all eight profile pins with
the target installer's actual policy, without sourcing the profiles or using
the network. Both `tools/build.py` and `tools/build.py --check` run this gate
before generating release products. Missing, duplicate, nonliteral, inconsistent
or invalid pins stop publication rather than surfacing late in d-i.

See [the current repair and deployment report](docs/RESCTL-RELEASE-REPAIR-20260917.md)
and `validation/resctl-release-20260917/`. The earlier resctl release pins and
validation reports below are historical. The 2 GiB publisher ceiling, 4 GiB
retained-archive ceiling, and package-safe power flows remain unchanged.

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

All existing values, including sizing and hardware policy variables, remain in:

```text
d-i/forky/hosts/profiles/btrfs-de-dual-flex.env
d-i/forky/hosts/profiles/btrfs-de-dual-main.env
d-i/forky/hosts/profiles/btrfs-de-dual.env
d-i/forky/hosts/profiles/btrfs-de-flex.env
d-i/forky/hosts/profiles/btrfs-de-main.env
d-i/forky/hosts/profiles/btrfs-de.env
d-i/forky/hosts/profiles/btrfs-desktop.env
d-i/forky/hosts/profiles/f2fs-de-cbook.env
d-i/forky/hosts/profiles/f2fs-de-dual-cbook.env
d-i/forky/hosts/profiles/f2fs-de-dual.env
d-i/forky/hosts/profiles/f2fs-de.env
d-i/forky/hosts/profiles/f2fs-desktop.env
d-i/forky/hosts/profiles/vm-desktop.env
```

The logical `override-<name>` identifier remains compatible internally, although
its physical source is now `hosts/profiles/<name>.env`. Baseline profiles retain
`btrfs-desktop.env`, `f2fs-desktop.env` and `vm-desktop.env` fallback names. See
`d-i/forky/hosts/README.md` for the unchanged environment precedence.

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
