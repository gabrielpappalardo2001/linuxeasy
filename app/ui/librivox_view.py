import re
import threading
from functools import partial

from gi.repository import GLib

from app.core.log import scrivi_log
from app.core.mpv_engine import TrackInfo
from app.librivox import librivox_downloads as scaricamenti
from app.librivox.librivox_catalog import (
    INIZIALE_ALTRI,
    NOMI_LINGUE,
    TUTTE_LE_LINGUE,
    durata_leggibile,
    in_lingua,
    nome_lingua,
)
from app.ui.pagina import PaginaProgresso, PaginaTesto

TITOLO_MENU = "Menu LibriVox"
TITOLO_LINGUE = "Elenco per lingua"
TITOLO_SCELTA_LINGUA = "Lingua preferita di LibriVox"
TITOLO_SCARICATI = "Audiolibri scaricati"
TITOLO_DOWNLOAD = "Download degli audiolibri"
TITOLO_PREFERITI = "Audiolibri preferiti"
TITOLO_RECENTI = "Audiolibri recenti"
TITOLO_AVANZAMENTO_CATALOGO = "Download del catalogo di LibriVox"
TIPO_ASCOLTO = "audiolibro"
SOGLIA_ELENCO = 300
ERRORE_RETE = "Impossibile contattare LibriVox. Riprovare più tardi."
ERRORE_LOG = "I dettagli sono nel file di log."


def conta(numero, singolare, plurale):
    try:
        return f"1 {singolare}" if numero == 1 else f"{numero} {plurale}"
    except Exception as ex:
        scrivi_log("librivox_view.conta", ex)
        return str(numero)


def nome_iniziale(lettera):
    return "Numeri e simboli" if lettera == INIZIALE_ALTRI else lettera


class LibriVoxView:
    def __init__(self, finestra, engine, catalogo, libreria, downloads):
        self.finestra = finestra
        self.engine = engine
        self.catalogo = catalogo
        self.libreria = libreria
        self.downloads = downloads
        self._ascolto = None
        self._pagina_catalogo = None
        try:
            self.catalogo.imposta_ascoltatore(self._eventi_catalogo)
        except Exception as ex:
            scrivi_log("LibriVoxView.__init__ ascoltatore", ex)

    def get_menu_items(self):
        try:
            lingua = self.catalogo.lingua_preferita()
            voci = [
                (f"Opere {in_lingua(lingua)}", self.apri_opere, None),
                (f"Autori {in_lingua(lingua)}", self.apri_autori, None),
                ("Elenco per lingua", self.apri_lingue, None),
                ("Cerca un'opera", self.cerca_opera, None),
                ("Cerca un autore", self.cerca_autore, None),
                ("Audiolibri scaricati", self.apri_scaricati, None),
            ]
            in_corso = self.downloads.numero_in_corso() if self.downloads is not None else 0
            if in_corso:
                voci.append((f"{TITOLO_DOWNLOAD}, {in_corso}", self.apri_download, None))
            voci.extend(
                [
                    (TITOLO_PREFERITI, self.apri_preferiti, None),
                    (TITOLO_RECENTI, self.apri_recenti, None),
                    (f"Cambia la lingua, attuale: {nome_lingua(lingua)}", self.apri_scelta_lingua, None),
                    (self._etichetta_catalogo(), self.aggiorna_catalogo, self._azioni_catalogo),
                ]
            )
            return voci
        except Exception as ex:
            scrivi_log("LibriVoxView.get_menu_items", ex)
            return [(self._etichetta_catalogo(), self.aggiorna_catalogo, self._azioni_catalogo)]

    def _azioni_catalogo(self):
        try:
            if self.catalogo.aggiornamento_in_corso:
                return [
                    ("Segui l'avanzamento del download", self.apri_avanzamento_catalogo, None),
                    ("Annulla il download del catalogo", self.annulla_catalogo, None),
                ]
            if self.catalogo.eventi():
                return [
                    ("Rileggi il resoconto dell'ultimo download", self.apri_avanzamento_catalogo, None),
                    ("Scarica di nuovo il catalogo", self.aggiorna_catalogo, None),
                ]
            return [("Scarica il catalogo", self.aggiorna_catalogo, None)]
        except Exception as ex:
            scrivi_log("LibriVoxView._azioni_catalogo", ex)
            return []

    def _azioni_avanzamento(self):
        try:
            if self.catalogo.aggiornamento_in_corso:
                return [("Annulla il download del catalogo", self.annulla_catalogo, None)]
            return [("Scarica di nuovo il catalogo", self.aggiorna_catalogo, None)]
        except Exception as ex:
            scrivi_log("LibriVoxView._azioni_avanzamento", ex)
            return []

    def _etichetta_catalogo(self):
        try:
            if self.catalogo.aggiornamento_in_corso:
                return "Download del catalogo in corso, aprire per seguire l'avanzamento"
            totale = self.catalogo.numero_libri()
            if totale == 0:
                return "Scarica il catalogo di LibriVox"
            data = self.catalogo.data_aggiornamento()
            testo = f"Aggiorna il catalogo, {conta(totale, 'audiolibro', 'audiolibri')}"
            return f"{testo}, aggiornato il {data}" if data else testo
        except Exception as ex:
            scrivi_log("LibriVoxView._etichetta_catalogo", ex)
            return "Aggiorna il catalogo"

    def proponi_catalogo(self):
        try:
            if self.catalogo.ha_catalogo() or self.catalogo.aggiornamento_in_corso:
                return
            if self.finestra.chiedi_conferma(
                "Il catalogo di LibriVox non è ancora stato scaricato. Scaricarlo adesso?",
                "Il download richiede alcuni minuti. Nel frattempo il programma resta utilizzabile.",
            ):
                self.aggiorna_catalogo()
        except Exception as ex:
            scrivi_log("LibriVoxView.proponi_catalogo", ex)

    def _catalogo_pronto(self):
        try:
            if self.catalogo.ha_catalogo():
                return True
            if self.catalogo.aggiornamento_in_corso:
                self.finestra.mostra_messaggio(
                    "Il catalogo di LibriVox è in corso di download.",
                    f"Finora sono stati letti {self.catalogo.libri_letti} audiolibri. "
                    "Al termine compare un avviso. Per seguire l'avanzamento aprire il Centro di controllo.",
                )
                return False
            self.proponi_catalogo()
            return False
        except Exception as ex:
            scrivi_log("LibriVoxView._catalogo_pronto", ex)
            return False

    def aggiorna_catalogo(self):
        try:
            if self.catalogo.aggiornamento_in_corso:
                self.apri_avanzamento_catalogo()
                return
            self._pagina_catalogo = None
            if not self.catalogo.avvia_aggiornamento(self._catalogo_aggiornato):
                self.finestra.mostra_messaggio("Impossibile avviare il download del catalogo.", ERRORE_LOG)
                return
            self._ricarica_se(TITOLO_MENU)
            self.finestra.mostra_stato("Download del catalogo di LibriVox avviato.")
            self.apri_avanzamento_catalogo()
        except Exception as ex:
            scrivi_log("LibriVoxView.aggiorna_catalogo", ex)

    def _pagina_avanzamento(self):
        try:
            if self._pagina_catalogo is None:
                self._pagina_catalogo = PaginaProgresso(
                    TITOLO_AVANZAMENTO_CATALOGO,
                    self.catalogo.eventi(),
                    self._azioni_avanzamento,
                )
            return self._pagina_catalogo
        except Exception as ex:
            scrivi_log("LibriVoxView._pagina_avanzamento", ex)
            return None

    def _sincronizza_pagina(self, pagina):
        try:
            eventi = self.catalogo.eventi()
            for riga in eventi[len(pagina.righe):]:
                self.finestra.aggiungi_riga_pagina(pagina, riga)
        except Exception as ex:
            scrivi_log("LibriVoxView._sincronizza_pagina", ex)

    def _eventi_catalogo(self):
        try:
            if self._pagina_catalogo is not None:
                self._sincronizza_pagina(self._pagina_catalogo)
        except Exception as ex:
            scrivi_log("LibriVoxView._eventi_catalogo", ex)

    def apri_avanzamento_catalogo(self):
        try:
            if not self.catalogo.aggiornamento_in_corso and not self.catalogo.eventi():
                self.finestra.mostra_messaggio("Nessun download del catalogo in corso.")
                return
            pagina = self._pagina_avanzamento()
            if pagina is None:
                self.finestra.mostra_messaggio("Impossibile mostrare l'avanzamento del download.", ERRORE_LOG)
                return
            self._sincronizza_pagina(pagina)
            if self.finestra.in_pagina() and self.finestra.titolo_corrente() == TITOLO_AVANZAMENTO_CATALOGO:
                if self.finestra.current_source is pagina:
                    return
                self.finestra.go_back()
            self.finestra.mostra_pagina(pagina)
        except Exception as ex:
            scrivi_log("LibriVoxView.apri_avanzamento_catalogo", ex)

    def annulla_catalogo(self):
        try:
            if not self.catalogo.aggiornamento_in_corso:
                self.finestra.mostra_messaggio("Nessun download del catalogo in corso.")
                return
            if not self.finestra.chiedi_conferma(
                "Annullare il download del catalogo di LibriVox?",
                "Il catalogo già presente resta invariato.",
            ):
                return
            if self.catalogo.annulla_aggiornamento():
                self.finestra.mostra_stato("Annullamento del download del catalogo richiesto.")
            else:
                self.finestra.mostra_messaggio("Impossibile annullare il download del catalogo.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("LibriVoxView.annulla_catalogo", ex)

    def _catalogo_aggiornato(self, esito):
        try:
            self._ricarica_se(TITOLO_MENU)
            if esito.get("annullato"):
                self.finestra.mostra_stato("Download del catalogo di LibriVox annullato.")
                self.finestra.notifica_operazione("LibriVox", "Download del catalogo annullato.")
                return
            if esito.get("errore"):
                self.finestra.notifica_operazione("LibriVox", "Download del catalogo non riuscito.")
                self.finestra.mostra_messaggio(
                    "Download del catalogo di LibriVox non riuscito.",
                    f"Controllare la connessione e riprovare. {ERRORE_LOG}",
                )
                return
            testo = f"Catalogo di LibriVox aggiornato: {conta(esito.get('libri', 0), 'audiolibro', 'audiolibri')}."
            self.finestra.mostra_stato(testo)
            self.finestra.notifica_operazione("LibriVox", testo)
        except Exception as ex:
            scrivi_log("LibriVoxView._catalogo_aggiornato", ex)

    def _ricarica_se(self, *titoli):
        try:
            if self.finestra.titolo_corrente() in titoli and not self.finestra.in_pagina():
                self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
        except Exception as ex:
            scrivi_log("LibriVoxView._ricarica_se", ex)

    def _etichetta_libro(self, libro, con_lingua=False, con_autore=True):
        try:
            parti = [libro.title]
            if con_autore and libro.authors:
                parti.append(libro.authors)
            durata = durata_leggibile(libro.totaltime)
            if durata:
                parti.append(durata)
            if con_lingua and libro.language:
                parti.append(nome_lingua(libro.language))
            return ", ".join(parte for parte in parti if parte)
        except Exception as ex:
            scrivi_log("LibriVoxView._etichetta_libro", ex)
            return str(getattr(libro, "title", ""))

    def _voci_libri(self, libri, con_lingua=False, con_autore=True, recente=False):
        voci = []
        try:
            for libro in libri or []:
                voci.append(
                    (
                        self._etichetta_libro(libro, con_lingua, con_autore),
                        partial(self.apri_libro, libro),
                        partial(self._azioni_libro, libro, recente),
                    )
                )
        except Exception as ex:
            scrivi_log("LibriVoxView._voci_libri", ex)
        return voci

    def _azioni_libro(self, libro, recente=False):
        try:
            azioni = [("Ascolta", partial(self.apri_libro, libro), None)]
            progresso = self.libreria.progresso(libro.id)
            if progresso is not None:
                testo = f"Riprendi dal capitolo {progresso['capitolo'] + 1}"
                if progresso["titolo_capitolo"]:
                    testo = f"{testo}: {progresso['titolo_capitolo']}"
                azioni.append((testo, partial(self.riprendi, libro), None))
            stato = self.downloads.stato(libro.id) if self.downloads is not None else None
            if stato == scaricamenti.STATO_COMPLETATO:
                azioni.append(("Elimina l'audiolibro scaricato", partial(self.elimina_download, libro), None))
                azioni.append(("Apri la cartella dell'audiolibro", partial(self.apri_cartella, libro), None))
            elif stato in (scaricamenti.STATO_IN_CORSO, scaricamenti.STATO_IN_CODA):
                azioni.append(("Annulla il download", partial(self.annulla_download, libro), None))
            elif stato == scaricamenti.STATO_ERRORE:
                azioni.append(("Riprova il download", partial(self.riprova_download, libro), None))
                azioni.append(("Annulla il download", partial(self.annulla_download, libro), None))
            else:
                azioni.append(("Scarica l'audiolibro", partial(self.scarica, libro), None))
            if self.libreria.preferito(libro.id):
                azioni.append(("Rimuovi dagli audiolibri preferiti", partial(self.rimuovi_preferito, libro), None))
            else:
                azioni.append(("Aggiungi agli audiolibri preferiti", partial(self.aggiungi_preferito, libro), None))
            for autore in self.catalogo.autori_libro(libro.id):
                azioni.append((f"Altre opere di {autore.nome()}", partial(self.apri_autore, autore, None), None))
            if recente:
                azioni.append(("Rimuovi dagli audiolibri recenti", partial(self.rimuovi_recente, libro), None))
                azioni.append(("Svuota gli audiolibri recenti", self.svuota_recenti, None))
            azioni.append(("Informazioni sull'audiolibro", partial(self.informazioni, libro), None))
            if libro.url_librivox:
                azioni.append(("Apri la pagina su LibriVox", partial(self.finestra.apri_nel_browser, libro.url_librivox), None))
            return azioni
        except Exception as ex:
            scrivi_log(f"LibriVoxView._azioni_libro ({getattr(libro, 'id', '')})", ex)
            return []

    def _voci_iniziali(self, coppie, apri, singolare, plurale):
        voci = []
        try:
            for lettera, numero in coppie:
                voci.append((f"{nome_iniziale(lettera)}, {conta(numero, singolare, plurale)}", partial(apri, lettera), None))
        except Exception as ex:
            scrivi_log("LibriVoxView._voci_iniziali", ex)
        return voci

    def apri_opere(self, lingua=None):
        try:
            if not self._catalogo_pronto():
                return
            lingua = lingua or self.catalogo.lingua_preferita()
            totale = self.catalogo.numero_libri(lingua)
            titolo = f"Opere {in_lingua(lingua)}"
            if totale == 0:
                self.finestra.mostra_messaggio(f"Nessuna opera {in_lingua(lingua)} nel catalogo.")
                return
            if totale <= SOGLIA_ELENCO:
                self.finestra.push_menu(
                    titolo,
                    lambda: self._voci_libri(self.catalogo.opere(lingua), lingua == TUTTE_LE_LINGUE),
                    "Nessuna opera nel catalogo.",
                )
                return
            self.finestra.push_menu(
                titolo,
                lambda: self._voci_iniziali(
                    self.catalogo.iniziali_opere(lingua),
                    partial(self.apri_opere_lettera, lingua),
                    "opera",
                    "opere",
                ),
                "Nessuna opera nel catalogo.",
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxView.apri_opere ({lingua})", ex)

    def apri_opere_lettera(self, lingua, lettera):
        try:
            self.finestra.push_menu(
                f"Opere {in_lingua(lingua)}, {nome_iniziale(lettera)}",
                lambda: self._voci_libri(self.catalogo.opere(lingua, lettera), lingua == TUTTE_LE_LINGUE),
                "Nessuna opera con questa iniziale.",
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxView.apri_opere_lettera ({lingua}, {lettera})", ex)

    def _etichetta_autore(self, autore):
        try:
            testo = autore.nome_ordinato()
            date = autore.date()
            if date:
                testo = f"{testo} ({date})"
            if autore.opere:
                testo = f"{testo}, {conta(autore.opere, 'opera', 'opere')}"
            return testo
        except Exception as ex:
            scrivi_log("LibriVoxView._etichetta_autore", ex)
            return str(getattr(autore, "last_name", ""))

    def _voci_autori(self, autori, lingua):
        voci = []
        try:
            for autore in autori or []:
                azioni = [("Apri le opere", partial(self.apri_autore, autore, lingua), None)]
                if lingua != TUTTE_LE_LINGUE:
                    azioni.append(("Opere in tutte le lingue", partial(self.apri_autore, autore, TUTTE_LE_LINGUE), None))
                voci.append((self._etichetta_autore(autore), partial(self.apri_autore, autore, lingua), azioni))
        except Exception as ex:
            scrivi_log("LibriVoxView._voci_autori", ex)
        return voci

    def apri_autori(self, lingua=None):
        try:
            if not self._catalogo_pronto():
                return
            lingua = lingua or self.catalogo.lingua_preferita()
            totale = self.catalogo.numero_autori(lingua)
            titolo = f"Autori {in_lingua(lingua)}"
            if totale == 0:
                self.finestra.mostra_messaggio(f"Nessun autore {in_lingua(lingua)} nel catalogo.")
                return
            if totale <= SOGLIA_ELENCO:
                self.finestra.push_menu(
                    titolo,
                    lambda: self._voci_autori(self.catalogo.autori(lingua), lingua),
                    "Nessun autore nel catalogo.",
                )
                return
            self.finestra.push_menu(
                titolo,
                lambda: self._voci_iniziali(
                    self.catalogo.iniziali_autori(lingua),
                    partial(self.apri_autori_lettera, lingua),
                    "autore",
                    "autori",
                ),
                "Nessun autore nel catalogo.",
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxView.apri_autori ({lingua})", ex)

    def apri_autori_lettera(self, lingua, lettera):
        try:
            self.finestra.push_menu(
                f"Autori {in_lingua(lingua)}, {nome_iniziale(lettera)}",
                lambda: self._voci_autori(self.catalogo.autori(lingua, lettera), lingua),
                "Nessun autore con questa iniziale.",
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxView.apri_autori_lettera ({lingua}, {lettera})", ex)

    def apri_autore(self, autore, lingua=None):
        try:
            lingua = lingua or self.catalogo.lingua_preferita()
            if lingua != TUTTE_LE_LINGUE and not self.catalogo.opere_autore(autore.id, lingua):
                lingua = TUTTE_LE_LINGUE
            titolo = f"Opere di {autore.nome()}"
            if lingua != TUTTE_LE_LINGUE:
                titolo = f"{titolo} {in_lingua(lingua)}"
            self.finestra.push_menu(
                titolo,
                lambda: self._voci_libri(
                    self.catalogo.opere_autore(autore.id, lingua),
                    con_lingua=lingua == TUTTE_LE_LINGUE,
                    con_autore=False,
                ),
                "Nessuna opera di questo autore nel catalogo.",
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxView.apri_autore ({getattr(autore, 'id', '')})", ex)

    def apri_lingue(self):
        try:
            if not self._catalogo_pronto():
                return
            self.finestra.push_menu(TITOLO_LINGUE, self._voci_lingue, "Nessuna lingua nel catalogo.")
        except Exception as ex:
            scrivi_log("LibriVoxView.apri_lingue", ex)

    def _voci_lingue(self):
        voci = []
        try:
            for lingua, numero in self.catalogo.lingue():
                voci.append(
                    (
                        f"{nome_lingua(lingua)}, {conta(numero, 'opera', 'opere')}",
                        partial(self.apri_lingua, lingua),
                        [
                            ("Opere", partial(self.apri_opere, lingua), None),
                            ("Autori", partial(self.apri_autori, lingua), None),
                            ("Imposta come lingua preferita", partial(self.imposta_lingua, lingua, False), None),
                        ],
                    )
                )
        except Exception as ex:
            scrivi_log("LibriVoxView._voci_lingue", ex)
        return voci

    def apri_lingua(self, lingua):
        try:
            self.finestra.push_menu(nome_lingua(lingua), partial(self._voci_lingua, lingua))
        except Exception as ex:
            scrivi_log(f"LibriVoxView.apri_lingua ({lingua})", ex)

    def _voci_lingua(self, lingua):
        try:
            voci = [
                (f"Opere, {self.catalogo.numero_libri(lingua)}", partial(self.apri_opere, lingua), None),
                (f"Autori, {self.catalogo.numero_autori(lingua)}", partial(self.apri_autori, lingua), None),
            ]
            if self.catalogo.lingua_preferita() == lingua:
                voci.append(("È la lingua preferita", None, None))
            else:
                voci.append(("Imposta come lingua preferita", partial(self.imposta_lingua, lingua, False), None))
            return voci
        except Exception as ex:
            scrivi_log(f"LibriVoxView._voci_lingua ({lingua})", ex)
            return []

    def apri_scelta_lingua(self):
        try:
            for indice, voce in enumerate(self._voci_scelta_lingua()):
                if voce[0].endswith(", scelta attuale"):
                    self.finestra.menu_positions[TITOLO_SCELTA_LINGUA] = indice
                    break
            self.finestra.push_menu(TITOLO_SCELTA_LINGUA, self._voci_scelta_lingua)
        except Exception as ex:
            scrivi_log("LibriVoxView.apri_scelta_lingua", ex)

    def _voci_scelta_lingua(self):
        voci = []
        try:
            attuale = self.catalogo.lingua_preferita()
            lingue = self.catalogo.lingue()
            if not lingue:
                lingue = [(lingua, None) for lingua in sorted(NOMI_LINGUE, key=lambda nome: nome_lingua(nome))]
            totale = self.catalogo.numero_libri()
            elenco = [(TUTTE_LE_LINGUE, totale or None)] + lingue
            for lingua, numero in elenco:
                testo = nome_lingua(lingua)
                if numero:
                    testo = f"{testo}, {conta(numero, 'opera', 'opere')}"
                if lingua == attuale:
                    testo = f"{testo}, scelta attuale"
                voci.append((testo, partial(self.imposta_lingua, lingua, True), None))
        except Exception as ex:
            scrivi_log("LibriVoxView._voci_scelta_lingua", ex)
        return voci

    def imposta_lingua(self, lingua, torna_indietro):
        try:
            if not self.catalogo.imposta_lingua(lingua):
                self.finestra.mostra_messaggio("Impossibile salvare la lingua preferita.", ERRORE_LOG)
                return
            if torna_indietro:
                self.finestra.go_back()
            else:
                self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            self.finestra.mostra_stato(f"Lingua preferita: {nome_lingua(lingua)}.")
        except Exception as ex:
            scrivi_log(f"LibriVoxView.imposta_lingua ({lingua})", ex)

    def cerca_opera(self):
        try:
            if not self._catalogo_pronto():
                return
            testo = self.finestra.chiedi_testo("Cerca un'opera", "Titolo o parte del titolo")
            if testo:
                self.esegui_ricerca(testo, False)
        except Exception as ex:
            scrivi_log("LibriVoxView.cerca_opera", ex)

    def cerca_autore(self):
        try:
            if not self._catalogo_pronto():
                return
            testo = self.finestra.chiedi_testo("Cerca un autore", "Nome o cognome dell'autore")
            if testo:
                self.esegui_ricerca(testo, True)
        except Exception as ex:
            scrivi_log("LibriVoxView.cerca_autore", ex)

    def esegui_ricerca(self, testo, per_autore):
        try:
            lingua = self.catalogo.lingua_preferita()
            cerca = self.catalogo.cerca_autori if per_autore else self.catalogo.cerca_opere
            avviso = ""
            if not cerca(testo, lingua) and lingua != TUTTE_LE_LINGUE:
                if cerca(testo, TUTTE_LE_LINGUE):
                    avviso = f"Nessun risultato {in_lingua(lingua)}. Elenco i risultati in tutte le lingue."
                    lingua = TUTTE_LE_LINGUE
            if per_autore:
                aperto = self.finestra.push_menu(
                    f"Autori trovati per {testo}",
                    lambda: self._voci_autori(self.catalogo.cerca_autori(testo, lingua), lingua),
                    "Nessun autore trovato.",
                )
            else:
                aperto = self.finestra.push_menu(
                    f"Opere trovate per {testo}",
                    lambda: self._voci_libri(self.catalogo.cerca_opere(testo, lingua), lingua == TUTTE_LE_LINGUE),
                    "Nessuna opera trovata.",
                )
            if aperto and avviso:
                self.finestra.mostra_stato(avviso)
        except Exception as ex:
            scrivi_log(f"LibriVoxView.esegui_ricerca ({testo})", ex)

    def _etichetta_capitolo(self, capitolo):
        try:
            titolo = capitolo.title or f"Capitolo {capitolo.numero}"
            if not re.search(r"\d", titolo):
                titolo = f"{capitolo.numero}. {titolo}"
            return f"{titolo}, {capitolo.durata}" if capitolo.durata else titolo
        except Exception as ex:
            scrivi_log("LibriVoxView._etichetta_capitolo", ex)
            return str(getattr(capitolo, "title", ""))

    def _azioni_capitolo(self, libro, capitoli, indice):
        try:
            azioni = [("Ascolta da questo capitolo", partial(self.riproduci, libro, capitoli, indice), None)]
            for testo, azione, altro in self._azioni_libro(libro):
                if testo != "Ascolta":
                    azioni.append((testo, azione, altro))
            return azioni
        except Exception as ex:
            scrivi_log("LibriVoxView._azioni_capitolo", ex)
            return []

    def _lettura_capitoli(self, libro):
        try:
            cartella = self.downloads.cartella(libro.id) if self.downloads is not None else None
            if cartella is not None:
                capitoli = scaricamenti.capitoli_locali(cartella)
                if capitoli:
                    return capitoli
            return self.catalogo.capitoli(libro)
        except Exception as ex:
            scrivi_log(f"LibriVoxView._lettura_capitoli ({getattr(libro, 'id', '')})", ex)
            raise

    def apri_libro(self, libro, indice=None):
        try:
            stato = self.downloads.stato(libro.id) if self.downloads is not None else None
            if stato == scaricamenti.STATO_COMPLETATO:
                self.finestra.push_menu(libro.title, partial(self._voci_libro_scaricato, libro), None)
                return
            if stato in (scaricamenti.STATO_IN_CORSO, scaricamenti.STATO_IN_CODA):
                self.finestra.mostra_messaggio(
                    "Il download dell'audiolibro è già in corso.",
                    f'È possibile seguirne l\'avanzamento da "{TITOLO_DOWNLOAD}" nel menu LibriVox.',
                )
                return
            if stato == scaricamenti.STATO_ERRORE:
                if self.finestra.chiedi_conferma(f"Il download di {libro.title} non è riuscito. Riprovare il download?"):
                    self.riprova_download(libro)
                return
            if self.finestra.chiedi_conferma(
                f"Scaricare l'audiolibro {libro.title}?",
                "Il download avviene in background: nel frattempo il programma resta utilizzabile.",
            ):
                self.scarica(libro)
        except Exception as ex:
            scrivi_log(f"LibriVoxView.apri_libro ({getattr(libro, 'id', '')})", ex)

    def _voci_libro_scaricato(self, libro):
        try:
            return [
                ("Ascolta", partial(self.apri_menu_ascolto, libro), None),
                ("Elimina l'audiolibro scaricato", partial(self.elimina_download, libro), None),
            ]
        except Exception as ex:
            scrivi_log(f"LibriVoxView._voci_libro_scaricato ({getattr(libro, 'id', '')})", ex)
            return []

    def apri_menu_ascolto(self, libro):
        try:
            self.finestra.push_menu(libro.title, partial(self._voci_menu_ascolto, libro), None)
        except Exception as ex:
            scrivi_log(f"LibriVoxView.apri_menu_ascolto ({getattr(libro, 'id', '')})", ex)

    def _voci_menu_ascolto(self, libro):
        try:
            return [
                ("Ascolta l'intero libro", partial(self.ascolta_intero, libro), None),
                ("Ascolta per capitoli", partial(self.apri_capitoli, libro), None),
            ]
        except Exception as ex:
            scrivi_log(f"LibriVoxView._voci_menu_ascolto ({getattr(libro, 'id', '')})", ex)
            return []

    def ascolta_intero(self, libro):
        try:
            self.finestra.mostra_stato(f"Caricamento dei capitoli di {libro.title}.")
            threading.Thread(
                target=self._carica_ascolto_intero,
                args=(libro,),
                name="AscoltoIntegraleLibriVox",
                daemon=True,
            ).start()
        except Exception as ex:
            scrivi_log(f"LibriVoxView.ascolta_intero ({getattr(libro, 'id', '')})", ex)

    def _carica_ascolto_intero(self, libro):
        capitoli = []
        try:
            capitoli = self._lettura_capitoli(libro)
        except Exception as ex:
            scrivi_log(f"LibriVoxView._carica_ascolto_intero ({libro.id})", ex)
        try:
            GLib.idle_add(self._avvia_ascolto_intero, libro, capitoli)
        except Exception as ex:
            scrivi_log("LibriVoxView._carica_ascolto_intero consegna", ex)

    def _avvia_ascolto_intero(self, libro, capitoli):
        try:
            if not capitoli:
                self.finestra.mostra_messaggio("Impossibile leggere i capitoli dell'audiolibro.", ERRORE_RETE)
                return False
            self.riproduci(libro, capitoli, 0)
        except Exception as ex:
            scrivi_log(f"LibriVoxView._avvia_ascolto_intero ({getattr(libro, 'id', '')})", ex)
        return False

    def apri_capitoli(self, libro):
        try:
            self.finestra.carica_in_background(
                libro.title,
                partial(self._lettura_capitoli, libro),
                partial(self._voci_capitoli_selezione, libro),
                "Nessun capitolo trovato per questo audiolibro.",
                ERRORE_RETE,
                selezione=True,
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxView.apri_capitoli ({getattr(libro, 'id', '')})", ex)

    def _voci_capitoli_selezione(self, libro, capitoli):
        voci = []
        try:
            elenco = list(capitoli or [])
            for indice, capitolo in enumerate(elenco):
                voci.append(
                    (
                        self._etichetta_capitolo(capitolo),
                        partial(self.riproduci_selezione, libro, elenco, indice),
                        partial(self._azioni_capitolo, libro, elenco, indice),
                    )
                )
        except Exception as ex:
            scrivi_log("LibriVoxView._voci_capitoli_selezione", ex)
        return voci

    def riproduci_selezione(self, libro, capitoli, indice):
        try:
            if not 0 <= indice < len(capitoli):
                return
            selezionati = self.finestra.get_selected_indices() if hasattr(self.finestra, "get_selected_indices") else []
            selezionati = [i for i in selezionati if 0 <= i < len(capitoli)]
            if selezionati:
                indici = selezionati if indice in selezionati else sorted(set(selezionati) | {indice})
            else:
                indici = [indice]
            sotto_elenco = [capitoli[i] for i in indici]
            avvio = indici.index(indice)
            tracce = [TrackInfo(title=capitolo.title, album=libro.title, url=capitolo.url) for capitolo in sotto_elenco]
            if self.engine is None or not self.engine.load_playlist(tracce, avvio, kind=TIPO_ASCOLTO):
                self.finestra.mostra_messaggio("Impossibile avviare la riproduzione.", "Verificare che mpv sia installato.")
                return
            self._ascolto = {"libro": libro, "capitoli": sotto_elenco}
            self.libreria.registra_ascolto(libro, avvio, sotto_elenco[avvio].title)
            if len(sotto_elenco) > 1:
                self.finestra.mostra_stato(
                    f"In ascolto: {libro.title} ({conta(len(sotto_elenco), 'capitolo selezionato', 'capitoli selezionati')}). "
                    "Ctrl+F per il capitolo successivo, Ctrl+B per il precedente."
                )
            else:
                self.finestra.mostra_stato(f"In ascolto: {libro.title}, {sotto_elenco[avvio].title}.")
            self.finestra.apri_player()
        except Exception as ex:
            scrivi_log(f"LibriVoxView.riproduci_selezione ({getattr(libro, 'id', '')})", ex)

    def riproduci(self, libro, capitoli, indice):
        try:
            if not 0 <= indice < len(capitoli):
                return
            tracce = [TrackInfo(title=capitolo.title, album=libro.title, url=capitolo.url) for capitolo in capitoli]
            if self.engine is None or not self.engine.load_playlist(tracce, indice, kind=TIPO_ASCOLTO):
                self.finestra.mostra_messaggio("Impossibile avviare la riproduzione.", "Verificare che mpv sia installato.")
                return
            self._ascolto = {"libro": libro, "capitoli": list(capitoli)}
            self.libreria.registra_ascolto(libro, indice, capitoli[indice].title)
            self.finestra.mostra_stato(
                f"In ascolto: {libro.title}, {capitoli[indice].title}. "
                "Ctrl+F per il capitolo successivo, Ctrl+B per il precedente."
            )
            self.finestra.apri_player()
        except Exception as ex:
            scrivi_log(f"LibriVoxView.riproduci ({getattr(libro, 'id', '')})", ex)

    def traccia_cambiata(self, indice):
        try:
            if self._ascolto is None or self.engine is None or self.engine.get_kind() != TIPO_ASCOLTO:
                return
            capitoli = self._ascolto["capitoli"]
            if 0 <= indice < len(capitoli):
                self.libreria.registra_ascolto(self._ascolto["libro"], indice, capitoli[indice].title)
        except Exception as ex:
            scrivi_log(f"LibriVoxView.traccia_cambiata ({indice})", ex)

    def riprendi(self, libro):
        try:
            progresso = self.libreria.progresso(libro.id)
            indice = progresso["capitolo"] if progresso is not None else 0
            titolo_capitolo = progresso["titolo_capitolo"] if progresso is not None else ""
            self.finestra.mostra_stato(f"Caricamento dei capitoli di {libro.title}.")
            threading.Thread(
                target=self._carica_ripresa,
                args=(libro, indice, titolo_capitolo),
                name="RipresaLibriVox",
                daemon=True,
            ).start()
        except Exception as ex:
            scrivi_log(f"LibriVoxView.riprendi ({getattr(libro, 'id', '')})", ex)

    def _carica_ripresa(self, libro, indice, titolo_capitolo):
        capitoli = []
        try:
            capitoli = self._lettura_capitoli(libro)
        except Exception as ex:
            scrivi_log(f"LibriVoxView._carica_ripresa ({libro.id})", ex)
        try:
            GLib.idle_add(self._avvia_ripresa, libro, capitoli, indice, titolo_capitolo)
        except Exception as ex:
            scrivi_log("LibriVoxView._carica_ripresa consegna", ex)

    def _avvia_ripresa(self, libro, capitoli, indice, titolo_capitolo):
        try:
            if not capitoli:
                self.finestra.mostra_messaggio("Impossibile leggere i capitoli dell'audiolibro.", ERRORE_RETE)
                return False
            if titolo_capitolo and not (0 <= indice < len(capitoli) and capitoli[indice].title == titolo_capitolo):
                for posizione, capitolo in enumerate(capitoli):
                    if capitolo.title == titolo_capitolo:
                        indice = posizione
                        break
            if not 0 <= indice < len(capitoli):
                indice = 0
            self.riproduci(libro, capitoli, indice)
        except Exception as ex:
            scrivi_log(f"LibriVoxView._avvia_ripresa ({getattr(libro, 'id', '')})", ex)
        return False

    def informazioni(self, libro):
        try:
            self.finestra.carica_in_background(
                f"Informazioni su {libro.title}",
                partial(self._dati_informazioni, libro),
                partial(self._pagina_informazioni, libro),
                "Informazioni non disponibili.",
                ERRORE_RETE,
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxView.informazioni ({getattr(libro, 'id', '')})", ex)

    def _dati_informazioni(self, libro):
        try:
            return self.catalogo.dettagli(libro)
        except Exception as ex:
            scrivi_log(f"LibriVoxView._dati_informazioni ({libro.id})", ex)
            return {"descrizione": "", "generi": [], "traduttori": [], "non_raggiungibile": True}

    def _pagina_informazioni(self, libro, dettagli):
        try:
            righe = [f"Titolo: {libro.title}"]
            autori = self.catalogo.autori_libro(libro.id)
            if autori:
                nomi = []
                for autore in autori:
                    date = autore.date()
                    nomi.append(f"{autore.nome()} ({date})" if date else autore.nome())
                righe.append(f"{'Autore' if len(nomi) == 1 else 'Autori'}: {', '.join(nomi)}")
            elif libro.authors:
                righe.append(f"Autori: {libro.authors}")
            if libro.language:
                righe.append(f"Lingua: {nome_lingua(libro.language)}")
            durata = durata_leggibile(libro.totaltime)
            if durata:
                righe.append(f"Durata: {durata}")
            if libro.num_sections:
                righe.append(f"Capitoli: {libro.num_sections}")
            if libro.copyright_year and libro.copyright_year != "0":
                righe.append(f"Anno del testo: {libro.copyright_year}")
            dettagli = dettagli or {}
            if dettagli.get("generi"):
                righe.append(f"Generi: {', '.join(dettagli['generi'])}")
            if dettagli.get("traduttori"):
                righe.append(f"Traduzione: {', '.join(dettagli['traduttori'])}")
            cartella = self.downloads.cartella(libro.id) if self.downloads is not None else None
            righe.append(f"Scaricato in: {cartella}" if cartella else "Non scaricato")
            progresso = self.libreria.progresso(libro.id)
            if progresso is not None:
                testo = f"Ultimo ascolto: capitolo {progresso['capitolo'] + 1}"
                if progresso["titolo_capitolo"]:
                    testo = f"{testo}, {progresso['titolo_capitolo']}"
                righe.append(testo)
            if dettagli.get("descrizione"):
                righe.append("")
                righe.append(dettagli["descrizione"])
            elif dettagli.get("non_raggiungibile"):
                righe.append("")
                righe.append("Descrizione non disponibile: LibriVox non è raggiungibile.")
            return PaginaTesto(f"Informazioni su {libro.title}", "\n".join(righe), partial(self._azioni_libro, libro))
        except Exception as ex:
            scrivi_log(f"LibriVoxView._pagina_informazioni ({getattr(libro, 'id', '')})", ex)
            return PaginaTesto(f"Informazioni su {libro.title}", libro.title)

    def aggiungi_preferito(self, libro):
        try:
            if self.libreria.aggiungi_preferito(libro):
                self.finestra.mostra_stato("Audiolibro aggiunto ai preferiti.")
            else:
                self.finestra.mostra_messaggio("Impossibile aggiungere l'audiolibro ai preferiti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("LibriVoxView.aggiungi_preferito", ex)

    def rimuovi_preferito(self, libro):
        try:
            if self.libreria.rimuovi_preferito(libro.id):
                self.finestra.mostra_stato("Audiolibro rimosso dai preferiti.")
            else:
                self.finestra.mostra_messaggio("Impossibile rimuovere l'audiolibro dai preferiti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("LibriVoxView.rimuovi_preferito", ex)

    def apri_preferiti(self):
        try:
            self.finestra.push_menu(
                TITOLO_PREFERITI,
                lambda: self._voci_libri(self.libreria.elenco_preferiti(), con_lingua=True),
                "Nessun audiolibro preferito.",
            )
        except Exception as ex:
            scrivi_log("LibriVoxView.apri_preferiti", ex)

    def apri_recenti(self):
        try:
            self.finestra.push_menu(TITOLO_RECENTI, self._voci_recenti, "Nessun audiolibro ascoltato di recente.")
        except Exception as ex:
            scrivi_log("LibriVoxView.apri_recenti", ex)

    def _voci_recenti(self):
        voci = []
        try:
            for elemento in self.libreria.elenco_recenti():
                libro = elemento["libro"]
                testo = self._etichetta_libro(libro)
                testo = f"{testo}, capitolo {elemento['capitolo'] + 1}"
                if elemento["titolo_capitolo"]:
                    testo = f"{testo}: {elemento['titolo_capitolo']}"
                voci.append((testo, partial(self.apri_libro, libro), partial(self._azioni_libro, libro, True)))
        except Exception as ex:
            scrivi_log("LibriVoxView._voci_recenti", ex)
        return voci

    def rimuovi_recente(self, libro):
        try:
            if self.libreria.rimuovi_recente(libro.id):
                self.finestra.mostra_stato("Audiolibro rimosso dai recenti.")
            else:
                self.finestra.mostra_messaggio("Impossibile rimuovere l'audiolibro dai recenti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"LibriVoxView.rimuovi_recente ({getattr(libro, 'id', '')})", ex)

    def svuota_recenti(self):
        try:
            if not self.finestra.chiedi_conferma("Svuotare l'elenco degli audiolibri recenti?"):
                return
            if self.libreria.svuota_recenti():
                self.finestra.mostra_stato("Elenco degli audiolibri recenti svuotato.")
            else:
                self.finestra.mostra_messaggio("Impossibile svuotare l'elenco dei recenti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("LibriVoxView.svuota_recenti", ex)

    def scarica(self, libro):
        try:
            esito = self.downloads.accoda(libro)
            if esito == scaricamenti.ESITO_ACCODATO:
                self.finestra.mostra_stato(f"Download avviato: {libro.title}.")
            elif esito == scaricamenti.STATO_COMPLETATO:
                self.finestra.mostra_messaggio("L'audiolibro è già stato scaricato.")
            elif esito in (scaricamenti.STATO_IN_CORSO, scaricamenti.STATO_IN_CODA):
                self.finestra.mostra_messaggio("L'audiolibro è già in download.")
            else:
                self.finestra.mostra_messaggio("Impossibile avviare il download.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"LibriVoxView.scarica ({getattr(libro, 'id', '')})", ex)

    def riprova_download(self, libro):
        try:
            if self.downloads.riprova(libro.id) == scaricamenti.ESITO_ACCODATO:
                self.finestra.mostra_stato(f"Download ripreso: {libro.title}.")
            else:
                self.finestra.mostra_messaggio("Impossibile riprendere il download.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"LibriVoxView.riprova_download ({getattr(libro, 'id', '')})", ex)

    def _ferma_se_in_ascolto(self, libro):
        try:
            if (
                self._ascolto is not None
                and self._ascolto["libro"].id == libro.id
                and self.engine is not None
                and self.engine.get_kind() == TIPO_ASCOLTO
                and self.engine.is_loaded()
            ):
                self.engine.stop()
        except Exception as ex:
            scrivi_log("LibriVoxView._ferma_se_in_ascolto", ex)

    def annulla_download(self, libro):
        try:
            if not self.finestra.chiedi_conferma(
                f"Annullare il download di {libro.title}?",
                "I capitoli già scaricati verranno cancellati.",
            ):
                return
            if self.downloads.elimina(libro.id):
                self.finestra.mostra_stato("Download annullato.")
            else:
                self.finestra.mostra_messaggio("Impossibile annullare il download.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"LibriVoxView.annulla_download ({getattr(libro, 'id', '')})", ex)

    def elimina_download(self, libro):
        try:
            if not self.finestra.chiedi_conferma(f"Eliminare l'audiolibro scaricato {libro.title}?"):
                return
            self._ferma_se_in_ascolto(libro)
            if self.downloads.elimina(libro.id):
                self.finestra.mostra_stato("Audiolibro eliminato.")
            else:
                self.finestra.mostra_messaggio("Impossibile eliminare l'audiolibro.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"LibriVoxView.elimina_download ({getattr(libro, 'id', '')})", ex)

    def apri_cartella(self, libro):
        try:
            cartella = self.downloads.cartella(libro.id)
            if cartella is None:
                self.finestra.mostra_messaggio("La cartella dell'audiolibro non esiste più.")
                return
            if not self.finestra.apri_nel_browser(cartella.as_uri()):
                self.finestra.mostra_messaggio("Impossibile aprire la cartella.", str(cartella))
        except Exception as ex:
            scrivi_log(f"LibriVoxView.apri_cartella ({getattr(libro, 'id', '')})", ex)

    def annulla_tutti_download(self):
        try:
            elementi = [elemento for elemento in self.downloads.in_corso() if elemento["stato"] != scaricamenti.STATO_ERRORE]
            if not elementi:
                self.finestra.mostra_messaggio("Nessun download di audiolibri in corso.")
                return
            if not self.finestra.chiedi_conferma(
                f"Annullare {conta(len(elementi), 'download', 'download')} di audiolibri?",
                "I capitoli già scaricati verranno cancellati.",
            ):
                return
            falliti = 0
            for elemento in elementi:
                if not self.downloads.elimina(elemento["libro"].id):
                    falliti += 1
            if falliti:
                self.finestra.mostra_messaggio(f"Non è stato possibile annullare {conta(falliti, 'download', 'download')}.", ERRORE_LOG)
            else:
                self.finestra.mostra_stato("Download degli audiolibri annullati.")
        except Exception as ex:
            scrivi_log("LibriVoxView.annulla_tutti_download", ex)

    def apri_scaricati(self):
        try:
            self.finestra.push_menu(TITOLO_SCARICATI, self._voci_scaricati, "Nessun audiolibro scaricato.")
        except Exception as ex:
            scrivi_log("LibriVoxView.apri_scaricati", ex)

    def _voci_scaricati(self):
        voci = []
        try:
            for elemento in self.downloads.elenco():
                libro = elemento["libro"]
                megabyte = f"{elemento['size'] / 1048576:.0f}"
                testo = f"{libro.title}, {libro.authors}" if libro.authors else libro.title
                if elemento["capitoli"]:
                    testo = f"{testo}, {conta(elemento['capitoli'], 'capitolo', 'capitoli')}"
                voci.append((f"{testo}, {megabyte} MB", partial(self.apri_libro, libro), partial(self._azioni_libro, libro)))
        except Exception as ex:
            scrivi_log("LibriVoxView._voci_scaricati", ex)
        return voci

    def apri_download(self):
        try:
            self.finestra.push_menu(TITOLO_DOWNLOAD, self._voci_download, "Nessun download di audiolibri in corso.")
        except Exception as ex:
            scrivi_log("LibriVoxView.apri_download", ex)

    def _voci_download(self):
        voci = []
        try:
            for elemento in self.downloads.in_corso():
                libro = elemento["libro"]
                if elemento["stato"] == scaricamenti.STATO_IN_CORSO:
                    if elemento["capitoli"]:
                        stato = f"capitolo {elemento['capitolo']} di {elemento['capitoli']}"
                        if elemento["percentuale"] is not None:
                            stato = f"{stato}, {elemento['percentuale']} per cento"
                    else:
                        stato = "lettura dei capitoli"
                    azioni = [("Annulla il download", partial(self.annulla_download, libro), None)]
                elif elemento["stato"] == scaricamenti.STATO_IN_CODA:
                    stato = "in attesa"
                    azioni = [("Annulla il download", partial(self.annulla_download, libro), None)]
                else:
                    stato = "download non riuscito"
                    azioni = [
                        ("Riprova il download", partial(self.riprova_download, libro), None),
                        ("Annulla il download", partial(self.annulla_download, libro), None),
                    ]
                voci.append((f"{libro.title}, {stato}", partial(self.finestra.ricarica_menu_corrente, False), azioni))
        except Exception as ex:
            scrivi_log("LibriVoxView._voci_download", ex)
        return voci

    def download_completato(self, libro):
        try:
            self._ricarica_se(TITOLO_DOWNLOAD, TITOLO_SCARICATI, TITOLO_MENU)
            self.finestra.mostra_stato(f"Audiolibro scaricato: {libro.title}.")
            self.finestra.notifica_operazione("Audiolibro scaricato", libro.title)
        except Exception as ex:
            scrivi_log("LibriVoxView.download_completato", ex)

    def download_fallito(self, libro):
        try:
            self._ricarica_se(TITOLO_DOWNLOAD, TITOLO_MENU)
            self.finestra.mostra_stato(f"Download non riuscito: {libro.title}. Riprovare da {TITOLO_DOWNLOAD}.")
            self.finestra.notifica_operazione("Download non riuscito", libro.title)
        except Exception as ex:
            scrivi_log("LibriVoxView.download_fallito", ex)
