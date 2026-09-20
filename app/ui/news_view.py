import threading
from functools import partial

from gi.repository import GLib

from app.core.log import scrivi_log
from app.news import source_manager as gestore
from app.news.article_text import METODO_RIASSUNTO
from app.news.headless_browser import BrowserNonDisponibile
from app.news.news_parser import FeedNonTrovato, SitoNonRaggiungibile
from app.ui.pagina import PaginaTesto

ETA_MASSIMA_SECONDI = 600
TITOLO_MENU = "Menu Notizie"
TITOLO_SEGNALATE = "Nuove notizie segnalate"
ERRORE_LOG = "I dettagli sono nel file di log."


class FonteGiaPresente(Exception):
    pass


def conta(numero, singolare, plurale):
    try:
        if numero == 0:
            return f"nessun {singolare}" if singolare.endswith("o") else f"nessuna {singolare}"
        return f"1 {singolare}" if numero == 1 else f"{numero} {plurale}"
    except Exception as ex:
        scrivi_log("news_view.conta", ex)
        return str(numero)


class NewsView:
    def __init__(self, finestra, manager, parser, extractor, updater):
        self.finestra = finestra
        self.manager = manager
        self.parser = parser
        self.extractor = extractor
        self.updater = updater

    def _operazione(self, testo_ok, testo_errore, funzione, *argomenti):
        try:
            if funzione(*argomenti):
                self.finestra.mostra_stato(testo_ok)
            else:
                self.finestra.mostra_messaggio(testo_errore, ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"NewsView._operazione ({testo_ok})", ex)
            self.finestra.mostra_messaggio(testo_errore, ERRORE_LOG)

    def _segna_letto(self, article_id, letto):
        return partial(
            self._operazione,
            "Articolo segnato come letto." if letto else "Articolo segnato come non letto.",
            "Impossibile aggiornare lo stato dell'articolo.",
            self.manager.mark_read,
            article_id,
            letto,
        )

    def _segna_tutte(self, *argomenti):
        return partial(
            self._operazione,
            "Notizie segnate come lette.",
            "Impossibile segnare le notizie come lette.",
            self.manager.mark_all_read,
            *argomenti,
        )

    def _rimuovi_salvato(self, chiave):
        return partial(
            self._operazione,
            "Articolo rimosso dagli articoli salvati.",
            "Impossibile rimuovere l'articolo dagli articoli salvati.",
            self.manager.remove_saved,
            chiave,
        )

    def get_menu_items(self):
        try:
            non_letti = self.manager.count_unread()
            segnalate = self.manager.count_notified_unread()
            fonti = len(self.manager.get_sources())
            salvati = self.manager.count_saved()
            return [
                (f"Ultime notizie, {non_letti} non lette" if non_letti else "Ultime notizie", self.apri_ultime, None),
                ("Notizie per categoria", self.apri_categorie_lettura, None),
                (f"{TITOLO_SEGNALATE}, {segnalate}" if segnalate else f"{TITOLO_SEGNALATE}, nessuna", self.apri_segnalate, None),
                (f"Fonti, {fonti}", self.apri_fonti, None),
                ("Cerca nelle notizie", self.cerca, None),
                (f"Articoli salvati, {salvati}", self.apri_salvati, None),
                ("Nuova fonte", self.aggiungi_fonte, None),
                ("Gestione categorie", self.apri_gestione_categorie, None),
                ("Aggiorna tutte le notizie", self.aggiorna_tutte, None),
            ]
        except Exception as ex:
            scrivi_log("NewsView.get_menu_items", ex)
            return [("Nuova fonte", self.aggiungi_fonte, None)]

    def _voci_articoli(self, articoli, mostra_fonte=True, segna_tutte=None):
        voci = []
        try:
            for articolo in articoli or []:
                voci.append(
                    (
                        articolo.label(mostra_fonte),
                        partial(self.leggi_articolo, articolo.id),
                        partial(self._azioni_articolo, articolo.id, segna_tutte),
                    )
                )
        except Exception as ex:
            scrivi_log("NewsView._voci_articoli", ex)
        return voci

    def _azioni_articolo(self, article_id, segna_tutte=None):
        try:
            articolo = self.manager.get_article(article_id)
            if articolo is None:
                return []
            azioni = [("Leggi", partial(self.leggi_articolo, article_id), None)]
            if articolo.is_read:
                azioni.append(("Segna come non letto", self._segna_letto(article_id, False), None))
            else:
                azioni.append(("Segna come letto", self._segna_letto(article_id, True), None))
            if self.manager.is_saved(articolo):
                azioni.append(("Rimuovi dagli articoli salvati", self._rimuovi_salvato(articolo.chiave()), None))
            else:
                azioni.append(("Salva l'articolo", partial(self.salva_articolo, article_id, None), None))
            if articolo.link:
                azioni.append(("Apri nel browser", partial(self.finestra.apri_nel_browser, articolo.link), None))
                azioni.append(("Copia il link", partial(self.copia_link, articolo.link), None))
            if segna_tutte is not None:
                azioni.append(("Segna tutte come lette", segna_tutte, None))
            return azioni
        except Exception as ex:
            scrivi_log(f"NewsView._azioni_articolo ({article_id})", ex)
            return []

    def copia_link(self, link):
        try:
            if self.finestra.copia_negli_appunti(link):
                self.finestra.mostra_stato("Link copiato.")
            else:
                self.finestra.mostra_messaggio("Impossibile copiare il link.")
        except Exception as ex:
            scrivi_log("NewsView.copia_link", ex)

    def salva_articolo(self, article_id, testo=None):
        try:
            articolo = self.manager.get_article(article_id)
            if articolo is None:
                self.finestra.mostra_messaggio("L'articolo non è più disponibile.")
                return
            if not self.manager.save_article(articolo, testo or articolo.full_text):
                self.finestra.mostra_messaggio("Impossibile salvare l'articolo.", ERRORE_LOG)
                return
            if not testo and not articolo.full_text:
                self.finestra.mostra_stato("Articolo salvato. Scaricamento del testo completo in corso.")
                threading.Thread(target=self._completa_salvataggio, args=(articolo,), name="SalvaArticolo", daemon=True).start()
            else:
                self.finestra.mostra_stato("Articolo salvato.")
        except Exception as ex:
            scrivi_log(f"NewsView.salva_articolo ({article_id})", ex)

    def _completa_salvataggio(self, articolo):
        riuscito = False
        try:
            esito = self.extractor.estrai(articolo)
            if esito and esito.get("testo"):
                riuscito = bool(self.manager.save_article(articolo, esito["testo"]))
        except Exception as ex:
            scrivi_log(f"NewsView._completa_salvataggio ({articolo.link})", ex)
        try:
            GLib.idle_add(self._salvataggio_completato, articolo.title, riuscito)
        except Exception as ex:
            scrivi_log("NewsView._completa_salvataggio consegna", ex)

    def _salvataggio_completato(self, titolo, riuscito):
        try:
            if riuscito:
                self.finestra.mostra_stato(f"Testo completo salvato: {titolo}.")
            else:
                self.finestra.mostra_messaggio(
                    f"Impossibile scaricare il testo completo di {titolo}.",
                    "L'articolo è stato salvato senza il testo completo.",
                )
        except Exception as ex:
            scrivi_log("NewsView._salvataggio_completato", ex)
        return False

    def _pagina_articolo(self, articolo, testo, metodo, azioni):
        try:
            righe = [articolo.title]
            informazioni = ", ".join(parte for parte in (articolo.source_name, articolo.data_testo()) if parte)
            if informazioni:
                righe.append(informazioni)
            if metodo == METODO_RIASSUNTO:
                righe.append("Testo completo non disponibile, segue il riassunto.")
            righe.append(testo)
            if articolo.link:
                righe.append(f"Indirizzo: {articolo.link}")
            return PaginaTesto(articolo.title, "\n\n".join(riga for riga in righe if riga), azioni)
        except Exception as ex:
            scrivi_log("NewsView._pagina_articolo", ex)
            return PaginaTesto(articolo.title, testo, azioni)

    def _messaggio_errore_testo(self, errore):
        try:
            if isinstance(errore, BrowserNonDisponibile):
                return "Nessun browser invisibile installato. Installare Chromium con il comando: sudo dnf install chromium"
            return "Impossibile recuperare il testo dell'articolo."
        except Exception as ex:
            scrivi_log("NewsView._messaggio_errore_testo", ex)
            return "Impossibile recuperare il testo dell'articolo."

    def leggi_articolo(self, article_id):
        try:
            articolo = self.manager.get_article(article_id)
            if articolo is None:
                self.finestra.mostra_messaggio("L'articolo non è più disponibile.")
                return
            self.manager.mark_read(article_id, True)
            if articolo.full_text:
                self.finestra.mostra_pagina(self._crea_pagina_articolo(articolo, {"testo": articolo.full_text, "metodo": ""}))
                return
            self.finestra.carica_in_background(
                articolo.title,
                partial(self.extractor.estrai, articolo),
                partial(self._crea_pagina_articolo, articolo),
                "Testo non disponibile.",
                self._messaggio_errore_testo,
            )
        except Exception as ex:
            scrivi_log(f"NewsView.leggi_articolo ({article_id})", ex)

    def _crea_pagina_articolo(self, articolo, esito):
        try:
            testo = esito.get("testo", "")
            metodo = esito.get("metodo", "")
            return self._pagina_articolo(articolo, testo, metodo, partial(self._azioni_pagina_articolo, articolo.id, testo))
        except Exception as ex:
            scrivi_log("NewsView._crea_pagina_articolo", ex)
            return None

    def _azioni_pagina_articolo(self, article_id, testo):
        try:
            articolo = self.manager.get_article(article_id)
            if articolo is None:
                return []
            azioni = []
            if self.manager.is_saved(articolo):
                azioni.append(("Rimuovi dagli articoli salvati", self._rimuovi_salvato(articolo.chiave()), None))
            else:
                azioni.append(("Salva l'articolo", partial(self.salva_articolo, article_id, testo), None))
            if articolo.link:
                azioni.append(("Apri nel browser", partial(self.finestra.apri_nel_browser, articolo.link), None))
                azioni.append(("Copia il link", partial(self.copia_link, articolo.link), None))
                azioni.append(("Recupera il testo con il browser invisibile", partial(self.recupera_con_browser, article_id), None))
            azioni.append(("Segna come non letto", self._segna_letto(article_id, False), None))
            return azioni
        except Exception as ex:
            scrivi_log(f"NewsView._azioni_pagina_articolo ({article_id})", ex)
            return []

    def recupera_con_browser(self, article_id):
        try:
            articolo = self.manager.get_article(article_id)
            if articolo is None:
                self.finestra.mostra_messaggio("L'articolo non è più disponibile.")
                return
            if not self.extractor.browser_disponibile():
                self.finestra.mostra_messaggio(self._messaggio_errore_testo(BrowserNonDisponibile()))
                return
            self.finestra.go_back()
            self.finestra.carica_in_background(
                articolo.title,
                partial(self.extractor.estrai, articolo, True),
                partial(self._crea_pagina_articolo, articolo),
                "Testo non disponibile.",
                self._messaggio_errore_testo,
            )
        except Exception as ex:
            scrivi_log(f"NewsView.recupera_con_browser ({article_id})", ex)

    def _elenco_con_avviso(self, sorgente, avviso):
        def voci():
            try:
                risultato = list(sorgente())
                if avviso is not None:
                    risultato.insert(0, avviso)
                return risultato
            except Exception as ex:
                scrivi_log("NewsView._elenco_con_avviso", ex)
                return []
        return voci

    def _avviso_errori(self, nomi):
        try:
            if not nomi:
                return None
            etichetta = f"Fonti che non hanno risposto: {len(nomi)}"
            return (etichetta, partial(self.finestra.mostra_messaggio, etichetta, "\n".join(nomi)), None)
        except Exception as ex:
            scrivi_log("NewsView._avviso_errori", ex)
            return None

    def _apri_articoli(self, titolo, sorgente, fonti, aggiorna, messaggio_vuoto):
        try:
            if not fonti:
                self.finestra.mostra_messaggio("Nessuna fonte configurata.", "Aggiungere una fonte dal menu Notizie.")
                return
            if any(self.manager.needs_update(fonte, ETA_MASSIMA_SECONDI) for fonte in fonti):
                self.finestra.carica_in_background(
                    titolo,
                    aggiorna,
                    lambda resoconto: self._elenco_con_avviso(sorgente, self._avviso_errori(resoconto.get("fonti_in_errore"))),
                    messaggio_vuoto,
                    "Impossibile aggiornare le notizie.",
                )
            else:
                self.finestra.push_menu(titolo, sorgente, messaggio_vuoto)
        except Exception as ex:
            scrivi_log(f"NewsView._apri_articoli ({titolo})", ex)

    def apri_ultime(self):
        try:
            self._apri_articoli(
                "Ultime notizie",
                lambda: self._voci_articoli(self.manager.get_articles(), True, self._segna_tutte()),
                self.manager.get_sources(),
                partial(self.manager.update_all, ETA_MASSIMA_SECONDI),
                "Nessuna notizia disponibile.",
            )
        except Exception as ex:
            scrivi_log("NewsView.apri_ultime", ex)

    def apri_articoli_categoria(self, category_id):
        try:
            categoria = self.manager.get_category(category_id)
            if categoria is None:
                return
            self._apri_articoli(
                f"Notizie della categoria {categoria['name']}",
                lambda: self._voci_articoli(
                    self.manager.get_articles(category_id=category_id),
                    True,
                    self._segna_tutte(None, category_id),
                ),
                self.manager.get_sources(category_id),
                partial(self.manager.update_all, ETA_MASSIMA_SECONDI, category_id),
                "Nessuna notizia in questa categoria.",
            )
        except Exception as ex:
            scrivi_log(f"NewsView.apri_articoli_categoria ({category_id})", ex)

    def apri_fonte(self, url):
        try:
            fonte = self.manager.get_source(url)
            if fonte is None:
                self.finestra.mostra_messaggio("La fonte non è più disponibile.")
                return
            sorgente = lambda: self._voci_articoli(
                self.manager.get_articles(source_url=url),
                False,
                self._segna_tutte(url),
            )
            if self.manager.needs_update(fonte, ETA_MASSIMA_SECONDI):
                self.finestra.carica_in_background(
                    fonte["name"],
                    partial(self.manager.update_source, fonte),
                    lambda esito: self._elenco_con_avviso(
                        sorgente,
                        ("Aggiornamento non riuscito, notizie già scaricate", None, None) if esito.get("errore") else None,
                    ),
                    "Nessuna notizia per questa fonte.",
                    "Impossibile aggiornare la fonte.",
                )
            else:
                self.finestra.push_menu(fonte["name"], sorgente, "Nessuna notizia per questa fonte.")
        except Exception as ex:
            scrivi_log(f"NewsView.apri_fonte ({url})", ex)

    def apri_segnalate(self):
        try:
            self.finestra.nascondi_avviso_notizie()
            if self.finestra.titolo_corrente() == TITOLO_SEGNALATE:
                self.finestra.ricarica_menu_corrente()
                return
            self.finestra.push_menu(
                TITOLO_SEGNALATE,
                lambda: self._voci_articoli(
                    self.manager.get_notified_unread(),
                    True,
                    self._segna_tutte(None, None, True),
                ),
                "Nessuna nuova notizia segnalata.",
            )
        except Exception as ex:
            scrivi_log("NewsView.apri_segnalate", ex)

    def _etichetta_fonte(self, fonte, mostra_categoria):
        try:
            parti = [fonte["name"]]
            if mostra_categoria and fonte.get("category"):
                parti.append(fonte["category"])
            if fonte.get("unread"):
                parti.append(f"{fonte['unread']} non letti")
            if fonte.get("last_error"):
                parti.append("ultimo aggiornamento non riuscito")
            return ", ".join(parti)
        except Exception as ex:
            scrivi_log("NewsView._etichetta_fonte", ex)
            return str(fonte.get("name", ""))

    def _voci_fonti(self, fonti, mostra_categoria=True):
        voci = []
        try:
            for fonte in fonti or []:
                voci.append(
                    (
                        self._etichetta_fonte(fonte, mostra_categoria),
                        partial(self.apri_fonte, fonte["url"]),
                        partial(self._azioni_fonte, fonte["url"]),
                    )
                )
        except Exception as ex:
            scrivi_log("NewsView._voci_fonti", ex)
        return voci

    def _azioni_fonte(self, url):
        try:
            if self.manager.get_source(url) is None:
                return []
            return [
                ("Apri", partial(self.apri_fonte, url), None),
                ("Aggiorna ora", partial(self.aggiorna_fonte, url), None),
                ("Segna tutte come lette", self._segna_tutte(url), None),
                ("Rinomina", partial(self.rinomina_fonte, url), None),
                ("Sposta in un'altra categoria", partial(self.sposta_fonte, url), None),
                ("Elimina la fonte", partial(self.elimina_fonte, url), None),
            ]
        except Exception as ex:
            scrivi_log(f"NewsView._azioni_fonte ({url})", ex)
            return []

    def apri_fonti(self):
        try:
            self.finestra.push_menu(
                "Fonti",
                lambda: self._voci_fonti(self.manager.get_sources(), True),
                "Nessuna fonte configurata.",
            )
        except Exception as ex:
            scrivi_log("NewsView.apri_fonti", ex)

    def aggiorna_fonte(self, url):
        try:
            fonte = self.manager.get_source(url)
            if fonte is None:
                return
            titolo = self.finestra.titolo_corrente()
            self.finestra.mostra_stato(f"Aggiornamento di {fonte['name']} in corso.")
            threading.Thread(
                target=self._esegui_aggiornamento_fonte,
                args=(fonte, titolo),
                name="AggiornaFonte",
                daemon=True,
            ).start()
        except Exception as ex:
            scrivi_log(f"NewsView.aggiorna_fonte ({url})", ex)

    def _esegui_aggiornamento_fonte(self, fonte, titolo):
        try:
            esito = self.manager.update_source(fonte)
            GLib.idle_add(self._aggiornamento_fonte_concluso, fonte, titolo, esito)
        except Exception as ex:
            scrivi_log("NewsView._esegui_aggiornamento_fonte", ex)

    def _aggiornamento_fonte_concluso(self, fonte, titolo, esito):
        try:
            if self.finestra.titolo_corrente() == titolo:
                self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            if esito.get("errore"):
                self.finestra.mostra_stato(f"Aggiornamento di {fonte['name']} non riuscito.")
            else:
                self.finestra.mostra_stato(f"{fonte['name']} aggiornata, {conta(esito.get('nuovi', 0), 'articolo nuovo', 'articoli nuovi')}.")
        except Exception as ex:
            scrivi_log("NewsView._aggiornamento_fonte_concluso", ex)
        return False

    def rinomina_fonte(self, url):
        try:
            fonte = self.manager.get_source(url)
            if fonte is None:
                return
            nome = self.finestra.chiedi_testo("Rinomina la fonte", "Nuovo nome della fonte", fonte["name"])
            if nome and nome != fonte["name"]:
                self._operazione(
                    f"Fonte rinominata in {nome}.",
                    "Impossibile rinominare la fonte.",
                    self.manager.rename_source,
                    url,
                    nome,
                )
        except Exception as ex:
            scrivi_log(f"NewsView.rinomina_fonte ({url})", ex)

    def sposta_fonte(self, url):
        try:
            fonte = self.manager.get_source(url)
            if fonte is None:
                return
            voci = [
                (categoria["name"], partial(self._conferma_spostamento, url, categoria["id"], categoria["name"]), None)
                for categoria in self.manager.get_categories()
                if categoria["id"] != fonte["category_id"]
            ]
            if not voci:
                self.finestra.mostra_messaggio("Non ci sono altre categorie.", "Aggiungere una categoria da Gestione categorie.")
                return
            self.finestra.push_menu(f"Sposta {fonte['name']} in", voci)
        except Exception as ex:
            scrivi_log(f"NewsView.sposta_fonte ({url})", ex)

    def _conferma_spostamento(self, url, category_id, nome_categoria):
        try:
            riuscito = self.manager.move_source(url, category_id)
            self.finestra.go_back()
            if riuscito:
                self.finestra.mostra_stato(f"Fonte spostata in {nome_categoria}.")
            else:
                self.finestra.mostra_messaggio("Impossibile spostare la fonte.")
        except Exception as ex:
            scrivi_log(f"NewsView._conferma_spostamento ({url})", ex)

    def elimina_fonte(self, url):
        try:
            fonte = self.manager.get_source(url)
            if fonte is None:
                return
            if self.finestra.chiedi_conferma(f"Eliminare la fonte {fonte['name']} e le sue notizie scaricate?"):
                self._operazione(
                    f"Fonte {fonte['name']} eliminata.",
                    "Impossibile eliminare la fonte.",
                    self.manager.remove_source,
                    fonte,
                )
        except Exception as ex:
            scrivi_log(f"NewsView.elimina_fonte ({url})", ex)

    def _etichetta_categoria(self, categoria, mostra_avvisi):
        try:
            parti = [categoria["name"]]
            if mostra_avvisi:
                parti.append("avvisi attivi" if categoria["notify"] else "avvisi disattivati")
            parti.append(conta(categoria["sources"], "fonte", "fonti"))
            if categoria["unread"]:
                parti.append(f"{categoria['unread']} non letti")
            return ", ".join(parti)
        except Exception as ex:
            scrivi_log("NewsView._etichetta_categoria", ex)
            return str(categoria.get("name", ""))

    def apri_categorie_lettura(self):
        try:
            self.finestra.push_menu(
                "Notizie per categoria",
                lambda: [
                    (
                        self._etichetta_categoria(categoria, False),
                        partial(self.apri_categoria, categoria["id"]),
                        partial(self._azioni_categoria, categoria["id"]),
                    )
                    for categoria in self.manager.get_categories()
                ],
                "Nessuna categoria.",
            )
        except Exception as ex:
            scrivi_log("NewsView.apri_categorie_lettura", ex)

    def apri_categoria(self, category_id):
        try:
            categoria = self.manager.get_category(category_id)
            if categoria is None:
                return
            if not categoria["sources"]:
                self.finestra.mostra_messaggio("Nessuna fonte in questa categoria.")
                return
            self.finestra.push_menu(
                f"Categoria {categoria['name']}",
                partial(self._voci_categoria, category_id),
                "Nessuna fonte in questa categoria.",
            )
        except Exception as ex:
            scrivi_log(f"NewsView.apri_categoria ({category_id})", ex)

    def _voci_categoria(self, category_id):
        try:
            fonti = self.manager.get_sources(category_id)
            if not fonti:
                return []
            return [("Tutte le notizie della categoria", partial(self.apri_articoli_categoria, category_id), None)] + self._voci_fonti(fonti, False)
        except Exception as ex:
            scrivi_log(f"NewsView._voci_categoria ({category_id})", ex)
            return []

    def _azioni_categoria(self, category_id):
        try:
            categoria = self.manager.get_category(category_id)
            if categoria is None:
                return []
            return [
                ("Apri", partial(self.apri_categoria, category_id), None),
                (
                    "Disattiva gli avvisi" if categoria["notify"] else "Attiva gli avvisi",
                    partial(
                        self._operazione,
                        "Avvisi disattivati." if categoria["notify"] else "Avvisi attivati.",
                        "Impossibile modificare gli avvisi della categoria.",
                        self.manager.set_category_notify,
                        category_id,
                        not categoria["notify"],
                    ),
                    None,
                ),
                ("Rinomina", partial(self.rinomina_categoria, category_id), None),
                ("Segna tutte come lette", self._segna_tutte(None, category_id), None),
                ("Elimina la categoria", partial(self.elimina_categoria, category_id), None),
            ]
        except Exception as ex:
            scrivi_log(f"NewsView._azioni_categoria ({category_id})", ex)
            return []

    def apri_gestione_categorie(self):
        try:
            self.finestra.push_menu("Gestione categorie", self._voci_gestione_categorie)
        except Exception as ex:
            scrivi_log("NewsView.apri_gestione_categorie", ex)

    def _voci_gestione_categorie(self):
        try:
            voci = [("Nuova categoria", self.aggiungi_categoria, None)]
            for categoria in self.manager.get_categories():
                voci.append(
                    (
                        self._etichetta_categoria(categoria, True),
                        partial(self.apri_categoria, categoria["id"]),
                        partial(self._azioni_categoria, categoria["id"]),
                    )
                )
            return voci
        except Exception as ex:
            scrivi_log("NewsView._voci_gestione_categorie", ex)
            return [("Nuova categoria", self.aggiungi_categoria, None)]

    def aggiungi_categoria(self):
        try:
            nome = self.finestra.chiedi_testo("Nuova categoria", "Nome della nuova categoria")
            if not nome:
                return
            esito = self.manager.add_category(nome)
            if esito == gestore.ESITO_DUPLICATO:
                self.finestra.mostra_messaggio("Esiste già una categoria con questo nome.")
            elif esito != gestore.ESITO_OK:
                self.finestra.mostra_messaggio("Impossibile aggiungere la categoria.", ERRORE_LOG)
            else:
                self.finestra.ricarica_menu_corrente()
                self.finestra.mostra_stato(f"Categoria {nome} aggiunta.")
        except Exception as ex:
            scrivi_log("NewsView.aggiungi_categoria", ex)

    def rinomina_categoria(self, category_id):
        try:
            categoria = self.manager.get_category(category_id)
            if categoria is None:
                return
            nome = self.finestra.chiedi_testo("Rinomina la categoria", "Nuovo nome della categoria", categoria["name"])
            if not nome or nome == categoria["name"]:
                return
            esito = self.manager.rename_category(category_id, nome)
            if esito == gestore.ESITO_DUPLICATO:
                self.finestra.mostra_messaggio("Esiste già una categoria con questo nome.")
            elif esito != gestore.ESITO_OK:
                self.finestra.mostra_messaggio("Impossibile rinominare la categoria.", ERRORE_LOG)
            else:
                self.finestra.mostra_stato(f"Categoria rinominata in {nome}.")
        except Exception as ex:
            scrivi_log(f"NewsView.rinomina_categoria ({category_id})", ex)

    def elimina_categoria(self, category_id):
        try:
            categoria = self.manager.get_category(category_id)
            if categoria is None:
                return
            if categoria["sources"]:
                self.finestra.mostra_messaggio(
                    "La categoria contiene delle fonti.",
                    "Spostare o eliminare le fonti prima di eliminare la categoria.",
                )
                return
            if not self.finestra.chiedi_conferma(f"Eliminare la categoria {categoria['name']}?"):
                return
            if self.manager.delete_category(category_id) != gestore.ESITO_OK:
                self.finestra.mostra_messaggio("Impossibile eliminare la categoria.", ERRORE_LOG)
            else:
                self.finestra.mostra_stato(f"Categoria {categoria['name']} eliminata.")
        except Exception as ex:
            scrivi_log(f"NewsView.elimina_categoria ({category_id})", ex)

    def cerca(self):
        try:
            testo = self.finestra.chiedi_testo("Cerca nelle notizie", "Testo da cercare")
            if not testo:
                return
            self.finestra.push_menu(
                f"Notizie trovate per {testo}",
                partial(self._voci_ricerca, testo),
                "Nessuna notizia trovata.",
            )
        except Exception as ex:
            scrivi_log("NewsView.cerca", ex)

    def _voci_ricerca(self, testo):
        try:
            articoli = self.manager.search_articles(testo)
            voci = self._voci_articoli(articoli, True)
            chiavi = {articolo.chiave() for articolo in articoli}
            for salvato in self.manager.get_saved(testo):
                if salvato["key"] in chiavi:
                    continue
                voci.append(self._voce_salvato(salvato, True))
            return voci
        except Exception as ex:
            scrivi_log(f"NewsView._voci_ricerca ({testo})", ex)
            return []

    def _voce_salvato(self, salvato, indica_salvato=False):
        articolo = salvato["article"]
        etichetta = articolo.label(True)
        if indica_salvato:
            etichetta = f"{etichetta}, salvato"
        return (etichetta, partial(self.leggi_salvato, salvato["key"]), partial(self._azioni_salvato, salvato["key"]))

    def apri_salvati(self):
        try:
            self.finestra.push_menu(
                "Articoli salvati",
                lambda: [self._voce_salvato(salvato) for salvato in self.manager.get_saved()],
                "Nessun articolo salvato.",
            )
        except Exception as ex:
            scrivi_log("NewsView.apri_salvati", ex)

    def _trova_salvato(self, key):
        try:
            for salvato in self.manager.get_saved():
                if salvato["key"] == key:
                    return salvato
            return None
        except Exception as ex:
            scrivi_log(f"NewsView._trova_salvato ({key})", ex)
            return None

    def _azioni_salvato(self, key, con_lettura=True):
        try:
            salvato = self._trova_salvato(key)
            if salvato is None:
                return []
            articolo = salvato["article"]
            azioni = []
            if con_lettura:
                azioni.append(("Leggi", partial(self.leggi_salvato, key), None))
            azioni.append(("Rimuovi dagli articoli salvati", self._rimuovi_salvato(key), None))
            if articolo.link:
                azioni.append(("Apri nel browser", partial(self.finestra.apri_nel_browser, articolo.link), None))
                azioni.append(("Copia il link", partial(self.copia_link, articolo.link), None))
            return azioni
        except Exception as ex:
            scrivi_log(f"NewsView._azioni_salvato ({key})", ex)
            return []

    def leggi_salvato(self, key):
        try:
            salvato = self._trova_salvato(key)
            if salvato is None:
                self.finestra.mostra_messaggio("L'articolo salvato non è più disponibile.")
                return
            articolo = salvato["article"]
            self.finestra.mostra_pagina(
                self._pagina_articolo(articolo, articolo.full_text, "", partial(self._azioni_salvato, key, False))
            )
        except Exception as ex:
            scrivi_log(f"NewsView.leggi_salvato ({key})", ex)

    def aggiungi_fonte(self):
        try:
            indirizzo = self.finestra.chiedi_testo("Nuova fonte", "Indirizzo del sito o del feed")
            if not indirizzo:
                return
            if not self.manager.get_categories():
                self.finestra.mostra_messaggio("Nessuna categoria disponibile.", "Aggiungere una categoria da Gestione categorie.")
                return
            self.finestra.carica_in_background(
                "Ricerca del feed",
                partial(self._rileva_fonte, indirizzo),
                self._voci_categoria_nuova_fonte,
                "Nessuna categoria disponibile.",
                self._messaggio_errore_rilevamento,
                "Categoria della nuova fonte",
            )
        except Exception as ex:
            scrivi_log("NewsView.aggiungi_fonte", ex)

    def _rileva_fonte(self, indirizzo):
        rilevata = self.parser.detect_source(indirizzo)
        if self.manager.source_exists(rilevata["feed_url"]):
            raise FonteGiaPresente(rilevata["feed_url"])
        return rilevata

    def _messaggio_errore_rilevamento(self, errore):
        try:
            if isinstance(errore, FonteGiaPresente):
                return "La fonte è già presente."
            if isinstance(errore, SitoNonRaggiungibile):
                return "Il sito non è raggiungibile. Controllare l'indirizzo e la connessione."
            if isinstance(errore, FeedNonTrovato):
                return "Nessun feed trovato a questo indirizzo."
            return "Impossibile verificare l'indirizzo."
        except Exception as ex:
            scrivi_log("NewsView._messaggio_errore_rilevamento", ex)
            return "Impossibile verificare l'indirizzo."

    def _voci_categoria_nuova_fonte(self, rilevata):
        try:
            return [
                (categoria["name"], partial(self._conferma_nuova_fonte, rilevata, categoria["id"], categoria["name"]), None)
                for categoria in self.manager.get_categories()
            ]
        except Exception as ex:
            scrivi_log("NewsView._voci_categoria_nuova_fonte", ex)
            return []

    def _conferma_nuova_fonte(self, rilevata, category_id, nome_categoria):
        try:
            nome = self.finestra.chiedi_testo("Nome della fonte", "Nome della fonte", rilevata.get("name", ""))
            if not nome:
                return
            esito = self.manager.add_source(nome, rilevata, category_id)
            if esito == gestore.ESITO_OK:
                self.finestra.go_back()
                threading.Thread(
                    target=self._prima_lettura,
                    args=(rilevata["feed_url"], nome),
                    name="PrimaLetturaFonte",
                    daemon=True,
                ).start()
                self.finestra.mostra_messaggio(
                    f"Fonte {nome} aggiunta alla categoria {nome_categoria}.",
                    "Le notizie vengono scaricate in questo momento.",
                )
            elif esito == gestore.ESITO_DUPLICATO:
                self.finestra.go_back()
                self.finestra.mostra_messaggio("La fonte è già presente.")
            else:
                self.finestra.mostra_messaggio("Impossibile aggiungere la fonte.", "I dettagli sono nel file di log.")
        except Exception as ex:
            scrivi_log("NewsView._conferma_nuova_fonte", ex)

    def _prima_lettura(self, url, nome):
        esito = None
        try:
            esito = self.manager.update_source(url)
        except Exception as ex:
            scrivi_log(f"NewsView._prima_lettura ({url})", ex)
        try:
            GLib.idle_add(self._prima_lettura_conclusa, nome, esito)
        except Exception as ex:
            scrivi_log("NewsView._prima_lettura consegna", ex)

    def _prima_lettura_conclusa(self, nome, esito):
        try:
            if esito is None or esito.get("errore"):
                self.finestra.mostra_messaggio(
                    f"Impossibile scaricare le notizie di {nome}.",
                    "La fonte è stata aggiunta. Riprovare più tardi da Aggiorna ora.",
                )
            else:
                self.finestra.mostra_stato(f"{nome}: {conta(esito.get('nuovi', 0), 'articolo scaricato', 'articoli scaricati')}.")
                if self.finestra.titolo_corrente() == TITOLO_MENU:
                    self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
        except Exception as ex:
            scrivi_log("NewsView._prima_lettura_conclusa", ex)
        return False

    def aggiorna_tutte(self):
        try:
            if not self.manager.get_sources():
                self.finestra.mostra_messaggio("Nessuna fonte configurata.", "Aggiungere una fonte dal menu Notizie.")
                return
            self.finestra.mostra_stato("Aggiornamento delle notizie in corso.")
            self.updater.aggiorna_ora(self._aggiornamento_concluso)
        except Exception as ex:
            scrivi_log("NewsView.aggiorna_tutte", ex)

    def _aggiornamento_concluso(self, resoconto):
        try:
            if not resoconto:
                self.finestra.mostra_messaggio("Impossibile aggiornare le notizie.", ERRORE_LOG)
                return
            if self.finestra.titolo_corrente() == TITOLO_MENU:
                self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            testo = f"Notizie aggiornate, {conta(resoconto['nuovi'], 'articolo nuovo', 'articoli nuovi')}."
            if resoconto["errori"]:
                testo += f" {conta(resoconto['errori'], 'fonte non ha risposto', 'fonti non hanno risposto')}."
            self.finestra.mostra_stato(testo)
        except Exception as ex:
            scrivi_log("NewsView._aggiornamento_concluso", ex)
