# Test isolation, generation-only build and supplied AppArmor denials

## Implemented contracts

- `AGENTS.override.md` prohibits tests and validation from using or changing
  the development host. No environment-variable override or host fallback is
  provided.
- All 188 Python test/fixture modules check the isolation boundary before
  runtime imports. Twelve Python validation entry points are also gated.
  Explicit builder/browser `--check` branches and the shell credential
  diagnostic require isolation. Makefile test targets check before discovery.
- `tools/isolation.py` checks the private source copy, rootless UID mapping,
  namespace ownership, private procfs PID view, loopback-only network,
  capability sets, no-new-privileges, read-only image root and private mounts.
  It rejects persistent/host file binds, sysfs/cgroup mounts and installed
  `/usr/local` files. `tools/test-init.py` runs only as the prepared image's
  private PID 1, copies source to private tmpfs, supplies a minimal environment
  and bounds/reaps its own child process groups.
- Native kernel fixtures additionally require a disposable VM with its own
  kernel; namespaces alone do not virtualize every kernel-global procfs field.
  Provisioning this boundary is documented in `docs/test-isolation.md`.
- Local APT test state moved from `/var/lib/apt-repo-local-tests` to private
  `/workspace/apt-repo-local-tests`. GnuPG HOME uses the private fixture home.
  Native Bubblewrap fixtures construct a minimal runtime filesystem and bind
  only their owned fixture directories or sockets; root binds were removed.
- `make build` writes only `d-i/forky/payload.tar.gz`, `payload.manifest` and
  `preseed.cfg`. It executes no tests, subprocesses, source validators, browser
  generators or source synchronization. It retains safe packaging/publication
  boundaries and exclusion of private input names. Hashing and archiving use
  the same source bytes. Source checks moved to guarded `tools/check_build.py`.
- `apt-repo-local` inherits execution of `/usr/bin/rm` and allows owner-only
  reads of `/proc/<pid>/fd/` directories. No descriptor-target writes were added.
- `labwc-app//app-bwrap` inherits execution of `findmnt` and `ls` at both `/bin`
  and `/usr/bin`, and of `/usr/lib/chromium/chromium`. Edge's owner-only,
  versioned `Domain Actions/libdomain_actions.so` receives `mr` without `x`.
  Production Xwayland policy and runtime code were preserved.

## Evidence recorded in this turn

No tests, test discovery, repository validation runners, native AppArmor parser,
policy load, source compilation, or service action was executed after the host
safety restriction. Existing in-flight test results were not used as evidence
for the final state.

Source was parsed as data using inline standard-library AST inspection. The
inspection found the isolation call before runtime imports in all 188 Python
test/fixture modules and all 12 Python validation entry points. Builder source
has no `subprocess`/`runpy` import, source-validator function or synchronization
function. Changed Python source syntax and whitespace were inspected statically.
These observations are not passing unit or integration tests.

After separating generation from validation, the authorized command
`make build PYTHON=/usr/bin/python3` completed with exit status 0 and reported
`built 1744 payload files`. A before/after hash-and-mode inventory found exactly
three changed repository files: `d-i/forky/payload.tar.gz`, `payload.manifest`
and `preseed.cfg`. All other repository files kept their bytes and modes during
that command.

Static archive inspection compared every one of the 1,744 regular members with
the current source bytes and manifest SHA-256 entries. All matched, with the
expected fixed archive metadata. The preseed payload and manifest pins matched
the regenerated products. This inspection did not execute archived code.

## Live limits

No approved disposable VM/image was provisioned or executed in this turn.
The new guard, init lifecycle, regression assertions and native AppArmor syntax
have not been exercised in that environment. A full passing suite is not claimed.

The execution environment could not reach the reported host's systemd manager:
the read-only status request reported that systemd was not PID 1 and the system
bus was unavailable. The current state and complete failure cause of
`apt-repo-local-refresh.service` remain unverified. Its installed policy and
service were not changed or restarted. Source permission corrections require
the normal controlled deployment before they affect that host.
