"""Exercise real GTK icon-theme painting with synthetic, not bundled app artwork.

Arguments: rendered CSS, scale. XDG_DATA_HOME contains the fixture hicolor theme.
Never contacts Waybar, a session manager, or any power endpoint.
"""
import ctypes as C
import ctypes.util
import json
from pathlib import Path
import sys

P=C.c_void_p
G=C.CDLL(ctypes.util.find_library('gtk-3'))
D=C.CDLL(ctypes.util.find_library('gdk-3'))
O=C.CDLL(ctypes.util.find_library('gobject-2.0'))
R=C.CDLL(ctypes.util.find_library('cairo'))


def bind(lib,name,result,*args):
    f=getattr(lib,name);f.restype=result;f.argtypes=list(args);return f


class Error(C.Structure):
    _fields_=[('domain',C.c_uint),('code',C.c_int),('message',C.c_char_p)]


# This matches the installer's display-independent native icon decoding check.
new_theme=bind(G,'gtk_icon_theme_new',P)
custom_theme=bind(G,'gtk_icon_theme_set_custom_theme',None,P,C.c_char_p)
has_icon=bind(G,'gtk_icon_theme_has_icon',C.c_int,P,C.c_char_p)
load_icon=bind(G,'gtk_icon_theme_load_icon',P,P,C.c_char_p,C.c_int,C.c_int,C.POINTER(C.POINTER(Error)))
unref=bind(O,'g_object_unref',None,P)
icons={'app-terminal':('foot',(23,217,71)), 'app-files':('org.xfce.thunar',(35,145,247)),
       'app-tuta':('tuta-mail',(179,27,198)), 'app-notes':('featherpad',(47,226,211)),
       'app-sleek':('sleek',(230,72,174))}
theme=new_theme();custom_theme(theme,b'hicolor')
for icon,_ in icons.values():
    assert has_icon(theme,icon.encode()),icon
    error=C.POINTER(Error)()
    image=load_icon(theme,icon.encode(),32,16,C.byref(error))  # FORCE_SIZE
    assert image and not error,(icon,error.contents.message if error else None)
    unref(image)
unref(theme)
assert bind(G,'gtk_init_check',C.c_int,P,P)(None,None)
screen=bind(D,'gdk_screen_get_default',P)()
provider=bind(G,'gtk_css_provider_new',P)()
css=Path(sys.argv[1]).read_bytes()+b'\n* { transition: none; }\n'
error=C.POINTER(Error)()
assert bind(G,'gtk_css_provider_load_from_data',C.c_int,P,C.c_char_p,C.c_ssize_t,C.POINTER(C.POINTER(Error)))(provider,css,len(css),C.byref(error)), error.contents.message
bind(G,'gtk_style_context_add_provider_for_screen',None,P,P,C.c_uint)(screen,provider,600)
window_new=bind(G,'gtk_window_new',P,C.c_int)
box_new=bind(G,'gtk_box_new',P,C.c_int,C.c_int)
label_new=bind(G,'gtk_label_new',P,C.c_char_p)
name=bind(G,'gtk_widget_set_name',None,P,C.c_char_p)
context=bind(G,'gtk_widget_get_style_context',P,P)
add_class=bind(G,'gtk_style_context_add_class',None,P,C.c_char_p)
state=bind(G,'gtk_widget_set_state_flags',None,P,C.c_int,C.c_int)
add=bind(G,'gtk_container_add',None,P,P)
show=bind(G,'gtk_widget_show_all',None,P)
destroy=bind(G,'gtk_widget_destroy',None,P)
pending=bind(G,'gtk_events_pending',C.c_int)
iterate=bind(G,'gtk_main_iteration',C.c_int)
render=bind(G,'gtk_render_background',None,P,P,C.c_double,C.c_double,C.c_double,C.c_double)
surface_new=bind(R,'cairo_image_surface_create',P,C.c_int,C.c_int,C.c_int)
scale_surface=bind(R,'cairo_surface_set_device_scale',None,P,C.c_double,C.c_double)
cairo_new=bind(R,'cairo_create',P,P)
cairo_destroy=bind(R,'cairo_destroy',None,P)
flush=bind(R,'cairo_surface_flush',None,P)
surface_destroy=bind(R,'cairo_surface_destroy',None,P)
stride=bind(R,'cairo_image_surface_get_stride',C.c_int,P)
pixels=bind(R,'cairo_image_surface_get_data',P,P)
scale=int(sys.argv[2]);records=[]
for layout in ('external','internal'):
    for hover in (False,True):
        window=window_new(0);name(window,b'waybar');add_class(context(window),layout.encode())
        box=box_new(0,0);add(window,box)
        labels=[]
        for module,(icon,color) in icons.items():
            label=label_new(b' ');name(label,('custom-'+module).encode())
            state(label,2 if hover else 0,True);add(box,label);labels.append((label,icon,color))
        show(window)
        while pending():iterate()
        for label,icon,expected in labels:
            surface=surface_new(0,80*scale,40*scale);scale_surface(surface,scale,scale)
            cr=cairo_new(surface);render(context(label),cr,0,0,80,40);flush(surface)
            raw=C.string_at(pixels(surface),stride(surface)*40*scale)
            offset=20*scale*stride(surface)+40*scale*4
            # ARGB32 is native-endian, little endian on both supported test hosts.
            pixel=int.from_bytes(raw[offset:offset+4],sys.byteorder)
            actual=((pixel>>16)&255,(pixel>>8)&255,pixel&255)
            assert actual==expected,(layout,hover,icon,actual,expected)
            records.append({'layout':layout,'hover':hover,'icon':icon,'rgb':actual,'scale':scale})
            cairo_destroy(cr);surface_destroy(surface)
        destroy(window)
        while pending():iterate()
unref(provider)
print(json.dumps({'native_icon_paint_cases':len(records),'records':records}))
