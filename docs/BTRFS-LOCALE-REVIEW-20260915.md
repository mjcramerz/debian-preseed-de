# Btrfs features and installer/target locale correction

Date: 2026-09-15

## Delivery basis and scope

This revision starts from `debian-preseed-de-gpg-recipient-fixed.tar.gz`, SHA-256
`727a50673f808e0062ac760772ba8cbb31fdf50de58eaa8fdf1b47ffcbcc51ac`.
All 1,837 prior regular files and their modes are retained. Only two existing
production files change, with three regenerated payload/preseed artifacts:

- `d-i/forky/hosts/installer/layout-btrfs.env`
- `d-i/forky/scripts/common/target.sh`
- `d-i/forky/payload.tar.gz`, `payload.manifest`, `preseed.cfg`

The new regression module and this revision's review/evidence are additions.
The adjacent archive verification JSON records the final complete file count,
all file hashes and extraction checks. No native component was compiled, no
package was added to the repository, and no physical disk was formatted.

## 1. Btrfs: merge free-space-tree into --features

The ROOT, HOME and OPT option strings previously contained:

```text
--features extref,skinny-metadata,no-holes --runtime-features free-space-tree
```

All three now contain:

```text
--features extref,skinny-metadata,no-holes,free-space-tree
```

The feature is retained, not removed. The xxhash checksum, single data profile,
DUP metadata, 16384-byte nodes, volume labels, partition sizes, formatting gates,
subvolumes, and mount/boot `space_cache=v2` policy are unchanged. All eight
Btrfs/VM host compositions receive this canonical policy. No profile-specific
copy of the deprecated option remains in active configuration.

The supplied installer.log shows btrfs-progs 6.14 issuing the deprecation
warning for ROOT, HOME and OPT. Upstream documents merging runtime features
into `-O` / `--features` in btrfs-progs 6.3. This change uses that interface; it
does not introduce a fallback to the deprecated option or require a new kernel.

An older installation's log can still contain the formatter's informational
historical-defaults note mentioning `-R`. That is upstream tool output, not
an active option in this repository. Historical review files and negative tests
also deliberately retain the old diagnostic/option as evidence.

## 2. target_exec: normalize both sides of the boundary

The preceding source contained a partial locale fix: it removed LOCPATH and
LANGUAGE and set LC_ALL=C before in-target, then LANG/LC_ALL=C.UTF-8 for the
command. It did NOT remove inherited per-category locale variables, normalize
bridge LANG, constrain in-target's locale re-selection, or normalize the chroot
executable itself. Overriding LC_ALL concealed stale values rather than removing
them; a later child unsetting LC_ALL could reactivate those values.

The correction is in the canonical source, not merely in documentation:

| Boundary | Behavior |
| --- | --- |
| Caller | Locale and Debconf environment remain unchanged after success or failure. |
| Before in-target or chroot | Set LC_ALL=C first, then LANG=C; clear inherited categories and lookup paths. |
| in-target setup/cleanup | Set IT_LANG_OVERRIDE=C so chroot-setup.sh does not reselect an unavailable installer locale through debconf. |
| Target command via in-target | Explicitly remove locale categories/paths again; set LANG=C.UTF-8 and LC_ALL=C.UTF-8. Retain Debconf passthrough and proxy setup. |
| Target command via chroot | Keep the existing clean env -i target environment and UTF-8 defaults. |
| Explicit caller command override | A command such as `target_exec env LC_ALL=C ...` still works. |

The cleared categories are LC_CTYPE, LC_NUMERIC, LC_TIME, LC_COLLATE,
LC_MONETARY, LC_MESSAGES, LC_PAPER, LC_NAME, LC_ADDRESS, LC_TELEPHONE,
LC_MEASUREMENT and LC_IDENTIFICATION. LANGUAGE, LOCPATH, NLSPATH and GCONV_PATH
are removed too. IT_LANG_OVERRIDE is installer-only and is removed from the
target environment.

Setting LC_ALL=C BEFORE unsetting categories is intentional: Bash reevaluates
locale settings while unsetting them. Tests caught intermediate warnings with
the reverse order; the final implementation emits no such warnings in the
invalid-locale fixtures.

Normalization uses shell builtins in the installer. GNU env's `-u` operations
execute INSIDE the target through its pre-existing `/usr/bin/env`; this adds no
installer-side stat, locale, Python, GNU env or package-install dependency.
The function's subshell confines environment mutation to the command. Argument
quoting, stdin, descriptor 3, target-root selection, failure statuses and the
existing refusal to use in-target for a nondefault root are covered by tests.

The normal installed desktop locale files, locale generation policy and
login environment are unchanged. The two locales above are command-transport
defaults, not a change to the user's preferred desktop language.

## 3. Preserved integration

The source-change comparison confirms that all other prior regular files are
byte-identical, apart from the three generated artifacts. A selected inventory
also records hashes for 276 unchanged integration files covering AppArmor,
systemd, SSH/GPG, GitOps, debugsys, Codex, profiles and power actions.

The managed GPG recipient correction and private SSH identity flow are retained.
The 29 real-GPG/recipient/bootstrap regressions pass again. The previous minimal
BusyBox no-stat regression also passes: no installer-side stat dependency is
reintroduced. No AppArmor permission, service namespace option, security policy
or authentication exception is changed by this revision.

## 4. Validation and limitations

See `BTRFS-LOCALE-VALIDATION-20260915.md` and
`validation/btrfs-locale-fix-20260915/` for actual results, baseline comparison,
source diff, environment captures and payload verification.

The new tests cover poisoned caller environments under Dash, Bash and BusyBox
ash; hostile locale re-injection by an in-target fixture; preserved passthrough,
proxy, stdin and descriptor behavior; caller environment restoration; explicit
locale overrides; failure propagation; custom target paths; eight Btrfs/VM
compositions; and matching generated payload content.

A real minimal chroot executes the corrected helper using existing Debian
binaries and standard base C.utf8 data, without installer locale paths, a
locale.gen file, locale-gen execution, mounts or generated user locales. It
successfully runs a child that unsets LC_ALL and reports UTF-8 without warnings.
This does not simulate the full Debian Installer mount/diversion machinery.

The container has no mkfs.btrfs/btrfs or OpenSSH executables. An attempted
external tool download was unavailable. The optional real Btrfs image-format
test is therefore explicitly skipped, not replaced with a mock success. It is
included for a trusted Debian test host with btrfs-progs and uses only temporary
256 MiB regular-file images, never block devices. Full booted installation,
real filesystem formatting, network authentication and graphical/enforce-mode
acceptance are not claimed here.

## 5. Deployment

Verify the external checksum, extract the complete archive, and run:

```sh
python3 -B tools/build.py --check
python3 -B -m unittest discover -v -s d-i/forky/tests -p 'test_btrfs_locale_boundary.py'
```

Publish the complete matching repository snapshot atomically. Do not publish
only target.sh or only a changed payload: manifest/preseed pins must match.
A previously started installation may already have cached the previous helper
or layout policy under /tmp/install-runtime; test with a fresh installer boot
using this snapshot. Do not rerun formatting commands against an installed
machine merely to remove an old log warning.

Keep private initrd keys and preseed.env outside the served checkout. They do
not change for these fixes. Do not delete GPG keys or relax AppArmor/ownership
checks as a workaround.

## References

Source and logs are the task basis; the following primary sources were checked
for the two command-boundary details:

- Btrfs upstream mkfs.btrfs manual, OPTIONS / DEPRECATED OPTIONS:
  https://btrfs.readthedocs.io/en/stable/mkfs.btrfs.html
- Debian installer-utils 1.155 in-target (passthrough descriptors and command):
  https://sources.debian.org/src/debian-installer-utils/1.155/in-target
- Debian installer-utils chroot-setup.sh (IT_LANG_OVERRIDE and proxy setup):
  https://sources.debian.org/src/debian-installer-utils/1.155/chroot-setup.sh
- GNU libc standard locales (C bridge locale):
  https://www.gnu.org/software/libc/manual/html_node/Standard-Locales.html
