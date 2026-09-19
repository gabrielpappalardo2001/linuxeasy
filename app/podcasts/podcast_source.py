import html
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from app.core import rete
from app.core.log import scrivi_log
from app.core.mpv_engine import TrackInfo

try:
    import feedparser
except Exception as errore_importazione:
    feedparser = None
    scrivi_log("podcast_source: impossibile importare feedparser", errore_importazione)

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".flac", ".mp4", ".m4b")
FEED_TIMEOUT = 25
LUNGHEZZA_DESCRIZIONE = 1500


class ErroreFeed(Exception):
    pass


@dataclass
class Episode:
    title: str
    audio_url: str
    guid: str = ""
    feed_url: str = ""
    podcast_name: str = ""
    published: Optional[datetime] = None
    duration: str = ""
    description: str = ""

    def data_testo(self):
        try:
            return self.published.strftime("%d/%m/%Y") if self.published else ""
        except Exception as ex:
            scrivi_log("Episode.data_testo", ex)
            return ""

    def label(self):
        try:
            parti = [self.title, self.data_testo(), self.duration]
            return ", ".join(parte for parte in parti if parte)
        except Exception as ex:
            scrivi_log("Episode.label", ex)
            return str(self.title)


def formatta_durata(valore):
    try:
        testo = str(valore or "").strip()
        if not testo:
            return ""
        if testo.isdigit():
            totale = int(testo)
        else:
            parti = testo.split(":")
            if not all(parte.strip().isdigit() for parte in parti) or len(parti) > 3:
                return ""
            totale = 0
            for parte in parti:
                totale = totale * 60 + int(parte)
        if totale <= 0:
            return ""
        ore, resto = divmod(totale, 3600)
        minuti, secondi = divmod(resto, 60)
        if ore:
            return f"{ore}:{minuti:02d}:{secondi:02d}"
        return f"{minuti}:{secondi:02d}"
    except Exception as ex:
        scrivi_log(f"podcast_source.formatta_durata ({valore})", ex)
        return ""


def testo_semplice(frammento):
    try:
        testo = re.sub(r"<br\s*/?>|</p>", "\n", str(frammento or ""), flags=re.IGNORECASE)
        testo = re.sub(r"<[^>]+>", " ", testo)
        testo = html.unescape(testo)
        righe = [" ".join(riga.split()) for riga in testo.splitlines()]
        testo = "\n".join(riga for riga in righe if riga)
        if len(testo) > LUNGHEZZA_DESCRIZIONE:
            testo = testo[:LUNGHEZZA_DESCRIZIONE].rsplit(" ", 1)[0] + "…"
        return testo
    except Exception as ex:
        scrivi_log("podcast_source.testo_semplice", ex)
        return ""


def _find_audio_url(entry):
    try:
        for enclosure in entry.get("enclosures", []) or []:
            href = str(enclosure.get("href") or enclosure.get("url") or "").strip()
            enc_type = str(enclosure.get("type") or "").lower()
            percorso = href.lower().split("?")[0]
            if href and (enc_type.startswith("audio") or enc_type.startswith("video") or percorso.endswith(AUDIO_EXTENSIONS)):
                return href
        for link in entry.get("links", []) or []:
            href = str(link.get("href") or "").strip()
            tipo = str(link.get("type") or "").lower()
            if href and (tipo.startswith("audio") or href.lower().split("?")[0].endswith(AUDIO_EXTENSIONS)):
                return href
        link = str(entry.get("link") or "")
        if link.lower().split("?")[0].endswith(AUDIO_EXTENSIONS):
            return link
        return None
    except Exception as ex:
        scrivi_log("podcast_source._find_audio_url", ex)
        return None


def _parse_date(entry):
    try:
        time_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if not time_struct:
            return None
        return datetime(*time_struct[:6])
    except Exception as ex:
        scrivi_log("podcast_source._parse_date", ex)
        return None


def fetch_feed(feed_url, limit=300) -> Tuple[str, List[Episode]]:
    try:
        if feedparser is None:
            raise ErroreFeed("Libreria feedparser non installata")
        contenuto = rete.leggi_bytes(feed_url, None, FEED_TIMEOUT)
        parsed = feedparser.parse(contenuto)
        nome_podcast = " ".join(html.unescape(str(parsed.feed.get("title") or "")).split())
        if not parsed.entries and getattr(parsed, "bozo", False):
            raise ErroreFeed(f"Feed non valido: {getattr(parsed, 'bozo_exception', '')}")
        episodes = []
        for entry in parsed.entries[:limit]:
            try:
                audio_url = _find_audio_url(entry)
                if not audio_url:
                    continue
                guid = str(entry.get("id") or entry.get("guid") or audio_url).strip()
                episodes.append(
                    Episode(
                        title=" ".join(html.unescape(str(entry.get("title") or "Episodio senza titolo")).split()),
                        audio_url=audio_url,
                        guid=guid,
                        feed_url=feed_url,
                        podcast_name=nome_podcast,
                        published=_parse_date(entry),
                        duration=formatta_durata(entry.get("itunes_duration", "")),
                        description=testo_semplice(entry.get("summary", "")),
                    )
                )
            except Exception as ex:
                scrivi_log(f"podcast_source.fetch_feed episodio ({feed_url})", ex)
        episodes.sort(key=lambda episodio: episodio.published or datetime.min, reverse=True)
        return nome_podcast, episodes
    except ErroreFeed as ex:
        scrivi_log(f"podcast_source.fetch_feed ({feed_url})", ex)
        raise
    except Exception as ex:
        scrivi_log(f"podcast_source.fetch_feed ({feed_url})", ex)
        raise ErroreFeed(str(ex)) from ex


def fetch_episodes(feed_url, limit=50) -> List[Episode]:
    try:
        return fetch_feed(feed_url, limit)[1]
    except Exception as ex:
        scrivi_log(f"podcast_source.fetch_episodes ({feed_url})", ex)
        return []


def episodes_to_tracks(episodes) -> List[TrackInfo]:
    try:
        return [TrackInfo(title=episodio.title, url=episodio.audio_url) for episodio in episodes]
    except Exception as ex:
        scrivi_log("podcast_source.episodes_to_tracks", ex)
        return []
