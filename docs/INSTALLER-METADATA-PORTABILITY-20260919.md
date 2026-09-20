# Installer and target metadata portability correction

This correction supersedes the command-retention policy in the historical
2026-09-06 and 2026-09-14 incident reports. Those reports retain their original
evidence; they are not instructions for the current implementation.

## Failure and correction

The previous delivered tree called the external `stat` program at line 108 of
`scripts/late/iocost.sh` while running in Debian Installer. A restricted applet
fixture reproduced `/bin/sh: 108: stat: not found`. The credential reader itself
already used numeric `ls` metadata; IOCost had reintroduced the missing tool
later in the same installation flow.

All production invocations and required-command declarations for that external
program have been removed, including calls inside target chroots, desktop and
first-boot helpers. No replacement executable with that name is installed.

Installer IOCost now uses the existing `installer_metadata_value` reader. It
parses only fixed numeric columns from `LC_ALL=C ls -ldn`, with globbing disabled;
it does not parse the filename. A combined UID/GID selector avoids two separate
reads. The existing owner, group, mode, single-link, parent-containment, private
staging, publication and rollback checks are retained.

Installed-system helpers use GNU findutils on exactly one path (`-maxdepth 0`)
with fixed numeric formats. They do not enumerate directories. `-P` retains
non-following behavior; `-H` is used only where the old code intentionally
followed the specified argument, including an already-open lock descriptor.
No descriptor check was replaced with reopening a potentially substituted
pathname. GNU formatting is never required in the installer host. The target
initramfs hook copies its required target executable and dependencies through
the existing mechanism.

Only the corresponding executable entries in AppArmor were adjusted. No file,
capability, service, signal or process-isolation grants were broadened.

The Podman filesystem reader now receives findutils filesystem names (`ext2`,
`ext3`, `ext4`) rather than the former combined display alias. The same supported
filesystem families and native storage-driver decision are preserved. Its
filesystem-name lookup uses the existing target executor so the normal d-i
`in-target` bridge supplies the target mount table; it never reads the installer
filesystem as a substitute.

## A second BusyBox incompatibility

The restricted tests also found that BusyBox grep could not reliably match the
native IOCost configuration-path string inside an ELF file containing NULs.
The capability check now converts C-string separators to newlines and matches
the entire expected string. Unknown native interfaces still fail closed. No
extra service, hardware calibration, live uevent or installer-host hwdb update
was introduced.

## Regression protection and scope

Both `make build` and `make check` reject external metadata-program invocations
and command dependencies in active shell/Python code. Focused tests include:

- three shell interpreters with a restricted BusyBox-only applet PATH;
- real private `.env` loading without the missing executable;
- ownership, group, hard links, special mode bits, unusual filenames and errors;
- target single-path reads, explicit symlink handling and open lock descriptors;
- the entire IOCost schema/staging/rollback suite under the restricted PATH;
- a two-level disposable chroot with neither installer nor target metadata
  executable, exercising credential loading and actual native hwdb compilation
  and query through the production target executor.

Python/Perl native filesystem APIs, kernel `/proc/.../stat` filenames, negative
test strings and historical evidence remain. They do not execute the missing
program. Removing or disguising them would weaken security checks or break
process discovery without addressing the reported shell error.

All prior font, CPU, module, theme and profile-driven IOCost changes are retained.
The current release qualification and precise baseline exceptions are recorded
under `validation/metadata-portability-20260919/`. A booted hardware installation
is still required for end-to-end device acceptance.
