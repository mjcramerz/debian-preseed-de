# Validation: 2026-09-06 security/browser refactor

This records actual checks of the delivered revision. The fresh complete pipeline
returned zero; `validation/summary.json` records its five stages and runtime-product
hashes. This is not a certification of a booted Debian installation.

## Completed checks

| Check | Actual result |
| --- | --- |
| Browser generation / `--check` | PASS |
| Deterministic payload and preseed pin currentness | PASS |
| Isolated debconf preseed check | 58 files; PASS |
| Full retained suite plus 39 new security regressions | 271 tests; PASS; 0 skipped |
| Unit-suite measured runtime | 88.700 seconds |
| Syntax/inventory audit | 1,153 files; no hard audit failures |
| Original hardware profile preservation | 13 profiles; byte-identical to uploaded ZIP |
| Supplementary AppArmor offline compilation | 2 actual Vivaldi parent profiles; PASS; no kernel load |

Do not add inventory checks to the executed test count. The original supplied
role-specific suite had 232 tests; this revision adds 39. Run logs are included,
not reconstructed from expected outcomes. The pipeline's outer test-stage elapsed
time is slightly larger than the unittest runtime because it includes process
startup and reporting. `validation/run-status.txt` contains the completed run's
exit status; it is not evidence for any later local edit.

## What was exercised

The retained tests execute generated bootstrap commands with local media and
loopback HTTP/HTTPS, redirect chains, GNU/BusyBox wget, full source prefixes,
normal TLS trust and the explicit repository-only bypass. They test corrupted
pins, missing members, traversal, duplicate/symlink archive entries, stale local
sources, role/class/profile errors, credential handling, storage-policy fixtures,
path relocations and payload/cache integrity. They do not contact real GitHub,
TinyURL or NVIDIA endpoints.

New tests execute an external-key fetch over a trusted loopback HTTPS server while
the validated-payload ready marker exists. They prove that absent snapshot members
still fail, external data cannot inherit the TLS bypass, failed downloads preserve
the destination, unsafe modes/URLs are rejected, and the source line constrains
the full signing fingerprint without APT authentication bypass options.

Cryptographic fixtures generate a disposable RSA key with a SHA-1 certificate
self-signature and SHA-256-signed Release data. Real `sqv` rejects the certificate
under strict policy, accepts that SHA-256 fixture with the bounded exception,
rejects a SHA-1 data signature, rejects modified signed data, and rejects the
exception after its cutoff. A real isolated `apt-get update` uses a local flat
repository and private state/cache: strict policy rejects, the scoped policy
accepts, and the wrong Signed-By fingerprint rejects. No packages are installed;
no validation-host APT source, trust policy or package database is changed.

Production-wrapper fixtures test a `run_in_target` that exits, not just returns;
retry scope, cleanup, general-update source restoration, unrelated failures and
strict-first behavior are covered. DKMS tests verify missing-real-binary failure
instead of recursion, diversion with rename, and argument forwarding. Credential
reader tests prove wrong permission modes do not execute shell content.

Browser tests validate reproducible generation, all bookmark/exclusion accounting,
NoScript contextual grants and UUID removal, the actual selected uBOL IDs, no
unfiltered bookmark bypass, Privacy Badger explicit actions/no fabricated learning,
policy editability, supported recommendation placement, private debug directories,
loopback/sandbox flags, root refusal, and staging of owned private exports.
Staging tests cover repeated runs, preservation of user edits, Downloads symlinks,
FIFOs, inappropriate homes and ownership. No extension GUI or website task is run.

Two real Vivaldi AppArmor parent profiles were compiled with `apparmor_parser -Q
-K` and the repository include directory. The parser exits zero; it warns that a
kernel interface is unavailable. `-Q` prevents loading. The Chromium and Edge local
include files have regression checks but were not compiled within real installed
vendor parent profiles. No AppArmor enforcement or browser launch is claimed.

## Audit outcomes

| Outcome | Count | Meaning |
| --- | ---: | --- |
| `pass` | 402 | Available syntax/parser check passed; not semantic proof. |
| `structure-pass` | 116 | Systemd lexical structure only, not activation or full systemd-analyze verify. |
| `inventory-only` | 479 | Data/configuration asset recorded, not executed. |
| `blocked-dependency` | 154 | Perl compilation check could not finish without dependencies. |
| `template-needs-render` | 2 | Runtime-substituted template not validated in final form. |

Most blocked Perl checks require `Moo.pm`, not installed in this container; the
retained target package list includes `libmoo-perl`. One also needs the generated
`LabwcNetworkScanAction/Root.pm`. The two unrendered templates are
`hooks/target/etc/greetd/config.toml.tmpl` and
`hooks/target/etc/skel/.config/cargo/config.toml.tmpl` below `d-i/forky/`.
These 154 blocked checks are not fixed, passed or silently omitted. Perl `-c`
can execute BEGIN blocks, so only validate trusted code in a disposable system.

## Reproduce

    python3 -B tools/build.py
    python3 -B tools/validate.py

The publishing tools need Python 3.11+. Full fixture coverage additionally needs
POSIX sh, Bash, Perl, GNU wget, BusyBox, OpenSSL, Node.js, GnuPG, `sqv`, APT and
`debconf-set-selections`; a missing tool can cause a test to skip or fail, which
must be reviewed. The completed run here had zero skips. Supplementary profile
compilation needs AppArmor parser. Installer transport itself needs neither Python
nor curl; installed-target helpers use the target's existing Python package.

## Acceptance work NOT performed

| Area | Required real-system acceptance |
| --- | --- |
| d-i | Boot the actual image, native initial source trust, network setup, real redirects and complete phase ordering. |
| Storage | Disposable disks for each selected Btrfs/F2FS/VM profile; verify intended disk identity, capacity, boot/encryption and recovery. |
| Package sources | Live Debian and NVIDIA metadata/signatures, package availability, actual CUDA dependencies and version selection. |
| NVIDIA | Actual DKMS build against chosen kernel/headers, module load, Secure Boot enrollment, GPU workloads and suspend/resume. |
| Desktop | Reboot/login, Labwc/wlroots, input/output devices, D-Bus/session units, networking, integration credentials and first boot. |
| Browser | Installed-version policy recognition/precedence, extension installation/import/re-export, localhost DevTools, AppArmor denials. |
| Sites | Authenticated login/payment/CAPTCHA/video and other real bookmark workflows with blocked-request inspection. |

A coverage entry is not a successfully tested website. None of the 543 eligible
web bookmarks has live workflow acceptance in this run. Other managed browser
policy sources can override local JSON. Initial preseed SHA-256 pins do not prove
the authenticity of a maliciously replaced preseed. See `SECURITY.md`.
