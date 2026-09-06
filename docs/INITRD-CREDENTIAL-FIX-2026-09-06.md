# Initrd credentials and root-login repair - 2026-09-06

## Scope and root cause

This is an amendment to the complete security/browser refactor, not a replacement
of its hardware profiles or browser settings. The actual private USB/initrd and
passwords were not supplied, so this report distinguishes a reproduced source
bug from unobserved details of the user's USB.

Both credential readers previously called `stat -c '%u:%a'` before sourcing
`/preseed.env`. Debian's busybox-udeb configuration explicitly disables the
`stat` applet. When it was missing, the reader returned status 1 with no value;
the account resolver suppressed its status and stderr and reported that the root
password was missing. The same silent failure happened for an otherwise trusted,
root-owned 0644 file. The reported error is therefore consistent with a genuine
installer-compatibility bug even when PRESEED_ROOT_PASSWORD is populated.

`validation/root-env-fix/before.json` records both failures against the previous
archive using dummy secrets. No actual password was required to reproduce them.
Previous tests using a full desktop BusyBox did not adequately model the missing
installer applet; the isolated chroot tests now explicitly omit `stat` from PATH.

## Effective precedence

| Installer input | Effective root password / outcome |
| --- | --- |
| No `root_password` parameter | Read `PRESEED_ROOT_PASSWORD` from the installer's `/preseed.env`. |
| `root_password=VALUE` | Use VALUE, irrespective of the environment-file value. |
| `root_password=` or bare `root_password` | Explicit empty override; stop with a specific error. Remove the parameter to enable fallback. |
| Several `root_password` parameters | The first exact parameter wins, preserving the existing parser contract. |
| No parameter and missing/empty environment value | Stop before disk discovery/planning; never invent a password or lock root silently. |
| No parameter and invalid/untrusted environment file | Stop with a specific, redacted credential-loader diagnostic. |

The matching is exact: a name containing `root_password` as a substring does not
count. Password values are literal, with glob expansion disabled; shell characters
are not evaluated a second time. The existing account input contract still requires
one printable token without whitespace. Correctly quoted shell punctuation is
supported. Do not put plaintext credentials on a public boot command line; the
private initrd is the preferred source when no override is needed.

## Root and primary account policy

Local root login remains enabled (`ROOT_LOGIN=true`). Generated answers explicitly
set `passwd/root-login=true`, clear a stale `passwd/root-password-crypted` answer
(including `!`), and seed the selected plaintext root password twice. An empty root
password is never enabled. SSH's separate `PermitRootLogin no` policy is unchanged.

A supplied plaintext primary password now also clears a stale
`passwd/user-password-crypted` answer, preventing an old hash from defeating the
selected override. The primary username's existing policy default remains valid
when its parameter and environment value are absent. Blank optional integration
entries do not by themselves mean the root password is absent, although selected
integrations may later require their own credentials. The redacted example is not
intended to be an installable set of passwords; keep the real private values in
YOUR initrd, not in this repository.

## Complete supplied environment mapping

Your assignment names and shell format are retained. All 15 supplied variables
and their 20 recognized parameter spellings are regression-tested.

| Command-line parameter(s) | Environment-file variable |
| --- | --- |
| `netcfg/wireless_wpa`, `wireless_wpa`, `wifi_wpa` | `PRESEED_WIFI_PASSPHRASE` |
| `fruux_username` | `PRESEED_FRUUX_USERNAME` |
| `fruux_password` | `PRESEED_FRUUX_PASSWORD` |
| `primary_user` | `PRESEED_PRIMARY_USERNAME` |
| `primary_password` | `PRESEED_PRIMARY_PASSWORD` |
| `primary_gpg_passphrase` | `PRESEED_PRIMARY_GPG_PASSPHRASE` |
| `root_password` | `PRESEED_ROOT_PASSWORD` |
| `crowdsec_token`, `crowdsec_enroll_token`, `crowdsec_attachment_key` | `PRESEED_CROWDSEC_TOKEN` |
| `tailscale_authkey`, `tailscale_auth_key` | `PRESEED_TAILSCALE_TOKEN` |
| `telegram_chat_id` | `PRESEED_TELEGRAM_CHAT_ID` |
| `telegram_api_key` | `PRESEED_TELEGRAM_API_KEY` |
| `cf_r2_access_key` | `PRESEED_CF_APTLY_ACCESS_KEY` |
| `cf_r2_secret_key` | `PRESEED_CF_APTLY_SECRET_KEY` |
| `obs_username` | `PRESEED_OBS_USERNAME` |
| `obs_password` | `PRESEED_OBS_PASSWORD` |

## Loader changes

The canonical POSIX shell implementation is in
`d-i/forky/scripts/common/credentials.sh`. The build tool embeds exactly the same
source into the installer and runtime common libraries. There is no new boot-time
network fetch, Python dependency, or fragile relative include. `build.py --check`
rejects divergence between those embedded copies and the canonical source.

Metadata checks use `ls -ldn`, `id`, shell builtins and applets enabled in d-i,
rather than `stat`. A regular, singly-linked file owned by the invoking installer
UID (root in d-i), with safe parent directories, is required. Root-owned 0400/0600
files are accepted. Owner-readable files with additional group/other READ bits
(for example 0644) are reduced to 0600 before being sourced. Unsafe owners, links,
write/execute/special bits, replaceable parent directories, or an unsuccessful
chmod are rejected. Automatic hardening cannot undo prior disclosure: preserve
root ownership and 0600 in the USB build, and rotate credentials previously leaked.

Initial UTF-8 BOM and CRLF line endings are normalized in a private temporary copy.
Syntax is checked with `/bin/sh -n`; parser errors and source stdout/stderr cannot
become password values or expose source lines. Recognized inherited PRESEED_*
variables are cleared before loading, so missing assignments do not accidentally
pick up stale process environment values. Temporary copies are removed on normal
exit and catchable interruption. Missing/empty values (status 1) and load/security
errors (status 2) are distinguished rather than silently collapsed.

IMPORTANT: this file remains TRUSTED EXECUTABLE SHELL, not an arbitrary dotenv/data
import. Ownership checks and syntax checking do not make malicious shell code safe.
Do not run with shell xtrace, and do not publish the file, debug environment dumps,
or raw kernel command lines containing passwords.

## Related installer repairs

The broader check found later installer-side calls to `stat` in rootless Podman
filesystem detection and four Codex helper ownership/mode checks. They now use the
installed target's `/usr/bin/stat` through `chroot`, with target-relative paths.
They do not require a new stat applet in the initrd. Podman's approved backing
filesystem policy remains unchanged and a failed target query fails explicitly.
These checks occur after target package installation, not during early boot.

The early account validation now occurs before the early hook's disk discovery and
crypto-answer generation. This catches the reported credentials failure earlier;
it is not a general certification of safe disk selection or a validation of every
late-stage third-party integration before partitioning.

## Deploy the fix

The tarball contains the entire repository, rebuilt payload, manifest and generated
preseed. Publish the whole tree as one consistent release. Do not update only one
library while serving the old archive or preseed pins. Clear any stale deployment
cache as appropriate, and start a NEW installation rather than resuming the old
installer's cached payload.

Your private `/preseed.env` belongs at the root of the actual booted installer
initrd, not under `/target`, `/etc`, or only beside the USB's initrd archive.
There is no need to rename its variables or move the passwords to GRUB. If your
initrd embeds only that private credentials file and downloads the public preseed
from the server, update the server release. If it also embeds an old preseed.cfg,
bootstrap library or payload, rebuild those embedded PUBLIC components with this
release as well. This package does not contain a rebuilt USB image because that
image and its build process were not supplied.

From the extracted repository:

```sh
python3 -B tools/build.py --check
python3 -B tools/validate.py
```

After any runtime source or browser-input edit, run `python3 -B tools/build.py`
before those checks. Run the test suite on a disposable trusted Linux environment;
Perl syntax checks can execute BEGIN blocks, as documented in SECURITY.md.

For a private local credentials copy, this optional diagnostic simulates an empty
kernel command line without printing a password:

```sh
sudo sh tools/check-installer-credentials.sh /path/to/trusted/preseed.env /dev/null
```

Run it against the real `/preseed.env` from a checkout available in the installer
shell to inspect the actual booted command-line precedence:

```sh
sh tools/check-installer-credentials.sh /preseed.env /proc/cmdline
```

It reports `present`, `explicit-empty`, `missing-or-empty`, `invalid-format`, or
`load-error`, and whether the source is `command-line` or `initrd-env`. It does not
print values, configure accounts, seed debconf, or touch disks. It can harden file
permissions and executes the trusted assignments just as the installer does.
Missing optional values are informational; an unusable root credential or a loader
error produces nonzero status. This is not a substitute for profile validation.

## Evidence and limits

The completed five-stage pipeline passed: **305 tests, zero skips**, 58 preseed
checks, 1,225 payload member hashes, and no hard audit failures. All 13 hardware
profiles, all 1,031 target-hook assets, the five browser-generator inputs, and the
three SSH assets retain their preceding-release file contents. No runtime source
file was removed. Syntax/inventory checks still report 154 dependency-blocked
Perl checks, 116 structure-only systemd checks and two unrendered templates; these
are not counted as successful runtime tests.

See `validation/summary.json` for this revision's completed pipeline result,
`validation/tests.log` for all test names, `validation/audit.json` for non-passing
inventory/dependency categories, and `validation/root-env-fix/release-check.json`
for preservation/integrity checks. The new credential and target-tool test modules
cover all supplied mappings, command-line precedence, unsafe and shared-read modes,
BOM/CRLF, shell punctuation, malformed syntax, absent stat, redacted diagnostics,
parent/link attacks, and target-chroot metadata calls. Retained root tests include
an isolated BusyBox chroot WITHOUT stat and real isolated debconf round trips.

The complete USB boot, actual private initrd, package availability, GPU/kernel
build, desktop login and external website workflows were not executed here. Passing
fixtures establish the repaired behavior, not the absence of every possible error.
The browser and CUDA fixes are preserved, including the documented expiry of the
legacy CUDA certificate compatibility exception on 2027-02-01.

## Primary references checked

Debian busybox-udeb configuration (CONFIG_STAT disabled; required reader applets
and ash enabled):
https://sources.debian.org/src/busybox/1:1.37.0-6/debian/config/pkg/udeb/

Debian Installer Forky preconfiguration, account setup and root password/lock
answers:
https://d-i.debian.org/doc/installation-guide/en.amd64/apbs04.html#preseed-account
