import copy
from dataclasses import dataclass

from app.core.log import scrivi_log
from app.podcasts.podcast_source import formatta_durata

try:
    import yt_dlp
except Exception as errore_importazione:
    yt_dlp = None
    scrivi_log("youtube_search: impossibile importare yt-dlp", errore_importazione)

TEMPO_MASSIMO_SECONDI = 25
LINGUA_YOUTUBE = "it"
PAESE_YOUTUBE = "IT"
ESTRATTORI_CON_PAESE = ("YoutubeSearch", "YoutubeSearchURL", "YoutubeTab")
INTESTAZIONE_LINGUA = "it-IT,it;q=0.9"
OPZIONI_BASE = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "extract_flat": "in_playlist",
    "socket_timeout": TEMPO_MASSIMO_SECONDI,
    "extractor_args": {"youtube": {"lang": [LINGUA_YOUTUBE]}},
    "http_headers": {"Accept-Language": INTESTAZIONE_LINGUA},
}


class ErroreYouTube(Exception):
    pass


@dataclass
class VideoResult:
    title: str
    video_id: str
    url: str
    channel: str = ""
    duration: str = ""


def _url_video(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def _converti(elemento):
    try:
        video_id = str(elemento.get("id") or "").strip()
        if not video_id:
            return None
        return VideoResult(
            title=" ".join(str(elemento.get("title") or "Video senza titolo").split()),
            video_id=video_id,
            url=elemento.get("url") or elemento.get("webpage_url") or _url_video(video_id),
            channel=" ".join(str(elemento.get("channel") or elemento.get("uploader") or "").split()),
            duration=formatta_durata(elemento.get("duration")),
        )
    except Exception as ex:
        scrivi_log("youtube_search._converti", ex)
        return None


class YouTubeSearchClient:
    def _imposta_paese(self, estrattore):
        for chiave in ESTRATTORI_CON_PAESE:
            try:
                istanza = estrattore.get_info_extractor(chiave)
                originale = getattr(istanza, "_extract_context", None)
                if originale is None or getattr(originale, "paese_linuxeasy", False):
                    continue

                def contesto_italiano(*argomenti, _originale=originale, **opzioni):
                    risultato = _originale(*argomenti, **opzioni)
                    try:
                        cliente = risultato.get("client") if isinstance(risultato, dict) else None
                        if isinstance(cliente, dict):
                            cliente["gl"] = PAESE_YOUTUBE
                            cliente["hl"] = LINGUA_YOUTUBE
                    except Exception as ex_contesto:
                        scrivi_log("YouTubeSearchClient contesto italiano", ex_contesto)
                    return risultato

                contesto_italiano.paese_linuxeasy = True
                istanza._extract_context = contesto_italiano
            except Exception as ex:
                scrivi_log(f"YouTubeSearchClient._imposta_paese ({chiave})", ex)

    def _estrai(self, sorgente):
        if yt_dlp is None:
            raise ErroreYouTube("Libreria yt-dlp non installata")
        try:
            with yt_dlp.YoutubeDL(copy.deepcopy(OPZIONI_BASE)) as estrattore:
                self._imposta_paese(estrattore)
                informazioni = estrattore.extract_info(sorgente, download=False)
            if informazioni is None:
                raise ErroreYouTube("Nessuna informazione restituita da YouTube")
            return informazioni
        except ErroreYouTube:
            raise
        except Exception as ex:
            scrivi_log(f"YouTubeSearchClient._estrai ({sorgente})", ex)
            raise ErroreYouTube(str(ex)) from ex

    def search(self, query, limit=20):
        try:
            testo = str(query or "").strip()
            if not testo:
                return []
            informazioni = self._estrai(f"ytsearch{max(1, int(limit))}:{testo}")
            voci = informazioni.get("entries") or []
            risultati = []
            visti = set()
            for elemento in voci:
                video = _converti(elemento)
                if video is None or video.video_id in visti:
                    continue
                visti.add(video.video_id)
                risultati.append(video)
            return risultati
        except ErroreYouTube:
            raise
        except Exception as ex:
            scrivi_log(f"YouTubeSearchClient.search ({query})", ex)
            raise ErroreYouTube(str(ex)) from ex

    def video_info(self, url_o_id):
        try:
            testo = str(url_o_id or "").strip()
            if not testo:
                raise ErroreYouTube("Indirizzo del video vuoto")
            sorgente = testo if "://" in testo else _url_video(testo)
            informazioni = self._estrai(sorgente)
            video = _converti(informazioni)
            if video is None:
                raise ErroreYouTube("Video non trovato")
            return video
        except ErroreYouTube:
            raise
        except Exception as ex:
            scrivi_log(f"YouTubeSearchClient.video_info ({url_o_id})", ex)
            raise ErroreYouTube(str(ex)) from ex