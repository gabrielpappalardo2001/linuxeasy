import re
import time
import unicodedata
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from app.core.log import scrivi_log

TIPO_TELEFONO = "telefono"
TIPO_EMAIL = "email"
TIPO_INDIRIZZO = "indirizzo"
TIPO_SITO = "sito"
TIPI_VALORE = (TIPO_TELEFONO, TIPO_EMAIL, TIPO_INDIRIZZO, TIPO_SITO)
LIMITE_RICERCHE = 30
LIMITE_RECENTI = 30
ANNO_SCONOSCIUTO = 1900


def normalizza(testo):
    try:
        valore = unicodedata.normalize("NFKD", str(testo or ""))
        valore = "".join(carattere for carattere in valore if not unicodedata.combining(carattere)).lower()
        return " ".join(re.sub(r"[^a-z0-9@.+_-]+", " ", valore).split())
    except Exception as ex:
        scrivi_log(f"rubrica_store.normalizza ({testo})", ex)
        return ""


def solo_cifre(testo):
    try:
        valore = str(testo or "").strip()
        prefisso = "+" if valore.startswith("+") else ""
        return prefisso + re.sub(r"\D", "", valore)
    except Exception as ex:
        scrivi_log(f"rubrica_store.solo_cifre ({testo})", ex)
        return ""


@dataclass
class Valore:
    tipo: str
    etichetta: str
    valore: str
    id: int = 0


@dataclass
class Contatto:
    id: int = 0
    nome: str = ""
    cognome: str = ""
    azienda: str = ""
    compleanno: Optional[date] = None
    anno_noto: bool = True
    note: str = ""
    preferito: bool = False
    valori: List[Valore] = field(default_factory=list)

    def nome_completo(self):
        try:
            completo = " ".join(parte for parte in (self.nome, self.cognome) if parte)
            return completo or self.azienda or "Contatto senza nome"
        except Exception as ex:
            scrivi_log("Contatto.nome_completo", ex)
            return "Contatto"

    def nome_ordinato(self):
        try:
            completo = " ".join(parte for parte in (self.cognome, self.nome) if parte)
            return completo or self.azienda or "Contatto senza nome"
        except Exception as ex:
            scrivi_log("Contatto.nome_ordinato", ex)
            return self.nome_completo()

    def di_tipo(self, tipo):
        return [valore for valore in self.valori if valore.tipo == tipo]


class RubricaStore:
    def __init__(self, db):
        self.db = db

    def _chiave_ordinamento(self, contatto):
        try:
            return normalizza(contatto.nome_ordinato())
        except Exception as ex:
            scrivi_log("RubricaStore._chiave_ordinamento", ex)
            return ""

    def _testo_ricerca(self, contatto):
        try:
            parti = [contatto.nome, contatto.cognome, contatto.azienda, contatto.note]
            for valore in contatto.valori:
                parti.append(valore.valore)
                parti.append(valore.etichetta)
                if valore.tipo == TIPO_TELEFONO:
                    parti.append(solo_cifre(valore.valore).lstrip("+"))
            return normalizza(" ".join(parti))
        except Exception as ex:
            scrivi_log("RubricaStore._testo_ricerca", ex)
            return ""

    def _compleanno_testo(self, contatto):
        try:
            if contatto.compleanno is None:
                return ""
            anno = contatto.compleanno.year if contatto.anno_noto else ANNO_SCONOSCIUTO
            return f"{anno:04d}-{contatto.compleanno.month:02d}-{contatto.compleanno.day:02d}"
        except Exception as ex:
            scrivi_log("RubricaStore._compleanno_testo", ex)
            return ""

    def _leggi_compleanno(self, testo):
        try:
            if not testo:
                return None, True
            anno, mese, giorno = (int(parte) for parte in str(testo).split("-"))
            if anno == ANNO_SCONOSCIUTO:
                return date(2000, mese, giorno), False
            return date(anno, mese, giorno), True
        except Exception as ex:
            scrivi_log(f"RubricaStore._leggi_compleanno ({testo})", ex)
            return None, True

    def _contatti(self, condizione="1 = 1", parametri=(), ordine="sort_key", limite=None):
        try:
            sql = (
                "SELECT id, first_name, last_name, company, birthday, notes, favorite FROM contacts "
                f"WHERE {condizione} ORDER BY {ordine}"
            )
            if limite:
                sql += f" LIMIT {int(limite)}"
            righe = self.db.leggi_tutti(sql, tuple(parametri))
            if not righe:
                return []
            identificativi = [int(riga[0]) for riga in righe]
            valori = {}
            for inizio in range(0, len(identificativi), 400):
                blocco = identificativi[inizio:inizio + 400]
                segnaposto = ", ".join("?" for _id in blocco)
                for riga in self.db.leggi_tutti(
                    f"SELECT contact_id, kind, label, value, id FROM contact_values WHERE contact_id IN ({segnaposto}) "
                    "ORDER BY contact_id, position, id",
                    tuple(blocco),
                ):
                    valori.setdefault(int(riga[0]), []).append(Valore(riga[1], riga[2], riga[3], int(riga[4])))
            contatti = []
            for riga in righe:
                compleanno, anno_noto = self._leggi_compleanno(riga[4])
                contatti.append(
                    Contatto(
                        id=int(riga[0]),
                        nome=riga[1] or "",
                        cognome=riga[2] or "",
                        azienda=riga[3] or "",
                        compleanno=compleanno,
                        anno_noto=anno_noto,
                        note=riga[5] or "",
                        preferito=bool(riga[6]),
                        valori=valori.get(int(riga[0]), []),
                    )
                )
            return contatti
        except Exception as ex:
            scrivi_log("RubricaStore._contatti", ex)
            return []

    def numero(self):
        try:
            riga = self.db.leggi_uno("SELECT COUNT(*) FROM contacts")
            return int(riga[0]) if riga else 0
        except Exception as ex:
            scrivi_log("RubricaStore.numero", ex)
            return 0

    def tutti(self):
        return self._contatti()

    def iniziali(self):
        try:
            conteggi = {}
            for contatto in self._contatti():
                chiave = self._chiave_ordinamento(contatto)
                lettera = chiave[0].upper() if chiave and "a" <= chiave[0] <= "z" else "#"
                conteggi[lettera] = conteggi.get(lettera, 0) + 1
            return sorted(conteggi.items(), key=lambda coppia: (coppia[0] == "#", coppia[0]))
        except Exception as ex:
            scrivi_log("RubricaStore.iniziali", ex)
            return []

    def per_iniziale(self, lettera):
        try:
            if lettera == "#":
                return [
                    contatto
                    for contatto in self._contatti()
                    if not (self._chiave_ordinamento(contatto)[:1] and "a" <= self._chiave_ordinamento(contatto)[0] <= "z")
                ]
            return self._contatti("sort_key LIKE ?", (f"{lettera.lower()}%",))
        except Exception as ex:
            scrivi_log(f"RubricaStore.per_iniziale ({lettera})", ex)
            return []

    def contatto(self, identificativo):
        try:
            elenco = self._contatti("id = ?", (int(identificativo),))
            return elenco[0] if elenco else None
        except Exception as ex:
            scrivi_log(f"RubricaStore.contatto ({identificativo})", ex)
            return None

    def preferiti(self):
        return self._contatti("favorite = 1")

    def recenti(self):
        return self._contatti("last_viewed > 0", (), "last_viewed DESC", LIMITE_RECENTI)

    def cerca(self, testo):
        try:
            parole = normalizza(testo).split()
            cifre = solo_cifre(testo).lstrip("+")
            if not parole:
                return []
            condizioni = []
            parametri = []
            for parola in parole:
                condizioni.append("search_text LIKE ?")
                parametri.append(f"%{parola}%")
            condizione = " AND ".join(condizioni)
            if len(cifre) >= 3 and cifre == "".join(parole):
                condizione = f"({condizione}) OR search_text LIKE ?"
                parametri.append(f"%{cifre}%")
            return self._contatti(condizione, parametri)
        except Exception as ex:
            scrivi_log(f"RubricaStore.cerca ({testo})", ex)
            return []

    def _scrivi_valori(self, connessione, contatto):
        connessione.execute("DELETE FROM contact_values WHERE contact_id = ?", (contatto.id,))
        for posizione, valore in enumerate(contatto.valori):
            if not str(valore.valore or "").strip():
                continue
            connessione.execute(
                "INSERT INTO contact_values (contact_id, kind, label, value, position) VALUES (?, ?, ?, ?, ?)",
                (contatto.id, valore.tipo, valore.etichetta.strip(), valore.valore.strip(), posizione),
            )

    def salva(self, contatto):
        try:
            adesso = time.time()
            with closing(self.db.get_connection()) as connessione, connessione:
                parametri = (
                    contatto.nome.strip(),
                    contatto.cognome.strip(),
                    contatto.azienda.strip(),
                    self._compleanno_testo(contatto),
                    contatto.note.strip(),
                    1 if contatto.preferito else 0,
                    self._chiave_ordinamento(contatto),
                    self._testo_ricerca(contatto),
                )
                if contatto.id:
                    connessione.execute(
                        "UPDATE contacts SET first_name = ?, last_name = ?, company = ?, birthday = ?, notes = ?, "
                        "favorite = ?, sort_key = ?, search_text = ?, updated_at = ? WHERE id = ?",
                        parametri + (adesso, contatto.id),
                    )
                else:
                    cursore = connessione.execute(
                        "INSERT INTO contacts (first_name, last_name, company, birthday, notes, favorite, sort_key, "
                        "search_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        parametri + (adesso, adesso),
                    )
                    contatto.id = int(cursore.lastrowid)
                self._scrivi_valori(connessione, contatto)
            return contatto.id
        except Exception as ex:
            scrivi_log(f"RubricaStore.salva ({contatto.nome_completo()})", ex)
            return 0

    def elimina(self, identificativo):
        try:
            return self.db.transazione(
                [
                    ("DELETE FROM contact_values WHERE contact_id = ?", (int(identificativo),)),
                    ("DELETE FROM contacts WHERE id = ?", (int(identificativo),)),
                ]
            )
        except Exception as ex:
            scrivi_log(f"RubricaStore.elimina ({identificativo})", ex)
            return False

    def imposta_preferito(self, identificativo, preferito):
        try:
            return self.db.esegui(
                "UPDATE contacts SET favorite = ? WHERE id = ?",
                (1 if preferito else 0, int(identificativo)),
            )
        except Exception as ex:
            scrivi_log(f"RubricaStore.imposta_preferito ({identificativo})", ex)
            return False

    def segna_consultato(self, identificativo):
        try:
            return self.db.esegui("UPDATE contacts SET last_viewed = ? WHERE id = ?", (time.time(), int(identificativo)))
        except Exception as ex:
            scrivi_log(f"RubricaStore.segna_consultato ({identificativo})", ex)
            return False

    def rimuovi_da_recenti(self, identificativo):
        try:
            return self.db.esegui("UPDATE contacts SET last_viewed = 0 WHERE id = ?", (int(identificativo),))
        except Exception as ex:
            scrivi_log(f"RubricaStore.rimuovi_da_recenti ({identificativo})", ex)
            return False

    def svuota_recenti(self):
        try:
            return self.db.esegui("UPDATE contacts SET last_viewed = 0")
        except Exception as ex:
            scrivi_log("RubricaStore.svuota_recenti", ex)
            return False

    def ricerche(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT query FROM contacts_search_history ORDER BY used_at DESC LIMIT ?",
                (LIMITE_RICERCHE,),
            )
            return [riga[0] for riga in righe]
        except Exception as ex:
            scrivi_log("RubricaStore.ricerche", ex)
            return []

    def aggiungi_ricerca(self, testo):
        try:
            valore = " ".join(str(testo or "").split())
            if not valore:
                return False
            return self.db.transazione(
                [
                    (
                        "INSERT INTO contacts_search_history (query, used_at) VALUES (?, ?) "
                        "ON CONFLICT (query) DO UPDATE SET used_at = excluded.used_at",
                        (valore, time.time()),
                    ),
                    (
                        "DELETE FROM contacts_search_history WHERE id NOT IN "
                        "(SELECT id FROM contacts_search_history ORDER BY used_at DESC LIMIT ?)",
                        (LIMITE_RICERCHE,),
                    ),
                ]
            )
        except Exception as ex:
            scrivi_log(f"RubricaStore.aggiungi_ricerca ({testo})", ex)
            return False

    def rimuovi_ricerca(self, testo):
        try:
            return self.db.esegui("DELETE FROM contacts_search_history WHERE query = ?", (testo,))
        except Exception as ex:
            scrivi_log(f"RubricaStore.rimuovi_ricerca ({testo})", ex)
            return False

    def svuota_ricerche(self):
        try:
            return self.db.esegui("DELETE FROM contacts_search_history")
        except Exception as ex:
            scrivi_log("RubricaStore.svuota_ricerche", ex)
            return False
