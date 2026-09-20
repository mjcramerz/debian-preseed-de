#!/usr/bin/python3
"""Real GTK3 menu styling and signal wiring, with no host action execution.

Usage: xvfb-run -a python3 -I -B THIS FORKY PROFILES_JSON
PROFILES_JSON is generated from actual host profile renderer substitutions.
Uses packaged shared libraries through ctypes; no upstream source compilation.
The X server is only a disposable GTK test fixture, not a target configuration.
"""
from __future__ import annotations

import ctypes as C
import ctypes.util
import json
from pathlib import Path
import sys
import tempfile
from unittest import mock

G = C.CDLL(ctypes.util.find_library('gtk-3'))
D = C.CDLL(ctypes.util.find_library('gdk-3'))
O = C.CDLL(ctypes.util.find_library('gobject-2.0'))
L = C.CDLL(ctypes.util.find_library('glib-2.0'))
ptr = C.c_void_p


class Error(C.Structure):
    _fields_ = [('domain', C.c_uint), ('code', C.c_int), ('message', C.c_char_p)]


class RGBA(C.Structure):
    _fields_ = [(name, C.c_double) for name in ('red', 'green', 'blue', 'alpha')]


class List(C.Structure):
    pass


List._fields_ = [('data', ptr), ('next', C.POINTER(List)), ('prev', C.POINTER(List))]


def bind(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype, function.argtypes = result, list(arguments)
    return function


init = bind(G, 'gtk_init_check', C.c_int, ptr, ptr)
assert init(None, None), 'GTK fixture display unavailable'
settings = bind(G, 'gtk_settings_get_default', ptr)()
set_property = O.g_object_set
set_property.restype, set_property.argtypes = None, [ptr, C.c_char_p]
set_property(settings, b'gtk-enable-animations', C.c_int(0), None)
screen = bind(D, 'gdk_screen_get_default', ptr)()
provider_new = bind(G, 'gtk_css_provider_new', ptr)
load_css = bind(G, 'gtk_css_provider_load_from_data', C.c_int, ptr, C.c_char_p,
                C.c_ssize_t, C.POINTER(C.POINTER(Error)))
add_provider = bind(G, 'gtk_style_context_add_provider_for_screen', None, ptr, ptr, C.c_uint)
remove_provider = bind(G, 'gtk_style_context_remove_provider_for_screen', None, ptr, ptr)
builder_new = bind(G, 'gtk_builder_new', ptr)
build = bind(G, 'gtk_builder_add_from_file', C.c_uint, ptr, C.c_char_p, C.POINTER(C.POINTER(Error)))
get_object = bind(G, 'gtk_builder_get_object', ptr, ptr, C.c_char_p)
children = bind(G, 'gtk_container_get_children', C.POINTER(List), ptr)
list_free = bind(L, 'g_list_free', None, C.POINTER(List))
submenu = bind(G, 'gtk_menu_item_get_submenu', ptr, ptr)
parent = bind(G, 'gtk_widget_get_parent', ptr, ptr)
get_label = bind(G, 'gtk_menu_item_get_label', C.c_char_p, ptr)
child = bind(G, 'gtk_bin_get_child', ptr, ptr)
get_name = bind(G, 'gtk_buildable_get_name', C.c_char_p, ptr)
get_context = bind(G, 'gtk_widget_get_style_context', ptr, ptr)
get_state = bind(G, 'gtk_widget_get_state_flags', C.c_uint, ptr)
set_state = bind(G, 'gtk_widget_set_state_flags', None, ptr, C.c_uint, C.c_int)
set_sensitive = bind(G, 'gtk_widget_set_sensitive', None, ptr, C.c_int)
is_sensitive = bind(G, 'gtk_widget_get_sensitive', C.c_int, ptr)
select_item = bind(G, 'gtk_menu_shell_select_item', None, ptr, ptr)
deselect = bind(G, 'gtk_menu_shell_deselect', None, ptr)
background = bind(G, 'gtk_style_context_get_background_color', None, ptr, C.c_uint, C.POINTER(RGBA))
foreground = bind(G, 'gtk_style_context_get_color', None, ptr, C.c_uint, C.POINTER(RGBA))
show = bind(G, 'gtk_widget_show_all', None, ptr)
destroy = bind(G, 'gtk_widget_destroy', None, ptr)
activate = bind(G, 'gtk_menu_item_activate', None, ptr)
is_type = bind(O, 'g_type_check_instance_is_a', C.c_int, ptr, C.c_size_t)
separator_type = bind(G, 'gtk_separator_menu_item_get_type', C.c_size_t)()
unref = bind(O, 'g_object_unref', None, ptr)
connect = bind(O, 'g_signal_connect_data', C.c_ulong, ptr, C.c_char_p, ptr, ptr, ptr, C.c_uint)
pending = bind(G, 'gtk_events_pending', C.c_int)
iterate = bind(G, 'gtk_main_iteration', C.c_int)


def drain():
    # These menus do not run a main loop or an external service. Bound pumping
    # nevertheless, so a broken test cannot spin indefinitely on GTK sources.
    for _ in range(1000):
        if not pending():
            return
        iterate()
    raise AssertionError('GTK events did not settle')


def walk(menu):
    items = children(menu)
    try:
        current = items
        while current:
            item = current.contents.data
            if not is_type(item, separator_type):
                yield item
                nested = submenu(item)
                if nested:
                    yield from walk(nested)
            current = current.contents.next
    finally:
        list_free(items)


def rgba(widget, getter):
    value = RGBA()
    getter(get_context(widget), get_state(widget), C.byref(value))
    return [round(getattr(value, name) * 255) for name in ('red', 'green', 'blue')] + [round(value.alpha, 4)]


root = Path(sys.argv[1]).resolve()
profiles = json.loads(Path(sys.argv[2]).read_text())
assets = root / 'hooks/target/etc/skel-desktop/.config/waybar'
source = (root / 'scripts/desktop/components.sh').read_text()
staging = source.split('run_in_target "configure optional native audio menu" /usr/bin/python3 -I -c \'\n', 1)[1].split("\n' \"$native_menu_whisper\"", 1)[0]
modules = [('custom/tomat', 'tomat'), ('clock', 'calendar'), ('pulseaudio', 'audio'),
           ('custom/notifications', 'notifications'), ('custom/power', 'power')]
report = {'profiles': len(profiles), 'themes': ['Adwaita', 'Adwaita-dark'],
          'menu_roots': 0, 'activations': 0, 'center_activations': 0,
          'highlight_states': 0, 'disabled_states': 0, 'submenu_headers': 0,
          'orange_rgba': [242, 159, 103, 0.24], 'callback_errors': []}
callback_type = C.CFUNCTYPE(None, ptr, ptr)

with tempfile.TemporaryDirectory() as temporary:
    staged_audio = {}
    for enabled in (False, True):
        path = Path(temporary) / ('audio-' + str(int(enabled)) + '.xml')
        path.write_bytes((assets / 'audio-menu.xml').read_bytes())
        with mock.patch('pathlib.Path', return_value=path), mock.patch.object(sys, 'argv', ['fixture', str(int(enabled))]):
            exec(compile(staging, 'actual-native-audio-staging', 'exec'), {})
        staged_audio[enabled] = path
    for theme in report['themes']:
        set_property(settings, b'gtk-theme-name', C.c_char_p(theme.encode()), None)
        for profile in profiles:
            css = Path(profile['css']).read_bytes()
            provider = provider_new()
            error = C.POINTER(Error)()
            ok = load_css(provider, css, len(css), C.byref(error))
            assert ok and not error, (profile['name'], error.contents.message.decode() if error else 'CSS load failed')
            add_provider(screen, provider, 600)  # Same application-level priority as Waybar.
            for bar in profile['bars']:
                for optional_enabled in (False, True):
                    for module, menu_name in modules:
                        builder = builder_new()
                        error = C.POINTER(Error)()
                        path = staged_audio[optional_enabled] if menu_name == 'audio' else assets / (menu_name + '-menu.xml')
                        assert build(builder, str(path).encode(), C.byref(error)) and not error
                        menu = get_object(builder, b'menu')
                        assert menu
                        show(menu)
                        drain()
                        report['menu_roots'] += 1
                        commands = bar[module]['menu-actions']
                        refs = []
                        expected_callback = []
                        seen_callback = []
                        for ident, command in commands.items():
                            item = get_object(builder, ident.encode())
                            assert item

                            def on_activate(_item, _data, ident=ident, command=command):
                                # Mirror Waybar's GtkMenuItem::activate -> command
                                # association without executing the systemd command.
                                try:
                                    seen_callback.append((ident, command))
                                except Exception as exc:
                                    report['callback_errors'].append(str(exc))

                            callback = callback_type(on_activate)
                            refs.append(callback)
                            assert connect(item, b'activate', callback, None, None, 0)
                        for item in walk(menu):
                            label = (get_label(item) or b'').decode()
                            ident = (get_name(item) or b'').decode()
                            where = (profile['name'], bar['name'], theme, optional_enabled, menu_name, ident, label)
                            header = bool(submenu(item))
                            enabled = bool(is_sensitive(item))
                            if header:
                                report['submenu_headers'] += 1
                            if menu_name == 'audio' and label.startswith('Whisper'):
                                assert enabled == optional_enabled, where
                            for state in (2, 4):  # PRELIGHT (pointer), SELECTED (theme compatibility)
                                set_state(item, state, True)
                                if not enabled:
                                    set_state(item, 8, False)  # INSENSITIVE must remain dominant.
                                actual = rgba(item, background)
                                if enabled:
                                    assert actual == report['orange_rgba'], (where, state, actual)
                                    assert rgba(child(item), foreground) == [245, 239, 227, 1.0], where
                                    report['highlight_states'] += 1
                                else:
                                    assert actual[3] == 0.0, (where, state, actual)
                                    assert rgba(child(item), foreground)[:3] == [174, 183, 198], where
                                    report['disabled_states'] += 1
                            set_state(item, 0, True)
                            if enabled:
                                # Native menu selection is the operation GTK uses
                                # for keyboard traversal, not just a CSS flag probe.
                                container = parent(item)
                                select_item(container, item)
                                assert get_state(item) & 2, (where, 'keyboard selection is not PRELIGHT')
                                assert rgba(item, background) == report['orange_rgba'], (where, 'keyboard highlight')
                                report['highlight_states'] += 1
                                deselect(container)
                            # Exercise the inactive guard on every leaf/header,
                            # including a deliberately selected insensitive widget.
                            set_sensitive(item, False)
                            set_state(item, 2 | 4, False)
                            assert rgba(item, background)[3] == 0.0, (where, 'disabled highlight')
                            assert rgba(child(item), foreground)[:3] == [174, 183, 198], where
                            report['disabled_states'] += 1
                            set_sensitive(item, enabled)
                            set_state(item, 0, True)
                            if enabled and ident in commands and (optional_enabled or not ident.startswith('whisper_')):
                                expected_callback.append((ident, commands[ident]))
                                activate(item)
                                report['activations'] += 1
                                if ident == 'notifications_center':
                                    report['center_activations'] += 1
                        assert seen_callback == expected_callback, (profile['name'], bar['name'], menu_name)
                        destroy(menu)
                        unref(builder)
                        drain()
            remove_provider(screen, provider)
            unref(provider)
assert not report['callback_errors'], report
print(json.dumps(report, indent=2))
