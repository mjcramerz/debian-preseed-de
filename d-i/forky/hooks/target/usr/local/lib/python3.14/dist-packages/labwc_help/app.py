"""Single-instance GApplication and fixed, validated command-line deep links."""
from __future__ import annotations

import os
import sys
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk

from . import APP_ID, VERSION
from .catalog import TOPIC
from .window import HelpWindow
from .theme import load as load_theme


def parse_arguments(arguments: list[str]) -> str:
    if not arguments:
        return ''
    if len(arguments) == 2 and arguments[0] == '--topic' and len(arguments[1]) <= 100 and TOPIC.fullmatch(arguments[1]):
        return arguments[1]
    raise ValueError('Usage: labwc-help [--topic CATEGORY.TOPIC]')


class HelpApplication(Adw.Application):
    def __init__(self, theme):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self.pending_topic = ''
        self.theme = theme

    def do_startup(self):
        Adw.Application.do_startup(self)
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property('gtk-font-name', self.theme['font_family'] + ' 11')
        for name in ('home', 'back', 'forward', 'search', 'find', 'bookmark', 'bookmarks', 'recents', 'zoom-in', 'zoom-out', 'preferences', 'copy', 'shortcuts', 'about', 'quit'):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _a, _p, chosen=name: self.dispatch(chosen))
            self.add_action(action)
        for name, accelerators in {'home': ['<Alt>Home'], 'back': ['<Alt>Left'], 'forward': ['<Alt>Right'], 'search': ['<Primary>k', '<Primary>l'], 'find': ['<Primary>f'], 'bookmark': ['<Primary>d'], 'zoom-in': ['<Primary>plus', '<Primary>equal'], 'zoom-out': ['<Primary>minus'], 'shortcuts': ['F1'], 'quit': ['<Primary>q', '<Primary>w']}.items():
            self.set_accels_for_action('app.' + name, accelerators)

    def do_command_line(self, command):
        try:
            self.pending_topic = parse_arguments(command.get_arguments()[1:])
        except ValueError:
            return 2
        self.activate()
        if self.window.catalog and self.pending_topic:
            self.window.open_topic(self.pending_topic)
        return 0

    def do_activate(self):
        if self.window is None:
            self.window = HelpWindow(self)
        self.window.present()

    def dispatch(self, name):
        window = self.window
        if not window:
            return
        if name == 'home':
            window.open_topic('')
        elif name == 'search':
            window.split.set_show_content(False)
            window.search.grab_focus()
        elif name == 'find':
            window.find_entry.set_visible(True)
            window.find_entry.grab_focus()
        elif name == 'copy':
            window.reader.copy_selection()
        elif name == 'about':
            window.about()
        elif name == 'back':
            window.navigate(-1)
        elif name == 'forward':
            window.navigate(1)
        elif name == 'bookmark':
            window.toggle_bookmark()
        elif name in ('bookmarks', 'recents'):
            window.open_topic('#' + name)
        elif name == 'zoom-in':
            window.zoom(10)
        elif name == 'zoom-out':
            window.zoom(-10)
        elif name == 'preferences':
            window.preferences()
        elif name == 'shortcuts':
            dialog = Adw.MessageDialog.new(window, 'Keyboard shortcuts', 'Ctrl+K: search guides\nAlt+Left / Right: history\nAlt+Home: home\nCtrl+F: find in guide\nCtrl+D: bookmark\nCtrl++ / Ctrl+-: text size\nCtrl+C: copy selection\nTab / Shift+Tab: move focus\nEnter: open focused item\nCtrl+Q: close Help')
            dialog.add_response('close', 'Close')
            dialog.present()
        elif name == 'quit':
            window.close()


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ['--version']:
        print('Help ' + VERSION)
        return 0
    if arguments == ['--help']:
        print('Usage: labwc-help [--topic CATEGORY.TOPIC]')
        return 0
    parse_arguments(arguments)
    if os.geteuid() == 0:
        raise ValueError('Help must run as the desktop user')
    os.umask(0o077)
    GLib.set_application_name('Help')
    theme = load_theme()
    return HelpApplication(theme).run(['labwc-help', *arguments])
