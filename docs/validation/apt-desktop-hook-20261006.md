# Installed APT desktop hook failure, 2026-10-06

## Supplied evidence

All records in `todo/apparmor.log`, `todo/fail` and `todo/iocost` were read.
The AppArmor log contains 409 records: 407 status records and two denials,
both for `labwc-wrap-desktop-files` (`dac_read_search` and `dac_override`,
lines 408-409). The status records report filesystem initialization, hashing,
profile loads and one unchanged-profile replacement.

`todo/fail` records two failed `oomd` transactions at the desktop APT pre-hook:
Python cannot find a usable default temporary directory. `todo/iocost` records
the same dependency-install hook failing to inspect a `.deb` under the user's
private workspace output tree. The IOCost log explicitly says no benchmark
was launched; it provides no evidence of a calibration or kernel IO failure.

## Cause and narrow correction

The metadata inspector used `tempfile.TemporaryFile()` without a directory.
That depends on Python's default temporary-directory probing. The profile's
old scratch permissions covered `/tmp/tmp*` and `/tmp/#*`, while directory
probing uses other random names. The error is a concrete dependency on global
temporary storage that this helper's confinement does not support. The supplied
audit has no temporary-file denial record, so it does not establish the exact
filesystem or audit path of every failed probe.

The inspector now creates and validates its existing protected state directory,
ensures mode 0700 and uses `TemporaryFile(dir=STATE_DIR)`. Its anonymous scratch
file is mode 0600 and is closed/deleted by the context manager. The decompressor
output limit, timeout, process-group cleanup and argument arrays are retained.
This removes global temporary-directory discovery from metadata inspection.
[Python's tempfile documentation](https://docs.python.org/3.14/library/tempfile.html)
describes the explicit directory parameter and default discovery behavior.

Root also needs to traverse/read an APT archive inside a private user directory.
The profile now permits `dac_read_search`, subject to its existing read-only
archive rules. It does not permit `dac_override`. The obsolete public scratch
write permissions are removed. The
[Linux capability reference](https://man7.org/linux/man-pages/man7/capabilities.7.html)
documents the read/search permission bypass separately from write bypass.

## Validation

The new temporary-directory checks failed before the production fix: both
control archive variants and a direct scratch probe raised the injected
`FileNotFoundError`. After the fix:

| Exact command, from repository root | Result |
| --- | --- |
| `timeout 120s python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_maintenance_20261004.py -q` | 34 passed, no skips. Real `dpkg-deb` fixtures cover packages with/without md5sums and names with spaces. Default temporary discovery is forced to fail; state ancestry checks are mocked for the invoking non-root account. Scratch permissions, initialization and cleanup are exercised. |
| `timeout 120s python3 -W ignore::EncodingWarning -B -m unittest discover -s d-i/forky/tests -p test_apparmor_incidents_20261004.py -q` | 20 passed, no skips. Native offline parsing and expanded file rules verify archive read access, protected state scratch access and no public/home scratch writes. No kernel policy load. |
| `timeout 180s python3 -W ignore::EncodingWarning -B tools/build.py` | Rebuilt 1,704 payload files; zero browser artifacts changed. |
| `timeout 180s python3 -W ignore::EncodingWarning -B tools/build.py --check` | Snapshot, pins, preseed and browser artifacts current. |
| `timeout 180s python3 -W ignore::EncodingWarning -B tools/check_shells.py` | 350 files; 711 parser checks passed. |
| `timeout 90s python3 -W ignore::EncodingWarning -B tools/check_preseeds.py` | 59 files passed; all four generated commands survived private debconf read-back. |
| `git diff --check` | Passed. |

The test host has Python 3.14.7, AppArmor 4.1.8-2, APT 3.3.3 and systemd 262-1.
The installed system's intended systemd 261.2 is not represented as live-tested.
These changes do not modify systemd policy, partitioning, NFS or Xwayland.

## Repair the existing installed host

Run these steps on the affected installed host from the corrected checkout.
Rebuilding the installer payload does not change an existing installation.

1. Install the corrected helper; this step uses no APT transaction:

   ```sh
   sudo install -o root -g root -m 0755 -- \
     d-i/forky/hooks/target/usr/local/libexec/labwc-wrap-desktop-files \
     /usr/local/libexec/labwc-wrap-desktop-files
   ```

2. Edit the profile's existing local include, preserving any administrator rules:

   ```sh
   sudoedit /etc/apparmor.d/local/usr.local.libexec.labwc-wrap-desktop-files
   ```

   Add this line once:

   ```text
   capability dac_read_search,
   ```

3. Parse the installed, already-rendered policy before replacing the loaded policy:

   ```sh
   sudo apparmor_parser --config-file /dev/null \
     --Include /etc/apparmor.d --Include /usr/share/apparmor \
     --policy-features /usr/share/apparmor-features/features \
     --Optimize=rule-merge --Optimize=compress-fast \
     --skip-cache --skip-kernel-load /etc/apparmor.d/desktop-wrappers &&
   sudo apparmor_parser --config-file /dev/null \
     --Include /etc/apparmor.d --Include /usr/share/apparmor \
     --policy-features /usr/share/apparmor-features/features \
     --Optimize=rule-merge --Optimize=compress-fast \
     --skip-cache --replace /etc/apparmor.d/desktop-wrappers
   ```

   The managed parser configuration enables `write-cache`. With parser 4.1.8,
   an offline probe reproduced `Failed to create cache` with exit status zero
   even when `--skip-cache` was supplied. The commands above bypass that default
   configuration for this invocation and explicitly preserve its include paths,
   policy features and optimization options. An offline check with an unusable
   cache path passed without the warning. No kernel policy was loaded in that
   check. Caching and enforcement are separate: the reload still replaces the
   kernel policy. Check the reload's exit status immediately; it must be zero.

4. Retry the requested package installation:

   ```sh
   sudo apt install oomd
   ```

The unrendered repository `desktop-wrappers.tmpl` is not an installed policy.
The local include supplies the one capability correction without replacing
the host's rendered theme/account configuration. A live package transaction,
policy reload and IOCost benchmark were not executed by this repository task.
