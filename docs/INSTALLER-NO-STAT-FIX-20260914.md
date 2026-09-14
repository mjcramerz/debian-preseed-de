# Debian Installer Codex staging: remove the installer-side stat dependency

Date: 2026-09-14

Base: `debian-preseed-de-codex-clone-fixed.tar.gz`

Base SHA-256: `0c3b411848f0c9c23c07cd7b9eb5a1671ebfed02a80d8bac456599aa92f049a3`

This review supersedes the previous staging report's claim that its shell test
fixture adequately represented the installer command set. It does not supersede
the SSH/GPG trust model, GitOps policy, debug collection policy or service design.

## 1. Reproduced failure and cause

The previous `devops_install_pinned_codex()` executed these two expressions in
Debian Installer, outside the installed system:

```sh
stat -c %u -- "$clone_parent"
stat -c '%u:%a' -- "$clone_parent"
```

The reported installer does not have that command. When the first command
substitution failed, its empty output was compared to `0`. The shell therefore
printed `private Codex clone staging directory is not root-owned`, even though
the fixture directory was actually owned by root. That second message was a
consequence of the missing command, not evidence of a genuine ownership change.

The previous source was exercised before modification with an installer PATH
containing only the explicitly selected BusyBox applets. Dash, BusyBox ash and
Bash all reproduced the missing-command error followed by the misleading
ownership error. See `validation/installer-no-stat-fix/pre-fix-no-stat.log`.

The old fixture had explicitly installed a `stat` applet symlink and allowed a
fallback to `/usr/bin:/bin`. That made an unsuitable host command available in
testing. The new regressions assert that `command -v stat` fails, and also test a
poisoned `stat` executable that must never be invoked.

## 2. Narrow implementation

The only production source change is in
`d-i/forky/scripts/late/devops.sh`, inside `devops_install_pinned_codex()`.

It now reuses `installer_metadata_value` from the existing generated common
library. That function is authored in `scripts/common/lifecycle.sh`, embedded in
`common/lib.sh` and `common/source.sh`, and loaded by
`bootstrap_source_common_lib` before the late helper invokes the allocator.
It uses `LC_ALL=C ls -ldn` and, for mode conversion, `awk`. It parses numeric
metadata fields, not filenames, and disables pathname expansion while splitting
those fields. No new installer utility, package, Python interpreter or fallback
permission bypass has been introduced.

The sequence is now:

1. Create the private stage under the existing `root:devops` mode-`3770` root.
2. Require a direct directory and inspect its UID through the canonical reader.
3. Report inspection failure separately from an observed non-root UID.
4. Apply `0700` and explicitly clear inherited set-ID bits with `chmod a-s`.
5. Re-read UID, GID and mode. Require root UID and exactly mode `700`; permit the
   deliberately inherited numeric devops GID.
6. Invoke the existing private SSH clone helper and then the existing publisher.

The Python clone helper's independent direct-directory/root/`0700` validation
remains unchanged. A real non-root stage is rejected without `chown` repair.
A symlink is rejected without changing its referent. A failing or ineffective
`chmod`, failed metadata read, or malformed metadata prevents the SSH action.

The existing subshell, private umask and exit/signal cleanup traps are retained.
No clone or publication occurs after validation failure. Clone failure prevents
publication and removes partial staging.

## 3. Installer/target boundary review

The review covered metadata-command occurrences in `scripts/common`,
`scripts/runtime`, `scripts/late` and `scripts/desktop`, and traced their execution
contexts rather than replacing every occurrence of the word `stat`.

| Context | Decision |
| --- | --- |
| Codex clone allocator in d-i | Replace the two bare `stat` calls with the canonical installer reader. |
| Credential ingestion and lifecycle in d-i | Existing no-stat readers retained. |
| `devops_assert_target_metadata`, desktop installer-supervisor checks, Podman filesystem check, software target checks | Existing explicit `chroot ... /usr/bin/stat` calls retained. They use the installed system's tools and target-relative paths. |
| SSH server, account, CrowdSec, storage, desktop verification and other inline target snippets | Existing calls execute inside `run_in_target`/`run_in_target_quiet` or an explicit target chroot. Retained. |
| Llama/Whisper helpers | Metadata functions belong to the `--target-install` branch invoked inside the target. Retained. |
| Python `stat` imports and `Path.stat`/`os.stat` calls | Library APIs, not an external installer applet. Retained. |
| Installed SSH/GPG helpers, GitOps, debugsys, AppArmor and systemd assets | No production changes in this correction. |

Raw pre-change metadata inventory is included as `metadata-review.txt`; it
contains comments, Python APIs and target-side code as well as shell calls, and
must not be interpreted as a list of uncorrected installer failures.

## 4. Executable regression coverage

The staging suite has 33 tests, including nine newly added test methods. The
new coverage includes three real shell interpreters with `stat` absent, a
poisoned command, a real Git clone through the production allocator/validator in
a disposable chroot with no installer-side stat, independent inspection errors,
malformed metadata, genuine wrong ownership, symlink rejection and clone-failure
cleanup. Existing permission normalization, publication readability, tracking
branch and cancellation tests remain active.

A separate integration check sources the complete generated common library,
not just the extracted metadata function, and runs the production allocator
under Dash, BusyBox ash and Bash with the restricted PATH. All three complete
without a missing command or false ownership diagnostic.

The additional `minimal-initrd-rootfs-check.py` builds a disposable chroot from
installed BusyBox and its shared libraries. Neither `/bin/stat`, `/usr/bin/stat`
nor `/usr/bin/python3` exists inside it. It sources the complete generated
common library: the previous allocator reproduces both reported errors; the
corrected allocator publishes the fixture and cleans its stage with no stderr.
The shared `root:65534` mode-`3770` parent stays unchanged in both runs. This
checks filesystem-level absence of the utility, not just PATH lookup.

The BusyBox tests use this container's installed BusyBox with a deliberately
restricted applet PATH. They are not claimed to be execution of a downloaded
`busybox-udeb` binary. The real-Git fixture uses local transport, not real
OpenSSH authentication or the private GitLab repository.

The complete validation results and remaining environmental/fixture failures
are recorded in `docs/INSTALLER-NO-STAT-VALIDATION-20260914.md` and the matching
`validation/installer-no-stat-fix/` logs. Historical validation logs from prior
releases remain historical; they are not represented as this release's results.

## 5. Preserved security and runtime behavior

Private input paths stay `/preseed.env`, `/git_ed25519` and `/git_ed25519.pub` in
the private initrd. Do not place them in the HTTP-served checkout. The encrypted
SSH identity, GPG-sealed passphrase, temporary installer agent, strict host-key
policy and desktop agent lifecycle are unchanged. The Codex checkout remains
`mcr/main` tracking `origin/mcr/main`, with the main `.git/HEAD` retained.

The earlier checkout-child umask correction is retained. The private enclosing
stage stays `0700`, while publication can make the nonsecret configuration
readable to the desktop user as already designed.

AppArmor profiles, `PrivatePIDs`/`PrivateUsers` choices, power-action code,
GitOps protection lists, debugsys and the runtime Codex isolation wrapper are
unchanged. No application, system component or helper was compiled to produce
this correction. Build commands regenerate repository payloads and checksums.

## 6. Deployment

Publish the complete newly built repository snapshot together. In particular,
`preseed.cfg`, `payload.manifest` and `payload.tar.gz` must be from this same
release. The corrected `scripts/late/devops.sh` is present in the rebuilt
payload, and its digest agrees with the manifest.

Start a fresh installer boot against the new snapshot. Do not simply resume the
failed cached helper in `/tmp/install-runtime/bootstrap/late-helpers/`: the
installer verifies and caches its pinned payload before later installation
phases, and replacing server files does not replace the cached running script.
Regenerate separately pinned boot/preseed inputs when your deployment embeds
those values; the private SSH key and its passphrase do not need to change.

```sh
sha256sum -c debian-preseed-de-installer-no-stat-fixed.tar.gz.sha256
tar -xzf debian-preseed-de-installer-no-stat-fixed.tar.gz
cd debian-preseed-de
python3 -B tools/build.py --check
python3 -B -m unittest discover -v -s d-i/forky/tests \
  -p test_codex_clone_staging.py
```

Run the root-dependent filesystem/chroot regressions in a disposable root-capable
Linux environment with BusyBox and Git installed; non-root runs explicitly skip
those tests. They all executed in the supplied verification run.

A fresh unattended installation on a disposable target is still the acceptance
check for the full boot/install/SSH/GPG/hardware path. The supplied container
cannot establish that every possible deployment is failure-free. No claimed
live installation, real provider authentication or AppArmor enforce-mode
acceptance is inferred from unit tests or names-only policy parsing.

## References

Repository evidence is in the source patch and executable logs packaged with
this release. Debian's installer documentation distinguishes commands run in
the installer from those run in `/target` with `in-target` or `chroot`:

https://www.debian.org/releases/trixie/amd64/apbs05.en.html
