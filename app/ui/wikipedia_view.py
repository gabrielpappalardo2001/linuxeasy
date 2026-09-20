from collections import OrderedDict
from functools import partial

from gi.repository import GLib

from app.core.log import scrivi_log
from app.ui.pagina import PaginaTesto
from app.wikipedia.wikipedia_client import PaginaNonTrovata, indirizzo_pagina

TITOLO_MENU = "Menu Wikipedia"
TITOLO_RICERCHE = "Ricerche recenti di Wikipedia"
TITOLO_PREFERITE = "Pagine preferite di Wikipedia"
TITOLO_RECENTI = "Pagine recenti di Wikipedia"
ERRORE_SERVIZIO = "Impossibile contattare Wikipedia. Riprovare più tardi."
ERRORE_LOG = "I dettagli sono nel file di log."
PAGINE_IN_MEMORIA = 20


def conta(numero, singolare, plurale):
    try:
        return f"1 {singolare}" if numero == 1 else f"{numero} {plurale}"
    except Exception as ex:
        scrivi_log("wikipedia_view.conta", ex)
        return str(numero)


class WikipediaView:
    def __init__(self, finestra, client, libreria, selettore):
        self.finestra = finestra
        self.client = client
        self.libreria = libreria
        self.selettore = selettore
        self._pagine = OrderedDict()

    def get_menu_items(self):
        try:
            return [
                ("Cerca su Wikipedia", self.cerca, None),
                ("Ricerche recenti", self.apri_ricerche, None),
                ("Pagine preferite", self.apri_preferite, None),
                ("Pagine recenti", self.apri_recenti, None),
            ]
        except Exception as ex:
            scrivi_log("WikipediaView.get_menu_items", ex)
            return [("Cerca su Wikipedia", self.cerca, None)]

    def _etichetta(self, titolo, descrizione):
        try:
            return f"{titolo}, {descrizione}" if descrizione else titolo
        except Exception as ex:
            scrivi_log("WikipediaView._etichetta", ex)
            return str(titolo)

    def _memorizza(self, pagina):
        try:
            chiave = (pagina.lingua, pagina.title)
            self._pagine[chiave] = pagina
            self._pagine.move_to_end(chiave)
            while len(self._pagine) > PAGINE_IN_MEMORIA:
                self._pagine.popitem(last=False)
        except Exception as ex:
            scrivi_log("WikipediaView._memorizza", ex)

    def _in_memoria(self, titolo):
        try:
            return self._pagine.get((self.client.lingua, titolo))
        except Exception as ex:
            scrivi_log(f"WikipediaView._in_memoria ({titolo})", ex)
            return None

    def cerca(self):
        try:
            testo = self.finestra.chiedi_testo("Cerca su Wikipedia", "Testo da cercare su Wikipedia")
            if testo:
                self.esegui_ricerca(testo)
        except Exception as ex:
            scrivi_log("WikipediaView.cerca", ex)

    def esegui_ricerca(self, testo):
        try:
            self.libreria.aggiungi_ricerca(testo)
            self.finestra.carica_in_background(
                f"Risultati di Wikipedia per {testo}",
                partial(self.client.cerca, testo),
                self._voci_risultati,
                "Nessuna pagina trovata.",
                ERRORE_SERVIZIO,
            )
        except Exception as ex:
            scrivi_log(f"WikipediaView.esegui_ricerca ({testo})", ex)

    def _voci_risultati(self, esito):
        voci = []
        try:
            for risultato in esito.risultati:
                voci.append(
                    (
                        self._etichetta(risultato.title, risultato.description),
                        partial(self.apri_pagina, risultato.title, risultato.description),
                        partial(self._azioni_voce, risultato.title, risultato.description, None),
                    )
                )
            if voci and esito.corretto:
                GLib.idle_add(
                    self._annuncia,
                    f"Nessun risultato per {esito.testo}. Risultati per {esito.corretto}.",
                )
        except Exception as ex:
            scrivi_log("WikipediaView._voci_risultati", ex)
        return voci

    def _annuncia(self, testo):
        try:
            self.finestra.mostra_stato(testo)
        except Exception as ex:
            scrivi_log("WikipediaView._annuncia", ex)
        return False

    def _azioni_voce(self, titolo, descrizione, elenco):
        try:
            lingua = self.client.lingua
            azioni = [
                ("Apri la pagina", partial(self.apri_pagina, titolo, descrizione), None),
                ("Leggi la pagina intera", partial(self._apri_e_esegui, titolo, descrizione, self.leggi_intera), None),
                ("Leggi per parti", partial(self._apri_e_esegui, titolo, descrizione, self.apri_indice), None),
            ]
            if self.libreria.preferita(titolo, lingua):
                azioni.append(("Rimuovi dalle pagine preferite", partial(self.rimuovi_preferita, titolo), None))
            else:
                azioni.append(("Aggiungi alle pagine preferite", partial(self.aggiungi_preferita, titolo, descrizione), None))
            if elenco == TITOLO_RECENTI:
                azioni.append(("Rimuovi dalle pagine recenti", partial(self.rimuovi_recente, titolo), None))
                azioni.append(("Svuota le pagine recenti", self.svuota_recenti, None))
            azioni.append(("Apri la pagina nel browser", partial(self._apri_browser, titolo), None))
            return azioni
        except Exception as ex:
            scrivi_log(f"WikipediaView._azioni_voce ({titolo})", ex)
            return []

    def _apri_browser(self, titolo, url=""):
        try:
            indirizzo = url or indirizzo_pagina(titolo, self.client.lingua)
            if not self.finestra.apri_nel_browser(indirizzo):
                self.finestra.mostra_messaggio("Impossibile aprire il browser.", indirizzo)
        except Exception as ex:
            scrivi_log(f"WikipediaView._apri_browser ({titolo})", ex)

    def _carica(self, titolo):
        try:
            pagina = self._in_memoria(titolo)
            if pagina is None:
                pagina = self.client.pagina(titolo)
            return pagina
        except Exception as ex:
            scrivi_log(f"WikipediaView._carica ({titolo})", ex)
            raise

    def _errore_pagina(self, errore):
        try:
            if isinstance(errore, PaginaNonTrovata):
                return "La pagina non esiste su Wikipedia."
            return ERRORE_SERVIZIO
        except Exception as ex:
            scrivi_log("WikipediaView._errore_pagina", ex)
            return ERRORE_SERVIZIO

    def apri_pagina(self, titolo, descrizione=""):
        try:
            self.finestra.carica_in_background(
                titolo,
                partial(self._carica, titolo),
                partial(self._pagina_caricata, descrizione),
                "La pagina è vuota.",
                self._errore_pagina,
            )
        except Exception as ex:
            scrivi_log(f"WikipediaView.apri_pagina ({titolo})", ex)

    def _apri_e_esegui(self, titolo, descrizione, azione):
        try:
            pagina = self._in_memoria(titolo)
            if pagina is not None:
                self._registra(pagina, descrizione)
                azione(pagina)
                return
            self.finestra.carica_in_background(
                titolo,
                partial(self._carica, titolo),
                partial(self._pagina_poi_azione, descrizione, azione),
                "La pagina è vuota.",
                self._errore_pagina,
            )
        except Exception as ex:
            scrivi_log(f"WikipediaView._apri_e_esegui ({titolo})", ex)

    def _pagina_poi_azione(self, descrizione, azione, pagina):
        try:
            self._registra(pagina, descrizione)
            GLib.idle_add(self._azione_differita, azione, pagina)
            return partial(self._voci_pagina, pagina)
        except Exception as ex:
            scrivi_log("WikipediaView._pagina_poi_azione", ex)
            return []

    def _azione_differita(self, azione, pagina):
        try:
            azione(pagina)
        except Exception as ex:
            scrivi_log("WikipediaView._azione_differita", ex)
        return False

    def _registra(self, pagina, descrizione=""):
        try:
            if descrizione and not pagina.description:
                pagina.description = descrizione
            self._memorizza(pagina)
            self.libreria.aggiungi_recente(pagina.title, pagina.lingua, pagina.description)
        except Exception as ex:
            scrivi_log("WikipediaView._registra", ex)

    def _pagina_caricata(self, descrizione, pagina):
        try:
            self._registra(pagina, descrizione)
            return partial(self._voci_pagina, pagina)
        except Exception as ex:
            scrivi_log("WikipediaView._pagina_caricata", ex)
            return []

    def _azioni_pagina(self, pagina):
        try:
            azioni = []
            if self.libreria.preferita(pagina.title, pagina.lingua):
                azioni.append(("Rimuovi dalle pagine preferite", partial(self.rimuovi_preferita, pagina.title), None))
            else:
                azioni.append(
                    ("Aggiungi alle pagine preferite", partial(self.aggiungi_preferita, pagina.title, pagina.description), None)
                )
            azioni.append(("Salva la pagina intera in un file di testo", partial(self.salva, pagina, None), None))
            azioni.append(("Apri la pagina nel browser", partial(self._apri_browser, pagina.title, pagina.url), None))
            return azioni
        except Exception as ex:
            scrivi_log("WikipediaView._azioni_pagina", ex)
            return []

    def _voci_pagina(self, pagina):
        try:
            azioni = partial(self._azioni_pagina, pagina)
            voci = [
                (
                    f"Leggi la pagina intera, {conta(pagina.numero_parole(), 'parola', 'parole')}",
                    partial(self.leggi_intera, pagina),
                    azioni,
                )
            ]
            if pagina.sezioni:
                voci.append(
                    (f"Leggi per parti, {conta(len(pagina.sezioni), 'parte', 'parti')}", partial(self.apri_indice, pagina), azioni)
                )
            return voci
        except Exception as ex:
            scrivi_log("WikipediaView._voci_pagina", ex)
            return []

    def leggi_intera(self, pagina):
        try:
            self.finestra.mostra_pagina(
                PaginaTesto(pagina.title, pagina.testo_completo(), partial(self._azioni_testo, pagina, None))
            )
        except Exception as ex:
            scrivi_log("WikipediaView.leggi_intera", ex)

    def _titolo_indice(self, pagina):
        return f"Parti di {pagina.title}"

    def apri_indice(self, pagina):
        try:
            self.finestra.push_menu(self._titolo_indice(pagina), partial(self._voci_indice, pagina), "La pagina non ha parti.")
        except Exception as ex:
            scrivi_log("WikipediaView.apri_indice", ex)

    def _voci_indice(self, pagina):
        voci = []
        try:
            for indice in range(len(pagina.sezioni)):
                voci.append(
                    (
                        pagina.etichetta_sezione(indice),
                        partial(self.leggi_sezione, pagina, indice),
                        [
                            ("Leggi questa parte", partial(self.leggi_sezione, pagina, indice), None),
                            ("Salva questa parte in un file di testo", partial(self.salva, pagina, indice), None),
                            ("Salva la pagina intera in un file di testo", partial(self.salva, pagina, None), None),
                        ],
                    )
                )
        except Exception as ex:
            scrivi_log("WikipediaView._voci_indice", ex)
        return voci

    def _titolo_sezione(self, pagina, indice):
        return f"{pagina.title}, {pagina.sezioni[indice].titolo}"

    def leggi_sezione(self, pagina, indice):
        try:
            if not 0 <= indice < len(pagina.sezioni):
                return
            self.finestra.menu_positions[self._titolo_indice(pagina)] = indice
            self.finestra.mostra_pagina(
                PaginaTesto(
                    self._titolo_sezione(pagina, indice),
                    pagina.testo_sezione(indice),
                    partial(self._azioni_testo, pagina, indice),
                )
            )
        except Exception as ex:
            scrivi_log(f"WikipediaView.leggi_sezione ({indice})", ex)

    def _cambia_sezione(self, pagina, indice):
        try:
            if self.finestra.in_pagina():
                self.finestra.go_back()
            if self.finestra.titolo_corrente() != self._titolo_indice(pagina):
                self.apri_indice(pagina)
            self.leggi_sezione(pagina, indice)
        except Exception as ex:
            scrivi_log(f"WikipediaView._cambia_sezione ({indice})", ex)

    def _passa_a_pagina_intera(self, pagina):
        try:
            if self.finestra.in_pagina():
                self.finestra.go_back()
            self.leggi_intera(pagina)
        except Exception as ex:
            scrivi_log("WikipediaView._passa_a_pagina_intera", ex)

    def _passa_a_indice(self, pagina, indice):
        try:
            if self.finestra.in_pagina():
                self.finestra.go_back()
            if indice is not None:
                self.finestra.menu_positions[self._titolo_indice(pagina)] = indice
            if self.finestra.titolo_corrente() != self._titolo_indice(pagina):
                self.apri_indice(pagina)
        except Exception as ex:
            scrivi_log("WikipediaView._passa_a_indice", ex)

    def _azioni_testo(self, pagina, indice):
        try:
            if indice is None:
                azioni = [("Salva la pagina intera in un file di testo", partial(self.salva, pagina, None), None)]
                if pagina.sezioni:
                    azioni.append(("Leggi per parti", partial(self._passa_a_indice, pagina, None), None))
            else:
                azioni = [
                    ("Salva questa parte in un file di testo", partial(self.salva, pagina, indice), None),
                    ("Salva la pagina intera in un file di testo", partial(self.salva, pagina, None), None),
                ]
                fine = pagina.fine_sezione(indice)
                if fine < len(pagina.sezioni):
                    azioni.append(
                        (
                            f"Parte successiva: {pagina.etichetta_sezione(fine)}",
                            partial(self._cambia_sezione, pagina, fine),
                            None,
                        )
                    )
                precedente = indice - 1
                if precedente >= 0:
                    azioni.append(
                        (
                            f"Parte precedente: {pagina.etichetta_sezione(precedente)}",
                            partial(self._cambia_sezione, pagina, precedente),
                            None,
                        )
                    )
                azioni.append(("Torna all'elenco delle parti", partial(self._passa_a_indice, pagina, indice), None))
                azioni.append(("Leggi la pagina intera", partial(self._passa_a_pagina_intera, pagina), None))
            if self.libreria.preferita(pagina.title, pagina.lingua):
                azioni.append(("Rimuovi dalle pagine preferite", partial(self.rimuovi_preferita, pagina.title), None))
            else:
                azioni.append(
                    ("Aggiungi alle pagine preferite", partial(self.aggiungi_preferita, pagina.title, pagina.description), None)
                )
            azioni.append(("Apri la pagina nel browser", partial(self._apri_browser, pagina.title, pagina.url), None))
            return azioni
        except Exception as ex:
            scrivi_log(f"WikipediaView._azioni_testo ({indice})", ex)
            return []

    def salva(self, pagina, indice):
        try:
            if indice is None:
                corpo = pagina.testo_completo()
                nome = pagina.title
            else:
                corpo = pagina.testo_sezione(indice)
                nome = f"{pagina.title} - {pagina.sezioni[indice].titolo}"
                corpo = f"{pagina.title}\n\n{corpo}"
            testo = f"{corpo}\n\nFonte: {pagina.url}\n"
            if self.selettore is None:
                self.finestra.mostra_messaggio("Il salvataggio dei file non è disponibile.", ERRORE_LOG)
                return
            self.selettore.salva_testo(testo, nome)
        except Exception as ex:
            scrivi_log(f"WikipediaView.salva ({indice})", ex)

    def aggiungi_preferita(self, titolo, descrizione=""):
        try:
            if self.libreria.aggiungi_preferita(titolo, self.client.lingua, descrizione):
                self.finestra.mostra_stato("Pagina aggiunta alle preferite.")
            else:
                self.finestra.mostra_messaggio("Impossibile aggiungere la pagina alle preferite.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"WikipediaView.aggiungi_preferita ({titolo})", ex)

    def rimuovi_preferita(self, titolo):
        try:
            if self.libreria.rimuovi_preferita(titolo, self.client.lingua):
                self.finestra.mostra_stato("Pagina rimossa dalle preferite.")
            else:
                self.finestra.mostra_messaggio("Impossibile rimuovere la pagina dalle preferite.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"WikipediaView.rimuovi_preferita ({titolo})", ex)

    def _voci_salvate(self, pagine, elenco):
        voci = []
        try:
            for pagina in pagine:
                voci.append(
                    (
                        self._etichetta(pagina.title, pagina.description),
                        partial(self.apri_pagina, pagina.title, pagina.description),
                        partial(self._azioni_voce, pagina.title, pagina.description, elenco),
                    )
                )
        except Exception as ex:
            scrivi_log("WikipediaView._voci_salvate", ex)
        return voci

    def apri_preferite(self):
        try:
            self.finestra.push_menu(
                TITOLO_PREFERITE,
                lambda: self._voci_salvate(self.libreria.elenco_preferite(), TITOLO_PREFERITE),
                "Nessuna pagina preferita.",
            )
        except Exception as ex:
            scrivi_log("WikipediaView.apri_preferite", ex)

    def apri_recenti(self):
        try:
            self.finestra.push_menu(
                TITOLO_RECENTI,
                lambda: self._voci_salvate(self.libreria.elenco_recenti(), TITOLO_RECENTI),
                "Nessuna pagina letta di recente.",
            )
        except Exception as ex:
            scrivi_log("WikipediaView.apri_recenti", ex)

    def rimuovi_recente(self, titolo):
        try:
            if self.libreria.rimuovi_recente(titolo, self.client.lingua):
                self.finestra.mostra_stato("Pagina rimossa dalle recenti.")
            else:
                self.finestra.mostra_messaggio("Impossibile rimuovere la pagina dalle recenti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"WikipediaView.rimuovi_recente ({titolo})", ex)

    def svuota_recenti(self):
        try:
            if not self.finestra.chiedi_conferma("Svuotare l'elenco delle pagine recenti di Wikipedia?"):
                return
            if self.libreria.svuota_recenti():
                self.finestra.mostra_stato("Elenco delle pagine recenti svuotato.")
            else:
                self.finestra.mostra_messaggio("Impossibile svuotare l'elenco delle pagine recenti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("WikipediaView.svuota_recenti", ex)

    def apri_ricerche(self):
        try:
            self.finestra.push_menu(TITOLO_RICERCHE, self._voci_ricerche, "Nessuna ricerca recente.")
        except Exception as ex:
            scrivi_log("WikipediaView.apri_ricerche", ex)

    def _voci_ricerche(self):
        voci = []
        try:
            for testo in self.libreria.elenco_ricerche():
                voci.append(
                    (
                        testo,
                        partial(self.esegui_ricerca, testo),
                        [
                            ("Cerca di nuovo", partial(self.esegui_ricerca, testo), None),
                            ("Rimuovi dalle ricerche recenti", partial(self.rimuovi_ricerca, testo), None),
                            ("Svuota le ricerche recenti", self.svuota_ricerche, None),
                        ],
                    )
                )
        except Exception as ex:
            scrivi_log("WikipediaView._voci_ricerche", ex)
        return voci

    def rimuovi_ricerca(self, testo):
        try:
            if self.libreria.rimuovi_ricerca(testo):
                self.finestra.mostra_stato("Ricerca rimossa dalle recenti.")
            else:
                self.finestra.mostra_messaggio("Impossibile rimuovere la ricerca.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"WikipediaView.rimuovi_ricerca ({testo})", ex)

    def svuota_ricerche(self):
        try:
            if not self.finestra.chiedi_conferma("Svuotare le ricerche recenti di Wikipedia?"):
                return
            if self.libreria.svuota_ricerche():
                self.finestra.mostra_stato("Ricerche recenti svuotate.")
            else:
                self.finestra.mostra_messaggio("Impossibile svuotare le ricerche recenti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("WikipediaView.svuota_ricerche", ex)
