# Optional URLhaus authentication

The installer reads `PRESEED_URLHAUS_AUTHKEY` from the private `d-i/preseed.env`
input that is embedded as `/preseed.env` in the installer initrd. Use the existing
protected credential input; the key is not a host-profile variable or a boot
command-line parameter.

| Private input | Installed behavior |
| --- | --- |
| Variable missing | URLhaus disabled; official ClamAV and Sanesecurity updates continue. |
| Empty value | Same behavior as a missing variable. |
| Nonempty Auth-Key | URLhaus enabled with the authenticated HTTPS export. |
| Unsafe credential file or malformed key | Installation fails with a redacted diagnostic. |

An explicit opt-out assignment is:

```sh
PRESEED_URLHAUS_AUTHKEY=''
```

For URLhaus, put the real Auth-Key between the quotes in that private input.
The reader accepts 1–256 URL-unreserved ASCII characters (`A–Z`, `a–z`, `0–9`,
`.`, `_`, `~`, `-`). It rejects URL delimiters, whitespace and interpolation
characters. The existing credential reader validates ownership, modes, shell
assignment syntax and parent directories, and clears ambient credential values
before reading the file. Missing/empty is distinct from an unsafe input.

## Installation and runtime

The key crosses into the target through a mode-0600 file in a private mode-0700
installer staging directory. The target configurator publishes
`/etc/fangfrisch.conf` atomically as **root:clamav, mode 0640**. Staging is removed
on exit. The key is never an installer command argument, environment assignment,
template substitution, payload input or diagnostic value.

The configured export is
`https://urlhaus-api.abuse.ch/v2/files/exports/${auth_key}/urlhaus_clamav.ndb`.
The literal `${auth_key}` is expanded by Fangfrisch from its private configuration.
The 10-minute provider interval and SHA-256 content consistency checks remain
enabled. URLhaus now requires a key in the export URL; the explicit override also
works with Forky's Fangfrisch 1.9.2, whose built-in URLhaus default still names the
retired anonymous endpoint. See the [URLhaus API](https://urlhaus.abuse.ch/api/),
[Fangfrisch's current provider defaults](https://raw.githubusercontent.com/rseichter/fangfrisch/master/docs/internal.conf)
and [1.9.2 defaults](https://raw.githubusercontent.com/rseichter/fangfrisch/1.9.2/docs/internal.conf).

The existing unified updater still runs as `clamav`, holds its existing update
lock, initializes Fangfrisch's database when necessary, runs official `freshclam`
updates and refreshes enabled external providers. Its Fangfrisch adapter accepts
only `initdb` and `refresh`, supplies a minimal environment, merges both output
streams, and redacts complete lines before logging. It removes the active key
and URLhaus export keys from older database mappings. HTTP failure causes such as
`403 Forbidden` remain visible. Output and line limits, a shared streaming/final
wait deadline, separate bounded cleanup, and the owning service cgroup bound the
operation. Cancellation and unproven cleanup retain distinct exit statuses.
The fixed log format also converts logged `ERROR`/`CRITICAL` records into failure
when packaged Fangfrisch returns zero after a provider download error; its
[1.9.2 entrypoint](https://raw.githubusercontent.com/rseichter/fangfrisch/1.9.2/src/fangfrisch/__main__.py)
does not propagate individual download failures itself.

Fangfrisch records source URLs in its SQLite database. Treat
`/var/lib/fangfrisch/` as credential-bearing state; its existing private directory
and service umask apply. The `clamav` account and group can read the configuration
and state by design. Do not run `fangfrisch dumpconf` or `dumpmappings` into shared
logs. Content hashes establish byte consistency, not a vendor signature.

Before consumer enablement, the installer verifies both delegates, root ownership,
private configuration modes, the fixed HTTPS URL and key/enabled agreement. It
does not download the feed or start a manager during this configuration step.
Automatic signature work also requires the current network readiness condition.

## Failed publication and acceptance

Publication synchronizes the candidate, previous bytes/metadata (or absence),
recovery receipt and parent directories. An uncertain rename/sync retains a
root-only `/etc/.fangfrisch-recovery.*` directory and returns status 125 with its
path. Do not automatically retry that installation step over retained evidence.
An unconfirmed cleanup after proven publication is reported separately.

The added credential, publication, replacement, redaction, timeout and result
propagation fixtures are **unexecuted**. The user requested no VM, test or
validation runs. Source inspection and the permitted payload serialization do
not establish a live authenticated download or a loaded target AppArmor policy.
No real key or private `preseed.env` was read during this change.
