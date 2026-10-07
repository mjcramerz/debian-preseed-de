"""Headless GTK3 measurement of the actual rendered CSS, not a Waybar runtime test."""
import ctypes as C
import ctypes.util
import json
from pathlib import Path
import sys

G = C.CDLL(ctypes.util.find_library('gtk-3'))
D = C.CDLL(ctypes.util.find_library('gdk-3'))
O = C.CDLL(ctypes.util.find_library('gobject-2.0'))
L = C.CDLL(ctypes.util.find_library('glib-2.0'))
P = C.CDLL(ctypes.util.find_library('pango-1.0'))
ptr = C.c_void_p
class Error(C.Structure):
    _fields_ = [('domain', C.c_uint), ('code', C.c_int), ('message', C.c_char_p)]
class Border(C.Structure):
    _fields_ = [('left', C.c_short), ('right', C.c_short), ('top', C.c_short), ('bottom', C.c_short)]
class RGBA(C.Structure):
    _fields_ = [(name, C.c_double) for name in ('red', 'green', 'blue', 'alpha')]

def bind(lib, name, result, *args):
    function = getattr(lib, name)
    function.restype = result
    function.argtypes = list(args)
    return function
init = bind(G, 'gtk_init_check', C.c_int, ptr, ptr)
assert init(None, None), 'GTK initialization failed'
screen = bind(D, 'gdk_screen_get_default', ptr)()
provider_new = bind(G, 'gtk_css_provider_new', ptr)
load_css = bind(G, 'gtk_css_provider_load_from_data', C.c_int, ptr, C.c_char_p, C.c_ssize_t, C.POINTER(C.POINTER(Error)))
add_provider = bind(G, 'gtk_style_context_add_provider_for_screen', None, ptr, ptr, C.c_uint)
remove_provider = bind(G, 'gtk_style_context_remove_provider_for_screen', None, ptr, ptr)
unref = bind(O, 'g_object_unref', None, ptr)
window_new = bind(G, 'gtk_window_new', ptr, C.c_int)
box_new = bind(G, 'gtk_box_new', ptr, C.c_int, C.c_int)
label_new = bind(G, 'gtk_label_new', ptr, C.c_char_p)
set_name = bind(G, 'gtk_widget_set_name', None, ptr, C.c_char_p)
get_context = bind(G, 'gtk_widget_get_style_context', ptr, ptr)
add_class = bind(G, 'gtk_style_context_add_class', None, ptr, C.c_char_p)
set_state = bind(G, 'gtk_widget_set_state_flags', None, ptr, C.c_int, C.c_int)
get_state = bind(G, 'gtk_widget_get_state_flags', C.c_int, ptr)
container_add = bind(G, 'gtk_container_add', None, ptr, ptr)
pack = bind(G, 'gtk_box_pack_start', None, ptr, ptr, C.c_int, C.c_int, C.c_uint)
show = bind(G, 'gtk_widget_show_all', None, ptr)
destroy = bind(G, 'gtk_widget_destroy', None, ptr)
events_pending = bind(G, 'gtk_events_pending', C.c_int)
iterate = bind(G, 'gtk_main_iteration', C.c_int)
width = bind(G, 'gtk_widget_get_allocated_width', C.c_int, ptr)
height = bind(G, 'gtk_widget_get_allocated_height', C.c_int, ptr)
padding = bind(G, 'gtk_style_context_get_padding', None, ptr, C.c_int, C.POINTER(Border))
margin = bind(G, 'gtk_style_context_get_margin', None, ptr, C.c_int, C.POINTER(Border))
border = bind(G, 'gtk_style_context_get_border', None, ptr, C.c_int, C.POINTER(Border))
bg = bind(G, 'gtk_style_context_get_background_color', None, ptr, C.c_int, C.POINTER(RGBA))
color = bind(G, 'gtk_style_context_get_color', None, ptr, C.c_int, C.POINTER(RGBA))
style_get = G.gtk_style_context_get
style_get.restype = None
style_get.argtypes = [ptr, C.c_int]  # Remaining arguments are C varargs.
font_size = bind(P, 'pango_font_description_get_size', C.c_int, ptr)
font_free = bind(P, 'pango_font_description_free', None, ptr)

def drain():
    while events_pending():
        iterate()

def metrics(label):
    context = get_context(label)
    state = get_state(label)
    values = {'width': width(label), 'height': height(label)}
    for name, fn in (('padding', padding), ('margin', margin), ('border', border)):
        val = Border()
        fn(context, state, C.byref(val))
        values[name] = [getattr(val, edge) for edge in ('left','right','top','bottom')]
    font = ptr()
    style_get(context, state, C.c_char_p(b'font'), C.byref(font), None)
    assert font.value
    values['font_size'] = font_size(font)
    font_free(font)
    return values

records = []
for css_path in sys.argv[1:]:
    css = Path(css_path).read_bytes()
    provider = provider_new()
    error = C.POINTER(Error)()
    ok = load_css(provider, css, len(css), C.byref(error))
    assert ok and not error, (css_path, error.contents.message.decode() if error else 'CSS failed')
    add_provider(screen, provider, 600)
    for layout in ('external', 'internal'):
        for dnd in (False, True):
            for hover in (False, True):
                window = window_new(0)
                set_name(window, b'waybar')
                add_class(get_context(window), layout.encode())
                box = box_new(0, 4)
                container_add(window, box)
                labels = []
                for name, text in (('notifications', '\U0001f515' if dnd else '\U0001f514'),
                                   ('lock', '\U0001f512'), ('power', '\u23fb')):
                    label = label_new(text.encode())
                    set_name(label, ('custom-' + name).encode())
                    if name == 'notifications':
                        add_class(get_context(label), b'dnd' if dnd else b'normal')
                        if hover:
                            set_state(label, 2, False)  # GTK_STATE_FLAG_PRELIGHT
                    pack(box, label, False, False, 0)
                    labels.append(label)
                show(window)
                drain()
                measured = [metrics(label) for label in labels]
                assert measured[0] == measured[1] == measured[2], (css_path, layout, dnd, hover, measured)
                record = {'profile': Path(css_path).stem, 'layout': layout, 'dnd': dnd,
                          'hover': hover, 'metrics': measured[0]}
                if hover:
                    context = get_context(labels[0])
                    state = get_state(labels[0])
                    val = RGBA()
                    bg(context, state, C.byref(val))
                    actual = [round(getattr(val, k)*255) for k in ('red','green','blue')]
                    assert actual == [236,184,96] and abs(val.alpha-1) < 0.001, (layout,dnd,actual,val.alpha)
                    color(context, state, C.byref(val))
                    assert [round(getattr(val,k)*255) for k in ('red','green','blue')] == [8,17,31]
                    record['hover_rgb'] = actual
                # Resting chips retain the same geometry while their tint
                # distinguishes notification (gold), lock (silver) and power (red).
                for idx, expected, alpha in ((0, [236,184,96], .14),
                                             (1, [203,213,225], .14),
                                             (2, [248,113,113], .16)):
                    if idx == 0 and hover:
                        continue
                    val = RGBA()
                    bg(get_context(labels[idx]), get_state(labels[idx]), C.byref(val))
                    actual = [round(getattr(val,k)*255) for k in ('red','green','blue')]
                    assert actual == expected and abs(val.alpha-alpha) < .001, (css_path,idx,actual,val.alpha)
                records.append(record)
                destroy(window)
                drain()
    remove_provider(screen, provider)
    unref(provider)
print(json.dumps({'gtk_cases': len(records), 'records': records}, indent=2))
