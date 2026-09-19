from functools import partial

from app.core.log import scrivi_log
from app.podcasts import podcast_downloads
from app.podcasts.podcast_search import CATEGORIE
from app.podcasts.podcast_source import fetch_feed
from app.podcasts.subscriptions import SavedPodcast, da_risultato

ERRORE_APPLE = "Impossibile contattare il servizio dei podcast. Riprovare più tardi."
ERRORE_FEED = "Impossibile leggere gli episodi del podcast. Riprovare più tardi."


class PodcastView:
    def __init__(self, finestra, engine, library, search_client, downloads, notifier):
        self.finestra = finestra
        self.engine = engine
        self.library = library
        self.search_client = search_client
        self.downloads = downloads
        self.notifier = notifier

    def get_menu_items(self):
        try:
            nuovi = self.library.count_new()
            voci = [
                (f"Nuovi episodi, {nuovi}" if nuovi else "Nuovi episodi, nessuno", self.apri_nuovi_episodi, None),
                ("Cerca podcast", self.cerca, None),
                ("Ricerche recenti", self.apri_ricerche_recenti, None),
                ("Podcast iscritti", self.apri_iscritti, None),
                ("Podcast preferiti", self.apri_preferiti, None),
                ("Podcast recenti", self.apri_recenti, None),
                ("Podcast per categoria", self.apri_categorie, None),
                ("Classifica dei podcast", self.apri_classifica, None),
                ("Episodi scaricati", self.apri_scaricati, None),
            ]
            in_corso = len(self.downloads.in_corso())
            if in_corso:
                voci.append((f"Download in corso, {in_corso}", self.apri_download_in_corso, None))
            voci.append(("Controlla ora i nuovi episodi", self.controlla_ora, None))
            return voci
        except Exception as ex:
            scrivi_log("PodcastView.get_menu_items", ex)
            return [("Cerca podcast", self.cerca, None)]

    def _etichetta_podcast(self, podcast, posizione=None):
        try:
            testo = podcast.name or podcast.feed_url
            if podcast.author and podcast.author != podcast.name:
                testo = f"{testo}, {podcast.author}"
            if posizione is not None:
                testo = f"{posizione}. {testo}"
            return testo
        except Exception as ex:
            scrivi_log("PodcastView._etichetta_podcast", ex)
            return str(getattr(podcast, "name", ""))

    def _voci_podcast(self, elenco, numerati=False, recenti=False):
        voci = []
        try:
            for posizione, elemento in enumerate(elenco or [], start=1):
                try:
                    podcast = elemento if isinstance(elemento, SavedPodcast) else da_risultato(elemento)
                    if not podcast.feed_url:
                        continue
                    voci.append(
                        (
                            self._etichetta_podcast(podcast, posizione if numerati else None),
                            partial(self.apri_podcast, podcast),
                            partial(self._azioni_podcast, podcast, recenti),
                        )
                    )
                except Exception as ex:
                    scrivi_log("PodcastView._voci_podcast elemento", ex)
        except Exception as ex:
            scrivi_log("PodcastView._voci_podcast", ex)
        return voci

    def _azioni_podcast(self, podcast, recenti=False):
        try:
            azioni = [("Apri gli episodi", partial(self.apri_podcast, podcast), None)]
            if self.library.is_subscribed(podcast.feed_url):
                azioni.append(("Annulla l'iscrizione", partial(self.annulla_iscrizione, podcast), None))
            else:
                azioni.append(("Iscriviti al podcast", partial(self.iscriviti, podcast), None))
            if self.library.is_favorite(podcast.feed_url):
                azioni.append(("Rimuovi dai podcast preferiti", partial(self.library.remove_favorite, podcast.feed_url), None))
            else:
                azioni.append(("Aggiungi ai podcast preferiti", partial(self.aggiungi_preferito, podcast), None))
            if recenti:
                azioni.append(("Rimuovi dai podcast recenti", partial(self.library.remove_recent, podcast.feed_url), None))
                azioni.append(("Svuota i podcast recenti", self.svuota_recenti, None))
            return azioni
        except Exception as ex:
            scrivi_log("PodcastView._azioni_podcast", ex)
            return []

    def iscriviti(self, podcast):
        try:
            if not self.library.subscribe(podcast):
                self.finestra.mostra_messaggio("Iscrizione non riuscita.", "I dettagli sono nel file di log.")
                return
            self.notifier.stabilisci_riferimento(podcast.feed_url)
            self.finestra.mostra_messaggio(
                f"Iscrizione a {podcast.name} effettuata.",
                "Quando esce un nuovo episodio compare un avviso in qualsiasi punto del programma.",
            )
        except Exception as ex:
            scrivi_log("PodcastView.iscriviti", ex)

    def annulla_iscrizione(self, podcast):
        try:
            if self.finestra.chiedi_conferma(f"Annullare l'iscrizione a {podcast.name}?"):
                self.library.unsubscribe(podcast.feed_url)
        except Exception as ex:
            scrivi_log("PodcastView.annulla_iscrizione", ex)

    def aggiungi_preferito(self, podcast):
        try:
            if self.library.add_favorite(podcast):
                self.finestra.mostra_stato("Podcast aggiunto ai preferiti.")
            else:
                self.finestra.mostra_messaggio("Impossibile aggiungere il podcast ai preferiti.")
        except Exception as ex:
            scrivi_log("PodcastView.aggiungi_preferito", ex)

    def apri_podcast(self, podcast):
        try:
            self.library.add_recent(podcast)
            self.finestra.carica_in_background(
                podcast.name or "Episodi",
                partial(fetch_feed, podcast.feed_url, 300),
                partial(self._voci_episodi_podcast, podcast),
                "Nessun episodio trovato.",
                ERRORE_FEED,
            )
        except Exception as ex:
            scrivi_log(f"PodcastView.apri_podcast ({podcast.feed_url})", ex)

    def _voci_episodi_podcast(self, podcast, risultato):
        voci = []
        try:
            nome_feed, episodi = risultato
            nome = podcast.name or nome_feed
            if nome_feed and not podcast.name:
                podcast.name = nome_feed
                self.library.add_recent(podcast)
            for episodio in episodi:
                episodio.podcast_name = nome
                episodio.feed_url = podcast.feed_url
                voci.append(
                    (
                        episodio.label(),
                        partial(self.riproduci_episodio, episodio),
                        partial(self._azioni_episodio, episodio, False, podcast),
                    )
                )
        except Exception as ex:
            scrivi_log("PodcastView._voci_episodi_podcast", ex)
        return voci

    def _azioni_episodio(self, episodio, nuovo=False, podcast=None):
        try:
            azioni = [("Riproduci", partial(self.riproduci_episodio, episodio), None)]
            stato = self.downloads.stato(episodio.audio_url)
            if stato == podcast_downloads.STATO_SCARICATO:
                azioni.append(("Elimina l'episodio scaricato", partial(self.elimina_download, episodio), None))
            elif stato in (podcast_downloads.STATO_IN_CORSO, podcast_downloads.STATO_IN_CODA):
                azioni.append(("Annulla il download", partial(self.downloads.annulla, episodio.audio_url), None))
            else:
                azioni.append(("Scarica l'episodio", partial(self.scarica_episodio, episodio), None))
            if nuovo:
                azioni.append(
                    ("Rimuovi dai nuovi episodi", partial(self.library.remove_new, episodio.feed_url, episodio.guid), None)
                )
                azioni.append(("Svuota l'elenco dei nuovi episodi", self.svuota_nuovi, None))
                if episodio.feed_url:
                    azioni.append(
                        (
                            "Apri tutti gli episodi del podcast",
                            partial(self.apri_podcast, SavedPodcast(episodio.podcast_name, "", episodio.feed_url)),
                            None,
                        )
                    )
            elif podcast is not None and not self.library.is_subscribed(podcast.feed_url):
                azioni.append(("Iscriviti al podcast", partial(self.iscriviti, podcast), None))
            azioni.append(("Informazioni sull'episodio", partial(self.informazioni_episodio, episodio), None))
            return azioni
        except Exception as ex:
            scrivi_log("PodcastView._azioni_episodio", ex)
            return []

    def riproduci_episodio(self, episodio):
        try:
            percorso = self.downloads.percorso_locale(episodio.audio_url)
            sorgente = percorso or episodio.audio_url
            if self.engine is None or self.engine.play(sorgente, episodio.title, kind="brani") is False:
                self.finestra.mostra_messaggio("Impossibile avviare la riproduzione.", "Verificare che mpv sia installato.")
                return
            origine = "dal file scaricato" if percorso else "in streaming"
            self.finestra.mostra_stato(f"In riproduzione {origine}: {episodio.title}")
            if episodio.feed_url:
                self.library.add_recent(SavedPodcast(episodio.podcast_name, "", episodio.feed_url))
                if self.library.is_new(episodio.feed_url, episodio.guid):
                    self.library.remove_new(episodio.feed_url, episodio.guid)
                    if self.finestra.titolo_corrente() == "Nuovi episodi":
                        self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            if hasattr(self.finestra, "apri_player"):
                self.finestra.apri_player()
        except Exception as ex:
            scrivi_log("PodcastView.riproduci_episodio", ex)

    def scarica_episodio(self, episodio):
        try:
            esito = self.downloads.accoda(episodio)
            if esito == podcast_downloads.ESITO_ACCODATO:
                self.finestra.mostra_stato(f"Download avviato: {episodio.title}")
            elif esito == podcast_downloads.STATO_SCARICATO:
                self.finestra.mostra_messaggio("L'episodio è già stato scaricato.")
            elif esito in (podcast_downloads.STATO_IN_CORSO, podcast_downloads.STATO_IN_CODA):
                self.finestra.mostra_messaggio("L'episodio è già in download.")
            else:
                self.finestra.mostra_messaggio("Impossibile avviare il download.", "I dettagli sono nel file di log.")
        except Exception as ex:
            scrivi_log("PodcastView.scarica_episodio", ex)

    def elimina_download(self, episodio):
        try:
            if not self.finestra.chiedi_conferma(f"Eliminare il file scaricato di {episodio.title}?"):
                return
            if not self.downloads.elimina(episodio.audio_url):
                self.finestra.mostra_messaggio("Impossibile eliminare il file.", "I dettagli sono nel file di log.")
        except Exception as ex:
            scrivi_log("PodcastView.elimina_download", ex)

    def informazioni_episodio(self, episodio):
        try:
            righe = []
            if episodio.podcast_name:
                righe.append(f"Podcast: {episodio.podcast_name}")
            if episodio.published:
                righe.append(f"Data: {episodio.data_testo()}")
            if episodio.duration:
                righe.append(f"Durata: {episodio.duration}")
            percorso = self.downloads.percorso_locale(episodio.audio_url)
            righe.append(f"Scaricato in: {percorso}" if percorso else "Non scaricato")
            if episodio.description:
                righe.append("")
                righe.append(episodio.description)
            self.finestra.mostra_messaggio(episodio.title, "\n".join(righe))
        except Exception as ex:
            scrivi_log("PodcastView.informazioni_episodio", ex)

    def apri_nuovi_episodi(self):
        try:
            self.finestra.nascondi_avviso_episodi()
            self.finestra.push_menu("Nuovi episodi", self._voci_nuovi, "Nessun nuovo episodio.")
        except Exception as ex:
            scrivi_log("PodcastView.apri_nuovi_episodi", ex)

    def _voci_nuovi(self):
        voci = []
        try:
            for episodio in self.library.list_new():
                voci.append(
                    (
                        f"{episodio.podcast_name}: {episodio.label()}",
                        partial(self.riproduci_episodio, episodio),
                        partial(self._azioni_episodio, episodio, True),
                    )
                )
        except Exception as ex:
            scrivi_log("PodcastView._voci_nuovi", ex)
        return voci

    def svuota_nuovi(self):
        try:
            if self.finestra.chiedi_conferma("Svuotare l'elenco dei nuovi episodi?"):
                self.library.clear_new()
        except Exception as ex:
            scrivi_log("PodcastView.svuota_nuovi", ex)

    def cerca(self):
        try:
            testo = self.finestra.chiedi_testo("Cerca podcast", "Nome del podcast da cercare")
            if testo:
                self.esegui_ricerca(testo)
        except Exception as ex:
            scrivi_log("PodcastView.cerca", ex)

    def esegui_ricerca(self, testo):
        try:
            self.library.add_search(testo)
            self.finestra.carica_in_background(
                f"Podcast trovati per {testo}",
                partial(self.search_client.search, testo),
                self._voci_podcast,
                "Nessun podcast trovato.",
                ERRORE_APPLE,
            )
        except Exception as ex:
            scrivi_log(f"PodcastView.esegui_ricerca ({testo})", ex)

    def apri_ricerche_recenti(self):
        try:
            self.finestra.push_menu("Ricerche recenti di podcast", self._voci_ricerche, "Nessuna ricerca recente.")
        except Exception as ex:
            scrivi_log("PodcastView.apri_ricerche_recenti", ex)

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
                            ("Rimuovi dalle ricerche recenti", partial(self.library.remove_search, testo), None),
                            ("Svuota le ricerche recenti", self.svuota_ricerche, None),
                        ],
                    )
                )
        except Exception as ex:
            scrivi_log("PodcastView._voci_ricerche", ex)
        return voci

    def svuota_ricerche(self):
        try:
            if self.finestra.chiedi_conferma("Svuotare le ricerche recenti di podcast?"):
                self.library.clear_searches()
        except Exception as ex:
            scrivi_log("PodcastView.svuota_ricerche", ex)

    def apri_iscritti(self):
        try:
            self.finestra.push_menu(
                "Podcast iscritti",
                lambda: self._voci_podcast(self.library.list_subscriptions()),
                "Nessun podcast iscritto.",
            )
        except Exception as ex:
            scrivi_log("PodcastView.apri_iscritti", ex)

    def apri_preferiti(self):
        try:
            self.finestra.push_menu(
                "Podcast preferiti",
                lambda: self._voci_podcast(self.library.list_favorites()),
                "Nessun podcast preferito.",
            )
        except Exception as ex:
            scrivi_log("PodcastView.apri_preferiti", ex)

    def apri_recenti(self):
        try:
            self.finestra.push_menu(
                "Podcast recenti",
                lambda: self._voci_podcast(self.library.list_recent(), recenti=True),
                "Nessun podcast aperto di recente.",
            )
        except Exception as ex:
            scrivi_log("PodcastView.apri_recenti", ex)

    def svuota_recenti(self):
        try:
            if self.finestra.chiedi_conferma("Svuotare l'elenco dei podcast recenti?"):
                self.library.clear_recent()
        except Exception as ex:
            scrivi_log("PodcastView.svuota_recenti", ex)

    def apri_categorie(self):
        try:
            voci = [(nome, partial(self.apri_categoria, identificativo, nome), None) for identificativo, nome in CATEGORIE]
            self.finestra.push_menu("Podcast per categoria", voci)
        except Exception as ex:
            scrivi_log("PodcastView.apri_categorie", ex)

    def apri_categoria(self, identificativo, nome):
        try:
            self.finestra.carica_in_background(
                f"Podcast della categoria {nome}",
                partial(self.search_client.category, identificativo),
                self._voci_podcast,
                "Nessun podcast trovato in questa categoria.",
                ERRORE_APPLE,
            )
        except Exception as ex:
            scrivi_log(f"PodcastView.apri_categoria ({nome})", ex)

    def apri_classifica(self):
        try:
            self.finestra.carica_in_background(
                "Classifica dei podcast",
                self.search_client.chart,
                partial(self._voci_podcast, numerati=True),
                "Classifica non disponibile.",
                ERRORE_APPLE,
            )
        except Exception as ex:
            scrivi_log("PodcastView.apri_classifica", ex)

    def apri_scaricati(self):
        try:
            self.finestra.push_menu("Episodi scaricati", self._voci_scaricati, "Nessun episodio scaricato.")
        except Exception as ex:
            scrivi_log("PodcastView.apri_scaricati", ex)

    def _voci_scaricati(self):
        voci = []
        try:
            for elemento in self.downloads.elenco():
                episodio = elemento["episodio"]
                megabyte = f"{elemento['size'] / 1048576:.1f}".replace(".", ",")
                etichetta = f"{episodio.title}, {episodio.podcast_name}, {megabyte} MB"
                voci.append(
                    (
                        etichetta,
                        partial(self.riproduci_episodio, episodio),
                        [
                            ("Riproduci", partial(self.riproduci_episodio, episodio), None),
                            ("Elimina l'episodio scaricato", partial(self.elimina_download, episodio), None),
                            ("Informazioni sull'episodio", partial(self.informazioni_episodio, episodio), None),
                        ],
                    )
                )
        except Exception as ex:
            scrivi_log("PodcastView._voci_scaricati", ex)
        return voci

    def apri_download_in_corso(self):
        try:
            self.finestra.push_menu("Download in corso", self._voci_in_corso, "Nessun download in corso.")
        except Exception as ex:
            scrivi_log("PodcastView.apri_download_in_corso", ex)

    def _voci_in_corso(self):
        voci = []
        try:
            for elemento in self.downloads.in_corso():
                episodio = elemento["episodio"]
                if elemento["in_coda"]:
                    stato = "in attesa"
                elif elemento["percentuale"] is not None:
                    stato = f"{elemento['percentuale']} per cento"
                else:
                    stato = f"{elemento['megabyte']:.1f} MB scaricati".replace(".", ",")
                azioni = [("Annulla il download", partial(self.downloads.annulla, episodio.audio_url), None)]
                voci.append((f"{episodio.title}, {stato}", self.finestra.ricarica_menu_corrente, azioni))
        except Exception as ex:
            scrivi_log("PodcastView._voci_in_corso", ex)
        return voci

    def controlla_ora(self):
        try:
            if not self.library.list_subscriptions():
                self.finestra.mostra_messaggio("Nessun podcast iscritto.", "Iscriversi a un podcast dal menu Azioni.")
                return
            if self.notifier.controllo_in_corso:
                self.finestra.mostra_messaggio("Il controllo dei nuovi episodi è già in corso.")
                return
            self.finestra.mostra_stato("Controllo dei nuovi episodi in corso.")
            self.notifier.controlla_ora(self._controllo_concluso)
        except Exception as ex:
            scrivi_log("PodcastView.controlla_ora", ex)

    def _controllo_concluso(self, nuovi, errori):
        try:
            if nuovi:
                return
            if errori:
                self.finestra.mostra_messaggio(
                    "Nessun nuovo episodio trovato.",
                    f"Non è stato possibile leggere {errori} podcast. I dettagli sono nel file di log.",
                )
            else:
                self.finestra.mostra_messaggio("Nessun nuovo episodio.")
        except Exception as ex:
            scrivi_log("PodcastView._controllo_concluso", ex)
