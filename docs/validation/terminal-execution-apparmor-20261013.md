# Foot/Kitty general command execution — 2026-10-13

## Supplied evidence and accepted behavior

The user supplied four root-owned Go executable denials from node `LPL-603`,
audit events `1791926596.538:4032`, `1791926596.538:4033`,
`1791926618.595:4058`, and `1791926618.595:4059`. Each reports operation `exec`,
profile `desktop-launcher`, executable `/usr/lib/go-1.27/bin/go`, caller
`timeout`, filesystem UID 1000, and denied mask `x`.

The final requested behavior is unrestricted AppArmor access for direct commands
from Foot and Kitty, including arbitrary executable locations, future toolchain
versions, and ordinary-user compilation without sudo. The
old shared launcher profile allowed selected executable roots, missing this
versioned Go path and other arbitrary locations.

## Source repair and boundaries

`hooks/target/etc/apparmor.d/desktop-utilities` now attaches Foot, Footclient,
and Kitty to `desktop-terminal`. The existing `desktop-launcher` attachment
continues to own Fuzzel, the terminal chooser, Thunar, Xarchiver, and nnn; its
body is byte-identical to HEAD. All other existing profiles in this file are
unchanged.

The terminal profile grants `allow all,` plus `/** rix,`. The all rule grants
all AppArmor resource classes; the explicit execution rule keeps direct
descendants in the terminal domain instead of applying executable attachments.
AppArmor permission does not give a
process a new kernel capability or bypass UID, filesystem permissions, noexec
mounts, or authentication. This is intentionally a trusted interactive command
domain; it is not an application-specific resource allowlist.

The user's final instruction superseded an intermediate `Pix` implementation.
The final terminal policy has no `px`, `cx`, `ux`, named exec transitions, deny
rules, or includes that could introduce restrictions. Shells, compiler/linker
helpers, build tools, sudo, and pkexec inherit the terminal domain. Sudo/Polkit
continue their normal authentication; no wrapper elevates compilation commands.
Desktop-menu launches and separately started services retain their existing
policy. Commands that deliberately use another manager or explicitly change
their own confinement are outside ordinary exec inheritance. See the
[official AppArmor all-rule and inherited-execution documentation](https://www.apparmor.net/man/4.0/apparmor.d/)
and the [AppArmor 4.0 all-rule implementation](https://gitlab.com/apparmor/apparmor/-/raw/apparmor-4.0/parser/all_rule.cc),
which emits inherited execution plus the supported resource-class permissions.

The profile uses explicit permissions in ordinary enforce mode. The current
managed mode controller rejects/removes `default_allow` and `unconfined` flags;
it can therefore continue selecting enforce/complain for this source without a
terminal exception or controller modification.

`abstractions/base.d/process-monitor` adds reciprocal signal-receive and
ptrace-readby permissions for `desktop-terminal`, plus the child-exit signal
back to the terminal. This preserves terminal
close, Ctrl-C, timeout, and process-status operations against separately
profiled children. It does not grant ptrace-tracedby; existing explicit denies
and kernel credential checks remain effective.

The Fuzzel wrapper's cancellation cleanup can also send its existing TERM
signal to the new terminal domain, matching its previous launcher-domain grant.

## Ordinary-user compilation review

The later supplied `zsh: permission denied: go` output is consistent with the
reported AppArmor execution denial. It does not establish a filesystem-mode or
ownership defect independently. The new terminal execution rule covers Go,
its versioned compiler/linker helpers, temporary outputs, caches and ordinary
user-writable workspaces without requiring sudo.

Source review confirmed `golang-go` and `build-essential` are selected desktop
packages. `scripts/late/devops/main-orchestration.sh` creates the primary
account's Go workspace, module-cache, Cargo, sccache, and other development
directories with `install -d -m 2770 -o "$account_user" -g devops`; the desktop
pool tmpfiles template also assigns primary-account ownership. No evidence in
the supplied output supports changing package executable ownership/modes or
recursively changing workspace ownership. No such repair was added.

The opt-in DevOps shell exports GOPATH and GOMODCACHE below these user-owned
roots. Bazelisk and Rustup bootstrap executables are installed mode 0755;
Node installation preserves executable bits and gives package directories mode
0755. Their root-owned release storage does not require root to run a compiler.
Account-specific Rust/Cargo/Bazel/Node storage is created with the user owner.
`gitbuild` explicitly rejects root execution and uses rootless sbuild/unshare or
Bubblewrap for builds; its separate authenticated repository-import operation
does not elevate compilation. No live filesystem permissions were inspected.

## Complete installed wiring

- `labwc-terminal` preserves argv and invokes the native Foot/Kitty executable
  through `labwc-wayland-app`; no shell or command implementation was changed.
- `labwc_managed_app/generic.py` retains the existing transient service, host
  UID/mount view, `NoNewPrivileges=no`, process visibility, and bounded terminal
  stop lifecycle. There is no terminal property pin to `desktop-launcher`.
- Existing `stage_target_desktop_apparmor_profiles()` installs
  `desktop-utilities` at `/etc/apparmor.d/desktop-utilities`, mode 0644.
- Existing security staging installs the base.d fragment at mode 0644.
- `modes.conf.tmpl` already declares `desktop-utilities`; its mode reconciliation
  processes every declaration in the file, including the new terminal label.
- The private Xwayland source policy, managed application network policy, and
  terminal launch/lifecycle implementation remain unchanged.

## Verification and limits

The added native rule-reader regression in
`tests/test_apparmor_incidents_20261004.py` covers Go and its compiler child,
Clang, system administration commands, Node, future /opt tools, shared/mounted
workspaces, HOME, temporary build outputs, and an arbitrary future root. It also
covers unique terminal ownership, inherited execution for profiled applications
and authentication tools, absence of restricting includes/transitions,
reciprocal permissions, and staging references. This guarded
regression was **not run**.

Static inspection parsed the changed Python source as AST data and compared the
existing launcher body and other profiles against HEAD. An initial attachment
assertion used an incorrectly escaped regex and failed; literal header-field
parsing replaced that inspection check and completed successfully. No
repository module was imported or executed by those inspections.

No native AppArmor parser, test runner, live terminal command, compiler, host
manager, or installed helper was executed. Repository guidance requires a
prepared disposable environment for tests/native validation; none is available.
The delegated read-only sidecar failed encrypted-context initialization and
produced no findings. Root performed integration review directly.

The Makefile, builder, and publication helper were read before the explicitly
authorized serialization-only build:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build PYTHON='/usr/bin/python3 -I' SHELL=/bin/sh
```

Final artifact and preservation evidence follows after generation. A preliminary
build and intermediate policy checks are superseded by the final `ix` contract.
The preliminary build preserved metadata across 2,920 other checkout paths and
changed exactly the three generated products. A later metadata tool call failed
before execution because its saved command was unavailable; it provided no
verification evidence. Final artifact checks use source/archive bytes directly.

The final build completed successfully with **1,755 files**. Independent archive
inspection verified **33,987,772 source bytes**, every member's exact source
content and manifest SHA-256, unique safe paths, test/private-input exclusions,
normalized metadata (0644, zero UID/GID/mtime, empty owner/group names), and all
three bootstrap pins. There are zero active `CPUAccounting=` assignments.

Metadata of all **2,920 non-product checkout paths** was unchanged across the
final build (directory metadata comparison includes mode/inode; file comparison
also includes size and nanosecond modification/change times). Only the three
allowed generated artifact paths were rewritten. Source file modes remain
their pre-existing 0600, while staged policies and serialized members are 0644.

Read-only Git comparisons confirmed the terminal launcher, transient lifecycle
implementation, private Xwayland policy/helper, toolchain abstractions,
installer development directory creation, pool tmpfiles and DevOps shell are
unchanged from HEAD. The existing launcher body and other existing profiles in
`desktop-utilities` are byte-identical to HEAD. Final `git diff --check` passed.

| Artifact | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `e216ef64cbe6783ebb24aada382d42b1d4cbacd832f3f374cd5099c980049690` |
| `d-i/forky/payload.manifest` | `5d7405e208a800b856e074e0df19971c98f56643178b5c42e9b78a39bc87cebe` |
| `d-i/forky/preseed.cfg` | `237a576186eda5b89ab9e2ca21e0dafba7048fa2fbb66e4452261873e2e68d87` |
| Unchanged `scripts/common/source.sh` | `6b3a40bb85942ed8f4b780852743140132414898b578af7c7597bb7c3872b246` |

## Changed paths for this follow-up

- `d-i/forky/hooks/target/etc/apparmor.d/desktop-utilities`
- `d-i/forky/hooks/target/etc/apparmor.d/desktop-wrappers.tmpl`
- `d-i/forky/hooks/target/etc/apparmor.d/abstractions/base.d/process-monitor`
- `d-i/forky/tests/test_apparmor_incidents_20261004.py`
- `d-i/forky/payload.tar.gz`
- `d-i/forky/payload.manifest`
- `d-i/forky/preseed.cfg`
- `docs/validation/terminal-execution-apparmor-20261013.md`

No installed policy was loaded/replaced, no host service was contacted, and no
deployment or installed-host repair was performed. Native policy acceptance,
live Foot/Kitty command execution, and live terminal teardown remain unverified.
Earlier task changes, including the Tailscale execution grant, are preserved.
