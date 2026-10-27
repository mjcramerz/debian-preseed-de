# Waybar notification, taskview and calendar repairs — 2026-10-27

## Source and execution boundary

Base revision: `3ac1fddc51d727d09479f9078d1b38d8f0c3a92e`, with the changes
recorded here still in the working tree.

Target contracts: Debian Forky, systemd 262 and the installed Python 3.14
interpreter named in the supplied audit records. Waybar 0.15.0 is the version
reported by the user; no installed binary was queried.

Inspection covered the 91 supplied files under `todo/` (4,175,733 bytes at the
time of the census). These are historical target records. No host service,
desktop, package state, socket, device or credential was inspected or changed.
No tests, validation runners, native syntax checks, repository imports or
disposable execution environments were used.

## Findings and changes

### Notification JSON module and native GTK dropdown

The supplied audit log records 13 launches of the notification event reader,
with initial spacings of 30.131, 30.032, 30.036, 30.032 and 30.032 seconds.
Capture readers show the same restart pattern. See
`todo/managed/security/audit/auditd.log:4612` and `:6525` for the first two
notification reader executions. The records establish successful executable
launches followed by repeated restarts; they do not contain the Python error.

`labwc-waybar-events.tmpl` rejected user bus socket modes other than 0600,
0660 and 0700 before emitting JSON. Both the direct notification controller
and calendar controller repeated that restriction. A user bus socket can use
0666 inside its UID-owned 0700 runtime directory: the upstream
[D-Bus user socket unit](https://github.com/d-bus/dbus/blob/master/bus/systemd-user/dbus.socket.in)
does not override the
[systemd 262 socket mode default](https://github.com/systemd/systemd/blob/v262/man/systemd.socket.xml).
The supplied records do not include the actual bus socket mode, so attribution
to that particular initialization failure remains an inference from source.

The three helpers now retain canonical runtime paths, UID ownership, socket
type, single-link socket identity and the private 0700 parent check. They
accept the socket permissions selected by the bus unit.

The notification reader now emits a nonempty JSON error bell and returns zero
after initialization exceptions or a failed bus connection. Waybar can retain
that last status until the configured 30-second restart interval. Ordinary
notification control failures still return failure. Invalid reader arguments
and capture reader failures also retain their failure status.

This follows the behavior in
[Waybar 0.15.0 custom.cpp](https://github.com/Alexays/Waybar/blob/0.15.0/src/modules/custom.cpp):
nonzero continuous-reader exits clear the output, while a successful EOF
retains the last JSON status before restarting. JSON custom modules are
[documented in the same release](https://github.com/Alexays/Waybar/blob/0.15.0/man/waybar-custom.5.scd).

Both original bar definitions retain `return-type: json`, `format: {}`,
escaped output, the managed continuous reader and live normal/DND/error
classes. An intermediate static-button edit was withdrawn. Left click remains
`menu: on-click`, with no competing left-click command, and points at the
native GTK `notifications-menu.xml`. All seven action IDs match the XML.
The normal bell and its gold theme styling remain in use.

### Taskview

The audit log shows the click reaching `systemd-run`, the switcher helper,
`id -u` and then `stat -Lc '%u %a %h' /run/user/1000` at lines 8964–8989.
The supplied audit contains no `wtype` execution. This supports failure at
the helper's directory check.

The helper required the runtime directory's link count to equal one, although
directory link counts depend on the filesystem and child directories. It also
rejected normal compositor socket permissions. The helper now derives the
runtime path from the invoking UID, requires the matching `XDG_RUNTIME_DIR`,
rejects symlink endpoints and checks directory ownership/mode and real socket
ownership/type. The socket's own mode is left to the compositor inside that
private directory.

The release-triggered, bounded transient service, fixed F13 press/release
sequence, native `NextWindow` binding, cgroup ownership and timeout remain in
place. No input was injected during this work.

### Calendar Create task / Create event

Both GTK menu actions map to `labwc-calendar-actions` with `task-create` or
`event-create`. The controller repeated the bus socket-mode rejection and
masked every escaping exception as `controller-unavailable`.

The bus identity correction applies to both actions. Known startup failures
now retain their specific allowlisted error code and failure/unavailable/
outcome-unknown status. Unexpected exceptions include only their type name,
without exception messages, event/task fields or credentials. CalDAV writes,
their explicit Save action, ETag checks and uncertain-write recovery behavior
were not changed or exercised.

## Static evidence and generation

- Parsed three changed Python helpers and three fixture sources as AST data.
- Parsed both notification module objects and the notification/calendar XML as
  data; compared menu IDs and fixed action argument lists.
- Reviewed the taskview entrypoint, F13 mapping, service options and relevant
  AppArmor profiles as source.
- `git diff --check` completed without output.
- Authored unexecuted fixtures for bus socket modes, foreign owners, unsafe
  parents, aliases and link counts; visible JSON after reader failures;
  calendar startup error propagation; and taskview rejection/dispatch.
- Reviewed `Makefile`, `tools/build.py` and `tools/publication.py` before the
  permitted `make build`. It completed with `built 1854 payload files`.
- Compared seven selected source/archive members byte for byte, their manifest
  entries, and the archive/manifest pins embedded in preseed. No archive was
  extracted to disk and no packaged code was executed.

Source fingerprint for the four changed runtime files and three changed/new
fixture files, using sorted path bytes, NUL, file bytes, NUL:

```text
306a195c933f2c93dc8e4d257f2006346881ed8f4130e0f26f2987fc9ba80a1b
```

New fixture `d-i/forky/tests/test_waybar_button_runtime_20261027.py` SHA-256:

```text
0b5fc48f0e3e1ebae0bd489fe8ee722e0301ddae91dc925e9d5be5e549b67cce
```

Generated artifact SHA-256 values:

```text
be0ac047daa762f3c49cbb4ccd94a990731ee19004c0e6472150926e323d79cb  d-i/forky/payload.tar.gz
2b1aa2c6a0dad5cfa6c9a792e95466d37aa1ad86a9079c58bebae28906fdc467  d-i/forky/payload.manifest
47ea58a36add758eb7ac00182ac51ea5196d4305f12bbf8b79de9a2d08b79b8c  d-i/forky/preseed.cfg
```

## Remaining evidence limits

The supplied managed application and system logs are empty. The AppArmor log
contains no `DENIED` record, and the firstboot failed-unit snapshots list zero
failed system units. These facts do not establish a working user desktop.
Actual GTK popup visibility, taskview behavior, Mako state updates, credential
availability and successful Fruux operations remain unverified.

Other supplied observations include UCSI/USB-C firmware errors, I2C/HID firmware
diagnostics and CrowdSec Console synchronization while the machine reports
that it is not enrolled. The CrowdSec log later continues processing. These
observations need firmware or account-specific evidence; the desktop source
changes do not establish their resolution.

The regenerated preseed, manifest and payload form one publication set.
Generating them does not update an already installed system or publish them
to the installer's download origin.
