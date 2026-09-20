#!/usr/bin/env python3
"""Offline native GTK3 check of both optional-audio staging states.

Run with xvfb-run -a python3 -I -B <this-file> <forky-source-dir>. The X display is a disposable
validation fixture, not part of the installed Wayland/Xwayland configuration.
No service, microphone, or audio action is invoked.
"""
import ctypes as C
import ctypes.util
from pathlib import Path
import sys
import tempfile
from unittest import mock
import xml.etree.ElementTree as ET

FORKY = Path(sys.argv[1]).resolve()
source = (FORKY / 'scripts/desktop/components.sh').read_text()
code = source.split('run_in_target "configure optional native audio menu" /usr/bin/python3 -I -c \'\n', 1)[1].split("\n' \"$native_menu_whisper\"", 1)[0]
G = C.CDLL(ctypes.util.find_library('gtk-3'))
O = C.CDLL(ctypes.util.find_library('gobject-2.0'))
G.gtk_init_check.argtypes = [C.c_void_p, C.c_void_p]
G.gtk_init_check.restype = C.c_int
assert G.gtk_init_check(None, None), 'GTK fixture display unavailable'
G.gtk_builder_new.restype = C.c_void_p
G.gtk_builder_add_from_file.argtypes = [C.c_void_p, C.c_char_p, C.POINTER(C.c_void_p)]
G.gtk_builder_add_from_file.restype = C.c_uint
G.gtk_builder_get_object.argtypes = [C.c_void_p, C.c_char_p]
G.gtk_builder_get_object.restype = C.c_void_p
for name in ('gtk_widget_get_parent', 'gtk_menu_get_attach_widget'):
    getattr(G, name).argtypes = [C.c_void_p]
    getattr(G, name).restype = C.c_void_p
G.gtk_widget_get_sensitive.argtypes = [C.c_void_p]
G.gtk_widget_get_sensitive.restype = C.c_int
O.g_object_unref.argtypes = [C.c_void_p]

with tempfile.TemporaryDirectory() as work:
    path = Path(work) / 'audio-menu.xml'
    path.write_bytes((FORKY / 'hooks/target/etc/skel-desktop/.config/waybar/audio-menu.xml').read_bytes())
    for enabled in ('0', '1', '0'):
        with mock.patch('pathlib.Path', return_value=path), mock.patch.object(sys, 'argv', ['fixture', enabled]):
            exec(compile(code, 'actual-audio-staging', 'exec'), {})
        builder = G.gtk_builder_new()
        error = C.c_void_p()
        try:
            assert G.gtk_builder_add_from_file(builder, str(path).encode(), C.byref(error)), 'staged XML rejected by GTK3'
            for item in ET.parse(path).iter('object'):
                if item.get('id'):
                    assert G.gtk_builder_get_object(builder, item.get('id').encode())
            record = G.gtk_builder_get_object(builder, b'whisper_record')
            submenu = G.gtk_widget_get_parent(record)
            parent = G.gtk_menu_get_attach_widget(submenu)
            assert parent and bool(G.gtk_widget_get_sensitive(parent)) == (enabled == '1')
            print('PASS: actual staged GtkMenu Whisper sensitivity =', enabled)
        finally:
            O.g_object_unref(builder)
