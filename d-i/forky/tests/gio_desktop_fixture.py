"""Test-only C ABI adapter for hosts without PyGObject; never installed.

This calls the real libgio XDG/parser/launch implementation, not a substitute
indexer. PyGObject integration has a separate capability-gated test. Each probe
runs in a fresh, unprivileged process, as the production menu workers do.
"""
import ctypes as C
import json
import locale
from pathlib import Path
import sys
import types


def load_api():
    gio = C.CDLL('libgio-2.0.so.0')
    glib = C.CDLL('libglib-2.0.so.0')
    gobject = C.CDLL('libgobject-2.0.so.0')
    pointer = C.c_void_p

    def bind(library, name, result, *arguments):
        function = getattr(library, name)
        function.restype = result
        function.argtypes = list(arguments)
        return function

    class GList(C.Structure):
        pass
    GList._fields_ = [('data', pointer), ('next', C.POINTER(GList)), ('prev', C.POINTER(GList))]
    class GError(C.Structure):
        _fields_ = [('domain', C.c_uint), ('code', C.c_int), ('message', C.c_char_p)]

    get_all = bind(gio, 'g_app_info_get_all', C.POINTER(GList))
    new = bind(gio, 'g_desktop_app_info_new', pointer, C.c_char_p)
    new_context = bind(gio, 'g_app_launch_context_new', pointer)
    unref = bind(gobject, 'g_object_unref', None, pointer)
    free = bind(glib, 'g_free', None, pointer)
    free_list = bind(glib, 'g_list_free', None, C.POINTER(GList))
    free_error = bind(glib, 'g_error_free', None, C.POINTER(GError))
    get_string = bind(gio, 'g_desktop_app_info_get_string', pointer, pointer, C.c_char_p)
    functions = {}
    for method, function in (
            ('get_id', 'g_app_info_get_id'), ('get_display_name', 'g_app_info_get_display_name'),
            ('get_filename', 'g_desktop_app_info_get_filename'),
            ('get_categories', 'g_desktop_app_info_get_categories')):
        functions[method] = bind(gio, function, C.c_char_p, pointer)
    hidden = bind(gio, 'g_desktop_app_info_get_is_hidden', C.c_int, pointer)
    shown = bind(gio, 'g_app_info_should_show', C.c_int, pointer)
    launch = bind(gio, 'g_app_info_launch', C.c_int, pointer, pointer, pointer, C.POINTER(C.POINTER(GError)))

    class DesktopAppInfo:
        def __init__(self, address): self.address = address
        def __del__(self):
            if self.address: unref(self.address)
        @staticmethod
        def new(desktop_id):
            address = new(desktop_id.encode('utf-8'))
            return DesktopAppInfo(address) if address else None
        def get_string(self, key):
            address = get_string(self.address, key.encode('utf-8'))
            if not address: return None
            try: return C.string_at(address).decode('utf-8')
            finally: free(address)
        def get_is_hidden(self): return bool(hidden(self.address))
        def should_show(self): return bool(shown(self.address))
        def launch(self, files, context):
            assert files == [], 'fixture supports the menu no-file launch only'
            error = C.POINTER(GError)()
            if not launch(self.address, None, context.address, C.byref(error)):
                message = error.contents.message.decode('utf-8') if error else 'GIO launch failed'
                if error: free_error(error)
                raise RuntimeError(message)
            return True

    def string_method(function):
        def method(self):
            value = function(self.address)
            return value.decode('utf-8') if value else None
        return method
    for method, function in functions.items(): setattr(DesktopAppInfo, method, string_method(function))

    class AppInfo:
        @staticmethod
        def get_all():
            head = get_all(); cursor = head; result = []
            while cursor:
                result.append(DesktopAppInfo(cursor.contents.data))
                cursor = cursor.contents.next
            free_list(head)
            return result
    class AppLaunchContext:
        def __init__(self): self.address = new_context()
        def __del__(self): unref(self.address)
    return types.SimpleNamespace(AppInfo=AppInfo, AppLaunchContext=AppLaunchContext), DesktopAppInfo


def main():
    path = Path(sys.argv[1])
    module = types.ModuleType('fixture_main_menu'); module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    arguments = sys.argv[2:]
    if arguments[-1:] == ['--ctypes']:
        arguments = arguments[:-1]
        def api():
            module.prepare_environment()
            locale.setlocale(locale.LC_ALL, '')
            return load_api()
        module.gio_api = api
    return module.main(arguments)


if __name__ == '__main__':
    raise SystemExit(main())
