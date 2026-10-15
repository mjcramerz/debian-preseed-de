# Browser startup and policy correction, 2026-10-15

> Superseded by [Tor runtime denial and Wayland follow-up](tor-runtime-denials-20261015.md).
> Later installed-system logs exposed additional runtime permissions, missing
> accessibility bus wiring and Vivaldi cache initialization. The static review
> below did not establish live correctness. Its artifact hashes are historical;
> use the follow-up report for the current generated payload.

## Supplied evidence and correction

Read the updated `todo/journalctl` (1,762 lines) and `todo/apparmor.log`
(434 lines) as data. The current supplied AppArmor file is named
`apparmor.log`; `todo/apparmor` is absent. This review did not inspect or
change installed host configuration, services, policy, networking or profiles.

`todo/apparmor.log:434` records the bundled Tor exec denial with
`info="no new privs"`, source `labwc-app//tor-bwrap`, and target
`labwc-app//tor-bwrap//transport`. The child profile is loaded. The journal
shows the dedicated veth ready before the denied exec, followed by
`bundled Tor exited before local IPC readiness` and service failure.

The preceding change corrected target lookup but missed the second restriction:
Bubblewrap sets `no_new_privs`, so replacing its confinement with another
profile is rejected. That earlier repair was incomplete.

## Tor AppArmor change

The canonical `hooks/target/etc/apparmor.d/desktop-wrappers.tmpl` now directs
both executable transitions to an explicit stack retaining
`labwc-app//tor-bwrap` and adding the respective existing child:

| Executable | Mode | Added child |
| --- | --- | --- |
| `/opt/tor-browser/Browser/TorBrowser/Tor/tor` | `rpx` | `labwc-app//tor-bwrap//transport` |
| `/opt/tor-browser/Browser/firefox` | `rPx` | `labwc-app//tor-bwrap//browser` |

This follows the AppArmor maintainer's
[Bubblewrap stacking example](https://gitlab.com/apparmor/apparmor/-/wikis/flatpak/diff?version_id=3d4f6992f5917036d48e797ba8ea043398f3872c)
and [explicit stack syntax](https://gitlab.com/apparmor/apparmor/-/wikis/AppArmorStacking/diff?version_id=a6670913fcbf1b5030ac458e58595bb2fae529fa).
The original profile remains in the stack and permissions are intersected.
The lowercase transport transition retains only the runtime's existing fixed
bundled-library environment; the browser retains uppercase environment scrubbing.

Because both profiles now apply, the original profile also permits inherited
execution of Firefox's existing `firefox.real`, `abicheck`, `glxtest` and
`vaapitest` helpers. Explicit stacked peers cover signals and reciprocal
process-read permissions; browser self-tracing also retains reciprocal
`tracedby`. The transport retains only process reads. Linux's
[ptrace mediation](https://github.com/torvalds/linux/blob/v6.17/security/apparmor/task.c)
checks both the observer and observed profiles.

The transport's datagram denies and browser's IPv4/IPv6 denies remain present.
The preceding owner-only descriptor-directory read is retained. There is no
unconfined or inherited fallback on either main exec transition. The runtime,
Tor circuit settings, namespaces, systemd lifecycle and Xwayland code are unchanged.

Existing installation wiring stages the managed profile through
`scripts/late/security.sh`. `labwc_managed_app/sandbox.py` enters
`labwc-app//tor-bwrap` before the outer Bubblewrap process. The authenticated
Tor installer already stages the runtime and bundle; no source build was added.

## Tor desktop actions

`hooks/target/usr/local/share/applications/tor-browser.desktop` is now
accelerator-neutral: the default launch and ANOM action remain, with no static
Intel or NVIDIA action. Tor is added to the existing
`labwc-sync-application-launchers.tmpl` application map. Its account-local
launcher receives only the Intel/NVIDIA actions permitted by the installed
availability booleans, while preserving ANOM and the single-URI `%u` contract.

The existing detector enables NVIDIA only when an NVIDIA addon class is
selected and supported NVIDIA hardware is detected. The existing installer
account setup and session service already run this synchronizer. It reads the
system desktop entry, so an older account-local copy is replaced through the
normal synchronization path. The journal's `processed=0` counts changed files,
not entries inspected; no separate synchronizer failure is demonstrated.

## Vivaldi extension policy

Added Proton VPN ID `jplgfhpmjnbigmhklmmbgecoobifkmpa` to
`hooks/target/etc/vivaldi/policies/managed/extensions.json`, addressing the
missing ID reported at `todo/journalctl:1544-1545,1623`.

`browser-config/policies.json` has a Vivaldi-specific extension section, and
`tools/build_browser_config.py` validates and merges it only for Vivaldi.
The existing shared uBlock Origin Lite, NoScript and Privacy Badger policies
are preserved. All four use the existing user-adjustable `normal_installed`,
default-pinned policy and HTTPS Chrome update service. Other browser lists
remain unchanged. Existing target staging, verification and sandbox policy
binds already expose Vivaldi's managed directory and persistent profile.

The NoScript favicon warnings at lines 1546/1550 remain: the browser refuses
a resource absent from the extension's web-accessible manifest. This is not an
AppArmor denial, and the signed extension was not modified. The user reported
that the three existing privacy extensions appear to work; this review did
not independently exercise them. Vivaldi's missing signed search-cache reads
at lines 1532-1533/1621-1622 remain vendor-owned; no unsigned cache was seeded.
Proton download, browser recognition and disappearance of the missing-ID
message still require a browser session with access to its update service.

Other updated journal records include successful Tailscale warmup/rebind,
the existing deliberately absent global Xwayland executable, Spotify's vendor
deprecation warning and menu cancellation exit statuses. No other AppArmor
access denial occurs in the current supplied AppArmor log.

## Verification

Repository instructions prohibit tests and validators on the development host.
No approved disposable environment was supplied. No tests, native policy parser,
browser session, installed helper or host-management command were executed.
Independent review agents failed to initialize with encrypted-context errors;
no child review result is claimed.

Completed source-as-data inspection without importing repository modules:

- Parsed the six changed Python inputs with the standard-library AST.
- Parsed duplicate-free policy JSON and compared all 20 generated browser
  policy files byte-for-byte with the canonical data and Vivaldi-only merge.
- Read launcher literals and the base desktop entry; confirmed Tor uses the
  existing filtered GPU action keys and preserves ANOM.
- Inspected explicit AppArmor stack components, helper execution, reciprocal
  lifecycle rules and transport/browser network separation. This is text
  inspection, not native parser or kernel acceptance.
- Preserved the ten owned source/test inputs' original modes.

Existing guarded regression files now cover the stack contract, all four GPU
availability combinations, ANOM preservation, Vivaldi-only installation and
invalid Vivaldi policy rejection. These tests were added/updated but not run.

Before generation, the previous archive differed from source in exactly four
members: the AppArmor policy, Vivaldi extension policy, Tor desktop entry and
launcher synchronizer. Generation and final archive results are recorded below.

### Generated payload

After reviewing the Makefile recipe and the complete `tools/build.py` /
`tools/publication.py` execution path, ran the permitted pure serializer:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/timeout 60 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
```

It exited successfully and built 1,781 payload files. No validator, browser
generator, shell snippet or test ran within the build. Standard-library archive
inspection then compared every entry's bytes and SHA-256 with source and
manifest: 1,781 files and 34,223,119 source bytes agree. Member inventories,
safe relative paths, regular-file types, normalized metadata and preseed
archive/manifest/bootstrap checksum pins also agree.

Compared 2,970 nonproduct paths immediately before and after generation.
Only the product parent directory's metadata changed from atomic publication;
no other path changed. `git diff --check` completed without findings.

| Generated file | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `ab07fb98c8267da27eae4f22c53c6c94dfefe17681245ef365ccc4ccd464e3ca` |
| `d-i/forky/payload.manifest` | `97f901090c43f00ed5ef9e8240e9d9752678d8d43b967c6d5f2bd3ce0dc3738d` |
| `d-i/forky/preseed.cfg` | `58c6bd2a8f03c2d698cad7595719f1f1d854bd3b692213dccf0ed34e8c883e92` |

The generated products contain the current source changes. Native AppArmor
acceptance, Tor startup/circuit bootstrap, child shutdown, extension download
and browser functionality remain unverified in a disposable installed system.
This work updates the installer repository; it does not deploy changes to an
already installed machine.

## Second incorporation and security review

Repeated the review of the pending source/test changes and their callers after
the request for another pass. No additional implementation defect was found
within the Tor, Vivaldi policy and desktop-action changes. This pass changes
only this report; the implementation and generated products above remain current.

### Contracts reviewed

- **Installer trust and bounds:** Tor installation checks the release URL,
  archive/key SHA-256 pins, GPG signature and signer. The extractor rejects
  unsafe/duplicate paths, links, special files and special mode bits, and
  bounds member count and expanded size before publishing a new root-owned
  bundle. This was source inspection; no vendor archive was installed or run.
- **Runtime isolation:** the worker bind sources are inside the synthetic
  outer root. The RAM bundle is read-only in both workers; the browser hides
  the alternate RAM bundle path with its private runtime mount. Browser IP
  isolation and transport-only networking remain separate. Environment
  handling removes inherited loader variables before setting the fixed Tor
  library directory. The explicit AppArmor exec stacks retain the original
  confinement and add the appropriate child.
- **Process lifetime:** the runtime waits for private IPC objects with a
  bounded startup deadline, waits on pidfds during browsing, and stops/reaps
  both children through `finally` cleanup. The transient service has
  `KillMode=control-group`, bounded stop handling and final SIGKILL. These
  existing paths were reviewed without invoking a manager or launching a child.
- **Desktop ownership:** the neutral Tor entry is staged by the software
  installer. The existing synchronizer reads that system source, filters GPU
  actions using installed availability, retains ANOM and publishes the
  account-local entry. The initial account setup and session service/path
  already invoke it; existing AppArmor paths cover the new entry.
- **Vivaldi ownership:** strict canonical extension IDs and installation
  settings feed the Vivaldi-only merge. Existing staging uses mode 0644 and
  the sandbox exposes the managed policy directory. Shared extension policy
  and persistent user settings retain their existing ownership.
- **Performance:** the changes add no polling loop, daemon, network probe or
  bundle copy. The existing browsing wait is event-driven; startup polling
  has a deadline. No startup latency, memory or throughput benchmark was run,
  so no measured performance gain is claimed.

### Fresh static results

Used a clean environment and bounded standard-library Python invocation,
without importing or executing repository code:

- Parsed ten relevant Python sources, including the installer, runtime,
  launcher, sandbox/session callers and changed regression files, with AST.
- Compared all **23** browser-generated artifacts, including the three
  profile preference seeds, byte-for-byte with the canonical output data;
  their source modes are 0644 and JSON has no duplicate keys.
- Rechecked Tor's base desktop entry, single-URI contract, application-map
  literals, explicit stack components, helper permissions, reciprocal
  lifecycle rules and network denies.
- Rechecked all **1,781** payload members / **34,223,119** source bytes,
  manifest SHA-256 records, regular-file metadata, safe member paths and
  preseed/bootstrap pins. All agree. The three product hashes are unchanged
  from the table above, so no rebuild was necessary.
- `git diff --check` completed without findings.

Both fresh independent-review agent attempts failed during initialization with
the runtime's encrypted-context error. The checks above were performed by the
coordinating agent; no independent agent result is claimed. Tests, native
AppArmor acceptance and installed browser behavior remain unexecuted under
the same isolation boundary described above. The previously identified
NoScript favicon and Vivaldi search-cache messages remain outside the repaired
missing-extension and exec-denial contracts.
