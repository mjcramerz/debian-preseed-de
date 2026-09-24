# Native IOCost configuration fixture

`udev-257-iocost.conf` is the unmodified conffile installed by Debian udev
257.9-1~deb13u1 at `/etc/udev/iocost.conf`. It contains no active directive.
Source: https://github.com/systemd/systemd/blob/v257/src/udev/iocost/iocost.conf
The upstream copyright/license header is retained.

SHA-256: `39f985861cb49e86be2434029800eca9be9b9704f0ddb6d67465a3e037587c41`

The native and two-level BusyBox chroot fixtures include this file, rather
than assuming that installing udev leaves its native configuration absent.


## Calibration fixtures

`resctl-bench-20260923.json` records the first naive-only raw-result/export
integration and is retained as historical evidence. `exports-20260923.json`
records the newer user export with six independently modelled solutions. It
includes separate measured firmware and requested wildcard match, the nine
reserved group names, all twelve scalars per supplied solution, source digests,
and evidence limitations. The full immutable export JSON/hwdb are under
`docs/hardware-tuning/calibration-20260923-exports/`, outside the runtime payload.

`profile-calibration-reversions.json` is a narrow reverse map used by older
non-IOCost policy-history tests: only `current` IOCost blocks track this revision;
`historical` values and historical checksums remain immutable. Replacing the
current block must reproduce every non-IOCost byte in the prior profiles. It is
not an alternative deployment configuration.
