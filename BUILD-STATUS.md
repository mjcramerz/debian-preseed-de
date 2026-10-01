# Build status - 2026-09-30 NFS integration

This snapshot adds profile-controlled NFSv4 network sharing, managed firewall
integration and the Computer Management network-sharing submenu. All ten
profiles ship with NFS server/client and home binds disabled. The sharing root
is still created. See [the configuration guide](docs/network-sharing.md).

## Generated installer snapshot

The complete source tree and regenerated `d-i/forky/preseed.cfg`,
`d-i/forky/payload.manifest`, and `d-i/forky/payload.tar.gz` are included.
`make build` succeeded with 1689 payload files. `make check` confirmed that
snapshot, pins and preseed match the source and passed 705 parser checks across
347 shell files. The separate preseed check passed all 59 files and preserved
all four generated command values through private debconf read-back. BusyBox
ash was available for these checks; no substitute shell was used for its gate.

## Validation status

The focused NFS suite passed 46 tests, seven existing firewall/installer
integration tests passed, and three updated menu-routing contracts passed.
The AppArmor policy parsed and real systemd-generated mount/automount units
were inspected. `make audit` completed: 609 pass, 222 structure-pass,
159 blocked-dependency, 616 inventory-only, 11 template-needs-render.
Only the first category means a passed check; none of these categories alone
certifies runtime acceptance.

The broad repository suites are **not green**. A selected 92-case comparison
against a pristine extraction produced 133 failures and six errors on the
original, and 114 failures and six errors on this final snapshot; subtests
can produce more failures than selected cases. Every remaining failing case
identifier also fails on the original. The full tools suite ran 244 tests
and has the same three failing cases on both trees. An earlier exploratory
full installer-suite run was not a final release certification. No unrelated
source repairs or test suppression were made to hide these results.

This container runs systemd 257.9, not the requested target's 261.2. Package
fetches for additional live test tools were blocked by DNS, and network
namespace/kernel firewall tests were unavailable. Real NFS permission tests,
boot/offline-server behavior, GUI/Polkit authorization, and enforcing AppArmor
behavior on Forky/systemd 261.2 remain unverified. Do not treat this archive as
a production-accepted release solely because offline NFS checks pass.

See the [validation record](docs/validation/network-sharing-20260930/README.md)
for commands, raw logs, exact comparisons, preservation evidence, and target
acceptance requirements. On the release host, run the complete project gates
(`make build`, `make check`, `make test`, `make audit`, `make validate`), resolve
remaining release failures, and perform the documented live acceptance before
production publication. Review destructive disk settings and credentials, and
publish the complete checked repository atomically.
