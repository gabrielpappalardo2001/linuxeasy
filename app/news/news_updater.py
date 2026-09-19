import threading

from gi.repository import GLib

from app.core.log import scrivi_log

INTERVALLO_MINUTI = 15
RITARDO_INIZIALE_SECONDI = 45


class NewsUpdater:
    def __init__(self, manager, al_rilevamento=None, intervallo_minuti=INTERVALLO_MINUTI, ritardo_iniziale=RITARDO_INIZIALE_SECONDI):
        self.manager = manager
        self.al_rilevamento = al_rilevamento
        self.intervallo = max(5, int(intervallo_minuti)) * 60
        self.ritardo_iniziale = max(0, int(ritardo_iniziale))
        self._fermo = threading.Event()
        self._thread = None

    def avvia(self):
        try:
            if self._thread is not None and self._thread.is_alive():
                return
            self._fermo.clear()
            self._thread = threading.Thread(target=self._ciclo, name="AggiornamentoNotizie", daemon=True)
            self._thread.start()
        except Exception as ex:
            scrivi_log("NewsUpdater.avvia", ex)

    def ferma(self):
        try:
            self._fermo.set()
        except Exception as ex:
            scrivi_log("NewsUpdater.ferma", ex)

    def _ciclo(self):
        try:
            if self._fermo.wait(self.ritardo_iniziale):
                return
            while not self._fermo.is_set():
                self._aggiorna(None, self.intervallo - 60)
                if self._fermo.wait(self.intervallo):
                    return
        except Exception as ex:
            scrivi_log("NewsUpdater._ciclo", ex)

    def aggiorna_ora(self, al_termine=None, category_id=None):
        try:
            threading.Thread(
                target=self._aggiorna,
                args=(al_termine, None, category_id),
                name="AggiornamentoManualeNotizie",
                daemon=True,
            ).start()
        except Exception as ex:
            scrivi_log("NewsUpdater.aggiorna_ora", ex)

    def _aggiorna(self, al_termine, eta_massima, category_id=None):
        resoconto = None
        try:
            resoconto = self.manager.update_all(eta_massima, category_id)
            if resoconto["da_avvisare"] and self.al_rilevamento is not None and not self._fermo.is_set():
                GLib.idle_add(self._consegna, self.al_rilevamento, resoconto["da_avvisare"])
        except Exception as ex:
            scrivi_log("NewsUpdater._aggiorna", ex)
        try:
            if al_termine is not None and not self._fermo.is_set():
                GLib.idle_add(self._consegna, al_termine, resoconto)
        except Exception as ex:
            scrivi_log("NewsUpdater._aggiorna consegna", ex)
        return resoconto

    def _consegna(self, funzione, valore):
        try:
            funzione(valore)
        except Exception as ex:
            scrivi_log("NewsUpdater._consegna", ex)
        return False
