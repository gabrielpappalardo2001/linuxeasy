import threading

from gi.repository import GLib

from app.core.log import scrivi_log
from app.podcasts.podcast_source import fetch_feed

INTERVALLO_MINUTI = 30
RITARDO_INIZIALE_SECONDI = 20
EPISODI_CONTROLLATI = 50


class PodcastNotifier:
    def __init__(self, library, al_rilevamento=None, intervallo_minuti=INTERVALLO_MINUTI, ritardo_iniziale=RITARDO_INIZIALE_SECONDI):
        self.library = library
        self.al_rilevamento = al_rilevamento
        self.intervallo = max(5, int(intervallo_minuti)) * 60
        self.ritardo_iniziale = max(0, int(ritardo_iniziale))
        self._fermo = threading.Event()
        self._blocco_controllo = threading.Lock()
        self._thread = None

    def avvia(self):
        try:
            if self._thread is not None and self._thread.is_alive():
                return
            self._fermo.clear()
            self._thread = threading.Thread(target=self._ciclo, name="ControlloNuoviEpisodi", daemon=True)
            self._thread.start()
        except Exception as ex:
            scrivi_log("PodcastNotifier.avvia", ex)

    def ferma(self):
        try:
            self._fermo.set()
        except Exception as ex:
            scrivi_log("PodcastNotifier.ferma", ex)

    @property
    def controllo_in_corso(self):
        return self._blocco_controllo.locked()

    def _ciclo(self):
        try:
            if self._fermo.wait(self.ritardo_iniziale):
                return
            while not self._fermo.is_set():
                self._esegui_controllo(None)
                if self._fermo.wait(self.intervallo):
                    return
        except Exception as ex:
            scrivi_log("PodcastNotifier._ciclo", ex)

    def controlla_ora(self, al_termine=None):
        try:
            threading.Thread(
                target=self._esegui_controllo,
                args=(al_termine,),
                name="ControlloManualeEpisodi",
                daemon=True,
            ).start()
        except Exception as ex:
            scrivi_log("PodcastNotifier.controlla_ora", ex)

    def stabilisci_riferimento(self, feed_url):
        try:
            threading.Thread(
                target=self._riferimento,
                args=(feed_url,),
                name="RiferimentoEpisodi",
                daemon=True,
            ).start()
        except Exception as ex:
            scrivi_log(f"PodcastNotifier.stabilisci_riferimento ({feed_url})", ex)

    def _riferimento(self, feed_url):
        try:
            _nome, episodi = fetch_feed(feed_url, EPISODI_CONTROLLATI)
            self.library.mark_known(feed_url, [episodio.guid for episodio in episodi])
        except Exception as ex:
            scrivi_log(f"PodcastNotifier._riferimento ({feed_url})", ex)

    def _esegui_controllo(self, al_termine):
        nuovi = []
        errori = 0
        try:
            with self._blocco_controllo:
                for iscrizione in self.library.list_subscriptions():
                    if self._fermo.is_set():
                        break
                    try:
                        nome, episodi = fetch_feed(iscrizione.feed_url, EPISODI_CONTROLLATI)
                    except Exception as ex:
                        errori += 1
                        scrivi_log(f"PodcastNotifier._esegui_controllo feed ({iscrizione.feed_url})", ex)
                        continue
                    try:
                        for episodio in episodi:
                            episodio.podcast_name = iscrizione.name or nome or episodio.podcast_name
                            episodio.feed_url = iscrizione.feed_url
                        guids = [episodio.guid for episodio in episodi]
                        if not self.library.has_known(iscrizione.feed_url):
                            self.library.mark_known(iscrizione.feed_url, guids)
                            continue
                        sconosciuti = self.library.unknown_guids(iscrizione.feed_url, guids)
                        trovati = [episodio for episodio in episodi if episodio.guid in sconosciuti]
                        self.library.mark_known(iscrizione.feed_url, guids)
                        if trovati:
                            self.library.add_new(trovati)
                            nuovi.extend(trovati)
                    except Exception as ex:
                        errori += 1
                        scrivi_log(f"PodcastNotifier._esegui_controllo confronto ({iscrizione.feed_url})", ex)
        except Exception as ex:
            errori += 1
            scrivi_log("PodcastNotifier._esegui_controllo", ex)
        try:
            if nuovi and self.al_rilevamento is not None and not self._fermo.is_set():
                GLib.idle_add(self._consegna, self.al_rilevamento, nuovi)
            if al_termine is not None:
                GLib.idle_add(self._consegna_termine, al_termine, nuovi, errori)
        except Exception as ex:
            scrivi_log("PodcastNotifier._esegui_controllo consegna", ex)
        return nuovi

    def _consegna(self, funzione, nuovi):
        try:
            funzione(nuovi)
        except Exception as ex:
            scrivi_log("PodcastNotifier._consegna", ex)
        return False

    def _consegna_termine(self, funzione, nuovi, errori):
        try:
            funzione(nuovi, errori)
        except Exception as ex:
            scrivi_log("PodcastNotifier._consegna_termine", ex)
        return False
