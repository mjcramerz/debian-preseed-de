> **Superseded by [revision 2](NVIDIA580-XANMOD724-R2.md).** The new logs demonstrate that this process-name-only repair missed NVSwitch and other Linux 7.2 interfaces. This document and its test counts are historical, not validation of the current revision.

# NVIDIA 580.142 / XanMod 7.2.4 targeted installer fix

Date: 2026-09-08

## Delivery status

The delivered source change removes the exact `strncpy` compile blocker reported
in the supplied `make.log`. It is installed by the existing pre-pkgsel DKMS
wrapper, before the NVIDIA package's first DKMS build. CUDA repository setup,
its explicit insecure/trust exception, the NVIDIA branch, package selection,
compiler settings and kernel selection are unchanged.

**A complete unattended installation and a full NVIDIA 580.142 DKMS build on
7.2.4-x64v3-xanmod1 have not been performed in this environment.** The exact
build inputs and an NVIDIA GPU were unavailable, and attempts to download the
build inputs did not succeed. The validation below is evidence of the targeted
repair, not a substitute for that hardware acceptance test.

## What the supplied logs show

The diagnosis uses the three separately uploaded September 8 logs, not the older
historical logs already present under the repository's `todo/` directory.

| Evidence | Finding |
| --- | --- |
| `make.log`, opening lines | DKMS 3.2.2 is building NVIDIA 580.142 for 7.2.4-x64v3-xanmod1 with LLVM. |
| `make.log`, `nvidia/os-interface.c:732` | The fatal error is the call to undeclared `strncpy`. |
| `make.log`, compiler/pahole diagnostics | These are warnings; they are not the fatal diagnostic in this build. |
| `installer(3).log`, 07:44:23Z | Legacy CUDA metadata refresh completed. NVIDIA's pre-pkgsel wrapper was then staged successfully. |
| `syslog(3)`, 08:08:14 | Both `cuda-nvcc-12-8` and `cuda-nvcc-12-9` were configured. |
| `syslog(3)`, 08:11:48-08:12:02 | The repeated DKMS build failed and `nvidia-dkms-580` remained the reported package-configuration failure. |

Linux 7.2 no longer declares or exports the kernel-side `strncpy` API. The old
installer wrapper added `linux/string.h`, which cannot restore a removed API.
Adding a libc header, declaring the missing function manually, suppressing the
compiler diagnostic, or replacing it with unbounded `strcpy` is not this fix.

The CUDA toolkits' successful package configuration does **not** prove working
GPU computation: their runtime driver still depends on the NVIDIA kernel
modules. There is no separate fatal CUDA repository or toolkit installation
error demonstrated by these logs that warrants changing the repository policy.

## The source change

Only this existing installation-logic file was edited:

`d-i/forky/hooks/installer/pre-pkgsel.d/92nvidia-legacy-dkms.sh`

The new `patch_nv_os_interface` helper transforms the known process-name function
from:

```c
void NV_API_CALL os_get_current_process_name(char *buf, NvU32 len)
{
    task_lock(current);
    strncpy(buf, current->comm, len - 1);
    buf[len - 1] = '\0';
    task_unlock(current);
}
```

into:

```c
void NV_API_CALL os_get_current_process_name(char *buf, NvU32 len)
{
    task_lock(current);
    /* NV_INSTALLER_NVIDIA_LEGACY_STRNCPY_COMPAT */
    strscpy_pad(buf, current->comm, len);
    task_unlock(current);
}
```

The full destination size, `len`, is deliberate. `strscpy_pad` reserves the
terminator itself and preserves the original NUL padding. Passing `len - 1`
would unnecessarily truncate an additional character. Removing the separate
`buf[len - 1]` write also avoids its zero-length underflow. Task locking is
preserved. The modern primitive is also available in the Debian 6.12 headers
used for the compatibility compile probe.

The wrapper validates the complete known function, rather than replacing every
`strncpy` in the source tree. It handles the existing proprietary layout and
the existing nested `kernel-open` layout within the wrapper's 580-only roots.
It patches `/usr/src` before DKMS copies it, and also handles existing registered
source links and stale build copies. A package reinstall that restores the old
source is repaired on the next invocation; there is no stale success stamp.

Rewrites preserve ownership/mode and are published by a same-directory atomic
rename. Already-correct functions are validated without requiring source write
access, including read-only DKMS status operations. Unknown, duplicate or
partially patched function bodies cause a clear error and do not publish that
file's rewrite or invoke the real DKMS build. A future vendor function with a
different body must be reviewed instead of being silently modified.

The real DKMS executable's arguments and exit status remain intact. No build
failure is converted to success. The existing string-header/GPIO compatibility
code is retained unchanged. No labwc, wlroots, systemd, storage, Secure Boot,
compiler-warning policy, NVIDIA package pin or CUDA repository changes were made.

## Generated installation products

The repository's own `tools/build.py` was run. These three generated files were
updated together with the hook:

- `d-i/forky/payload.tar.gz`
- `d-i/forky/payload.manifest`
- `d-i/forky/preseed.cfg`

There are exactly four changed existing files: the hook and those three generated
products. All other 1,311 original files are unchanged. Tests, this report, and
validation evidence are additions. `scope.json` records original/new SHA-256
values and verifies that all 11 original CUDA-named files are unchanged.

## Validation performed

The evidence directory is `validation/nvidia-580-xanmod-7.2.4/`.

| Check | Result and scope |
| --- | --- |
| New NVIDIA DKMS regressions | 14 passed. Covers actual generated wrapper execution, atomic failures, unknown source rejection, idempotency, read-only reruns, version scope, source links, stale builds, package re-unpack, argument forwarding and DKMS failure propagation. |
| Executable C contract fixture | 1,040 combinations of process-name length and destination capacity, plus NULL/zero capacity; padding, terminator, canaries and lock balance checked with UndefinedBehaviorSanitizer. Original code is a failing negative control when `strncpy` is poisoned. This is an explicitly modeled API-contract fixture. |
| CUDA legacy regressions | 40 passed. |
| Existing security regressions | 28 passed. |
| Repository integrity regressions | 8 passed. |
| Repository test coverage | All 530 unique test cases have passing evidence across completed module runs and isolated debconf reruns. This is not a single uninterrupted full-suite invocation. |
| Shell parsing | 264 shell files, 539 parser checks passed, including the generated preseed command boundaries. |
| Preseed checks | 59 files passed; all four generated command values survived actual private debconf read-back. |
| Real kernel API compile/link probe | The patched function compiled and passed MODPOST/linking against Debian `6.12.96+deb13-amd64` headers using GCC 14, in a small module declaring the proprietary `NVIDIA` license. No module was loaded. This is not the full NVIDIA driver and not a XanMod 7.2.4 build. |
| Broader pre-existing code audit | 415 pass, 115 structural pass, 154 dependency-blocked, 476 inventory-only and 2 templates requiring rendering. Blocked/inventory/structural checks are not runtime acceptance tests. |

The first monolithic test run exceeded the execution window. Smaller completed
runs cover every expected case; `test-coverage.json` and `module-tests.json`
identify that evidence. Historical interrupted/short-budget logs are retained,
not reclassified as passing runs.

To repeat the targeted checks from the repository root:

```sh
python3 -B tools/build.py --check
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_nvidia_legacy_dkms.py
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_cuda_legacy_apt.py
python3 -B tools/check_shells.py
python3 -B tools/check_preseeds.py
```

The optional compile probe is reproducible with explicitly selected prepared
kernel headers and an appropriate compiler. It never loads its module:

```sh
python3 -B validation/nvidia-580-xanmod-7.2.4/kernel-api-probe.py \
  --headers /usr/src/linux-headers-6.12.96+deb13-amd64 --cc gcc-14
```

## Publishing and target acceptance

Extract the tarball into a staging directory and publish the complete repository
through the existing serving workflow. Publish the updated hook, payload,
manifest and preseed entry point **together**, preferably by an atomic release
switch. Updating only the loose hook leaves the pinned installer snapshot stale.
Keep the existing repository URL/branch layout. A fresh installer invocation is
needed to fetch the new snapshot; an already running installation may retain the
old cached payload and old target wrapper.

On the installed target, the following are acceptance checks, not checks that
were performed against a GPU in this environment:

```sh
uname -r
sudo dpkg --audit
sudo dkms status -m nvidia -v 580.142
for module in nvidia nvidia-modeset nvidia-drm nvidia-uvm; do
  modinfo -k 7.2.4-x64v3-xanmod1 -F version "$module"
done
nvidia-smi
/usr/local/cuda-12.8/bin/nvcc --version
/usr/local/cuda-12.9/bin/nvcc --version
```

For the exact logged installation, the intended running release is
`7.2.4-x64v3-xanmod1`; DKMS should report the 580.142 modules as installed for it,
`dpkg --audit` should be empty, and all four module version queries should
succeed. `nvcc --version` verifies toolkit installation only. Driver
initialization can additionally be tested through the CUDA driver API:

```sh
python3 - <<'PY'
import ctypes
cuda = ctypes.CDLL('libcuda.so.1')
cuda.cuInit.argtypes = [ctypes.c_uint]
cuda.cuInit.restype = ctypes.c_int
cuda.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
cuda.cuDeviceGetCount.restype = ctypes.c_int
rc = cuda.cuInit(0)
if rc:
    raise SystemExit(f'cuInit failed: CUDA error {rc}')
count = ctypes.c_int()
rc = cuda.cuDeviceGetCount(ctypes.byref(count))
if rc or count.value < 1:
    raise SystemExit(f'CUDA device enumeration failed: rc={rc}, count={count.value}')
print(f'CUDA driver initialized; visible devices: {count.value}')
PY
```

A representative CUDA workload and the actual labwc session must still be
exercised after boot. Secure Boot enrollment and module loading remain governed
by the existing installation policy. This patch neither bypasses those checks
nor claims they were hardware-tested.

## Upstream API references

- NVIDIA 580.142 function: `https://raw.githubusercontent.com/NVIDIA/open-gpu-kernel-modules/580.142/kernel-open/nvidia/os-interface.c`
- Linux 7.2 string API and padding contract: `https://raw.githubusercontent.com/torvalds/linux/v7.2/include/linux/string.h`
- Linux 7.2 `sized_strscpy` implementation and non-GPL-only export: `https://raw.githubusercontent.com/torvalds/linux/v7.2/lib/string.c`

The open-module source above is an API reference. The installation has **not**
been switched from the user's proprietary 580 package to the open driver.
