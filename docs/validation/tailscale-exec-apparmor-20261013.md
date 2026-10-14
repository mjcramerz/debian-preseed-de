# Tailscale daemon CLI execution denial — 2026-10-13

## Supplied evidence

The user supplied an AVC for node `LPL-584`, audit event
`1791925024.981:21020`: profile `usr.sbin.tailscaled`, operation `exec`, executable
`/usr/bin/tailscale`, requested and denied mask `x`, root filesystem UID. This
specific record was not present in the current `todo/` files when searched.
The supplied record establishes the missing execution permission; it does not
identify the CLI arguments or prove which daemon feature launched the command.

## Narrow source repair

`d-i/forky/hooks/target/etc/apparmor.d/usr.sbin.tailscaled` now grants the exact
path `/usr/bin/tailscale rix,` inside the daemon profile. A daemon-spawned CLI
inherits daemon confinement, consistent with the existing `loginctl` helper.
Direct CLI invocation retains the existing `usr.bin.tailscale` attachment.
Neither profile receives new capabilities, wildcard execution, or unconfined
execution. The service retains `NoNewPrivileges=true` and all existing hardening.

AppArmor's documented `ix` mode preserves the caller's profile when executing
the specified program. A separate CLI profile already exists, but has bootstrap
file permissions that the daemon profile does not grant. Selecting it with a
profile transition would introduce a separate NoNewPrivileges compatibility
question. The exact inherited execution rule avoids that transition.
See the [official AppArmor execution-mode documentation](https://www.apparmor.net/man/4.0/apparmor.d/).

Installer integration already lists `usr.sbin.tailscaled` in
`apparmor_managed_system_profile_files()` in `scripts/late/security.sh`.
`stage_target_system_apparmor_profiles()` installs that source at
`/etc/apparmor.d/usr.sbin.tailscaled`, mode 0644. Both named profiles are in that
file. No new staging path or service override is required.

The existing native AppArmor rule-reader regression in
`d-i/forky/tests/test_apparmor_incidents_20261004.py` now covers both
`/usr/bin/loginctl` and `/usr/bin/tailscale`, checking one exact non-deny `ix`
rule for each and retaining the service hardening assertion. Its isolation gate
is unchanged.

## Validation boundary

Static inspection parsed source as data without importing or executing repository
modules. The changed regression file passed Python AST parsing, and
`git diff --check` completed successfully. Native AppArmor parsing, regression
execution, and installed-system reproduction were not run: repository guidance
requires a prepared disposable environment, which is unavailable.

The delegated read-only sidecar failed during encrypted-context initialization.
It produced no review findings; integration review was completed by the root
agent directly.

The full Makefile and `tools/build.py` / `tools/publication.py` execution paths
were inspected before the explicitly permitted serialization-only build. The
build command is:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
```

The first build completed with 1,755 payload files. The initial verbose metadata
capture exceeded the tool output budget and was not used as verification
evidence. A second permitted pure serialization run completed with the same
1,755 files. A bounded metadata digest covering 2,919 non-product checkout paths
was identical before and after that second run, and none of the three products
changed on that repeat generation.

Independent standard-library archive inspection, as data without extraction or
execution, verified all 1,755 regular members and 33,986,660 source bytes against
the source files and manifest SHA-256 entries. Member paths, private-input/test
exclusions, uniqueness, and normalized metadata (0644, zero UID/GID/mtime,
empty owner/group names) were checked. All three embedded bootstrap pins match.
The direct CLI profile was byte-identical to HEAD, and read-only Git comparisons
confirmed the service override and security staging source are unchanged.

| Artifact | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `cbfda27c08a6fa2e1a0ad03d7ce6f0ffca575880a4fba3e4553ceaff74b3c631` |
| `d-i/forky/payload.manifest` | `fb2e6680066d05df7db04ee92254d00216b1427e4f472b374025c995175a44c6` |
| `d-i/forky/preseed.cfg` | `0085368c9f64ef96a3ffe1777c6022e4d32251738727758c1ad0c7fc2757f474` |
| Unchanged `scripts/common/source.sh` | `6b3a40bb85942ed8f4b780852743140132414898b578af7c7597bb7c3872b246` |

## Changed paths for this follow-up

- `d-i/forky/hooks/target/etc/apparmor.d/usr.sbin.tailscaled`
- `d-i/forky/tests/test_apparmor_incidents_20261004.py`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/payload.manifest`
- `d-i/forky/preseed.cfg`
- `docs/validation/tailscale-exec-apparmor-20261013.md`

All previously uncommitted work is preserved. No host policy was loaded or
modified, no service was contacted or restarted, and no installed machine was
repaired or deployed. Live kernel policy acceptance and the daemon's complete
CLI operation remain unverified. This repair addresses the reported execution
denial; it does not change Tailscale's separate device-approval requirement.
