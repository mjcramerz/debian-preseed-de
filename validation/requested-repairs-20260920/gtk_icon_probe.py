import ctypes as C
from ctypes import c_void_p as P,c_char_p as S,c_int as I,c_uint as U
from pathlib import Path
import re,shutil,time
root=Path(__file__).resolve().parents[2] / 'd-i/forky/hooks/target/etc/skel-desktop/.config/waybar'
import tempfile
probe_directory=tempfile.TemporaryDirectory(prefix='repair-icons-')
out=Path(probe_directory.name)
shutil.copytree(root/'icons',out/'icons',dirs_exist_ok=True)
s=re.sub(r'__INSTALLER_[A-Z0-9_]+__','15',(root/'style.css.tmpl').read_text())
(out/'style.css').write_text(s)
gtk=C.CDLL('libgtk-3.so.0');gobj=C.CDLL('libgobject-2.0.so.0');pix=C.CDLL('libgdk_pixbuf-2.0.so.0')
def fn(lib,name,result,args):
    f=getattr(lib,name); f.restype=result; f.argtypes=args; return f
init=fn(gtk,'gtk_init_check',I,[P,P]); assert init(None,None)
provider=fn(gtk,'gtk_css_provider_new',P,[])()
load=fn(gtk,'gtk_css_provider_load_from_path',I,[P,S,C.POINTER(P)])
error=P(); assert load(provider,str(out/'style.css').encode(),C.byref(error)),error
windownew=fn(gtk,'gtk_offscreen_window_new',P,[])
labelnew=fn(gtk,'gtk_label_new',P,[S]);setname=fn(gtk,'gtk_widget_set_name',None,[P,S])
setsize=fn(gtk,'gtk_widget_set_size_request',None,[P,I,I]);add=fn(gtk,'gtk_container_add',None,[P,P])
ctx=fn(gtk,'gtk_widget_get_style_context',P,[P]);addprovider=fn(gtk,'gtk_style_context_add_provider',None,[P,P,U])
show=fn(gtk,'gtk_widget_show_all',None,[P]); events=fn(gtk,'gtk_events_pending',I,[])
iterate=fn(gtk,'gtk_main_iteration',I,[]); get=fn(gtk,'gtk_offscreen_window_get_pixbuf',P,[P])
save=fn(pix,'gdk_pixbuf_savev',I,[P,S,S,P,P,C.POINTER(P)])
state=fn(gtk,'gtk_widget_set_state_flags',None,[P,I,I]);destroy=fn(gtk,'gtk_widget_destroy',None,[P])
for name in ('apps','wayscriber'):
  for hover in (False,True):
    w=windownew(); l=labelnew(b' ');setname(l,('custom-'+name).encode())
    setsize(l,48,40);addprovider(ctx(l),provider,600);add(w,l)
    if hover: state(l,2,1)
    show(w)
    for i in range(10):
      while events():iterate()
      time.sleep(.02)
    image=get(w); assert image
    output=out/(name+('-hover' if hover else '')+'.png')
    assert save(image,str(output).encode(),b'png',None,None,C.byref(error))
    blank=fn(gtk,'gtk_css_provider_new',P,[])()
    rule = ('#custom-'+name+(':hover' if hover else '')+' { background-image: '+
            ('linear-gradient(135deg, rgba(236, 184, 96, 0.92), rgba(242, 159, 103, 0.92))' if hover else 'none')+
            '; background-size: 100% 100%; }')
    load_data=fn(gtk,'gtk_css_provider_load_from_data',I,[P,S,C.c_ssize_t,C.POINTER(P)])
    assert load_data(blank,rule.encode(),-1,C.byref(error))
    addprovider(ctx(l),blank,601)
    for i in range(10):
      while events():iterate()
      time.sleep(.02)
    image=get(w)
    assert save(image,str(output.with_name(output.stem+'-baseline.png')).encode(),b'png',None,None,C.byref(error))
    destroy(w)
print('GTK 3 parsed full rendered CSS and rendered both symbolic icons in normal and hover states.')
from PIL import Image
for path in sorted(p for p in out.glob('*.png') if 'baseline' not in p.stem):
  im=Image.open(path).convert('RGB')
  bg=Image.open(path.with_name(path.stem+'-baseline.png')).convert('RGB')
  points=[(x,y) for y in range(im.height) for x in range(im.width)
          if sum(abs(a-b) for a,b in zip(im.getpixel((x,y)),bg.getpixel((x,y))))>36]
  if not points: raise AssertionError(f'No foreground pixels: {path}')
  box=(min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points))
  dx=(box[0]+box[2]+1-im.width)/2;dy=(box[1]+box[3]+1-im.height)/2
  print(path.name,'size=',im.size,'foreground_bbox=',box,'center_offset=',(dx,dy))
  assert abs(dx)<=1 and abs(dy)<=1,(path,dx,dy)
