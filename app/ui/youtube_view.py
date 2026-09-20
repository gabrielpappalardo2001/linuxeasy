from functools import partial

from app.core.log import scrivi_log
from app.core.mpv_engine import TrackInfo
from app.youtube.youtube_library import da_risultato
from app.youtube.youtube_search import ErroreYouTube

ERRORE_SERVIZIO = "Impossibile contattare YouTube. Riprovare più tardi."
ERRORE_LOG = "I dettagli sono nel file di log."


class YouTubeView:
    def __init__(self, finestra, engine, library, search_client):
        self.finestra = finestra
        self.engine = engine
        self.library = library
        self.search_client = search_client

    def _operazione(self, testo_ok, testo_errore, funzione, *argomenti):
        try:
            if funzione(*argomenti):
                self.finestra.mostra_stato(testo_ok)
            else:
                self.finestra.mostra_messaggio(testo_errore, ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"{self.__class__.__name__}._operazione ({testo_ok})", ex)
            self.finestra.mostra_messaggio(testo_errore, ERRORE_LOG)

    def get_menu_items(self):
        try:
            return [
                ("Cerca video", self.cerca, None),
                ("Video preferiti", self.apri_preferiti, None),
                ("Video recenti", self.apri_recenti, None),
                ("Ricerche recenti", self.apri_ricerche_recenti, None),
            ]
        except Exception as ex:
            scrivi_log("YouTubeView.get_menu_items", ex)
            return [("Cerca video", self.cerca, None)]

    def _etichetta(self, video):
        try:
            parti = [video.title]
            if getattr(video, "channel", ""):
                parti.append(video.channel)
            if getattr(video, "duration", ""):
                parti.append(video.duration)
            return ", ".join(parte for parte in parti if parte)
        except Exception as ex:
            scrivi_log("YouTubeView._etichetta", ex)
            return str(getattr(video, "title", ""))

    def _voci_video(self, elenco, recenti=False):
        voci = []
        try:
            elenco = list(elenco or [])
            for indice, video in enumerate(elenco):
                voci.append(
                    (
                        self._etichetta(video),
                        partial(self.riproduci, elenco, indice),
                        partial(self._azioni_video, elenco, indice, recenti),
                    )
                )
        except Exception as ex:
            scrivi_log("YouTubeView._voci_video", ex)
        return voci

    def _azioni_video(self, elenco, indice, recenti):
        try:
            video = elenco[indice]
            azioni = [("Riproduci", partial(self.riproduci, elenco, indice), None)]
            if self.library.is_favorite(video.video_id):
                azioni.append(
                    (
                        "Rimuovi dai video preferiti",
                        partial(
                            self._operazione,
                            "Video rimosso dai preferiti.",
                            "Impossibile rimuovere il video dai preferiti.",
                            self.library.remove_favorite,
                            video.video_id,
                        ),
                        None,
                    )
                )
            else:
                azioni.append(("Aggiungi ai video preferiti", partial(self.aggiungi_preferito, video), None))
            if recenti:
                azioni.append(
                    (
                        "Rimuovi dai video recenti",
                        partial(
                            self._operazione,
                            "Video rimosso dai recenti.",
                            "Impossibile rimuovere il video dai recenti.",
                            self.library.remove_recent,
                            video.video_id,
                        ),
                        None,
                    )
                )
                azioni.append(("Svuota i video recenti", self.svuota_recenti, None))
            return azioni
        except Exception as ex:
            scrivi_log("YouTubeView._azioni_video", ex)
            return []

    def riproduci(self, elenco, indice):
        try:
            if not 0 <= indice < len(elenco):
                return
            video = elenco[indice]
            if not video.url:
                self.finestra.mostra_messaggio("Il video non ha un indirizzo valido.")
                return
            selezionati = self.finestra.get_selected_indices() if hasattr(self.finestra, "get_selected_indices") else []
            selezionati = [i for i in selezionati if 0 <= i < len(elenco)]
            if selezionati:
                indici = selezionati if indice in selezionati else sorted(set(selezionati) | {indice})
            else:
                indici = [indice]
            sotto_elenco = [elenco[i] for i in indici]
            avvio = indici.index(indice)
            tracce = [TrackInfo(title=self._etichetta(item), url=item.url) for item in sotto_elenco]
            if self.engine is None or not self.engine.load_playlist(tracce, avvio, kind="youtube"):
                self.finestra.mostra_messaggio("Impossibile avviare la riproduzione.", "Verificare che mpv sia installato.")
                return
            self.library.add_recent(da_risultato(video))
            if len(sotto_elenco) > 1:
                self.finestra.mostra_stato(
                    f"In riproduzione: {video.title} ({len(sotto_elenco)} video selezionati). "
                    "Ctrl+F per il video successivo, Ctrl+B per il precedente."
                )
            else:
                self.finestra.mostra_stato(f"In riproduzione: {video.title}")
            if hasattr(self.finestra, "apri_player"):
                self.finestra.apri_player()
        except Exception as ex:
            scrivi_log("YouTubeView.riproduci", ex)

    def aggiungi_preferito(self, video):
        try:
            if self.library.add_favorite(da_risultato(video)):
                self.finestra.mostra_stato("Video aggiunto ai preferiti.")
            else:
                self.finestra.mostra_messaggio("Impossibile aggiungere il video ai preferiti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("YouTubeView.aggiungi_preferito", ex)

    def cerca(self):
        try:
            testo = self.finestra.chiedi_testo("Cerca video", "Testo da cercare su YouTube")
            if testo:
                self.esegui_ricerca(testo)
        except Exception as ex:
            scrivi_log("YouTubeView.cerca", ex)

    def esegui_ricerca(self, testo):
        try:
            self.library.add_search(testo)
            self.finestra.carica_in_background(
                f"Video trovati per {testo}",
                partial(self.search_client.search, testo),
                self._voci_video,
                "Nessun video trovato.",
                self._messaggio_errore,
                selezione=True,
            )
        except Exception as ex:
            scrivi_log(f"YouTubeView.esegui_ricerca ({testo})", ex)

    def _messaggio_errore(self, errore):
        try:
            if isinstance(errore, ErroreYouTube):
                return ERRORE_SERVIZIO
            return "Impossibile completare la ricerca su YouTube."
        except Exception as ex:
            scrivi_log("YouTubeView._messaggio_errore", ex)
            return ERRORE_SERVIZIO

    def apri_ricerche_recenti(self):
        try:
            self.finestra.push_menu("Ricerche recenti di YouTube", self._voci_ricerche, "Nessuna ricerca recente.")
        except Exception as ex:
            scrivi_log("YouTubeView.apri_ricerche_recenti", ex)

    def _voci_ricerche(self):
        voci = []
        try:
            for testo in self.library.list_searches():
                voci.append(
                    (
                        testo,
                        partial(self.esegui_ricerca, testo),
                        [
                            ("Cerca di nuovo", partial(self.esegui_ricerca, testo), None),
                            (
                                "Rimuovi dalle ricerche recenti",
                                partial(
                                    self._operazione,
                                    "Ricerca rimossa dalle recenti.",
                                    "Impossibile rimuovere la ricerca.",
                                    self.library.remove_search,
                                    testo,
                                ),
                                None,
                            ),
                            ("Svuota le ricerche recenti", self.svuota_ricerche, None),
                        ],
                    )
                )
        except Exception as ex:
            scrivi_log("YouTubeView._voci_ricerche", ex)
        return voci

    def svuota_ricerche(self):
        try:
            if self.finestra.chiedi_conferma("Svuotare le ricerche recenti di YouTube?"):
                self._operazione(
                    "Ricerche recenti svuotate.",
                    "Impossibile svuotare le ricerche recenti.",
                    self.library.clear_searches,
                )
        except Exception as ex:
            scrivi_log("YouTubeView.svuota_ricerche", ex)

    def apri_preferiti(self):
        try:
            self.finestra.push_menu(
                "Video preferiti",
                lambda: self._voci_video(self.library.list_favorites()),
                "Nessun video preferito.",
                selezione=True,
            )
        except Exception as ex:
            scrivi_log("YouTubeView.apri_preferiti", ex)

    def apri_recenti(self):
        try:
            self.finestra.push_menu(
                "Video recenti",
                lambda: self._voci_video(self.library.list_recent(), recenti=True),
                "Nessun video ascoltato di recente.",
                selezione=True,
            )
        except Exception as ex:
            scrivi_log("YouTubeView.apri_recenti", ex)

    def svuota_recenti(self):
        try:
            if self.finestra.chiedi_conferma("Svuotare l'elenco dei video recenti?"):
                self._operazione(
                    "Elenco dei video recenti svuotato.",
                    "Impossibile svuotare l'elenco dei video recenti.",
                    self.library.clear_recent,
                )
        except Exception as ex:
            scrivi_log("YouTubeView.svuota_recenti", ex)
