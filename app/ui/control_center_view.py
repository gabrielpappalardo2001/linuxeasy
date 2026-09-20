from gi.repository import GLib

from app.core.log import scrivi_log
from app.librivox import librivox_downloads as scaricamenti

ETICHETTE_ASCOLTO = {
    "brani": "Ascolto brani",
    "video": "Ascolto video",
    "youtube": "Ascolto YouTube",
    "stream": "Ascolto stream",
    "audiolibro": "Ascolto audiolibro",
}
TITOLO_ASCOLTO_PREDEFINITO = "Ascolto in corso"
TITOLO_CENTRO_CONTROLLO = "Centro di controllo"
TITOLO_RIPRODUZIONE = "Riproduzione in corso"
MILLISECONDI_AGGIORNAMENTO_DIFFERITO = 400
VOLUME_MASSIMO = 130
INCREMENTO_VOLUME = 5
ERRORE_LOG = "I dettagli sono nel file di log."


def conta(numero, singolare, plurale):
    try:
        return f"1 {singolare}" if numero == 1 else f"{numero} {plurale}"
    except Exception as ex:
        scrivi_log("control_center_view.conta", ex)
        return str(numero)


class ControlCenterView:
    def __init__(self, finestra, engine):
        self.finestra = finestra
        self.engine = engine

    def _servizio(self, nome):
        try:
            return getattr(self.finestra, nome, None)
        except Exception as ex:
            scrivi_log(f"ControlCenterView._servizio ({nome})", ex)
            return None

    def _riproduzione_attiva(self):
        try:
            return self.engine is not None and self.engine.is_loaded()
        except Exception as ex:
            scrivi_log("ControlCenterView._riproduzione_attiva", ex)
            return False

    def get_menu_items(self):
        voci = []
        try:
            voci.extend(self._voci_riproduzione_principale())
            voci.extend(self._voci_catalogo())
            voci.extend(self._voci_audiolibri())
            voci.extend(self._voci_podcast())
        except Exception as ex:
            scrivi_log("ControlCenterView.get_menu_items", ex)
        if not voci:
            voci.append(("Nessuna attività in corso", None, None))
        return voci

    def _voci_riproduzione_principale(self):
        try:
            if not self._riproduzione_attiva():
                return []
            return [(TITOLO_RIPRODUZIONE, self.apri_riproduzione, self._azioni_riproduzione)]
        except Exception as ex:
            scrivi_log("ControlCenterView._voci_riproduzione_principale", ex)
            return []

    def _voci_catalogo(self):
        try:
            vista = self._servizio("librivox_view")
            catalogo = self._servizio("librivox_catalog")
            if vista is None or catalogo is None or not catalogo.aggiornamento_in_corso:
                return []
            azioni = [
                ("Segui l'avanzamento", vista.apri_avanzamento_catalogo, None),
                ("Annulla il download del catalogo", vista.annulla_catalogo, None),
            ]
            return [("Download del catalogo di LibriVox in corso", vista.apri_avanzamento_catalogo, azioni)]
        except Exception as ex:
            scrivi_log("ControlCenterView._voci_catalogo", ex)
            return []

    def _voci_audiolibri(self):
        try:
            vista = self._servizio("librivox_view")
            downloads = self._servizio("librivox_downloads")
            if vista is None or downloads is None:
                return []
            elementi = downloads.in_corso()
            falliti = sum(1 for elemento in elementi if elemento["stato"] == scaricamenti.STATO_ERRORE)
            attivi = len(elementi) - falliti
            if not elementi:
                return []
            parti = []
            if attivi:
                parti.append(f"{attivi} in corso")
            if falliti:
                parti.append(f"{conta(falliti, 'non riuscito', 'non riusciti')}")
            azioni = [("Apri l'elenco dei download", vista.apri_download, None)]
            if attivi:
                azioni.append(("Annulla tutti i download degli audiolibri", vista.annulla_tutti_download, None))
            return [(f"Download degli audiolibri, {', '.join(parti)}", vista.apri_download, azioni)]
        except Exception as ex:
            scrivi_log("ControlCenterView._voci_audiolibri", ex)
            return []

    def _voci_podcast(self):
        try:
            vista = self._servizio("podcast_view")
            downloads = self._servizio("podcast_downloads")
            if vista is None or downloads is None:
                return []
            totale = len(downloads.in_corso())
            if not totale:
                return []
            azioni = [
                ("Apri l'elenco dei download", vista.apri_download_in_corso, None),
                ("Annulla tutti i download dei podcast", self.annulla_download_podcast, None),
            ]
            return [(f"Download dei podcast, {conta(totale, 'episodio', 'episodi')}", vista.apri_download_in_corso, azioni)]
        except Exception as ex:
            scrivi_log("ControlCenterView._voci_podcast", ex)
            return []

    def annulla_download_podcast(self):
        try:
            downloads = self._servizio("podcast_downloads")
            if downloads is None:
                return
            elementi = downloads.in_corso()
            if not elementi:
                self.finestra.mostra_messaggio("Nessun download di podcast in corso.")
                return
            if not self.finestra.chiedi_conferma(
                f"Annullare {conta(len(elementi), 'download', 'download')} di episodi?",
            ):
                return
            falliti = 0
            for elemento in elementi:
                if not downloads.annulla(elemento["episodio"].audio_url):
                    falliti += 1
            if falliti:
                self.finestra.mostra_messaggio(
                    f"Non è stato possibile annullare {conta(falliti, 'download', 'download')}.",
                    ERRORE_LOG,
                )
            else:
                self.finestra.mostra_stato("Download dei podcast annullati.")
        except Exception as ex:
            scrivi_log("ControlCenterView.annulla_download_podcast", ex)

    def _azioni_riproduzione(self):
        try:
            return [
                ("Pausa / Riprendi", self.toggle_play, None),
                ("Aumenta il volume", self.volume_up, None),
                ("Abbassa il volume", self.volume_down, None),
                ("Interrompi la riproduzione", self.stop_play, None),
                ("Apri il lettore", self.apri_player, None),
            ]
        except Exception as ex:
            scrivi_log("ControlCenterView._azioni_riproduzione", ex)
            return []

    def apri_riproduzione(self):
        try:
            self.finestra.push_menu(TITOLO_RIPRODUZIONE, self._voci_riproduzione, "Nessuna riproduzione in corso.")
        except Exception as ex:
            scrivi_log("ControlCenterView.apri_riproduzione", ex)

    def _voci_riproduzione(self):
        voci = []
        try:
            if not self._riproduzione_attiva():
                return voci
            volume = int(self.engine.get_volume())
            stato = "in riproduzione" if self.engine.is_playing() else "in pausa"
            tipo = ETICHETTE_ASCOLTO.get(self.engine.get_kind(), TITOLO_ASCOLTO_PREDEFINITO)
            voci.append((f"{tipo}, {stato}", None, None))
            titolo = self.engine.current_title or ""
            if titolo:
                voci.append((f"Traccia: {titolo}", None, None))
            voci.extend(
                [
                    (f"Volume: {volume}%", None, None),
                    ("Pausa / Riprendi", self.toggle_play, None),
                    ("Aumenta il volume", self.volume_up, None),
                    ("Abbassa il volume", self.volume_down, None),
                    ("Interrompi la riproduzione", self.stop_play, None),
                    ("Apri il lettore", self.apri_player, None),
                ]
            )
        except Exception as ex:
            scrivi_log("ControlCenterView._voci_riproduzione", ex)
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
            self._aggiorna(f"Volume: {int(valore)}%")
        except Exception as ex:
            scrivi_log("ControlCenterView.volume_up", ex)

    def volume_down(self):
        try:
            if self.engine is None:
                return
            valore = max(0, self.engine.get_volume() - INCREMENTO_VOLUME)
            self.engine.set_volume(valore)
            self._aggiorna(f"Volume: {int(valore)}%")
        except Exception as ex:
            scrivi_log("ControlCenterView.volume_down", ex)

    def toggle_play(self):
        try:
            if not self._riproduzione_attiva():
                self.finestra.mostra_messaggio("Nessuna riproduzione in corso.")
                return
            if self.engine.is_playing():
                self.engine.pause()
                self._aggiorna("Riproduzione in pausa.")
            else:
                self.engine.resume()
                self._aggiorna("Riproduzione ripresa.")
        except Exception as ex:
            scrivi_log("ControlCenterView.toggle_play", ex)

    def stop_play(self):
        try:
            if not self._riproduzione_attiva():
                self.finestra.mostra_messaggio("Nessuna riproduzione in corso.")
                return
            self.engine.stop()
            self._aggiorna("Riproduzione interrotta.")
            GLib.timeout_add(MILLISECONDI_AGGIORNAMENTO_DIFFERITO, self._aggiorna_differito)
        except Exception as ex:
            scrivi_log("ControlCenterView.stop_play", ex)
