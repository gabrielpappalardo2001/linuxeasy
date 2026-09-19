import re
import time
import unicodedata
from contextlib import closing
from datetime import date, datetime, timedelta

from app.agenda.agenda_model import (
    FINE_DATA,
    FINE_MAI,
    FINE_VOLTE,
    FREQUENZA_NESSUNA,
    FREQUENZE,
    Evento,
    occorrenze_di,
    prossima_occorrenza,
)
from app.core.log import scrivi_log

FORMATO_DATA_ORA = "%Y-%m-%dT%H:%M"
FORMATO_DATA = "%Y-%m-%d"
GIORNI_CONSERVAZIONE_NOTIFICHE = 90
COLONNE = (
    "id, title, location, notes, start, end, all_day, freq, interval, weekdays, end_mode, until, count, "
    "reminder, exclusions"
)


def normalizza(testo):
    try:
        valore = unicodedata.normalize("NFKD", str(testo or ""))
        valore = "".join(carattere for carattere in valore if not unicodedata.combining(carattere)).lower()
        return " ".join(re.sub(r"[^a-z0-9@.+]+", " ", valore).split())
    except Exception as ex:
        scrivi_log(f"agenda_store.normalizza ({testo})", ex)
        return ""


def _data_ora(testo, predefinito=None):
    try:
        return datetime.strptime(str(testo), FORMATO_DATA_ORA)
    except Exception as ex:
        scrivi_log(f"agenda_store._data_ora ({testo})", ex)
        return predefinito


def _data(testo):
    try:
        if not testo:
            return None
        return datetime.strptime(str(testo), FORMATO_DATA).date()
    except Exception as ex:
        scrivi_log(f"agenda_store._data ({testo})", ex)
        return None


class AgendaStore:
    def __init__(self, db):
        self.db = db
        self.al_cambiamento = None

    def _notifica_cambiamento(self):
        try:
            if self.al_cambiamento is not None:
                self.al_cambiamento()
        except Exception as ex:
            scrivi_log("AgendaStore._notifica_cambiamento", ex)

    def _evento_da_riga(self, riga):
        try:
            inizio = _data_ora(riga[4], datetime.now().replace(second=0, microsecond=0))
            fine = _data_ora(riga[5], inizio)
            frequenza = riga[7] if riga[7] in FREQUENZE else FREQUENZA_NESSUNA
            giorni = [int(parte) for parte in str(riga[9] or "").split(",") if parte.strip().isdigit()]
            esclusioni = {valore for valore in (_data(parte) for parte in str(riga[14] or "").split(",") if parte) if valore}
            return Evento(
                id=int(riga[0]),
                titolo=riga[1] or "",
                luogo=riga[2] or "",
                note=riga[3] or "",
                inizio=inizio,
                fine=max(fine, inizio),
                tutto_il_giorno=bool(riga[6]),
                frequenza=frequenza,
                intervallo=max(1, int(riga[8] or 1)),
                giorni_settimana=giorni,
                fine_ripetizione=riga[10] if riga[10] in (FINE_MAI, FINE_DATA, FINE_VOLTE) else FINE_MAI,
                ripeti_fino=_data(riga[11]),
                ripeti_volte=int(riga[12] or 0),
                avviso_minuti=int(riga[13] if riga[13] is not None else -1),
                esclusioni=esclusioni,
            )
        except Exception as ex:
            scrivi_log("AgendaStore._evento_da_riga", ex)
            return None

    def _parametri(self, evento):
        return (
            evento.titolo.strip(),
            evento.luogo.strip(),
            evento.note.strip(),
            evento.inizio.strftime(FORMATO_DATA_ORA),
            evento.fine.strftime(FORMATO_DATA_ORA),
            1 if evento.tutto_il_giorno else 0,
            evento.frequenza,
            max(1, int(evento.intervallo or 1)),
            ",".join(str(giorno) for giorno in sorted(set(evento.giorni_settimana or []))),
            evento.fine_ripetizione,
            evento.ripeti_fino.strftime(FORMATO_DATA) if evento.ripeti_fino else "",
            int(evento.ripeti_volte or 0),
            int(evento.avviso_minuti),
            ",".join(sorted(giorno.strftime(FORMATO_DATA) for giorno in evento.esclusioni)),
            normalizza(f"{evento.titolo} {evento.luogo} {evento.note}"),
        )

    def eventi(self):
        try:
            righe = self.db.leggi_tutti(f"SELECT {COLONNE} FROM agenda_events ORDER BY start")
            return [evento for evento in (self._evento_da_riga(riga) for riga in righe) if evento is not None]
        except Exception as ex:
            scrivi_log("AgendaStore.eventi", ex)
            return []

    def evento(self, identificativo):
        try:
            riga = self.db.leggi_uno(f"SELECT {COLONNE} FROM agenda_events WHERE id = ?", (int(identificativo),))
            return self._evento_da_riga(riga) if riga else None
        except Exception as ex:
            scrivi_log(f"AgendaStore.evento ({identificativo})", ex)
            return None

    def aggiungi(self, evento):
        try:
            adesso = time.time()
            with closing(self.db.get_connection()) as connessione, connessione:
                cursore = connessione.execute(
                    "INSERT INTO agenda_events (title, location, notes, start, end, all_day, freq, interval, weekdays, "
                    "end_mode, until, count, reminder, exclusions, search_text, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    self._parametri(evento) + (adesso, adesso),
                )
                evento.id = int(cursore.lastrowid)
            self._notifica_cambiamento()
            return evento.id
        except Exception as ex:
            scrivi_log(f"AgendaStore.aggiungi ({evento.titolo})", ex)
            return 0

    def aggiorna(self, evento):
        try:
            esito = self.db.esegui(
                "UPDATE agenda_events SET title = ?, location = ?, notes = ?, start = ?, end = ?, all_day = ?, "
                "freq = ?, interval = ?, weekdays = ?, end_mode = ?, until = ?, count = ?, reminder = ?, "
                "exclusions = ?, search_text = ?, updated_at = ? WHERE id = ?",
                self._parametri(evento) + (time.time(), int(evento.id)),
            )
            if esito:
                self._notifica_cambiamento()
            return esito
        except Exception as ex:
            scrivi_log(f"AgendaStore.aggiorna ({evento.id})", ex)
            return False

    def elimina(self, identificativo):
        try:
            esito = self.db.transazione(
                [
                    ("DELETE FROM agenda_events WHERE id = ?", (int(identificativo),)),
                    ("DELETE FROM agenda_notified WHERE event_id = ?", (int(identificativo),)),
                ]
            )
            if esito:
                self._notifica_cambiamento()
            return esito
        except Exception as ex:
            scrivi_log(f"AgendaStore.elimina ({identificativo})", ex)
            return False

    def escludi_giorno(self, identificativo, giorno):
        try:
            evento = self.evento(identificativo)
            if evento is None:
                return False
            evento.esclusioni.add(giorno)
            return self.aggiorna(evento)
        except Exception as ex:
            scrivi_log(f"AgendaStore.escludi_giorno ({identificativo}, {giorno})", ex)
            return False

    def occorrenze(self, da, a):
        try:
            return occorrenze_di(self.eventi(), da, a)
        except Exception as ex:
            scrivi_log("AgendaStore.occorrenze", ex)
            return []

    def occorrenze_giorno(self, giorno):
        try:
            inizio = datetime.combine(giorno, datetime.min.time())
            return self.occorrenze(inizio, inizio + timedelta(days=1))
        except Exception as ex:
            scrivi_log(f"AgendaStore.occorrenze_giorno ({giorno})", ex)
            return []

    def conteggi_mese(self, anno, mese):
        conteggi = {}
        try:
            primo = date(anno, mese, 1)
            successivo = date(anno + (mese // 12), mese % 12 + 1, 1)
            for occorrenza in self.occorrenze(
                datetime.combine(primo, datetime.min.time()),
                datetime.combine(successivo, datetime.min.time()),
            ):
                giorno = max(occorrenza.inizio.date(), primo)
                ultimo = min(occorrenza.ultimo_giorno, successivo - timedelta(days=1))
                while giorno <= ultimo:
                    conteggi[giorno] = conteggi.get(giorno, 0) + 1
                    giorno += timedelta(days=1)
        except Exception as ex:
            scrivi_log(f"AgendaStore.conteggi_mese ({anno}, {mese})", ex)
        return conteggi

    def cerca(self, testo):
        try:
            parole = normalizza(testo).split()
            if not parole:
                return []
            condizione = " AND ".join("search_text LIKE ?" for _parola in parole)
            righe = self.db.leggi_tutti(
                f"SELECT {COLONNE} FROM agenda_events WHERE {condizione} ORDER BY start",
                tuple(f"%{parola}%" for parola in parole),
            )
            return [evento for evento in (self._evento_da_riga(riga) for riga in righe) if evento is not None]
        except Exception as ex:
            scrivi_log(f"AgendaStore.cerca ({testo})", ex)
            return []

    def eventi_ordinati(self, adesso=None):
        try:
            riferimento = adesso or datetime.now()
            elenco = []
            for evento in self.eventi():
                prossima = prossima_occorrenza(evento, riferimento)
                elenco.append((evento, prossima))
            elenco.sort(
                key=lambda coppia: (
                    coppia[1] is None,
                    coppia[1].inizio if coppia[1] is not None else coppia[0].inizio,
                )
            )
            return elenco
        except Exception as ex:
            scrivi_log("AgendaStore.eventi_ordinati", ex)
            return []

    def gia_notificata(self, identificativo, inizio, tipo):
        try:
            return self.db.leggi_uno(
                "SELECT 1 FROM agenda_notified WHERE event_id = ? AND occurrence = ? AND kind = ?",
                (int(identificativo), inizio.strftime(FORMATO_DATA_ORA), tipo),
            ) is not None
        except Exception as ex:
            scrivi_log(f"AgendaStore.gia_notificata ({identificativo})", ex)
            return True

    def segna_notificata(self, identificativo, inizio, tipo):
        try:
            return self.db.esegui(
                "INSERT OR IGNORE INTO agenda_notified (event_id, occurrence, kind, notified_at) VALUES (?, ?, ?, ?)",
                (int(identificativo), inizio.strftime(FORMATO_DATA_ORA), tipo, time.time()),
            )
        except Exception as ex:
            scrivi_log(f"AgendaStore.segna_notificata ({identificativo})", ex)
            return False

    def pulisci_notifiche(self):
        try:
            return self.db.esegui(
                "DELETE FROM agenda_notified WHERE notified_at < ?",
                (time.time() - GIORNI_CONSERVAZIONE_NOTIFICHE * 86400,),
            )
        except Exception as ex:
            scrivi_log("AgendaStore.pulisci_notifiche", ex)
            return False
