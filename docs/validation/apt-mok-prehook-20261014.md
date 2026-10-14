# APT MOK unlock and mount-inspection repair

## Reported failure and source evidence

The supplied APT log fails when `secure-boot-tool` opens `/proc/self/mounts`,
before its `command_with_tty cryptsetup open` call. The same mount-table reader
is used during close, explaining the subsequent cleanup failure. The log does
not establish a wrong passphrase or a missing terminal: the prompt was not
reached.

The source profile previously allowed only the literal `/proc/self/mounts`.
Linux resolves `/proc/self` to the caller's numeric PID. The missing resolved
path rule is consistent with the reported denial; no live AppArmor audit record
or loaded policy was inspected in this session. Native libmount uses
`/proc/self/mountinfo`, and libdevmapper reads `/proc/devices`. Device-mapper
names also need their canonical `/dev/dm-N` node permissions.

The hook previously suppressed probe diagnostics and treated every nonzero
probe status as a negative result. Shell predicates also relied on `set -e`
where conditional callers suppress it. Together these could misclassify an
inspection failure as closed storage and create an unlock/cleanup marker.

## Changes

- `d-i/forky/hooks/target/etc/apparmor.d/system-wrappers.tmpl`: only the
  `secure-boot-tool` block changes. It permits owner reads of
  `@{PROC}/@{pid}/{mounts,mountinfo}`, read-only device-major discovery through
  `@{PROC}/devices`, and the resolved `/dev/dm-[0-9]*` nodes. Other profiles,
  terminal policy and private Xwayland policy are unchanged.
- `d-i/forky/hooks/target/usr/libexec/install-tools/secure-boot-tool.tmpl`:
  mount-table open failures explicitly return status 2, including within
  conditional callers. Readiness is a silent yes/no probe with diagnostics on
  inspection errors. Wrong mount sources and filesystems are errors. Required
  mount checks, open, close, passphrase changes and ESP-copy inspection preserve
  reader errors. Open inspects the mount source once. Missing configuration
  files and conflicting/invalid state modes also fail with status 2.
- `d-i/forky/hooks/target/usr/local/libexec/apt-mok-prehook`: shared probe
  handling accepts only status 0 (yes) or 1 (no), preserves stderr, and raises
  on other statuses before creating its marker or attempting an unlock.
- `d-i/forky/tests/test_maintenance_20261004.py`: added regression cases for
  probe errors/signals, conditional mount-reader failures and preventing
  ownership/open/close actions after failed inspection. These tests were
  statically reviewed and AST parsed, **not executed**.

The existing APT protocol version 2 / InfoFD 3 contract is retained. Package
metadata has its own descriptor. Interactive unlock still uses the existing
controlling-terminal handoff and cryptsetup's `/dev/tty` passphrase prompt.
There is no new pinentry backend, password file, service or interface.

The root-private marker is still created before the hook's open attempt, so
partial opens can be cleaned up. A ready administrator-opened volume remains
outside hook ownership. Failed cleanup retains the marker for retry. The
existing `DPkg::Post-Invoke` cleanup hook is retained.

## Installation trace

`scripts/late/grub.sh:write_target_secure_boot_payloads` renders the signing
tool and LUKS wrappers as 0755, secure-boot configuration as 0600, the APT hook
as 0755, and both APT configuration fragments as 0644. APT hooks are staged only
for LUKS mode. `hosts/installer/runtime.env` supplies the existing helper paths.
`scripts/late/security.sh` includes `system-wrappers` in its managed system
profile list and stages its existing template to `/etc/apparmor.d/system-wrappers`
as 0644. No staging path or permission change was needed.

## Verification actually performed

Repository `AGENTS.override.md` prohibits host tests and validators. No prepared
disposable environment is available. No APT transaction, LUKS helper, native
crypto command, shell syntax runner, AppArmor parser/reload, systemd action,
mock test or live integration test was run. The installed host was not repaired
or modified. Delegated read-only review attempts failed before work with an
agent runtime encrypted-content hydration error; no child findings were used.

Completed checks:

- Source/diff inspection of the APT action/terminal/marker lifecycle, signing
  helper callers, profile transitions and installer staging.
- `python3 -I -B` standard-library AST parsing of the hook and changed test
  source, without importing or executing repository modules.
- Byte comparison against `git show HEAD:...`: everything outside the
  `secure-boot-tool` AppArmor block is identical.
- Archive-to-source comparison before regeneration: exactly the three MOK
  runtime source files differ from the preceding key-manager payload. All
  earlier key-manager and development-tool payload content is preserved.
- `git diff --check`: completed without whitespace errors.
- Inspected `Makefile`, `tools/build.py` and `tools/publication.py` before running
  the permitted serialization-only `make build PYTHON=python3`. Output:
  `built 1768 payload files`. No software was compiled.
- Standard-library archive/hash inspection without extraction or execution:
  all 1,768 regular entries match source bytes and manifest SHA256; archive
  modes/ownership/timestamps are normalized; required MOK assets are present;
  tests/private inputs are excluded; all three preseed bootstrap pins match.
- Canonical source files retain this checkout's non-executable mode 0600;
  installed permissions remain controlled by the staging calls above.

### Snapshot after the MOK repair

This combined key-manager/MOK snapshot supersedes the generated hashes in the
earlier [key-manager integration report](key-manager-integration-20261014.md).
It precedes the subsequent
[PKI traversal repair](key-manager-pki-permissions-20261014.md).
The current combined snapshot is in the
[desktop CrowdSec report](crowdsec-desktop-relevance-20261014.md).

| Product | SHA256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `a08e589ebc00eb0d1008b9fb5df731c07fc15716c2fdbb334dd1aca526410849` |
| `d-i/forky/payload.manifest` | `af004793145eff5917503584564d1e7124c51506a1eff399bb02aebbbe62d2b0` |
| `d-i/forky/preseed.cfg` | `a9ca76d2d8bddc2d2dd25ad0e912d88aadda02be1463f1bfb7ef05e7cd4e5de5` |

Installed acceptance still requires the updated helper, hook and loaded
AppArmor policy together. Native policy parsing, a real terminal prompt,
successful unlock/sign/cleanup and interruption behavior must be verified in
the prepared disposable Forky environment. Static inspection does not establish
those runtime results.

## Primary references

- [Linux proc/self implementation](https://github.com/torvalds/linux/blob/master/fs/proc/self.c)
  resolves the process link to its numeric TGID.
- [AppArmor kernel-variable tunables](https://gitlab.com/apparmor/apparmor/-/blob/master/profiles/apparmor.d/tunables/kernelvars)
  and [profile syntax](https://manpages.debian.org/unstable/apparmor/apparmor.d.5.en.html)
  define the PID glob and owner-qualified file permissions.
- [util-linux libmount parser](https://github.com/util-linux/util-linux/blob/master/libmount/src/tab_parse.c)
  uses `/proc/self/mountinfo` as the native mount-table input.
- [libdevmapper Linux interface](https://github.com/lvmteam/lvm2/blob/main/libdm/ioctl/libdm-iface.c)
  opens `/proc/devices` to discover the device-mapper major number.
