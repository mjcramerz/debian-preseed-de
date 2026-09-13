#!/usr/bin/env python3
"""Opt-in GTK3 rendering smoke test; run with xvfb-run, no native compilation.

Uses installed GTK directly through ctypes, not a fake widget implementation.
HighContrast's installed terminal image is a test fixture, not a Papirus claim.
"""
import ctypes as C
import ctypes.util
import sys
from pathlib import Path

P = C.c_void_p
I = C.c_int
S = C.c_char_p


def bind(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, list(args)
    return fn


def main():
    if len(sys.argv) != 3:
        raise SystemExit('usage: gtk_smoke.py rendered-style.css output.png')
    gtk = C.CDLL(ctypes.util.find_library('gtk-3'))
    gdk = C.CDLL(ctypes.util.find_library('gdk-3'))
    pix = C.CDLL(ctypes.util.find_library('gdk_pixbuf-2.0'))
    obj = C.CDLL(ctypes.util.find_library('gobject-2.0'))
    assert bind(gtk, 'gtk_init_check', I, P, P)(None, None), 'GTK display unavailable'
    css = bind(gtk, 'gtk_css_provider_new', P)()
    error = P()
    raw = Path(sys.argv[1]).read_bytes() + b'''\n
    .workspace-app, .workspace-app.active, .workspace-app:hover { -gtk-icon-theme: "HighContrast"; font-family: "DejaVu Sans"; }
    .workspace-app.wbi-test { background-image: -gtk-icontheme("utilities-terminal"); }
    .workspace-app.no-image { background-image: none; }
    '''
    loaded = bind(gtk, 'gtk_css_provider_load_from_data', I, P, S, C.c_ssize_t, C.POINTER(P))
    assert loaded(css, raw, len(raw), C.byref(error)) and not error.value, 'GTK CSS rejected'
    screen = bind(gdk, 'gdk_screen_get_default', P)()
    bind(gtk, 'gtk_style_context_add_provider_for_screen', None, P, P, C.c_uint)(screen, css, 800)
    win = bind(gtk, 'gtk_offscreen_window_new', P)()
    bind(gtk, 'gtk_widget_set_name', None, P, S)(win, b'waybar')
    box = bind(gtk, 'gtk_box_new', P, I, I)(0, 10)
    bind(gtk, 'gtk_container_add', None, P, P)(win, box)
    labels = []
    for count in (1, 2, 10, 99, 100):
        label = bind(gtk, 'gtk_label_new', P, S)(None)
        context = bind(gtk, 'gtk_widget_get_style_context', P, P)(label)
        add = bind(gtk, 'gtk_style_context_add_class', None, P, S)
        add(context, b'workspace-app'); add(context, b'wbi-test')
        if count == 2: add(context, b'active')
        if count == 99: add(context, b'minimized')
        markup = '\u200b'
        if count > 1:
            badge = str(count) if count < 100 else '99+'
            markup += '<span size="x-small" rise="5000" weight="bold">' + badge + '</span>'
        bind(gtk, 'gtk_label_set_markup', None, P, S)(label, markup.encode())
        bind(gtk, 'gtk_widget_set_size_request', None, P, I, I)(label, -1, 46)
        bind(gtk, 'gtk_box_pack_start', None, P, P, I, I, C.c_uint)(box, label, 0, 0, 0)
        labels.append((label, context))
    bind(gtk, 'gtk_widget_show_all', None, P)(win)
    pending = bind(gtk, 'gtk_events_pending', I)
    iterate = bind(gtk, 'gtk_main_iteration', I)
    while pending(): iterate()
    get = bind(gtk, 'gtk_offscreen_window_get_pixbuf', P, P)
    image = get(win)
    assert image
    save = bind(pix, 'gdk_pixbuf_savev', I, P, S, S, P, P, C.POINTER(P))
    assert save(image, str(Path(sys.argv[2])).encode(), b'png', None, None, C.byref(error))
    width = bind(pix, 'gdk_pixbuf_get_width', I, P)(image)
    height = bind(pix, 'gdk_pixbuf_get_height', I, P)(image)
    stride = bind(pix, 'gdk_pixbuf_get_rowstride', I, P)(image)
    data = bind(pix, 'gdk_pixbuf_get_pixels', P, P)(image)
    before = C.string_at(data, stride * height)
    remove_image = bind(gtk, 'gtk_style_context_add_class', None, P, S)
    for label, context in labels: remove_image(context, b'no-image')
    # Process a frame after a style change so comparison tests actual images,
    # not only parser acceptance or nonzero widget allocation.
    import time
    for _ in range(10):
        while pending(): iterate()
        time.sleep(.03)
    without = get(win)
    after = C.string_at(bind(pix, 'gdk_pixbuf_get_pixels', P, P)(without), stride * height)
    changed = sum(a != b for a, b in zip(before, after))
    assert changed > 100, 'theme image made no visible pixel contribution'
    bind(obj, 'g_object_unref', None, P)(image)
    bind(obj, 'g_object_unref', None, P)(without)
    bind(gtk, 'gtk_widget_destroy', None, P)(win)
    print(f'GTK3 CSS and raised badges rendered: {width}x{height}; image delta={changed} bytes')


if __name__ == '__main__':
    main()
