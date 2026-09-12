# Local APT repository v2: weekly, metadata-first refresh

Date: 2026-09-12. Baseline: the complete `debian-preseed-de-scoped-fixes.tar.gz` supplied in this conversation. This revision changes only local-repository discovery, refresh scheduling, its command-line entrypoint, necessary installer/AppArmor integration, tests and documentation. The earlier desktop, Whisper, session-isolation and rfkill changes are retained.

## Operational contract

**There is no repository refresh hook in APT.** `apt update` reads the already-published signed file repository and normal configured repositories. It does not run this repository's downloader. `apt upgrade` installs available candidates through APT/dpkg; refresh itself never installs software or invokes APT.

```sh
sudo apt-local-repo --add ./example.deb
sudo apt-local-repo --delete
sudo apt-local-repo --refresh
sudo apt-local-repo --list

# After addition or refresh, normal APT operations:
sudo apt update
sudo apt install actual-package-name
sudo apt upgrade
sudo apt remove actual-package-name
```

`--add` preserves the add confirmation, optional comma-separated `Depends` removals, automatic-update choice, and HTTPS URL prompt. Removing dependencies is an administrator decision and can make a package unusable. Answering `n` to automatic updates leaves the package registered, installable and removable, but causes no upstream metadata or artifact requests for it. `--delete` lists registered packages, removes the selected package and update policy, and publishes the new repository. It does not uninstall the package. Immutable old files remain available for readers holding old APT metadata; deletion is not secure erasure.

`--list` emits the private catalog as JSON, including effective policies and discovery receipts. The wrapper accepts only the documented argument forms; the old executable is removed, not retained as an alias.

## Weekly scheduling

`local-apt-refresh.timer` is enabled by the unattended installer along with `local-apt-inbox.path`:

```ini
OnCalendar=weekly
Persistent=true
RandomizedDelaySec=6h
FixedRandomDelay=true
AccuracySec=1min
Unit=local-apt-refresh.service
```

The weekly calendar boundary is Monday 00:00 in the host's timezone, with a stable per-host delay of up to six hours. A missed activation is eligible for catch-up when the timer becomes active, subject to that delay. There is no hourly poll, boot-time package download hook, or automatic installation timer. `--refresh` performs the same engine operation immediately, independently of the timer.

The oneshot service waits for `network-online.target`, has a two-hour timeout, runs with low CPU/I/O priority, a private temporary directory, a read-only system/home view, and explicit writable repository/key/source/lock paths. Network-online ordering does not guarantee Internet availability; a failed upstream check is reported, not treated as success. The inbox service allows enough time to wait for the same repository lock rather than repeatedly timing out behind a weekly refresh.

```sh
systemctl list-timers local-apt-refresh.timer
systemctl status local-apt-refresh.service
sudo journalctl -u local-apt-refresh.service
sudo cat /var/lib/software/state/last-refresh.json
```

Refresh returns 0 for a completed pass without detected errors, 3 for per-package upstream/validation failures or rejected inbox items, and 1 for fatal local/publication failures. The service does not whitelist partial failure as success. Healthy packages may publish even when a different upstream fails. The last-refresh report contains package outcomes and counters; fatal publication failures may leave the previous report in place, so use service status and the journal as well.

## Metadata discovery, not download-to-check

| Supplied endpoint | Discovery behavior |
| --- | --- |
| GitHub repository, release page, old tagged asset, or releases API URL | Canonical repository releases API; inspect public stable releases and matching `.deb` assets. The old tag/download path is not used as the update source. |
| GitLab release page or release API URL | Canonical project releases API, including nested namespaces and self-hosted GitLab release URLs. Match the intended `.deb` release link. |
| SourceForge project/file/download-mirror URL | Project RSS file feed; match package family/architecture and select the newest recognizable Debian version, with publication time as fallback. |
| Direct/raw HTTPS resource, including versionless endpoints and HTTPS redirects | Conditional HEAD using the stored ETag or Last-Modified. Retrieve the package only when the representation metadata indicates change, or an advertised recognizable version is newer. |

An old asset filename supplies an edition/architecture family hint after its version-shaped component is normalized. For example, a URL ending in `app_1.2.3_amd64.deb` can select `app_1.3.0_amd64.deb` from later releases without selecting an ARM or differently named edition. A release-page URL without a filename uses package-name/architecture matching; an ambiguous result is an error, not a guessed download. Re-add with the intended old/current release asset URL to supply the family hint.

The canonical discovery source and last published artifact receipt are separate from the administrator-supplied URL. Release metadata requests are bounded JSON/RSS GETs and use HTTP validators where available. They are not package-body downloads. SourceForge feed requests are separated by at least 30 minutes, including repeated manual refreshes; a recent cached feed is reused.

Drafts, recognizable prereleases, GitLab upcoming releases and future-dated releases are excluded. Recognizable versions are compared with Debian version ordering. An older release does not become newer merely because it was republished. Candidate architecture and edition are selected before retrieval, and actual Package/Architecture/Version are checked again after retrieval. A new release returning stale package bytes is rejected without advancing its receipt.

When GitHub provides an asset SHA-256 or size, these are checked against the retrieved bytes before ingestion. A digest matching the existing upstream archive can establish that no retrieval is necessary. Same-version conflicting digests or changed release identities are reported instead of silently replacing installed-version content.

### Direct resource details and limits

HEAD follows HTTPS-only redirects and uses `If-None-Match` when an ETag is recorded, otherwise `If-Modified-Since`. Both a 304 and a 200 carrying unchanged validators avoid downloading the body. For a changed representation, the GET uses the discovered strong ETag as `If-Match`, or Last-Modified as `If-Unmodified-Since` when available. Response validators, declared size and archive validity are checked; a HEAD/GET race is rejected. Download validators are committed only with the accepted package transaction.

A timestamp/ETag is an indication of representation change, **not a cryptographic proof of a newer application version**. The Debian control version remains authoritative. Downgrades and different bytes under an unchanged version are rejected. A direct server changing validators for identical bytes can be acknowledged after validation without replacing the package version. Weak ETags are accepted as HTTP cache validators, not interpreted as content hashes.

**An arbitrary locally supplied package cannot be proved equal to an unversioned remote resource from an opaque ETag alone.** At registration, or on the first refresh after migration from the previous implementation, a metadata-only baseline may therefore be recorded with `observed_only: true` and an explicit warning. This does not assert that the supplied package was the newest remote version. Subsequent representation changes can be detected without repeated body downloads. A release-provided matching digest or recognizable newer version provides a stronger initial decision. The code never pretends that local filesystem modification time establishes a remote release version.

An endpoint that rejects HEAD, supplies neither usable ETag nor Last-Modified, returns HTML/API data instead of a binary resource, changes validator type incompatibly, or returns malformed metadata is reported as unavailable. There is **no automatic GET fallback merely to discover whether its package changed**. For such a provider use a release-discovery endpoint, or add later packages manually. HTTP redirect downgrades, embedded URL credentials and nonstandard HTTPS ports are rejected.

Public release APIs are supported, not private authenticated APIs or arbitrary HTML scraping. GitHub/GitLab discovery is bounded to the returned page of up to 100 releases; SourceForge requests up to 100 recent feed entries and enforces a hard parse bound. A matching asset outside that window is not silently guessed. Recognizable version naming is necessary for initial version-only comparison; nonstandard naming can require an explicitly reported metadata baseline. Provider rate limits, outages and API/schema changes remain possible and are surfaced as errors while the last-good repository remains usable.

### Existing managed prebuilt applications

Discord and Ledger now expose a metadata-only probe through the existing Perl verifier bridge. Discord examines its bounded host/module manifest; Ledger examines its bounded release YAML and advertised digest. The gate compares against the **published repository package**, not only the installed package, so deferring `apt upgrade` does not repeatedly download the same already-published update. Discord module changes with an unchanged host version still produce a new local package revision.

Postman and Tuta use HEAD metadata gating before their existing verification/download path. Their endpoint metadata is checked again after a retrieved distribution. Existing signature/hash validation, prebuilt binary packaging, and managed ChatGPT dpkg policy are retained. No vendor application source is rebuilt or compiled.

## Transactions and recovery

```text
manual add or changed upstream candidate
  -> private /var/lib/software/inbox partial file
  -> complete .deb + transaction policy/receipt
  -> validated Package / Version / Architecture and payload
  -> immutable repo/pool/<package>/<sha256>/...deb
  -> signed snapshot + catalog
  -> atomic repo/current switch
  -> remove completed inbox transaction
```

Packages, Packages.gz, Release, InRelease, Release.gpg, immutable pool files and by-hash indexes remain in `/var/lib/software/repo`. The repository catalog/update receipt is committed with the signed snapshot rather than in an independent mutable success marker. A signing failure leaves the previous `current` pointer and old metadata receipt selected, with the completed inbox transaction available for retry. A failed or rejected download cannot poison future update detection by recording itself as already published.

Manual refresh, weekly refresh, inbox processing, addition and deletion share the existing root-owned flock. They do not take APT/dpkg database locks. Existing readers retain valid immutable indexes and pool paths while a new snapshot is published. Unchanged refreshes do not re-sign or republish a snapshot solely because the timer ran.

Invalid inbox items are quarantined with a `.reason` file under `/var/lib/software/rejected`. Producers other than the wrapper must write a `.part` file and rename only a fully written `.deb` into the root-private inbox; streaming into a watched `.deb` filename is not supported. Snapshot/pool garbage collection is intentionally not introduced; retained generations can consume disk space.

Local signing establishes the authenticity of this host's repository, not the trustworthiness of an unknown vendor package. HTTPS, metadata hashes and archive validation do not make a malicious maintainer script safe. Adding a package remains a privileged trust decision.

## Fresh installations and existing-host migration

The updated unattended installer stages the renamed wrapper and engine/bridge, initializes the repository, installs the new service/timer, and enables the timer/path units. The removed APT hook and wrapper are absent from the source payload. The payload archive, file manifest and generated preseed pins must remain synchronized; this delivery includes their regenerated versions.

Updating this served installer source does **not** update an already installed host automatically. For an existing host, first review/backup local modifications, stop repository maintenance while replacing the affected files, and deploy the changed helper scripts, units and repository-related AppArmor rules. Preserve the existing repository, source, signing key, catalog and local AppArmor customizations. The change ledger identifies the exact paths; do not copy the entire target overlay onto a live system indiscriminately.

After the updated files and AppArmor rules are deployed/reloaded:

```sh
# Explicit migration: removes only the recognized old managed entrypoints.
sudo /usr/local/libexec/local-apt-repository init
sudo systemctl daemon-reload
sudo systemctl enable --now local-apt-inbox.path local-apt-refresh.timer

# Optional immediate check, otherwise wait for the weekly activation.
sudo apt-local-repo --refresh
sudo apt update
```

Initialization deletes the previous shipped `local-add-deb` only if its exact file digest matches, and deletes the old `90-local-apt-repository` only if it contains the single recognized hook plus optional whole-line comments/whitespace. Both are validated before either is removed. A customized script/hook causes an explicit error; review and retire its refresh action manually rather than silently deleting administrator commands. There is no compatibility wrapper that can accidentally keep the old workflow alive. The previous implementation already retired the older download/install timers; the installer retains that retirement logic.

## Validation and limits

Validation logs are under `validation/`; tests are under `tools/tests/` and the existing `d-i/forky/tests/`.

- 64 scoped tests passed, including metadata normalization/selection, release and direct validators, SourceForge feed safety/throttling, static packages, downgrade/same-version guards, stale-release rejection, body/metadata mismatch, cache behavior, no-op refresh, legacy migration, signing recovery, and retained desktop/Whisper/panel regressions.
- Real curl/TLS fixtures exercised unchanged HEAD/304 (no GET), changed representation retrieval, no-validator/HEAD-unsupported refusal, a bad download followed by successful retry, and HTTPS-to-HTTP redirect rejection. Test-only loopback TLS settings do not relax production URL/TLS rules.
- Real isolated APT accepted the signed file repository, saw the candidate advance from 1.0 to 2.0 after explicit refresh, and made no request to the fixture upstream during `apt update`. No package was installed.
- 34 existing installation regressions and 22 lifecycle regressions passed. The 10-test repository-integrity suite passed its other 9 tests but retained the already-reported 13 host-profile provenance subtest failures. Those profiles and their old provenance ledger remain byte-identical to the supplied baseline; no out-of-scope correction was made.
- The serialized installer payload, manifest and generated preseed pins pass `tools/build.py --check`; the browser-artifact check also remained current. Changed Python syntax and shell scripts are checked. The changed AppArmor profile passed parsing with kernel loading/cache disabled; this is not an enforcement test.
- `systemd-analyze verify` passed for both repository services, the timer and inbox path. The actual helper was temporarily staged only to satisfy executable-path validation; no systemd service ran in this container.
- The Perl bridge could not be fully loaded/executed here: existing Moo/MooX dependencies are absent. An attempt to obtain test-only Debian dependency packages was blocked by container DNS resolution, before any package download or installation. The original Perl-dependent suite retains this environment limitation; vendor probes/signatures were inspected but not exercised against live providers.
- No full unattended installation, live weekly activation under PID 1 systemd, live third-party provider download, enforcing AppArmor session, or actual software upgrade was performed. Those are target-host validation steps, not claimed successes.

The old report in `docs/scoped-fixes-2026-09-12/` is retained as history; this document supersedes its local-APT hook/CLI/update-discovery descriptions. No application was compiled or rebuilt to perform this work. Tiny Debian fixture archives and the existing installer deployment archive were serialized for tests/deployment only.

## Primary protocol/platform references

These references informed the implementation; provider-specific and live-host behavior still require the validation above.

- HTTP HEAD, ETag, Last-Modified and preconditions: https://www.rfc-editor.org/rfc/rfc9110.html
- GitHub public releases and assets: https://docs.github.com/en/rest/releases/releases
- GitHub asset digests: https://github.blog/changelog/2025-06-03-releases-now-expose-digests-for-release-assets/
- GitLab releases API: https://docs.gitlab.com/api/releases/
- SourceForge RSS and polling guidance: https://sourceforge.net/p/forge/documentation/RSS/
- systemd timer semantics: https://manpages.debian.org/trixie/systemd/systemd.timer.5.en.html
- curl transport options: https://curl.se/docs/manpage.html
