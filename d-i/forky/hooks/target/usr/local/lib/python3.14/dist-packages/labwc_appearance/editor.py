"""GTK4 editor for the colors present in installed native appearance files."""
from __future__ import annotations

from collections import defaultdict
import subprocess
import sys

from . import fields


WAYBAR_CATEGORY_ORDER = (
    'Panel', 'Menu', 'Menu Button', 'Workspaces', 'Tomat / Wayscriber',
    'Taskview / Apps', 'Expanded / Revealed Apps', 'Clock', 'Monitor Buttons',
    'Tray', 'System', 'Expanded / Revealed System', 'Notifications', 'Lock', 'Power',
)


def main() -> int:
    try:
        import gi
        gi.require_version('Gdk', '4.0')
        gi.require_version('Gio', '2.0')
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gdk, Gio, Gtk
    except (ImportError, ValueError) as error:
        raise RuntimeError('GTK4 PyGObject is required for Desktop Appearance') from error

    registry = fields.load_registry()

    class AppearanceWindow(Gtk.ApplicationWindow):
        def __init__(self, application):
            super().__init__(application=application, title='Desktop Appearance')
            self.set_default_size(1120, 760)
            self.set_size_request(780, 520)
            self._registry = registry
            self._field_by_key = fields.field_map(registry)
            self._initial = fields.current_values(registry)
            self._draft = dict(self._initial)
            self._rows = []
            self._categories = []

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            root.set_margin_top(16)
            root.set_margin_bottom(16)
            root.set_margin_start(18)
            root.set_margin_end(18)
            self.set_child(root)

            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            root.append(header)
            heading = Gtk.Label(label='Installed native colors')
            heading.set_xalign(0)
            heading.set_hexpand(True)
            heading.add_css_class('title-2')
            header.append(heading)
            self._search = Gtk.SearchEntry()
            self._search.set_placeholder_text('Search colors')
            self._search.set_width_chars(28)
            self._search.connect('search-changed', self._filter_rows)
            header.append(self._search)

            selector_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            root.append(selector_row)
            selector_row.append(Gtk.Label(label='Component'))
            labels = [component['label'] for component in registry['components']]
            self._components = Gtk.StringList.new(labels)
            self._selector = Gtk.DropDown.new(self._components, None)
            self._selector.set_hexpand(True)
            self._selector.connect('notify::selected', self._component_changed)
            selector_row.append(self._selector)
            self._target_label = Gtk.Label()
            self._target_label.set_xalign(1)
            self._target_label.add_css_class('dim-label')
            selector_row.append(self._target_label)

            scroll = Gtk.ScrolledWindow()
            scroll.set_vexpand(True)
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            root.append(scroll)
            self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            scroll.set_child(self._content)

            footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            root.append(footer)
            self._status = Gtk.Label()
            self._status.set_xalign(0)
            self._status.set_wrap(True)
            self._status.set_hexpand(True)
            footer.append(self._status)
            cancel = Gtk.Button(label='Close')
            cancel.connect('clicked', lambda *_: self.close())
            footer.append(cancel)
            save = Gtk.Button(label='Save and refresh')
            save.add_css_class('suggested-action')
            save.connect('clicked', self._save)
            footer.append(save)

            self._component_changed()

        def _remember_rows(self):
            for row in self._rows:
                self._draft[row['field']['key']] = row['entry'].get_text()

        def _component_changed(self, *_args, remember=True):
            if remember:
                self._remember_rows()
            selected = self._selector.get_selected()
            if selected >= len(self._registry['components']):
                return
            component = self._registry['components'][selected]['id']
            while child := self._content.get_first_child():
                self._content.remove(child)
            self._rows = []
            self._categories = []
            grouped = defaultdict(list)
            for field in self._registry['fields']:
                if field['component'] == component:
                    grouped[field['category']].append(field)
            total = sum(len(values) for values in grouped.values())
            self._target_label.set_text(f'{total} installed fields')
            categories = (WAYBAR_CATEGORY_ORDER if component == 'WAYBAR'
                          else tuple(sorted(grouped)))
            for category in categories:
                category_fields = grouped.get(category)
                if not category_fields:
                    continue
                expander = Gtk.Expander(label=f'{category}  ({len(category_fields)})')
                expander.set_expanded(True)
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                box.set_margin_top(8)
                box.set_margin_bottom(8)
                box.set_margin_start(8)
                box.set_margin_end(8)
                expander.set_child(box)
                self._content.append(expander)
                category_record = {'expander': expander, 'rows': []}
                self._categories.append(category_record)
                for field in category_fields:
                    row = self._field_row(field)
                    box.append(row['widget'])
                    row['category'] = category_record
                    self._rows.append(row)
                    category_record['rows'].append(row)
            self._filter_rows()

        def _field_row(self, field):
            frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            frame.set_margin_top(5)
            frame.set_margin_bottom(5)
            heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            frame.append(heading)
            label = Gtk.Label(label=field['label'])
            label.set_xalign(0)
            label.set_hexpand(True)
            label.set_tooltip_text(field['key'])
            heading.append(label)
            targets = sum(1 for mapping in field['mappings'] if mapping['path'].startswith('/'))
            target_text = ('greeter + native' if targets and targets < len(field['mappings'])
                           else 'greeter' if targets else 'native')
            target = Gtk.Label(label=target_text)
            target.add_css_class('dim-label')
            heading.append(target)
            entry = Gtk.Entry()
            entry.set_text(self._draft[field['key']])
            entry.set_hexpand(True)
            grammars = tuple(dict.fromkeys(mapping['grammar'] for mapping in field['mappings']))
            grammar_hint = ', '.join(grammars)
            entry.set_tooltip_text(field['key'] + ' — native format: ' + grammar_hint)
            heading.append(entry)
            if field['type'] not in ('alpha', 'decimal'):
                try:
                    button = Gtk.ColorDialogButton.new(Gtk.ColorDialog())
                    button.set_tooltip_text('Choose a color; the text value remains editable')
                    button.set_rgba(fields.color_to_rgba(entry.get_text(), field['type'], grammars))
                    button.connect('notify::rgba', self._color_changed, entry, field)
                    heading.append(button)
                except (ValueError, TypeError):
                    # The entry remains the authoritative editor for formats
                    # that GTK cannot preview, such as Crystal-Dock ARGB.
                    pass
            reset = Gtk.Button(label='Reset')
            reset.set_tooltip_text('Restore the installed base theme value')
            reset.connect('clicked', lambda *_: entry.set_text(field['default']))
            heading.append(reset)
            hint = Gtk.Label(label=f"{field['key']}  ·  native: {grammar_hint}")
            hint.set_xalign(0)
            hint.add_css_class('dim-label')
            frame.append(hint)
            return {'widget': frame, 'field': field, 'entry': entry}

        @staticmethod
        def _color_changed(button, _param, entry, field):
            try:
                grammars = tuple(dict.fromkeys(mapping['grammar'] for mapping in field['mappings']))
                entry.set_text(fields.rgba_to_value(button.get_rgba(), field['type'], grammars))
            except ValueError:
                pass

        def _filter_rows(self, *_args):
            needle = self._search.get_text().strip().casefold()
            for category in self._categories:
                visible = False
                for row in category['rows']:
                    field = row['field']
                    match = (not needle or needle in field['key'].casefold()
                             or needle in field['label'].casefold()
                             or needle in field['category'].casefold())
                    row['widget'].set_visible(match)
                    visible = visible or match
                category['expander'].set_visible(visible)

        def _save(self, *_args):
            selected = {}
            try:
                self._remember_rows()
                for key, draft in self._draft.items():
                    value = draft.strip()
                    if value != self._initial[key]:
                        selected[key] = fields.validate_value(self._field_by_key[key], value)
            except (ValueError, KeyError) as error:
                self._show_error('Appearance was not saved: ', error)
                return
            if not selected:
                self._status.set_text('No appearance changes to save.')
                return
            try:
                warnings = fields.apply(selected)
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
                self._show_error('Appearance update did not finish: ', error)
                return
            try:
                self._initial = fields.current_values(self._registry)
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
                self._show_error('Appearance saved, but current colors could not be reread: ', error)
                return
            self._draft = dict(self._initial)
            self._component_changed(remember=False)
            self._status.set_text('Saved appearance changes.'
                                  + (('\n' + '\n'.join(warnings)) if warnings else ''))

        def _show_error(self, prefix, error):
            message = ''.join(char if char.isprintable() else '?' for char in str(error))
            self._status.set_text(prefix + message[:300])

    class AppearanceApplication(Gtk.Application):
        def __init__(self):
            super().__init__(application_id='org.labwc.DesktopAppearance',
                             flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.window = None
            self.connect('window-removed', self._window_removed)

        def _window_removed(self, _application, window):
            if window is self.window:
                self.window = None

        def do_activate(self):
            if self.window is None:
                self.window = AppearanceWindow(self)
            self.window.present()

    application = AppearanceApplication()
    return application.run(sys.argv[:1])
