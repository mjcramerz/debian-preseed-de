"""Measure real GTK3 state colors, symbolic painting and tray load context.

Arguments: fully rendered CSS; validated values JSON. No Waybar daemon, D-Bus
client, signal delivery or application launch occurs in this headless fixture.
"""
import ctypes as C
import ctypes.util
import json
from pathlib import Path
import sys

P = C.c_void_p
G = C.CDLL(ctypes.util.find_library('gtk-3'))
D = C.CDLL(ctypes.util.find_library('gdk-3'))
O = C.CDLL(ctypes.util.find_library('gobject-2.0'))
R = C.CDLL(ctypes.util.find_library('cairo'))
B = C.CDLL(ctypes.util.find_library('gdk_pixbuf-2.0'))


def bind(lib, name, result, *args):
    fn = getattr(lib, name); fn.restype = result; fn.argtypes = list(args); return fn


class Error(C.Structure):
    _fields_ = [('domain', C.c_uint), ('code', C.c_int), ('message', C.c_char_p)]


class RGBA(C.Structure):
    _fields_ = [(name, C.c_double) for name in ('red','green','blue','alpha')]


assert bind(G,'gtk_init_check',C.c_int,P,P)(None,None)
values = json.loads(Path(sys.argv[2]).read_text())
provider = bind(G,'gtk_css_provider_new',P)()
css = Path(sys.argv[1]).read_bytes() + b'\n* { transition: none; }\n'
error = C.POINTER(Error)()
assert bind(G,'gtk_css_provider_load_from_data',C.c_int,P,C.c_char_p,C.c_ssize_t,C.POINTER(C.POINTER(Error)))(provider,css,len(css),C.byref(error)), error.contents.message
screen = bind(D,'gdk_screen_get_default',P)()
bind(G,'gtk_style_context_add_provider_for_screen',None,P,P,C.c_uint)(screen,provider,600)
new_window = bind(G,'gtk_window_new',P,C.c_int)
new_box = bind(G,'gtk_box_new',P,C.c_int,C.c_int)
new_eventbox = bind(G,'gtk_event_box_new',P)
new_label = bind(G,'gtk_label_new',P,C.c_char_p)
set_name = bind(G,'gtk_widget_set_name',None,P,C.c_char_p)
context = bind(G,'gtk_widget_get_style_context',P,P)
add_class = bind(G,'gtk_style_context_add_class',None,P,C.c_char_p)
state = bind(G,'gtk_widget_set_state_flags',None,P,C.c_int,C.c_int)
get_state = bind(G,'gtk_widget_get_state_flags',C.c_int,P)
add = bind(G,'gtk_container_add',None,P,P)
show = bind(G,'gtk_widget_show_all',None,P)
destroy = bind(G,'gtk_widget_destroy',None,P)
pending = bind(G,'gtk_events_pending',C.c_int)
iterate = bind(G,'gtk_main_iteration',C.c_int)
get_color = bind(G,'gtk_style_context_get_color',None,P,C.c_int,C.POINTER(RGBA))
render = bind(G,'gtk_render_background',None,P,P,C.c_double,C.c_double,C.c_double,C.c_double)
surface_new = bind(R,'cairo_image_surface_create',P,C.c_int,C.c_int,C.c_int)
cairo_new = bind(R,'cairo_create',P,P)
surface_data = bind(R,'cairo_image_surface_get_data',P,P)
surface_stride = bind(R,'cairo_image_surface_get_stride',C.c_int,P)
flush = bind(R,'cairo_surface_flush',None,P)
cairo_destroy = bind(R,'cairo_destroy',None,P)
surface_destroy = bind(R,'cairo_surface_destroy',None,P)
unref = bind(O,'g_object_unref',None,P)


def rgb(name):
    color = values[name]
    return tuple(int(color[i:i+2],16) for i in (1,3,5))


def drain():
    while pending(): iterate()


def window(layout):
    win = new_window(0); set_name(win,b'waybar'); add_class(context(win),layout.encode())
    box = new_box(0,0); add(win,box)
    return win,box


records = []
for layout in ('internal','external'):
    cases = []
    for mode in ('IDLE','RECORDING'):
        for hover in (False,True):
            cases.append(('custom-screenshot', '' if mode=='IDLE' else 'recording', hover,
                          'WAYBAR_BUTTON_SCREENSHOT_'+mode+('_HOVER' if hover else '')+'_ICON_COLOR'))
    for state_name,language in (('se','SWEDISH'),('us','US_ENGLISH')):
        cases.append(('custom-keyboard',state_name,False,'WAYBAR_BUTTON_KEYBOARD_'+language+'_ICON_COLOR'))
    for mode in ('ENABLED','CONNECTED','DISABLED','UNAVAILABLE'):
        cases.append(('custom-bluetooth',mode.lower(),False,'WAYBAR_BUTTON_BLUETOOTH_'+mode+'_ICON_COLOR'))
    for mode in ('WIFI','ETHERNET','LINKED','DISCONNECTED','DISABLED'):
        cases.append(('network',mode.lower(),False,'WAYBAR_BUTTON_NETWORK_'+mode+'_ICON_COLOR'))
    for mode in ('NORMAL','DND','ERROR'):
        for hover in (False,True):
            cases.append(('custom-notifications',mode.lower(),hover,
                          'WAYBAR_BUTTON_NOTIFICATIONS_'+('HOVER' if hover else mode)+'_ICON_COLOR'))
    for module,component in (('custom-window-switcher','TASKVIEW'), ('custom-system','SYSTEM')):
        cases.append((module,'',False,'WAYBAR_BUTTON_'+component+'_NORMAL_ICON_COLOR'))
    for component in ('LOCK','POWER'):
        for hover in (False,True):
            cases.append(('custom-'+component.lower(),'',hover,'WAYBAR_BUTTON_'+component+('_HOVER' if hover else '_NORMAL')+'_ICON_COLOR'))
    for module,cls,hover,key in cases:
        win,box = window(layout)
        label = new_label(b'icon'); set_name(label,module.encode()); add(box,label)
        if cls: add_class(context(label),cls.encode())
        if hover: state(label,2,False)
        show(win); drain()
        actual = RGBA(); get_color(context(label),get_state(label),C.byref(actual))
        got = tuple(round(getattr(actual,ch)*255) for ch in ('red','green','blue'))
        assert got == rgb(key),(layout,module,cls,hover,key,got,rgb(key))
        records.append({'layout':layout,'module':module,'state':cls,'hover':hover,'rgb':got})
        destroy(win); drain()
    for component in ('APPS','WAYSCRIBER'):
        for hover in (False,True):
            win,box = window(layout)
            label = new_label(b' '); set_name(label,('custom-'+component.lower()).encode()); add(box,label)
            if hover: state(label,2,False)
            show(win); drain()
            surface = surface_new(0,80,40); cr = cairo_new(surface)
            render(context(label),cr,0,0,80,40); flush(surface)
            stride = surface_stride(surface); pixels = C.string_at(surface_data(surface),stride*40)
            expected = rgb('WAYBAR_BUTTON_'+component+('_HOVER' if hover else '_NORMAL')+'_ICON_COLOR')
            matches = 0
            for y in range(40):
                for x in range(80):
                    pixel = int.from_bytes(pixels[y*stride+x*4:y*stride+x*4+4],sys.byteorder)
                    if ((pixel>>16)&255,(pixel>>8)&255,pixel&255)==expected: matches+=1
            assert matches>3,(layout,component,hover,expected,matches)
            records.append({'layout':layout,'paint':component,'hover':hover,'rgb':expected,'matching_pixels':matches})
            cairo_destroy(cr); surface_destroy(surface); destroy(win); drain()
    # Waybar SNI colors symbolic pixels using the event-box, before creating a
    # Cairo surface. Testing an image widget's CSS color would miss this boundary.
    win,box = window(layout)
    tray = new_box(0,0); set_name(tray,b'tray'); add(box,tray)
    item = new_eventbox(); add(tray,item); add(item,new_label(b' ')); show(win); drain()
    theme = bind(G,'gtk_icon_theme_get_default',P)()
    lookup = bind(G,'gtk_icon_theme_lookup_icon',P,P,C.c_char_p,C.c_int,C.c_int)
    info = lookup(theme,b'media-playback-start-symbolic',24,16)
    assert info, 'native symbolic test icon not available'
    load_symbolic = bind(G,'gtk_icon_info_load_symbolic_for_context',P,P,P,C.POINTER(C.c_int),C.POINTER(C.POINTER(Error)))
    was = C.c_int(); error = C.POINTER(Error)()
    pixbuf = load_symbolic(info,context(item),C.byref(was),C.byref(error))
    assert pixbuf and was.value, error.contents.message if error else 'symbolic icon was not loaded'
    width = bind(B,'gdk_pixbuf_get_width',C.c_int,P)(pixbuf)
    height = bind(B,'gdk_pixbuf_get_height',C.c_int,P)(pixbuf)
    stride = bind(B,'gdk_pixbuf_get_rowstride',C.c_int,P)(pixbuf)
    channels = bind(B,'gdk_pixbuf_get_n_channels',C.c_int,P)(pixbuf)
    data = C.string_at(bind(B,'gdk_pixbuf_get_pixels',P,P)(pixbuf),stride*height)
    expected = rgb('WAYBAR_BUTTON_TRAY_NORMAL_ICON_COLOR')
    matches = sum(tuple(data[y*stride+x*channels:y*stride+x*channels+3])==expected
                  for y in range(height) for x in range(width))
    assert matches>3,('tray',layout,expected,matches)
    records.append({'layout':layout,'paint':'tray-symbolic','rgb':expected,'matching_pixels':matches})
    unref(pixbuf); unref(info); destroy(win); drain()
print(json.dumps({'native_gtk_icon_cases':len(records),'records':records}))
