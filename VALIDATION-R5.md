# R5 validation - 16 September 2026

Baseline: complete accepted R4 archive. This report covers the new explicit
application classes, broker stop policy and normal machine-shutdown path.
Earlier validation directories describe earlier revisions, not new R5 results.

## Completed selected regression runs

The 12 completed selections contain **232 tests: 231 passed, 1 skipped**, with
no failures or errors. Machine power commands were mocked throughout.

| Selection | Tests | Outcome |
| --- | ---: | --- |
| Power/keyboard/session preparation | 36 | Passed |
| Existing D-Bus broker tests | 16 | Passed |
| New R5 broker/shutdown-policy tests | 8 | Passed |
| Resource policy, all 13 profiles and both I/O modes | 16 | Passed |
| Resource refinements and offline unit loading | 9 | Passed |
| R4 systemd review assertions, adjusted for explicit R5 scope/panel classes | 4 | Passed |
| R4 AppArmor boundary assertions | 9 | Passed |
| Lifecycle review | 30 | Passed |
| Existing lifecycle tests | 22 | Passed |
| GitOps mirror tests | 16 | Passed |
| Repository integrity, including all profile composition | 10 | Passed |
| Managed Git/debugsys | 56 | 55 passed; 1 missing-OpenSSH-client skip |

Exact commands and outputs are in `validation/r5/test_*.log`; machine-readable
counts are in `validation/r5/test-summary.json`. Run a selection with:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=d-i/forky/tests \
  python3 -B -m unittest -v test_shutdown_policy_r5
```

The new test module invokes the real target publisher and literal renderer.
It checks the full broker configure sequence using mocks only for package/dpkg
operations and enablement, all profiles in both I/O modes, valid overrides,
malformed values, existing-file preservation and failed-fetch cleanup. Offline
manager graphs check the effective 30-second timeout, retained control-group
kill mode, SIGKILL fallback, socket ordering and client-before-bus stop relation.
These are reduced fixtures, not live broker acceptance tests.

Power-worker tests explicitly assert ordinary nonblocking reboot and poweroff,
no preemptive UID teardown on those paths, no forced retry, failure before
commitment, other-user rechecking, save cancellation, logout isolation and
unchanged suspend handling. Existing tests that required the old force path
were replaced with assertions for the requested orderly policy, not disabled.

## Other completed checks

- Shell syntax: **277 files, 565 parser checks, PASS**.
- Preseed validation: **59 files, PASS**; four generated command values survived
  private debconf read-back unchanged.
- Payload build: **1,331 payload files**, with current manifest/preseed pins.
  Repeated builds were compared, and the final extracted tree is checked again.
- Resource tests exercise the original home-copy routine in an isolated chroot,
  including the new panel/dock policies and account ownership/private modes.
- Offline systemd fixture checks retain the existing 36-fragment resource graph
  in both I/O modes, plus separate R5 broker fixture checks. Scopes are validated
  for drop-in shape and staging, not misrepresented as static service fragments.
- **149 AppArmor/Podman/zram policy and workload files are byte-identical to R4**;
  their hashes are recorded in `validation/r5/protected-policy-sha256.json`.
  The existing original-workload policy fixture also passes.

## Limits and interrupted attempt

The full repository aggregate suite was not run. An initial combined selected
run reached the 200-second tool execution limit during all-profile AppArmor
compilation. It is retained in `validation/r5/focused-tests.log` as an incomplete
attempt and is not counted in the 232 completed tests. The local-fragment compiler
test had passed before interruption, but no fresh successful result for all
AppArmor profile compilation is claimed. No AppArmor source changed in R5.

The available executable is systemd **257.9**, and AppArmor parser **4.1.0**.
No systemd 261.2 host was booted; no live manager/broker was restarted; no kernel
policy was loaded. There was no real logout/reboot, disk enforcement benchmark,
hardware watchdog test or authenticated remote-provider acceptance test.

No shutdown journal supplied here proves the reported delay's cause. Correcting
unconditional forced shutdown restores the documented service-stop path;
30 seconds is a selected broker grace policy, not a performance measurement or
a whole-system shutdown guarantee. See the implementation report for read-only
inspection commands and installed-host acceptance checks.

## Complete archive

`r5-change-manifest.json` inventories changes from R4, including source hashes and
file modes. The delivery archive is independently extracted and all content and
file permissions are compared; the external archive-verification JSON records
that result without creating a circular checksum dependency. All original input
file paths and their original regular-file permissions are checked as well.
