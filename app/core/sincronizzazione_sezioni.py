import json
import re
import time
import urllib.parse
from contextlib import closing
from datetime import date, datetime, timedelta

from app.agenda.agenda_store import normalizza as normalizza_agenda
from app.core.log import scrivi_log
from app.rubrica.rubrica_store import (
    TIPO_EMAIL,
    TIPO_INDIRIZZO,
    TIPO_SITO,
    TIPO_TELEFONO,
    Contatto,
    RubricaStore,
    Valore,
)

SEZIONE_CONTATTI = "contatti"
SEZIONE_APPUNTAMENTI = "appuntamenti"
SEZIONE_RADIO_PREFERITI = "radioPreferiti"
SEZIONE_RADIO_RECENTI = "radioRecenti"
SEZIONE_CATEGORIE_TESTATE = "categorieTestate"
SEZIONE_TESTATE = "testate"
CAMPI_COMUNI = ("id", "modificato", "eliminato")
FORMATO_UTC = "%Y-%m-%dT%H:%M:%S"
FORMATO_DATA_ORA_AGENDA = "%Y-%m-%dT%H:%M"
FORMATO_GIORNO = "%Y-%m-%d"
ETICHETTA_CELLULARE = "Cellulare"
ETICHETTE_PREDEFINITE = {
    "telefoni": "Casa",
    "cellulari": ETICHETTA_CELLULARE,
    "email": "Personale",
    "indirizzi": "Casa",
    "siti": "Sito web",
}
TIPI_ELENCHI = {
    "telefoni": TIPO_TELEFONO,
    "cellulari": TIPO_TELEFONO,
    "email": TIPO_EMAIL,
    "indirizzi": TIPO_INDIRIZZO,
    "siti": TIPO_SITO,
}
FREQUENZE_DA_CODICE = {
    0: ("nessuna", 1),
    1: ("giornaliera", 1),
    2: ("settimanale", 1),
    3: ("settimanale", 2),
    4: ("mensile", 1),
    5: ("annuale", 1),
}
MASSIMO_RECENTI_RADIO = 40
DATA_MINIMA = datetime(1970, 1, 1)


def ora_utc():
    try:
        adesso = datetime.utcnow()
        return adesso.strftime(FORMATO_UTC) + f".{adesso.microsecond // 1000:03d}Z"
    except Exception as ex:
        scrivi_log("sincronizzazione_sezioni.ora_utc", ex)
        return "1970-01-01T00:00:00.000Z"


def formato_utc(valore):
    try:
        return valore.strftime(FORMATO_UTC) + f".{valore.microsecond // 1000:03d}Z"
    except Exception as ex:
        scrivi_log(f"sincronizzazione_sezioni.formato_utc ({valore})", ex)
        return ora_utc()


def leggi_utc(testo):
    try:
        valore = str(testo or "").strip()
        if not valore:
            return DATA_MINIMA
        corrispondenza = re.match(
            r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:?\d{2})?$",
            valore,
        )
        if corrispondenza is None:
            return DATA_MINIMA
        anno, mese, giorno, ora, minuto, secondo, frazione, fuso = corrispondenza.groups()
        microsecondi = int((frazione or "0")[:6].ljust(6, "0"))
        risultato = datetime(int(anno), int(mese), int(giorno), int(ora), int(minuto), int(secondo or 0), microsecondi)
        if fuso and fuso != "Z":
            segno = 1 if fuso[0] == "+" else -1
            cifre = fuso[1:].replace(":", "")
            spostamento = timedelta(hours=int(cifre[:2]), minutes=int(cifre[2:4]))
            risultato = risultato - segno * spostamento
        return risultato
    except Exception as ex:
        scrivi_log(f"sincronizzazione_sezioni.leggi_utc ({testo})", ex)
        return DATA_MINIMA


def testo(voce, chiave):
    try:
        valore = voce.get(chiave) if isinstance(voce, dict) else None
        if valore is None:
            return ""
        return str(valore).strip()
    except Exception as ex:
        scrivi_log(f"sincronizzazione_sezioni.testo ({chiave})", ex)
        return ""


def vero(voce, chiave):
    try:
        valore = voce.get(chiave) if isinstance(voce, dict) else None
        if isinstance(valore, bool):
            return valore
        return str(valore or "").strip().lower() in ("true", "1", "si", "sì")
    except Exception as ex:
        scrivi_log(f"sincronizzazione_sezioni.vero ({chiave})", ex)
        return False


def intero(voce, chiave, predefinito=0):
    try:
        valore = voce.get(chiave) if isinstance(voce, dict) else None
        if valore is None or valore == "":
            return predefinito
        return int(float(valore))
    except Exception as ex:
        scrivi_log(f"sincronizzazione_sezioni.intero ({chiave})", ex)
        return predefinito


def elenco(voce, chiave):
    risultato = []
    try:
        valore = voce.get(chiave) if isinstance(voce, dict) else None
        if valore is None:
            return risultato
        if isinstance(valore, str):
            valori = [valore]
        elif isinstance(valore, (list, tuple)):
            valori = valore
        else:
            return risultato
        for elemento in valori:
            if elemento is None:
                continue
            pulito = str(elemento).strip()
            if pulito and pulito not in risultato:
                risultato.append(pulito)
    except Exception as ex:
        scrivi_log(f"sincronizzazione_sezioni.elenco ({chiave})", ex)
    return risultato


def campi_esterni(voce, campi_gestiti):
    try:
        if not isinstance(voce, dict):
            return {}
        return {
            chiave: valore
            for chiave, valore in voce.items()
            if chiave not in CAMPI_COMUNI and chiave not in campi_gestiti
        }
    except Exception as ex:
        scrivi_log("sincronizzazione_sezioni.campi_esterni", ex)
        return {}


def leggi_esterni(testo_json):
    try:
        if not testo_json:
            return {}
        valore = json.loads(testo_json)
        return valore if isinstance(valore, dict) else {}
    except Exception as ex:
        scrivi_log("sincronizzazione_sezioni.leggi_esterni", ex)
        return {}


def scrivi_esterni(valori):
    try:
        if not valori:
            return ""
        return json.dumps(valori, ensure_ascii=False, sort_keys=True)
    except Exception as ex:
        scrivi_log("sincronizzazione_sezioni.scrivi_esterni", ex)
        return ""


def id_testata(indirizzo_sito, indirizzo_feed=""):
    try:
        base = str(indirizzo_sito or "").strip() or str(indirizzo_feed or "").strip()
        if not base:
            return ""
        parti = urllib.parse.urlsplit(base)
        if not parti.scheme or not parti.netloc:
            return base
        if not str(indirizzo_sito or "").strip():
            return f"{parti.scheme.lower()}://{parti.netloc.lower()}/"
        percorso = parti.path or "/"
        if not percorso.endswith("/"):
            percorso += "/"
        return urllib.parse.urlunsplit((parti.scheme.lower(), parti.netloc.lower(), percorso, "", ""))
    except Exception as ex:
        scrivi_log(f"sincronizzazione_sezioni.id_testata ({indirizzo_sito})", ex)
        return str(indirizzo_sito or indirizzo_feed or "")


class SezioneBase:
    nome = ""
    campi_gestiti = ()

    def __init__(self, db):
        self.db = db
        self.id_remoti = set()

    def prepara(self, voci_remote):
        self.ricorda_id_remoti(voci_remote)
        return True

    def ricorda_id_remoti(self, voci_remote):
        try:
            self.id_remoti = {testo(voce, "id") for voce in voci_remote or [] if isinstance(voce, dict) and testo(voce, "id")}
        except Exception as ex:
            scrivi_log(f"SezioneBase.ricorda_id_remoti ({self.nome})", ex)
            self.id_remoti = set()

    def stato_locale(self):
        return {}

    def voce_locale(self, identificativo):
        return None

    def applica(self, voce):
        return False

    def applica_eliminazione(self, identificativo, data):
        return False

    def rifinisci(self, voci):
        return voci

    def _eliminazioni(self):
        risultato = {}
        try:
            for riga in self.db.leggi_tutti(
                "SELECT sync_id, data FROM sync_eliminati WHERE sezione = ?",
                (self.nome,),
            ):
                if riga[0]:
                    risultato[str(riga[0])] = (leggi_utc(riga[1]), True)
        except Exception as ex:
            scrivi_log(f"SezioneBase._eliminazioni ({self.nome})", ex)
        return risultato

    def _registra_eliminazione(self, connessione, identificativo, data):
        connessione.execute(
            "INSERT OR REPLACE INTO sync_eliminati (sezione, sync_id, data) VALUES (?, ?, ?)",
            (self.nome, str(identificativo), formato_utc(data)),
        )

    def _togli_eliminazione(self, connessione, identificativo):
        connessione.execute(
            "DELETE FROM sync_eliminati WHERE sezione = ? AND sync_id = ?",
            (self.nome, str(identificativo)),
        )

    def pulisci_eliminazioni(self, limite):
        try:
            return self.db.esegui(
                "DELETE FROM sync_eliminati WHERE sezione = ? AND data < ?",
                (self.nome, formato_utc(limite)),
            )
        except Exception as ex:
            scrivi_log(f"SezioneBase.pulisci_eliminazioni ({self.nome})", ex)
            return False

    def _stato_tabella(self, tabella):
        stato = {}
        try:
            stato.update(self._eliminazioni())
            for riga in self.db.leggi_tutti(
                f"SELECT sync_id, sync_modificato FROM {tabella} WHERE sync_id IS NOT NULL AND sync_id <> ''"
            ):
                stato[str(riga[0])] = (leggi_utc(riga[1]), False)
        except Exception as ex:
            scrivi_log(f"SezioneBase._stato_tabella ({tabella})", ex)
        return stato


class SezioneContatti(SezioneBase):
    nome = SEZIONE_CONTATTI
    campi_gestiti = ("nome", "cognome", "azienda", "note", "preferito", "telefoni", "cellulari", "email", "indirizzi", "siti", "compleanno")

    def __init__(self, db):
        super().__init__(db)
        self.store = RubricaStore(db)

    def stato_locale(self):
        return self._stato_tabella("contacts")

    def voce_locale(self, identificativo):
        try:
            riga = self.db.leggi_uno(
                "SELECT id, first_name, last_name, company, birthday, notes, favorite, sync_modificato, sync_extra "
                "FROM contacts WHERE sync_id = ?",
                (identificativo,),
            )
            if riga is None:
                return None
            elenchi = {chiave: [] for chiave in TIPI_ELENCHI}
            for valore in self.db.leggi_tutti(
                "SELECT kind, label, value FROM contact_values WHERE contact_id = ? ORDER BY position, id",
                (int(riga[0]),),
            ):
                tipo, etichetta, contenuto = valore[0], str(valore[1] or ""), str(valore[2] or "").strip()
                if not contenuto:
                    continue
                if tipo == TIPO_TELEFONO:
                    chiave = "cellulari" if etichetta.strip().lower() == ETICHETTA_CELLULARE.lower() else "telefoni"
                elif tipo == TIPO_EMAIL:
                    chiave = "email"
                elif tipo == TIPO_INDIRIZZO:
                    chiave = "indirizzi"
                elif tipo == TIPO_SITO:
                    chiave = "siti"
                else:
                    continue
                if contenuto not in elenchi[chiave]:
                    elenchi[chiave].append(contenuto)
            voce = leggi_esterni(riga[8])
            voce.update(
                {
                    "id": identificativo,
                    "modificato": formato_utc(leggi_utc(riga[7])),
                    "eliminato": False,
                    "nome": riga[1] or "",
                    "cognome": riga[2] or "",
                    "azienda": riga[3] or "",
                    "note": riga[5] or "",
                    "preferito": bool(riga[6]),
                    "compleanno": riga[4] or "",
                }
            )
            voce.update(elenchi)
            voce.setdefault("categoria", "")
            return voce
        except Exception as ex:
            scrivi_log(f"SezioneContatti.voce_locale ({identificativo})", ex)
            return None

    def applica(self, voce):
        try:
            identificativo = testo(voce, "id")
            modificato = formato_utc(leggi_utc(testo(voce, "modificato")))
            esistente = self.db.leggi_uno("SELECT id, birthday FROM contacts WHERE sync_id = ?", (identificativo,))
            etichette_precedenti = {}
            if esistente is not None:
                for riga in self.db.leggi_tutti(
                    "SELECT kind, label, value FROM contact_values WHERE contact_id = ?",
                    (int(esistente[0]),),
                ):
                    etichette_precedenti[(riga[0], str(riga[2] or "").strip())] = str(riga[1] or "")
            valori = []
            for chiave in ("cellulari", "telefoni", "email", "indirizzi", "siti"):
                tipo = TIPI_ELENCHI[chiave]
                for contenuto in elenco(voce, chiave):
                    etichetta = etichette_precedenti.get((tipo, contenuto), "")
                    if chiave == "cellulari":
                        etichetta = ETICHETTA_CELLULARE
                    elif chiave == "telefoni" and (not etichetta or etichetta.lower() == ETICHETTA_CELLULARE.lower()):
                        etichetta = ETICHETTE_PREDEFINITE[chiave]
                    elif not etichetta:
                        etichetta = ETICHETTE_PREDEFINITE[chiave]
                    valori.append(Valore(tipo, etichetta, contenuto))
            if "compleanno" in voce:
                compleanno = testo(voce, "compleanno")
                if compleanno and not re.match(r"^\d{4}-\d{2}-\d{2}$", compleanno):
                    compleanno = esistente[1] if esistente is not None else ""
            else:
                compleanno = esistente[1] if esistente is not None else ""
            data_compleanno, anno_noto = self.store._leggi_compleanno(compleanno)
            contatto = Contatto(
                nome=testo(voce, "nome"),
                cognome=testo(voce, "cognome"),
                azienda=testo(voce, "azienda"),
                compleanno=data_compleanno,
                anno_noto=anno_noto,
                note=testo(voce, "note"),
                preferito=vero(voce, "preferito"),
                valori=valori,
            )
            esterni = scrivi_esterni(campi_esterni(voce, self.campi_gestiti))
            adesso = time.time()
            with closing(self.db.get_connection()) as connessione, connessione:
                parametri = (
                    contatto.nome,
                    contatto.cognome,
                    contatto.azienda,
                    self.store._compleanno_testo(contatto),
                    contatto.note,
                    1 if contatto.preferito else 0,
                    self.store._chiave_ordinamento(contatto),
                    self.store._testo_ricerca(contatto),
                )
                if esistente is not None:
                    contatto.id = int(esistente[0])
                    connessione.execute(
                        "UPDATE contacts SET first_name = ?, last_name = ?, company = ?, birthday = ?, notes = ?, "
                        "favorite = ?, sort_key = ?, search_text = ?, updated_at = ?, sync_extra = ?, sync_modificato = ? "
                        "WHERE id = ?",
                        parametri + (adesso, esterni, modificato, contatto.id),
                    )
                else:
                    cursore = connessione.execute(
                        "INSERT INTO contacts (first_name, last_name, company, birthday, notes, favorite, sort_key, "
                        "search_text, created_at, updated_at, sync_id, sync_modificato, sync_extra) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        parametri + (adesso, adesso, identificativo, modificato, esterni),
                    )
                    contatto.id = int(cursore.lastrowid)
                connessione.execute("DELETE FROM contact_values WHERE contact_id = ?", (contatto.id,))
                for posizione, valore in enumerate(contatto.valori):
                    connessione.execute(
                        "INSERT INTO contact_values (contact_id, kind, label, value, position) VALUES (?, ?, ?, ?, ?)",
                        (contatto.id, valore.tipo, valore.etichetta, valore.valore, posizione),
                    )
                connessione.execute("UPDATE contacts SET sync_modificato = ? WHERE id = ?", (modificato, contatto.id))
                self._togli_eliminazione(connessione, identificativo)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneContatti.applica ({testo(voce, 'id')})", ex)
            return False

    def applica_eliminazione(self, identificativo, data):
        try:
            with closing(self.db.get_connection()) as connessione, connessione:
                riga = connessione.execute("SELECT id FROM contacts WHERE sync_id = ?", (identificativo,)).fetchone()
                if riga is not None:
                    connessione.execute("DELETE FROM contact_values WHERE contact_id = ?", (int(riga[0]),))
                    connessione.execute("DELETE FROM contacts WHERE id = ?", (int(riga[0]),))
                self._registra_eliminazione(connessione, identificativo, data)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneContatti.applica_eliminazione ({identificativo})", ex)
            return False


class SezioneAppuntamenti(SezioneBase):
    nome = SEZIONE_APPUNTAMENTI
    campi_gestiti = ("oggetto", "luogo", "note", "dataInizio", "dataFine", "oraInizio", "oraFine", "frequenza", "linuxeasy")

    def stato_locale(self):
        return self._stato_tabella("agenda_events")

    def _codice_frequenza(self, frequenza, intervallo):
        try:
            if frequenza == "giornaliera":
                return 1
            if frequenza == "settimanale":
                return 3 if int(intervallo or 1) == 2 else 2
            if frequenza == "mensile":
                return 4
            if frequenza == "annuale":
                return 5
            return 0
        except Exception as ex:
            scrivi_log(f"SezioneAppuntamenti._codice_frequenza ({frequenza})", ex)
            return 0

    def voce_locale(self, identificativo):
        try:
            riga = self.db.leggi_uno(
                "SELECT title, location, notes, start, end, all_day, freq, interval, weekdays, end_mode, until, count, "
                "reminder, exclusions, sync_modificato, sync_extra FROM agenda_events WHERE sync_id = ?",
                (identificativo,),
            )
            if riga is None:
                return None
            inizio = datetime.strptime(str(riga[3]), FORMATO_DATA_ORA_AGENDA)
            fine = datetime.strptime(str(riga[4]), FORMATO_DATA_ORA_AGENDA)
            if fine < inizio:
                fine = inizio
            tutto_il_giorno = bool(riga[5])
            if tutto_il_giorno:
                ultimo = (fine - timedelta(days=1)).date() if fine > inizio else inizio.date()
                if ultimo < inizio.date():
                    ultimo = inizio.date()
                ora_inizio = ""
                ora_fine = ""
            else:
                ultimo = fine.date()
                ora_inizio = inizio.strftime("%H:%M")
                ora_fine = fine.strftime("%H:%M")
            voce = leggi_esterni(riga[15])
            voce.update(
                {
                    "id": identificativo,
                    "modificato": formato_utc(leggi_utc(riga[14])),
                    "eliminato": False,
                    "oggetto": riga[0] or "",
                    "luogo": riga[1] or "",
                    "note": riga[2] or "",
                    "dataInizio": inizio.strftime(FORMATO_GIORNO),
                    "dataFine": ultimo.strftime(FORMATO_GIORNO),
                    "oraInizio": ora_inizio,
                    "oraFine": ora_fine,
                    "frequenza": self._codice_frequenza(riga[6], riga[7]),
                    "linuxeasy": {
                        "tuttoIlGiorno": tutto_il_giorno,
                        "frequenza": riga[6] or "nessuna",
                        "intervallo": int(riga[7] or 1),
                        "giorniSettimana": riga[8] or "",
                        "fineRipetizione": riga[9] or "mai",
                        "ripetiFino": riga[10] or "",
                        "ripetiVolte": int(riga[11] or 0),
                        "avvisoMinuti": int(riga[12] if riga[12] is not None else -1),
                        "esclusioni": riga[13] or "",
                    },
                }
            )
            voce.setdefault("nome", "")
            voce.setdefault("categoria", "")
            voce.setdefault("preavviso", 0)
            return voce
        except Exception as ex:
            scrivi_log(f"SezioneAppuntamenti.voce_locale ({identificativo})", ex)
            return None

    def _giorno(self, valore):
        try:
            pulito = str(valore or "").strip()
            for formato in (FORMATO_GIORNO, "%d/%m/%Y"):
                try:
                    return datetime.strptime(pulito, formato).date()
                except ValueError:
                    continue
            return None
        except Exception as ex:
            scrivi_log(f"SezioneAppuntamenti._giorno ({valore})", ex)
            return None

    def _ora(self, valore):
        try:
            pulito = str(valore or "").strip()
            for formato in ("%H:%M", "%H:%M:%S"):
                try:
                    return datetime.strptime(pulito, formato).time()
                except ValueError:
                    continue
            return None
        except Exception as ex:
            scrivi_log(f"SezioneAppuntamenti._ora ({valore})", ex)
            return None

    def applica(self, voce):
        try:
            identificativo = testo(voce, "id")
            modificato = formato_utc(leggi_utc(testo(voce, "modificato")))
            primo_giorno = self._giorno(testo(voce, "dataInizio"))
            if primo_giorno is None:
                return False
            ultimo_giorno = self._giorno(testo(voce, "dataFine")) or primo_giorno
            if ultimo_giorno < primo_giorno:
                ultimo_giorno = primo_giorno
            ora_inizio = self._ora(testo(voce, "oraInizio"))
            ora_fine = self._ora(testo(voce, "oraFine"))
            if ora_inizio is None:
                tutto_il_giorno = 1
                inizio = datetime.combine(primo_giorno, datetime.min.time())
                fine = datetime.combine(ultimo_giorno + timedelta(days=1), datetime.min.time())
            else:
                tutto_il_giorno = 0
                inizio = datetime.combine(primo_giorno, ora_inizio)
                if ora_fine is not None:
                    fine = datetime.combine(ultimo_giorno, ora_fine)
                else:
                    fine = inizio + timedelta(hours=1)
                if fine < inizio:
                    fine = inizio
            frequenza, intervallo = FREQUENZE_DA_CODICE.get(intero(voce, "frequenza"), FREQUENZE_DA_CODICE[0])
            esistente = self.db.leggi_uno("SELECT id, reminder FROM agenda_events WHERE sync_id = ?", (identificativo,))
            avviso = int(esistente[1]) if esistente is not None and esistente[1] is not None else 15
            giorni = ""
            fine_ripetizione = "mai"
            ripeti_fino = ""
            ripeti_volte = 0
            esclusioni = ""
            proprie = voce.get("linuxeasy") if isinstance(voce.get("linuxeasy"), dict) else None
            if proprie is not None and str(proprie.get("frequenza") or "") == frequenza:
                intervallo = max(1, intero(proprie, "intervallo", intervallo))
                giorni = testo(proprie, "giorniSettimana")
                fine_ripetizione = testo(proprie, "fineRipetizione") or "mai"
                if fine_ripetizione not in ("mai", "data", "volte"):
                    fine_ripetizione = "mai"
                ripeti_fino = testo(proprie, "ripetiFino")
                ripeti_volte = max(0, intero(proprie, "ripetiVolte"))
                esclusioni = testo(proprie, "esclusioni")
                avviso = intero(proprie, "avvisoMinuti", avviso)
            oggetto = testo(voce, "oggetto") or "Appuntamento"
            luogo = testo(voce, "luogo")
            note = testo(voce, "note")
            esterni = scrivi_esterni(campi_esterni(voce, self.campi_gestiti))
            parametri = (
                oggetto,
                luogo,
                note,
                inizio.strftime(FORMATO_DATA_ORA_AGENDA),
                fine.strftime(FORMATO_DATA_ORA_AGENDA),
                tutto_il_giorno,
                frequenza,
                intervallo,
                giorni,
                fine_ripetizione,
                ripeti_fino,
                ripeti_volte,
                avviso,
                esclusioni,
                normalizza_agenda(f"{oggetto} {luogo} {note}"),
            )
            adesso = time.time()
            with closing(self.db.get_connection()) as connessione, connessione:
                if esistente is not None:
                    connessione.execute(
                        "UPDATE agenda_events SET title = ?, location = ?, notes = ?, start = ?, end = ?, all_day = ?, "
                        "freq = ?, interval = ?, weekdays = ?, end_mode = ?, until = ?, count = ?, reminder = ?, "
                        "exclusions = ?, search_text = ?, updated_at = ?, sync_extra = ?, sync_modificato = ? WHERE id = ?",
                        parametri + (adesso, esterni, modificato, int(esistente[0])),
                    )
                else:
                    connessione.execute(
                        "INSERT INTO agenda_events (title, location, notes, start, end, all_day, freq, interval, weekdays, "
                        "end_mode, until, count, reminder, exclusions, search_text, created_at, updated_at, "
                        "sync_id, sync_modificato, sync_extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        parametri + (adesso, adesso, identificativo, modificato, esterni),
                    )
                self._togli_eliminazione(connessione, identificativo)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneAppuntamenti.applica ({testo(voce, 'id')})", ex)
            return False

    def applica_eliminazione(self, identificativo, data):
        try:
            with closing(self.db.get_connection()) as connessione, connessione:
                riga = connessione.execute("SELECT id FROM agenda_events WHERE sync_id = ?", (identificativo,)).fetchone()
                if riga is not None:
                    connessione.execute("DELETE FROM agenda_notified WHERE event_id = ?", (int(riga[0]),))
                    connessione.execute("DELETE FROM agenda_events WHERE id = ?", (int(riga[0]),))
                self._registra_eliminazione(connessione, identificativo, data)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneAppuntamenti.applica_eliminazione ({identificativo})", ex)
            return False


class SezioneCategorieTestate(SezioneBase):
    nome = SEZIONE_CATEGORIE_TESTATE
    campi_gestiti = ("nome",)

    def stato_locale(self):
        return self._stato_tabella("news_categories")

    def voce_locale(self, identificativo):
        try:
            riga = self.db.leggi_uno(
                "SELECT name, sync_modificato, sync_extra FROM news_categories WHERE sync_id = ?",
                (identificativo,),
            )
            if riga is None:
                return None
            voce = leggi_esterni(riga[2])
            voce.update(
                {
                    "id": identificativo,
                    "modificato": formato_utc(leggi_utc(riga[1])),
                    "eliminato": False,
                    "nome": riga[0] or "",
                }
            )
            return voce
        except Exception as ex:
            scrivi_log(f"SezioneCategorieTestate.voce_locale ({identificativo})", ex)
            return None

    def applica(self, voce):
        try:
            identificativo = testo(voce, "id")
            nome = " ".join(testo(voce, "nome").split()) or "Senza nome"
            modificato = formato_utc(leggi_utc(testo(voce, "modificato")))
            esterni = scrivi_esterni(campi_esterni(voce, self.campi_gestiti))
            with closing(self.db.get_connection()) as connessione, connessione:
                esistente = connessione.execute(
                    "SELECT id FROM news_categories WHERE sync_id = ?", (identificativo,)
                ).fetchone()
                omonima = connessione.execute(
                    "SELECT id, sync_id FROM news_categories WHERE name = ? COLLATE NOCASE", (nome,)
                ).fetchone()
                if esistente is None and omonima is not None and str(omonima[1] or "") not in self.id_remoti:
                    esistente = omonima
                if esistente is not None:
                    if omonima is not None and int(omonima[0]) != int(esistente[0]):
                        nome = f"{nome} ({identificativo[:4]})"
                    connessione.execute(
                        "UPDATE news_categories SET name = ?, sync_id = ?, sync_extra = ?, sync_modificato = ? WHERE id = ?",
                        (nome, identificativo, esterni, modificato, int(esistente[0])),
                    )
                    connessione.execute(
                        "UPDATE news_sources SET category = ? WHERE category_id = ?",
                        (nome, int(esistente[0])),
                    )
                else:
                    if omonima is not None:
                        nome = f"{nome} ({identificativo[:4]})"
                    posizione = connessione.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM news_categories").fetchone()[0]
                    connessione.execute(
                        "INSERT INTO news_categories (name, position, sync_id, sync_modificato, sync_extra) VALUES (?, ?, ?, ?, ?)",
                        (nome, posizione, identificativo, modificato, esterni),
                    )
                self._togli_eliminazione(connessione, identificativo)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneCategorieTestate.applica ({testo(voce, 'id')})", ex)
            return False

    def applica_eliminazione(self, identificativo, data):
        try:
            with closing(self.db.get_connection()) as connessione, connessione:
                riga = connessione.execute("SELECT id FROM news_categories WHERE sync_id = ?", (identificativo,)).fetchone()
                if riga is not None:
                    altra = connessione.execute(
                        "SELECT id, name FROM news_categories WHERE id <> ? ORDER BY position, id LIMIT 1",
                        (int(riga[0]),),
                    ).fetchone()
                    if altra is None:
                        return False
                    connessione.execute(
                        "UPDATE news_sources SET category_id = ?, category = ? WHERE category_id = ?",
                        (int(altra[0]), altra[1], int(riga[0])),
                    )
                    connessione.execute("DELETE FROM news_categories WHERE id = ?", (int(riga[0]),))
                self._registra_eliminazione(connessione, identificativo, data)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneCategorieTestate.applica_eliminazione ({identificativo})", ex)
            return False


class SezioneTestate(SezioneBase):
    nome = SEZIONE_TESTATE
    campi_gestiti = ("titolo", "url", "tipo", "feedUrl", "categoria")

    def prepara(self, voci_remote):
        try:
            self.ricorda_id_remoti(voci_remote)
            usati = {
                str(riga[0])
                for riga in self.db.leggi_tutti(
                    "SELECT sync_id FROM news_sources WHERE sync_id IS NOT NULL AND sync_id <> ''"
                )
            }
            for riga in self.db.leggi_tutti(
                "SELECT rowid, url, site_url FROM news_sources WHERE sync_id IS NULL OR sync_id = ''"
            ):
                identificativo = id_testata(riga[2], riga[1])
                if not identificativo or identificativo in usati:
                    identificativo = str(riga[1])
                if identificativo in usati:
                    continue
                if self.db.esegui("UPDATE news_sources SET sync_id = ? WHERE rowid = ?", (identificativo, int(riga[0]))):
                    usati.add(identificativo)
            return True
        except Exception as ex:
            scrivi_log("SezioneTestate.prepara", ex)
            return False

    def stato_locale(self):
        return self._stato_tabella("news_sources")

    def voce_locale(self, identificativo):
        try:
            riga = self.db.leggi_uno(
                "SELECT s.name, s.url, s.site_url, s.kind, c.sync_id, s.added_at, s.sync_modificato, s.sync_extra "
                "FROM news_sources s LEFT JOIN news_categories c ON c.id = s.category_id WHERE s.sync_id = ?",
                (identificativo,),
            )
            if riga is None:
                return None
            voce = leggi_esterni(riga[7])
            indirizzo_sito = identificativo if identificativo.startswith("http") and identificativo != riga[1] else (riga[2] or "")
            voce.update(
                {
                    "id": identificativo,
                    "modificato": formato_utc(leggi_utc(riga[6])),
                    "eliminato": False,
                    "titolo": riga[0] or "",
                    "url": indirizzo_sito,
                    "tipo": "WordPress" if str(riga[3] or "").lower() == "wordpress" else "Rss",
                    "feedUrl": riga[1] or "",
                    "categoria": riga[4] or "",
                }
            )
            if "dataAggiunta" not in voce:
                try:
                    voce["dataAggiunta"] = formato_utc(datetime.utcfromtimestamp(float(riga[5] or 0)))
                except Exception as exData:
                    scrivi_log(f"SezioneTestate.voce_locale data di aggiunta ({identificativo})", exData)
                    voce["dataAggiunta"] = ""
            voce.setdefault("preferito", False)
            voce.setdefault("ultimoAccesso", "")
            return voce
        except Exception as ex:
            scrivi_log(f"SezioneTestate.voce_locale ({identificativo})", ex)
            return None

    def applica(self, voce):
        try:
            identificativo = testo(voce, "id")
            tipo = testo(voce, "tipo").lower()
            indirizzo_sito = testo(voce, "url") or identificativo
            if tipo == "rss":
                feed = testo(voce, "feedUrl")
                genere = "rss"
            elif tipo == "wordpress":
                feed = testo(voce, "feedUrl") or indirizzo_sito.rstrip("/") + "/feed/"
                genere = "wordpress"
            else:
                return False
            if not feed:
                return False
            modificato = formato_utc(leggi_utc(testo(voce, "modificato")))
            esterni = scrivi_esterni(campi_esterni(voce, self.campi_gestiti))
            nome = " ".join(testo(voce, "titolo").split()) or feed
            with closing(self.db.get_connection()) as connessione, connessione:
                categoria = None
                if testo(voce, "categoria"):
                    categoria = connessione.execute(
                        "SELECT id, name FROM news_categories WHERE sync_id = ?", (testo(voce, "categoria"),)
                    ).fetchone()
                esistente = connessione.execute(
                    "SELECT rowid, category_id FROM news_sources WHERE sync_id = ?", (identificativo,)
                ).fetchone()
                stesso_feed = connessione.execute(
                    "SELECT rowid, category_id, sync_id FROM news_sources WHERE url = ?", (feed,)
                ).fetchone()
                if esistente is None and stesso_feed is not None:
                    if str(stesso_feed[2] or "") in self.id_remoti:
                        return False
                    esistente = stesso_feed
                elif esistente is not None and stesso_feed is not None and int(stesso_feed[0]) != int(esistente[0]):
                    return False
                if categoria is None and esistente is not None and esistente[1] is not None:
                    categoria = connessione.execute(
                        "SELECT id, name FROM news_categories WHERE id = ?", (int(esistente[1]),)
                    ).fetchone()
                if categoria is None:
                    categoria = connessione.execute(
                        "SELECT id, name FROM news_categories ORDER BY position, id LIMIT 1"
                    ).fetchone()
                if categoria is None:
                    return False
                if esistente is not None:
                    connessione.execute(
                        "UPDATE news_sources SET name = ?, url = ?, site_url = ?, kind = ?, category_id = ?, category = ?, "
                        "sync_id = ?, sync_extra = ?, sync_modificato = ? WHERE rowid = ?",
                        (nome, feed, indirizzo_sito, genere, int(categoria[0]), categoria[1], identificativo, esterni, modificato, int(esistente[0])),
                    )
                else:
                    connessione.execute(
                        "INSERT INTO news_sources (name, url, category, site_url, kind, category_id, added_at, "
                        "sync_id, sync_modificato, sync_extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (nome, feed, categoria[1], indirizzo_sito, genere, int(categoria[0]), time.time(), identificativo, modificato, esterni),
                    )
                self._togli_eliminazione(connessione, identificativo)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneTestate.applica ({testo(voce, 'id')})", ex)
            return False

    def applica_eliminazione(self, identificativo, data):
        try:
            with closing(self.db.get_connection()) as connessione, connessione:
                riga = connessione.execute("SELECT url FROM news_sources WHERE sync_id = ?", (identificativo,)).fetchone()
                if riga is not None:
                    connessione.execute("DELETE FROM news_sources WHERE sync_id = ?", (identificativo,))
                    connessione.execute("DELETE FROM news_articles WHERE source_url = ?", (riga[0],))
                    connessione.execute("DELETE FROM news_source_state WHERE source_url = ?", (riga[0],))
                self._registra_eliminazione(connessione, identificativo, data)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneTestate.applica_eliminazione ({identificativo})", ex)
            return False


class SezioneRadio(SezioneBase):
    def __init__(self, db, nome, tabella, client=None, massimo=0):
        super().__init__(db)
        self.nome = nome
        self.tabella = tabella
        self.client = client
        self.massimo = massimo
        self._indirizzi_remoti = {}
        self._indirizzi_cercati = set()

    def prepara(self, voci_remote):
        try:
            self.ricorda_id_remoti(voci_remote)
            self._indirizzi_remoti = {}
            if self.client is None:
                return True
            for riga in self.db.leggi_tutti(f"SELECT id, url FROM {self.tabella} WHERE uuid IS NULL OR uuid = ''"):
                if riga[1] in self._indirizzi_cercati:
                    continue
                self._indirizzi_cercati.add(riga[1])
                try:
                    trovato = self.client.uuid_per_indirizzo(riga[1])
                    if trovato:
                        self.db.esegui(f"UPDATE {self.tabella} SET uuid = ? WHERE id = ?", (trovato, int(riga[0])))
                except Exception as exRiga:
                    scrivi_log(f"SezioneRadio.prepara identificativo ({riga[1]})", exRiga)
            locali = {
                str(riga[0])
                for riga in self.db.leggi_tutti(f"SELECT uuid FROM {self.tabella} WHERE uuid IS NOT NULL AND uuid <> ''")
            }
            mancanti = []
            for voce in voci_remote or []:
                identificativo = testo(voce, "id")
                if identificativo and identificativo not in locali and not vero(voce, "eliminato"):
                    mancanti.append(identificativo)
            if mancanti:
                self._indirizzi_remoti = self.client.indirizzi_per_uuid(mancanti)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneRadio.prepara ({self.nome})", ex)
            return False

    def stato_locale(self):
        stato = {}
        try:
            stato.update(self._eliminazioni())
            for riga in self.db.leggi_tutti(
                f"SELECT uuid, sync_modificato FROM {self.tabella} WHERE uuid IS NOT NULL AND uuid <> ''"
            ):
                stato[str(riga[0])] = (leggi_utc(riga[1]), False)
        except Exception as ex:
            scrivi_log(f"SezioneRadio.stato_locale ({self.nome})", ex)
        return stato

    def voce_locale(self, identificativo):
        try:
            riga = self.db.leggi_uno(
                f"SELECT name, sync_modificato FROM {self.tabella} WHERE uuid = ?",
                (identificativo,),
            )
            if riga is None:
                return None
            return {
                "id": identificativo,
                "modificato": formato_utc(leggi_utc(riga[1])),
                "eliminato": False,
                "nome": riga[0] or "",
            }
        except Exception as ex:
            scrivi_log(f"SezioneRadio.voce_locale ({identificativo})", ex)
            return None

    def applica(self, voce):
        try:
            identificativo = testo(voce, "id")
            modificato = formato_utc(leggi_utc(testo(voce, "modificato")))
            nome = testo(voce, "nome") or identificativo
            with closing(self.db.get_connection()) as connessione, connessione:
                esistente = connessione.execute(
                    f"SELECT id FROM {self.tabella} WHERE uuid = ?", (identificativo,)
                ).fetchone()
                if esistente is not None:
                    connessione.execute(
                        f"UPDATE {self.tabella} SET name = ?, sync_modificato = ? WHERE id = ?",
                        (nome, modificato, int(esistente[0])),
                    )
                else:
                    indirizzo = self._indirizzi_remoti.get(identificativo, "")
                    if not indirizzo:
                        return False
                    stesso = connessione.execute(
                        f"SELECT id, uuid FROM {self.tabella} WHERE url = ?", (indirizzo,)
                    ).fetchone()
                    if stesso is not None and str(stesso[1] or "") in self.id_remoti:
                        return False
                    if stesso is not None:
                        connessione.execute(
                            f"UPDATE {self.tabella} SET name = ?, uuid = ?, sync_modificato = ? WHERE id = ?",
                            (nome, identificativo, modificato, int(stesso[0])),
                        )
                    else:
                        connessione.execute(
                            f"INSERT INTO {self.tabella} (name, url, uuid, sync_modificato) VALUES (?, ?, ?, ?)",
                            (nome, indirizzo, identificativo, modificato),
                        )
                self._togli_eliminazione(connessione, identificativo)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneRadio.applica ({self.nome}, {testo(voce, 'id')})", ex)
            return False

    def applica_eliminazione(self, identificativo, data):
        try:
            with closing(self.db.get_connection()) as connessione, connessione:
                connessione.execute(f"DELETE FROM {self.tabella} WHERE uuid = ?", (identificativo,))
                self._registra_eliminazione(connessione, identificativo, data)
            return True
        except Exception as ex:
            scrivi_log(f"SezioneRadio.applica_eliminazione ({self.nome}, {identificativo})", ex)
            return False

    def rifinisci(self, voci):
        try:
            if self.massimo <= 0:
                return voci
            self.db.esegui(
                f"DELETE FROM {self.tabella} WHERE id NOT IN "
                f"(SELECT id FROM {self.tabella} ORDER BY sync_modificato DESC, id DESC LIMIT ?)",
                (self.massimo,),
            )
            presenti = [voce for voce in voci if not vero(voce, "eliminato")]
            eliminate = [voce for voce in voci if vero(voce, "eliminato")]
            presenti.sort(key=lambda voce: leggi_utc(testo(voce, "modificato")), reverse=True)
            return eliminate + presenti[: self.massimo]
        except Exception as ex:
            scrivi_log(f"SezioneRadio.rifinisci ({self.nome})", ex)
            return voci
