# NVIDIA 580.142 / XanMod 7.2.4: revision 2

Date: 2026-09-08. Supersedes the first process-name-only repair.

## What was missed

The first repair was incomplete. The new `syslog(4)` explicitly records that the
process-name patch was applied before DKMS started. This is not evidence of an
old payload being served. The new `make(1).log` reports three errors at two other
call sites in `nvidia/linux_nvswitch.c`:

- Line 2040: undeclared `strncpy(regkey_val, regkey_val_start, regkey_val_len)`.
- Line 2395: undeclared `strncpy(dest, src, length)` and its consequential
  integer-to-pointer return conversion error.

The earlier error in `nvidia/os-interface.c` is no longer the stopping error.
The build has progressed to NVSwitch. The package postinst still fails because
its NVIDIA DKMS build fails, not because of the intentionally trusted CUDA repo.
`installer(4).log` records a successful legacy CUDA metadata refresh at
10:08:40Z, followed by successful staging of the NVIDIA DKMS wrapper.

Inspection of NVIDIA's 580.142 Linux interface sources identifies additional
uses of the same removed API in modeset and UVM. Linux 7.2 also renames the DRM
atomic transaction type and its lifetime helpers. Those DRM incompatibilities
are source-derived findings, not diagnostics reached in the supplied build log.

## Changes in this revision

The existing production file changed is:

`d-i/forky/hooks/installer/pre-pkgsel.d/92nvidia-legacy-dkms.sh`

The hook still stages the existing diverted DKMS wrapper before package
selection. The wrapper now applies the complete known string compatibility
repair and the DRM compatibility adaptation before executing `dkms.distrib`.
No NVIDIA modules are excluded and no DKMS failure is converted to success.

### String interfaces: retain semantics and proprietary ABI

| Interface | Repair |
| --- | --- |
| `os_get_current_process_name` | Retains the first repair: `strscpy_pad` with the complete destination capacity, under the original task lock. |
| NVSwitch registry substring | Uses `memcpy` for the previously length-checked substring and preserves the following explicit NUL terminator. |
| `nvswitch_os_strncpy` | Retains its name, signature, `char *` return and exact bounded-copy/padding semantics using `strnlen`, `memcpy` and `memset`. |
| `nvkms_strncpy` | The same ABI-preserving bounded-copy implementation, without renaming the symbol expected by the proprietary modeset binary. |
| UVM chunk-cache name | Uses `strscpy_pad` with the complete destination-array size. |

Simply changing `return strncpy(...)` to `return strscpy(...)` would be wrong:
the return types and semantics differ. Renaming the two OS-interface symbols to
the names proposed in an open-driver patch would also leave the proprietary
binary's expected interfaces unresolved. The existing exported names are kept.

The NVSwitch registry input is a substring, potentially followed by a semicolon.
Passing `regkey_val_len` to a terminating string-copy API would lose the last
hex digit. The patch preserves the existing length validation and terminator.

The two generic copy wrappers intentionally preserve the original behavior:
copy at most `n` bytes, pad unused destination bytes with zero, return the
original destination, and do not force termination when all `n` bytes are used.
Zero-length calls perform no read or write.

### DRM transaction compatibility

The wrapper adds one NVIDIA conftest, registers it in
`nvidia-drm-sources.mk`, and adds conditional aliases to
`nvidia-drm-conftest.h`. The probe requires the target headers to provide a
complete `struct drm_atomic_commit` and both full-transaction `atomic_check`
callback signatures. A pointer to an incomplete structure alone is deliberately
not used as evidence of API availability.

On the renamed API, the old NVIDIA transaction type and lifetime helper names
map to the Linux 7.2 names. The existing full-transaction CRTC and plane branches
remain selected, instead of incorrectly falling back to older per-object-state
callback signatures. On older headers the probe is false and the original
NVIDIA feature decisions remain in effect. The common NVIDIA conftest header is
include-guarded, so repeated inclusion does not undo these feature decisions.
No kernel-version number alone is used to select this compatibility path.

### Application and failure handling

The existing 580-only `/usr/src` and DKMS source/build roots remain the scope.
Registered source-directory symlinks, optional nested `kernel-open` layouts,
package re-unpack, and stale build copies are covered. Changed source files are
staged beside their destination and atomically renamed, preserving owner/mode.
Already-correct sources are not rewritten, including unprivileged read-only
status checks.

Known source bodies and patch markers are validated. The new helper validates
its whole batch and audits the Linux interface C/H files before publishing its
rewrites. Any remaining raw `strncpy` reference outside comments/strings causes
an explicit path-and-line error before compilation; it is not blindly globally
replaced. An unexpected future vendor body is rejected rather than guessed at.
The prior process-name/header steps may already have completed before this new
batch; the entire multi-file source tree is not one filesystem transaction.

The new helper uses only Perl and modules provided by Debian's `perl-base`.
No repository access or patch download is required at DKMS invocation time.

## Scope preserved

Relative to the original ZIP, exactly four existing files differ: the NVIDIA
hook and the three regenerated products below. All other 1,311 original files
are byte-identical. In particular, all 11 original CUDA-named files are
byte-identical. CUDA's repository URL, staged addition mechanism, APT trust /
insecure allowances, pinning and package selection are unchanged.

There is no kernel downgrade, change to NVIDIA's proprietary 580 branch, or
switch to the open modules. Compiler policy, Secure Boot/signing policy,
labwc/wlroots, service configuration, storage and unrelated installer code are
unchanged. The earlier revision's report is retained with a superseded notice;
its old test counts are not used as validation of this revision.

Rebuilt and verified together:

- `d-i/forky/payload.tar.gz`
- `d-i/forky/payload.manifest`
- `d-i/forky/preseed.cfg`

New files are regression tests, a recovery helper, this report, and validation
evidence. `validation/nvidia-580-xanmod-7.2.4-r2/scope.json` gives SHA-256 values
and the complete comparison against both original ZIP and first delivery.

## Completed validation

Current evidence is in `validation/nvidia-580-xanmod-7.2.4-r2/`.

| Check | Result and actual scope |
| --- | --- |
| NVIDIA tests | 43 passed: 14 existing process-name/wrapper tests, 19 new interface tests, 10 recovery-orchestration tests. |
| Legacy CUDA tests | 40 passed, including local real-APT trust behavior tests. |
| Existing wrapper security regressions | 3 passed: dispatch/failure propagation and existing string/GPIO header handling. |
| C copy contracts | 18,818 boundary cases per compiler under GCC and Clang with UndefinedBehaviorSanitizer; return pointers, padding, guard-page read limits, registry values and UVM cache names checked. |
| Negative compiler controls | Original NVSwitch, modeset and UVM fixtures each independently fail with the removed API poisoned; their patched versions compile. |
| DRM probe/branches | Compiled against minimal modeled old, renamed, incomplete and wrong-callback interfaces; only the correct renamed API selects the new branch. These are not full Linux 7.2 headers. |
| Actual kernel API probe | All five repaired string interfaces compiled and linked through MODPOST against Debian `6.12.96+deb13-amd64` headers using `MODULE_LICENSE("NVIDIA")`. No `strncpy` import remains in the resulting probe. No module was loaded. |
| Shell checks | 265 files, 541 parser checks passed. |
| Preseed checks | 59 files passed; all four generated command values survived real private debconf read-back unchanged. |
| Generated snapshot | Repository build and `tools/build.py --check` passed; 1,234 payload files. |

The fixtures are source-derived, reduced regression fixtures, not the full
proprietary driver. Recovery tests use a fake chroot and verify exact command
ordering and exit propagation; they do not install packages on a GPU host.
Two wider test batches exceeded the execution window. Their `.interrupted.log`
files are retained and not counted as completed suites. The completed focused
logs listed above are the basis of the pass counts, not the first delivery's
530-test claim.

**Not performed here:** a full NVIDIA 580.142 build against the exact
`7.2.4-x64v3-xanmod1` headers, loading the driver, booting the target, or executing
CUDA/labwc workloads. The exact proprietary build inputs and XanMod headers are
not available locally and attempted downloads were unsuccessful. There is no
hardware access. The source fixes and tests are not a claim of end-to-end
installation certification. The recovery helper below performs the full target
build and package checks on the actual installed system, without hiding failure.

## Publish for subsequent unattended installations

Publish the complete `debian-preseed-de/` snapshot atomically at the existing
served location. Do not publish the loose hook without its regenerated payload,
manifest and preseed. A fresh installer invocation then stages this revision's
wrapper before NVIDIA's initial DKMS build.

Expected additional log marker when previously unpatched files are present:

```text
Applied NVIDIA 580 Linux 7.2 interface compatibility (r2): ...
```

Re-running an already patched tree makes no rewrite and need not print this
marker again. This revision does not remove or weaken the normal installer
package failure behavior.

## Recover the installation that has already downloaded its packages

The new helper is `tools/repair_nvidia_580.sh`. Run only after the failed package
operation has returned to the installer menu; do not run concurrent APT/dpkg or
DKMS operations. It makes no repository changes, downloads nothing, loads no
modules and does not reboot.

From the Debian installer's root shell, with this archive accessible at a known
path, the preferred invocation uses `in-target` to supply the normal target
pseudo-filesystem setup:

```sh
mkdir -p /target/root/nvidia-r2
tar -xzf /path/to/debian-preseed-de-nvidia580-xanmod724-r2.tar.gz \
  -C /target/root/nvidia-r2
in-target /bin/sh \
  /root/nvidia-r2/debian-preseed-de/tools/repair_nvidia_580.sh \
  / 7.2.4-x64v3-xanmod1
```

`/path/to/` is the location of the new archive on the installer/USB; replace it.
Do not run the archive's general installation or partitioning hooks for recovery.

Alternatively, with the extracted snapshot outside the target and the target's
`/dev`, `/proc` and `/sys` already mounted, the helper can operate directly:

```sh
sh tools/repair_nvidia_580.sh /target 7.2.4-x64v3-xanmod1
```

On an installed system, use `/` as TARGET_ROOT and run as root.

The helper checks the prepared headers/Module.symvers, existing DKMS diversion,
Perl and installed 580 source-package version. It extracts the exact production
wrapper from this snapshot, keeps an adjacent backup of the old wrapper, then
forces a full NVIDIA build and install for the explicitly named target kernel.
It does not use the installer's `uname -r`.

Only after the build, install and depmod succeed does it verify the versions and kernel identities of
`nvidia`, `nvidia-modeset`, `nvidia-drm` and `nvidia-uvm`, finish pending package
configuration, regenerate that kernel's initramfs and check that
`nvidia-dkms-580` is fully installed. Every failure propagates. A source fix or
build failure leaves the new wrapper in place for diagnosis/retry; the script
does not roll back packages or falsely print completion.

After a successful repair, return to the installer menu and retry package
installation so that the remaining installer and late hooks finish. **Do not
reboot immediately or treat this helper as completion of the Debian install.**

After the actual target has finished installation and booted, verify its running
kernel, DKMS modules, Secure Boot/MOK state where applicable, `nvidia-smi`, CUDA
12.8/12.9 compiler execution and an actual CUDA device workload. Compiler version
output alone does not establish working GPU computation.

## Primary-source references

The uploaded logs establish the observed failures. The following upstream source
files establish the additional API findings and the patch's compatibility basis:

- NVIDIA 580.142 NVSwitch: https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/580.142/kernel-open/nvidia/linux_nvswitch.c
- NVIDIA 580.142 modeset: https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/580.142/kernel-open/nvidia-modeset/nvidia-modeset-linux.c
- NVIDIA 580.142 UVM: https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/580.142/kernel-open/nvidia-uvm/uvm_pmm_gpu.c
- NVIDIA 580.142 DRM conftest header: https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/580.142/kernel-open/nvidia-drm/nvidia-drm-conftest.h
- NVIDIA 580.142 conftest implementation: https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/580.142/kernel-open/conftest.sh
- NVIDIA 580.142 common conftest include guard: https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/580.142/kernel-open/common/inc/conftest.h
- Linux 7.2 string implementations/exports: https://raw.githubusercontent.com/torvalds/linux/v7.2/lib/string.c
- Linux 7.2 DRM atomic transaction API: https://raw.githubusercontent.com/torvalds/linux/v7.2/include/drm/drm_atomic.h
- Linux 7.2 mode-config callback types: https://raw.githubusercontent.com/torvalds/linux/v7.2/include/drm/drm_mode_config.h

A community proposal in NVIDIA's repository also identifies the string and DRM
changes: https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1227/files . It is
not represented here as an approved proprietary-driver fix. Its open-driver ABI
renaming is deliberately not applied to the proprietary binaries.
