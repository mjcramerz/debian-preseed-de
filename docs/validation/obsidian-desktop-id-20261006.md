# Obsidian desktop entry integration: 2026-10-06

## Reported failure and cause

The unattended installation stopped with:

```text
FATAL: obsidian package payload is missing desktop entry: /usr/share/applications/obsidian.desktop
```

The release update retained the previous desktop basename in the installer and
update worker. Obsidian's developer reports that the Debian package installs
`md.obsidian.Obsidian.desktop`, matching its native Wayland application ID and
`StartupWMClass`. This is primary maintainer evidence, rather than an inference
from the filename of the downloaded archive.
[Maintainer report](https://github.com/electron-userland/electron-builder/issues/10173).

All ten profiles already pin the correct Obsidian 1.14.4 amd64 Debian asset and
SHA-256. The publisher's metadata was checked again; those pins remain valid.
[Published asset and digest](https://github.com/obsidianmd/obsidian-releases/releases/expanded_assets/v1.14.4).

```text
85b10dcba6edfc1c0460a6d18260cf31c30447a444bd858a6440b9c9c8806d25
```

## Corrected consumers

| Source under `d-i/forky/` | Change |
| --- | --- |
| `scripts/late/software.sh.tmpl` | Require the current desktop entry in the archive, check its installed presence, and validate that same entry after installation. |
| `hooks/target/usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/Obsidian.pm` | Validate the current desktop path when downloading an update. |
| `hooks/target/usr/local/lib/perl5/site_perl/apt-repo-local/APTRepoLocal/Servicing/CLI.pm` | Use the same path in update/import and installed-payload specifications. |
| `hooks/target/usr/local/bin/labwc-sync-application-launchers.tmpl` | Discover the current vendor desktop ID first, retain the older vendor basename as a fallback, and preserve the vendor ID when publishing the managed launcher. |
| `scripts/desktop/verify.sh.tmpl` | Include the current account-local launcher in the existing ownership/mode verification. |
| `hooks/target/etc/apparmor.d/desktop-wrappers.tmpl` | Permit the update worker to read the exact current system desktop entry. The native parser confirms read access without write or execution access. |

Package version, architecture, executable, library, digest and required desktop
checks remain enforced. No aliases are created in the vendor package directory.
Source compilation and private Xwayland policy were not changed. The requested
compatibility target remains Debian Forky with systemd 261.2.

The related Sleek desktop assumption was also reviewed. Its tagged 2.0.29
configuration uses electron-builder 26.16.1 and does not enable
`linux.syncDesktopName`. Electron-builder's **v26** documentation explicitly
retains the executable basename when that option is absent. Retaining
`sleek.desktop` is therefore supported by the tagged configuration and documented
v26 behavior; it is not a claim that Sleek's vendor archive was inspected.
[Tagged configuration](https://raw.githubusercontent.com/ransome1/sleek/v2.0.29/electron-builder.yml),
[tagged dependency lock](https://raw.githubusercontent.com/ransome1/sleek/v2.0.29/package-lock.json),
[v26 filename behavior](https://www.electron.build/v26/docs/linux/).

## Validation

These checks were run from the repository root:

```sh
python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_obsidian_desktop_id_20261006.py -v
python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_desktop_release_integrity_20261005.py -v
python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_apparmor_incidents_20261004.py -k test_native_parser_permissions_cover_nested_documents_usb_and_unclean_journals -v
python3 -B tools/check_logging.py
python3 -W ignore::EncodingWarning -B tools/build.py
python3 -W ignore::EncodingWarning -B tools/build.py --check
python3 -W ignore::EncodingWarning -B tools/check_shells.py
python3 -W ignore::EncodingWarning -B tools/check_preseeds.py
git diff --check
```

| Check | Observed result |
| --- | --- |
| Obsidian regression suite | **9 passed**. Reproduces the reported failure with the old basename, accepts the current layout through installer/post-install checks and both updater paths, and rejects a missing current desktop entry. Launcher synchronization preserves the native ID, MIME types, icon and window class under the managed wrapper, with mode 0600. |
| Desktop release integrity suite | **16 passed**, including all ten profile URL/hash policies. |
| Effective AppArmor permissions | **1 passed**, using native offline parser expansion. Includes the current and legacy Obsidian system desktop entries as read-only inputs to the update worker. |
| Logging catalog | **PASS**: 111 variables, 354 templates, 78 logging templates, ten profiles. |
| Snapshot generation | **PASS**: 1,704 payload members; zero browser artifacts changed. |
| Snapshot check | **PASS**: snapshot, pins and preseed are current. |
| Archive/manifest inspection | **PASS**: all 1,704 members are unique regular files with canonical mode/owner/timestamps; the six changed sources match their archive bytes and manifest digests, and preseed binds the current payload/manifest hashes. |
| Shell parsing | **PASS**: 352 shell files, 715 parser checks. |
| Preseed/debconf validation | **PASS**: 59 preseed files; all four generated commands survived private debconf read-back unchanged. |
| Diff whitespace check | **PASS**. |

The new Debian archives are synthetic fixtures built with native `dpkg-deb`.
Archive/control inspection, the actual shell payload/post-install checks,
Perl package validation and artifact digest/size checks are real. APT/chroot
installation, HTTP transport, prevalidated update metadata and vendor-root
ownership are explicit test doubles. The tests run no vendor executable or
maintainer script. Launcher fixture paths stay inside a private temporary home
and restore the caller's umask. The AppArmor check does not load kernel policy.

### Existing broader checker failure

This additional check was run and failed:

```sh
python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_categorized_menu.py -k test_all_project_desktop_entries_validate_after_template_rendering -v
```

The local native desktop validator rejects the `DesktopNames` key in the
existing `hooks/target/usr/share/wayland-sessions/labwc.desktop`. An isolated
validation of the file from **HEAD** reproduced the same error, and its bytes
equal the working-tree file. The session file and this broad test are unchanged
by the Obsidian fix. This failed check is recorded separately from the 26 passing
targeted tests; it is not being reported as a passing application validation.

## Generated products and deployment boundary

The regenerated snapshot contains all six changed source members. Serve the
complete consistent repository snapshot when retrying the installation.

```text
payload.tar.gz   daf3ec302ea7f2028d36a68b7061987e023b72f32bf82c4dec2d1aebaa4d4dd4
payload.manifest 9b2ec1ca4cfa6e184d463576c3d8be2dfcbd43de41d87748fc3b5925f80504e0
preseed.cfg      4e760d083be8f0e94cd2cd2a8f18ffe9f650108ece8cadeb7c4fd06d022ef8e9
```

The local validation environment reports Python 3.14.7, dpkg-deb 1.23.11,
AppArmor parser 4.1.8 and systemd 262. The requested systemd 261.2 target was
preserved. Downloading the authentic Obsidian Debian archive failed because the
shell environment could not resolve `github.com`, including the approved retry.
No authentic vendor archive, full unattended installation, GUI session or live
target AppArmor enforcement was exercised in this follow-up. No deployment,
commit or push was performed.
