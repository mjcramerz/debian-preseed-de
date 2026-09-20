# Native IOCost configuration fixture

`udev-257-iocost.conf` is the unmodified conffile installed by Debian udev
257.9-1~deb13u1 at `/etc/udev/iocost.conf`. It contains no active directive.
Source: https://github.com/systemd/systemd/blob/v257/src/udev/iocost/iocost.conf
The upstream copyright/license header is retained.

SHA-256: `39f985861cb49e86be2434029800eca9be9b9704f0ddb6d67465a3e037587c41`

The native and two-level BusyBox chroot fixtures include this file, rather
than assuming that installing udev leaves its native configuration absent.
