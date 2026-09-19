from gi.repository import GLib

from app.core.log import scrivi_log

ETICHETTE_ASCOLTO = {
    "brani": "Ascolto brani",
    "video": "Ascolto video",
    "youtube": "Ascolto YouTube",
    "stream": "Ascolto stream",
    "audiolibro": "Ascolto audiolibro",
}
TITOLO_ASCOLTO_PREDEFINITO = "Ascolto in corso"
TITOLO_CENTRO_CONTROLLO = "Centro di controllo"
MILLISECONDI_AGGIORNAMENTO_DIFFERITO = 400
VOLUME_MASSIMO = 130
INCREMENTO_VOLUME = 5


class ControlCenterView:
    def __init__(self, finestra, engine):
        self.finestra = finestra
        self.engine = engine

    def get_menu_items(self):
        voci = []
        try:
            volume = int(self.engine.get_volume()) if self.engine is not None else 100
            in_riproduzione = self.engine is not None and self.engine.is_playing()
            caricato = self.engine is not None and self.engine.is_loaded()
            if caricato:
                etichetta = ETICHETTE_ASCOLTO.get(self.engine.get_kind(), TITOLO_ASCOLTO_PREDEFINITO)
                voci.append((etichetta, self.apri_player, None))
            if in_riproduzione:
                stato = "In riproduzione"
            elif caricato:
                stato = "In pausa"
            else:
                stato = "Fermo"
            voci.extend(
                [
                    (f"Stato riproduzione: {stato}", None, None),
                    (f"Volume attuale: {volume}%", None, None),
                    ("Aumenta volume", self.volume_up, None),
                    ("Abbassa volume", self.volume_down, None),
                    ("Pausa / Riprendi", self.toggle_play, None),
                    ("Interrompi riproduzione", self.stop_play, None),
                ]
            )
        except Exception as ex:
            scrivi_log("ControlCenterView.get_menu_items", ex)
        return voci

    def _aggiorna(self, messaggio=""):
        try:
            self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            if messaggio:
                self.finestra.mostra_stato(messaggio)
        except Exception as ex:
            scrivi_log("ControlCenterView._aggiorna", ex)

    def _aggiorna_differito(self):
        try:
            if self.finestra.titolo_corrente() == TITOLO_CENTRO_CONTROLLO and not self.finestra.in_pagina():
                self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
        except Exception as ex:
            scrivi_log("ControlCenterView._aggiorna_differito", ex)
        return False

    def apri_player(self):
        try:
            self.finestra.apri_player()
        except Exception as ex:
            scrivi_log("ControlCenterView.apri_player", ex)

    def volume_up(self):
        try:
            if self.engine is None:
                return
            valore = min(VOLUME_MASSIMO, self.engine.get_volume() + INCREMENTO_VOLUME)
            self.engine.set_volume(valore)
            self._aggiorna()
        except Exception as ex:
            scrivi_log("ControlCenterView.volume_up", ex)

    def volume_down(self):
        try:
            if self.engine is None:
                return
            valore = max(0, self.engine.get_volume() - INCREMENTO_VOLUME)
            self.engine.set_volume(valore)
            self._aggiorna()
        except Exception as ex:
            scrivi_log("ControlCenterView.volume_down", ex)

    def toggle_play(self):
        try:
            if self.engine is None or not self.engine.is_loaded():
                self.finestra.mostra_stato("Nessun ascolto in corso.")
                return
            if self.engine.is_playing():
                self.engine.pause()
                self._aggiorna("Pausa.")
            else:
                self.engine.resume()
                self._aggiorna("Riproduzione ripresa.")
        except Exception as ex:
            scrivi_log("ControlCenterView.toggle_play", ex)

    def stop_play(self):
        try:
            if self.engine is None or not self.engine.is_loaded():
                self.finestra.mostra_stato("Nessun ascolto in corso.")
                return
            self.engine.stop()
            self._aggiorna("Riproduzione interrotta.")
            GLib.timeout_add(MILLISECONDI_AGGIORNAMENTO_DIFFERITO, self._aggiorna_differito)
        except Exception as ex:
            scrivi_log("ControlCenterView.stop_play", ex)
