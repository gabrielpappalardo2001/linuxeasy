import time

from app.core.log import scrivi_log
from app.librivox.librivox_catalog import Libro

LIMITE_RECENTI = 30


class LibriVoxLibrary:
    def __init__(self, db, catalogo=None):
        self.db = db
        self.catalogo = catalogo

    def _libro(self, identificativo, titolo, autori, lingua):
        try:
            if self.catalogo is not None:
                trovato = self.catalogo.libro(identificativo)
                if trovato is not None:
                    return trovato
            return Libro(id=int(identificativo), title=titolo, authors=autori, language=lingua)
        except Exception as ex:
            scrivi_log(f"LibriVoxLibrary._libro ({identificativo})", ex)
            return Libro(id=int(identificativo), title=str(titolo), authors=str(autori), language=str(lingua))

    def elenco_preferiti(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT book_id, title, authors, language FROM librivox_favorites ORDER BY title COLLATE NOCASE"
            )
            return [self._libro(riga[0], riga[1], riga[2], riga[3]) for riga in righe]
        except Exception as ex:
            scrivi_log("LibriVoxLibrary.elenco_preferiti", ex)
            return []

    def preferito(self, id_libro):
        try:
            return self.db.leggi_uno("SELECT 1 FROM librivox_favorites WHERE book_id = ?", (int(id_libro),)) is not None
        except Exception as ex:
            scrivi_log(f"LibriVoxLibrary.preferito ({id_libro})", ex)
            return False

    def aggiungi_preferito(self, libro):
        try:
            return self.db.esegui(
                "INSERT INTO librivox_favorites (book_id, title, authors, language, added_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (book_id) DO UPDATE SET title = excluded.title, authors = excluded.authors, "
                "language = excluded.language",
                (int(libro.id), libro.title, libro.authors, libro.language, time.time()),
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxLibrary.aggiungi_preferito ({getattr(libro, 'id', '')})", ex)
            return False

    def rimuovi_preferito(self, id_libro):
        try:
            return self.db.esegui("DELETE FROM librivox_favorites WHERE book_id = ?", (int(id_libro),))
        except Exception as ex:
            scrivi_log(f"LibriVoxLibrary.rimuovi_preferito ({id_libro})", ex)
            return False

    def elenco_recenti(self):
        risultati = []
        try:
            righe = self.db.leggi_tutti(
                "SELECT book_id, title, authors, language, chapter_index, chapter_title FROM librivox_recent "
                "ORDER BY last_used DESC LIMIT ?",
                (LIMITE_RECENTI,),
            )
            for riga in righe:
                risultati.append(
                    {
                        "libro": self._libro(riga[0], riga[1], riga[2], riga[3]),
                        "capitolo": int(riga[4] or 0),
                        "titolo_capitolo": riga[5] or "",
                    }
                )
        except Exception as ex:
            scrivi_log("LibriVoxLibrary.elenco_recenti", ex)
        return risultati

    def progresso(self, id_libro):
        try:
            riga = self.db.leggi_uno(
                "SELECT chapter_index, chapter_title FROM librivox_recent WHERE book_id = ?",
                (int(id_libro),),
            )
            if riga is None:
                return None
            return {"capitolo": int(riga[0] or 0), "titolo_capitolo": riga[1] or ""}
        except Exception as ex:
            scrivi_log(f"LibriVoxLibrary.progresso ({id_libro})", ex)
            return None

    def registra_ascolto(self, libro, indice_capitolo, titolo_capitolo):
        try:
            if not self.db.esegui(
                "INSERT INTO librivox_recent (book_id, title, authors, language, chapter_index, chapter_title, last_used) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (book_id) DO UPDATE SET title = excluded.title, authors = excluded.authors, "
                "language = excluded.language, chapter_index = excluded.chapter_index, "
                "chapter_title = excluded.chapter_title, last_used = excluded.last_used",
                (
                    int(libro.id),
                    libro.title,
                    libro.authors,
                    libro.language,
                    int(indice_capitolo),
                    str(titolo_capitolo or ""),
                    time.time(),
                ),
            ):
                return False
            return self.db.esegui(
                "DELETE FROM librivox_recent WHERE book_id NOT IN "
                "(SELECT book_id FROM librivox_recent ORDER BY last_used DESC LIMIT ?)",
                (LIMITE_RECENTI,),
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxLibrary.registra_ascolto ({getattr(libro, 'id', '')})", ex)
            return False

    def rimuovi_recente(self, id_libro):
        try:
            return self.db.esegui("DELETE FROM librivox_recent WHERE book_id = ?", (int(id_libro),))
        except Exception as ex:
            scrivi_log(f"LibriVoxLibrary.rimuovi_recente ({id_libro})", ex)
            return False

    def svuota_recenti(self):
        try:
            return self.db.esegui("DELETE FROM librivox_recent")
        except Exception as ex:
            scrivi_log("LibriVoxLibrary.svuota_recenti", ex)
            return False
