import time
from dataclasses import dataclass

from app.core.log import scrivi_log

LIMITE_RICERCHE = 30
LIMITE_RECENTI = 50


@dataclass
class PaginaSalvata:
    title: str
    lingua: str
    description: str = ""


class WikipediaLibrary:
    def __init__(self, db):
        self.db = db

    def elenco_ricerche(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT query FROM wikipedia_search_history ORDER BY used_at DESC LIMIT ?",
                (LIMITE_RICERCHE,),
            )
            return [riga[0] for riga in righe]
        except Exception as ex:
            scrivi_log("WikipediaLibrary.elenco_ricerche", ex)
            return []

    def aggiungi_ricerca(self, testo):
        try:
            valore = " ".join(str(testo or "").split())
            if not valore:
                return False
            return self.db.transazione(
                [
                    (
                        "INSERT INTO wikipedia_search_history (query, used_at) VALUES (?, ?) "
                        "ON CONFLICT (query) DO UPDATE SET used_at = excluded.used_at",
                        (valore, time.time()),
                    ),
                    (
                        "DELETE FROM wikipedia_search_history WHERE id NOT IN "
                        "(SELECT id FROM wikipedia_search_history ORDER BY used_at DESC LIMIT ?)",
                        (LIMITE_RICERCHE,),
                    ),
                ]
            )
        except Exception as ex:
            scrivi_log(f"WikipediaLibrary.aggiungi_ricerca ({testo})", ex)
            return False

    def rimuovi_ricerca(self, testo):
        try:
            return self.db.esegui("DELETE FROM wikipedia_search_history WHERE query = ?", (testo,))
        except Exception as ex:
            scrivi_log(f"WikipediaLibrary.rimuovi_ricerca ({testo})", ex)
            return False

    def svuota_ricerche(self):
        try:
            return self.db.esegui("DELETE FROM wikipedia_search_history")
        except Exception as ex:
            scrivi_log("WikipediaLibrary.svuota_ricerche", ex)
            return False

    def _elenco(self, tabella, ordine, limite=None):
        try:
            sql = f"SELECT title, lang, description FROM {tabella} ORDER BY {ordine}"
            parametri = ()
            if limite:
                sql += " LIMIT ?"
                parametri = (limite,)
            return [PaginaSalvata(riga[0], riga[1], riga[2]) for riga in self.db.leggi_tutti(sql, parametri)]
        except Exception as ex:
            scrivi_log(f"WikipediaLibrary._elenco ({tabella})", ex)
            return []

    def _salva(self, tabella, colonna_tempo, titolo, lingua, descrizione):
        try:
            return self.db.esegui(
                f"INSERT INTO {tabella} (title, lang, description, {colonna_tempo}) VALUES (?, ?, ?, ?) "
                f"ON CONFLICT (lang, title) DO UPDATE SET "
                f"description = CASE WHEN excluded.description <> '' THEN excluded.description ELSE description END, "
                f"{colonna_tempo} = excluded.{colonna_tempo}",
                (titolo, lingua, descrizione or "", time.time()),
            )
        except Exception as ex:
            scrivi_log(f"WikipediaLibrary._salva ({tabella}, {titolo})", ex)
            return False

    def elenco_preferite(self):
        return self._elenco("wikipedia_favorites", "title COLLATE NOCASE")

    def preferita(self, titolo, lingua):
        try:
            return self.db.leggi_uno(
                "SELECT 1 FROM wikipedia_favorites WHERE title = ? AND lang = ?",
                (titolo, lingua),
            ) is not None
        except Exception as ex:
            scrivi_log(f"WikipediaLibrary.preferita ({titolo})", ex)
            return False

    def aggiungi_preferita(self, titolo, lingua, descrizione=""):
        return self._salva("wikipedia_favorites", "added_at", titolo, lingua, descrizione)

    def rimuovi_preferita(self, titolo, lingua):
        try:
            return self.db.esegui("DELETE FROM wikipedia_favorites WHERE title = ? AND lang = ?", (titolo, lingua))
        except Exception as ex:
            scrivi_log(f"WikipediaLibrary.rimuovi_preferita ({titolo})", ex)
            return False

    def elenco_recenti(self):
        return self._elenco("wikipedia_recent", "last_used DESC", LIMITE_RECENTI)

    def aggiungi_recente(self, titolo, lingua, descrizione=""):
        try:
            if not self._salva("wikipedia_recent", "last_used", titolo, lingua, descrizione):
                return False
            return self.db.esegui(
                "DELETE FROM wikipedia_recent WHERE rowid NOT IN "
                "(SELECT rowid FROM wikipedia_recent ORDER BY last_used DESC LIMIT ?)",
                (LIMITE_RECENTI,),
            )
        except Exception as ex:
            scrivi_log(f"WikipediaLibrary.aggiungi_recente ({titolo})", ex)
            return False

    def rimuovi_recente(self, titolo, lingua):
        try:
            return self.db.esegui("DELETE FROM wikipedia_recent WHERE title = ? AND lang = ?", (titolo, lingua))
        except Exception as ex:
            scrivi_log(f"WikipediaLibrary.rimuovi_recente ({titolo})", ex)
            return False

    def svuota_recenti(self):
        try:
            return self.db.esegui("DELETE FROM wikipedia_recent")
        except Exception as ex:
            scrivi_log("WikipediaLibrary.svuota_recenti", ex)
            return False
