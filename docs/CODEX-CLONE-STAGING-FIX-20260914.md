# Codex private clone staging fix - 14 September 2026

## Pre-implementation review

Basis: the supplied `debian-preseed-de-lifecycle-reviewed.tar.gz`, not the
original ZIP. The delivered archive checksum was verified before extraction.
The reported failure is:

```
managed-ssh-install: InstallError: unsafe Codex clone staging parent
fatal: failed to clone codex-home over the private installer SSH identity
```

### Reproduced cause

`devops_prepare_codex_layout()` deliberately prepares `/data/codex` as
`root:devops`, mode `3770` (sticky, setgid, group-shared). The newer
`devops_install_pinned_codex()` allocates `.home-clone.XXXXXXXX` underneath it
using `mktemp -d` but does not clear inherited setgid. The resulting direct,
root-owned directory is mode `2700`, not `0700`. The Python installer clone
helper correctly insists on exactly `0700` and rejects it before invoking Git.
This reproduces the user's exact diagnostic without any key, passphrase,
network, AppArmor policy change, or real target modification.

The reproduction also establishes that GNU `chmod 0700` alone leaves that
directory at `2700`; explicitly clearing set-ID bits is necessary. Therefore
removing the safety check, allowing group access, changing `/data/codex` itself,
or adding an AppArmor allow rule would be the wrong repair.

Evidence: `validation/clone-staging-fix/pre-fix-reproduction.log`.

### Integration path reviewed before editing

1. `scripts/late/devops.sh`: shared-root preparation, clone allocation, private
   SSH action, release/archive preflight, repository promotion, rollback,
   ownership normalization and final tmpfiles verification.
2. `scripts/common/ssh.sh`: exact private-initrd filenames, secret reader,
   private stdin pipe, target proc/dev mount ownership and cleanup, and
   installer-only helper staging.
3. `hooks/target/usr/local/libexec/managed-ssh-install.py` and the askpass helper:
   exact staging path and metadata checks, encrypted-key/public-key proof,
   anonymous sealed passphrase descriptor, temporary agent supervision,
   clean Git/SSH environment, pinned hosts, branch/upstream checks and cleanup.
4. Codex archive/state verifiers: the later `.install.*` stage has a different
   permissions contract (private access, not exact no-setgid mode), and
   publication already explicitly clears special bits. There is no evidence
   that it needs a permissions-policy change to repair this failure.
5. Existing regressions cover prepared-root setgid and private-key handling,
   but did not execute the clone allocator and Python validator together under
   the deployed `3770` parent. That missing boundary test explains why the
   previous focused suites did not detect this failure.
6. The reported diagnostic is an application metadata rejection, not an SSH
   authentication error or an AppArmor denial. No runtime agent, service
   namespace, power-flow, GitOps or debugsys policy change is needed to repair
   this reproducer. Those integrations must remain intact and be regression
   checked rather than rewritten.

### Narrow implementation decision

Normalize only the newly allocated clone staging directory before invoking the
private SSH action: private umask, direct/root-owned checks, explicit clearing
of set-ID bits and exact postcondition verification. Preserve `/data/codex`
mode `3770`, the inherited group identity, the Python exact `0700` rejection
policy, and trap-based cleanup. Improve the Python error with nonsecret
expected/observed ownership and mode, without logging child output or secrets.

Add executable regressions with real filesystem permissions, both GNU and
BusyBox shell/tool paths, failed-normalization checks, cleanup checks, and a
chrooted real-Git clone using a local test transport. The local transport is
explicitly not an OpenSSH/GitLab authentication test.

### Follow-on publication review before its implementation

After repairing allocation, the real-Git fixture exposed a second boundary
issue in the same private clone path. The installer helper's umask `077` is
inherited by Git, creating ordinary checkout files `0600` and directories
`0700`. Publication makes `etc/` content root-owned and preserves its modes
with `cp -a`; it does not add read/traverse permissions to nested content.
Thus root-owned `/etc/codex` configuration would not be readable by the primary
user even after the reported clone failure was repaired. The new executable
publication regression reproduces this before the follow-on change; see
`validation/clone-staging-fix/pre-publication-fix-proof.log`.

The narrow correction is a child-only `umask=0o022` for Git clone via Python's
`subprocess.Popen` parameter. The installer parent remains at `077`, every
other supervised command inherits its existing umask, the enclosing clone
stage stays root-only `0700`, and SSH identity/agent staging and configuration
remain private. This restores ordinary tracked checkout modes (`0644` files,
`0755` directories and executable files) for the existing publisher. It does
not alter private-key or GPG ciphertext permissions, shared-root permissions,
published Git metadata policy, service hardening, or AppArmor permissions.

The added tests run the actual config-copy/permission block, verify effective
read but not write access as an unprivileged UID after publication, verify
that the same UID cannot traverse the private staging directory, and check
parent/default-child umask preservation on success and failure.

### Primary documentation consulted

- GNU Coreutils, Directory Setuid and Setgid:
  https://www.gnu.org/software/coreutils/manual/html_node/Directory-Setuid-and-Setgid.html
- Python 3.13 subprocess, child-only `Popen(umask=...)`:
  https://docs.python.org/3.13/library/subprocess.html
- Linux man-pages, mkdir(2), parent setgid inheritance:
  https://man7.org/linux/man-pages/man2/mkdir.2.html

The source trace and real filesystem reproduction are the basis for this fix;
these references corroborate the filesystem and command semantics. No software
component will be compiled and no service or initramfs will be activated for
this validation.

## Implementation and validation

The final validation record is supplied separately as
`CODEX-CLONE-STAGING-VALIDATION-20260914.md`. Historical review reports are kept
unchanged and must not be mistaken for results of this revision.

## Deploying this correction

Use the complete corrected repository snapshot, including its matching
`d-i/forky/preseed.cfg`, `payload.manifest` and `payload.tar.gz`. They have been
regenerated from the corrected source; the runtime payload contains both fixes.
Publish the matched snapshot atomically rather than overlaying individual files
while a machine is installing. Verify it with:

```sh
python3 -B tools/build.py --check
```

Restart the failed installation using the new matched snapshot. This installer
caches the pinned payload before partitioning: changing the HTTP-served source
files cannot repair the code already unpacked by the failed run. Do not delete
or hand-edit an active installer's cache as a substitute for a clean rerun.

Keep `/preseed.env`, `/git_ed25519` and `/git_ed25519.pub` in the private initrd,
not in the served checkout. The fix does not require changing the SSH key,
passphrase, GPG setup, GitLab URL or branch. Do not change `/data/codex` to `0700`,
permit `2700` in the helper, or disable AppArmor to bypass this diagnostic.

On the disposable target, confirm that installation proceeds beyond the private
clone, that the installed repository remains on tracking `mcr/main` with its
main `.git/HEAD` retained, and that root-owned `/etc/codex` configuration can be
read by the primary user. Then repeat the SSH/GPG login/unlock/logout checks from
the prior operations guide. No real Git provider authentication or physical
d-i installation was performed in the validation container.
