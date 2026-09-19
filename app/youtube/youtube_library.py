import time
from dataclasses import dataclass

from app.core.log import scrivi_log

LIMITE_RECENTI = 30
LIMITE_RICERCHE = 30


@dataclass
class SavedVideo:
    title: str
    channel: str
    video_id: str
    url: str
    duration: str = ""


def da_risultato(video):
    try:
        return SavedVideo(
            title=str(getattr(video, "title", "") or ""),
            channel=str(getattr(video, "channel", "") or ""),
            video_id=str(getattr(video, "video_id", "") or ""),
            url=str(getattr(video, "url", "") or ""),
            duration=str(getattr(video, "duration", "") or ""),
        )
    except Exception as ex:
        scrivi_log("youtube_library.da_risultato", ex)
        return SavedVideo("", "", "", "")


class YouTubeLibrary:
    def __init__(self, db):
        self.db = db

    def _elenco(self, tabella, ordine):
        try:
            righe = self.db.leggi_tutti(f"SELECT title, channel, video_id, url, duration FROM {tabella} ORDER BY {ordine}")
            return [SavedVideo(riga[0], riga[1], riga[2], riga[3], riga[4]) for riga in righe]
        except Exception as ex:
            scrivi_log(f"YouTubeLibrary._elenco ({tabella})", ex)
            return []

    def _presente(self, tabella, video_id):
        try:
            if not video_id:
                return False
            return self.db.leggi_uno(f"SELECT 1 FROM {tabella} WHERE video_id = ?", (video_id,)) is not None
        except Exception as ex:
            scrivi_log(f"YouTubeLibrary._presente ({tabella}, {video_id})", ex)
            return False

    def _inserisci(self, tabella, colonna_tempo, video):
        try:
            if not video.video_id:
                return False
            return self.db.esegui(
                f"INSERT INTO {tabella} (title, channel, video_id, url, duration, {colonna_tempo}) VALUES (?, ?, ?, ?, ?, ?) "
                f"ON CONFLICT (video_id) DO UPDATE SET "
                f"title = CASE WHEN excluded.title <> '' THEN excluded.title ELSE title END, "
                f"channel = CASE WHEN excluded.channel <> '' THEN excluded.channel ELSE channel END, "
                f"url = excluded.url, "
                f"duration = CASE WHEN excluded.duration <> '' THEN excluded.duration ELSE duration END, "
                f"{colonna_tempo} = excluded.{colonna_tempo}",
                (video.title or video.video_id, video.channel or "", video.video_id, video.url, video.duration or "", time.time()),
            )
        except Exception as ex:
            scrivi_log(f"YouTubeLibrary._inserisci ({tabella}, {video.video_id})", ex)
            return False

    def list_favorites(self):
        return self._elenco("youtube_favorites", "title COLLATE NOCASE")

    def is_favorite(self, video_id):
        return self._presente("youtube_favorites", video_id)

    def add_favorite(self, video):
        return self._inserisci("youtube_favorites", "added_at", video)

    def remove_favorite(self, video_id):
        try:
            return self.db.esegui("DELETE FROM youtube_favorites WHERE video_id = ?", (video_id,))
        except Exception as ex:
            scrivi_log(f"YouTubeLibrary.remove_favorite ({video_id})", ex)
            return False

    def list_recent(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT title, channel, video_id, url, duration FROM youtube_recent ORDER BY last_used DESC LIMIT ?",
                (LIMITE_RECENTI,),
            )
            return [SavedVideo(riga[0], riga[1], riga[2], riga[3], riga[4]) for riga in righe]
        except Exception as ex:
            scrivi_log("YouTubeLibrary.list_recent", ex)
            return []

    def add_recent(self, video):
        try:
            if not self._inserisci("youtube_recent", "last_used", video):
                return False
            return self.db.esegui(
                "DELETE FROM youtube_recent WHERE id NOT IN "
                "(SELECT id FROM youtube_recent ORDER BY last_used DESC LIMIT ?)",
                (LIMITE_RECENTI,),
            )
        except Exception as ex:
            scrivi_log(f"YouTubeLibrary.add_recent ({video.video_id})", ex)
            return False

    def remove_recent(self, video_id):
        try:
            return self.db.esegui("DELETE FROM youtube_recent WHERE video_id = ?", (video_id,))
        except Exception as ex:
            scrivi_log(f"YouTubeLibrary.remove_recent ({video_id})", ex)
            return False

    def clear_recent(self):
        try:
            return self.db.esegui("DELETE FROM youtube_recent")
        except Exception as ex:
            scrivi_log("YouTubeLibrary.clear_recent", ex)
            return False

    def list_searches(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT query FROM youtube_search_history ORDER BY used_at DESC LIMIT ?",
                (LIMITE_RICERCHE,),
            )
            return [riga[0] for riga in righe]
        except Exception as ex:
            scrivi_log("YouTubeLibrary.list_searches", ex)
            return []

    def add_search(self, query):
        try:
            testo = " ".join(str(query or "").split())
            if not testo:
                return False
            return self.db.transazione(
                [
                    (
                        "INSERT INTO youtube_search_history (query, used_at) VALUES (?, ?) "
                        "ON CONFLICT (query) DO UPDATE SET used_at = excluded.used_at",
                        (testo, time.time()),
                    ),
                    (
                        "DELETE FROM youtube_search_history WHERE id NOT IN "
                        "(SELECT id FROM youtube_search_history ORDER BY used_at DESC LIMIT ?)",
                        (LIMITE_RICERCHE,),
                    ),
                ]
            )
        except Exception as ex:
            scrivi_log(f"YouTubeLibrary.add_search ({query})", ex)
            return False

    def remove_search(self, query):
        try:
            return self.db.esegui("DELETE FROM youtube_search_history WHERE query = ?", (query,))
        except Exception as ex:
            scrivi_log(f"YouTubeLibrary.remove_search ({query})", ex)
            return False

    def clear_searches(self):
        try:
            return self.db.esegui("DELETE FROM youtube_search_history")
        except Exception as ex:
            scrivi_log("YouTubeLibrary.clear_searches", ex)
            return False
