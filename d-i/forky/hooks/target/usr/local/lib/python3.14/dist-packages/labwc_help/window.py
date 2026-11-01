"""Adaptive Help shell. Native widgets retain keyboard and accessibility support."""
from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from . import VERSION
from .catalog import Catalog, link_target
from .render import Reader, label
from .navigation import History
from .search import SearchIndex
from .state import StateStore, StateWriter


def button(icon, tooltip, callback):
    widget = Gtk.Button(tooltip_text=tooltip)
    if icon:
        widget.set_icon_name(icon)
    widget.connect('clicked', callback)
    return widget


def set_icon(widget, icon):
    widget.set_icon_name(icon or None)


class HelpWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Help', default_width=1060, default_height=760)
        self.icons = app.theme['icons']
        self.catalog = None
        self.current = ''
        self.history = History()
        self.state = None
        self.state_writer = None
        self.index = None
        self.query_source = 0
        self.toast = Adw.ToastOverlay()
        self.set_content(self.toast)
        self.split = Adw.NavigationSplitView()
        self.toast.set_child(self.split)
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 720sp'))
        breakpoint.add_setter(self.split, 'collapsed', True)
        self.add_breakpoint(breakpoint)
        self.set_size_request(320, 360)

        sidebar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title='Help', subtitle='Offline desktop guides'))
        sidebar.add_top_bar(header)
        self.search = Gtk.SearchEntry(placeholder_text='Search all guides', hexpand=True)
        self.search.set_tooltip_text('Search titles, keywords and article text (Ctrl+K)')
        self.search.connect('search-changed', self.search_changed)
        self.search.connect('activate', lambda _entry: self.open_first_result())
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=8, margin_end=8)
        nav.append(self.search)
        self.topics = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, activate_on_single_click=True)
        self.topics.add_css_class('navigation-sidebar')
        self.topics.connect('row-activated', self.row_activated)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.topics)
        nav.append(scroll)
        sidebar.set_content(nav)
        self.split.set_sidebar(Adw.NavigationPage.new(sidebar, 'Guides'))

        content = Adw.ToolbarView()
        self.header = Adw.HeaderBar()
        self.header.set_title_widget(Adw.WindowTitle(title='Help'))
        self.back_button = button(self.icons['back'], 'Back (Alt+Left)', lambda _b: self.action('back'))
        self.forward_button = button(self.icons['forward'], 'Forward (Alt+Right)', lambda _b: self.action('forward'))
        self.header.pack_start(self.back_button)
        self.header.pack_start(self.forward_button)
        self.header.pack_start(button(self.icons['home'], 'Home (Alt+Home)', lambda _b: self.open_topic('')))
        self.bookmark_button = button(self.icons['bookmark-empty'], 'Bookmark this guide (Ctrl+D)', lambda _b: self.action('bookmark'))
        self.header.pack_end(self.bookmark_button)
        menu = Gio.Menu()
        for title, action in [('Bookmarks', 'app.bookmarks'), ('Recent guides', 'app.recents'), ('Find in guide', 'app.find'), ('Copy selected text', 'app.copy'), ('Larger text', 'app.zoom-in'), ('Smaller text', 'app.zoom-out'), ('Reading preferences', 'app.preferences'), ('Keyboard shortcuts', 'app.shortcuts'), ('About Help', 'app.about')]:
            menu.append(title, action)
        menu_button = Gtk.MenuButton(menu_model=menu, tooltip_text='Help menu')
        if self.icons['menu']:
            menu_button.set_icon_name(self.icons['menu'])
        self.header.pack_end(menu_button)
        content.add_top_bar(self.header)
        self.breadcrumb = Gtk.Box(spacing=8, margin_start=16, margin_end=16)
        content.add_top_bar(self.breadcrumb)
        self.find_entry = Gtk.SearchEntry(placeholder_text='Find in this guide', visible=False)
        self.find_entry.set_tooltip_text('Find text in the current guide (Ctrl+F, Enter, Escape)')
        self.find_entry.connect('activate', lambda _e: self.find_in_article())
        self.find_entry.connect('stop-search', lambda _e: self.find_entry.set_visible(False))
        content.add_top_bar(self.find_entry)
        self.pages = Gtk.Stack(vexpand=True)
        loading = Adw.StatusPage(title='Loading offline guides…')
        if self.icons['application']:
            loading.set_icon_name(self.icons['application'])
        spinner = Gtk.Spinner(spinning=True)
        loading.set_child(spinner)
        self.pages.add_named(loading, 'loading')
        self.status = Adw.StatusPage()
        self.pages.add_named(self.status, 'status')
        self.reader = Reader(self.open_link, self.notify, self.icons['copy'], app.theme['list_marker'])
        self.article_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=850, tightening_threshold=600)
        clamp.set_child(self.reader)
        self.article_scroll.set_child(clamp)
        self.pages.add_named(self.article_scroll, 'reader')
        content.set_content(self.pages)
        self.split.set_content(Adw.NavigationPage.new(content, 'Help'))
        self.connect('close-request', self.closing)
        GLib.idle_add(self.load)

    def notify(self, message):
        self.toast.add_toast(Adw.Toast.new(message))

    def action(self, name):
        self.get_application().activate_action(name, None)

    def load(self):
        try:
            self.catalog = Catalog().load()
            self.index = SearchIndex(self.catalog)
            self.state = StateStore(set(self.catalog.articles))
            self.state_writer = StateWriter(self.state)
            self.history.entries = [tuple(item) for item in self.state.data['history']]
            self.history.position = self.state.data['history_position']
            self.set_default_size(self.state.data['width'], self.state.data['height'])
            if self.state.data['maximized']:
                self.maximize()
            self.apply_appearance()
            if self.state.error:
                self.notify(self.state.error)
            self.populate_sidebar()
            target = self.get_application().pending_topic or self.state.data['last_topic']
            previous = (self.history.entries[self.history.position]
                        if 0 <= self.history.position < len(self.history.entries) else None)
            self.open_topic(target, record=not (previous and previous[0] == target))
            if previous and previous[0] == target:
                self.restore_scroll(previous[1])
        except (OSError, ValueError, TypeError, KeyError):
            self.show_status('Help library unavailable', 'The installed documentation is missing or invalid. Reinstall the managed Help assets.', self.icons['error'])
        return GLib.SOURCE_REMOVE

    def show_status(self, title, description, icon=None):
        icon = icon or self.icons['application']
        self.status.set_title(title)
        self.status.set_description(description)
        self.status.set_icon_name(icon or None)
        self.pages.set_visible_child_name('status')
        self.split.set_show_content(True)

    def row(self, title, icon, target, summary='', query=''):
        row = Gtk.ListBoxRow()
        row.target = target
        box = Gtk.Box(spacing=10, margin_start=10, margin_end=10, margin_top=10, margin_bottom=10)
        if icon:
            box.append(Gtk.Image.new_from_icon_name(icon))
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        words.append(label(title, query=query) if query else Gtk.Label(label=title, xalign=0, wrap=True))
        if summary:
            sub = label(summary, query=query) if query else Gtk.Label(label=summary, xalign=0, wrap=True)
            sub.add_css_class('caption')
            words.append(sub)
        box.append(words)
        row.set_child(box)
        self.topics.append(row)
        return row

    def clear_sidebar(self):
        while child := self.topics.get_first_child():
            self.topics.remove(child)

    def populate_sidebar(self):
        if not self.catalog:
            return
        self.clear_sidebar()
        self.row('Home', self.icons['home'], '')
        self.row('Bookmarks', self.icons['bookmark'], '#bookmarks')
        self.row('Recent guides', self.icons['recents'], '#recents')
        for cid, category in sorted(self.catalog.categories.items(), key=lambda pair: pair[1]['order']):
            self.row(category['title'], category['icon'], '@' + cid)
            for article in sorted(self.catalog.articles.values(), key=lambda a: (a.order, a.title)):
                if article.category == cid:
                    self.row(article.title, article.icon, article.id)

    def row_activated(self, _box, row):
        self.open_topic(row.target)

    def open_first_result(self):
        row = self.topics.get_row_at_index(0)
        if row:
            self.open_topic(row.target)

    def open_topic(self, target, *, record=True):
        if not self.catalog:
            self.get_application().pending_topic = target
            return
        if record:
            self.history.visit(target, self.article_scroll.get_vadjustment().get_value())
        self.current = target
        self.back_button.set_sensitive(self.history.position > 0)
        self.forward_button.set_sensitive(self.history.position + 1 < len(self.history.entries))
        self.bookmark_button.set_sensitive(target in self.catalog.articles)
        set_icon(self.bookmark_button, self.icons['bookmark'] if self.state and target in self.state.data['bookmarks'] else self.icons['bookmark-empty'])
        while child := self.breadcrumb.get_first_child():
            self.breadcrumb.remove(child)
        home = Gtk.Button(label='Home', has_frame=False)
        home.connect('clicked', lambda _b: self.open_topic(''))
        self.breadcrumb.append(home)
        self.find_entry.set_visible(False)
        if not target:
            self.reader.clear()
            self.reader.append(label('Welcome to Help', css='title-1'))
            self.reader.append(label('Practical guides for your managed Debian desktop. All guides are available offline. Commands are displayed for you to review and copy; Help never runs them.'))
            self.reader.append(label('Featured guides', css='title-2'))
            self.article_buttons(self.catalog.featured)
            if self.state and self.state.data['recents']:
                self.reader.append(label('Recently viewed', css='title-2'))
                self.article_buttons(self.state.data['recents'])
            self.reader.append(label('Browse categories', css='title-2'))
            for cid, category in self.catalog.categories.items():
                item = Gtk.Button(label=category['title'], halign=Gtk.Align.FILL)
                item.connect('clicked', lambda _b, topic='@' + cid: self.open_topic(topic))
                self.reader.append(item)
        elif target in ('#bookmarks', '#recents'):
            field = target[1:]
            self.reader.clear()
            self.reader.append(label('Bookmarks' if field == 'bookmarks' else 'Recently viewed', css='title-1'))
            identifiers = self.state.data[field] if self.state else []
            if not identifiers:
                self.reader.append(label('No saved guides yet. Open a guide and press Ctrl+D to bookmark it.' if field == 'bookmarks' else 'No recent guides. Browse a category or search to get started.'))
            self.article_buttons(identifiers)
        elif target.startswith('@') and target[1:] in self.catalog.categories:
            cid = target[1:]
            self.reader.clear()
            self.reader.append(label(self.catalog.categories[cid]['title'], css='title-1'))
            self.article_buttons([a.id for a in sorted(self.catalog.articles.values(), key=lambda a: a.order) if a.category == cid])
        elif target in self.catalog.articles:
            article = self.catalog.articles[target]
            category = Gtk.Button(label=self.catalog.categories[article.category]['title'], has_frame=False)
            category.connect('clicked', lambda _b: self.open_topic('@' + article.category))
            self.breadcrumb.append(category)
            if article.error:
                self.show_status('Guide unavailable', article.error)
                return
            self.reader.show_article(article, self.catalog, size=self.state.data['text_size'] if self.state else 100)
            if self.state:
                self.state.data['last_topic'] = target
                self.state.data['recents'] = list(dict.fromkeys([target, *self.state.data['recents']]))[:self.state.data['recent_limit']]
            if article.related:
                self.reader.append(label('Related guides', css='title-2'))
                self.article_buttons(article.related)
            siblings = [a.id for a in sorted(self.catalog.articles.values(), key=lambda a: a.order) if a.category == article.category]
            position = siblings.index(target)
            if position:
                self.reader.append(label('Previous in this category', css='heading'))
                self.article_buttons([siblings[position - 1]])
            if position + 1 < len(siblings):
                self.reader.append(label('Next in this category', css='heading'))
                self.article_buttons([siblings[position + 1]])
        else:
            self.show_status('Guide not found', 'This topic may have been removed or renamed. Browse Home or search the current documentation.')
            return
        self.pages.set_visible_child_name('reader')
        self.article_scroll.get_vadjustment().set_value(0)
        self.split.set_show_content(True)
        self.persist(record_scroll=False)

    def article_buttons(self, identifiers):
        for identifier in identifiers:
            if identifier in self.catalog.articles:
                article = self.catalog.articles[identifier]
                item = Gtk.Button()
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
                box.append(Gtk.Label(label=article.title, xalign=0, wrap=True))
                box.append(Gtk.Label(label=article.summary, xalign=0, wrap=True))
                item.set_child(box)
                item.connect('clicked', lambda _b, topic=identifier: self.open_topic(topic))
                self.reader.append(item)

    def open_link(self, uri):
        try:
            kind = link_target(uri, self.catalog.articles)
            if kind == 'topic':
                self.open_topic(uri[5:])
            else:
                dialog = Adw.MessageDialog.new(self, 'External website', 'This link needs an internet connection. Copy the HTTPS address to open it in your browser.')
                dialog.set_extra_child(label(uri))
                dialog.add_response('cancel', 'Close')
                dialog.add_response('copy', 'Copy address')
                dialog.connect('response', lambda _d, response: self.reader.copy(uri) if response == 'copy' else None)
                dialog.present()
        except ValueError:
            self.notify('This link is invalid or unavailable')

    def search_changed(self, _entry):
        if self.query_source:
            GLib.source_remove(self.query_source)
        self.query_source = GLib.timeout_add(120, self.run_search)

    def run_search(self):
        self.query_source = 0
        if not self.catalog or not self.index:
            return GLib.SOURCE_REMOVE
        query = self.search.get_text()[:200].strip()
        if not query:
            self.populate_sidebar()
            return GLib.SOURCE_REMOVE
        results = self.index.search(query)
        self.clear_sidebar()
        for result in results:
            article = self.catalog.articles[result.id]
            self.row(article.title, article.icon, result.id, result.snippet, query)
        if self.topics.get_first_child() is None:
            row = self.row('No matching guides', self.icons['search'], '', 'Try fewer words, a component name, or browse Home.')
            row.set_activatable(False)
            row.set_selectable(False)
        return GLib.SOURCE_REMOVE

    def find_in_article(self):
        if not self.reader.find(self.find_entry.get_text()[:200]):
            self.notify('No matching text in this guide')

    def closing(self, _window):
        if self.query_source:
            GLib.source_remove(self.query_source)
            self.query_source = 0
        self.persist()
        return False

    def persist(self, *, record_scroll=True):
        if not self.state:
            return
        if record_scroll:
            self.history.remember(self.article_scroll.get_vadjustment().get_value())
        self.state.data['history'] = [[t, p] for t, p in self.history.entries if not t or t in self.catalog.articles]
        self.state.data['history_position'] = min(self.history.position, len(self.state.data['history']) - 1)
        # The allocated size records user resizing; default_size remains the
        # construction request and does not describe the current window.
        width, height = ((self.get_width(), self.get_height()) if not self.is_maximized()
                         else (self.state.data['width'], self.state.data['height']))
        self.state.data.update(width=max(320, min(width, 3840)), height=max(360, min(height, 2160)), maximized=self.is_maximized())
        if not self.state_writer.submit():
            self.notify(self.state.error)

    def navigate(self, delta):
        entry = self.history.move(delta, self.article_scroll.get_vadjustment().get_value())
        if entry:
            self.open_topic(entry[0], record=False)
            self.restore_scroll(entry[1])

    def restore_scroll(self, value):
        def restore(_widget, _clock):
            adjustment = self.article_scroll.get_vadjustment()
            adjustment.set_value(min(value, max(0, adjustment.get_upper() - adjustment.get_page_size())))
            return GLib.SOURCE_REMOVE
        self.article_scroll.add_tick_callback(restore)

    def toggle_bookmark(self):
        if not self.state or self.current not in self.catalog.articles:
            return
        bookmarks = self.state.data['bookmarks']
        if self.current in bookmarks:
            bookmarks.remove(self.current)
            self.notify('Bookmark removed')
        else:
            bookmarks.append(self.current)
            self.notify('Guide bookmarked')
        set_icon(self.bookmark_button, self.icons['bookmark'] if self.current in bookmarks else self.icons['bookmark-empty'])
        self.persist()

    def zoom(self, amount):
        if self.state:
            self.state.data['text_size'] = max(80, min(180, self.state.data['text_size'] + amount))
            scroll = self.article_scroll.get_vadjustment().get_value()
            self.open_topic(self.current, record=False)
            self.restore_scroll(scroll)

    def apply_appearance(self):
        choice = self.state.data['appearance']
        Adw.StyleManager.get_default().set_color_scheme({'system': Adw.ColorScheme.DEFAULT, 'light': Adw.ColorScheme.FORCE_LIGHT, 'dark': Adw.ColorScheme.FORCE_DARK}[choice])

    def preferences(self):
        if not self.state:
            return
        dialog = Adw.PreferencesWindow(transient_for=self, modal=True, title='Reading preferences')
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title='Reading and privacy')
        appearance = Adw.ComboRow(title='Appearance', model=Gtk.StringList.new(['System preference', 'Light', 'Dark']))
        appearance.set_selected(['system', 'light', 'dark'].index(self.state.data['appearance']))
        def changed(row, _property):
            self.state.data['appearance'] = ['system', 'light', 'dark'][row.get_selected()]
            self.apply_appearance()
            self.persist()
        appearance.connect('notify::selected', changed)
        group.add(appearance)
        recent = Adw.SpinRow.new_with_range(0, 50, 1)
        recent.set_title('Maximum recent guides (0 disables recording)')
        recent.set_value(self.state.data['recent_limit'])
        def recent_changed(row, _property):
            self.state.data['recent_limit'] = int(row.get_value())
            self.state.data['recents'] = self.state.data['recents'][:int(row.get_value())]
            self.persist()
        recent.connect('notify::value', recent_changed)
        group.add(recent)
        clear = Adw.ActionRow(title='Clear reading history', subtitle='Bookmarks are retained')
        clear_button = Gtk.Button(label='Clear', valign=Gtk.Align.CENTER)
        def clear_history(_button):
            self.state.data['recents'] = []
            self.state.data['last_topic'] = ''
            self.history = History()
            self.persist()
            self.notify('Reading history cleared')
        clear_button.connect('clicked', clear_history)
        clear.add_suffix(clear_button)
        group.add(clear)
        page.add(group)
        dialog.add(page)
        dialog.present()

    def about(self):
        dialog = Adw.AboutWindow(transient_for=self, modal=True, application_name='Help',
                                 application_icon=self.icons['application'] or None, developer_name='Labwc Desktop', version=VERSION,
                                 comments='Offline help for the managed Debian Forky desktop.')
        dialog.present()
