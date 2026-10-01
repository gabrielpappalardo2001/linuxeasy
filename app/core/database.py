import sqlite3
from contextlib import closing
from pathlib import Path

from app.core.log import scrivi_log

CARTELLA_PROGETTO = Path(__file__).resolve().parents[2]

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS radio_favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        url TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS radio_recent (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        url TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS radio_search_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        url TEXT NOT NULL UNIQUE,
        category TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS podcast_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        feed_url TEXT NOT NULL UNIQUE,
        added_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS podcast_favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        feed_url TEXT NOT NULL UNIQUE,
        added_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS podcast_recent (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        feed_url TEXT NOT NULL UNIQUE,
        last_used REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS podcast_search_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL UNIQUE COLLATE NOCASE,
        used_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS podcast_known_episodes (
        feed_url TEXT NOT NULL,
        guid TEXT NOT NULL,
        PRIMARY KEY (feed_url, guid)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS podcast_new_episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feed_url TEXT NOT NULL,
        podcast_name TEXT NOT NULL DEFAULT '',
        guid TEXT NOT NULL,
        title TEXT NOT NULL,
        audio_url TEXT NOT NULL,
        published TEXT NOT NULL DEFAULT '',
        duration TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        found_at REAL NOT NULL DEFAULT 0,
        UNIQUE (feed_url, guid)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS podcast_downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feed_url TEXT NOT NULL DEFAULT '',
        podcast_name TEXT NOT NULL DEFAULT '',
        guid TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL,
        audio_url TEXT NOT NULL UNIQUE,
        file_path TEXT NOT NULL,
        size INTEGER NOT NULL DEFAULT 0,
        published TEXT NOT NULL DEFAULT '',
        duration TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        downloaded_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        position INTEGER NOT NULL DEFAULT 0,
        notify INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_url TEXT NOT NULL,
        guid TEXT NOT NULL,
        title TEXT NOT NULL,
        link TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL DEFAULT '',
        published TEXT NOT NULL DEFAULT '',
        fetched_at REAL NOT NULL DEFAULT 0,
        is_read INTEGER NOT NULL DEFAULT 0,
        notified INTEGER NOT NULL DEFAULT 0,
        full_text TEXT NOT NULL DEFAULT '',
        UNIQUE (source_url, guid)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS news_articles_source ON news_articles (source_url, published)
    """,
    """
    CREATE TABLE IF NOT EXISTS news_saved (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_key TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        link TEXT NOT NULL DEFAULT '',
        source_name TEXT NOT NULL DEFAULT '',
        published TEXT NOT NULL DEFAULT '',
        text TEXT NOT NULL DEFAULT '',
        saved_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_source_state (
        source_url TEXT PRIMARY KEY,
        last_update REAL NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS youtube_favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT '',
        video_id TEXT NOT NULL UNIQUE,
        url TEXT NOT NULL,
        duration TEXT NOT NULL DEFAULT '',
        added_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS youtube_recent (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT '',
        video_id TEXT NOT NULL UNIQUE,
        url TEXT NOT NULL,
        duration TEXT NOT NULL DEFAULT '',
        last_used REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS youtube_search_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL UNIQUE COLLATE NOCASE,
        used_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS librivox_books (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        title_sort TEXT NOT NULL DEFAULT '',
        initial TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT '',
        authors TEXT NOT NULL DEFAULT '',
        totaltime TEXT NOT NULL DEFAULT '',
        num_sections INTEGER NOT NULL DEFAULT 0,
        copyright_year TEXT NOT NULL DEFAULT '',
        url_rss TEXT NOT NULL DEFAULT '',
        url_zip_file TEXT NOT NULL DEFAULT '',
        url_librivox TEXT NOT NULL DEFAULT '',
        search_text TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS librivox_books_lingua ON librivox_books (language, initial, title_sort)
    """,
    """
    CREATE TABLE IF NOT EXISTS librivox_authors (
        id INTEGER PRIMARY KEY,
        first_name TEXT NOT NULL DEFAULT '',
        last_name TEXT NOT NULL DEFAULT '',
        dob TEXT NOT NULL DEFAULT '',
        dod TEXT NOT NULL DEFAULT '',
        name_sort TEXT NOT NULL DEFAULT '',
        initial TEXT NOT NULL DEFAULT '',
        search_text TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS librivox_book_authors (
        book_id INTEGER NOT NULL,
        author_id INTEGER NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (book_id, author_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS librivox_book_authors_autore ON librivox_book_authors (author_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS librivox_favorites (
        book_id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        authors TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT '',
        added_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS librivox_recent (
        book_id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        authors TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT '',
        chapter_index INTEGER NOT NULL DEFAULT 0,
        chapter_title TEXT NOT NULL DEFAULT '',
        last_used REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS librivox_downloads (
        book_id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        authors TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT '',
        folder TEXT NOT NULL DEFAULT '',
        chapters_total INTEGER NOT NULL DEFAULT 0,
        chapters_done INTEGER NOT NULL DEFAULT 0,
        size INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '',
        added_at REAL NOT NULL DEFAULT 0,
        completed_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS librivox_tag_cache (
        url TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        read_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wikipedia_search_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL UNIQUE COLLATE NOCASE,
        used_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wikipedia_favorites (
        title TEXT NOT NULL,
        lang TEXT NOT NULL DEFAULT 'it',
        description TEXT NOT NULL DEFAULT '',
        added_at REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (lang, title)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS wikipedia_recent (
        title TEXT NOT NULL,
        lang TEXT NOT NULL DEFAULT 'it',
        description TEXT NOT NULL DEFAULT '',
        last_used REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (lang, title)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agenda_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        location TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        start TEXT NOT NULL,
        end TEXT NOT NULL,
        all_day INTEGER NOT NULL DEFAULT 0,
        freq TEXT NOT NULL DEFAULT 'nessuna',
        interval INTEGER NOT NULL DEFAULT 1,
        weekdays TEXT NOT NULL DEFAULT '',
        end_mode TEXT NOT NULL DEFAULT 'mai',
        until TEXT NOT NULL DEFAULT '',
        count INTEGER NOT NULL DEFAULT 0,
        reminder INTEGER NOT NULL DEFAULT 15,
        exclusions TEXT NOT NULL DEFAULT '',
        search_text TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agenda_notified (
        event_id INTEGER NOT NULL,
        occurrence TEXT NOT NULL,
        kind TEXT NOT NULL,
        notified_at REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (event_id, occurrence, kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL DEFAULT '',
        last_name TEXT NOT NULL DEFAULT '',
        company TEXT NOT NULL DEFAULT '',
        birthday TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        favorite INTEGER NOT NULL DEFAULT 0,
        sort_key TEXT NOT NULL DEFAULT '',
        search_text TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL DEFAULT 0,
        last_viewed REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contact_values (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        value TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS contact_values_contatto ON contact_values (contact_id, kind, position)
    """,
    """
    CREATE TABLE IF NOT EXISTS contacts_search_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL UNIQUE COLLATE NOCASE,
        used_at REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS player_positions (
        url TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        position REAL NOT NULL DEFAULT 0,
        duration REAL NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL DEFAULT 0
    )
    """,
]


CATEGORIE_NOTIZIE_PREDEFINITE = ["Generale", "Tecnologia", "Cronaca", "Sport", "Cultura"]

ORA_SINCRONIZZAZIONE = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"

COLONNE_SINCRONIZZAZIONE = {
    "contacts": [("sync_id", "TEXT"), ("sync_modificato", "TEXT"), ("sync_extra", "TEXT NOT NULL DEFAULT ''")],
    "agenda_events": [("sync_id", "TEXT"), ("sync_modificato", "TEXT"), ("sync_extra", "TEXT NOT NULL DEFAULT ''")],
    "news_categories": [("sync_id", "TEXT"), ("sync_modificato", "TEXT"), ("sync_extra", "TEXT NOT NULL DEFAULT ''")],
    "news_sources": [("sync_id", "TEXT"), ("sync_modificato", "TEXT"), ("sync_extra", "TEXT NOT NULL DEFAULT ''")],
    "radio_favorites": [("uuid", "TEXT NOT NULL DEFAULT ''"), ("sync_modificato", "TEXT NOT NULL DEFAULT ''")],
    "radio_recent": [("uuid", "TEXT NOT NULL DEFAULT ''"), ("sync_modificato", "TEXT NOT NULL DEFAULT ''")],
}

ISTRUZIONI_SINCRONIZZAZIONE = [
    "CREATE TABLE IF NOT EXISTS sync_eliminati (sezione TEXT NOT NULL, sync_id TEXT NOT NULL, data TEXT NOT NULL, "
    "PRIMARY KEY (sezione, sync_id))",
    "UPDATE contacts SET sync_id = lower(hex(randomblob(16))) WHERE sync_id IS NULL OR sync_id = ''",
    f"UPDATE contacts SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE sync_modificato IS NULL OR sync_modificato = ''",
    "UPDATE agenda_events SET sync_id = lower(hex(randomblob(16))) WHERE sync_id IS NULL OR sync_id = ''",
    f"UPDATE agenda_events SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE sync_modificato IS NULL OR sync_modificato = ''",
    "UPDATE news_categories SET sync_id = lower(hex(randomblob(16))) WHERE sync_id IS NULL OR sync_id = ''",
    f"UPDATE news_categories SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE sync_modificato IS NULL OR sync_modificato = ''",
    f"UPDATE news_sources SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE sync_modificato IS NULL OR sync_modificato = ''",
    f"UPDATE radio_favorites SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE sync_modificato IS NULL OR sync_modificato = ''",
    f"UPDATE radio_recent SET sync_modificato = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || (SELECT COUNT(*) FROM radio_recent r WHERE r.id > radio_recent.id) || ' seconds') "
    "WHERE sync_modificato IS NULL OR sync_modificato = ''",
    "CREATE INDEX IF NOT EXISTS contacts_sync_id ON contacts (sync_id)",
    "CREATE INDEX IF NOT EXISTS agenda_events_sync_id ON agenda_events (sync_id)",
    "CREATE INDEX IF NOT EXISTS news_sources_sync_id ON news_sources (sync_id)",
    "CREATE INDEX IF NOT EXISTS radio_favorites_uuid ON radio_favorites (uuid)",
    "CREATE INDEX IF NOT EXISTS radio_recent_uuid ON radio_recent (uuid)",
    "CREATE TRIGGER IF NOT EXISTS contacts_sync_ins AFTER INSERT ON contacts "
    "WHEN NEW.sync_id IS NULL OR NEW.sync_id = '' OR NEW.sync_modificato IS NULL OR NEW.sync_modificato = '' BEGIN "
    "UPDATE contacts SET "
    "sync_id = CASE WHEN NEW.sync_id IS NULL OR NEW.sync_id = '' THEN lower(hex(randomblob(16))) ELSE NEW.sync_id END, "
    f"sync_modificato = CASE WHEN NEW.sync_modificato IS NULL OR NEW.sync_modificato = '' THEN {ORA_SINCRONIZZAZIONE} ELSE NEW.sync_modificato END "
    "WHERE id = NEW.id; END",
    "CREATE TRIGGER IF NOT EXISTS contacts_sync_upd AFTER UPDATE OF first_name, last_name, company, birthday, notes, favorite "
    "ON contacts WHEN NEW.sync_modificato IS OLD.sync_modificato BEGIN "
    f"UPDATE contacts SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE id = NEW.id; END",
    "CREATE TRIGGER IF NOT EXISTS contacts_sync_del AFTER DELETE ON contacts "
    "WHEN OLD.sync_id IS NOT NULL AND OLD.sync_id <> '' BEGIN "
    f"INSERT OR REPLACE INTO sync_eliminati (sezione, sync_id, data) VALUES ('contatti', OLD.sync_id, {ORA_SINCRONIZZAZIONE}); END",
    "CREATE TRIGGER IF NOT EXISTS contact_values_sync_ins AFTER INSERT ON contact_values BEGIN "
    f"UPDATE contacts SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE id = NEW.contact_id; END",
    "CREATE TRIGGER IF NOT EXISTS contact_values_sync_del AFTER DELETE ON contact_values BEGIN "
    f"UPDATE contacts SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE id = OLD.contact_id; END",
    "CREATE TRIGGER IF NOT EXISTS agenda_events_sync_ins AFTER INSERT ON agenda_events "
    "WHEN NEW.sync_id IS NULL OR NEW.sync_id = '' OR NEW.sync_modificato IS NULL OR NEW.sync_modificato = '' BEGIN "
    "UPDATE agenda_events SET "
    "sync_id = CASE WHEN NEW.sync_id IS NULL OR NEW.sync_id = '' THEN lower(hex(randomblob(16))) ELSE NEW.sync_id END, "
    f"sync_modificato = CASE WHEN NEW.sync_modificato IS NULL OR NEW.sync_modificato = '' THEN {ORA_SINCRONIZZAZIONE} ELSE NEW.sync_modificato END "
    "WHERE id = NEW.id; END",
    "CREATE TRIGGER IF NOT EXISTS agenda_events_sync_upd AFTER UPDATE OF title, location, notes, start, end, all_day, freq, "
    "interval, weekdays, end_mode, until, count, reminder, exclusions ON agenda_events "
    "WHEN NEW.sync_modificato IS OLD.sync_modificato BEGIN "
    f"UPDATE agenda_events SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE id = NEW.id; END",
    "CREATE TRIGGER IF NOT EXISTS agenda_events_sync_del AFTER DELETE ON agenda_events "
    "WHEN OLD.sync_id IS NOT NULL AND OLD.sync_id <> '' BEGIN "
    f"INSERT OR REPLACE INTO sync_eliminati (sezione, sync_id, data) VALUES ('appuntamenti', OLD.sync_id, {ORA_SINCRONIZZAZIONE}); END",
    "CREATE TRIGGER IF NOT EXISTS news_categories_sync_ins AFTER INSERT ON news_categories "
    "WHEN NEW.sync_id IS NULL OR NEW.sync_id = '' OR NEW.sync_modificato IS NULL OR NEW.sync_modificato = '' BEGIN "
    "UPDATE news_categories SET "
    "sync_id = CASE WHEN NEW.sync_id IS NULL OR NEW.sync_id = '' THEN lower(hex(randomblob(16))) ELSE NEW.sync_id END, "
    f"sync_modificato = CASE WHEN NEW.sync_modificato IS NULL OR NEW.sync_modificato = '' THEN {ORA_SINCRONIZZAZIONE} ELSE NEW.sync_modificato END "
    "WHERE id = NEW.id; END",
    "CREATE TRIGGER IF NOT EXISTS news_categories_sync_upd AFTER UPDATE OF name ON news_categories "
    "WHEN NEW.sync_modificato IS OLD.sync_modificato BEGIN "
    f"UPDATE news_categories SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE id = NEW.id; END",
    "CREATE TRIGGER IF NOT EXISTS news_categories_sync_del AFTER DELETE ON news_categories "
    "WHEN OLD.sync_id IS NOT NULL AND OLD.sync_id <> '' BEGIN "
    f"INSERT OR REPLACE INTO sync_eliminati (sezione, sync_id, data) VALUES ('categorieTestate', OLD.sync_id, {ORA_SINCRONIZZAZIONE}); END",
    "CREATE TRIGGER IF NOT EXISTS news_sources_sync_ins AFTER INSERT ON news_sources "
    "WHEN NEW.sync_modificato IS NULL OR NEW.sync_modificato = '' BEGIN "
    f"UPDATE news_sources SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE rowid = NEW.rowid; END",
    "CREATE TRIGGER IF NOT EXISTS news_sources_sync_upd AFTER UPDATE OF name, url, site_url, kind, category_id ON news_sources "
    "WHEN NEW.sync_modificato IS OLD.sync_modificato BEGIN "
    f"UPDATE news_sources SET sync_modificato = {ORA_SINCRONIZZAZIONE} WHERE rowid = NEW.rowid; END",
    "CREATE TRIGGER IF NOT EXISTS news_sources_sync_del AFTER DELETE ON news_sources "
    "WHEN OLD.sync_id IS NOT NULL AND OLD.sync_id <> '' BEGIN "
    f"INSERT OR REPLACE INTO sync_eliminati (sezione, sync_id, data) VALUES ('testate', OLD.sync_id, {ORA_SINCRONIZZAZIONE}); END",
]

COLONNE_FONTI_AGGIUNTE = [
    ("site_url", "TEXT NOT NULL DEFAULT ''"),
    ("kind", "TEXT NOT NULL DEFAULT 'rss'"),
    ("category_id", "INTEGER"),
    ("added_at", "REAL NOT NULL DEFAULT 0"),
]


class Database:
    def __init__(self, db_path="app.db"):
        self.db_path = self._risolvi_percorso(db_path)
        self.init_db()

    def _risolvi_percorso(self, db_path):
        try:
            percorso = Path(db_path).expanduser()
            if percorso.is_absolute():
                return str(percorso)
            if percorso.exists():
                return str(percorso.resolve())
            return str(CARTELLA_PROGETTO / percorso)
        except Exception as ex:
            scrivi_log(f"Database._risolvi_percorso ({db_path})", ex)
            return str(db_path)

    def get_connection(self):
        try:
            return sqlite3.connect(self.db_path, timeout=15)
        except Exception as ex:
            scrivi_log(f"Database.get_connection ({self.db_path})", ex)
            raise

    def init_db(self):
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            with closing(self.get_connection()) as conn:
                with conn:
                    for istruzione in SCHEMA:
                        conn.execute(istruzione)
            self._migra_notizie()
            self._migra_sincronizzazione()
            return True
        except Exception as ex:
            scrivi_log("Database.init_db", ex)
            return False

    def _migra_notizie(self):
        try:
            with closing(self.get_connection()) as conn:
                with conn:
                    colonne = {riga[1] for riga in conn.execute("PRAGMA table_info(news_sources)").fetchall()}
                    for nome, definizione in COLONNE_FONTI_AGGIUNTE:
                        if nome not in colonne:
                            conn.execute(f"ALTER TABLE news_sources ADD COLUMN {nome} {definizione}")
                    totale = conn.execute("SELECT COUNT(*) FROM news_categories").fetchone()[0]
                    if totale == 0:
                        for posizione, nome in enumerate(CATEGORIE_NOTIZIE_PREDEFINITE):
                            conn.execute(
                                "INSERT OR IGNORE INTO news_categories (name, position) VALUES (?, ?)",
                                (nome, posizione),
                            )
                    conn.execute(
                        "INSERT OR IGNORE INTO news_categories (name, position) "
                        "SELECT DISTINCT TRIM(category), 1000 FROM news_sources "
                        "WHERE category_id IS NULL AND TRIM(category) <> ''"
                    )
                    conn.execute(
                        "UPDATE news_sources SET category_id = "
                        "(SELECT c.id FROM news_categories c WHERE c.name = TRIM(news_sources.category) COLLATE NOCASE) "
                        "WHERE category_id IS NULL"
                    )
                    conn.execute(
                        "UPDATE news_sources SET category_id = "
                        "(SELECT id FROM news_categories ORDER BY position, id LIMIT 1) "
                        "WHERE category_id IS NULL OR category_id NOT IN (SELECT id FROM news_categories)"
                    )
                    conn.execute(
                        "UPDATE news_sources SET category = "
                        "(SELECT c.name FROM news_categories c WHERE c.id = news_sources.category_id) "
                        "WHERE category_id IS NOT NULL"
                    )
            return True
        except Exception as ex:
            scrivi_log("Database._migra_notizie", ex)
            return False

    def _migra_sincronizzazione(self):
        try:
            with closing(self.get_connection()) as conn:
                with conn:
                    for tabella, colonne in COLONNE_SINCRONIZZAZIONE.items():
                        presenti = {riga[1] for riga in conn.execute(f"PRAGMA table_info({tabella})").fetchall()}
                        for nome, definizione in colonne:
                            if nome not in presenti:
                                conn.execute(f"ALTER TABLE {tabella} ADD COLUMN {nome} {definizione}")
                    for istruzione in ISTRUZIONI_SINCRONIZZAZIONE:
                        conn.execute(istruzione)
            return True
        except Exception as ex:
            scrivi_log("Database._migra_sincronizzazione", ex)
            return False

    def esegui(self, sql, parametri=()):
        try:
            with closing(self.get_connection()) as conn:
                with conn:
                    conn.execute(sql, parametri)
            return True
        except Exception as ex:
            scrivi_log(f"Database.esegui ({sql.strip()[:80]})", ex)
            return False

    def esegui_molti(self, sql, sequenza):
        try:
            with closing(self.get_connection()) as conn:
                with conn:
                    conn.executemany(sql, list(sequenza))
            return True
        except Exception as ex:
            scrivi_log(f"Database.esegui_molti ({sql.strip()[:80]})", ex)
            return False

    def transazione(self, istruzioni):
        try:
            with closing(self.get_connection()) as conn:
                with conn:
                    for sql, parametri in istruzioni:
                        conn.execute(sql, parametri)
            return True
        except Exception as ex:
            scrivi_log("Database.transazione", ex)
            return False

    def leggi_tutti(self, sql, parametri=()):
        try:
            with closing(self.get_connection()) as conn:
                return conn.execute(sql, parametri).fetchall()
        except Exception as ex:
            scrivi_log(f"Database.leggi_tutti ({sql.strip()[:80]})", ex)
            return []

    def leggi_uno(self, sql, parametri=()):
        try:
            with closing(self.get_connection()) as conn:
                return conn.execute(sql, parametri).fetchone()
        except Exception as ex:
            scrivi_log(f"Database.leggi_uno ({sql.strip()[:80]})", ex)
            return None

    def leggi_impostazione(self, chiave, predefinito=""):
        try:
            riga = self.leggi_uno("SELECT value FROM app_settings WHERE key = ?", (chiave,))
            return riga[0] if riga else predefinito
        except Exception as ex:
            scrivi_log(f"Database.leggi_impostazione ({chiave})", ex)
            return predefinito

    def scrivi_impostazione(self, chiave, valore):
        try:
            return self.esegui(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (chiave, str(valore)),
            )
        except Exception as ex:
            scrivi_log(f"Database.scrivi_impostazione ({chiave})", ex)
            return False
