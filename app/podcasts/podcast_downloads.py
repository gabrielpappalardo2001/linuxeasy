import collections
import os
import re
import threading
import time
import urllib.parse
from pathlib import Path

from gi.repository import GLib

from app.core import percorsi, rete
from app.core.log import scrivi_log
from app.podcasts.podcast_source import AUDIO_EXTENSIONS, Episode
from app.podcasts.subscriptions import data_in_testo, testo_in_data

STATO_SCARICATO = "scaricato"
STATO_IN_CORSO = "in_corso"
STATO_IN_CODA = "in_coda"
ESITO_ACCODATO = "accodato"
LUNGHEZZA_NOME = 100


def nome_sicuro(testo, predefinito="episodio"):
    try:
        valore = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", str(testo or ""))
        valore = " ".join(valore.split()).strip(" .")
        if len(valore) > LUNGHEZZA_NOME:
            valore = valore[:LUNGHEZZA_NOME].rstrip(" .")
        return valore or predefinito
    except Exception as ex:
        scrivi_log(f"podcast_downloads.nome_sicuro ({testo})", ex)
        return predefinito


def estensione_audio(url):
    try:
        percorso = urllib.parse.urlparse(url).path.lower()
        for estensione in AUDIO_EXTENSIONS:
            if percorso.endswith(estensione):
                return estensione
        return ".mp3"
    except Exception as ex:
        scrivi_log(f"podcast_downloads.estensione_audio ({url})", ex)
        return ".mp3"


def percorso_libero(cartella, nome_base, estensione):
    try:
        candidato = Path(cartella) / f"{nome_base}{estensione}"
        numero = 2
        while candidato.exists() or candidato.with_name(candidato.name + ".part").exists():
            candidato = Path(cartella) / f"{nome_base} ({numero}){estensione}"
            numero += 1
        return candidato
    except Exception as ex:
        scrivi_log(f"podcast_downloads.percorso_libero ({cartella})", ex)
        return Path(cartella) / f"{nome_base}-{int(time.time())}{estensione}"


class PodcastDownloads:
    def __init__(self, db, al_completamento=None, al_errore=None):
        self.db = db
        self.al_completamento = al_completamento
        self.al_errore = al_errore
        self._coda = collections.deque()
        self._blocco = threading.Lock()
        self._evento = threading.Event()
        self._fermo = threading.Event()
        self._corrente = None
        self._thread = None

    def avvia(self):
        try:
            with self._blocco:
                if self._thread is not None and self._thread.is_alive():
                    return
                self._fermo.clear()
                self._thread = threading.Thread(target=self._lavoro, name="DownloadPodcast", daemon=True)
                self._thread.start()
        except Exception as ex:
            scrivi_log("PodcastDownloads.avvia", ex)

    def ferma(self):
        try:
            self._fermo.set()
            with self._blocco:
                self._coda.clear()
                if self._corrente is not None:
                    self._corrente["annulla"].set()
            self._evento.set()
        except Exception as ex:
            scrivi_log("PodcastDownloads.ferma", ex)

    def stato(self, audio_url):
        try:
            with self._blocco:
                if self._corrente is not None and self._corrente["episodio"].audio_url == audio_url:
                    return STATO_IN_CORSO
                if any(elemento.audio_url == audio_url for elemento in self._coda):
                    return STATO_IN_CODA
            if self.percorso_locale(audio_url):
                return STATO_SCARICATO
            return None
        except Exception as ex:
            scrivi_log(f"PodcastDownloads.stato ({audio_url})", ex)
            return None

    def accoda(self, episodio):
        try:
            stato = self.stato(episodio.audio_url)
            if stato is not None:
                return stato
            with self._blocco:
                self._coda.append(episodio)
            self.avvia()
            self._evento.set()
            return ESITO_ACCODATO
        except Exception as ex:
            scrivi_log(f"PodcastDownloads.accoda ({episodio.audio_url})", ex)
            return None

    def annulla(self, audio_url):
        try:
            with self._blocco:
                for elemento in list(self._coda):
                    if elemento.audio_url == audio_url:
                        self._coda.remove(elemento)
                        return True
                if self._corrente is not None and self._corrente["episodio"].audio_url == audio_url:
                    self._corrente["annulla"].set()
                    return True
            return False
        except Exception as ex:
            scrivi_log(f"PodcastDownloads.annulla ({audio_url})", ex)
            return False

    def in_corso(self):
        elenco = []
        try:
            with self._blocco:
                if self._corrente is not None:
                    totale = self._corrente["totale"]
                    letti = self._corrente["letti"]
                    percentuale = int(letti * 100 / totale) if totale else None
                    elenco.append(
                        {
                            "episodio": self._corrente["episodio"],
                            "in_coda": False,
                            "percentuale": percentuale,
                            "megabyte": round(letti / 1048576, 1),
                        }
                    )
                for episodio in self._coda:
                    elenco.append({"episodio": episodio, "in_coda": True, "percentuale": None, "megabyte": 0})
        except Exception as ex:
            scrivi_log("PodcastDownloads.in_corso", ex)
        return elenco

    def elenco(self):
        risultati = []
        try:
            righe = self.db.leggi_tutti(
                "SELECT feed_url, podcast_name, guid, title, audio_url, file_path, size, published, duration, description "
                "FROM podcast_downloads ORDER BY downloaded_at DESC"
            )
            mancanti = []
            for riga in righe:
                if not riga[5] or not Path(riga[5]).is_file():
                    mancanti.append((riga[4],))
                    continue
                risultati.append(
                    {
                        "episodio": Episode(
                            title=riga[3],
                            audio_url=riga[4],
                            guid=riga[2],
                            feed_url=riga[0],
                            podcast_name=riga[1],
                            published=testo_in_data(riga[7]),
                            duration=riga[8],
                            description=riga[9],
                        ),
                        "file_path": riga[5],
                        "size": int(riga[6] or 0),
                    }
                )
            if mancanti:
                self.db.esegui_molti("DELETE FROM podcast_downloads WHERE audio_url = ?", mancanti)
        except Exception as ex:
            scrivi_log("PodcastDownloads.elenco", ex)
        return risultati

    def percorso_locale(self, audio_url):
        try:
            riga = self.db.leggi_uno("SELECT file_path FROM podcast_downloads WHERE audio_url = ?", (audio_url,))
            if riga and riga[0] and Path(riga[0]).is_file():
                return riga[0]
            return None
        except Exception as ex:
            scrivi_log(f"PodcastDownloads.percorso_locale ({audio_url})", ex)
            return None

    def elimina(self, audio_url):
        try:
            riga = self.db.leggi_uno("SELECT file_path FROM podcast_downloads WHERE audio_url = ?", (audio_url,))
            if riga and riga[0]:
                file_audio = Path(riga[0])
                try:
                    if file_audio.is_file():
                        file_audio.unlink()
                except Exception as ex:
                    scrivi_log(f"PodcastDownloads.elimina file ({file_audio})", ex)
                    return False
                try:
                    cartella = file_audio.parent
                    if cartella != percorsi.cartella_podcast() and cartella.is_dir() and not any(cartella.iterdir()):
                        cartella.rmdir()
                except Exception as ex:
                    scrivi_log(f"PodcastDownloads.elimina cartella ({file_audio.parent})", ex)
            return self.db.esegui("DELETE FROM podcast_downloads WHERE audio_url = ?", (audio_url,))
        except Exception as ex:
            scrivi_log(f"PodcastDownloads.elimina ({audio_url})", ex)
            return False

    def _lavoro(self):
        try:
            while not self._fermo.is_set():
                with self._blocco:
                    episodio = self._coda.popleft() if self._coda else None
                    if episodio is not None:
                        self._corrente = {"episodio": episodio, "letti": 0, "totale": 0, "annulla": threading.Event()}
                    else:
                        self._evento.clear()
                if episodio is None:
                    self._evento.wait(60)
                    continue
                try:
                    self._scarica(episodio)
                finally:
                    with self._blocco:
                        self._corrente = None
        except Exception as ex:
            scrivi_log("PodcastDownloads._lavoro", ex)

    def _aggiorna_avanzamento(self, letti, totale):
        try:
            with self._blocco:
                if self._corrente is not None:
                    self._corrente["letti"] = letti
                    self._corrente["totale"] = totale
        except Exception as ex:
            scrivi_log("PodcastDownloads._aggiorna_avanzamento", ex)

    def _scarica(self, episodio):
        destinazione = None
        try:
            with self._blocco:
                annulla = self._corrente["annulla"] if self._corrente is not None else threading.Event()
            cartella = percorsi.cartella_podcast() / nome_sicuro(episodio.podcast_name, "Podcast")
            cartella.mkdir(parents=True, exist_ok=True)
            destinazione = percorso_libero(cartella, nome_sicuro(episodio.title), estensione_audio(episodio.audio_url))
            dimensione = rete.scarica_file(episodio.audio_url, destinazione, self._aggiorna_avanzamento, annulla)
            salvato = self.db.esegui(
                "INSERT INTO podcast_downloads "
                "(feed_url, podcast_name, guid, title, audio_url, file_path, size, published, duration, description, downloaded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (audio_url) DO UPDATE SET file_path = excluded.file_path, size = excluded.size, "
                "downloaded_at = excluded.downloaded_at",
                (
                    episodio.feed_url,
                    episodio.podcast_name,
                    episodio.guid,
                    episodio.title,
                    episodio.audio_url,
                    str(destinazione),
                    dimensione,
                    data_in_testo(episodio.published),
                    episodio.duration,
                    episodio.description,
                    time.time(),
                ),
            )
            if not salvato:
                raise RuntimeError("Registrazione del download nel database non riuscita")
            if self.al_completamento is not None:
                GLib.idle_add(self._consegna, self.al_completamento, episodio)
        except rete.DownloadAnnullato:
            return
        except Exception as ex:
            scrivi_log(f"PodcastDownloads._scarica ({episodio.audio_url})", ex)
            try:
                if destinazione is not None and destinazione.is_file() and not self.percorso_locale(episodio.audio_url):
                    os.remove(destinazione)
            except Exception as ex_pulizia:
                scrivi_log(f"PodcastDownloads._scarica pulizia ({destinazione})", ex_pulizia)
            if self.al_errore is not None and not self._fermo.is_set():
                GLib.idle_add(self._consegna, self.al_errore, episodio)

    def _consegna(self, funzione, episodio):
        try:
            funzione(episodio)
        except Exception as ex:
            scrivi_log("PodcastDownloads._consegna", ex)
        return False
