import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Atk", "1.0")
from gi.repository import Atk, Gdk, Gtk

from app.core.log import scrivi_log

NOME_PROGRAMMA = "LinuxEasy"
TASTI_INVIO = ("Return", "KP_Enter", "ISO_Enter")
TASTI_SU = ("Up", "KP_Up")
TASTI_GIU = ("Down", "KP_Down")
TESTO_ANNULLA = "Annulla"
TESTO_SI = "Sì"
TESTO_NO = "No"


def _distruggi(dialogo, contesto):
    try:
        if dialogo is not None:
            dialogo.destroy()
    except Exception as ex:
        scrivi_log(f"messaggi._distruggi ({contesto})", ex)


def _tasto_messaggio(dialogo, evento):
    try:
        nome = Gdk.keyval_name(evento.keyval)
        if nome == "Escape" or nome in TASTI_INVIO or nome == "space":
            dialogo.response(Gtk.ResponseType.CLOSE)
            return True
        return False
    except Exception as ex:
        scrivi_log("messaggi._tasto_messaggio", ex)
        return False


def mostra_messaggio(genitore, testo, dettaglio="", tipo=Gtk.MessageType.INFO, titolo=NOME_PROGRAMMA):
    dialogo = None
    try:
        dialogo = Gtk.MessageDialog(
            transient_for=genitore,
            modal=True,
            message_type=tipo,
            buttons=Gtk.ButtonsType.NONE,
            text=testo,
        )
        dialogo.set_title(titolo)
        if dettaglio:
            dialogo.format_secondary_text(dettaglio)
        dialogo.connect("key-press-event", _tasto_messaggio)
        dialogo.run()
    except Exception as ex:
        scrivi_log(f"messaggi.mostra_messaggio ({testo})", ex)
    finally:
        _distruggi(dialogo, "mostra_messaggio")


def mostra_avviso(genitore, testo, dettaglio=""):
    mostra_messaggio(genitore, testo, dettaglio, Gtk.MessageType.WARNING)


def _riga_attivata(lista, riga, dialogo):
    try:
        if riga is not None:
            dialogo.response(riga.get_index())
    except Exception as ex:
        scrivi_log("messaggi._riga_attivata", ex)


def _seleziona(lista, indice):
    try:
        riga = lista.get_row_at_index(indice)
        if riga is not None:
            lista.select_row(riga)
            riga.grab_focus()
    except Exception as ex:
        scrivi_log(f"messaggi._seleziona ({indice})", ex)


def _tasto_scelta(dialogo, evento, lista):
    try:
        nome = Gdk.keyval_name(evento.keyval)
        if nome == "Escape":
            dialogo.response(Gtk.ResponseType.CANCEL)
            return True
        righe = lista.get_children()
        totale = len(righe)
        if totale == 0:
            return False
        selezionata = lista.get_selected_row()
        indice = selezionata.get_index() if selezionata is not None else 0
        if nome in TASTI_SU:
            _seleziona(lista, (indice - 1) % totale)
            return True
        if nome in TASTI_GIU:
            _seleziona(lista, (indice + 1) % totale)
            return True
        if nome in TASTI_INVIO or nome == "space":
            dialogo.response(indice)
            return True
        return False
    except Exception as ex:
        scrivi_log("messaggi._tasto_scelta", ex)
        return False


def chiedi_scelta(genitore, domanda, opzioni, dettaglio="", con_annulla=True, indice_iniziale=0):
    dialogo = None
    try:
        voci = [str(opzione) for opzione in opzioni]
        totale_opzioni = len(voci)
        if con_annulla:
            voci.append(TESTO_ANNULLA)
        dialogo = Gtk.MessageDialog(
            transient_for=genitore,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=domanda,
        )
        dialogo.set_title(NOME_PROGRAMMA)
        if dettaglio:
            dialogo.format_secondary_text(dettaglio)
        lista = Gtk.ListBox()
        lista.set_selection_mode(Gtk.SelectionMode.SINGLE)
        lista.set_activate_on_single_click(False)
        accessibile_lista = lista.get_accessible()
        if accessibile_lista is not None:
            accessibile_lista.set_role(Atk.Role.MENU)
            accessibile_lista.set_name(domanda)
        for testo in voci:
            riga = Gtk.ListBoxRow()
            etichetta = Gtk.Label(label=testo)
            etichetta.set_xalign(0)
            riga.add(etichetta)
            accessibile_riga = riga.get_accessible()
            if accessibile_riga is not None:
                accessibile_riga.set_role(Atk.Role.MENU_ITEM)
                accessibile_riga.set_name(testo)
            lista.add(riga)
        lista.connect("row-activated", _riga_attivata, dialogo)
        dialogo.get_message_area().pack_start(lista, False, False, 0)
        dialogo.connect("key-press-event", _tasto_scelta, lista)
        dialogo.show_all()
        indice = indice_iniziale if 0 <= indice_iniziale < len(voci) else 0
        _seleziona(lista, indice)
        risposta = dialogo.run()
        if isinstance(risposta, int) and 0 <= risposta < totale_opzioni:
            return risposta
        return -1
    except Exception as ex:
        scrivi_log(f"messaggi.chiedi_scelta ({domanda})", ex)
        return -1
    finally:
        _distruggi(dialogo, "chiedi_scelta")


def chiedi_conferma(genitore, domanda, dettaglio="", predefinita_si=True):
    try:
        risposta = chiedi_scelta(
            genitore,
            domanda,
            [TESTO_SI, TESTO_NO],
            dettaglio,
            con_annulla=False,
            indice_iniziale=0 if predefinita_si else 1,
        )
        return risposta == 0
    except Exception as ex:
        scrivi_log(f"messaggi.chiedi_conferma ({domanda})", ex)
        return False
