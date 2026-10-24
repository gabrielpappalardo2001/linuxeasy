from app.core.log import installa_gestori_globali, scrivi_log

installa_gestori_globali()

import sys

try:
    from app.core import strumenti_youtube

    strumenti_youtube.prepara_ambiente()
except Exception as ex_strumenti:
    scrivi_log("main.prepara_ambiente_youtube", ex_strumenti)

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.linuxeasy.app")
        self.finestra_principale = None
        self.finestra_aggiornamento = None

    def do_activate(self):
        try:
            if self.finestra_principale is not None:
                self.finestra_principale.present()
                return
            if self.finestra_aggiornamento is not None:
                self.finestra_aggiornamento.present()
                return
            from app.core.updater import FinestraAggiornamento
            self.finestra_aggiornamento = FinestraAggiornamento(self, self.avvia_programma)
            self.finestra_aggiornamento.avvia()
        except Exception as ex:
            scrivi_log("Application.do_activate", ex)
            self.avvia_programma()

    def avvia_programma(self):
        try:
            if self.finestra_principale is None:
                from app.ui.main_window import MainWindow
                self.finestra_principale = MainWindow(self)
                self.finestra_principale.show_all()
                self.finestra_principale.present()
        except Exception as ex:
            scrivi_log("Application.avvia_programma", ex)
        finally:
            GLib.idle_add(self._chiudi_finestra_aggiornamento)

    def _chiudi_finestra_aggiornamento(self):
        try:
            if self.finestra_aggiornamento is not None:
                finestra = self.finestra_aggiornamento
                self.finestra_aggiornamento = None
                finestra.destroy()
        except Exception as ex:
            scrivi_log("Application._chiudi_finestra_aggiornamento", ex)
        return False


def main():
    try:
        try:
            strumenti_youtube.avvia_manutenzione()
        except Exception as ex_manutenzione:
            scrivi_log("main.avvia_manutenzione", ex_manutenzione)
        return Application().run(sys.argv)
    except Exception as ex:
        scrivi_log("main", ex)
        return 1


if __name__ == "__main__":
    sys.exit(main())