# Installed desktop failure review — 2026-10-13

## Follow-up: updated LPL-162 logs, 10:52 launch

The updated `todo/vivaldi` has 36 lines and `todo/journalctl` has 1,572 lines.
Both files were inspected as data. The earlier snapshot and its generation
evidence are retained below as history.

The new failure is explicit at `todo/vivaldi:34` and `todo/journalctl:1520`:

```text
TypeError: run_veth_sandbox() got an unexpected keyword argument 'graceful_shutdown'
```

The persistent browser caller and PurePrivacy caller pass this keyword to
`sandbox.run_veth_sandbox`. The lower `network_namespace.run_veth_sandbox`
already accepts it, but the intermediate facade omitted the parameter and its
forwarding. This omission aborts the launcher before namespace/proxy/payload
startup. The facade now accepts `graceful_shutdown: bool = False` and passes its
value unchanged to the lower supervisor. The private procfs check remains before
delegation. Default network/shutdown behavior and all existing callbacks remain
unchanged. The shared fix covers Chromium, Microsoft Edge, Vivaldi, Mullvad
Browser and PurePrivacy qBittorrent. Native qBittorrent already invokes the lower
supervisor directly with the supported keyword.

Existing mount-plan fixtures replaced the intermediate facade with a permissive
mock accepting arbitrary keywords, so they could not catch this omission. The
persistent and PurePrivacy fixtures now retain the real facade and mock the
lower supervisor with `autospec=True`, which enforces its actual signature.
Their browser payload/shutdown expectations now include the shared proxy
supervisor, and installed policy-file validation is explicitly mocked. A direct
facade regression covers true/false shutdown choices, the unchanged defaults,
all callbacks, inherited descriptors and exit-status forwarding. These guarded
tests were added/updated but were **not executed**.

Static AST inspection parsed 397 Python sources and checked all five production
calls against the two actual `run_veth_sandbox` signatures. There are no unknown
keywords or missing required arguments. Every facade argument is forwarded under
the same name, and both shutdown defaults remain false. Source inspection also
confirms that the updated fixtures retain the real intermediate facade.

The updated journal contains no AppArmor AVC denial records. Its only reported
failed unit is the Vivaldi transient service affected by the traceback above.
Tailscale's stopped and warming-up warnings clear at lines 811 and 1127.
The network-sharing identity check succeeds at line 1548; the NFS source mount
succeeds at line 1553 and the home bind succeeds at line 1563. These are records
from the user's installed system, not checks executed by this assistant.
The global Xwayland messages continue without that server, and its existing
private Zoom/Discord boundary was preserved. No AppArmor or network-policy
grant was changed for this Python interface error.

The sidecar audit again failed at startup with an encrypted-content hydration
error; there is no independent agent finding. Root source inspection performed
the interface audit instead. No tests, validators, host managers/helpers,
package operations, policy loads or live browser checks ran. Current source and
new payload generation cannot establish an installed Vivaldi launch until those
bytes are deployed and exercised in the authorized target environment.

The permitted serialization command completed successfully:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
```

Observed output: `built 1754 payload files`. A before/after metadata inventory of
2,278 checkout files confirmed that only `payload.tar.gz`, `payload.manifest`
and `preseed.cfg` changed during the build. Streaming inspection matched all
1,754 regular archive members / 33,934,878 source bytes against the current
checkout and manifest, with mode 0644 and uid/gid/mtime zero. The archived facade
was parsed as data and explicitly confirmed to accept and forward
`graceful_shutdown`. The canonical `nfsmnt` and six managed proxy templates are
present. Archive, manifest and bootstrap checksum pins agree. Nothing was
extracted or executed from the archive. `git diff --check` completed cleanly.

These current hashes supersede the earlier generation table below:

| Product | Follow-up SHA-256 |
| --- | --- |
| payload.tar.gz | e27586fefa631296d5d74a138d6fce65fa727f8d4285185dd380e66adf1db54b |
| payload.manifest | 7d9717b855e1aae05227bd7fdaf16595708ac09c7d60f32cc3dfd8d5040c5264 |
| preseed.cfg | e8795e92c8e7c84e613840616bcbe4460bae8220ce7f10b57f46f12a159c64c1 |

## Evidence and causes

The supplied `todo/` snapshot contains three files. All 1,544 lines were read as
data: `vivaldi` (11), `error` (20), and `journalctl` (1,513). Commands in those
files were not executed.

Vivaldi fails before the proxy starts: `todo/vivaldi:8–11`, `todo/error:9–12`,
and `todo/journalctl:1492–1495` report permission denied while inspecting
`/etc/3proxy/session.json`. This establishes an access failure, rather than a
missing executable or configuration file. No installed directory metadata or
matching kernel audit record is supplied for that failure.

The upstream [Debian package maintainer script](https://github.com/3proxy/3proxy/blob/master/debian/postinst)
recursively removes other-user access from `/etc/3proxy` and changes ownership
to `proxy:proxy`. This is a concrete package behavior that can prevent the
desktop user from traversing the old managed configuration directory. These
public, root-owned application policies now live in `/etc/labwc/3proxy`,
independently of the package's private directory. The target installer also
sets explicit parent-directory modes to prevent an installer umask from making
them inaccessible. The exact installed metadata remains unverified.

Source review also found a subsequent startup blocker: the proxy supervisor
required `st_uid == 0` after Bubblewrap entered its user namespace. Linux
[user-namespace documentation](https://www.man7.org/linux/man-pages/man7/user_namespaces.7.html)
explains that unmapped ownership returned by `stat` uses the overflow UID.
Every launcher now validates host-root ownership before binding the fixed
policy files. Inside the namespace, the supervisor requires the opened file
to reside on a read-only mount and retains type, single-link, permission,
size and unresolved-token checks. The same reader handles the qBittorrent
privacy configuration. This defect was identified in source; no additional
installed runtime failure is claimed from the supplied logs.

`todo/error:14–19` invokes `nftmnt`, `sudo nftmnt`, and `which nftmnt`. The
canonical command is **`nfsmnt`**. The temporary misspelled alias was removed at
the user's explicit correction; no alias is installed. Source staging installs
`/usr/local/bin/nfsmnt` with mode 0755 on every desktop. It delegates to the
existing confined `labwc-network-sharing --connect` path. No actual `nfsmnt`
attempt or NFS mount failure is present in these three supplied files. The
configured source mount, home bind, bounded server probe and existing Polkit
authorization remain the implementation.

The separately supplied Vivaldi AVC reports inherited read/write descriptors
for the invoking user's `/dev/pts/0`. The `vivaldi-stable` wrapper and
`vivaldi-bin` binary attachments now explicitly allow `owner /dev/pts/[0-9]* rw`.

The other relevant journal records were correlated before changing anything:

- Tailscale startup warnings at lines 675 and 882 subsequently clear at 883
  and 1158. Its netfilter-off warning corresponds to the existing firewall
  ownership policy.
- XFS autofsck messages describe its configured logging behavior.
- NetworkManager reports an unavailable optional oFono backend.
- Netavark exits after inactivity; no failing container is identified.
- BlueZ reports a missing controller identity key, with no corresponding failed
  Bluetooth service or pairing failure in this snapshot.
- Labwc continues after finding no global Xwayland executable. The existing
  private Xwayland policy for Zoom and Discord is preserved.
- The calendar synchronization completes successfully at lines 1505–1511.

## Source changes and delivery contracts

- Six existing templates moved byte-for-byte to
  `hooks/target/etc/labwc/3proxy/`: five application configurations and the
  listener map. Their canonical locations mirror their installed paths.
- Staging normalizes only `/etc/labwc` and `/etc/labwc/3proxy` to root:root
  0755. Policies remain root:root 0644. No recursive vendor-directory permission
  or ownership change is added.
- Browser persistent/PurePrivacy and both qBittorrent paths read the new
  location. Namespace construction creates the private destination directories
  explicitly; policy files are individually bound read-only.
- Native qBittorrent uses its existing bounded, opened-file root-ownership
  validator for both proxy assets before adding their read-only binds. Browser
  and privacy launchers already validate root ownership before those binds.
- The launcher and child AppArmor paths match those files. Owner-qualified
  construction-directory permissions cover only synthetic directories, while
  the actual host policy directories are root-owned.
- Desktop installation and firstboot now check the configuration files'
  presence, type, root ownership, permissions and single-link status, as well
  as the required 3proxy, shared supervisor and `nfsmnt` executables. The
  qBittorrent proxy file is conditional on the managed qBittorrent policy.
- 3proxy continues to be selected through `apt-setup/local11` and `pkgsel`.
  The upstream binary package is installed by APT. No standalone installer or
  source compilation is introduced; the vendor host service remains masked.

## Static evidence

Only checkout source and supplied logs were inspected. No repository module,
test or validator was imported or executed.

- 397 Python sources parsed as data with the standard-library `ast` parser.
- All ten profiles contain the eight fields read by the production proxy map.
  Static substitutions cover 11 proxy/browser-policy assets per profile:
  110 substitutions and 60 JSON documents, with no remaining installer tokens.
- Both explicit native qBittorrent render calls cover all five actual template
  keys, including the listener setting.
- `nfsmnt` staging, both installation inventories, AppArmor attachment and
  terminal delegation agree. No `nftmnt` executable is present.
- Vivaldi's two actual attachment includes contain the owner-qualified PTY
  grant. The local11 repository/key and core package selection remain present.
- `git diff --check` reports no whitespace errors.

The first ad hoc asset inventory expected 12 proxy/browser assets and stopped
at that count assertion after parsing the 397 Python files. The corrected
inventory explicitly enumerated the 11 assets above, then completed the
substitution and delivery-contract inspection. No repository code ran in either
inspection.

Regression source was added for private managed-parent modes with untouched
vendor assets (ownership command replaced by an explicit fixture), canonical
`nfsmnt` installation inventories, Vivaldi PTY grants on both attachments, and
an unmapped owner on a read-only policy mount (metadata and mount flags mocked).
The native qBittorrent command fixture explicitly mocks and verifies both
pre-bind policy reads, so it cannot fall through to installed configuration.
Existing fixture paths were updated. These tests were **not run**.

## Execution boundary and acceptance limits

`AGENTS.override.md` prohibits host tests and validators. No prepared disposable
environment was available. No test/discovery runner, shell syntax validator,
native AppArmor/nft parser, package operation, installed management helper,
service operation or live GUI/network/mount check was executed. Sidecar startup
failed with encrypted-content hydration errors and supplied no independent
review result.

## Final generated products

The permitted serialization command completed successfully:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
```

Observed output: `built 1754 payload files`.

An owned before/after metadata inventory of 2,280 checkout files established
that this command changed exactly `d-i/forky/payload.tar.gz`,
`d-i/forky/payload.manifest`, and `d-i/forky/preseed.cfg`. No source input was
rewritten by the build.

Streaming archive inspection compared all 1,754 regular members / 33,934,796
source bytes against the current checkout and manifest. All paths and SHA-256
digests agree; archive members have mode 0644 and uid/gid/mtime zero. The six
new-location proxy templates and canonical `nfsmnt` are present. Neither an old
managed `/etc/3proxy` template nor a `nftmnt` executable is included. Generated
archive/manifest/bootstrap checksum pins agree. Nothing was extracted or
executed from the archive.

An earlier successful serialization was superseded after source review found
the namespace ownership defect. The final rebuild and archive comparison above
include that additional correction.

| Product | Final SHA-256 |
| --- | --- |
| payload.tar.gz | 13d49cefe82146eb8562fa7361447cf160b35914687d0b2dd908a2305316d246 |
| payload.manifest | 3ef3ae648097810a970cb2656dbe3d4c936791309aa7114ab6b56747f36ca2a2 |
| preseed.cfg | 319a328ada10bc4f53532f7110776f24087e51e9c65702b7c85b6b30afd0784f |

The installed machine has not been repaired or reconfigured. Fresh-install
acceptance still needs package/signature availability, loaded AppArmor syntax
and enforcement, browser proxy-policy acceptance and foreground process
lifecycle, and a real configured NFS server/mount/Polkit flow in a disposable
environment. Source inspection and matching archive bytes do not establish
those live behaviors.
