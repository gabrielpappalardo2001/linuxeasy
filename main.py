import sys
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from app.ui.main_window import MainWindow

class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.linuxeasy.app")

    def do_activate(self):
        win = MainWindow(self)
        win.show_all()

if __name__ == "__main__":
    app = Application()
    app.run(sys.argv)
