# Clock click binding and Agenda decorations — 2026-10-24

## Changes

The user requested that left-clicking Waybar's clock open the existing GTK
menu without changing the clock format, and that only right-click switch
formats. Both `internal` and `external` clock sections in
`d-i/forky/hooks/target/etc/skel-desktop/.config/waybar/config.tmpl` now use
`"format-alt-click": 3`, retaining `"menu": "on-click"`. The existing fixture
expectation in `d-i/forky/tests/test_native_menu_contract_20260920.py` is updated.
The normal and alternate format strings and calendar menu actions are unchanged
by this correction.

[Waybar's label implementation](https://github.com/Alexays/Waybar/blob/master/src/ALabel.cpp)
compares the configured format-toggle button directly with the GTK button
event before invoking the ordinary menu handler. The installer renderer
substitutes template variables; the clock button binding is a literal.

The user also requested no client-side decorations for Agenda. Inspection of
`/home/mcramer/Workspace/agenda/src/Window.vala` found an explicit
`Gtk.HeaderBar` passed to `set_titlebar()`. The existing managed environment
already sets `GTK_CSD=0`, so merely repeating that setting cannot address the
explicit header bar. No files in that sibling checkout were changed or built.

The integration now uses the packaged GTK-NoCSD interposer:

- `d-i/forky/classes/class-select/role/desktop.cfg` includes `libgtk-nocsd0`
  through the existing Debian package installation path.
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/labwc_managed_app/profiles.py.tmpl`
  sets Agenda's `LD_PRELOAD` to the fixed Debian amd64 library path
  `/usr/lib/x86_64-linux-gnu/libgtk-nocsd.so.0`, retains `GDK_BACKEND=wayland`
  and explicitly sets `GTK_CSD=0`. The library is also a required runtime file
  so a missing package is reported instead of silently ignoring the preload.
- New `d-i/forky/hooks/target/etc/environment.d/50-gtk-nocsd.conf` contains
  comments only. Its higher-priority basename overrides the vendor's global
  preload snippet, keeping the interposer scoped to Agenda's final exec.
- `d-i/forky/scripts/desktop/components/target-assets.sh` stages that override
  as `/etc/environment.d/50-gtk-nocsd.conf`, root-owned mode 0644, using the
  existing asset publisher.
- `docs/calendar-and-wifi.md` describes both corrected controls and Agenda's
  decoration integration.

Agenda's desktop entry has `DBusActivatable=false` and invokes the managed
launcher. The menu alias also reaches that launcher. Its environment is
constructed after native user-manager reentry and passed to the application
exec. The existing Labwc `serverDecoration=yes` rule supplies the frame. The
existing Agenda AppArmor profile allows the packaged `/usr/lib/**` library
mapping; no new executable transition is introduced.

## Package and upstream evidence

[Debian's package description](https://packages.debian.org/forky/libgtk-nocsd0)
describes the library and the same-name environment override convention.
The [amd64 file list](https://packages.debian.org/forky/amd64/libgtk-nocsd0/filelist)
identifies `/usr/lib/x86_64-linux-gnu/libgtk-nocsd.so.0` and the vendor snippet.
The package web pages served inconsistent cached version labels, so a live
read-only query to the
[official Debian archive API](https://api.ftp-master.debian.org/madison?package=libgtk-nocsd0&s=forky)
confirmed Forky/testing `4.8-1` for amd64 and the other listed architectures.
No host package database was read.

The Debian upstream source and packaging archives were fetched as bounded
data and inspected in memory without extraction or execution:

| Public source | Bytes | SHA-256 |
| --- | ---: | --- |
| [gtk-nocsd_4.8.orig.tar.gz](https://deb.debian.org/debian/pool/main/g/gtk-nocsd/gtk-nocsd_4.8.orig.tar.gz) | 719,696 | `2be0214c37a57d1e0bcd7d217310c2af1307955710077f41db928fb40d33fa68` |
| [gtk-nocsd_4.8-1.debian.tar.xz](https://deb.debian.org/debian/pool/main/g/gtk-nocsd/gtk-nocsd_4.8-1.debian.tar.xz) | 6,684 | `b9b83741ef6cfa2f09187de03af24d0d19158cf461a3516e786058e24747f3a1` |

The upstream README explicitly supports Wayland and describes moving header
controls into window content while restoring server decorations. The source
intercepts `gtk_window_set_titlebar` and reparents the header; this preserves
Agenda's application menu. Packaging includes the global environment snippet
and no new target package repository is needed. The source hashes record the
bytes inspected, not a separate signature verification.

## Checks and generated products

Source fingerprint for the template, changed fixture, desktop package class,
Agenda profile, environment override and staging component, sorted using
`path + NUL + bytes + NUL`:
`763c100b29b44f0ea80cd49e27b4830790f2bd1e1ab6eb2b4b585428820d250a`.

- Inline `/usr/bin/python3 -I -S -B -` parsed the Waybar template as JSON data
  after neutral scalar substitution for installer tokens. Both clock objects
  select button 3 and the left-click menu.
- The same data inspection used `ast.parse` on the profile and changed fixture,
  and `ast.literal_eval` only on Agenda's literal profile dictionary. It
  confirmed the preload is specific to Agenda, the dependency occurs once,
  the library is required, and the comment-only override is explicitly staged.
  The staging shell was tokenized with `shlex`, not executed or natively
  syntax-checked. No repository module was imported.
- `git diff --check` completed without errors.
- `make build PYTHON=/usr/bin/python3` completed with 1,830 payload files.
- Separate bounded standard-library archive/hash inspection matched all
  1,830 members with current source and manifest bytes, totaling 34,862,061
  expanded bytes. Preseed archive, manifest and bootstrap-source pins match;
  private input names are absent.

| Product | SHA-256 |
| --- | --- |
| `d-i/forky/payload.tar.gz` | `ad0676867aa9409547f3698e8083cfd738febd7bc84cfe657ba4b548d076b823` |
| `d-i/forky/payload.manifest` | `5f14ef290906fd6bef5f80994229eb87378eb65b3c891ce642dc349f6b2df896` |
| `d-i/forky/preseed.cfg` | `dad6046c00f6f83168dbc730365528c2a165752b1b3568d54b1dc8853a9b5849` |

No test suite, GUI, package installation, source compilation, host manager
operation or deployment was run. The attempted independent sidecars failed
encrypted-content hydration; no independent review is claimed. The target
remains Debian Forky/systemd 262; no installed target image was queried. The
Agenda release and preload path here are amd64, consistent with the existing
Agenda binary integration. Live visual behavior remains unverified. The root
offline inventories remain separate, stale generation products.
