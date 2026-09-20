from datetime import date, datetime, time, timedelta
from functools import partial

from app.agenda.agenda_model import (
    FINE_DATA,
    FINE_MAI,
    FINE_VOLTE,
    FREQUENZA_ANNUALE,
    FREQUENZA_GIORNALIERA,
    FREQUENZA_MENSILE,
    FREQUENZA_NESSUNA,
    FREQUENZA_SETTIMANALE,
    GIORNI,
    NESSUNA_NOTIFICA,
    Evento,
    Occorrenza,
    data_breve,
    data_estesa,
    descrizione_avviso,
    descrizione_ricorrenza,
    leggi_data,
    leggi_ora,
    nome_mese,
    ora_breve,
    occorrenze_di,
    orario_occorrenza,
    prossima_occorrenza,
)
from app.core.log import scrivi_log
from app.ui.modulo_dialogo import TIPO_MULTIRIGA, TIPO_SCELTA, TIPO_SPUNTA, Campo

TITOLO_MENU = "Menu Agenda"
TITOLO_TUTTI = "Tutti gli appuntamenti"
FREQUENZA_FERIALI = "feriali"
SCELTE_FREQUENZA = [
    (FREQUENZA_NESSUNA, "Nessuna ripetizione"),
    (FREQUENZA_GIORNALIERA, "Ogni giorno"),
    (FREQUENZA_FERIALI, "Dal lunedì al venerdì"),
    (FREQUENZA_SETTIMANALE, "Ogni settimana"),
    (FREQUENZA_MENSILE, "Ogni mese"),
    (FREQUENZA_ANNUALE, "Ogni anno"),
]
SCELTE_FINE = [
    (FINE_MAI, "Senza fine"),
    (FINE_DATA, "Fino a una data"),
    (FINE_VOLTE, "Per un numero di volte"),
]
SCELTE_AVVISO = [
    ("-1", "Nessuna notifica"),
    ("0", "All'inizio dell'appuntamento"),
    ("5", "5 minuti prima"),
    ("10", "10 minuti prima"),
    ("15", "15 minuti prima"),
    ("30", "30 minuti prima"),
    ("60", "1 ora prima"),
    ("120", "2 ore prima"),
    ("1440", "1 giorno prima"),
    ("2880", "2 giorni prima"),
    ("10080", "1 settimana prima"),
]
ERRORE_LOG = "I dettagli sono nel file di log."
SCELTA_OCCORRENZA = 0
SCELTA_SERIE = 1


def appuntamenti(numero):
    try:
        if numero == 0:
            return "nessun appuntamento"
        return "1 appuntamento" if numero == 1 else f"{numero} appuntamenti"
    except Exception as ex:
        scrivi_log("agenda_view.appuntamenti", ex)
        return str(numero)


def _giorno_intero(giorno):
    return datetime.combine(giorno, time(0, 0))


class AgendaView:
    def __init__(self, finestra, store, notifier=None):
        self.finestra = finestra
        self.store = store
        self.notifier = notifier
        self._mese = None

    def _oggi(self):
        return date.today()

    def get_menu_items(self):
        try:
            oggi = self._oggi()
            domani = oggi + timedelta(days=1)
            voci = [
                ("Nuovo appuntamento", partial(self.aggiungi, None), None),
                (f"Appuntamenti di oggi: {appuntamenti(len(self.store.occorrenze_giorno(oggi)))}", partial(self.apri_giorno, oggi), None),
                (f"Appuntamenti di domani: {appuntamenti(len(self.store.occorrenze_giorno(domani)))}", partial(self.apri_giorno, domani), None),
                (f"Appuntamenti dei prossimi 7 giorni: {appuntamenti(len(self._periodo(oggi, 7)))}", partial(self.apri_periodo, 7), None),
                (f"Appuntamenti dei prossimi 30 giorni: {appuntamenti(len(self._periodo(oggi, 30)))}", partial(self.apri_periodo, 30), None),
                ("Appuntamenti di un altro giorno", self.chiedi_giorno, None),
                (f"Appuntamenti del mese di {nome_mese(oggi.year, oggi.month)}", partial(self.apri_mese, oggi.year, oggi.month), None),
                ("Cerca un appuntamento", self.cerca, None),
                (TITOLO_TUTTI, self.apri_tutti, None),
            ]
            return voci
        except Exception as ex:
            scrivi_log("AgendaView.get_menu_items", ex)
            return [("Nuovo appuntamento", partial(self.aggiungi, None), None)]

    def _periodo(self, giorno, giorni):
        try:
            inizio = datetime.now().replace(second=0, microsecond=0) if giorno == self._oggi() else _giorno_intero(giorno)
            return self.store.occorrenze(inizio, _giorno_intero(giorno) + timedelta(days=giorni))
        except Exception as ex:
            scrivi_log(f"AgendaView._periodo ({giorno}, {giorni})", ex)
            return []

    def _etichetta_occorrenza(self, occorrenza, con_data=False, giorno=None):
        try:
            parti = []
            if con_data:
                parti.append(data_estesa(occorrenza.inizio.date(), self._oggi()))
            orario = orario_occorrenza(occorrenza)
            if giorno is not None and occorrenza.piu_giorni and giorno != occorrenza.inizio.date():
                orario = f"{orario}, continua da {data_estesa(occorrenza.inizio.date(), self._oggi(), False)}"
            parti.append(orario)
            parti.append(occorrenza.evento.titolo or "Appuntamento senza titolo")
            if occorrenza.evento.luogo:
                parti.append(f"presso {occorrenza.evento.luogo}")
            if occorrenza.evento.ricorrente:
                parti.append(descrizione_ricorrenza(occorrenza.evento))
            return ", ".join(parte for parte in parti if parte)
        except Exception as ex:
            scrivi_log("AgendaView._etichetta_occorrenza", ex)
            return str(getattr(occorrenza.evento, "titolo", ""))

    def _voci_occorrenze(self, occorrenze, con_data=False, giorno=None, azioni_elenco=None):
        voci = []
        try:
            for occorrenza in occorrenze:
                voci.append(
                    (
                        self._etichetta_occorrenza(occorrenza, con_data, giorno),
                        partial(self.dettagli, occorrenza),
                        partial(self._azioni_voce_occorrenza, occorrenza, azioni_elenco),
                    )
                )
        except Exception as ex:
            scrivi_log("AgendaView._voci_occorrenze", ex)
        return voci

    def _azioni_evento(self, occorrenza):
        try:
            return [
                ("Modifica l'appuntamento", partial(self.modifica, occorrenza.evento.id), None),
                ("Duplica l'appuntamento", partial(self.duplica, occorrenza.evento.id), None),
                ("Elimina l'appuntamento", partial(self.elimina, occorrenza), None),
            ]
        except Exception as ex:
            scrivi_log("AgendaView._azioni_evento", ex)
            return []

    def _risolvi_azioni(self, azioni):
        try:
            if azioni is None:
                return []
            if callable(azioni):
                return list(azioni() or [])
            return list(azioni)
        except Exception as ex:
            scrivi_log("AgendaView._risolvi_azioni", ex)
            return []

    def _azioni_voce_occorrenza(self, occorrenza, azioni_elenco=None):
        try:
            azioni = [("Apri i dettagli", partial(self.dettagli, occorrenza), None)]
            azioni.extend(self._azioni_evento(occorrenza))
            aggiuntive = self._risolvi_azioni(azioni_elenco)
            if aggiuntive:
                azioni.extend(aggiuntive)
            else:
                azioni.append(("Nuovo appuntamento", partial(self.aggiungi, None), None))
            return azioni
        except Exception as ex:
            scrivi_log("AgendaView._azioni_voce_occorrenza", ex)
            return []

    def _titolo_giorno(self, giorno):
        return f"Appuntamenti di {data_estesa(giorno, self._oggi())}"

    def apri_giorno(self, giorno):
        try:
            self.finestra.push_menu(self._titolo_giorno(giorno), partial(self._voci_giorno, giorno))
        except Exception as ex:
            scrivi_log(f"AgendaView.apri_giorno ({giorno})", ex)

    def _vai_al_giorno(self, giorno):
        try:
            self.finestra.sostituisci_menu(self._titolo_giorno(giorno), partial(self._voci_giorno, giorno), 0)
        except Exception as ex:
            scrivi_log(f"AgendaView._vai_al_giorno ({giorno})", ex)

    def _chiedi_altro_giorno(self, giorno):
        try:
            testo = self.finestra.chiedi_testo(
                "Vai a un altro giorno",
                "Data da consultare (gg/mm/aaaa, oppure oggi, domani)",
                data_breve(giorno),
            )
            if not testo:
                return
            scelto = leggi_data(testo, self._oggi())
            if scelto is None:
                self.finestra.mostra_messaggio("La data non è valida.", "Scrivere la data nella forma giorno/mese/anno.")
                return
            self._vai_al_giorno(scelto)
        except Exception as ex:
            scrivi_log(f"AgendaView._chiedi_altro_giorno ({giorno})", ex)

    def _azioni_giorno(self, giorno):
        try:
            precedente = giorno - timedelta(days=1)
            successivo = giorno + timedelta(days=1)
            return [
                ("Nuovo appuntamento in questo giorno", partial(self.aggiungi, giorno), None),
                (f"Giorno successivo: {data_estesa(successivo, self._oggi())}", partial(self._vai_al_giorno, successivo), None),
                (f"Giorno precedente: {data_estesa(precedente, self._oggi())}", partial(self._vai_al_giorno, precedente), None),
                ("Vai a un altro giorno", partial(self._chiedi_altro_giorno, giorno), None),
                (f"Appuntamenti del mese di {nome_mese(giorno.year, giorno.month)}", partial(self.apri_mese, giorno.year, giorno.month), None),
            ]
        except Exception as ex:
            scrivi_log(f"AgendaView._azioni_giorno ({giorno})", ex)
            return []

    def _voci_giorno(self, giorno):
        voci = []
        try:
            occorrenze = self.store.occorrenze_giorno(giorno)
            voci = self._voci_occorrenze(occorrenze, giorno=giorno, azioni_elenco=partial(self._azioni_giorno, giorno))
            if not voci:
                etichetta = "Nessun appuntamento in questo giorno"
                azioni = partial(self._azioni_giorno, giorno)
                voci.append((etichetta, partial(self.finestra.apri_azioni, etichetta, azioni), azioni))
        except Exception as ex:
            scrivi_log(f"AgendaView._voci_giorno ({giorno})", ex)
        return voci

    def apri_periodo(self, giorni):
        try:
            oggi = self._oggi()
            self.finestra.push_menu(
                f"Appuntamenti dei prossimi {giorni} giorni",
                lambda: self._voci_occorrenze(self._periodo(oggi, giorni), con_data=True),
                f"Nessun appuntamento nei prossimi {giorni} giorni.",
            )
        except Exception as ex:
            scrivi_log(f"AgendaView.apri_periodo ({giorni})", ex)

    def chiedi_giorno(self):
        try:
            testo = self.finestra.chiedi_testo(
                "Appuntamenti di un altro giorno",
                "Data da consultare (gg/mm/aaaa, oppure oggi, domani)",
                data_breve(self._oggi()),
            )
            if not testo:
                return
            giorno = leggi_data(testo, self._oggi())
            if giorno is None:
                self.finestra.mostra_messaggio("La data non è valida.", "Scrivere la data nella forma giorno/mese/anno.")
                return
            self.apri_giorno(giorno)
        except Exception as ex:
            scrivi_log("AgendaView.chiedi_giorno", ex)

    def _titolo_mese(self, anno, mese):
        return f"Agenda di {nome_mese(anno, mese)}"

    def apri_mese(self, anno, mese):
        try:
            self.finestra.push_menu(self._titolo_mese(anno, mese), partial(self._voci_mese, anno, mese))
        except Exception as ex:
            scrivi_log(f"AgendaView.apri_mese ({anno}, {mese})", ex)

    def _vai_al_mese(self, anno, mese):
        try:
            self.finestra.sostituisci_menu(self._titolo_mese(anno, mese), partial(self._voci_mese, anno, mese), 0)
        except Exception as ex:
            scrivi_log(f"AgendaView._vai_al_mese ({anno}, {mese})", ex)

    def _azioni_mese(self, anno, mese):
        try:
            anno_successivo, mese_successivo = (anno + 1, 1) if mese == 12 else (anno, mese + 1)
            anno_precedente, mese_precedente = (anno - 1, 12) if mese == 1 else (anno, mese - 1)
            return [
                (
                    f"Mese successivo: {nome_mese(anno_successivo, mese_successivo)}",
                    partial(self._vai_al_mese, anno_successivo, mese_successivo),
                    None,
                ),
                (
                    f"Mese precedente: {nome_mese(anno_precedente, mese_precedente)}",
                    partial(self._vai_al_mese, anno_precedente, mese_precedente),
                    None,
                ),
                ("Nuovo appuntamento", partial(self.aggiungi, None), None),
            ]
        except Exception as ex:
            scrivi_log(f"AgendaView._azioni_mese ({anno}, {mese})", ex)
            return []

    def _azioni_giorno_del_mese(self, giorno):
        try:
            azioni = [
                ("Apri il giorno", partial(self.apri_giorno, giorno), None),
                ("Nuovo appuntamento in questo giorno", partial(self.aggiungi, giorno), None),
            ]
            azioni.extend(
                voce for voce in self._azioni_mese(giorno.year, giorno.month) if not voce[0].startswith("Nuovo")
            )
            return azioni
        except Exception as ex:
            scrivi_log(f"AgendaView._azioni_giorno_del_mese ({giorno})", ex)
            return []

    def _voci_mese(self, anno, mese):
        voci = []
        try:
            conteggi = self.store.conteggi_mese(anno, mese)
            for giorno in sorted(conteggi):
                voci.append(
                    (
                        f"{data_estesa(giorno, self._oggi())}: {appuntamenti(conteggi[giorno])}",
                        partial(self.apri_giorno, giorno),
                        partial(self._azioni_giorno_del_mese, giorno),
                    )
                )
            if not voci:
                etichetta = "Nessun appuntamento in questo mese"
                azioni = partial(self._azioni_mese, anno, mese)
                voci.append((etichetta, partial(self.finestra.apri_azioni, etichetta, azioni), azioni))
        except Exception as ex:
            scrivi_log(f"AgendaView._voci_mese ({anno}, {mese})", ex)
        return voci

    def cerca(self):
        try:
            testo = self.finestra.chiedi_testo("Cerca un appuntamento", "Testo da cercare nel titolo, nel luogo o nelle note")
            if not testo:
                return
            self.finestra.push_menu(
                f"Appuntamenti trovati per {testo}",
                lambda: self._voci_eventi(self.store.cerca(testo)),
                "Nessun appuntamento trovato.",
            )
        except Exception as ex:
            scrivi_log("AgendaView.cerca", ex)

    def apri_tutti(self):
        try:
            self.finestra.push_menu(
                TITOLO_TUTTI,
                lambda: self._voci_eventi([evento for evento, _prossima in self.store.eventi_ordinati()]),
                "L'agenda è vuota.",
            )
        except Exception as ex:
            scrivi_log("AgendaView.apri_tutti", ex)

    def _voci_eventi(self, eventi):
        voci = []
        try:
            adesso = datetime.now()
            for evento in eventi:
                prossima = prossima_occorrenza(evento, adesso)
                occorrenza = prossima if prossima is not None else Occorrenza(evento, evento.inizio, evento.fine)
                parti = [evento.titolo or "Appuntamento senza titolo"]
                if prossima is not None:
                    parti.append(f"{data_estesa(prossima.inizio.date(), self._oggi())}, {orario_occorrenza(prossima)}")
                else:
                    parti.append(f"concluso, {data_breve(evento.inizio.date())}")
                if evento.ricorrente:
                    parti.append(descrizione_ricorrenza(evento))
                voci.append(
                    (
                        ", ".join(parti),
                        partial(self.dettagli, occorrenza),
                        partial(self._azioni_voce_occorrenza, occorrenza, None),
                    )
                )
        except Exception as ex:
            scrivi_log("AgendaView._voci_eventi", ex)
        return voci

    def _titolo_dettagli(self, evento):
        return f"Appuntamento {evento.titolo or 'senza titolo'}"

    def _occorrenza_attuale(self, identificativo, inizio_precedente):
        try:
            evento = self.store.evento(identificativo)
            if evento is None:
                return None
            if not evento.ricorrente:
                if inizio_precedente.date() in evento.esclusioni:
                    return None
                return Occorrenza(evento, evento.inizio, evento.fine)
            giorno = inizio_precedente.date()
            for occorrenza in occorrenze_di([evento], _giorno_intero(giorno), _giorno_intero(giorno) + timedelta(days=1)):
                if occorrenza.inizio.date() == giorno:
                    return occorrenza
            return None
        except Exception as ex:
            scrivi_log(f"AgendaView._occorrenza_attuale ({identificativo})", ex)
            return None

    def dettagli(self, occorrenza):
        try:
            attuale = self._occorrenza_attuale(occorrenza.evento.id, occorrenza.inizio) or occorrenza
            self.finestra.push_menu(
                self._titolo_dettagli(attuale.evento),
                partial(self._voci_dettagli, occorrenza.evento.id, occorrenza.inizio),
                "L'appuntamento non esiste più.",
            )
        except Exception as ex:
            scrivi_log("AgendaView.dettagli", ex)

    def _righe_dettagli(self, occorrenza):
        righe = []
        try:
            evento = occorrenza.evento
            righe.append(("Titolo", evento.titolo or "senza titolo"))
            righe.append(("Quando", f"{data_estesa(occorrenza.inizio.date(), self._oggi())}, {orario_occorrenza(occorrenza)}"))
            if evento.luogo:
                righe.append(("Luogo", evento.luogo))
            if evento.ricorrente:
                righe.append(("Ripetizione", descrizione_ricorrenza(evento)))
                righe.append(("Primo appuntamento della serie", data_breve(evento.inizio.date())))
            righe.append(("Notifica", descrizione_avviso(evento.avviso_minuti)))
            if evento.esclusioni:
                righe.append(("Giorni esclusi", ", ".join(data_breve(giorno) for giorno in sorted(evento.esclusioni))))
            if evento.note:
                for posizione, riga in enumerate(riga for riga in evento.note.splitlines() if riga.strip()):
                    righe.append(("Note" if posizione == 0 else "", riga.strip()))
        except Exception as ex:
            scrivi_log("AgendaView._righe_dettagli", ex)
        return righe

    def _voci_dettagli(self, identificativo, inizio_precedente):
        voci = []
        try:
            occorrenza = self._occorrenza_attuale(identificativo, inizio_precedente)
            if occorrenza is None:
                return voci
            for nome, valore in self._righe_dettagli(occorrenza):
                etichetta = f"{nome}: {valore}" if nome else valore
                azioni = partial(self._azioni_dettaglio, occorrenza, valore)
                voci.append((etichetta, partial(self.finestra.apri_azioni, etichetta, azioni), azioni))
        except Exception as ex:
            scrivi_log(f"AgendaView._voci_dettagli ({identificativo})", ex)
        return voci

    def _azioni_dettaglio(self, occorrenza, valore):
        try:
            azioni = self._azioni_evento(occorrenza)
            azioni.append(("Copia questa informazione", partial(self.copia, valore), None))
            azioni.append(
                (
                    f"Nuovo appuntamento per {data_estesa(occorrenza.inizio.date(), self._oggi())}",
                    partial(self.aggiungi, occorrenza.inizio.date()),
                    None,
                )
            )
            return azioni
        except Exception as ex:
            scrivi_log("AgendaView._azioni_dettaglio", ex)
            return []

    def copia(self, testo):
        try:
            if self.finestra.copia_negli_appunti(testo):
                self.finestra.mostra_stato("Informazione copiata.")
            else:
                self.finestra.mostra_messaggio("Impossibile copiare negli appunti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("AgendaView.copia", ex)

    def _campi(self, evento):
        try:
            frequenza = evento.frequenza
            if frequenza == FREQUENZA_SETTIMANALE and sorted(set(evento.giorni_settimana)) == [0, 1, 2, 3, 4] and evento.intervallo == 1:
                frequenza = FREQUENZA_FERIALI
            giorni_scelti = set(evento.giorni_settimana or [evento.inizio.weekday()])
            ricorrente = lambda valori: valori.get("frequenza") != FREQUENZA_NESSUNA
            orario = lambda valori: not valori.get("tutto_il_giorno")
            campi = [
                Campo("titolo", "Titolo", valore=evento.titolo),
                Campo("luogo", "Luogo", valore=evento.luogo),
                Campo("data_inizio", "Data di inizio", valore=data_breve(evento.inizio.date()), suggerimento="gg/mm/aaaa"),
                Campo("tutto_il_giorno", "Tutto il giorno", TIPO_SPUNTA, evento.tutto_il_giorno),
                Campo("ora_inizio", "Ora di inizio", valore=ora_breve(evento.inizio.time()), attivo_se=orario, suggerimento="hh:mm"),
                Campo("data_fine", "Data di fine", valore=data_breve(evento.ultimo_giorno), suggerimento="gg/mm/aaaa"),
                Campo("ora_fine", "Ora di fine", valore=ora_breve(evento.fine.time()), attivo_se=orario, suggerimento="hh:mm"),
                Campo("frequenza", "Ripetizione", TIPO_SCELTA, frequenza, SCELTE_FREQUENZA),
                Campo(
                    "intervallo",
                    "Ogni quanti giorni, settimane, mesi o anni",
                    valore=str(max(1, evento.intervallo)),
                    attivo_se=lambda valori: valori.get("frequenza") in (FREQUENZA_GIORNALIERA, FREQUENZA_SETTIMANALE, FREQUENZA_MENSILE, FREQUENZA_ANNUALE),
                ),
            ]
            for posizione, nome in enumerate(GIORNI):
                campi.append(
                    Campo(
                        f"giorno_{posizione}",
                        f"Si ripete di {nome}",
                        TIPO_SPUNTA,
                        posizione in giorni_scelti,
                        attivo_se=lambda valori: valori.get("frequenza") == FREQUENZA_SETTIMANALE,
                    )
                )
            campi.extend(
                [
                    Campo("fine_ripetizione", "Fine della ripetizione", TIPO_SCELTA, evento.fine_ripetizione, SCELTE_FINE, attivo_se=ricorrente),
                    Campo(
                        "ripeti_fino",
                        "Ripeti fino al",
                        valore=data_breve(evento.ripeti_fino) if evento.ripeti_fino else "",
                        suggerimento="gg/mm/aaaa",
                        attivo_se=lambda valori: ricorrente(valori) and valori.get("fine_ripetizione") == FINE_DATA,
                    ),
                    Campo(
                        "ripeti_volte",
                        "Numero di volte",
                        valore=str(evento.ripeti_volte) if evento.ripeti_volte else "",
                        attivo_se=lambda valori: ricorrente(valori) and valori.get("fine_ripetizione") == FINE_VOLTE,
                    ),
                    Campo("avviso", "Notifica", TIPO_SCELTA, str(evento.avviso_minuti), SCELTE_AVVISO),
                    Campo("note", "Note", TIPO_MULTIRIGA, evento.note),
                ]
            )
            return campi
        except Exception as ex:
            scrivi_log("AgendaView._campi", ex)
            return []

    def _evento_da_valori(self, valori, evento):
        oggi = self._oggi()
        titolo = valori.get("titolo", "").strip()
        if not titolo:
            return None, ("Scrivere il titolo dell'appuntamento.", "titolo")
        data_inizio = leggi_data(valori.get("data_inizio"), oggi)
        if data_inizio is None:
            return None, ("La data di inizio non è valida.", "data_inizio")
        testo_fine = valori.get("data_fine", "").strip()
        data_fine = leggi_data(testo_fine, oggi) if testo_fine else data_inizio
        if data_fine is None:
            return None, ("La data di fine non è valida.", "data_fine")
        tutto_il_giorno = bool(valori.get("tutto_il_giorno"))
        data_fine_invariata = testo_fine == data_breve(evento.ultimo_giorno)
        if tutto_il_giorno:
            inizio = _giorno_intero(data_inizio)
            if data_fine_invariata and evento.tutto_il_giorno and data_inizio != evento.inizio.date():
                fine = inizio + max(timedelta(days=1), evento.durata)
            else:
                if data_fine < data_inizio:
                    return None, ("La data di fine precede la data di inizio.", "data_fine")
                fine = _giorno_intero(data_fine) + timedelta(days=1)
        else:
            ora_inizio = leggi_ora(valori.get("ora_inizio"))
            if ora_inizio is None:
                return None, ("L'ora di inizio non è valida.", "ora_inizio")
            testo_ora_fine = valori.get("ora_fine", "").strip()
            ora_fine = leggi_ora(testo_ora_fine) if testo_ora_fine else ora_inizio
            if ora_fine is None:
                return None, ("L'ora di fine non è valida.", "ora_fine")
            inizio = datetime.combine(data_inizio, ora_inizio)
            fine = datetime.combine(data_fine, ora_fine)
            ora_fine_invariata = testo_ora_fine == ora_breve(evento.fine.time())
            if data_fine_invariata and ora_fine_invariata and not evento.tutto_il_giorno and inizio != evento.inizio:
                fine = inizio + evento.durata
            if fine < inizio:
                return None, ("La fine dell'appuntamento precede l'inizio.", "ora_fine")
        frequenza = valori.get("frequenza") or FREQUENZA_NESSUNA
        giorni = [posizione for posizione in range(7) if valori.get(f"giorno_{posizione}")]
        intervallo_testo = valori.get("intervallo", "").strip() or "1"
        if frequenza in (FREQUENZA_GIORNALIERA, FREQUENZA_SETTIMANALE, FREQUENZA_MENSILE, FREQUENZA_ANNUALE):
            if not intervallo_testo.isdigit() or int(intervallo_testo) < 1:
                return None, ("L'intervallo di ripetizione deve essere un numero intero maggiore di zero.", "intervallo")
        intervallo = int(intervallo_testo) if intervallo_testo.isdigit() and int(intervallo_testo) > 0 else 1
        if frequenza == FREQUENZA_FERIALI:
            frequenza = FREQUENZA_SETTIMANALE
            giorni = [0, 1, 2, 3, 4]
            intervallo = 1
        if frequenza == FREQUENZA_SETTIMANALE and not giorni:
            giorni = [data_inizio.weekday()]
        fine_ripetizione = valori.get("fine_ripetizione") or FINE_MAI
        ripeti_fino = None
        ripeti_volte = 0
        if frequenza != FREQUENZA_NESSUNA:
            if fine_ripetizione == FINE_DATA:
                ripeti_fino = leggi_data(valori.get("ripeti_fino"), oggi)
                if ripeti_fino is None:
                    return None, ("La data di fine della ripetizione non è valida.", "ripeti_fino")
                if ripeti_fino < data_inizio:
                    return None, ("La ripetizione termina prima dell'inizio.", "ripeti_fino")
            elif fine_ripetizione == FINE_VOLTE:
                testo_volte = valori.get("ripeti_volte", "").strip()
                if not testo_volte.isdigit() or int(testo_volte) < 1:
                    return None, ("Il numero di volte deve essere un numero intero maggiore di zero.", "ripeti_volte")
                ripeti_volte = int(testo_volte)
        else:
            fine_ripetizione = FINE_MAI
        try:
            avviso = int(valori.get("avviso", "15"))
        except Exception as ex:
            scrivi_log("AgendaView._evento_da_valori avviso", ex)
            avviso = NESSUNA_NOTIFICA
        nuovo = Evento(
            id=evento.id,
            titolo=titolo,
            luogo=valori.get("luogo", "").strip(),
            note=valori.get("note", "").strip(),
            inizio=inizio,
            fine=fine,
            tutto_il_giorno=tutto_il_giorno,
            frequenza=frequenza,
            intervallo=intervallo,
            giorni_settimana=giorni if frequenza == FREQUENZA_SETTIMANALE else [],
            fine_ripetizione=fine_ripetizione,
            ripeti_fino=ripeti_fino,
            ripeti_volte=ripeti_volte,
            avviso_minuti=avviso,
            esclusioni=set(evento.esclusioni) if frequenza != FREQUENZA_NESSUNA else set(),
        )
        return nuovo, None

    def _chiedi_evento(self, titolo_modulo, evento):
        try:
            risultato = {}

            def convalida(valori):
                nuovo, errore = self._evento_da_valori(valori, evento)
                if errore:
                    return errore
                risultato["evento"] = nuovo
                return None

            valori = self.finestra.chiedi_modulo(titolo_modulo, self._campi(evento), convalida)
            if valori is None:
                return None
            if "evento" not in risultato:
                nuovo, errore = self._evento_da_valori(valori, evento)
                if errore:
                    self.finestra.mostra_messaggio(errore[0])
                    return None
                return nuovo
            return risultato["evento"]
        except Exception as ex:
            scrivi_log(f"AgendaView._chiedi_evento ({titolo_modulo})", ex)
            return None

    def _dopo_modifica(self, messaggio, evento=None):
        try:
            if self.notifier is not None:
                self.notifier.controlla_ora()
            titolo = self.finestra.titolo_corrente()
            sorgente = self.finestra.current_source
            if evento is not None and titolo.startswith("Appuntamento ") and callable(sorgente):
                if not sorgente():
                    self.finestra.go_back()
                    self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
                elif titolo != self._titolo_dettagli(evento):
                    self.finestra.sostituisci_menu(self._titolo_dettagli(evento), sorgente, self.finestra.get_current_selected_index())
                else:
                    self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            else:
                self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            self.finestra.mostra_stato(messaggio)
        except Exception as ex:
            scrivi_log("AgendaView._dopo_modifica", ex)

    def aggiungi(self, giorno=None):
        try:
            adesso = datetime.now().replace(second=0, microsecond=0)
            ora = (adesso + timedelta(hours=1)).replace(minute=0)
            giorno_scelto = giorno or ora.date()
            inizio = datetime.combine(giorno_scelto, ora.time())
            evento = Evento(inizio=inizio, fine=inizio + timedelta(hours=1))
            nuovo = self._chiedi_evento("Nuovo appuntamento", evento)
            if nuovo is None:
                return
            if not self.store.aggiungi(nuovo):
                self.finestra.mostra_messaggio("Impossibile salvare l'appuntamento.", ERRORE_LOG)
                return
            self._dopo_modifica(
                f"Appuntamento aggiunto: {nuovo.titolo}, {data_estesa(nuovo.inizio.date(), self._oggi())}."
            )
        except Exception as ex:
            scrivi_log("AgendaView.aggiungi", ex)

    def aggiungi_evento(self, evento):
        try:
            if not self.store.aggiungi(evento):
                return False
            if self.notifier is not None:
                self.notifier.controlla_ora()
            return True
        except Exception as ex:
            scrivi_log("AgendaView.aggiungi_evento", ex)
            return False

    def modifica(self, identificativo):
        try:
            evento = self.store.evento(identificativo)
            if evento is None:
                self.finestra.mostra_messaggio("L'appuntamento non esiste più.")
                return
            titolo = "Modifica la serie di appuntamenti" if evento.ricorrente else "Modifica l'appuntamento"
            nuovo = self._chiedi_evento(titolo, evento)
            if nuovo is None:
                return
            if not self.store.aggiorna(nuovo):
                self.finestra.mostra_messaggio("Impossibile salvare le modifiche.", ERRORE_LOG)
                return
            self._dopo_modifica(f"Appuntamento modificato: {nuovo.titolo}.", nuovo)
        except Exception as ex:
            scrivi_log(f"AgendaView.modifica ({identificativo})", ex)

    def duplica(self, identificativo):
        try:
            evento = self.store.evento(identificativo)
            if evento is None:
                self.finestra.mostra_messaggio("L'appuntamento non esiste più.")
                return
            evento.id = 0
            evento.esclusioni = set()
            nuovo = self._chiedi_evento("Duplica l'appuntamento", evento)
            if nuovo is None:
                return
            nuovo.id = 0
            if not self.store.aggiungi(nuovo):
                self.finestra.mostra_messaggio("Impossibile salvare l'appuntamento.", ERRORE_LOG)
                return
            self._dopo_modifica(f"Appuntamento aggiunto: {nuovo.titolo}.")
        except Exception as ex:
            scrivi_log(f"AgendaView.duplica ({identificativo})", ex)

    def elimina(self, occorrenza):
        try:
            evento = occorrenza.evento
            if evento.ricorrente:
                scelta = self.finestra.chiedi_scelta(
                    f"Eliminare l'appuntamento {evento.titolo}?",
                    ["Solo questa volta", "Tutta la serie"],
                    f"L'appuntamento si ripete {descrizione_ricorrenza(evento)}.",
                )
                if scelta == SCELTA_OCCORRENZA:
                    esito = self.store.escludi_giorno(evento.id, occorrenza.inizio.date())
                    messaggio = f"Eliminato l'appuntamento di {data_estesa(occorrenza.inizio.date(), self._oggi())}."
                elif scelta == SCELTA_SERIE:
                    esito = self.store.elimina(evento.id)
                    messaggio = "Serie di appuntamenti eliminata."
                else:
                    return
            else:
                if not self.finestra.chiedi_conferma(f"Eliminare l'appuntamento {evento.titolo}?"):
                    return
                esito = self.store.elimina(evento.id)
                messaggio = "Appuntamento eliminato."
            if not esito:
                self.finestra.mostra_messaggio("Impossibile eliminare l'appuntamento.", ERRORE_LOG)
                return
            if self.finestra.titolo_corrente() == self._titolo_dettagli(evento):
                self.finestra.go_back()
            self._dopo_modifica(messaggio)
        except Exception as ex:
            scrivi_log("AgendaView.elimina", ex)

    def apri_notificate(self):
        try:
            self.apri_giorno(self._oggi())
        except Exception as ex:
            scrivi_log("AgendaView.apri_notificate", ex)
