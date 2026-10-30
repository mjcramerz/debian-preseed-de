"""GTK4 local reminder editor and manager."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys

import labwc_calendar_reminders as phone
import labwc_local_reminders as local

MANAGER_ACTIONS = frozenset({
    'pause-local', 'resume-local', 'pause-phone', 'resume-phone',
    'upcoming', 'overdue', 'complete-selected', 'edit-selected',
    'delete-selected', 'clear-expired',
})


def _request(arguments: list[str]) -> tuple[str, str | None]:
    """Validate each local or forwarded launch before touching reminder state."""
    if (len(arguments) not in {1, 2}
            or not all(isinstance(value, str) for value in arguments)):
        raise local.ReminderError('invalid reminder launch request')
    mode = arguments[0]
    action = arguments[1] if len(arguments) == 2 else None
    if (mode not in {'new', 'manager'}
            or (action is not None and (mode != 'manager' or action not in MANAGER_ACTIONS))):
        raise local.ReminderError('invalid reminder launch request')
    return mode, action


def failure_status(error: Exception) -> int:
    return 4 if (isinstance(error, local.OutcomeUnknown)
                 or getattr(error, 'code', None) == 'reminder-state-unknown') else 1


def notify(summary: str, body: str) -> None:
    """Best-effort post-commit feedback; a missing Mako bus never blocks UI state."""
    if (not os.access('/usr/bin/notify-send', os.X_OK)
            or not os.access('/usr/bin/timeout', os.X_OK)
            or not os.environ.get('DBUS_SESSION_BUS_ADDRESS')):
        return
    try:
        subprocess.run(
            ['/usr/bin/timeout', '--kill-after=1s', '3s', '/usr/bin/notify-send',
             '--app-name=Labwc Reminders', '--urgency=low',
             '--category=reminder.state', '--', summary, body],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def notification_text(value: object) -> str:
    return ''.join(character if character in '\n\t' or
                   (ord(character) >= 32 and not 0x7f <= ord(character) <= 0x9f
                    and not 0xd800 <= ord(character) <= 0xdfff) else ' '
                   for character in str(value))[:240]


def main(mode: str, action: str | None = None) -> int:
    if mode not in {'--new', '--manager'}:
        raise local.ReminderError('invalid reminder launch mode')
    arguments = [mode[2:]] + ([action] if action is not None else [])
    _request(arguments)
    try:
        import gi
        gi.require_version('Gio', '2.0')
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gio, Gtk
    except (ImportError, ValueError) as error:
        raise local.ReminderError('GTK4 PyGObject is required for local reminders') from error

    class ReminderWindow(Gtk.ApplicationWindow):
        def __init__(self, application, *, manager=None, item=None):
            title = 'Edit Local Reminder' if item else 'New Local Reminder'
            super().__init__(application=application, title=title)
            self.set_default_size(720, 620)
            self.set_size_request(560, 480)
            self.manager = manager
            self.item = item
            self.store = local.Store()
            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            root.set_margin_top(18)
            root.set_margin_bottom(18)
            root.set_margin_start(20)
            root.set_margin_end(20)
            self.set_child(root)
            heading = Gtk.Label(label=title)
            heading.set_xalign(0)
            heading.add_css_class('title-2')
            root.append(heading)
            grid = Gtk.Grid(column_spacing=14, row_spacing=10)
            root.append(grid)
            self.entries = {}
            defaults = item or {'title': '', 'body': '', 'due': '', 'timezone': 'Europe/Stockholm',
                                'first_minutes': 0, 'recurrence': 'none', 'sound': True,
                                'urgency': 'normal', 'allow_dnd': False}
            for row, (key, label, placeholder) in enumerate((
                    ('title', 'Title', 'Reminder title'),
                    ('due', 'Date and time', 'YYYY-MM-DD HH:MM±HH:MM'),
                    ('timezone', 'Timezone', 'Europe/Stockholm'))):
                grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
                entry = Gtk.Entry()
                entry.set_hexpand(True)
                entry.set_placeholder_text(placeholder)
                entry.set_text(str(defaults.get(key, '')))
                entry.set_max_length(512 if key == 'title' else 128)
                grid.attach(entry, 1, row, 2, 1)
                self.entries[key] = entry
            body_label = Gtk.Label(label='Body (optional)', xalign=0)
            root.append(body_label)
            body = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
            body.set_vexpand(True)
            body.get_buffer().set_text(str(defaults.get('body', '')))
            body_scroll = Gtk.ScrolledWindow()
            body_scroll.set_min_content_height(110)
            body_scroll.set_child(body)
            root.append(body_scroll)
            self.body = body

            controls = Gtk.Grid(column_spacing=14, row_spacing=10)
            root.append(controls)
            controls.attach(Gtk.Label(label='First reminder', xalign=0), 0, 0, 1, 1)
            first_values = [str(value) for value in local.FIRST_MINUTES]
            first_labels = ['At time' if value == 0 else
                            '1 hour before' if value == 60 else
                            f'{value // 60} hours before' if value % 60 == 0 else
                            f'{value} min before' for value in local.FIRST_MINUTES]
            first = Gtk.DropDown.new(Gtk.StringList.new(first_labels), None)
            first.set_selected(first_values.index(str(defaults.get('first_minutes', 0))))
            controls.attach(first, 1, 0, 2, 1)
            controls.attach(Gtk.Label(label='Repeat', xalign=0), 0, 1, 1, 1)
            recurrence_values = list(local.RECURRENCES)
            recurrence_labels = {key: label for key, label, _rule in phone.RECURRENCE_OPTIONS}
            recurrence = Gtk.DropDown.new(Gtk.StringList.new(
                [recurrence_labels[key] for key in recurrence_values]), None)
            recurrence.set_tooltip_text('Repeats keep the selected timezone\'s local time. '
                                        'Dates and times that do not exist are skipped.')
            recurrence.set_selected(recurrence_values.index(defaults.get('recurrence', 'none')))
            controls.attach(recurrence, 1, 1, 2, 1)
            controls.attach(Gtk.Label(label='Urgency', xalign=0), 0, 2, 1, 1)
            urgency_values = list(local.URGENCIES)
            urgency = Gtk.DropDown.new(Gtk.StringList.new(['Low', 'Normal', 'Critical']), None)
            urgency.set_selected(urgency_values.index(defaults.get('urgency', 'normal')))
            controls.attach(urgency, 1, 2, 2, 1)
            sound = Gtk.CheckButton(label='Play a sound')
            sound.set_active(bool(defaults.get('sound', True)))
            controls.attach(sound, 0, 3, 3, 1)
            allow_dnd = Gtk.CheckButton(label='Allow during Do not disturb')
            allow_dnd.set_active(bool(defaults.get('allow_dnd', False)))
            controls.attach(allow_dnd, 0, 4, 3, 1)
            self.first, self.first_values = first, first_values
            self.recurrence, self.recurrence_values = recurrence, recurrence_values
            self.urgency, self.urgency_values = urgency, urgency_values
            self.sound, self.allow_dnd = sound, allow_dnd

            footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            root.append(footer)
            self.status = Gtk.Label()
            self.status.set_xalign(0)
            self.status.set_wrap(True)
            self.status.set_hexpand(True)
            footer.append(self.status)
            cancel = Gtk.Button(label='Cancel')
            cancel.connect('clicked', lambda *_: self.close())
            footer.append(cancel)
            save = Gtk.Button(label='Save')
            save.add_css_class('suggested-action')
            save.connect('clicked', self._save)
            footer.append(save)

        def _fields(self) -> dict:
            buffer = self.body.get_buffer()
            body = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
            due_text = self.entries['due'].get_text().strip()
            timezone = self.entries['timezone'].get_text().strip()
            try:
                due = datetime.fromisoformat(due_text)
                if due.tzinfo is None:
                    due = local.localize(due, timezone)
                due_text = due.isoformat(timespec='minutes')
            except (ValueError, local.ReminderError, KeyError):
                raise local.ReminderError('enter a valid date/time with an offset or timezone') from None
            return {
                'title': self.entries['title'].get_text().strip(),
                'body': body,
                'due': due_text,
                'timezone': timezone,
                'first_minutes': int(self.first_values[self.first.get_selected()]),
                'recurrence': self.recurrence_values[self.recurrence.get_selected()],
                'sound': self.sound.get_active(),
                'urgency': self.urgency_values[self.urgency.get_selected()],
                'allow_dnd': self.allow_dnd.get_active(),
                'enabled': True,
                'link': self.item.get('link') if self.item else None,
            }

        def _save(self, *_args):
            try:
                values = self._fields()
                if self.item:
                    self.store.mutate('update', item=values, item_id=self.item['id'])
                else:
                    self.store.mutate('create', item=values)
                if self.manager and self.manager in self.get_application().get_windows():
                    self.manager.refresh()
                self.close()
            except (OSError, ValueError, local.ReminderError) as error:
                prefix = ('Reminder save outcome is unknown: ' if failure_status(error) == 4
                          else 'Reminder was not saved: ')
                self.status.set_text(prefix + str(error)[:240])

    class ManagerWindow(Gtk.ApplicationWindow):
        def __init__(self, application):
            super().__init__(application=application, title='Reminder Manager')
            self.set_default_size(920, 700)
            self.store = local.Store()
            self.view = 'all'
            self.selected_action = None
            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            root.set_margin_top(16)
            root.set_margin_bottom(16)
            root.set_margin_start(18)
            root.set_margin_end(18)
            self.set_child(root)
            toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            root.append(toolbar)
            new = Gtk.Button(label='New local reminder')
            new.connect('clicked', lambda *_: self.open_editor())
            toolbar.append(new)
            test = Gtk.Button(label='Test notification')
            test.connect('clicked', lambda *_: self.test_notification())
            toolbar.append(test)
            sound = Gtk.Button(label='Test sound')
            sound.connect('clicked', lambda *_: self.test_sound())
            toolbar.append(sound)
            clear = Gtk.Button(label='Clear paused')
            clear.connect('clicked', lambda *_: self.clear())
            toolbar.append(clear)
            self.expired_button = Gtk.Button(label='Clear expired')
            self.expired_button.connect('clicked', lambda *_: self.clear_expired())
            toolbar.append(self.expired_button)
            self.selected_button = Gtk.Button()
            self.selected_button.connect('clicked', lambda *_: self.apply_selected())
            toolbar.append(self.selected_button)
            self.status = Gtk.Label()
            self.status.set_xalign(0)
            self.status.set_hexpand(True)
            toolbar.append(self.status)
            scroll = Gtk.ScrolledWindow()
            scroll.set_vexpand(True)
            root.append(scroll)
            self.list_box = Gtk.ListBox()
            self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
            self.row_items = {}
            scroll.set_child(self.list_box)

        def apply_action(self, action=None) -> int:
            self.view = {'upcoming': 'upcoming', 'overdue': 'overdue'}.get(action, 'all')
            selected_labels = {'complete-selected': 'Complete selected',
                               'edit-selected': 'Edit selected',
                               'delete-selected': 'Delete selected'}
            self.selected_action = action if action in selected_labels else None
            self.selected_button.set_label(selected_labels.get(action, ''))
            self.selected_button.set_visible(self.selected_action is not None)
            self.expired_button.set_visible(action == 'clear-expired')
            if action in {'pause-local', 'resume-local', 'pause-phone', 'resume-phone'}:
                return self.apply_bulk_action(action)
            if action == 'clear-expired':
                return self.clear_expired()
            self.refresh()
            return 0

        def refresh(self):
            self.row_items.clear()
            while child := self.list_box.get_first_child():
                self.list_box.remove(child)
            try:
                items = self.store.filtered(self.view)
                delivery_statuses = self.store.delivery_statuses()
                for item in items:
                    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                    row.set_margin_top(7)
                    row.set_margin_bottom(7)
                    label = Gtk.Label(label=item['title'] + '\n' + item['due']
                                      + ('  (paused)' if not item['enabled'] else '')
                                      + ('  (delivery uncertain)' if delivery_statuses.get(item['id'])
                                         in {'reserved', 'outcome-unknown'} else ''))
                    if delivery_statuses.get(item['id']) in {'reserved', 'outcome-unknown'}:
                        label.set_tooltip_text('Delivery could not be confirmed and will not be retried '
                                               'automatically. Edit its date to schedule another attempt, '
                                               'or complete/delete this reminder.')
                    label.set_xalign(0)
                    label.set_hexpand(True)
                    row.append(label)
                    edit = Gtk.Button(label='Open')
                    edit.connect('clicked', lambda _button, value=item: self.open_editor(value))
                    row.append(edit)
                    toggle = Gtk.Button(label='Pause' if item['enabled'] else 'Resume')
                    toggle.connect('clicked', lambda _button, value=item: self.toggle(value))
                    row.append(toggle)
                    done = Gtk.Button(label='Complete')
                    done.connect('clicked', lambda _button, value=item: self.complete(value))
                    row.append(done)
                    delete = Gtk.Button(label='Delete')
                    delete.connect('clicked', lambda _button, value=item: self.delete(value))
                    row.append(delete)
                    list_row = Gtk.ListBoxRow()
                    list_row.set_selectable(True)
                    self.row_items[id(list_row)] = item
                    list_row.set_child(row)
                    self.list_box.append(list_row)
                self.status.set_text(f'{len(items)} local reminder(s)')
            except (OSError, ValueError, local.ReminderError) as error:
                self.status.set_text('Reminder state unavailable: ' + str(error)[:240])

        def apply_bulk_action(self, action) -> int:
            try:
                if action == 'pause-local':
                    count = self.store.set_all_enabled(False)
                    message = f'Paused {count} local reminder(s)'
                elif action == 'resume-local':
                    count = self.store.set_all_enabled(True)
                    message = f'Resumed {count} local reminder(s)'
                elif action in {'pause-phone', 'resume-phone'}:
                    with phone.Store(Path.home()) as remote:
                        remote.set_paused(action == 'pause-phone')
                    message = ('Paused all phone reminder delivery'
                               if action == 'pause-phone'
                               else 'Resumed phone reminder delivery')
                else:
                    raise local.ReminderError('unsupported bulk reminder action')
                self.refresh()
                self.status.set_text(message)
                notify('Reminder delivery updated', message + '.')
                return 0
            except (OSError, ValueError, local.ReminderError, phone.ReminderError) as error:
                result = failure_status(error)
                self.status.set_text(('Bulk reminder outcome unknown: ' if result == 4 else
                                      'Bulk reminder action failed: ') + str(error)[:240])
                return result

        def open_editor(self, item=None):
            window = ReminderWindow(self.get_application(), manager=self, item=item)
            window.set_transient_for(self)
            window.present()

        def toggle(self, item):
            try:
                updated = self.store.mutate('set-enabled', item=not item['enabled'], item_id=item['id'])
                self.refresh()
                enabled = bool(updated.get('enabled')) if isinstance(updated, dict) else not item['enabled']
                title = (updated.get('title') if isinstance(updated, dict) else item.get('title', ''))
                notify('Reminder enabled' if enabled else 'Reminder paused',
                       f"Local reminder '{notification_text(title)}' is "
                       f"now {'enabled' if enabled else 'paused'}.")
            except (OSError, ValueError, local.ReminderError) as error:
                self.status.set_text(str(error)[:240])

        def complete(self, item):
            try:
                self.store.mutate('complete', item_id=item['id'])
                self.refresh()
            except (OSError, ValueError, local.ReminderError) as error:
                self.status.set_text(str(error)[:240])

        def delete(self, item):
            try:
                self.store.mutate('delete', item_id=item['id'])
                self.refresh()
            except (OSError, ValueError, local.ReminderError) as error:
                self.status.set_text(str(error)[:240])

        def clear(self):
            try:
                count = self.store.clear_paused()
                self.refresh()
                self.status.set_text(f'Cleared {count} paused reminder(s)')
            except (OSError, ValueError, local.ReminderError) as error:
                self.status.set_text(str(error)[:240])

        def clear_expired(self) -> int:
            try:
                count = self.store.clear_expired()
                self.refresh()
                self.status.set_text(f'Cleared {count} expired reminder(s)')
                notify('Expired reminders cleared', f'Cleared {count} expired reminder(s).')
                return 0
            except (OSError, ValueError, local.ReminderError) as error:
                self.status.set_text(str(error)[:240])
                return failure_status(error)

        def apply_selected(self):
            row = self.list_box.get_selected_row()
            item = self.row_items.get(id(row)) if row is not None else None
            if item is None:
                self.status.set_text('Select one reminder first.')
                return
            try:
                if self.selected_action == 'complete-selected':
                    self.store.mutate('complete', item_id=item['id'])
                    self.refresh()
                elif self.selected_action == 'delete-selected':
                    self.store.mutate('delete', item_id=item['id'])
                    self.refresh()
                elif self.selected_action == 'edit-selected':
                    self.open_editor(item)
            except (OSError, ValueError, local.ReminderError) as error:
                self.status.set_text(str(error)[:240])

        @staticmethod
        def test_notification():
            subprocess.run(['/usr/bin/notify-send', '-a', 'Labwc Reminders', 'Reminder test',
                            'Local reminder notifications are working.'], check=False, timeout=15)

        @staticmethod
        def test_sound():
            subprocess.run(['/usr/bin/paplay', '/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga'],
                           check=False, timeout=15)

    class ReminderApplication(Gtk.Application):
        def __init__(self):
            super().__init__(application_id='org.labwc.LocalReminders',
                             flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
            self.manager_window = None
            self.new_window = None
            self.connect('window-removed', self._window_removed)

        def _window_removed(self, _application, window):
            if window is self.manager_window:
                self.manager_window = None
            if window is self.new_window:
                self.new_window = None

        def _open_request(self, requested_mode, requested_action=None) -> int:
            if requested_mode == 'manager':
                if self.manager_window is None:
                    self.manager_window = ManagerWindow(self)
                window = self.manager_window
                result = window.apply_action(requested_action)
            else:
                if self.new_window is None:
                    self.new_window = ReminderWindow(self)
                window = self.new_window
                result = 0
            window.present()
            return result

        def do_command_line(self, command_line):
            try:
                requested_mode, requested_action = _request(command_line.get_arguments()[1:])
                return self._open_request(requested_mode, requested_action)
            except (OSError, ValueError, local.ReminderError, phone.ReminderError) as error:
                command_line.printerr_literal('Unable to open reminders: '
                                             + notification_text(error) + '\n')
                return failure_status(error)

        def do_activate(self):
            self._open_request('manager')

    return ReminderApplication().run([sys.argv[0], *arguments])
