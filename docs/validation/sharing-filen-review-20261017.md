# Follow-up review: Tailscale, shared storage and Filen

## Snapshot and acceptance boundary

This follows the [initial implementation evidence](sharing-filen-20261017.md).
Base revision: `d9d4934302faf370ffbe231b654837a61d79bda7`, plus the existing
implementation changes and the narrow follow-up changes listed below.
The current serialized source-path/content fingerprint is the payload manifest
SHA-256: `f3f677e6e953f6196dffe597445a0974b4d1e352298ef9545fcffcb856968656`.
Fixture hashes are recorded separately because tests are excluded from payloads.

Target contract: Debian Forky, systemd 262, pinned Filen CLI 0.0.36. No prepared
disposable VM/image was available, so **native acceptance remains pending**.
No test runner, fixture import, native syntax/policy parser, installed management
helper, service-manager operation, cloud login, live mount or host repair was
executed. The target image identity, kernel and installed package versions are
unverified acceptance inputs. The required isolation boundary is in
[test-isolation.md](../test-isolation.md).

## Confirmed findings and corrections

1. **Private installer umask hid public Filen parents.** Newly created module
   and configuration parents inherited mode 0700 under the installer's umask
   077. Root compilation could succeed while the service UID could not import
   the installed modules. New directories are created privately, opened without
   following a final symlink, then assigned root:root and their explicit mode
   through the pinned descriptor. Existing directories are preserved. Published
   files explicitly receive root:root, including under a setgid parent.
2. **Root-only compilation did not prove service-user access.** The installer
   now compiles the installed trusted wrapper as each enabled service UID and
   primary GID with no supplementary groups. Every compile must succeed before
   the first offline enable operation. Python's documented
   [subprocess identity arguments](https://docs.python.org/3.14/library/subprocess.html#popen-constructor)
   implement the UID/GID boundary. This installation-time gate is not an
   AppArmor or native CLI acceptance result.
3. **A final read could return valid bytes after the download deadline.** The
   download now checks its monotonic deadline after every read, including EOF,
   before accepting data. The 300-second acceptance deadline, individual socket
   timeout and outer 420-second installer timeout remain separate bounds; an
   in-progress blocking operation is not claimed to terminate at exactly 300
   seconds. Redirect origin, hop, byte, hash and architecture checks remain.
4. **Remote path contents could be mistaken for errors.** The supervisor now
   classifies exact messages from the pinned CLI, including its ANSI red error
   wrapper, rather than searching whole lines for error phrases. The expected
   startup and missing-directory messages include the configured UTF-8 remote
   path. A legitimate path containing error words cannot trigger that match.
   Raw output remains bounded and unlogged. Sources: pinned
   [sync interface](https://github.com/FilenCloudDienste/filen-cli/blob/v0.0.36/src/app/featureInterfaces/syncInterface.ts),
   [console adapter](https://github.com/FilenCloudDienste/filen-cli/blob/v0.0.36/src/index.ts)
   and [ANSI formatter](https://github.com/FilenCloudDienste/filen-cli/blob/v0.0.36/src/framework/util.ts).
5. **Output EOF caused frequent worker polling.** The EOF branch now waits one
   second between worker checks instead of 0.1 seconds. Cgroup ownership,
   startup observation, unexpected-exit handling and PID 1 stop escalation are
   preserved. This is a source-derived reduction in polling, not a measured
   CPU or throughput result.
6. **Inactive NFS roles inherited an unnecessary numeric identity condition.**
   Creating the shared home view now uses the existing desktop identity when
   both NFS roles are disabled. Home, reserved-identity and canonical UID checks
   still apply. Active NFS roles still require the configured AUTH_SYS UID/GID
   agreement before home-view preparation or package mutation. No account is
   renumbered.

## Integration review

- Traced desktop selection, credential mapping and private staging through the
  target publisher, installed Moo/MooX modules, account configuration, systemd
  template, AppArmor template and GTK skeleton bookmarks.
- Reviewed the shared-root/home-view/client dependency graph, manual client
  entrypoint, Polkit operation and shutdown transaction. systemd 262's
  [fstab generator](https://github.com/systemd/systemd/blob/v262/src/fstab-generator/fstab-generator.c)
  accumulates repeated `x-systemd.requires-mounts-for` paths; it does not discard
  the first path. The existing native generator fixture now checks both paths.
- Rechecked the Tailscale fresh-pair identity, pinned sysfs alias publication,
  retained recovery state and constructor policy against the service path.
  No additional Tailscale or firstboot changes were needed in this pass.
- The supervisor and CLI share each account's UID/profile and can both read its
  service credential view. The TOTP seed is omitted from the CLI environment;
  it is not claimed to be inaccessible to that UID. Cross-account DAC,
  credential, state and writable-tree boundaries remain separate.
- Two bounded read-only reviewers were attempted but failed during runtime
  context initialization. They supplied no findings or independent acceptance
  evidence; this report records the coordinator's direct source review.

## Checks actually performed

1. Source/diff and primary-documentation inspection; no repository runtime
   imports or shell snippets executed for inspection.
2. `/usr/bin/python3 -I -S -B` with a bounded stdlib-only stdin reader parsed all
   13 affected Python source/fixture files with `ast.parse`. It inspected all
   ten profile files as assignment text: exactly one occurrence of each of the
   eleven Filen controls and the shared home-view control, with retired per-role
   bind controls absent. No profile was sourced.
3. `git diff --check` exited 0 with no findings.
4. Reviewed the complete Makefile build recipe, `tools/build.py` and
   `tools/publication.py`, then ran only the permitted pure serialization path:

   ```sh
   /usr/bin/timeout --kill-after=2s 60s /usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent /usr/bin/make build 'PYTHON=/usr/bin/python3 -I -S'
   ```

   It exited 0 and reported `built 1812 payload files`. It executed no tests,
   source validators, native parsers, package operations or management helpers.
5. A separate bounded stdlib-only archive/hash reader inspected the products
   without extraction or execution. All 1,812 regular members, totaling
   34,674,359 bytes, equal the current source bytes and their manifest digests;
   member ownership, mode and timestamps are normalized. The complete source
   inventory matches the archive and manifest. The generated preseed contains
   the current archive, manifest and transport-source pins. Tests, private
   inputs and root `cli.sh` are excluded.
6. Static documentation inspection found clean line endings/trailing whitespace
   in all three affected documents and confirmed that all eight local Markdown
   link targets exist inside the checkout.

### Current generated products

| Product under `d-i/forky/` | SHA-256 |
| --- | --- |
| `payload.tar.gz` | `a940fcc7f38488a85624b93b2ad3f9f4735521283413120f20370161fb86ec21` |
| `payload.manifest` | `f3f677e6e953f6196dffe597445a0974b4d1e352298ef9545fcffcb856968656` |
| `preseed.cfg` | `a6b15dcc0be5da306510c4bb39abde13dc31e92bc4de931a36879fdf3fa0cf3e` |

### Focused fixtures, all unexecuted

| Fixture under `d-i/forky/tests/` | SHA-256 |
| --- | --- |
| `test_filen_sync_20261017.py` | `5c76f94a3fafd73b0ae5c868049c4c1ab0667f708d78aa708f737df7e33e77db` |
| `test_network_sharing.py` | `43901f12b4bf06ffc34f7cceb1be8a41013c211db0413104829daec564cac2a3` |
| `test_initrd_credentials.py` | `14adcd0677ff392f382d997ab78aa7d269ba4284b7de013ac9499318d8272b72` |
| `test_shutdown_storage.py` | `e490ba9dad1e6c1ce73008f76f12198d576a817b915bc46b3786b93053af4e49` |
| `test_tailscale_netkit_20261017.py` | `4622c7eca9d89a30c59b40a9ce12db852c64445fc638256f121e9f936da7abad` |

New fixtures cover private-umask publication, ownership failure preserving the
previous file, service-identity command arguments, second-account compile
failure preventing all enablement, late valid download bytes, exact Perl output
classification with Unicode/error-word paths, and inactive versus active NFS
identity handling. The existing native generator fixture checks both required
mount paths. Mocked process/clock cases and private filesystem/Perl cases are
distinct; none has been executed in this review.

## Remaining acceptance gates and upstream limitation

All native gates from the initial report remain: isolated Forky package/runtime
checks, enforced AppArmor, netkit publication/recovery, actual mount/unmount
propagation, one client authorization, both Filen accounts and all selected sync
modes, TOTP login, ACL inheritance/access, network failure/recovery, secret/output
redaction, bounded cgroup teardown and an unattended install through firstboot
and secondboot. Retain native application and private Zoom/Discord regression
checks. Record target image/package versions and the source/fixture hashes above
with results. Source serialization does not establish those outcomes.

The pinned upstream CLI's
[logging implementation](https://github.com/FilenCloudDienste/filen-cli/blob/v0.0.36/src/framework/app.ts)
accumulates messages in memory, including verbose events when verbose console
output is disabled, until a string-size threshold. Its actual long-run memory
behavior must be measured in the disposable native acceptance environment.
This review does not claim a measured bound for Bun or modify/recompile vendor
code, add arbitrary memory ceilings, or force periodic sync interruptions.

## Exact paths changed by this follow-up

```text
d-i/forky/scripts/desktop/filen-install.py
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/filen/FilenSync/Daemon.pm
d-i/forky/scripts/late/network-sharing.py
d-i/forky/tests/test_filen_sync_20261017.py
d-i/forky/tests/test_network_sharing.py
d-i/forky/payload.tar.gz
d-i/forky/payload.manifest
d-i/forky/preseed.cfg
docs/sharing-filen.md
docs/validation/sharing-filen-20261017.md
docs/validation/sharing-filen-review-20261017.md
```

The initial report's historical hashes are preserved. The existing untracked
root `cli.sh` remains untouched and has no installation dependency. There are
no new source builds, Xwayland changes, host configuration changes or deployment
operations in this follow-up.
