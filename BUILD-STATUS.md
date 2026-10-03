# Build status - 2026-10-03 finish-install home permission repair

The final `99-normalize-finish` hook still performed an unrestricted home chmod
walk after the earlier desktop pass. It reached root-owned, immutable Sharing
parents and aborted installation. The final hook now resolves a nonroot UID and
matching home from a unique entry in the target's `/etc/passwd`, verifies ownership,
and physically prunes foreign-owned entries before chmod or descent. Numeric
`-user` works with GNU find and the installer's BusyBox find. Sharing parent
flags and modes, `0000` unmounted endpoints, account-private modes, and fatal
account chmod failures are preserved. No mount, NFS policy, profile, AppArmor or
Xwayland source was changed.

The new fixture reproduced the original fatal directory normalization error.
The focused home/NFS/module/finish-order suite ran 155 tests: 129 passed and 26
were explicitly skipped. All 15 publication contract tests passed. Home tests
include the complete final hook, repeated execution, custom root-owned Sharing
parents, foreign files and descendants, GNU and BusyBox find/awk, symlink
boundaries, malformed/ambiguous identities, and fatal account chmod failures.
Ownership simulation is explicitly labelled: native foreign UID and immutable
fixtures cannot run in this environment, and private mount namespaces are denied.

The rebuilt snapshot contains 1694 payload files. Build freshness and all 59
preseeds passed, including private debconf command read-back. All 709 parser
checks across 349 shell sources passed with dash, bash and the official BusyBox
1.35.0 x86_64 musl binary. The whole-tree audit reported zero explicit failures:
612 syntax passes, 224 unit structure checks, 159 blocked Perl dependencies,
616 inventory-only records and 11 unrendered templates. These are offline checks;
the available systemd is 255, not the deployment's fixed systemd 261.2.

No software was compiled. No live Forky installation, immutable bind-mount/NFS
acceptance, enforcing AppArmor test or target service activation was performed.
The pre-existing broad-suite failures recorded below remain outside this repair;
those broad suites were not rerun. Publish the complete snapshot atomically and
perform an unattended installation on the intended deployment platform.

## Previous snapshot record: Codex, browser and Sharing integration


The desktop permission pass now prunes every foreign-owned entry before changing
modes or descending into directories. The NFS installer deliberately creates
root-owned, immutable home bind parents such as `/home/mcramer/Sharing` before
desktop configuration. The former home-wide chmod pass reached that protected
parent and failed with `Operation not permitted`; `find -xdev` did not exclude it.
All four permission walks now use physical traversal and an account-UID pruning
predicate. Root-managed parents and their `0000` unmounted endpoints remain
untouched, while account directories, data, programs and systemd units retain
their private modes. No immutable flag is cleared and no chmod failure is hidden.
The previous delivered block reproduces the protected-path failure in the
regression fixture with dash and official BusyBox ash; the corrected block passes.

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

The focused permission/browser/NFS/provenance suite ran 77 tests: 70 passed,
and seven were skipped. Five native ownership tests could not establish foreign
UID fixtures; the native systemd condition checker could not initialize, and the
AppArmor parser was unavailable. The new home permission regressions exercised
real find/chmod behavior, symlink boundaries and fatal error propagation. Their
mixed-ownership fixture substitutes only the UID predicate and guards protected
paths with EPERM; it is not a native immutable-flag acceptance test. Real
file-descriptor copying, atomic publication, collision handling and failure
cleanup also passed using separately labelled simulated ownership. The real Git
checkout test used a local transport fixture, without GitLab authentication.
All 15 module, source-mode and publication contract tests passed on this tree.
All ten NFS profiles passed the target-policy preflight.

The whole codebase audit completed with zero explicit failures: 601 passed syntax
checks, 224 systemd structure checks, 159 blocked Perl dependency checks, 11 blocked
tool checks, 616 inventory-only records and 11 templates requiring rendering.
Structure, inventory, blocked and unrendered checks are not runtime passes.

The broad suites remain **not green**. With the same Python runtime, BusyBox and
validation environment, a fresh extraction of the uploaded ZIP previously ran
3224 installer tests with 696 failures, 331 errors and 186 skips. The prior
delivered tree ran 3238 tests with 676 failures, 330 errors and 190 skips. This
corrected tree ran 3245 tests with 675 failures, 331 errors and 191 skips. Subtests
contribute multiple failures. All three trees ran 217 tools tests with the same
three failures and 74 errors. Comparing failing test identifiers with the prior
delivery, while ignoring shifted line numbers and generated temporary directory
names, found no new failing identifiers. Unrelated source/test repairs and test
suppression were not introduced to conceal these results.

No live Forky/systemd 261.2 installation, private GitLab authentication, browser
extension installation/import, hardware boot, NFS service activation or enforcing
AppArmor acceptance was performed. This archive contains the implemented fixes
and reproducible build products; it is not a claim of full production acceptance.
Run the project gates on the deployment host and publish the complete checked
repository with an atomic directory switch.
