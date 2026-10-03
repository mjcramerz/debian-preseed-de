# Build status - 2026-10-03 Codex and browser integration

The Codex publisher now accepts the private `0600` daemon-settings mode that
previously aborted installation. All ten host profiles define the SSH repository
`git@gitlab.com:core-assets/helpers/netscape.git`, branch `mcr/main`, and checkout
`Workspace/netscape`; there is no commit pin. The desktop installer reuses its
short-lived private SSH agent, stages the checkout privately, and publishes it
without replacing an existing checkout. Directories are account-owned `0700`,
regular data files are `0600`, and executable repository files are `0700`.
Symlinks, hard-linked files and special files are rejected. Target verification
checks the checkout ownership, modes, entry types and branch.

Browser policies are generated from `browser-config/policies.json` and staged
for Vivaldi, Chromium, Chrome and Edge. NoScript, Privacy Badger and uBlock Origin
Lite use `normal_installed` and default toolbar pinning. Managed extension storage
and the locked file-URL option are absent; users control extension settings and
manually import exports from the netscape checkout. Full uBlock Origin is Manifest
V2 and cannot be deployed to current Chrome through the Chrome Web Store. Edge's
existing AppArmor restriction on Workspace remains; intentional imports there
can use Downloads. Existing browser security and telemetry policy is preserved.

## Generated snapshot and permissions

The complete tree includes regenerated `d-i/forky/preseed.cfg`,
`d-i/forky/payload.manifest`, and `d-i/forky/payload.tar.gz` with 1694 payload files.
All source files use the project's nonexecutable `0644` contract; source
directories are `0755`, so ordinary HTTP/NFS service accounts can read the served
tree. Installer staging still applies its explicit executable, private-state and
credential modes. A review of 355 literal target staging paths found no conflicting
modes and no mismatch against their literal verifier checks. Every original profile
byte outside the three added browser assignments and their comment is preserved.
Xwayland source content and all Xwayland profile values are unchanged.

## Validation

Build and browser freshness checks passed. All 59 preseed files passed, including
private debconf read-back of all four generated command values. All 709 parser
checks across 349 shell sources passed using dash, bash and the official BusyBox
1.35.0 x86_64 musl binary. No executable was compiled or added to the source tree.

The focused installer/browser/provenance suite ran 38 tests: 34 passed, and four
native non-root ownership tests were skipped because this container rejects
ownership changes to the target UID/GID. Real file-descriptor copying, atomic
publication, collision handling and failure cleanup also passed using separately
labelled simulated ownership. The real Git checkout test used a local transport
fixture; it did not authenticate to GitLab. All 15 existing module/publication
contract tests passed.

The whole codebase audit completed with zero explicit failures: 601 passed syntax
checks, 224 systemd structure checks, 159 blocked Perl dependency checks, 11 blocked
tool checks, 616 inventory-only records and 11 templates requiring rendering.
Structure, inventory, blocked and unrendered checks are not runtime passes.

The broad suites remain **not green**. With the same Python runtime, BusyBox and
validation environment, a fresh extraction of the uploaded ZIP ran 3224 installer
tests with 696 failures, 331 errors and 186 skips. This tree ran 3238 installer tests
with 676 failures, 330 errors and 190 skips. Subtests contribute multiple failures.
Both trees ran 217 tools tests with the same three failures and 74 errors. Comparing
failing identifiers while ignoring shifted line numbers and generated temporary
directory names found no new failing identifiers. Unrelated source/test repairs
and test suppression were not introduced to conceal these results.

No live Forky/systemd 261.2 installation, private GitLab authentication, browser
extension installation/import, hardware boot, NFS service activation or enforcing
AppArmor acceptance was performed. This archive contains the implemented fixes
and reproducible build products; it is not a claim of full production acceptance.
Run the project gates on the deployment host and publish the complete checked
repository with an atomic directory switch.
