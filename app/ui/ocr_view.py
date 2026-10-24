import threading
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from gi.repository import GLib

from app.core.log import scrivi_log
from app.ocr.motore_ocr import (
    ESTENSIONI_SUPPORTATE,
    LINGUA_PREDEFINITA,
    ErroreOcr,
    OcrAnnullato,
    OpzioniOcr,
    nome_lingua,
)
from app.ui.pagina import PaginaProgresso, PaginaTesto

TITOLO_AVANZAMENTO = "Riconoscimento in corso"
TITOLO_SCELTA_FILE = "Scegli il documento da riconoscere in"
CHIAVE_LINGUA = "ocr_lingua"
CHIAVE_IGNORA_DISEGNI = "ocr_ignora_disegni"
CHIAVE_USA_TESTO_PDF = "ocr_usa_testo_pdf"
CHIAVE_RETE_NEURALE = "ocr_rete_neurale"
CHIAVE_SEGNA_IMMAGINI = "ocr_segna_immagini"
CHIAVE_CORREGGI_PAROLE = "ocr_correggi_parole"
ERRORE_LOG = "I dettagli sono nel file di log."
MESSAGGIO_NON_DISPONIBILI = "Le impostazioni non sono disponibili."


def conta(numero, singolare, plurale):
    try:
        return f"1 {singolare}" if numero == 1 else f"{numero} {plurale}"
    except Exception as ex:
        scrivi_log("ocr_view.conta", ex)
        return str(numero)


def stato_scelta(attivo):
    return "sì" if attivo else "no"


@dataclass
class RisultatoOcr:
    percorso: Path
    lingua: str
    esito: object

    def titolo(self):
        return self.percorso.name

    def titolo_pagine(self):
        return f"Pagine di {self.percorso.name}"


class OcrView:
    def __init__(self, finestra, motore, selettore, impostazioni):
        self.finestra = finestra
        self.motore = motore
        self.selettore = selettore
        self.impostazioni = impostazioni
        self._pagina_avanzamento = None
        self._ultimo = None

    def get_menu_items(self):
        try:
            voci = [("Riconosci un documento", self.scegli_documento, None)]
            if self.motore.in_corso:
                voci.append(("Riconoscimento in corso", self.apri_avanzamento, self._azioni_avanzamento))
            if self._ultimo is not None:
                voci.append(
                    (
                        f"Ultimo documento riconosciuto, {self._ultimo.titolo()}",
                        self.apri_ultimo,
                        partial(self._azioni_risultato, self._ultimo),
                    )
                )
            voci.append((f"Lingua del riconoscimento: {nome_lingua(self._lingua())}", self.scegli_lingua, None))
            voci.append(
                (
                    f"Analisi della pagina con rete neurale: {stato_scelta(self._attivo(CHIAVE_RETE_NEURALE, True))}",
                    self.alterna_rete_neurale,
                    None,
                )
            )
            voci.append(
                (
                    f"Segna le immagini nel testo: {stato_scelta(self._attivo(CHIAVE_SEGNA_IMMAGINI, True))}",
                    self.alterna_segna_immagini,
                    None,
                )
            )
            voci.append(
                (
                    f"Correggi le parole con il dizionario: {stato_scelta(self._attivo(CHIAVE_CORREGGI_PAROLE, True))}",
                    self.alterna_correggi_parole,
                    None,
                )
            )
            voci.append(
                (
                    f"Ignora il testo dei disegni: {stato_scelta(self._attivo(CHIAVE_IGNORA_DISEGNI, True))}",
                    self.alterna_ignora_disegni,
                    None,
                )
            )
            voci.append(
                (
                    f"Usa il testo già presente nei PDF: {stato_scelta(self._attivo(CHIAVE_USA_TESTO_PDF, True))}",
                    self.alterna_testo_pdf,
                    None,
                )
            )
            return voci
        except Exception as ex:
            scrivi_log("OcrView.get_menu_items", ex)
            return [("Riconosci un documento", self.scegli_documento, None)]

    def _attivo(self, chiave, predefinito):
        try:
            if self.impostazioni is None:
                return predefinito
            return self.impostazioni.attivo(chiave, predefinito)
        except Exception as ex:
            scrivi_log(f"OcrView._attivo ({chiave})", ex)
            return predefinito

    def _lingua_valida(self, codice, installate):
        try:
            parti = [parte for parte in str(codice).split("+") if parte]
            return bool(parti) and all(parte in installate for parte in parti)
        except Exception as ex:
            scrivi_log(f"OcrView._lingua_valida ({codice})", ex)
            return False

    def _lingua(self):
        try:
            installate = self.motore.lingue_disponibili()
            salvata = self.impostazioni.leggi(CHIAVE_LINGUA, "") if self.impostazioni is not None else ""
            if not installate:
                return salvata or LINGUA_PREDEFINITA
            if salvata and self._lingua_valida(salvata, installate):
                return salvata
            if LINGUA_PREDEFINITA in installate:
                return LINGUA_PREDEFINITA
            return installate[0]
        except Exception as ex:
            scrivi_log("OcrView._lingua", ex)
            return LINGUA_PREDEFINITA

    def _aggiorna_menu(self):
        try:
            self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
        except Exception as ex:
            scrivi_log("OcrView._aggiorna_menu", ex)

    def _alterna(self, chiave, predefinito):
        try:
            if self.impostazioni is None:
                self.finestra.mostra_messaggio(MESSAGGIO_NON_DISPONIBILI, ERRORE_LOG)
                return None
            nuovo = not self.impostazioni.attivo(chiave, predefinito)
            if not self.impostazioni.imposta_attivo(chiave, nuovo):
                self.finestra.mostra_messaggio("Impossibile salvare l'impostazione.", ERRORE_LOG)
                return None
            return nuovo
        except Exception as ex:
            scrivi_log(f"OcrView._alterna ({chiave})", ex)
            return None

    def alterna_ignora_disegni(self):
        try:
            nuovo = self._alterna(CHIAVE_IGNORA_DISEGNI, True)
            if nuovo is None:
                return
            self._aggiorna_menu()
            self.finestra.mostra_stato(f"Ignora il testo dei disegni: {stato_scelta(nuovo)}.")
        except Exception as ex:
            scrivi_log("OcrView.alterna_ignora_disegni", ex)

    def alterna_rete_neurale(self):
        try:
            nuovo = self._alterna(CHIAVE_RETE_NEURALE, True)
            if nuovo is None:
                return
            self._aggiorna_menu()
            self.finestra.mostra_stato(f"Analisi della pagina con rete neurale: {stato_scelta(nuovo)}.")
        except Exception as ex:
            scrivi_log("OcrView.alterna_rete_neurale", ex)

    def alterna_segna_immagini(self):
        try:
            nuovo = self._alterna(CHIAVE_SEGNA_IMMAGINI, True)
            if nuovo is None:
                return
            self._aggiorna_menu()
            self.finestra.mostra_stato(f"Segna le immagini nel testo: {stato_scelta(nuovo)}.")
        except Exception as ex:
            scrivi_log("OcrView.alterna_segna_immagini", ex)

    def alterna_correggi_parole(self):
        try:
            nuovo = self._alterna(CHIAVE_CORREGGI_PAROLE, True)
            if nuovo is None:
                return
            self._aggiorna_menu()
            self.finestra.mostra_stato(f"Correggi le parole con il dizionario: {stato_scelta(nuovo)}.")
        except Exception as ex:
            scrivi_log("OcrView.alterna_correggi_parole", ex)

    def alterna_testo_pdf(self):
        try:
            nuovo = self._alterna(CHIAVE_USA_TESTO_PDF, True)
            if nuovo is None:
                return
            self._aggiorna_menu()
            self.finestra.mostra_stato(f"Usa il testo già presente nei PDF: {stato_scelta(nuovo)}.")
        except Exception as ex:
            scrivi_log("OcrView.alterna_testo_pdf", ex)

    def _opzioni_lingua(self, installate):
        opzioni = []
        try:
            for codice in ("ita", "eng"):
                if codice in installate:
                    opzioni.append(codice)
            if "ita" in installate and "eng" in installate:
                opzioni.append("ita+eng")
            opzioni.extend(sorted(codice for codice in installate if codice not in ("ita", "eng")))
        except Exception as ex:
            scrivi_log("OcrView._opzioni_lingua", ex)
        return opzioni

    def scegli_lingua(self):
        try:
            installate = self.motore.lingue_disponibili(aggiorna=True)
            if not installate:
                self._avvisa_programmi_mancanti()
                return
            opzioni = self._opzioni_lingua(installate)
            etichette = [nome_lingua(codice) for codice in opzioni]
            scelta = self.finestra.chiedi_scelta(
                "Lingua del riconoscimento",
                etichette,
                "Scegliere la lingua in cui è scritto il documento.",
            )
            if scelta < 0 or scelta >= len(opzioni):
                return
            if self.impostazioni is None or not self.impostazioni.scrivi(CHIAVE_LINGUA, opzioni[scelta]):
                self.finestra.mostra_messaggio("Impossibile salvare la lingua.", ERRORE_LOG)
                return
            self._aggiorna_menu()
            self.finestra.mostra_stato(f"Lingua del riconoscimento: {etichette[scelta]}.")
        except Exception as ex:
            scrivi_log("OcrView.scegli_lingua", ex)

    def _avvisa_programmi_mancanti(self):
        try:
            mancanti = self.motore.programmi_mancanti()
            if mancanti:
                self.finestra.mostra_messaggio(
                    "Mancano alcuni programmi necessari al riconoscimento.",
                    f"Installare i pacchetti: {', '.join(mancanti)}, tesseract-ocr-ita.",
                )
            else:
                self.finestra.mostra_messaggio(
                    "Nessuna lingua di riconoscimento installata.",
                    "Installare il pacchetto tesseract-ocr-ita.",
                )
        except Exception as ex:
            scrivi_log("OcrView._avvisa_programmi_mancanti", ex)

    def scegli_documento(self):
        try:
            if self.motore.in_corso:
                self.finestra.mostra_messaggio("È già in corso un riconoscimento.")
                self.apri_avanzamento()
                return
            if self.motore.programmi_mancanti() or not self.motore.lingue_disponibili():
                self._avvisa_programmi_mancanti()
                return
            if self.selettore is None:
                self.finestra.mostra_messaggio("La scelta dei file non è disponibile.", ERRORE_LOG)
                return
            self.selettore.scegli_file(self._documento_scelto, ESTENSIONI_SUPPORTATE, TITOLO_SCELTA_FILE)
        except Exception as ex:
            scrivi_log("OcrView.scegli_documento", ex)

    def _documento_scelto(self, percorso):
        try:
            self.riconosci(Path(percorso))
        except Exception as ex:
            scrivi_log(f"OcrView._documento_scelto ({percorso})", ex)

    def riconosci(self, percorso):
        try:
            if self.motore.in_corso:
                self.finestra.mostra_messaggio("È già in corso un riconoscimento.")
                return
            lingua = self._lingua()
            opzioni = OpzioniOcr(
                ignora_disegni=self._attivo(CHIAVE_IGNORA_DISEGNI, True),
                usa_testo_pdf=self._attivo(CHIAVE_USA_TESTO_PDF, True),
                usa_rete_neurale=self._attivo(CHIAVE_RETE_NEURALE, True),
                segna_immagini=self._attivo(CHIAVE_SEGNA_IMMAGINI, True),
                correggi_parole=self._attivo(CHIAVE_CORREGGI_PAROLE, True),
            )
            pagina = PaginaProgresso(
                TITOLO_AVANZAMENTO,
                [f"Documento: {percorso.name}", f"Lingua: {nome_lingua(lingua)}"],
                self._azioni_avanzamento,
            )
            self._pagina_avanzamento = pagina
            self.finestra.mostra_pagina(pagina)
            threading.Thread(
                target=self._lavoro,
                args=(percorso, lingua, opzioni, pagina),
                name="RiconoscimentoTesto",
                daemon=True,
            ).start()
        except Exception as ex:
            scrivi_log(f"OcrView.riconosci ({percorso})", ex)
            self._pagina_avanzamento = None
            self.finestra.mostra_messaggio("Impossibile avviare il riconoscimento.", ERRORE_LOG)

    def _avanza(self, pagina, riga):
        try:
            self.finestra.aggiungi_riga_pagina(pagina, riga)
        except Exception as ex:
            scrivi_log("OcrView._avanza", ex)

    def _lavoro(self, percorso, lingua, opzioni, pagina):
        esito = None
        errore = None
        try:
            esito = self.motore.riconosci(percorso, lingua, opzioni, partial(self._avanza, pagina))
        except (ErroreOcr, OcrAnnullato) as ex:
            errore = ex
        except Exception as ex:
            scrivi_log(f"OcrView._lavoro ({percorso})", ex)
            errore = ex
        try:
            GLib.idle_add(self._concluso, percorso, lingua, esito, errore, pagina)
        except Exception as ex:
            scrivi_log(f"OcrView._lavoro consegna ({percorso})", ex)

    def _in_avanzamento(self, pagina):
        try:
            return self.finestra.in_pagina() and self.finestra.current_source is pagina
        except Exception as ex:
            scrivi_log("OcrView._in_avanzamento", ex)
            return False

    def _concluso(self, percorso, lingua, esito, errore, pagina):
        try:
            if self._pagina_avanzamento is pagina:
                self._pagina_avanzamento = None
            in_avanzamento = self._in_avanzamento(pagina)
            if in_avanzamento:
                self.finestra.go_back()
            if errore is not None:
                self._concluso_con_errore(percorso, errore, in_avanzamento)
                return False
            if esito is None or not esito.testo_completo():
                self._aggiorna_menu()
                self.finestra.mostra_messaggio(
                    "Nessun testo riconosciuto nel documento.",
                    "Provare con un'altra lingua oppure disattivare l'opzione che ignora il testo dei disegni.",
                )
                return False
            self._ultimo = RisultatoOcr(percorso, lingua, esito)
            testo_stato = (
                f"Riconoscimento terminato: {conta(esito.numero_parole(), 'parola', 'parole')} "
                f"in {conta(esito.numero_pagine(), 'pagina', 'pagine')}."
            )
            if in_avanzamento:
                self._mostra_risultato(self._ultimo)
                self.finestra.mostra_stato(testo_stato)
            else:
                self._aggiorna_menu()
                self.finestra.mostra_stato(f"{testo_stato} Documento: {percorso.name}.")
                self.finestra.notifica_operazione("Riconoscimento testo", f"Riconoscimento terminato: {percorso.name}.")
        except Exception as ex:
            scrivi_log(f"OcrView._concluso ({percorso})", ex)
        return False

    def _concluso_con_errore(self, percorso, errore, in_avanzamento):
        try:
            if isinstance(errore, OcrAnnullato):
                self._aggiorna_menu()
                self.finestra.mostra_stato("Riconoscimento annullato.")
                return
            dettaglio = str(errore) if isinstance(errore, ErroreOcr) else ERRORE_LOG
            self._aggiorna_menu()
            if not in_avanzamento:
                self.finestra.notifica_operazione("Riconoscimento testo", f"Riconoscimento non riuscito: {percorso.name}.")
            self.finestra.mostra_messaggio(f"Riconoscimento non riuscito: {percorso.name}.", dettaglio)
        except Exception as ex:
            scrivi_log(f"OcrView._concluso_con_errore ({percorso})", ex)

    def _azioni_avanzamento(self):
        try:
            return [("Annulla il riconoscimento", self.annulla, None)]
        except Exception as ex:
            scrivi_log("OcrView._azioni_avanzamento", ex)
            return []

    def apri_avanzamento(self):
        try:
            pagina = self._pagina_avanzamento
            if not self.motore.in_corso or pagina is None:
                self.finestra.mostra_messaggio("Nessun riconoscimento in corso.")
                return
            if self._in_avanzamento(pagina):
                return
            self.finestra.mostra_pagina(pagina)
        except Exception as ex:
            scrivi_log("OcrView.apri_avanzamento", ex)

    def annulla(self):
        try:
            if not self.motore.in_corso:
                self.finestra.mostra_messaggio("Nessun riconoscimento in corso.")
                return
            if not self.finestra.chiedi_conferma("Annullare il riconoscimento del documento?"):
                return
            if self.motore.annulla():
                self.finestra.mostra_stato("Annullamento del riconoscimento richiesto.")
            else:
                self.finestra.mostra_messaggio("Impossibile annullare il riconoscimento.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("OcrView.annulla", ex)

    def apri_ultimo(self):
        try:
            if self._ultimo is None:
                self.finestra.mostra_messaggio("Nessun documento riconosciuto.")
                return
            self._mostra_risultato(self._ultimo)
        except Exception as ex:
            scrivi_log("OcrView.apri_ultimo", ex)

    def _mostra_risultato(self, risultato):
        try:
            self.finestra.mostra_pagina(
                PaginaTesto(
                    f"Testo di {risultato.titolo()}",
                    risultato.esito.testo_completo(),
                    partial(self._azioni_risultato, risultato),
                )
            )
        except Exception as ex:
            scrivi_log("OcrView._mostra_risultato", ex)

    def _azioni_risultato(self, risultato):
        try:
            azioni = [
                ("Salva il testo in un file", partial(self.salva, risultato, None), None),
                ("Copia il testo negli appunti", partial(self.copia, risultato, None), None),
            ]
            if risultato.esito.numero_pagine() > 1:
                azioni.append(("Leggi per pagine", partial(self._passa_a_pagine, risultato, None), None))
            azioni.append(("Informazioni sul riconoscimento", partial(self.informazioni, risultato), None))
            return azioni
        except Exception as ex:
            scrivi_log("OcrView._azioni_risultato", ex)
            return []

    def informazioni(self, risultato):
        try:
            esito = risultato.esito
            righe = [
                f"Documento: {risultato.percorso.name}.",
                f"Lingua: {nome_lingua(risultato.lingua)}.",
                f"Pagine: {esito.numero_pagine()}.",
                f"Parole: {esito.numero_parole()}.",
            ]
            if esito.pagine_con_testo:
                righe.append(f"Pagine con testo già presente nel PDF: {esito.pagine_con_testo}.")
            if esito.pagine_con_rete:
                righe.append(f"Pagine analizzate con la rete neurale: {esito.pagine_con_rete}.")
            if esito.immagini_trovate:
                righe.append(f"Immagini trovate: {esito.immagini_trovate}.")
            if esito.tabelle_trovate:
                righe.append(f"Tabelle trovate: {esito.tabelle_trovate}.")
            if esito.parole_corrette:
                righe.append(f"Parole corrette con il dizionario: {esito.parole_corrette}.")
            for avviso in esito.avvisi:
                righe.append(avviso)
            self.finestra.mostra_messaggio("Informazioni sul riconoscimento", " ".join(righe))
        except Exception as ex:
            scrivi_log("OcrView.informazioni", ex)

    def _testo_da_salvare(self, risultato, indice):
        if indice is None:
            return risultato.esito.testo_completo(), risultato.percorso.stem
        return risultato.esito.testo_pagina(indice), f"{risultato.percorso.stem} - pagina {indice + 1}"

    def salva(self, risultato, indice):
        try:
            if self.selettore is None:
                self.finestra.mostra_messaggio("Il salvataggio dei file non è disponibile.", ERRORE_LOG)
                return
            testo, nome = self._testo_da_salvare(risultato, indice)
            self.selettore.salva_testo(testo, nome)
        except Exception as ex:
            scrivi_log(f"OcrView.salva ({indice})", ex)

    def copia(self, risultato, indice):
        try:
            testo, _nome = self._testo_da_salvare(risultato, indice)
            if self.finestra.copia_negli_appunti(testo):
                self.finestra.mostra_stato("Testo copiato negli appunti.")
            else:
                self.finestra.mostra_messaggio("Impossibile copiare il testo negli appunti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"OcrView.copia ({indice})", ex)

    def _passa_a_pagine(self, risultato, indice):
        try:
            if self.finestra.in_pagina():
                self.finestra.go_back()
            if indice is not None:
                self.finestra.menu_positions[risultato.titolo_pagine()] = indice
            if self.finestra.titolo_corrente() != risultato.titolo_pagine():
                self.apri_pagine(risultato)
        except Exception as ex:
            scrivi_log("OcrView._passa_a_pagine", ex)

    def apri_pagine(self, risultato):
        try:
            self.finestra.push_menu(
                risultato.titolo_pagine(),
                partial(self._voci_pagine, risultato),
                "Il documento non ha pagine.",
            )
        except Exception as ex:
            scrivi_log("OcrView.apri_pagine", ex)

    def _etichetta_pagina(self, risultato, indice):
        try:
            parole = risultato.esito.numero_parole(indice)
            if parole == 0:
                return f"Pagina {indice + 1}, senza testo"
            return f"Pagina {indice + 1}, {conta(parole, 'parola', 'parole')}"
        except Exception as ex:
            scrivi_log(f"OcrView._etichetta_pagina ({indice})", ex)
            return f"Pagina {indice + 1}"

    def _voci_pagine(self, risultato):
        voci = []
        try:
            for indice in range(risultato.esito.numero_pagine()):
                voci.append(
                    (
                        self._etichetta_pagina(risultato, indice),
                        partial(self.leggi_pagina, risultato, indice),
                        [
                            ("Leggi questa pagina", partial(self.leggi_pagina, risultato, indice), None),
                            ("Salva questa pagina in un file", partial(self.salva, risultato, indice), None),
                            ("Salva il testo intero in un file", partial(self.salva, risultato, None), None),
                        ],
                    )
                )
        except Exception as ex:
            scrivi_log("OcrView._voci_pagine", ex)
        return voci

    def leggi_pagina(self, risultato, indice):
        try:
            if not 0 <= indice < risultato.esito.numero_pagine():
                return
            testo = risultato.esito.testo_pagina(indice)
            if not testo:
                self.finestra.mostra_messaggio(f"La pagina {indice + 1} non contiene testo riconosciuto.")
                return
            self.finestra.menu_positions[risultato.titolo_pagine()] = indice
            self.finestra.mostra_pagina(
                PaginaTesto(
                    f"{risultato.titolo()}, pagina {indice + 1}",
                    testo,
                    partial(self._azioni_pagina, risultato, indice),
                )
            )
        except Exception as ex:
            scrivi_log(f"OcrView.leggi_pagina ({indice})", ex)

    def _cambia_pagina(self, risultato, indice):
        try:
            if self.finestra.in_pagina():
                self.finestra.go_back()
            self.leggi_pagina(risultato, indice)
        except Exception as ex:
            scrivi_log(f"OcrView._cambia_pagina ({indice})", ex)

    def _azioni_pagina(self, risultato, indice):
        try:
            azioni = [
                ("Salva questa pagina in un file", partial(self.salva, risultato, indice), None),
                ("Copia questa pagina negli appunti", partial(self.copia, risultato, indice), None),
            ]
            if indice + 1 < risultato.esito.numero_pagine():
                azioni.append((f"Pagina successiva: {indice + 2}", partial(self._cambia_pagina, risultato, indice + 1), None))
            if indice > 0:
                azioni.append((f"Pagina precedente: {indice}", partial(self._cambia_pagina, risultato, indice - 1), None))
            azioni.append(("Torna all'elenco delle pagine", partial(self._passa_a_pagine, risultato, indice), None))
            return azioni
        except Exception as ex:
            scrivi_log(f"OcrView._azioni_pagina ({indice})", ex)
            return []
