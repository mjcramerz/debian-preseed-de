# Test isolation is mandatory

## Absolute prohibition on host access and host changes

**NO TEST MAY READ, USE, OR MODIFY THE REAL HOST'S CONFIGURATION, SERVICES,
PACKAGE STATE, SECURITY POLICY, NETWORKING, DEVICES, OR USER DATA. NO TEST MAY
EXECUTE AN INSTALLED HOST MANAGEMENT HELPER.**

This applies to every test, fixture, discovery/import hook, test runner,
validation command, audit, benchmark, and smoke check in this repository. A
test's name, comments, mocks, temporary directory, or use of a namespace is not
proof that it is isolated.

- Never run tests directly on the development host. Execute them only inside
  an explicitly prepared disposable environment with no access to host state.
  If that environment is unavailable, stop at static inspection. Do not use
  automatic fallback, an opt-in environment variable, or elevated privileges.
- Never bind the host root, host `/etc`, `/var`, `/run`, `/proc`, `/sys`, `/dev`,
  user HOME, runtime sockets, or installed `/usr/local` helpers into a test.
  Namespace isolation alone does not make a host-root bind safe.
- Never contact the host system or user systemd manager, D-Bus, desktop session,
  CrowdSec API, package manager, or other running daemon. Never start, stop,
  restart, reload, enable, disable, mask, or reset host services or timers.
- Never load AppArmor policy, change host firewall rules, routes, interfaces,
  sysctls, mounts, storage, permissions, ownership, package repositories,
  package lists, credentials, or any file outside owned test fixtures.
- Never execute installed host helpers such as `/usr/local/libexec/apt-repo-local*`
  or `/usr/local/sbin/*`. Fixture programs must come from the checkout or an
  isolated test image, with all state paths and commands explicitly controlled.
- Replace privileged commands and external services with explicit fixture
  implementations. Run native integration checks only inside the disposable
  environment, using its own procfs, sysfs, devices, package tree, managers,
  sockets, and network. No host sockets or writable host mounts are permitted.
- Use a minimal fixture environment. Do not inherit host HOME, XDG runtime
  directories, D-Bus addresses, service variables, credentials, or full `PATH`.
- Keep test writes inside a private fixture tree or the disposable environment.
  Reject paths that resolve outside that tree. Cleanup may remove only resources
  created and owned by that test.

## Work in this checkout

`make build` is generation only. It may write exactly `d-i/forky/payload.tar.gz`,
`d-i/forky/payload.manifest`, and `d-i/forky/preseed.cfg`. It must not execute any
tests, validators, shell snippets, browser generators, policy parsers or host
management helpers, or rewrite source inputs. This pure serialization command
is permitted in the checkout. Source validation belongs to the separately
guarded `make check` / `make validate` commands in the disposable environment.

Preserve all unrelated and uncommitted work. Inspect callers and execution
helpers before editing. Keep fixes narrow and deterministic. Do not build
software from source or change the existing private Xwayland policy for Zoom
and Discord.

Following a host-impact report, do not run any test or validation runner until
its complete execution path and isolation boundary have been reviewed. Static
inspection must parse source as data without importing or executing repository
modules, helpers, shell snippets, or Makefile recipes. Read-only investigation
of a reported host failure is separate from testing; it does not authorize a
host repair, service restart, or configuration change.

Report exact changed paths and checks. Distinguish static inspection, mocks,
isolated integration, and live host execution. Never claim a test passed when
it was not run. Report any interrupted validation and stale generated artifacts.
