# Debian in-target protocol regression fixtures

`in-target` (31 lines, 498 bytes) and `debconf-get` (6 lines, 111 bytes) are
transcribed from Debian Sources, debian-installer-utils **1.155**, the version
recorded in the supplied installation syslog. Tabs and final newlines retained.

- https://sources.debian.org/src/debian-installer-utils/1.155/in-target/
- https://sources.debian.org/src/debian-installer-utils/1.155/debconf-get/
- https://sources.debian.org/src/debian-installer-utils/1.155/chroot-setup.sh/

`chroot-setup-protocol.sh` is explicitly a **reduced test fixture**, not the
complete upstream file: only the Debconf query, locale and environment-reset
sequence is kept. Mounts, diversions and filesystem preparation are not tested.
The test copies this reduction to `/lib/chroot-setup.sh` inside a temporary
installer chroot. A separate temporary `/target` is entered with real chroot.
`log-output` is a narrow shell shim preserving stdin and inherited descriptors;
the compiled d-i log-output and cdebconf backend are not executed here.

The shell clients use the existing Debian confmodule fixture and a private
installed Perl Debconf File-driver backend. No host Debconf database, devices,
mounts, network, packages or installed configuration are changed.

Upstream GPL-2-or-later applies. `COPYRIGHT` transcribes the Debian package notice
also published at https://sources.debian.org/src/debian-installer-utils/1.119/debian/copyright/.
The full GPL-2 text is retained in `../debian-preseed/GPL-2`.
SHA256SUMS records these local fixture bytes, not an independently downloaded signature.
