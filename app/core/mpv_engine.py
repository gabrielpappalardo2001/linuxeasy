import locale
import threading
import time

from app.core import percorsi
from app.core.log import scrivi_log

try:
    import mpv
except Exception as errore_importazione:
    mpv = None
    scrivi_log("mpv_engine: impossibile importare python-mpv", errore_importazione)

SECONDI_AVANTI_INDIETRO = 10
VOLUME_PREDEFINITO = 100
SECONDI_SALVATAGGIO_POSIZIONE = 5
SECONDI_MINIMI_POSIZIONE = 10
SECONDI_FINE_BRANO = 20
SECONDI_ATTESA_RIPRISTINO = 30
PAUSA_ATTESA_RIPRISTINO = 0.2
TIPI_SENZA_POSIZIONE = ("stream",)
FILE_CONFIGURAZIONE_TASTI = percorsi.cartella_profilo() / ".config" / "mpv" / "input.conf"
MARCATORE_CONFIGURAZIONE = "# Aggiunto da LinuxEasy: passa al brano precedente o successivo in coda"
RIGHE_CONFIGURAZIONE_TASTI = (
    f"{MARCATORE_CONFIGURAZIONE}\n"
    "ctrl+b playlist-prev\n"
    "ctrl+f playlist-next\n"
)

OPZIONI_PLAYER = {
    "ytdl": True,
    "input_default_bindings": False,
    "input_vo_keyboard": False,
    "input_terminal": False,
    "input_cursor": False,
    "input_media_keys": False,
    "osc": False,
    "osd_level": 0,
    "cursor_autohide": "no",
    "force_window": False,
    "keep_open": False,
    "idle": True,
}


class TrackInfo:
    def __init__(self, title="", artist="", album="", url="", duration=0):
        self.title = title
        self.artist = artist
        self.album = album
        self.url = url
        self.duration = duration


def assicura_configurazione_globale():
    try:
        percorso = FILE_CONFIGURAZIONE_TASTI
        if percorso.is_file():
            if MARCATORE_CONFIGURAZIONE in percorso.read_text(encoding="utf-8", errors="replace"):
                return True
            with open(percorso, "a", encoding="utf-8") as file_configurazione:
                file_configurazione.write("\n" + RIGHE_CONFIGURAZIONE_TASTI)
            return True
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text(RIGHE_CONFIGURAZIONE_TASTI, encoding="utf-8")
        return True
    except Exception as ex:
        scrivi_log("mpv_engine.assicura_configurazione_globale", ex)
        return False


class MPVEngine:
    def __init__(self, al_cambio_traccia=None, al_cambio_video=None, impostazioni=None, al_ripristino_posizione=None):
        self.player = None
        self.current_title = ""
        self.current_url = ""
        self.current_index = 0
        self.current_kind = ""
        self.playlist_length = 0
        self.al_cambio_traccia = al_cambio_traccia
        self.al_cambio_video = al_cambio_video
        self.al_ripristino_posizione = al_ripristino_posizione
        self.impostazioni = impostazioni
        self._titoli_coda = []
        self._blocco = threading.RLock()
        self._identificativo_finestra = 0
        self._finestra_del_player = 0
        self._fabbrica_render = None
        self._contesto_render = None
        self._volume_desiderato = VOLUME_PREDEFINITO
        self._video_presente = False
        self._generazione_ripristino = 0
        self._ultimo_salvataggio = None
        self._fermo_posizioni = threading.Event()
        self._thread_posizioni = None
        try:
            self._volume_desiderato = self._volume_iniziale()
            self._avvia_salvataggio_posizioni()
        except Exception as ex:
            scrivi_log("MPVEngine.__init__", ex)

    def _volume_iniziale(self):
        try:
            if self.impostazioni is not None and self.impostazioni.ricorda_volume():
                valore = self.impostazioni.volume_salvato()
                if valore is not None:
                    return max(0, min(130, float(valore)))
        except Exception as ex:
            scrivi_log("MPVEngine._volume_iniziale", ex)
        return VOLUME_PREDEFINITO

    def imposta_finestra(self, identificativo):
        try:
            nuovo = int(identificativo or 0)
            with self._blocco:
                if nuovo == self._identificativo_finestra:
                    return True
                self._identificativo_finestra = nuovo
                if self.player is not None and self._finestra_del_player != nuovo:
                    self._distruggi_player()
                    return self._crea_player()
            return True
        except Exception as ex:
            scrivi_log(f"MPVEngine.imposta_finestra ({identificativo})", ex)
            return False

    def imposta_render(self, fabbrica):
        try:
            with self._blocco:
                self._fabbrica_render = fabbrica
                self._distruggi_player()
                if not self._crea_player():
                    return False
                return self._contesto_render is not None
        except Exception as ex:
            scrivi_log("MPVEngine.imposta_render", ex)
            return False

    def ha_finestra_incastonata(self):
        return bool(self._contesto_render) or bool(self._identificativo_finestra)

    def solo_audio(self):
        return not self.ha_finestra_incastonata()

    def _distruggi_player(self):
        try:
            if self.player is None:
                return
            giocatore = self.player
            self.player = None
            self._finestra_del_player = 0
            contesto = self._contesto_render
            self._contesto_render = None
            if contesto is not None:
                try:
                    contesto.update_cb = None
                    contesto.free()
                except Exception as ex:
                    scrivi_log("MPVEngine._distruggi_player: contesto di render non liberato", ex)
            try:
                giocatore.terminate()
            except Exception as ex:
                scrivi_log("MPVEngine._distruggi_player: chiusura non riuscita", ex)
        except Exception as ex:
            scrivi_log("MPVEngine._distruggi_player", ex)

    def _crea_player(self):
        try:
            if mpv is None:
                return False
            locale.setlocale(locale.LC_NUMERIC, "C")
            opzioni = dict(OPZIONI_PLAYER)
            if self._fabbrica_render is not None:
                opzioni["vo"] = "libmpv"
            elif self._identificativo_finestra:
                opzioni["wid"] = str(self._identificativo_finestra)
            else:
                opzioni["vo"] = "null"
                opzioni["vid"] = "no"
            try:
                self.player = mpv.MPV(**opzioni)
            except Exception as ex:
                scrivi_log("MPVEngine._crea_player: opzioni complete rifiutate, uso quelle minime", ex, conta=False)
                minime = {
                    "ytdl": True,
                    "input_default_bindings": False,
                    "input_vo_keyboard": False,
                    "osc": False,
                }
                if self._fabbrica_render is not None:
                    minime["vo"] = "libmpv"
                elif self._identificativo_finestra:
                    minime["wid"] = str(self._identificativo_finestra)
                else:
                    minime["vo"] = "null"
                    minime["vid"] = "no"
                self.player = mpv.MPV(**minime)
            self._finestra_del_player = self._identificativo_finestra
            if self._fabbrica_render is not None:
                self._contesto_render = None
                try:
                    self._contesto_render = self._fabbrica_render(self.player)
                except Exception as ex:
                    scrivi_log("MPVEngine._crea_player: contesto di render non creato", ex)
                if self._contesto_render is None:
                    self._fabbrica_render = None
                    giocatore = self.player
                    self.player = None
                    try:
                        giocatore.terminate()
                    except Exception as ex:
                        scrivi_log("MPVEngine._crea_player: chiusura del player provvisorio", ex)
                    return self._crea_player()
            self.player.observe_property("path", self._alla_variazione_percorso)
            self.player.observe_property("video-format", self._alla_variazione_video)
            try:
                self.player.volume = self._volume_desiderato
            except Exception as ex:
                scrivi_log("MPVEngine._crea_player: volume non applicato", ex)
            return True
        except Exception as ex:
            scrivi_log("MPVEngine._crea_player", ex)
            self.player = None
            self._finestra_del_player = 0
            return False

    def _assicura_player(self):
        if self.player is not None:
            return True
        return self._crea_player()

    def _alla_variazione_video(self, nome, valore):
        try:
            presente = bool(valore)
            if presente == self._video_presente:
                return
            self._video_presente = presente
            if self.al_cambio_video is not None:
                self.al_cambio_video(presente)
        except Exception as ex:
            scrivi_log("MPVEngine._alla_variazione_video", ex)

    def has_video(self):
        return self._video_presente

    def _alla_variazione_percorso(self, nome, valore):
        try:
            if not valore:
                return
            self._richiedi_ripristino(str(valore), self.current_kind)
            with self._blocco:
                if self.playlist_length < 2 or not self._titoli_coda:
                    return
                try:
                    indice = self.player.playlist_pos if self.player is not None else -1
                except Exception as ex:
                    scrivi_log("MPVEngine._alla_variazione_percorso: lettura della posizione in coda non riuscita", ex)
                    indice = -1
                if isinstance(indice, int) and 0 <= indice < len(self._titoli_coda):
                    self.current_index = indice
                    self.current_title = self._titoli_coda[indice]
                self.current_url = valore
                titolo = self.current_title
            if self.al_cambio_traccia is not None:
                self.al_cambio_traccia(self.current_index, titolo)
        except Exception as ex:
            scrivi_log("MPVEngine._alla_variazione_percorso", ex)

    def _ricorda_posizione_attivo(self):
        try:
            return self.impostazioni is not None and self.impostazioni.ricorda_posizione()
        except Exception as ex:
            scrivi_log("MPVEngine._ricorda_posizione_attivo", ex)
            return False

    def _tipo_con_posizione(self, tipo):
        return tipo not in TIPI_SENZA_POSIZIONE

    def _richiedi_ripristino(self, percorso, tipo):
        try:
            if not percorso or not self._tipo_con_posizione(tipo) or not self._ricorda_posizione_attivo():
                return False
            posizione = self.impostazioni.posizione_salvata(percorso)
            if posizione < SECONDI_MINIMI_POSIZIONE:
                return False
            with self._blocco:
                self._generazione_ripristino += 1
                generazione = self._generazione_ripristino
            threading.Thread(
                target=self._ripristina,
                args=(generazione, percorso, posizione),
                name="RipristinoPosizione",
                daemon=True,
            ).start()
            return True
        except Exception as ex:
            scrivi_log(f"MPVEngine._richiedi_ripristino ({percorso})", ex)
            return False

    def _ripristina(self, generazione, percorso, posizione):
        try:
            scadenza = time.monotonic() + SECONDI_ATTESA_RIPRISTINO
            while time.monotonic() < scadenza:
                if generazione != self._generazione_ripristino:
                    return
                giocatore = self.player
                if giocatore is None:
                    return
                try:
                    corrente = getattr(giocatore, "path", None)
                    durata = getattr(giocatore, "duration", None)
                    spostabile = getattr(giocatore, "seekable", None)
                except Exception as ex:
                    scrivi_log(f"MPVEngine._ripristina: lettura dello stato non riuscita ({percorso})", ex)
                    return
                if corrente and str(corrente) == percorso and durata and spostabile:
                    if float(durata) - posizione <= SECONDI_FINE_BRANO:
                        return
                    with self._blocco:
                        if generazione != self._generazione_ripristino or self.player is not giocatore:
                            return
                        giocatore.seek(posizione, reference="absolute")
                    if self.al_ripristino_posizione is not None:
                        self.al_ripristino_posizione(posizione)
                    return
                time.sleep(PAUSA_ATTESA_RIPRISTINO)
        except Exception as ex:
            scrivi_log(f"MPVEngine._ripristina ({percorso})", ex)

    def _ripristino_in_attesa(self):
        try:
            return any(
                thread.name == "RipristinoPosizione" and thread.is_alive() for thread in threading.enumerate()
            )
        except Exception as ex:
            scrivi_log("MPVEngine._ripristino_in_attesa", ex)
            return False

    def memorizza_posizione(self):
        try:
            if not self._ricorda_posizione_attivo():
                return False
            with self._blocco:
                if self.player is None or not self._tipo_con_posizione(self.current_kind):
                    return False
                if getattr(self.player, "idle_active", True):
                    return False
                percorso = getattr(self.player, "path", None) or self.current_url
                posizione = getattr(self.player, "time_pos", None)
                durata = getattr(self.player, "duration", None)
                titolo = self.current_title
            if not percorso or posizione is None or not durata:
                return False
            percorso = str(percorso)
            posizione = float(posizione)
            durata = float(durata)
            if durata - posizione <= SECONDI_FINE_BRANO:
                self._ultimo_salvataggio = None
                return self.impostazioni.cancella_posizione(percorso)
            if posizione < SECONDI_MINIMI_POSIZIONE:
                return False
            firma = (percorso, int(posizione))
            if firma == self._ultimo_salvataggio:
                return True
            if self.impostazioni.salva_posizione(percorso, titolo, posizione, durata):
                self._ultimo_salvataggio = firma
                return True
            return False
        except Exception as ex:
            scrivi_log("MPVEngine.memorizza_posizione", ex)
            return False

    def _avvia_salvataggio_posizioni(self):
        try:
            if self._thread_posizioni is not None and self._thread_posizioni.is_alive():
                return
            self._fermo_posizioni.clear()
            self._thread_posizioni = threading.Thread(
                target=self._ciclo_posizioni,
                name="SalvataggioPosizioni",
                daemon=True,
            )
            self._thread_posizioni.start()
        except Exception as ex:
            scrivi_log("MPVEngine._avvia_salvataggio_posizioni", ex)

    def _ciclo_posizioni(self):
        try:
            while not self._fermo_posizioni.wait(SECONDI_SALVATAGGIO_POSIZIONE):
                try:
                    if self._ripristino_in_attesa() or not self.is_playing():
                        continue
                    self.memorizza_posizione()
                except Exception as ex:
                    scrivi_log("MPVEngine._ciclo_posizioni giro", ex)
        except Exception as ex:
            scrivi_log("MPVEngine._ciclo_posizioni", ex)

    def memorizza_volume(self):
        try:
            if self.impostazioni is None or not self.impostazioni.ricorda_volume():
                return False
            return self.impostazioni.salva_volume(self.get_volume())
        except Exception as ex:
            scrivi_log("MPVEngine.memorizza_volume", ex)
            return False

    def play(self, url, title="", kind=""):
        try:
            if not url:
                return False
            if not self._ripristino_in_attesa():
                self.memorizza_posizione()
            with self._blocco:
                if not self._assicura_player():
                    return False
                self._generazione_ripristino += 1
                self._ultimo_salvataggio = None
                self.current_url = url
                self.current_title = title or url
                self.current_index = 0
                self.current_kind = kind
                self._titoli_coda = [self.current_title]
                self.playlist_length = 1
                try:
                    self.player.pause = False
                    self.player.play(url)
                except Exception as ex:
                    scrivi_log(f"MPVEngine.play: play non riuscito, provo loadfile ({url})", ex, conta=False)
                    self.player.command("loadfile", url, "replace")
            self._richiedi_ripristino(str(url), kind)
            return True
        except Exception as ex:
            scrivi_log(f"MPVEngine.play ({url})", ex)
            return False

    def load_playlist(self, tracks, start_index=0, kind=""):
        try:
            elenco = list(tracks or [])
            if not elenco:
                return False
            if not self._ripristino_in_attesa():
                self.memorizza_posizione()
            indice_iniziale = start_index if 0 <= start_index < len(elenco) else 0
            with self._blocco:
                if not self._assicura_player():
                    return False
                self._generazione_ripristino += 1
                self._ultimo_salvataggio = None
                titoli_precedenti = self._titoli_coda
                lunghezza_precedente = self.playlist_length
                tipo_precedente = self.current_kind
                self._titoli_coda = [traccia.title or traccia.url for traccia in elenco]
                self.playlist_length = len(elenco)
                self.current_kind = kind
                try:
                    self.player.pause = False
                    self.player.command("loadfile", elenco[0].url, "replace")
                    for traccia in elenco[1:]:
                        self.player.command("loadfile", traccia.url, "append")
                    if indice_iniziale > 0:
                        self.player.command("playlist-play-index", indice_iniziale)
                except Exception as ex:
                    scrivi_log("MPVEngine.load_playlist", ex)
                    self._titoli_coda = titoli_precedenti
                    self.playlist_length = lunghezza_precedente
                    self.current_kind = tipo_precedente
                    return False
                self.current_index = indice_iniziale
                self.current_title = self._titoli_coda[indice_iniziale]
                self.current_url = elenco[indice_iniziale].url
            self._richiedi_ripristino(str(elenco[indice_iniziale].url), kind)
            return True
        except Exception as ex:
            scrivi_log("MPVEngine.load_playlist", ex)
            return False

    def get_kind(self):
        return self.current_kind

    def next_track(self):
        try:
            with self._blocco:
                if self.player is None or self.playlist_length < 2:
                    return False
            if not self._ripristino_in_attesa():
                self.memorizza_posizione()
            with self._blocco:
                if self.player is None or self.playlist_length < 2:
                    return False
                self.player.command("playlist-next", "force")
            return True
        except Exception as ex:
            scrivi_log("MPVEngine.next_track", ex)
            return False

    def previous_track(self):
        try:
            with self._blocco:
                if self.player is None or self.playlist_length < 2:
                    return False
            if not self._ripristino_in_attesa():
                self.memorizza_posizione()
            with self._blocco:
                if self.player is None or self.playlist_length < 2:
                    return False
                self.player.command("playlist-prev", "force")
            return True
        except Exception as ex:
            scrivi_log("MPVEngine.previous_track", ex)
            return False

    def has_playlist(self):
        return self.playlist_length > 1

    def is_loaded(self):
        try:
            if self.player is None:
                return False
            return not getattr(self.player, "idle_active", True)
        except Exception as ex:
            scrivi_log("MPVEngine.is_loaded", ex)
            return False

    def seek(self, secondi):
        try:
            with self._blocco:
                if self.player is None:
                    return False
                self._generazione_ripristino += 1
                self.player.seek(secondi, reference="relative")
            return True
        except Exception as ex:
            scrivi_log(f"MPVEngine.seek ({secondi})", ex)
            return False

    def seek_forward(self):
        return self.seek(SECONDI_AVANTI_INDIETRO)

    def seek_backward(self):
        return self.seek(-SECONDI_AVANTI_INDIETRO)

    def stop(self):
        try:
            if not self._ripristino_in_attesa():
                self.memorizza_posizione()
            with self._blocco:
                self._generazione_ripristino += 1
                if self.player is None:
                    return
                try:
                    self.player.stop()
                except Exception as ex:
                    scrivi_log("MPVEngine.stop: stop non riuscito, provo il comando", ex, conta=False)
                    self.player.command("stop")
                self._titoli_coda = []
                self.playlist_length = 0
                self.current_index = 0
                self.current_kind = ""
                self._ultimo_salvataggio = None
            self._alla_variazione_video("video-format", None)
        except Exception as ex:
            scrivi_log("MPVEngine.stop", ex)

    def pause(self):
        try:
            if self.player is not None:
                self.player.pause = True
            if not self._ripristino_in_attesa():
                self.memorizza_posizione()
        except Exception as ex:
            scrivi_log("MPVEngine.pause", ex)

    def resume(self):
        try:
            if self.player is not None:
                self.player.pause = False
        except Exception as ex:
            scrivi_log("MPVEngine.resume", ex)

    def set_volume(self, value):
        try:
            self._volume_desiderato = max(0, min(130, float(value)))
            if self.player is not None:
                self.player.volume = self._volume_desiderato
            if self.impostazioni is not None and self.impostazioni.ricorda_volume():
                self.impostazioni.salva_volume(self._volume_desiderato)
        except Exception as ex:
            scrivi_log(f"MPVEngine.set_volume ({value})", ex)

    def get_volume(self):
        try:
            if self.player is not None:
                valore = getattr(self.player, "volume", self._volume_desiderato)
                return self._volume_desiderato if valore is None else valore
            return self._volume_desiderato
        except Exception as ex:
            scrivi_log("MPVEngine.get_volume", ex)
            return self._volume_desiderato

    def is_playing(self):
        try:
            if self.player is None:
                return False
            if getattr(self.player, "idle_active", False):
                return False
            return not getattr(self.player, "pause", False)
        except Exception as ex:
            scrivi_log("MPVEngine.is_playing", ex)
            return False

    def terminate(self):
        try:
            self._fermo_posizioni.set()
        except Exception as ex:
            scrivi_log("MPVEngine.terminate: arresto del salvataggio posizioni", ex)
        try:
            with self._blocco:
                self._generazione_ripristino += 1
                self._distruggi_player()
        except Exception as ex:
            scrivi_log("MPVEngine.terminate", ex)
