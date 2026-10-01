import threading
import time
from datetime import datetime

from app.core.database import Database
from app.core.log import scrivi_log
from app.radio import regioni
from app.radio.radio_browser_client import ErroreRadio, RadioBrowserClient

DURATA_CACHE = 1800
LIMITE_CRONOLOGIA = 20
LIMITE_RECENTI = 40
SEZIONE_PREFERITI = "radioPreferiti"
SEZIONE_RECENTI = "radioRecenti"


def _ora_utc():
    try:
        adesso = datetime.utcnow()
        return adesso.strftime("%Y-%m-%dT%H:%M:%S") + f".{adesso.microsecond // 1000:03d}Z"
    except Exception as ex:
        scrivi_log("stations._ora_utc", ex)
        return "1970-01-01T00:00:00.000Z"


class RadioManager:
    def __init__(self, db=None, client=None):
        self.db = db if db else Database()
        self.client = client if client else RadioBrowserClient()
        self._blocco = threading.Lock()
        self._cache_italiane = None
        self._ora_cache = 0.0

    def _stazioni_italiane(self, forza=False):
        try:
            with self._blocco:
                if (
                    not forza
                    and self._cache_italiane is not None
                    and time.monotonic() - self._ora_cache < DURATA_CACHE
                ):
                    return list(self._cache_italiane)
            stazioni = self.client.stazioni_per_paese("IT")
            for stazione in stazioni:
                stazione["region"] = regioni.classifica(stazione.get("state"), stazione.get("name"), stazione.get("tags"))
            with self._blocco:
                self._cache_italiane = list(stazioni)
                self._ora_cache = time.monotonic()
            return stazioni
        except ErroreRadio:
            raise
        except Exception as ex:
            scrivi_log("RadioManager._stazioni_italiane", ex)
            raise ErroreRadio(str(ex)) from ex

    def get_italian_stations(self):
        return self._stazioni_italiane()

    def get_italian_regions(self):
        try:
            conteggi = {}
            for stazione in self._stazioni_italiane():
                nome = stazione.get("region") or regioni.REGIONE_NON_INDICATA
                conteggi[nome] = conteggi.get(nome, 0) + 1
            elenco = [
                {"name": nome, "count": conteggi[nome]}
                for nome in regioni.elenco_regioni()
                if conteggi.get(nome, 0) > 0
            ]
            if conteggi.get(regioni.REGIONE_NON_INDICATA, 0) > 0:
                elenco.append(
                    {"name": regioni.REGIONE_NON_INDICATA, "count": conteggi[regioni.REGIONE_NON_INDICATA]}
                )
            return elenco
        except ErroreRadio:
            raise
        except Exception as ex:
            scrivi_log("RadioManager.get_italian_regions", ex)
            raise ErroreRadio(str(ex)) from ex

    def get_stations_by_region(self, region_name):
        try:
            if region_name == regioni.REGIONE_NON_INDICATA:
                return [stazione for stazione in self._stazioni_italiane() if not stazione.get("region")]
            return [stazione for stazione in self._stazioni_italiane() if stazione.get("region") == region_name]
        except ErroreRadio:
            raise
        except Exception as ex:
            scrivi_log(f"RadioManager.get_stations_by_region ({region_name})", ex)
            raise ErroreRadio(str(ex)) from ex

    def get_international_stations(self):
        try:
            return self.client.stazioni_popolari(500, "IT")
        except ErroreRadio:
            raise
        except Exception as ex:
            scrivi_log("RadioManager.get_international_stations", ex)
            raise ErroreRadio(str(ex)) from ex

    def search_stations(self, query):
        try:
            testo = str(query or "").strip()
            if not testo:
                return []
            self.add_search_history(testo)
            return self.client.cerca(testo)
        except ErroreRadio:
            raise
        except Exception as ex:
            scrivi_log(f"RadioManager.search_stations ({query})", ex)
            raise ErroreRadio(str(ex)) from ex

    def register_click(self, uuid):
        try:
            self.client.registra_click(uuid)
        except Exception as ex:
            scrivi_log(f"RadioManager.register_click ({uuid})", ex)

    def get_search_history(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT query FROM radio_search_history ORDER BY id DESC LIMIT ?",
                (LIMITE_CRONOLOGIA,),
            )
            return [riga[0] for riga in righe]
        except Exception as ex:
            scrivi_log("RadioManager.get_search_history", ex)
            return []

    def add_search_history(self, query):
        try:
            testo = str(query or "").strip()
            if not testo:
                return False
            return self.db.transazione(
                [
                    ("DELETE FROM radio_search_history WHERE query = ?", (testo,)),
                    ("INSERT INTO radio_search_history (query) VALUES (?)", (testo,)),
                    (
                        "DELETE FROM radio_search_history WHERE id NOT IN "
                        "(SELECT id FROM radio_search_history ORDER BY id DESC LIMIT ?)",
                        (LIMITE_CRONOLOGIA,),
                    ),
                ]
            )
        except Exception as ex:
            scrivi_log(f"RadioManager.add_search_history ({query})", ex)
            return False

    def remove_search_history(self, query):
        try:
            return self.db.esegui("DELETE FROM radio_search_history WHERE query = ?", (query,))
        except Exception as ex:
            scrivi_log(f"RadioManager.remove_search_history ({query})", ex)
            return False

    def clear_search_history(self):
        try:
            return self.db.esegui("DELETE FROM radio_search_history")
        except Exception as ex:
            scrivi_log("RadioManager.clear_search_history", ex)
            return False

    def _uuid_noto(self, station):
        try:
            if not isinstance(station, dict):
                return ""
            uuid = str(station.get("uuid") or "").strip()
            if uuid:
                return uuid
            url = station.get("url") or ""
            if not url:
                return ""
            for tabella in ("radio_favorites", "radio_recent"):
                riga = self.db.leggi_uno(f"SELECT uuid FROM {tabella} WHERE url = ? AND uuid <> ''", (url,))
                if riga is not None and riga[0]:
                    return str(riga[0])
            return ""
        except Exception as ex:
            scrivi_log("RadioManager._uuid_noto", ex)
            return ""

    def get_favorites(self):
        try:
            righe = self.db.leggi_tutti("SELECT name, url, uuid FROM radio_favorites ORDER BY name COLLATE NOCASE")
            return [{"name": riga[0], "url": riga[1], "uuid": riga[2] or ""} for riga in righe]
        except Exception as ex:
            scrivi_log("RadioManager.get_favorites", ex)
            return []

    def is_favorite(self, url):
        try:
            if not url:
                return False
            return self.db.leggi_uno("SELECT 1 FROM radio_favorites WHERE url = ?", (url,)) is not None
        except Exception as ex:
            scrivi_log(f"RadioManager.is_favorite ({url})", ex)
            return False

    def add_favorite(self, station):
        try:
            nome = station.get("name") if isinstance(station, dict) else ""
            url = station.get("url") if isinstance(station, dict) else ""
            if not url or not nome:
                return False
            uuid = self._uuid_noto(station)
            istruzioni = [
                (
                    "INSERT OR IGNORE INTO radio_favorites (name, url, uuid, sync_modificato) VALUES (?, ?, ?, ?)",
                    (nome, url, uuid, _ora_utc()),
                )
            ]
            if uuid:
                istruzioni.append(("UPDATE radio_favorites SET uuid = ? WHERE url = ? AND uuid = ''", (uuid, url)))
                istruzioni.append(
                    ("DELETE FROM sync_eliminati WHERE sezione = ? AND sync_id = ?", (SEZIONE_PREFERITI, uuid))
                )
            return self.db.transazione(istruzioni)
        except Exception as ex:
            scrivi_log("RadioManager.add_favorite", ex)
            return False

    def remove_favorite(self, station):
        try:
            url = station.get("url") if isinstance(station, dict) else ""
            if not url:
                return False
            riga = self.db.leggi_uno("SELECT uuid FROM radio_favorites WHERE url = ?", (url,))
            istruzioni = [("DELETE FROM radio_favorites WHERE url = ?", (url,))]
            if riga is not None and riga[0]:
                istruzioni.append(
                    (
                        "INSERT OR REPLACE INTO sync_eliminati (sezione, sync_id, data) VALUES (?, ?, ?)",
                        (SEZIONE_PREFERITI, riga[0], _ora_utc()),
                    )
                )
            return self.db.transazione(istruzioni)
        except Exception as ex:
            scrivi_log("RadioManager.remove_favorite", ex)
            return False

    def get_recent(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT name, url, uuid FROM radio_recent ORDER BY sync_modificato DESC, id DESC LIMIT ?",
                (LIMITE_RECENTI,),
            )
            return [{"name": riga[0], "url": riga[1], "uuid": riga[2] or ""} for riga in righe]
        except Exception as ex:
            scrivi_log("RadioManager.get_recent", ex)
            return []

    def add_recent(self, station):
        try:
            nome = station.get("name") if isinstance(station, dict) else ""
            url = station.get("url") if isinstance(station, dict) else ""
            if not url or not nome:
                return False
            uuid = self._uuid_noto(station)
            istruzioni = [
                ("DELETE FROM radio_recent WHERE url = ?", (url,)),
                (
                    "INSERT INTO radio_recent (name, url, uuid, sync_modificato) VALUES (?, ?, ?, ?)",
                    (nome, url, uuid, _ora_utc()),
                ),
                (
                    "DELETE FROM radio_recent WHERE id NOT IN "
                    "(SELECT id FROM radio_recent ORDER BY sync_modificato DESC, id DESC LIMIT ?)",
                    (LIMITE_RECENTI,),
                ),
            ]
            if uuid:
                istruzioni.append(
                    ("DELETE FROM sync_eliminati WHERE sezione = ? AND sync_id = ?", (SEZIONE_RECENTI, uuid))
                )
            return self.db.transazione(istruzioni)
        except Exception as ex:
            scrivi_log("RadioManager.add_recent", ex)
            return False

    def remove_recent(self, station):
        try:
            url = station.get("url") if isinstance(station, dict) else ""
            if not url:
                return False
            riga = self.db.leggi_uno("SELECT uuid FROM radio_recent WHERE url = ?", (url,))
            istruzioni = [("DELETE FROM radio_recent WHERE url = ?", (url,))]
            if riga is not None and riga[0]:
                istruzioni.append(
                    (
                        "INSERT OR REPLACE INTO sync_eliminati (sezione, sync_id, data) VALUES (?, ?, ?)",
                        (SEZIONE_RECENTI, riga[0], _ora_utc()),
                    )
                )
            return self.db.transazione(istruzioni)
        except Exception as ex:
            scrivi_log("RadioManager.remove_recent", ex)
            return False

    def clear_recent(self):
        try:
            return self.db.transazione(
                [
                    (
                        "INSERT OR REPLACE INTO sync_eliminati (sezione, sync_id, data) "
                        "SELECT ?, uuid, ? FROM radio_recent WHERE uuid <> ''",
                        (SEZIONE_RECENTI, _ora_utc()),
                    ),
                    ("DELETE FROM radio_recent", ()),
                ]
            )
        except Exception as ex:
            scrivi_log("RadioManager.clear_recent", ex)
            return False
