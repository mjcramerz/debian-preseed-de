# Application diagnostics from the launcher

The desktop uses greetd/gtkgreet and Labwc on Wayland. The launcher has no GDM
debug mode. GDK is GTK's display/input library; it is part of the GTK profile.

Right-click the Waybar menu button, choose a diagnostic profile, then select an
application. The ordinary desktop entry is normalized through the existing
managed launch policy. Diagnostic launches use its Exec path with D-Bus
activation disabled so the new process can receive its diagnostic environment.
The private Xwayland picker shows only Zoom/Discord; those entries are excluded
from the native toolkit pickers and the selected executable is checked again.
Existing single-instance applications may still accept activation without
adopting those variables; diagnostics report the evidence that was available.

## Profiles

Every profile has the same private collector, identity snapshots, output copy,
service results, toolkit discovery, effective diagnostic/renderer values and
archive. The toolkit entries add their own controls to the common protocol and
graphics trace settings.

| Menu entry | Additional controls |
| --- | --- |
| GTK Inspector + logs | `GTK_DEBUG=interactive`, GLib debug messages, GDK miscellaneous diagnostics and GSK renderer information |
| Qt / QtQuick | Plugin discovery, Qt logging categories, QML import trace and QtQuick renderer information |
| Electron / Chromium | Electron logging and stack dumping; the managed Ozone/Wayland and sandbox policy stays in force |
| Full application bundle | The GTK, Qt and Electron controls together |
| Wayland / OpenGL / Mesa / Vulkan | Wayland client protocol, libGL verbosity, Mesa/EGL diagnostics and Vulkan loader diagnostics |
| Private Xwayland | Only the existing Zoom/Discord entrypoints; observational Wayland/graphics traces around their existing Cage/private Xwayland path |

The existing renderer policy selects OpenGL and disables managed Vulkan paths.
Vulkan loader diagnostics do **not** enable Vulkan, change drivers, add loader
layers or override that policy. No profile adds remote debugging ports or
disables application sandboxing. Ordinary application unit names and their
existing lifetime, dependency, private runtime and cleanup contracts are kept.

## Correlation and evidence

Each launch gets a random 24-hex session identifier. A shared closed context
crosses the generic launcher, configured network worker and dedicated native
application service handoffs. qBittorrent and ChatGPT preserve that context
through their own environment reconstruction. Effective values are recorded
from a fixed list of diagnostic and renderer keys; full environments and
application argument lists are excluded.

Application stdout/stderr normally goes to the private rsyslog sinks, bypassing
journald. The existing Python output supervisor and ChatGPT's existing Perl
supervisor optionally copy bounded records into this private diagnostic session.
Their normal sinks and application exit/signal handling remain in place.
Common credential field names and authorization/cookie headers are redacted in
the diagnostic copy. The collector queries the journal only for recorded app
units, to include service startup and exit diagnostics.

Identity evidence has distinct strengths:

- `desktop_id` identifies the selected launcher file.
- `wlrctl toplevel list` provides actual compositor-advertised `app_id: title`
  records. The collector retains a baseline and subsequent snapshots. New
  records are temporal candidates, since foreign-toplevel does not expose a PID.
- `set_app_id` messages in the selected client's captured Wayland trace provide
  direct client identity evidence. These are not inferred from the filename.
- Recorded application service cgroups supply the candidate processes for
  toolkit discovery. UID, start time, executable and cgroup are checked around
  reads. The report contains executable identities and mapped library names,
  including GTK, Qt, QtQuick, SDL, GL/EGL and Vulkan evidence when readable.
- Electron's adjacent `resources/app.asar` is reported as separate bundle
  evidence, rather than pretending a GTK library dependency proves Electron.
- Private Xwayland remains limited to Zoom and Discord. The outer compositor
  exposes the Cage toplevel. Inner X11 `WM_CLASS` is not exposed through this
  Wayland protocol. The report states that limitation and records the permitted
  compatibility service/process identities and captured traces.

## Collection and bundle

The observer runs in `labwc-debug-collector-<session>.service`, tied to the
existing Labwc session. Its visible terminal displays JSON-escaped status and
output. Press Enter to request early finalization, or let it collect for up to
120 seconds. Completion displays the archive path:

```text
/run/user/<uid>/labwc-debug/<session>/diagnostic-bundle.tar.gz
```

The directory is mode 0700 and report/archive files are mode 0600. The archive
contains the request, effective environment records, baseline and runtime
identities, captured output, process/toolkit reports, unit journal evidence,
status, explanatory notes and a SHA-256 member manifest. It remains local in
the user runtime directory and is removed with that runtime at logout.

Bounds include four output supervisors of at most 256 KiB each, eight retained
sessions, 64 directory entries, fixed subprocess output limits, a 4 MiB archive
input limit and a 150-second collector service lifetime. Admission, output
admission and collector ownership use separate, scoped locks. No automatic
pruning races with a writer or removes an application's state.

Unavailable process metadata, denied reads, missing output, truncation,
timeouts and service results are evidence fields. A silent application or an
existing-instance activation is not proof that diagnostic variables reached a
new application. Close the application normally and select diagnostics again
when a fresh process is required.

## Verification boundary

The regression cases in `test_application_diagnostics_20261101.py` are authored
for context validation, renderer preservation, private compatibility policy,
real wlrctl parsing, unavailable identity and path rejection. They remain
unexecuted under the repository's static-only rule.

AST/structured-source inspection, the changed-file static audit and payload
serialization do not establish a live application launch, Inspector display,
loaded AppArmor acceptance or target service integration. No native application,
host service, test runner, container, VM or disposable environment is required
or authorized by this document.
