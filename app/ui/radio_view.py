import threading
from functools import partial

from app.core.log import scrivi_log
from app.radio import regioni

ERRORE_SERVIZIO = "Impossibile contattare il servizio delle radio. Riprovare più tardi."


class RadioView:
    def __init__(self, finestra, radio_manager, engine):
        self.finestra = finestra
        self.manager = radio_manager
        self.engine = engine

    def get_menu_items(self):
        try:
            return [
                ("Radio italiane", self.apri_italiane, None),
                ("Radio per regione", self.apri_regioni, None),
                ("Radio internazionali", self.apri_internazionali, None),
                ("Cerca radio", self.apri_ricerca, None),
                ("Ricerche recenti", self.apri_ricerche_recenti, None),
                ("Radio preferite", self.apri_preferite, None),
                ("Radio recenti", self.apri_recenti, None),
            ]
        except Exception as ex:
            scrivi_log("RadioView.get_menu_items", ex)
            return []

    def _etichetta(self, stazione, dettaglio):
        try:
            nome = stazione.get("name", "")
            testo = ""
            if dettaglio == "regione":
                testo = stazione.get("region") or ""
            elif dettaglio == "citta":
                stato = stazione.get("state") or ""
                if stato and not regioni.stessa_regione(stato, stazione.get("region") or ""):
                    testo = stato
            elif dettaglio == "paese":
                testo = stazione.get("country") or ""
            return f"{nome}, {testo}" if testo else nome
        except Exception as ex:
            scrivi_log("RadioView._etichetta", ex)
            return str(stazione.get("name", ""))

    def _voci_stazioni(self, stazioni, dettaglio="", recenti=False):
        voci = []
        try:
            for stazione in stazioni or []:
                try:
                    voci.append(
                        (
                            self._etichetta(stazione, dettaglio),
                            partial(self.riproduci, stazione),
                            partial(self._azioni_stazione, stazione, recenti),
                        )
                    )
                except Exception as ex:
                    scrivi_log("RadioView._voci_stazioni elemento", ex)
        except Exception as ex:
            scrivi_log("RadioView._voci_stazioni", ex)
        return voci

    def _azioni_stazione(self, stazione, recenti):
        try:
            azioni = [("Riproduci", partial(self.riproduci, stazione), None)]
            if self.manager.is_favorite(stazione.get("url")):
                azioni.append(("Rimuovi dalle radio preferite", partial(self.manager.remove_favorite, stazione), None))
            else:
                azioni.append(("Aggiungi alle radio preferite", partial(self.aggiungi_preferita, stazione), None))
            if recenti:
                azioni.append(("Rimuovi dalle radio recenti", partial(self.manager.remove_recent, stazione), None))
                azioni.append(("Svuota le radio recenti", self.svuota_recenti, None))
            return azioni
        except Exception as ex:
            scrivi_log("RadioView._azioni_stazione", ex)
            return []

    def riproduci(self, stazione):
        try:
            url = stazione.get("url", "")
            nome = stazione.get("name", "") or url
            if not url:
                return
            if self.engine is None or self.engine.play(url, nome, kind="stream") is False:
                self.finestra.mostra_messaggio("Impossibile avviare la riproduzione.", "Verificare che mpv sia installato.")
                return
            self.manager.add_recent({"name": nome, "url": url})
            self.finestra.mostra_stato(f"In riproduzione: {nome}")
            uuid = stazione.get("uuid", "")
            if uuid:
                threading.Thread(target=self.manager.register_click, args=(uuid,), name="RadioClick", daemon=True).start()
            if hasattr(self.finestra, "apri_player"):
                self.finestra.apri_player()
        except Exception as ex:
            scrivi_log("RadioView.riproduci", ex)

    def aggiungi_preferita(self, stazione):
        try:
            if self.manager.add_favorite({"name": stazione.get("name", ""), "url": stazione.get("url", "")}):
                self.finestra.mostra_stato("Radio aggiunta alle preferite.")
            else:
                self.finestra.mostra_messaggio("Impossibile aggiungere la radio alle preferite.")
        except Exception as ex:
            scrivi_log("RadioView.aggiungi_preferita", ex)

    def apri_italiane(self):
        try:
            self.finestra.carica_in_background(
                "Radio italiane",
                self.manager.get_italian_stations,
                partial(self._voci_stazioni, dettaglio="regione"),
                "Nessuna radio trovata.",
                ERRORE_SERVIZIO,
            )
        except Exception as ex:
            scrivi_log("RadioView.apri_italiane", ex)

    def apri_regioni(self):
        try:
            self.finestra.carica_in_background(
                "Radio per regione",
                self.manager.get_italian_regions,
                self._voci_regioni,
                "Nessuna regione trovata.",
                ERRORE_SERVIZIO,
            )
        except Exception as ex:
            scrivi_log("RadioView.apri_regioni", ex)

    def _voci_regioni(self, elenco):
        voci = []
        try:
            for regione in elenco or []:
                nome = regione.get("name", "")
                voci.append((f"{nome}, {regione.get('count', 0)} radio", partial(self.apri_regione, nome), None))
        except Exception as ex:
            scrivi_log("RadioView._voci_regioni", ex)
        return voci

    def apri_regione(self, nome):
        try:
            titolo = nome if nome == regioni.REGIONE_NON_INDICATA else f"Radio della regione {nome}"
            self.finestra.carica_in_background(
                titolo,
                partial(self.manager.get_stations_by_region, nome),
                partial(self._voci_stazioni, dettaglio="citta"),
                "Nessuna radio trovata in questa regione.",
                ERRORE_SERVIZIO,
            )
        except Exception as ex:
            scrivi_log(f"RadioView.apri_regione ({nome})", ex)

    def apri_internazionali(self):
        try:
            self.finestra.carica_in_background(
                "Radio internazionali",
                self.manager.get_international_stations,
                partial(self._voci_stazioni, dettaglio="paese"),
                "Nessuna radio trovata.",
                ERRORE_SERVIZIO,
            )
        except Exception as ex:
            scrivi_log("RadioView.apri_internazionali", ex)

    def apri_ricerca(self):
        try:
            testo = self.finestra.chiedi_testo("Cerca radio", "Nome della radio da cercare")
            if testo:
                self.esegui_ricerca(testo)
        except Exception as ex:
            scrivi_log("RadioView.apri_ricerca", ex)

    def esegui_ricerca(self, testo):
        try:
            self.finestra.carica_in_background(
                f"Radio trovate per {testo}",
                partial(self.manager.search_stations, testo),
                partial(self._voci_stazioni, dettaglio="paese"),
                "Nessuna radio trovata.",
                ERRORE_SERVIZIO,
            )
        except Exception as ex:
            scrivi_log(f"RadioView.esegui_ricerca ({testo})", ex)

    def apri_ricerche_recenti(self):
        try:
            self.finestra.push_menu("Ricerche recenti di radio", self._voci_ricerche, "Nessuna ricerca recente.")
        except Exception as ex:
            scrivi_log("RadioView.apri_ricerche_recenti", ex)

    def _voci_ricerche(self):
        voci = []
        try:
            for testo in self.manager.get_search_history():
                voci.append(
                    (
                        testo,
                        partial(self.esegui_ricerca, testo),
                        [
                            ("Cerca di nuovo", partial(self.esegui_ricerca, testo), None),
                            ("Rimuovi dalle ricerche recenti", partial(self.manager.remove_search_history, testo), None),
                            ("Svuota le ricerche recenti", self.svuota_ricerche, None),
                        ],
                    )
                )
        except Exception as ex:
            scrivi_log("RadioView._voci_ricerche", ex)
        return voci

    def svuota_ricerche(self):
        try:
            if self.finestra.chiedi_conferma("Svuotare le ricerche recenti di radio?"):
                self.manager.clear_search_history()
        except Exception as ex:
            scrivi_log("RadioView.svuota_ricerche", ex)

    def apri_preferite(self):
        try:
            self.finestra.push_menu(
                "Radio preferite",
                lambda: self._voci_stazioni(self.manager.get_favorites()),
                "Nessuna radio preferita.",
            )
        except Exception as ex:
            scrivi_log("RadioView.apri_preferite", ex)

    def apri_recenti(self):
        try:
            self.finestra.push_menu(
                "Radio recenti",
                lambda: self._voci_stazioni(self.manager.get_recent(), recenti=True),
                "Nessuna radio ascoltata di recente.",
            )
        except Exception as ex:
            scrivi_log("RadioView.apri_recenti", ex)

    def svuota_recenti(self):
        try:
            if self.finestra.chiedi_conferma("Svuotare l'elenco delle radio recenti?"):
                self.manager.clear_recent()
        except Exception as ex:
            scrivi_log("RadioView.svuota_recenti", ex)
