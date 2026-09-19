import json
import time
from dataclasses import dataclass
from datetime import datetime

from app.core import percorsi
from app.core.log import scrivi_log
from app.podcasts.podcast_source import Episode

LIMITE_RECENTI = 30
LIMITE_RICERCHE = 30
LIMITE_NUOVI = 300
CHIAVE_MIGRAZIONE = "podcast_migrazione_json"


@dataclass
class SavedPodcast:
    name: str
    author: str
    feed_url: str


def da_risultato(podcast):
    try:
        return SavedPodcast(
            name=str(getattr(podcast, "name", "") or ""),
            author=str(getattr(podcast, "author", "") or ""),
            feed_url=str(getattr(podcast, "feed_url", "") or ""),
        )
    except Exception as ex:
        scrivi_log("subscriptions.da_risultato", ex)
        return SavedPodcast("", "", "")


def data_in_testo(valore):
    try:
        return valore.isoformat(timespec="seconds") if valore else ""
    except Exception as ex:
        scrivi_log("subscriptions.data_in_testo", ex)
        return ""


def testo_in_data(valore):
    try:
        return datetime.fromisoformat(valore) if valore else None
    except Exception as ex:
        scrivi_log(f"subscriptions.testo_in_data ({valore})", ex)
        return None


class PodcastLibrary:
    def __init__(self, db):
        self.db = db
        self._migra_json_vecchio()

    def _migra_json_vecchio(self):
        try:
            if self.db.leggi_impostazione(CHIAVE_MIGRAZIONE) == "1":
                return
            percorso = percorsi.cartella_config_vecchia() / "podcast.json"
            if percorso.is_file():
                with open(percorso, "r", encoding="utf-8-sig") as file_json:
                    dati = json.load(file_json)
                for elemento in dati if isinstance(dati, list) else []:
                    try:
                        feed_url = str(elemento.get("feed_url") or "").strip()
                        if feed_url:
                            self.subscribe(
                                SavedPodcast(
                                    name=str(elemento.get("name") or feed_url),
                                    author=str(elemento.get("author") or ""),
                                    feed_url=feed_url,
                                )
                            )
                    except Exception as ex:
                        scrivi_log("PodcastLibrary._migra_json_vecchio elemento", ex)
            self.db.scrivi_impostazione(CHIAVE_MIGRAZIONE, "1")
        except Exception as ex:
            scrivi_log("PodcastLibrary._migra_json_vecchio", ex)

    def _elenco(self, tabella, ordine):
        try:
            righe = self.db.leggi_tutti(f"SELECT name, author, feed_url FROM {tabella} ORDER BY {ordine}")
            return [SavedPodcast(riga[0], riga[1], riga[2]) for riga in righe]
        except Exception as ex:
            scrivi_log(f"PodcastLibrary._elenco ({tabella})", ex)
            return []

    def _presente(self, tabella, feed_url):
        try:
            if not feed_url:
                return False
            return self.db.leggi_uno(f"SELECT 1 FROM {tabella} WHERE feed_url = ?", (feed_url,)) is not None
        except Exception as ex:
            scrivi_log(f"PodcastLibrary._presente ({tabella}, {feed_url})", ex)
            return False

    def _inserisci(self, tabella, colonna_tempo, podcast):
        try:
            if not podcast.feed_url:
                return False
            return self.db.esegui(
                f"INSERT INTO {tabella} (name, author, feed_url, {colonna_tempo}) VALUES (?, ?, ?, ?) "
                f"ON CONFLICT (feed_url) DO UPDATE SET "
                f"name = CASE WHEN excluded.name <> '' THEN excluded.name ELSE name END, "
                f"author = CASE WHEN excluded.author <> '' THEN excluded.author ELSE author END, "
                f"{colonna_tempo} = excluded.{colonna_tempo}",
                (podcast.name or podcast.feed_url, podcast.author or "", podcast.feed_url, time.time()),
            )
        except Exception as ex:
            scrivi_log(f"PodcastLibrary._inserisci ({tabella}, {podcast.feed_url})", ex)
            return False

    def list_subscriptions(self):
        return self._elenco("podcast_subscriptions", "name COLLATE NOCASE")

    def is_subscribed(self, feed_url):
        return self._presente("podcast_subscriptions", feed_url)

    def subscribe(self, podcast):
        return self._inserisci("podcast_subscriptions", "added_at", podcast)

    def unsubscribe(self, feed_url):
        try:
            return self.db.transazione(
                [
                    ("DELETE FROM podcast_subscriptions WHERE feed_url = ?", (feed_url,)),
                    ("DELETE FROM podcast_new_episodes WHERE feed_url = ?", (feed_url,)),
                    ("DELETE FROM podcast_known_episodes WHERE feed_url = ?", (feed_url,)),
                ]
            )
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.unsubscribe ({feed_url})", ex)
            return False

    def list_favorites(self):
        return self._elenco("podcast_favorites", "name COLLATE NOCASE")

    def is_favorite(self, feed_url):
        return self._presente("podcast_favorites", feed_url)

    def add_favorite(self, podcast):
        return self._inserisci("podcast_favorites", "added_at", podcast)

    def remove_favorite(self, feed_url):
        try:
            return self.db.esegui("DELETE FROM podcast_favorites WHERE feed_url = ?", (feed_url,))
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.remove_favorite ({feed_url})", ex)
            return False

    def list_recent(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT name, author, feed_url FROM podcast_recent ORDER BY last_used DESC LIMIT ?",
                (LIMITE_RECENTI,),
            )
            return [SavedPodcast(riga[0], riga[1], riga[2]) for riga in righe]
        except Exception as ex:
            scrivi_log("PodcastLibrary.list_recent", ex)
            return []

    def add_recent(self, podcast):
        try:
            if not self._inserisci("podcast_recent", "last_used", podcast):
                return False
            return self.db.esegui(
                "DELETE FROM podcast_recent WHERE id NOT IN "
                "(SELECT id FROM podcast_recent ORDER BY last_used DESC LIMIT ?)",
                (LIMITE_RECENTI,),
            )
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.add_recent ({podcast.feed_url})", ex)
            return False

    def remove_recent(self, feed_url):
        try:
            return self.db.esegui("DELETE FROM podcast_recent WHERE feed_url = ?", (feed_url,))
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.remove_recent ({feed_url})", ex)
            return False

    def clear_recent(self):
        try:
            return self.db.esegui("DELETE FROM podcast_recent")
        except Exception as ex:
            scrivi_log("PodcastLibrary.clear_recent", ex)
            return False

    def list_searches(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT query FROM podcast_search_history ORDER BY used_at DESC LIMIT ?",
                (LIMITE_RICERCHE,),
            )
            return [riga[0] for riga in righe]
        except Exception as ex:
            scrivi_log("PodcastLibrary.list_searches", ex)
            return []

    def add_search(self, query):
        try:
            testo = " ".join(str(query or "").split())
            if not testo:
                return False
            return self.db.transazione(
                [
                    (
                        "INSERT INTO podcast_search_history (query, used_at) VALUES (?, ?) "
                        "ON CONFLICT (query) DO UPDATE SET used_at = excluded.used_at",
                        (testo, time.time()),
                    ),
                    (
                        "DELETE FROM podcast_search_history WHERE id NOT IN "
                        "(SELECT id FROM podcast_search_history ORDER BY used_at DESC LIMIT ?)",
                        (LIMITE_RICERCHE,),
                    ),
                ]
            )
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.add_search ({query})", ex)
            return False

    def remove_search(self, query):
        try:
            return self.db.esegui("DELETE FROM podcast_search_history WHERE query = ?", (query,))
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.remove_search ({query})", ex)
            return False

    def clear_searches(self):
        try:
            return self.db.esegui("DELETE FROM podcast_search_history")
        except Exception as ex:
            scrivi_log("PodcastLibrary.clear_searches", ex)
            return False

    def has_known(self, feed_url):
        try:
            return self.db.leggi_uno("SELECT 1 FROM podcast_known_episodes WHERE feed_url = ? LIMIT 1", (feed_url,)) is not None
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.has_known ({feed_url})", ex)
            return False

    def unknown_guids(self, feed_url, guids):
        try:
            righe = self.db.leggi_tutti("SELECT guid FROM podcast_known_episodes WHERE feed_url = ?", (feed_url,))
            noti = {riga[0] for riga in righe}
            return {guid for guid in guids if guid and guid not in noti}
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.unknown_guids ({feed_url})", ex)
            return set()

    def mark_known(self, feed_url, guids):
        try:
            valori = [(feed_url, guid) for guid in guids if guid]
            if not valori:
                return True
            return self.db.esegui_molti(
                "INSERT OR IGNORE INTO podcast_known_episodes (feed_url, guid) VALUES (?, ?)",
                valori,
            )
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.mark_known ({feed_url})", ex)
            return False

    def add_new(self, episodes):
        try:
            valori = [
                (
                    episodio.feed_url,
                    episodio.podcast_name,
                    episodio.guid,
                    episodio.title,
                    episodio.audio_url,
                    data_in_testo(episodio.published),
                    episodio.duration,
                    episodio.description,
                    time.time(),
                )
                for episodio in episodes
                if episodio.feed_url and episodio.guid
            ]
            if not valori:
                return True
            if not self.db.esegui_molti(
                "INSERT OR IGNORE INTO podcast_new_episodes "
                "(feed_url, podcast_name, guid, title, audio_url, published, duration, description, found_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                valori,
            ):
                return False
            return self.db.esegui(
                "DELETE FROM podcast_new_episodes WHERE id NOT IN "
                "(SELECT id FROM podcast_new_episodes ORDER BY found_at DESC, id DESC LIMIT ?)",
                (LIMITE_NUOVI,),
            )
        except Exception as ex:
            scrivi_log("PodcastLibrary.add_new", ex)
            return False

    def list_new(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT feed_url, podcast_name, guid, title, audio_url, published, duration, description "
                "FROM podcast_new_episodes ORDER BY published DESC, found_at DESC"
            )
            return [
                Episode(
                    title=riga[3],
                    audio_url=riga[4],
                    guid=riga[2],
                    feed_url=riga[0],
                    podcast_name=riga[1],
                    published=testo_in_data(riga[5]),
                    duration=riga[6],
                    description=riga[7],
                )
                for riga in righe
            ]
        except Exception as ex:
            scrivi_log("PodcastLibrary.list_new", ex)
            return []

    def count_new(self):
        try:
            riga = self.db.leggi_uno("SELECT COUNT(*) FROM podcast_new_episodes")
            return int(riga[0]) if riga else 0
        except Exception as ex:
            scrivi_log("PodcastLibrary.count_new", ex)
            return 0

    def is_new(self, feed_url, guid):
        try:
            return self.db.leggi_uno(
                "SELECT 1 FROM podcast_new_episodes WHERE feed_url = ? AND guid = ?",
                (feed_url, guid),
            ) is not None
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.is_new ({feed_url})", ex)
            return False

    def remove_new(self, feed_url, guid):
        try:
            return self.db.esegui(
                "DELETE FROM podcast_new_episodes WHERE feed_url = ? AND guid = ?",
                (feed_url, guid),
            )
        except Exception as ex:
            scrivi_log(f"PodcastLibrary.remove_new ({feed_url})", ex)
            return False

    def clear_new(self):
        try:
            return self.db.esegui("DELETE FROM podcast_new_episodes")
        except Exception as ex:
            scrivi_log("PodcastLibrary.clear_new", ex)
            return False
