import threading
from datetime import datetime, timedelta

from gi.repository import GLib

from app.agenda.agenda_model import NESSUNA_NOTIFICA, occorrenze_di
from app.core.log import scrivi_log

SECONDI_CONTROLLO = 20
MINUTI_TOLLERANZA_INIZIO = 30
GIORNI_ANTICIPO_MASSIMO = 8
TIPO_AVVISO = "avviso"
TIPO_INIZIO = "inizio"


class AgendaNotifier:
    def __init__(self, store, al_rilevamento=None):
        self.store = store
        self.al_rilevamento = al_rilevamento
        self._fermo = threading.Event()
        self._sveglia = threading.Event()
        self._blocco = threading.Lock()
        self._thread = None

    def avvia(self):
        try:
            if self._thread is not None and self._thread.is_alive():
                return
            self._fermo.clear()
            self._thread = threading.Thread(target=self._ciclo, name="NotificheAgenda", daemon=True)
            self._thread.start()
        except Exception as ex:
            scrivi_log("AgendaNotifier.avvia", ex)

    def ferma(self):
        try:
            self._fermo.set()
            self._sveglia.set()
        except Exception as ex:
            scrivi_log("AgendaNotifier.ferma", ex)

    def controlla_ora(self):
        try:
            self._sveglia.set()
        except Exception as ex:
            scrivi_log("AgendaNotifier.controlla_ora", ex)

    def _ciclo(self):
        try:
            self.store.pulisci_notifiche()
            while not self._fermo.is_set():
                self.controlla(datetime.now())
                self._sveglia.wait(SECONDI_CONTROLLO)
                self._sveglia.clear()
        except Exception as ex:
            scrivi_log("AgendaNotifier._ciclo", ex)

    def _scadenze(self, occorrenza):
        scadenze = []
        try:
            evento = occorrenza.evento
            minuti = int(evento.avviso_minuti)
            if minuti == NESSUNA_NOTIFICA:
                return scadenze
            if evento.tutto_il_giorno:
                limite_inizio = occorrenza.inizio + timedelta(days=1)
            else:
                limite_inizio = occorrenza.inizio + timedelta(minutes=MINUTI_TOLLERANZA_INIZIO)
                if occorrenza.fine > occorrenza.inizio:
                    limite_inizio = min(limite_inizio, occorrenza.fine)
            if minuti > 0:
                scadenze.append((TIPO_AVVISO, occorrenza.inizio - timedelta(minutes=minuti), occorrenza.inizio))
            scadenze.append((TIPO_INIZIO, occorrenza.inizio, limite_inizio))
        except Exception as ex:
            scrivi_log("AgendaNotifier._scadenze", ex)
        return scadenze

    def da_notificare(self, adesso):
        trovate = []
        try:
            occorrenze = occorrenze_di(
                self.store.eventi(),
                adesso - timedelta(days=1, minutes=MINUTI_TOLLERANZA_INIZIO),
                adesso + timedelta(days=GIORNI_ANTICIPO_MASSIMO),
            )
            for occorrenza in occorrenze:
                for tipo, momento, limite in self._scadenze(occorrenza):
                    if not momento <= adesso < limite:
                        continue
                    if self.store.gia_notificata(occorrenza.evento.id, occorrenza.inizio, tipo):
                        continue
                    trovate.append((occorrenza, tipo))
        except Exception as ex:
            scrivi_log("AgendaNotifier.da_notificare", ex)
        return trovate

    def controlla(self, adesso):
        try:
            with self._blocco:
                trovate = self.da_notificare(adesso)
                consegnate = []
                inizi = {(occorrenza.evento.id, occorrenza.inizio) for occorrenza, tipo in trovate if tipo == TIPO_INIZIO}
                for occorrenza, tipo in trovate:
                    if not self.store.segna_notificata(occorrenza.evento.id, occorrenza.inizio, tipo):
                        continue
                    if tipo == TIPO_AVVISO and (occorrenza.evento.id, occorrenza.inizio) in inizi:
                        continue
                    consegnate.append((occorrenza, tipo))
            if consegnate and self.al_rilevamento is not None and not self._fermo.is_set():
                GLib.idle_add(self._consegna, consegnate)
            return consegnate
        except Exception as ex:
            scrivi_log("AgendaNotifier.controlla", ex)
            return []

    def _consegna(self, consegnate):
        try:
            self.al_rilevamento(consegnate)
        except Exception as ex:
            scrivi_log("AgendaNotifier._consegna", ex)
        return False
