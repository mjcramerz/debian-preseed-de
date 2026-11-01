"""Native selectable article widgets; escaped markup and explicit link routing."""
from __future__ import annotations

from html import escape
import re
from gi.repository import Gtk

from .catalog import INLINE


def highlight(source: str, query: str) -> str:
    if not query:
        return escape(source)
    return ''.join(('<b><u>' + escape(part) + '</u></b>') if i % 2 else escape(part)
                   for i, part in enumerate(re.split('(' + re.escape(query) + ')', source, flags=re.I)))


def markup(source: str, query: str = '') -> str:
    """Only this finite grammar emits markup; raw HTML/Pango stays literal."""
    result, offset = [], 0
    for match in INLINE.finditer(source):
        result.append(highlight(source[offset:match.start()], query))
        label, uri, bold, italic, code = match.groups()
        if uri:
            result.append(f'<a href="{escape(uri, quote=True)}">{highlight(label, query)}</a>')
        else:
            tag, value = ('b', bold) if bold else ('i', italic) if italic else ('tt', code)
            result.append(f'<{tag}>{highlight(value, query)}</{tag}>')
        offset = match.end()
    result.append(highlight(source[offset:], query))
    return ''.join(result)


def label(source: str, *, css: str = '', query: str = '', activate=None) -> Gtk.Label:
    widget = Gtk.Label(xalign=0, wrap=True, selectable=True, hexpand=True)
    widget.set_markup(markup(source, query))
    widget.set_wrap_mode(2)  # Pango.WrapMode.WORD_CHAR, including long command names.
    if css:
        widget.add_css_class(css)
    # Never allow GTK's default external URI launch, even for headings/snippets.
    widget.connect('activate-link', lambda _widget, uri: (activate(uri) if activate else None, True)[1])
    return widget


class Reader(Gtk.Box):
    def __init__(self, activate, notify, copy_icon, list_marker):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                         margin_top=24, margin_bottom=32, margin_start=24, margin_end=24)
        self.activate = activate
        self.notify = notify
        self.copy_icon = copy_icon
        self.list_marker = list_marker
        self.text_widgets: list[Gtk.Widget] = []
        self.matches = []
        self.match_query = ''
        self.match_index = -1

    def clear(self) -> None:
        while child := self.get_first_child():
            self.remove(child)
        self.text_widgets = []
        self.matches = []
        self.match_query = ''
        self.match_index = -1

    def show_article(self, article, catalog, query: str = '', size: int = 100) -> None:
        self.clear()
        self.append(label(article.title, css='title-1'))
        self.append(label(f"{catalog.categories[article.category]['title']} · Updated {article.updated} · Offline guide", css='dim-label'))
        self.append(label(article.summary, css='heading'))
        for block in article.blocks:
            kind = block['type']
            if kind == 'image':
                picture = Gtk.Picture.new_for_filename(str(catalog.root / block['path']))
                picture.set_can_shrink(True)
                picture.set_alternative_text(block['alt'])
                self.append(picture)
                self.append(label(block['alt'], css='caption'))
            elif kind == 'code':
                container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                toolbar = Gtk.Box(spacing=8)
                toolbar.append(label('Command / code (review before running)', css='caption'))
                copy = Gtk.Button(tooltip_text='Copy this code block')
                if self.copy_icon:
                    copy.set_icon_name(self.copy_icon)
                copy.connect('clicked', lambda _button, value=block['text']: self.copy(value))
                toolbar.append(copy)
                container.append(toolbar)
                view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                    cursor_visible=True, accepts_tab=False, left_margin=12, right_margin=12,
                                    top_margin=12, bottom_margin=12)
                view.get_buffer().set_text(block['text'])
                container.append(view)
                container.add_css_class('card')
                self.text_widgets.append(view)
                self.append(container)
            else:
                prefix = self.list_marker + ' ' if self.list_marker else ''
                sources = [prefix + item for item in block['items']] if kind == 'list' else [block['text']]
                for source in sources:
                    css = 'title-2' if kind == 'heading' and block['level'] == 2 else 'title-3' if kind == 'heading' else 'warning' if kind == 'warning' else ''
                    widget = label(source, css=css, query=query, activate=self.activate)
                    widget.set_attributes(self._attributes(widget, size))
                    self.text_widgets.append(widget)
                    self.append(widget)

    @staticmethod
    def _attributes(widget, size):
        from gi.repository import Pango
        attributes = widget.get_attributes().copy() if widget.get_attributes() else Pango.AttrList()
        attributes.insert(Pango.attr_scale_new(size / 100))
        return attributes

    def copy(self, source: str) -> None:
        self.get_clipboard().set(source)
        self.notify('Copied to clipboard')

    def copy_selection(self) -> None:
        for widget in self.text_widgets:
            if isinstance(widget, Gtk.Label):
                selected, start, end = widget.get_selection_bounds()
                if selected:
                    self.copy(widget.get_text()[start:end])
                    return
            elif isinstance(widget, Gtk.TextView):
                buffer = widget.get_buffer()
                # PyGObject strips TextBuffer's boolean result; an empty
                # tuple means no selection. Label retains its boolean.
                bounds = buffer.get_selection_bounds()
                if bounds:
                    start, end = bounds
                    self.copy(buffer.get_text(start, end, True))
                    return

    def find(self, query: str, backwards: bool = False) -> bool:
        if not query:
            return False
        if query != self.match_query:
            self.match_query, self.match_index, self.matches = query, -1, []
            for widget in self.text_widgets:
                source = widget.get_text() if isinstance(widget, Gtk.Label) else widget.get_buffer().get_text(*widget.get_buffer().get_bounds(), True)
                for match in re.finditer(re.escape(query), source, re.I):
                    self.matches.append((widget, match.start(), match.end()))
        if not self.matches:
            return False
        self.match_index = (self.match_index + (-1 if backwards else 1)) % len(self.matches)
        widget, start, end = self.matches[self.match_index]
        if isinstance(widget, Gtk.Label):
            widget.select_region(start, end)
        else:
            buffer = widget.get_buffer()
            buffer.select_range(buffer.get_iter_at_offset(start), buffer.get_iter_at_offset(end))
        widget.grab_focus()
        return True
