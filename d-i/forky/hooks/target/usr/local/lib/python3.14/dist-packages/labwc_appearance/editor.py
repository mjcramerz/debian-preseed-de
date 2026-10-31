"""GTK4 editor for appearance colors and coordinated theme presets."""
from __future__ import annotations

from collections import defaultdict
import subprocess
import sys

from . import fields
from .catalog import LABELS
from .engine import apply_choice
from .icon_catalog import (ICON_COLLECTIONS, POINTER_COLLECTIONS,
                           available_collections)
from .themes import FAMILIES
from .defaults import load


WAYBAR_CATEGORY_ORDER = (
    'Panel', 'Menu', 'Menu Button', 'Workspaces', 'Tomat / Wayscriber',
    'Taskview / Apps', 'Expanded / Revealed Apps', 'Clock', 'Monitor Buttons',
    'Tray', 'System', 'Expanded / Revealed System', 'Notifications', 'Lock', 'Power',
)

GRAMMAR_LABELS = {
    'gtk3-css-color': 'GTK3 color',
    'gtk4-css-color': 'GTK4 color',
    'pango-color': 'Pango color',
    'qt-color': 'Qt color',
    'mako-color': 'Mako color',
    'mako-progress': 'Mako progress color (over #RRGGBBAA)',
    'fuzzel-rgba': 'Fuzzel RGBA',
    'foot-rgb': 'Foot RGB',
    'kitty-color': 'Kitty color',
    'swaylock-rgb': 'Swaylock RGB',
    'swaylock-rgba': 'Swaylock RGBA',
    'alpha': 'opacity',
    'decimal': 'number',
}


def grammar_description(grammars):
    """Return consumer formats without exposing registry identifiers."""
    labels = [GRAMMAR_LABELS.get(grammar, 'color value') for grammar in grammars]
    return ', '.join(dict.fromkeys(labels))


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
            self._defaults = load()
            self._field_by_key = fields.field_map(registry)
            self._initial = fields.current_values(registry)
            self._draft = dict(self._initial)
            self._rows = []
            self._categories = []
            self._preset_cache = {}
            self._preset_states = {}
            self._building = False
            self._updating_color = False
            self._component_ids = ['DESKTOP', *[item['id'] for item in registry['components']]]
            self._preset_options = [('Default', None), ('Custom', 'custom'),
                                    *[(label, identity) for identity, label in LABELS.items()]]
            self._entry_sizes = Gtk.SizeGroup.new(Gtk.SizeGroupMode.HORIZONTAL)
            self._color_button_sizes = Gtk.SizeGroup.new(Gtk.SizeGroupMode.HORIZONTAL)
            self._reset_button_sizes = Gtk.SizeGroup.new(Gtk.SizeGroupMode.HORIZONTAL)

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            root.set_margin_top(16)
            root.set_margin_bottom(16)
            root.set_margin_start(18)
            root.set_margin_end(18)
            self.set_child(root)

            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            root.append(header)
            heading = Gtk.Label(label='Desktop Appearance')
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
            labels = ['Desktop Themes', *[component['label'] for component in registry['components']]]
            self._components = Gtk.StringList.new(labels)
            self._selector = Gtk.DropDown.new(self._components, None)
            self._selector.set_hexpand(True)
            self._selector.connect('notify::selected', self._component_changed)
            selector_row.append(self._selector)
            self._preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            root.append(self._preset_row)
            self._preset_row.append(Gtk.Label(label='Preset'))
            self._preset_variant = Gtk.DropDown.new(
                Gtk.StringList.new([label for label, _identity in self._preset_options]), None)
            self._preset_variant.set_hexpand(True)
            self._preset_variant.connect('notify::selected', self._preset_changed)
            self._preset_row.append(self._preset_variant)
            reset = Gtk.Button(label='Reset component')
            reset.connect('clicked', self._reset_component)
            self._preset_row.append(reset)

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

        @staticmethod
        def _theme_options():
            return [(f'{family.label} · {theme.label}', theme.identity)
                    for family in FAMILIES for theme in family.variants]

        @staticmethod
        def _asset_options(collections, *, pointer=False):
            return [(f'{collection.label} · {variant}', variant)
                    for collection in available_collections(collections, pointer=pointer)
                    for variant in collection.variants]

        def _component(self):
            index = self._selector.get_selected()
            return self._component_ids[index] if index < len(self._component_ids) else None

        def _preset_values(self, component, identity):
            key = (component, identity)
            if key not in self._preset_cache:
                self._preset_cache[key] = fields.preset_values(self._registry, component, identity,
                                                             self._defaults)
            return self._preset_cache[key]

        def _selected_preset(self, component):
            if component in self._preset_states:
                return self._preset_states[component]
            # Compare native values, so a stale selection record cannot label
            # manually edited colors as a preset. Compute once per component.
            current = {field['key']: self._draft[field['key']].strip()
                       for field in self._registry['fields'] if field['component'] == component}
            for _label, identity in self._preset_options:
                if identity == 'custom':
                    continue
                try:
                    expected = self._preset_values(component, identity)
                except (OSError, ValueError, RuntimeError, KeyError):
                    continue
                if current == expected:
                    self._preset_states[component] = identity
                    return identity
            self._preset_states[component] = 'custom'
            return 'custom'

        def _preset_changed(self, *_args):
            if self._building or self._component() in (None, 'DESKTOP'):
                return
            index = self._preset_variant.get_selected()
            if index >= len(self._preset_options):
                return
            identity = self._preset_options[index][1]
            component = self._component()
            if identity == 'custom':
                self._preset_states[component] = identity
                return
            self._remember_rows()
            try:
                values = self._preset_values(component, identity)
                self._draft.update(values)
                self._preset_states[component] = identity
                self._component_changed(remember=False)
                self._status.set_text('Preset preview updated. Save to apply these colors.')
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                self._component_changed(remember=False)
                self._show_error('Preset preview is unavailable: ', error)

        def _reset_component(self, *_args):
            if self._component() == 'DESKTOP':
                self._apply_desktop(['reset', 'desktop'])
            else:
                if self._preset_variant.get_selected() == 0:
                    self._preset_changed()
                else:
                    self._preset_variant.set_selected(0)

        def _desktop_controls(self):
            from .engine import CONFIG, initial, validate_state
            from managed_workflows.fs import Tree
            defaults = self._defaults
            with Tree(fields._account_home()) as home:
                state = validate_state(home.json(CONFIG, initial(defaults)))
            rows = (
                ('Desktop theme', 'theme', self._theme_options(), state['theme'], None),
                ('Cursor theme', 'pointer', self._asset_options(POINTER_COLLECTIONS, pointer=True),
                 state['pointer_theme'], defaults['pointer_theme']),
                ('Icon theme', 'icon', self._asset_options(ICON_COLLECTIONS),
                 state['icon_theme'], defaults['icon_theme']),
            )
            for label, target, variants, current, installed in rows:
                options = [('Default', None), *variants]
                identities = [identity for _label, identity in options]
                selected = 0 if current == installed else (
                    identities.index(current) if current in identities else Gtk.INVALID_LIST_POSITION)
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                name = Gtk.Label(label=label)
                name.set_xalign(0)
                name.set_width_chars(16)
                row.append(name)
                selector = Gtk.DropDown.new(Gtk.StringList.new([name for name, _ in options]), None)
                selector.set_hexpand(True)
                selector.set_selected(selected)
                row.append(selector)
                apply_button = Gtk.Button(label='Apply')
                apply_button.connect('clicked', self._desktop_apply_clicked, target, selector, options)
                row.append(apply_button)
                reset = Gtk.Button(label='Reset')
                reset.connect('clicked', lambda _button, kind=target: self._apply_desktop(['reset', kind]))
                row.append(reset)
                self._content.append(row)
            reset = Gtk.Button(label='Reset desktop themes')
            reset.connect('clicked', lambda *_: self._apply_desktop(['reset', 'desktop']))
            self._content.append(reset)

        def _desktop_apply_clicked(self, _button, target, selector, options):
            index = selector.get_selected()
            if index >= len(options):
                return
            identity = options[index][1]
            argv = (['reset', target] if identity is None else ['theme', identity]
                    if target == 'theme' else ['apply', target, identity])
            self._apply_desktop(argv)

        def _apply_desktop(self, argv):
            try:
                warnings = apply_choice(argv)
                self._component_changed(remember=False)
                self._status.set_text('Desktop themes updated.'
                                      + (('\n' + '\n'.join(warnings)) if warnings else ''))
            except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
                self._show_error('Desktop theme update did not finish: ', error)

        def _remember_rows(self):
            for row in self._rows:
                self._draft[row['field']['key']] = row['entry'].get_text()

        def _component_changed(self, *_args, remember=True):
            if remember:
                self._remember_rows()
            component = self._component()
            if component is None:
                return
            self._building = True
            while child := self._content.get_first_child():
                self._content.remove(child)
            self._rows = []
            self._categories = []
            self._preset_row.set_visible(component != 'DESKTOP')
            self._search.set_visible(component != 'DESKTOP')
            if component == 'DESKTOP':
                try:
                    self._desktop_controls()
                except (OSError, ValueError, RuntimeError, KeyError) as error:
                    self._show_error('Desktop themes could not be read: ', error)
                finally:
                    self._building = False
                return
            identity = self._selected_preset(component)
            self._preset_variant.set_selected(next(
                index for index, (_label, value) in enumerate(self._preset_options) if value == identity))
            grouped = defaultdict(list)
            for field in self._registry['fields']:
                if field['component'] == component:
                    grouped[field['category']].append(field)
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
            self._building = False
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
            label.set_tooltip_text('Editable color: ' + field['label'])
            heading.append(label)
            targets = sum(1 for mapping in field['mappings'] if mapping['path'].startswith('/'))
            target_text = ('greeter + desktop' if targets and targets < len(field['mappings'])
                           else 'greeter' if targets else 'desktop')
            target = Gtk.Label(label=target_text)
            target.add_css_class('dim-label')
            heading.append(target)
            entry = Gtk.Entry()
            entry.set_text(self._draft[field['key']])
            entry.set_width_chars(20)
            entry.set_max_width_chars(20)
            grammars = tuple(dict.fromkeys(mapping['grammar'] for mapping in field['mappings']))
            grammar_hint = grammar_description(grammars)
            entry.set_tooltip_text('Format: ' + grammar_hint)
            self._entry_sizes.add_widget(entry)
            heading.append(entry)
            if field['type'] not in ('alpha', 'decimal'):
                button = Gtk.ColorDialogButton.new(Gtk.ColorDialog())
                button.set_tooltip_text('Choose a color; the text value remains editable')
                try:
                    preview = fields.color_to_rgba(entry.get_text(), field['type'], grammars)
                except (ValueError, TypeError):
                    preview = fields.fallback_rgba()
                button.set_rgba(preview)
                button.set_size_request(38, -1)
                self._color_button_sizes.add_widget(button)
                button.connect('notify::rgba', self._color_changed, entry, field)
                heading.append(button)
            reset = Gtk.Button(label='Reset')
            reset.set_tooltip_text('Restore the installed base theme value')
            reset.set_size_request(72, -1)
            self._reset_button_sizes.add_widget(reset)
            reset.connect('clicked', lambda *_: entry.set_text(field['default']))
            heading.append(reset)
            entry.connect('changed', self._entry_changed, field, button if field['type'] not in ('alpha', 'decimal') else None)
            return {'widget': frame, 'field': field, 'entry': entry}

        def _entry_changed(self, entry, field, button):
            if self._building:
                return
            self._draft[field['key']] = entry.get_text()
            self._preset_states[field['component']] = 'custom'
            self._building = True
            self._preset_variant.set_selected(1)
            self._building = False
            if button is not None:
                try:
                    grammars = tuple(dict.fromkeys(mapping['grammar'] for mapping in field['mappings']))
                    color = fields.color_to_rgba(entry.get_text(), field['type'], grammars)
                    self._updating_color = True
                    button.set_rgba(color)
                except (ValueError, TypeError):
                    pass
                finally:
                    self._updating_color = False

        def _color_changed(self, button, _param, entry, field):
            if self._updating_color:
                return
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
                    match = (not needle or needle in field['label'].casefold()
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
            for key in self._field_by_key:
                message = message.replace(key, 'selected color')
            for grammar, label in GRAMMAR_LABELS.items():
                message = message.replace(grammar, label)
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
