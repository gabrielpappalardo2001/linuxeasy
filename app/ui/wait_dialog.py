from gi.repository import Gtk, Gdk

class WaitDialog(Gtk.Window):
    def __init__(self, parent_window, title="Caricamento"):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        if parent_window:
            self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_title(title)
        self.set_default_size(300, 120)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        self.add(box)

        self.label = Gtk.Label(label="Attendere...")
        box.pack_start(self.label, True, True, 0)

        self.connect("key-press-event", self.on_key_press)
        self.show_all()

    def on_key_press(self, widget, event):
        keyname = Gdk.keyval_name(event.keyval)
        if keyname in ("Up", "Down", "Left", "Right", "Return", "KP_Enter", "space"):
            self.label.set_text("Attendere...")
            return True
        return True
