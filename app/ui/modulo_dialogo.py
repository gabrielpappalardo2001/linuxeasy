from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Atk, Gdk, Gtk

from app.core.log import scrivi_log
from app.ui.messaggi import mostra_avviso

TIPO_TESTO = "testo"
TIPO_MULTIRIGA = "multiriga"
TIPO_SPUNTA = "spunta"
TIPO_SCELTA = "scelta"
NOME_PROGRAMMA = "LinuxEasy"
LARGHEZZA = 560
ALTEZZA_MASSIMA = 560
ISTRUZIONI_MODULO = (
    "Invio passa al campo seguente e nell'ultimo campo salva tutto. "
    "Maiusc+Invio torna al campo precedente. "
    "Le frecce su e giù cambiano campo, tranne nelle caselle a scelta dove cambiano il valore. "
    "Escape annulla."
)
ISTRUZIONI_CAMPO_SINGOLO = "Invio conferma, Escape annulla."
TASTI_INVIO = ("Return", "KP_Enter", "ISO_Enter")
TASTI_SU = ("Up", "KP_Up")
TASTI_GIU = ("Down", "KP_Down")
TASTI_LATERALI = ("Left", "Right", "KP_Left", "KP_Right")
RISPOSTA_SALVA = Gtk.ResponseType.OK
RISPOSTA_ANNULLA = Gtk.ResponseType.CANCEL


@dataclass
class Campo:
    chiave: str
    etichetta: str
    tipo: str = TIPO_TESTO
    valore: object = ""
    scelte: List[Tuple[str, str]] = field(default_factory=list)
    attivo_se: Optional[Callable] = None
    suggerimento: str = ""


class ModuloDialogo:
    def __init__(self, finestra, titolo, campi, convalida=None):
        self.finestra = finestra
        self.titolo = titolo
        self.campi = list(campi)
        self.convalida = convalida
        self._widget = {}
        self._etichette = {}
        self._dialogo = None

    def _valore_widget(self, campo):
        try:
            widget = self._widget.get(campo.chiave)
            if widget is None:
                return campo.valore
            if campo.tipo == TIPO_SPUNTA:
                return bool(widget.get_active())
            if campo.tipo == TIPO_SCELTA:
                return widget.get_active_id() or ""
            if campo.tipo == TIPO_MULTIRIGA:
                buffer = widget.get_buffer()
                return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()
            return widget.get_text().strip()
        except Exception as ex:
            scrivi_log(f"ModuloDialogo._valore_widget ({campo.chiave})", ex)
            return campo.valore

    def valori(self):
        try:
            return {campo.chiave: self._valore_widget(campo) for campo in self.campi}
        except Exception as ex:
            scrivi_log("ModuloDialogo.valori", ex)
            return {}

    def _aggiorna_dipendenze(self, *_argomenti):
        try:
            valori = self.valori()
            for campo in self.campi:
                if campo.attivo_se is None:
                    continue
                try:
                    attivo = bool(campo.attivo_se(valori))
                except Exception as ex:
                    scrivi_log(f"ModuloDialogo._aggiorna_dipendenze regola ({campo.chiave})", ex)
                    attivo = True
                widget = self._widget.get(campo.chiave)
                if widget is not None:
                    contenitore = widget.get_parent() if campo.tipo == TIPO_MULTIRIGA else widget
                    contenitore.set_sensitive(attivo)
                    widget.set_sensitive(attivo)
                etichetta = self._etichette.get(campo.chiave)
                if etichetta is not None:
                    etichetta.set_sensitive(attivo)
        except Exception as ex:
            scrivi_log("ModuloDialogo._aggiorna_dipendenze", ex)

    def _collega_etichetta(self, etichetta, widget, testo):
        try:
            etichetta.set_mnemonic_widget(widget)
            accessibile = widget.get_accessible()
            accessibile_etichetta = etichetta.get_accessible()
            if accessibile is not None:
                accessibile.set_name(testo)
                if accessibile_etichetta is not None:
                    accessibile.add_relationship(Atk.RelationType.LABELLED_BY, accessibile_etichetta)
                    accessibile_etichetta.add_relationship(Atk.RelationType.LABEL_FOR, accessibile)
        except Exception as ex:
            scrivi_log(f"ModuloDialogo._collega_etichetta ({testo})", ex)

    def _crea_widget(self, campo):
        if campo.tipo == TIPO_SPUNTA:
            widget = Gtk.CheckButton.new_with_label(campo.etichetta)
            widget.set_active(bool(campo.valore))
            widget.connect("toggled", self._aggiorna_dipendenze)
            return widget, widget
        if campo.tipo == TIPO_SCELTA:
            widget = Gtk.ComboBoxText()
            for identificativo, testo in campo.scelte:
                widget.append(str(identificativo), testo)
            if not widget.set_active_id(str(campo.valore)) and campo.scelte:
                widget.set_active(0)
            widget.connect("changed", self._aggiorna_dipendenze)
            return widget, widget
        if campo.tipo == TIPO_MULTIRIGA:
            vista = Gtk.TextView()
            vista.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            vista.set_accepts_tab(False)
            vista.get_buffer().set_text(str(campo.valore or ""))
            contenitore = Gtk.ScrolledWindow()
            contenitore.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            contenitore.set_shadow_type(Gtk.ShadowType.IN)
            contenitore.set_size_request(-1, 90)
            contenitore.add(vista)
            return vista, contenitore
        widget = Gtk.Entry()
        widget.set_text(str(campo.valore or ""))
        if campo.suggerimento:
            widget.set_placeholder_text(campo.suggerimento)
        widget.connect("changed", self._aggiorna_dipendenze)
        return widget, widget

    def _testo_istruzioni(self):
        try:
            return ISTRUZIONI_CAMPO_SINGOLO if len(self.campi) == 1 else ISTRUZIONI_MODULO
        except Exception as ex:
            scrivi_log("ModuloDialogo._testo_istruzioni", ex)
            return ISTRUZIONI_MODULO

    def _costruisci(self):
        dialogo = Gtk.Dialog(title=f"{self.titolo} - {NOME_PROGRAMMA}", transient_for=self.finestra, modal=True)
        area_pulsanti = dialogo.get_action_area()
        if area_pulsanti is not None:
            area_pulsanti.set_no_show_all(True)
            area_pulsanti.hide()
        dialogo.set_default_size(LARGHEZZA, -1)
        griglia = Gtk.Grid(column_spacing=12, row_spacing=8)
        griglia.set_border_width(12)
        for riga, campo in enumerate(self.campi):
            widget, contenitore = self._crea_widget(campo)
            self._widget[campo.chiave] = widget
            if campo.tipo == TIPO_SPUNTA:
                griglia.attach(contenitore, 0, riga, 2, 1)
                continue
            testo = f"{campo.etichetta} ({campo.suggerimento})" if campo.suggerimento else campo.etichetta
            etichetta = Gtk.Label.new_with_mnemonic(testo.replace("_", "__"))
            etichetta.set_xalign(0)
            etichetta.set_line_wrap(True)
            self._etichette[campo.chiave] = etichetta
            self._collega_etichetta(etichetta, widget, testo)
            contenitore.set_hexpand(True)
            griglia.attach(etichetta, 0, riga, 1, 1)
            griglia.attach(contenitore, 1, riga, 1, 1)
        scorrimento = Gtk.ScrolledWindow()
        scorrimento.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scorrimento.set_propagate_natural_height(True)
        scorrimento.set_max_content_height(ALTEZZA_MASSIMA)
        scorrimento.add(griglia)
        griglia.set_focus_vadjustment(scorrimento.get_vadjustment())
        istruzioni = Gtk.Label(label=self._testo_istruzioni())
        istruzioni.set_xalign(0)
        istruzioni.set_line_wrap(True)
        istruzioni.set_margin_start(12)
        istruzioni.set_margin_end(12)
        istruzioni.set_margin_top(8)
        dialogo.get_content_area().pack_start(istruzioni, False, False, 0)
        dialogo.get_content_area().pack_start(scorrimento, True, True, 0)
        dialogo.connect("key-press-event", self._tasto)
        self._dialogo = dialogo
        self._aggiorna_dipendenze()
        return dialogo

    def _ordine_fuoco(self):
        elenco = []
        try:
            for campo in self.campi:
                widget = self._widget.get(campo.chiave)
                if widget is not None and widget.get_sensitive() and widget.get_visible():
                    elenco.append(widget)
        except Exception as ex:
            scrivi_log("ModuloDialogo._ordine_fuoco", ex)
        return elenco

    def _posizione_fuoco(self, elenco, fuoco):
        try:
            if fuoco is None:
                return -1
            for posizione, widget in enumerate(elenco):
                if fuoco is widget or fuoco.is_ancestor(widget):
                    return posizione
            return -1
        except Exception as ex:
            scrivi_log("ModuloDialogo._posizione_fuoco", ex)
            return -1

    def _sposta_fuoco(self, passo):
        try:
            elenco = self._ordine_fuoco()
            if not elenco:
                return False
            posizione = self._posizione_fuoco(elenco, self._dialogo.get_focus())
            destinazione = (posizione + passo) % len(elenco) if posizione >= 0 else 0
            elenco[destinazione].grab_focus()
            return True
        except Exception as ex:
            scrivi_log(f"ModuloDialogo._sposta_fuoco ({passo})", ex)
            return False

    def _avanza_o_salva(self, elenco, posizione):
        try:
            if posizione < 0:
                return self._sposta_fuoco(1)
            if posizione >= len(elenco) - 1:
                self._dialogo.response(RISPOSTA_SALVA)
                return True
            return self._sposta_fuoco(1)
        except Exception as ex:
            scrivi_log("ModuloDialogo._avanza_o_salva", ex)
            return False

    def _cambia_scelta(self, combo, passo):
        try:
            modello = combo.get_model()
            totale = len(modello) if modello is not None else 0
            if totale == 0:
                return True
            attuale = combo.get_active()
            if attuale < 0:
                combo.set_active(0)
                return True
            destinazione = attuale + passo
            if 0 <= destinazione < totale:
                combo.set_active(destinazione)
            return True
        except Exception as ex:
            scrivi_log("ModuloDialogo._cambia_scelta", ex)
            return True

    def _testo_al_bordo(self, vista, verso_basso):
        try:
            buffer = vista.get_buffer()
            cursore = buffer.get_iter_at_mark(buffer.get_insert())
            prova = cursore.copy()
            if verso_basso:
                return not vista.forward_display_line(prova)
            vista.backward_display_line_start(prova)
            return not vista.backward_display_line(prova)
        except Exception as ex:
            scrivi_log("ModuloDialogo._testo_al_bordo", ex)
            return True

    def _tasto(self, dialogo, evento):
        try:
            nome = Gdk.keyval_name(evento.keyval)
            stato = evento.state
            controllo = bool(stato & Gdk.ModifierType.CONTROL_MASK)
            maiuscolo = bool(stato & Gdk.ModifierType.SHIFT_MASK)
            alternativo = bool(stato & Gdk.ModifierType.MOD1_MASK)
            if nome == "Escape":
                dialogo.response(RISPOSTA_ANNULLA)
                return True
            fuoco = dialogo.get_focus()
            elenco = self._ordine_fuoco()
            posizione = self._posizione_fuoco(elenco, fuoco)
            widget = elenco[posizione] if posizione >= 0 else None
            if nome in TASTI_INVIO:
                if controllo:
                    dialogo.response(RISPOSTA_SALVA)
                    return True
                if isinstance(widget, Gtk.TextView) and maiuscolo:
                    return False
                if maiuscolo:
                    return self._sposta_fuoco(-1)
                return self._avanza_o_salva(elenco, posizione)
            if alternativo or controllo:
                return False
            if isinstance(widget, Gtk.ComboBox) and (nome in TASTI_SU or nome in TASTI_GIU):
                return self._cambia_scelta(widget, -1 if nome in TASTI_SU else 1)
            if nome in TASTI_SU or nome in TASTI_GIU:
                verso_basso = nome in TASTI_GIU
                if isinstance(widget, Gtk.TextView) and not self._testo_al_bordo(widget, verso_basso):
                    return False
                return self._sposta_fuoco(1 if verso_basso else -1)
            if nome in TASTI_LATERALI and isinstance(widget, Gtk.ComboBox):
                return self._cambia_scelta(widget, 1 if nome in ("Right", "KP_Right") else -1)
            return False
        except Exception as ex:
            scrivi_log("ModuloDialogo._tasto", ex)
            return False

    def _metti_a_fuoco(self, chiave):
        try:
            widget = self._widget.get(chiave)
            if widget is not None and widget.get_sensitive():
                widget.grab_focus()
                return
            for campo in self.campi:
                candidato = self._widget.get(campo.chiave)
                if candidato is not None and candidato.get_sensitive():
                    candidato.grab_focus()
                    return
        except Exception as ex:
            scrivi_log(f"ModuloDialogo._metti_a_fuoco ({chiave})", ex)

    def esegui(self, campo_iniziale=None):
        dialogo = None
        try:
            dialogo = self._costruisci()
            dialogo.show_all()
            self._metti_a_fuoco(campo_iniziale or (self.campi[0].chiave if self.campi else None))
            while True:
                risposta = dialogo.run()
                if risposta != RISPOSTA_SALVA:
                    return None
                valori = self.valori()
                if self.convalida is None:
                    return valori
                try:
                    errore = self.convalida(valori)
                except Exception as ex:
                    scrivi_log(f"ModuloDialogo.esegui convalida ({self.titolo})", ex)
                    errore = ("I dati inseriti non sono validi.", None)
                if not errore:
                    return valori
                messaggio, chiave = errore
                mostra_avviso(dialogo, messaggio)
                self._metti_a_fuoco(chiave)
        except Exception as ex:
            scrivi_log(f"ModuloDialogo.esegui ({self.titolo})", ex)
            return None
        finally:
            try:
                if dialogo is not None:
                    dialogo.destroy()
            except Exception as ex:
                scrivi_log("ModuloDialogo.esegui distruzione", ex)


def chiedi_modulo(finestra, titolo, campi, convalida=None, campo_iniziale=None):
    try:
        return ModuloDialogo(finestra, titolo, campi, convalida).esegui(campo_iniziale)
    except Exception as ex:
        scrivi_log(f"modulo_dialogo.chiedi_modulo ({titolo})", ex)
        return None


def chiedi_testo(finestra, titolo, domanda, testo_iniziale=""):
    try:
        campo = Campo("testo", domanda, valore=testo_iniziale or "")
        valori = ModuloDialogo(finestra, titolo, [campo]).esegui("testo")
        if valori is None:
            return None
        testo = " ".join(str(valori.get("testo", "")).split())
        return testo or None
    except Exception as ex:
        scrivi_log(f"modulo_dialogo.chiedi_testo ({titolo})", ex)
        return None
