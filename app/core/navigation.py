import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, Atk

class NavigationManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.stack = []
        self.current_view = None

    def push_view(self, view):
        if self.current_view:
            self.stack.append(self.current_view)
        self.set_view(view)

    def pop_view(self):
        if self.stack:
            previous_view = self.stack.pop()
            self.set_view(previous_view)
            return True
        return False

    def set_view(self, view):
        if self.current_view and hasattr(self.current_view, "widget"):
            self.main_window.container.remove(self.current_view.widget)
        self.current_view = view
        self.main_window.container.add(view.widget)
        self.main_window.container.show_all()
        if hasattr(view, "focus_default"):
            view.focus_default()

    def handle_key_press(self, widget, event):
        keyval = event.keyval
        
        if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            return True
            
        if keyval == Gdk.KEY_F6:
            self.main_window.open_control_center()
            return True

        if keyval == Gdk.KEY_Escape:
            if not self.pop_view():
                self.main_window.handle_escape_exit()
            return True

        if keyval in (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R):
            if self.current_view and hasattr(self.current_view, "open_context_menu"):
                self.current_view.open_context_menu()
                return True

        return False

    def setup_accessible_menu(self, listbox, menu_items):
        accessible_list = listbox.get_accessible()
        accessible_list.set_role(Atk.Role.MENU)
        
        for item in menu_items:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=item["title"])
            label.set_xalign(0)
            row.add(label)
            row.user_data = item
            
            accessible_row = row.get_accessible()
            accessible_row.set_role(Atk.Role.MENU_ITEM)
            
            listbox.add(row)