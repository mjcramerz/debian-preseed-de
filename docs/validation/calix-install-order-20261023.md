# Calix install ordering and installer verification removal — 2026-10-23

## Reported failure and owning code

The user reported an installer `FileNotFound` for `/opt/calix`. The source
contains a direct cause: `run_desktop_late_command` called
`desktop_verify_runtime_contracts` before `desktop_install_user_config`.
The latter function installs Waycal, Calix and Agenda through
`desktop_install_primary_account_calendar_stack`. The verifier unconditionally
called `trusted(Path('/opt/calix/calix'), True)`, whose parent loop called
`lstat()` on `/opt/calix`. On a fresh target the calendar installer had not
created that directory yet. The account-only verifier call also entered these
unconditional probes before reaching its stage-specific return.

This was an ordering error in the newly added verification, not evidence that
the pinned Calix release uses a different installation path. The actual
calendar installer publishes `bin/calix` from the pinned archive as
`/opt/calix/calix`; the managed application profile uses that exact path.

The user explicitly requested removal of installation-time verification if
it caused the failure. The installer no longer fetches or sources `verify.sh`,
and no `desktop_verify_*` calls remain in the desktop install flow. Its audit
definitions remain available as source for explicit isolated audits.

## Production changes

- `d-i/forky/scripts/late/desktop.sh`: remove the verifier from the fetched and
  sourced module list.
- `d-i/forky/scripts/desktop/labwc.sh`: remove the two runtime-contract calls,
  Kanshi/menu probes and inline GIO probe. Continue actual staging, account
  setup, package installation and service enablement.
- `d-i/forky/scripts/desktop/components/user-config.sh`: install the calendar
  binaries and private Fruux data before synchronizing account launchers.
  Launcher synchronization still runs as a real setup operation, with its
  original ownership and publication implementation.
- `d-i/forky/scripts/desktop/components/target-assets.sh`: remove the separate
  swaylock, Vivaldi and Hyprpolkit verification probes; retain their assets,
  configured runtime helpers and actual Vivaldi codec installation.
- `d-i/forky/scripts/desktop/components/compz.sh`: retain codec installation and
  remove the separate installed helper probe.
- `d-i/forky/scripts/desktop/components/services.sh`: retain offline global SSH
  socket disablement and account-specific activation; remove the preliminary
  read-only package/unit assertions.
- `d-i/forky/scripts/desktop/verify.sh.tmpl`: document its offline audit status.
- `d-i/forky/scripts/desktop/components/desktop-config.sh`: remove the fixed
  600-second cap around calendar installation.
- `d-i/forky/scripts/desktop/calendar-install.py`: replace the fixed 180-second
  download cap with a 300-second socket inactivity timeout and up to three
  retries for transport interruptions and transient HTTP statuses. Each retry
  starts at the pinned URL so expiring signed redirects can be renewed.
  Incomplete advertised response bodies retry; unsafe redirects, oversized
  content and digest failures still fail before publication. Application/version
  progress and fixed error causes are reported without exposing URLs or secrets.
- `docs/calendar-and-wifi.md`: update the active install contract.

No source build, host service operation, credential rotation, remote Fruux call
or change to private Zoom/Discord Xwayland policy is performed. The user-level
firstboot/credential-delivery code and cleanup state machine are preserved.

## Related source review

The calendar publication path, account ownership, launcher paths and service
enablement order were traced. The launcher synchronizer normalizes the fixed
`.local` and `.local/share` account directories before firstboot needs to
create the Calix database. Firstboot provisioning remains ordered before
greetd and does not use a keyring or network. Automatic login credential
delivery remains after the existing KWallet service. Secondboot cleanup still
requires completed credential delivery and durable removal of private input.

The earlier shared software timeout and AppArmor transition fixes remain in
the working tree. No new named AppArmor transitions are introduced here.
This review does not establish a successful live boot, keyring session or
remote synchronization.

## Unexecuted fixture maintenance

Existing fixture expectations were updated for the removed installer gates:

- `d-i/forky/tests/test_packaged_native_session_20260920.py`
- `d-i/forky/tests/test_rendered_runtime_contracts.py`
- `d-i/forky/tests/test_kanshi_fuzzel_followup_20260919.py`
- `d-i/forky/tests/test_drawer_native_icons_20260920.py`
- `d-i/forky/tests/test_log_review_20260921.py`
- `d-i/forky/tests/test_hyprpolkit_compatibility.py`

`d-i/forky/tests/test_vendor_http_redirects.py` also had a mock that rejected
the 1,500-second renewable inactivity window from the preceding shared-download
fix. Its old 1,200-second expectation was updated and it now requires a
progress owner. None of these fixtures was run.

## Validation boundary

Only source/data inspection and the reviewed pure serialization build are
performed. No test runner, shell validator, native policy parser or managed
module import is executed. An attempted independent read-only sidecar could
not initialize because of encrypted-content hydration, so no independent
review is claimed. A tool cell interrupted by user steering had no retrievable
result; all final evidence below comes from completed subsequent calls.

The declared target is Debian Forky, Python 3.14, systemd 262. No target image or
installed package versions were queried. The root JSON inventories are separate
generation products and remain stale relative to the rebuilt payload.

## Recorded results

- Base revision: `5926f21a0ac7c8ef331cc4011c3e7fc06c01cffa`, branch `mcr/main`.
- SHA-256 working-tree fingerprint of the nine production source paths and
  seven fixture paths listed above, sorted using `path + NUL + bytes + NUL`:
  `d5ddf7a7905cc1fe278e2323c148a844716ff847bc2fc90b80fcb97d42252874`.
- `git diff --check`: passed.
- Inline `/usr/bin/python3 -I -S -B -` data inspection: parsed the calendar
  installer and seven changed fixtures with `ast.parse`; tokenized the seven
  changed executable-path shell sources with `shlex` without executing them.
  Tokenization is not native shell syntax or runtime acceptance.
- The same source inspection confirmed that `verify` is absent from the
  desktop module fetch/source list, no active `desktop_verify_*` or
  `run_in_target "verify ..."` probes remain in that desktop flow, calendar
  installation precedes account launcher synchronization, and account setup
  precedes service enablement. Calendar acquisition has four attempts and no
  overall transfer/install clock; custom error messages are fixed strings.
- `make build PYTHON=/usr/bin/python3`: completed, 1,829 payload members.
- Separate standard-library archive/hash inspection matched all 1,829 archive
  members against both current source and the manifest, totaling 34,859,520
  expanded bytes. Preseed archive/manifest pins match; private input names are
  absent from the archive.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `83bc13a52e2a954e9b9554346d14a1ad6c3b20776ca7627d36ed00f53ce95e41` |
| `d-i/forky/payload.manifest` | `3e2ef05f84d9686473c89639cb954e5dacabcb83ac0b5c3c6dbb7ed02b477217` |
| `d-i/forky/preseed.cfg` | `93f71542c06c2f24d3c8ce7038296800d2d79a871c35c1ce55814a232377dd98` |

No fixture or live installation passed is claimed. The earlier reports remain
historical snapshots; these hashes identify the current serialized payload.
