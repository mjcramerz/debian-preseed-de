# Tailscale, shared storage and Filen implementation evidence

This records the initial implementation snapshot. Later fixes and the current
source/artifact fingerprints are in the
[follow-up review](sharing-filen-review-20261017.md). The hashes below identify
this historical snapshot and are not claims about the current working tree.

## Snapshot and acceptance status

Source base: `d9d4934302faf370ffbe231b654837a61d79bda7`, with the working-tree
changes listed below. The payload manifest SHA-256 identifies the complete
serialized source-path/content inventory for this snapshot:
`e228046f700ff7c6ad86d80d4347d368e56aec41520e362d0e487ffb0c0e6a59`.

The target is Debian Forky with systemd 262. **Native acceptance is pending.**
No prepared disposable VM/image was available. No tests, discovery imports,
native syntax/policy parsers, installed management helpers, cloud login, live
mount, service-manager operation or host repair were executed. Target image
identity, kernel version and installed package versions therefore remain
unrecorded acceptance inputs. Follow [test-isolation.md](../test-isolation.md).

The implementation and its current settings are documented in
[sharing-filen.md](../sharing-filen.md). This report records source/serialization
evidence and unexecuted gates; it does not approve deployment.

## Supplied logs and objective 1

All 92 files under `todo/` (4,474,536 bytes) were read as data. The current
October 17 journal reports the netkit ownership identity error, tailscaled
exiting 78, a bootstrap socket wait expiring, and secondboot temporary failures
while bootstrap remains incomplete. The firstboot validation report identifies
`tailscaled.service` as the failed unit. It is not necessary to weaken firstboot
validation or extend its waits to conceal this failure.

The constructor previously passed `alias` in link creation, then immediately
required that alias in its ownership check. The relevant Linux creation path
does not apply that attribute. The implementation now validates the fresh,
down L3 pair, records the interface index and writes its marker through a
pinned sysfs directory before applying the existing strict ownership check.
iproute2 emits reciprocal peer names in the `link` JSON field while both ends
remain in the same namespace. Sources:
[Linux rtnetlink](https://github.com/torvalds/linux/blob/v6.17/net/core/rtnetlink.c),
[iproute2 link formatting](https://github.com/iproute2/iproute2/blob/main/lib/utils.c),
[netkit formatting](https://github.com/iproute2/iproute2/blob/main/ip/iplink_netkit.c).

The existing strict cleanup/ownership behavior is retained. An already running
host with an old unmarked pair/recovery state needs deliberate administrator
recovery or a reboot into the corrected installed implementation; this patch
does not automatically adopt or delete unmarked links. No live repair was made.

The older October 13 journal retained as `todo/.~` also records a Tailscale
device awaiting administrator approval. That external approval remains
necessary; installer code must not bypass it. The supplied Xwayland warnings
were reviewed and excluded from this change, as requested.

## Checks actually performed

1. Read the relevant entrypoints, delegates, renderer, installed paths,
   authorization, AppArmor and shutdown callers as source data.
2. Parse the 13 changed Python source/fixture files using stdlib `ast.parse`
   without importing or executing repository modules. All parsed. This is
   static inspection, not interpreter/runtime acceptance.
3. Inspect profile assignment text: all ten profiles contain exactly one of
   each of the eleven Filen controls and the shared home-view control; retired
   per-role bind controls are absent. An initial ad hoc cardinality assertion
   expected one extra control; replacing it with the explicit key set confirmed
   the source inventory without a source change.
4. `git diff --check`: clean.
5. Review the Makefile, `tools/build.py` and `tools/publication.py` before using
   the permitted pure serialization path. The final command was:

   ```sh
   /usr/bin/timeout --kill-after=2s 60s /usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent /usr/bin/make build PYTHON=/usr/bin/python3
   ```

   It exited 0 and reported `built 1812 payload files`. The same serialization
   path was used for the preceding builds before the final document-policy and
   credential-input changes. No build ran tests or validation runners.
6. Inspect the final gzip/tar and manifest using only stdlib archive/hash reads:
   all 1,812 member byte strings equal their current source and manifest digest;
   inventory is complete, members are regular mode-0644 files with normalized
   ownership/time, and archive/manifest/transport hashes are present in the
   generated preseed. No files were extracted or executed. Tests, private
   preseed inputs and the root example `cli.sh` are excluded from the payload.

### Final generated products

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `0a592286a35804f419a6322f19ec76a85720dd6f26f2b40ae246fe290769672c` |
| `d-i/forky/payload.manifest` | `e228046f700ff7c6ad86d80d4347d368e56aec41520e362d0e487ffb0c0e6a59` |
| `d-i/forky/preseed.cfg` | `b4135e1c8d030a34721f3932c18ee82af68b1cac255e0023108e05d97a2f36b4` |

### Focused fixtures changed or added, all unexecuted

| Fixture under `d-i/forky/tests/` | SHA-256 |
| --- | --- |
| `test_tailscale_netkit_20261017.py` | `4622c7eca9d89a30c59b40a9ce12db852c64445fc638256f121e9f936da7abad` |
| `test_network_sharing.py` | `f9a0fb45cc9086122dd4373d2c228f247d1698a1a6c27340170f37cee5775f46` |
| `test_shutdown_storage.py` | `e490ba9dad1e6c1ce73008f76f12198d576a817b915bc46b3786b93053af4e49` |
| `test_initrd_credentials.py` | `14adcd0677ff392f382d997ab78aa7d269ba4284b7de013ac9499318d8272b72` |
| `test_filen_sync_20261017.py` | `ba3b22e3cd816767830b3d1287b4bdbcaa38b2af4bdb38fb5dd1d7a49e22116a` |

These include mocked netkit identity/replacement, NFS planning/authorization
and shutdown, credential mappings/UTF-8/line-break handling, and Filen
redirect/hash/size/base32/input failure fixtures. The Filen ACL fixture uses
the disposable image's packaged ACL tools
inside its private tree and mocks ownership publication because the required
test image has no capabilities. It checks inheritance; it does not establish
actual cross-UID access or live service isolation.

## Remaining acceptance gates

- Provision and record a disposable Forky VM/image meeting the repository
  isolation contract; record kernel, systemd 262, Python, Perl, Moo/MooX,
  oathtool, ACL, AppArmor, util-linux, iproute2 and Filen package/binary versions.
- Execute the focused fixtures above, the existing affected document-policy
  fixture, and the guarded build/source checks. Record skips and failures.
- Exercise actual netkit creation, pinned marker publication, replacement and
  interrupted publication/cleanup under the target kernel and enforced policy.
- Exercise actual self-bind/shared-root and recursive slave-view propagation,
  mount/unmount visibility, server export readiness, manual client startup,
  exactly one Polkit authorization and ordered shutdown under systemd 262.
- Verify both Filen accounts concurrently with disposable cloud credentials:
  clock/TOTP login, all configured sync modes, restart/database recovery,
  directory ACLs for files created by both UIDs, network failure, output/secret
  redaction, invalid credentials/remote path and bounded full-cgroup teardown.
- Compile/load and reconcile the rendered per-account AppArmor policies; prove
  no cross-account credential/state/tree access, including native Bun addon
  loading and Thunar/document access through the home view.
- Complete a fresh unattended install through bootstrap, firstboot and
  secondboot. Retain native application and private Zoom/Discord launch/stop
  checks. Xwayland eligibility and implementation are unchanged.

## Exact changed paths

The root `cli.sh` was already untracked and remains untouched. The following
paths belong to this implementation, including the three generated products:

```text
d-i/forky/classes/class-select/role/desktop.cfg
d-i/forky/hooks/target/etc/apparmor.d/abstractions/user-documents
d-i/forky/hooks/target/etc/apparmor.d/filen-sync.tmpl
d-i/forky/hooks/target/etc/apparmor.d/usr.sbin.tailscaled
d-i/forky/hooks/target/etc/apparmor/modes.conf.tmpl
d-i/forky/hooks/target/etc/systemd/system/filen-sync@.service.tmpl
d-i/forky/hooks/target/usr/local/bin/labwc-network-sharing
d-i/forky/hooks/target/usr/local/bin/nfsmnt
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/filen/FilenSync/Config.pm
d-i/forky/hooks/target/usr/local/lib/perl5/site_perl/filen/FilenSync/Daemon.pm
d-i/forky/hooks/target/usr/local/libexec/filen-sync
d-i/forky/hooks/target/usr/local/libexec/labwc-admin-action-worker
d-i/forky/hooks/target/usr/local/libexec/network-sharing-identity
d-i/forky/hooks/target/usr/local/libexec/network-sharing-report
d-i/forky/hooks/target/usr/local/libexec/tailscale-netkit
d-i/forky/hosts/installer/hosting.env
d-i/forky/hosts/profiles/btrfs-de-duo.env
d-i/forky/hosts/profiles/btrfs-de-flex-duo.env
d-i/forky/hosts/profiles/btrfs-de-flex.env
d-i/forky/hosts/profiles/btrfs-de-p15s-duo.env
d-i/forky/hosts/profiles/btrfs-de-p15s.env
d-i/forky/hosts/profiles/btrfs-de.env
d-i/forky/hosts/profiles/f2fs-de-hp14-duo.env
d-i/forky/hosts/profiles/f2fs-de-hp14.env
d-i/forky/hosts/profiles/f2fs-de-x360-duo.env
d-i/forky/hosts/profiles/f2fs-de-x360.env
d-i/forky/payload.manifest
d-i/forky/payload.tar.gz
d-i/forky/preseed.cfg
d-i/forky/scripts/common/credentials.sh
d-i/forky/scripts/desktop/filen-install.py
d-i/forky/scripts/desktop/filen.sh
d-i/forky/scripts/desktop/labwc.sh
d-i/forky/scripts/late/desktop.sh
d-i/forky/scripts/late/network-sharing.py
d-i/forky/scripts/late/network-sharing.sh
d-i/forky/tests/test_filen_sync_20261017.py
d-i/forky/tests/test_initrd_credentials.py
d-i/forky/tests/test_network_sharing.py
d-i/forky/tests/test_shutdown_storage.py
d-i/forky/tests/test_tailscale_netkit_20261017.py
docs/network-sharing.md
docs/sharing-filen.md
docs/validation/sharing-filen-20261017.md
tools/check_network_sharing.py
```
