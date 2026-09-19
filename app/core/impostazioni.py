import threading
import time

from app.core.log import scrivi_log

CHIAVE_NOTIFICHE_PODCAST = "notifiche_podcast"
CHIAVE_NOTIFICHE_NOTIZIE = "notifiche_notizie"
CHIAVE_NOTIFICHE_AGENDA = "notifiche_agenda"
CHIAVE_RICORDA_VOLUME = "player_ricorda_volume"
CHIAVE_RICORDA_POSIZIONE = "player_ricorda_posizione"
CHIAVE_VOLUME = "player_volume"
CHIAVE_ASCOLTO_SOTTOFONDO = "ask_background_escape"
MASSIMO_POSIZIONI = 500


class Impostazioni:
    def __init__(self, db):
        self.db = db
        self._memoria = {}
        self._blocco = threading.RLock()

    def leggi(self, chiave, predefinito=""):
        try:
            with self._blocco:
                if chiave in self._memoria:
                    return self._memoria[chiave]
            if self.db is None:
                return predefinito
            valore = self.db.leggi_impostazione(chiave, predefinito)
            with self._blocco:
                self._memoria[chiave] = valore
            return valore
        except Exception as ex:
            scrivi_log(f"Impostazioni.leggi ({chiave})", ex)
            return predefinito

    def scrivi(self, chiave, valore):
        try:
            if self.db is None:
                return False
            testo = str(valore)
            if not self.db.scrivi_impostazione(chiave, testo):
                return False
            with self._blocco:
                self._memoria[chiave] = testo
            return True
        except Exception as ex:
            scrivi_log(f"Impostazioni.scrivi ({chiave})", ex)
            return False

    def attivo(self, chiave, predefinito=False):
        try:
            return self.leggi(chiave, "1" if predefinito else "0") == "1"
        except Exception as ex:
            scrivi_log(f"Impostazioni.attivo ({chiave})", ex)
            return bool(predefinito)

    def imposta_attivo(self, chiave, valore):
        try:
            return self.scrivi(chiave, "1" if valore else "0")
        except Exception as ex:
            scrivi_log(f"Impostazioni.imposta_attivo ({chiave})", ex)
            return False

    def notifiche_podcast(self):
        return self.attivo(CHIAVE_NOTIFICHE_PODCAST, True)

    def notifiche_notizie(self):
        return self.attivo(CHIAVE_NOTIFICHE_NOTIZIE, True)

    def notifiche_agenda(self):
        return self.attivo(CHIAVE_NOTIFICHE_AGENDA, True)

    def ricorda_volume(self):
        return self.attivo(CHIAVE_RICORDA_VOLUME, False)

    def ricorda_posizione(self):
        return self.attivo(CHIAVE_RICORDA_POSIZIONE, False)

    def chiedi_ascolto_sottofondo(self):
        return self.attivo(CHIAVE_ASCOLTO_SOTTOFONDO, False)

    def volume_salvato(self):
        try:
            testo = self.leggi(CHIAVE_VOLUME, "")
            if not testo:
                return None
            return max(0.0, min(130.0, float(testo)))
        except Exception as ex:
            scrivi_log("Impostazioni.volume_salvato", ex)
            return None

    def salva_volume(self, valore):
        try:
            numero = max(0.0, min(130.0, float(valore)))
            return self.scrivi(CHIAVE_VOLUME, f"{numero:g}")
        except Exception as ex:
            scrivi_log(f"Impostazioni.salva_volume ({valore})", ex)
            return False

    def posizione_salvata(self, indirizzo):
        try:
            if self.db is None or not indirizzo:
                return 0.0
            riga = self.db.leggi_uno("SELECT position FROM player_positions WHERE url = ?", (str(indirizzo),))
            if riga is None or riga[0] is None:
                return 0.0
            return max(0.0, float(riga[0]))
        except Exception as ex:
            scrivi_log(f"Impostazioni.posizione_salvata ({indirizzo})", ex)
            return 0.0

    def salva_posizione(self, indirizzo, titolo, posizione, durata):
        try:
            if self.db is None or not indirizzo:
                return False
            return self.db.transazione(
                [
                    (
                        "INSERT INTO player_positions (url, title, position, duration, updated_at) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT (url) DO UPDATE SET title = excluded.title, position = excluded.position, "
                        "duration = excluded.duration, updated_at = excluded.updated_at",
                        (str(indirizzo), str(titolo or ""), float(posizione), float(durata or 0), time.time()),
                    ),
                    (
                        "DELETE FROM player_positions WHERE url NOT IN "
                        "(SELECT url FROM player_positions ORDER BY updated_at DESC LIMIT ?)",
                        (MASSIMO_POSIZIONI,),
                    ),
                ]
            )
        except Exception as ex:
            scrivi_log(f"Impostazioni.salva_posizione ({indirizzo})", ex)
            return False

    def cancella_posizione(self, indirizzo):
        try:
            if self.db is None or not indirizzo:
                return False
            return self.db.esegui("DELETE FROM player_positions WHERE url = ?", (str(indirizzo),))
        except Exception as ex:
            scrivi_log(f"Impostazioni.cancella_posizione ({indirizzo})", ex)
            return False

    def numero_posizioni(self):
        try:
            if self.db is None:
                return 0
            riga = self.db.leggi_uno("SELECT COUNT(*) FROM player_positions")
            return int(riga[0]) if riga else 0
        except Exception as ex:
            scrivi_log("Impostazioni.numero_posizioni", ex)
            return 0

    def cancella_tutte_le_posizioni(self):
        try:
            if self.db is None:
                return False
            return self.db.esegui("DELETE FROM player_positions")
        except Exception as ex:
            scrivi_log("Impostazioni.cancella_tutte_le_posizioni", ex)
            return False
