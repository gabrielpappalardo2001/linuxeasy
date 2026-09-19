import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app.core.database import Database
from app.core.log import scrivi_log
from app.news.models import Article
from app.news.news_parser import NewsParser

ARTICOLI_PER_FONTE = 300
LIMITE_ELENCO = 300
LIMITE_RICERCA = 200
AGGIORNAMENTI_PARALLELI = 6

ESITO_OK = "ok"
ESITO_DUPLICATO = "duplicato"
ESITO_NON_VUOTA = "non_vuota"
ESITO_ERRORE = "errore"

COLONNE_ARTICOLO = (
    "a.id, a.title, a.link, a.summary, a.published, a.content, a.guid, a.source_url, "
    "s.name, s.category_id, COALESCE(c.name, s.category), a.is_read, a.full_text"
)
DA_ARTICOLI = (
    "FROM news_articles a JOIN news_sources s ON s.url = a.source_url "
    "LEFT JOIN news_categories c ON c.id = s.category_id"
)


def data_in_testo(valore):
    try:
        return valore.isoformat(timespec="seconds") if valore else ""
    except Exception as ex:
        scrivi_log("source_manager.data_in_testo", ex)
        return ""


def testo_in_data(valore):
    try:
        return datetime.fromisoformat(valore) if valore else None
    except Exception as ex:
        scrivi_log(f"source_manager.testo_in_data ({valore})", ex)
        return None


def _articolo_da_riga(riga):
    return Article(
        id=riga[0],
        title=riga[1],
        link=riga[2],
        summary=riga[3],
        published=testo_in_data(riga[4]),
        content=riga[5],
        guid=riga[6],
        source_url=riga[7],
        source_name=riga[8] or "",
        category_id=riga[9],
        category=riga[10] or "",
        is_read=bool(riga[11]),
        full_text=riga[12] or "",
    )


def _escapa_like(testo):
    return str(testo).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SourceManager:
    def __init__(self, db=None, parser=None):
        self.db = db if db else Database()
        self.parser = parser if parser else NewsParser()
        self._blocco_aggiornamento = threading.Lock()

    def get_categories(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT c.id, c.name, c.notify, "
                "(SELECT COUNT(*) FROM news_sources s WHERE s.category_id = c.id), "
                "(SELECT COUNT(*) FROM news_articles a JOIN news_sources s ON s.url = a.source_url "
                "WHERE s.category_id = c.id AND a.is_read = 0) "
                "FROM news_categories c ORDER BY c.position, c.name COLLATE NOCASE"
            )
            return [
                {"id": riga[0], "name": riga[1], "notify": bool(riga[2]), "sources": riga[3], "unread": riga[4]}
                for riga in righe
            ]
        except Exception as ex:
            scrivi_log("SourceManager.get_categories", ex)
            return []

    def get_category(self, category_id):
        try:
            for categoria in self.get_categories():
                if categoria["id"] == category_id:
                    return categoria
            return None
        except Exception as ex:
            scrivi_log(f"SourceManager.get_category ({category_id})", ex)
            return None

    def add_category(self, name):
        try:
            nome = " ".join(str(name or "").split())
            if not nome:
                return ESITO_ERRORE
            if self.db.leggi_uno("SELECT 1 FROM news_categories WHERE name = ? COLLATE NOCASE", (nome,)):
                return ESITO_DUPLICATO
            riga = self.db.leggi_uno("SELECT COALESCE(MAX(position), 0) + 1 FROM news_categories")
            posizione = riga[0] if riga else 0
            if self.db.esegui("INSERT INTO news_categories (name, position) VALUES (?, ?)", (nome, posizione)):
                return ESITO_OK
            return ESITO_ERRORE
        except Exception as ex:
            scrivi_log(f"SourceManager.add_category ({name})", ex)
            return ESITO_ERRORE

    def rename_category(self, category_id, name):
        try:
            nome = " ".join(str(name or "").split())
            if not nome:
                return ESITO_ERRORE
            doppione = self.db.leggi_uno(
                "SELECT 1 FROM news_categories WHERE name = ? COLLATE NOCASE AND id <> ?",
                (nome, category_id),
            )
            if doppione:
                return ESITO_DUPLICATO
            riuscito = self.db.transazione(
                [
                    ("UPDATE news_categories SET name = ? WHERE id = ?", (nome, category_id)),
                    ("UPDATE news_sources SET category = ? WHERE category_id = ?", (nome, category_id)),
                ]
            )
            return ESITO_OK if riuscito else ESITO_ERRORE
        except Exception as ex:
            scrivi_log(f"SourceManager.rename_category ({category_id})", ex)
            return ESITO_ERRORE

    def delete_category(self, category_id):
        try:
            if self.db.leggi_uno("SELECT 1 FROM news_sources WHERE category_id = ? LIMIT 1", (category_id,)):
                return ESITO_NON_VUOTA
            if self.db.esegui("DELETE FROM news_categories WHERE id = ?", (category_id,)):
                return ESITO_OK
            return ESITO_ERRORE
        except Exception as ex:
            scrivi_log(f"SourceManager.delete_category ({category_id})", ex)
            return ESITO_ERRORE

    def set_category_notify(self, category_id, attivo):
        try:
            return self.db.esegui(
                "UPDATE news_categories SET notify = ? WHERE id = ?",
                (1 if attivo else 0, category_id),
            )
        except Exception as ex:
            scrivi_log(f"SourceManager.set_category_notify ({category_id})", ex)
            return False

    def get_sources(self, category_id=None):
        try:
            sql = (
                "SELECT s.name, s.url, s.site_url, s.kind, s.category_id, COALESCE(c.name, s.category), "
                "(SELECT COUNT(*) FROM news_articles a WHERE a.source_url = s.url AND a.is_read = 0), "
                "COALESCE(st.last_update, 0), COALESCE(c.notify, 0), COALESCE(st.last_error, '') "
                "FROM news_sources s LEFT JOIN news_categories c ON c.id = s.category_id "
                "LEFT JOIN news_source_state st ON st.source_url = s.url "
            )
            parametri = ()
            if category_id is not None:
                sql += "WHERE s.category_id = ? "
                parametri = (category_id,)
            sql += "ORDER BY s.name COLLATE NOCASE"
            return [
                {
                    "name": riga[0],
                    "url": riga[1],
                    "site_url": riga[2],
                    "kind": riga[3],
                    "category_id": riga[4],
                    "category": riga[5],
                    "unread": riga[6],
                    "last_update": riga[7],
                    "notify": bool(riga[8]),
                    "last_error": riga[9],
                }
                for riga in self.db.leggi_tutti(sql, parametri)
            ]
        except Exception as ex:
            scrivi_log("SourceManager.get_sources", ex)
            return []

    def get_source(self, url):
        try:
            for fonte in self.get_sources():
                if fonte["url"] == url:
                    return fonte
            return None
        except Exception as ex:
            scrivi_log(f"SourceManager.get_source ({url})", ex)
            return None

    def source_exists(self, feed_url):
        try:
            return self.db.leggi_uno("SELECT 1 FROM news_sources WHERE url = ?", (feed_url,)) is not None
        except Exception as ex:
            scrivi_log(f"SourceManager.source_exists ({feed_url})", ex)
            return False

    def add_source(self, name, detected, category_id):
        try:
            feed_url = detected.get("feed_url", "")
            if not feed_url:
                return ESITO_ERRORE
            if self.source_exists(feed_url):
                return ESITO_DUPLICATO
            categoria = self.get_category(category_id)
            if categoria is None:
                return ESITO_ERRORE
            nome = " ".join(str(name or "").split()) or detected.get("name") or feed_url
            riuscito = self.db.esegui(
                "INSERT INTO news_sources (name, url, category, site_url, kind, category_id, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    nome,
                    feed_url,
                    categoria["name"],
                    detected.get("site_url", ""),
                    detected.get("kind", "rss"),
                    category_id,
                    time.time(),
                ),
            )
            return ESITO_OK if riuscito else ESITO_ERRORE
        except Exception as ex:
            scrivi_log(f"SourceManager.add_source ({name})", ex)
            return ESITO_ERRORE

    def rename_source(self, url, name):
        try:
            nome = " ".join(str(name or "").split())
            if not nome:
                return False
            return self.db.esegui("UPDATE news_sources SET name = ? WHERE url = ?", (nome, url))
        except Exception as ex:
            scrivi_log(f"SourceManager.rename_source ({url})", ex)
            return False

    def move_source(self, url, category_id):
        try:
            categoria = self.get_category(category_id)
            if categoria is None:
                return False
            return self.db.esegui(
                "UPDATE news_sources SET category_id = ?, category = ? WHERE url = ?",
                (category_id, categoria["name"], url),
            )
        except Exception as ex:
            scrivi_log(f"SourceManager.move_source ({url})", ex)
            return False

    def remove_source(self, source):
        try:
            url = source.get("url") if isinstance(source, dict) else str(source or "")
            if not url:
                return False
            return self.db.transazione(
                [
                    ("DELETE FROM news_sources WHERE url = ?", (url,)),
                    ("DELETE FROM news_articles WHERE source_url = ?", (url,)),
                    ("DELETE FROM news_source_state WHERE source_url = ?", (url,)),
                ]
            )
        except Exception as ex:
            scrivi_log("SourceManager.remove_source", ex)
            return False

    def needs_update(self, source, eta_massima):
        try:
            return time.time() - float(source.get("last_update") or 0) > eta_massima
        except Exception as ex:
            scrivi_log("SourceManager.needs_update", ex)
            return True

    def _registra_stato(self, url, errore):
        try:
            self.db.esegui(
                "INSERT INTO news_source_state (source_url, last_update, last_error) VALUES (?, ?, ?) "
                "ON CONFLICT (source_url) DO UPDATE SET last_update = excluded.last_update, last_error = excluded.last_error",
                (url, time.time(), errore or ""),
            )
        except Exception as ex:
            scrivi_log(f"SourceManager._registra_stato ({url})", ex)

    def update_source(self, source):
        url = source.get("url", "") if isinstance(source, dict) else str(source or "")
        try:
            if isinstance(source, dict) and "notify" in source:
                fonte = source
            else:
                fonte = self.get_source(url) or {"url": url, "notify": False, "name": ""}
            articoli = self.parser.fetch_articles(fonte)
            righe = self.db.leggi_tutti("SELECT guid FROM news_articles WHERE source_url = ?", (url,))
            conosciuti = {riga[0] for riga in righe}
            nuovi = [articolo for articolo in articoli if articolo.guid not in conosciuti]
            adesso = time.time()
            if nuovi:
                self.db.esegui_molti(
                    "INSERT OR IGNORE INTO news_articles "
                    "(source_url, guid, title, link, summary, content, published, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            url,
                            articolo.guid,
                            articolo.title,
                            articolo.link,
                            articolo.summary,
                            articolo.content,
                            data_in_testo(articolo.published),
                            adesso,
                        )
                        for articolo in nuovi
                    ],
                )
            da_avvisare = []
            if nuovi and conosciuti and fonte.get("notify"):
                self.db.esegui_molti(
                    "UPDATE news_articles SET notified = 1 WHERE source_url = ? AND guid = ?",
                    [(url, articolo.guid) for articolo in nuovi],
                )
                for articolo in nuovi:
                    articolo.source_name = fonte.get("name", "")
                    articolo.category = fonte.get("category", "")
                da_avvisare = nuovi
            self.db.esegui(
                "DELETE FROM news_articles WHERE source_url = ? AND id NOT IN "
                "(SELECT id FROM news_articles WHERE source_url = ? ORDER BY published DESC, id DESC LIMIT ?)",
                (url, url, ARTICOLI_PER_FONTE),
            )
            self._registra_stato(url, "")
            return {"nuovi": len(nuovi), "da_avvisare": da_avvisare, "errore": None}
        except Exception as ex:
            scrivi_log(f"SourceManager.update_source ({url})", ex)
            self._registra_stato(url, str(ex))
            return {"nuovi": 0, "da_avvisare": [], "errore": str(ex)}

    def update_all(self, eta_massima=None, category_id=None):
        resoconto = {"fonti": 0, "aggiornate": 0, "errori": 0, "nuovi": 0, "da_avvisare": [], "fonti_in_errore": []}
        try:
            with self._blocco_aggiornamento:
                fonti = self.get_sources(category_id)
                if eta_massima is not None:
                    fonti = [fonte for fonte in fonti if self.needs_update(fonte, eta_massima)]
                resoconto["fonti"] = len(fonti)
                if not fonti:
                    return resoconto
                with ThreadPoolExecutor(max_workers=AGGIORNAMENTI_PARALLELI, thread_name_prefix="AggiornaNotizie") as esecutore:
                    for fonte, esito in zip(fonti, esecutore.map(self.update_source, fonti)):
                        if esito["errore"]:
                            resoconto["errori"] += 1
                            resoconto["fonti_in_errore"].append(fonte["name"])
                        else:
                            resoconto["aggiornate"] += 1
                            resoconto["nuovi"] += esito["nuovi"]
                            resoconto["da_avvisare"].extend(esito["da_avvisare"])
        except Exception as ex:
            scrivi_log("SourceManager.update_all", ex)
        return resoconto

    def _articoli(self, condizioni="", parametri=(), limite=LIMITE_ELENCO):
        try:
            sql = f"SELECT {COLONNE_ARTICOLO} {DA_ARTICOLI} "
            if condizioni:
                sql += f"WHERE {condizioni} "
            sql += "ORDER BY a.published DESC, a.id DESC LIMIT ?"
            return [_articolo_da_riga(riga) for riga in self.db.leggi_tutti(sql, tuple(parametri) + (limite,))]
        except Exception as ex:
            scrivi_log("SourceManager._articoli", ex)
            return []

    def get_articles(self, source_url=None, category_id=None, only_unread=False):
        try:
            condizioni = []
            parametri = []
            if source_url is not None:
                condizioni.append("a.source_url = ?")
                parametri.append(source_url)
            if category_id is not None:
                condizioni.append("s.category_id = ?")
                parametri.append(category_id)
            if only_unread:
                condizioni.append("a.is_read = 0")
            return self._articoli(" AND ".join(condizioni), parametri)
        except Exception as ex:
            scrivi_log("SourceManager.get_articles", ex)
            return []

    def get_notified_unread(self):
        return self._articoli("a.notified = 1 AND a.is_read = 0")

    def count_notified_unread(self):
        try:
            riga = self.db.leggi_uno("SELECT COUNT(*) FROM news_articles WHERE notified = 1 AND is_read = 0")
            return int(riga[0]) if riga else 0
        except Exception as ex:
            scrivi_log("SourceManager.count_notified_unread", ex)
            return 0

    def count_unread(self):
        try:
            riga = self.db.leggi_uno(
                "SELECT COUNT(*) FROM news_articles a JOIN news_sources s ON s.url = a.source_url WHERE a.is_read = 0"
            )
            return int(riga[0]) if riga else 0
        except Exception as ex:
            scrivi_log("SourceManager.count_unread", ex)
            return 0

    def get_article(self, article_id):
        try:
            risultati = self._articoli("a.id = ?", (article_id,), 1)
            return risultati[0] if risultati else None
        except Exception as ex:
            scrivi_log(f"SourceManager.get_article ({article_id})", ex)
            return None

    def search_articles(self, query):
        try:
            testo = " ".join(str(query or "").split())
            if not testo:
                return []
            modello = f"%{_escapa_like(testo)}%"
            return self._articoli(
                "(a.title LIKE ? ESCAPE '\\' OR a.summary LIKE ? ESCAPE '\\' "
                "OR a.content LIKE ? ESCAPE '\\' OR a.full_text LIKE ? ESCAPE '\\')",
                (modello, modello, modello, modello),
                LIMITE_RICERCA,
            )
        except Exception as ex:
            scrivi_log(f"SourceManager.search_articles ({query})", ex)
            return []

    def mark_read(self, article_id, letto=True):
        try:
            return self.db.esegui("UPDATE news_articles SET is_read = ? WHERE id = ?", (1 if letto else 0, article_id))
        except Exception as ex:
            scrivi_log(f"SourceManager.mark_read ({article_id})", ex)
            return False

    def mark_all_read(self, source_url=None, category_id=None, only_notified=False):
        try:
            if source_url is not None:
                return self.db.esegui("UPDATE news_articles SET is_read = 1 WHERE source_url = ?", (source_url,))
            if category_id is not None:
                return self.db.esegui(
                    "UPDATE news_articles SET is_read = 1 WHERE source_url IN "
                    "(SELECT url FROM news_sources WHERE category_id = ?)",
                    (category_id,),
                )
            if only_notified:
                return self.db.esegui("UPDATE news_articles SET is_read = 1 WHERE notified = 1")
            return self.db.esegui("UPDATE news_articles SET is_read = 1")
        except Exception as ex:
            scrivi_log("SourceManager.mark_all_read", ex)
            return False

    def save_full_text(self, article_id, testo):
        try:
            return self.db.esegui("UPDATE news_articles SET full_text = ? WHERE id = ?", (testo or "", article_id))
        except Exception as ex:
            scrivi_log(f"SourceManager.save_full_text ({article_id})", ex)
            return False

    def get_saved(self, query=None):
        try:
            sql = "SELECT id, item_key, title, link, source_name, published, text FROM news_saved "
            parametri = ()
            if query:
                modello = f"%{_escapa_like(' '.join(str(query).split()))}%"
                sql += "WHERE title LIKE ? ESCAPE '\\' OR text LIKE ? ESCAPE '\\' "
                parametri = (modello, modello)
            sql += "ORDER BY saved_at DESC"
            return [
                {
                    "id": riga[0],
                    "key": riga[1],
                    "article": Article(
                        title=riga[2],
                        link=riga[3],
                        source_name=riga[4],
                        published=testo_in_data(riga[5]),
                        full_text=riga[6],
                        is_read=True,
                    ),
                }
                for riga in self.db.leggi_tutti(sql, parametri)
            ]
        except Exception as ex:
            scrivi_log("SourceManager.get_saved", ex)
            return []

    def count_saved(self):
        try:
            riga = self.db.leggi_uno("SELECT COUNT(*) FROM news_saved")
            return int(riga[0]) if riga else 0
        except Exception as ex:
            scrivi_log("SourceManager.count_saved", ex)
            return 0

    def is_saved(self, article):
        try:
            return self.db.leggi_uno("SELECT 1 FROM news_saved WHERE item_key = ?", (article.chiave(),)) is not None
        except Exception as ex:
            scrivi_log("SourceManager.is_saved", ex)
            return False

    def save_article(self, article, testo):
        try:
            return self.db.esegui(
                "INSERT INTO news_saved (item_key, title, link, source_name, published, text, saved_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (item_key) DO UPDATE SET text = excluded.text, saved_at = excluded.saved_at",
                (
                    article.chiave(),
                    article.title,
                    article.link,
                    article.source_name,
                    data_in_testo(article.published),
                    testo or article.full_text or article.content or article.summary,
                    time.time(),
                ),
            )
        except Exception as ex:
            scrivi_log("SourceManager.save_article", ex)
            return False

    def remove_saved(self, key):
        try:
            return self.db.esegui("DELETE FROM news_saved WHERE item_key = ?", (key,))
        except Exception as ex:
            scrivi_log(f"SourceManager.remove_saved ({key})", ex)
            return False
