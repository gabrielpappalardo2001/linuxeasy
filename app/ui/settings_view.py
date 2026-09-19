import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from app.core import percorsi
from app.core.impostazioni import (
    CHIAVE_ASCOLTO_SOTTOFONDO,
    CHIAVE_NOTIFICHE_AGENDA,
    CHIAVE_NOTIFICHE_NOTIZIE,
    CHIAVE_NOTIFICHE_PODCAST,
    CHIAVE_RICORDA_POSIZIONE,
    CHIAVE_RICORDA_VOLUME,
)
from app.core.log import scrivi_log

NOME_PROGRAMMA = "LinuxEasy"
NOME_FILE_AVVIO = "linuxeasy.desktop"
NOME_FILE_ASSOCIAZIONE = "linux_easy.desktop"
MODULO_PREDEFINITO = "app.main"
CARTELLA_PROGETTO = Path(__file__).resolve().parents[2]
TIPI_ASSOCIATI = "audio/mpeg;audio/x-wav;audio/ogg;video/mp4;video/x-matroska;"
SECONDI_RITARDO_AVVIO = 5
CARATTERI_DA_RACCHIUDERE = set(" \t\n\"'\\><~|&;$*?#()`")
TITOLO_NOTIFICHE = "Impostazioni notifiche"
TITOLO_RIPRODUZIONE = "Impostazioni riproduzione"
TITOLO_SISTEMA = "Impostazioni di sistema"
MESSAGGIO_NON_DISPONIBILI = "Le impostazioni non sono disponibili."
MESSAGGIO_DETTAGLI_LOG = "I dettagli sono nel file di log."


class SettingsView:
    def __init__(self, finestra, impostazioni, engine=None):
        self.finestra = finestra
        self.impostazioni = impostazioni
        self.engine = engine

    def get_menu_items(self):
        try:
            return [
                ("Notifiche", self.apri_notifiche, None),
                ("Riproduzione", self.apri_riproduzione, None),
                ("Sistema", self.apri_sistema, None),
            ]
        except Exception as ex:
            scrivi_log("SettingsView.get_menu_items", ex)
            return []

    def apri_notifiche(self):
        try:
            self.finestra.push_menu(TITOLO_NOTIFICHE, self._voci_notifiche)
        except Exception as ex:
            scrivi_log("SettingsView.apri_notifiche", ex)

    def apri_riproduzione(self):
        try:
            self.finestra.push_menu(TITOLO_RIPRODUZIONE, self._voci_riproduzione)
        except Exception as ex:
            scrivi_log("SettingsView.apri_riproduzione", ex)

    def apri_sistema(self):
        try:
            self.finestra.push_menu(TITOLO_SISTEMA, self._voci_sistema)
        except Exception as ex:
            scrivi_log("SettingsView.apri_sistema", ex)

    def _stato_femminile(self, attivo):
        return "attive" if attivo else "disattivate"

    def _stato_maschile(self, attivo):
        return "attivo" if attivo else "disattivato"

    def _attivo(self, chiave, predefinito):
        try:
            if self.impostazioni is None:
                return predefinito
            return self.impostazioni.attivo(chiave, predefinito)
        except Exception as ex:
            scrivi_log(f"SettingsView._attivo ({chiave})", ex)
            return predefinito

    def _voci_notifiche(self):
        try:
            podcast = self._attivo(CHIAVE_NOTIFICHE_PODCAST, True)
            notizie = self._attivo(CHIAVE_NOTIFICHE_NOTIZIE, True)
            agenda = self._attivo(CHIAVE_NOTIFICHE_AGENDA, True)
            return [
                (f"Notifiche dei nuovi episodi podcast: {self._stato_femminile(podcast)}", self.alterna_notifiche_podcast, None),
                (f"Notifiche delle nuove notizie: {self._stato_femminile(notizie)}", self.alterna_notifiche_notizie, None),
                (f"Notifiche degli appuntamenti: {self._stato_femminile(agenda)}", self.alterna_notifiche_agenda, None),
            ]
        except Exception as ex:
            scrivi_log("SettingsView._voci_notifiche", ex)
            return []

    def _voci_riproduzione(self):
        try:
            volume = self._attivo(CHIAVE_RICORDA_VOLUME, False)
            posizione = self._attivo(CHIAVE_RICORDA_POSIZIONE, False)
            sottofondo = self._attivo(CHIAVE_ASCOLTO_SOTTOFONDO, False)
            return [
                (f"Ricorda il volume: {self._stato_maschile(volume)}", self.alterna_ricorda_volume, None),
                (f"Ricorda l'ultima posizione di ascolto: {self._stato_maschile(posizione)}", self.alterna_ricorda_posizione, None),
                ("Cancella le posizioni di ascolto salvate", self.cancella_posizioni, None),
                (f"Chiedi l'ascolto in sottofondo con Escape: {self._stato_maschile(sottofondo)}", self.alterna_ascolto_sottofondo, None),
            ]
        except Exception as ex:
            scrivi_log("SettingsView._voci_riproduzione", ex)
            return []

    def _voci_sistema(self):
        try:
            avvio = self.avvio_automatico_attivo()
            return [
                (f"Avvia {NOME_PROGRAMMA} all'accesso: {self._stato_maschile(avvio)}", self.alterna_avvio_automatico, None),
                ("Associa i file audio e video al programma", self.setup_desktop_integration, None),
            ]
        except Exception as ex:
            scrivi_log("SettingsView._voci_sistema", ex)
            return []

    def _aggiorna_menu(self):
        try:
            self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
        except Exception as ex:
            scrivi_log("SettingsView._aggiorna_menu", ex)

    def _alterna(self, chiave, predefinito):
        try:
            if self.impostazioni is None:
                self.finestra.mostra_messaggio(MESSAGGIO_NON_DISPONIBILI, MESSAGGIO_DETTAGLI_LOG)
                return None
            nuovo = not self.impostazioni.attivo(chiave, predefinito)
            if not self.impostazioni.imposta_attivo(chiave, nuovo):
                self.finestra.mostra_messaggio("Impossibile salvare l'impostazione.", MESSAGGIO_DETTAGLI_LOG)
                return None
            return nuovo
        except Exception as ex:
            scrivi_log(f"SettingsView._alterna ({chiave})", ex)
            return None

    def alterna_notifiche_podcast(self):
        try:
            nuovo = self._alterna(CHIAVE_NOTIFICHE_PODCAST, True)
            if nuovo is None:
                return
            if not nuovo:
                self.finestra.nascondi_avviso_episodi()
            self._aggiorna_menu()
        except Exception as ex:
            scrivi_log("SettingsView.alterna_notifiche_podcast", ex)

    def alterna_notifiche_notizie(self):
        try:
            nuovo = self._alterna(CHIAVE_NOTIFICHE_NOTIZIE, True)
            if nuovo is None:
                return
            if not nuovo:
                self.finestra.nascondi_avviso_notizie()
            self._aggiorna_menu()
        except Exception as ex:
            scrivi_log("SettingsView.alterna_notifiche_notizie", ex)

    def alterna_notifiche_agenda(self):
        try:
            nuovo = self._alterna(CHIAVE_NOTIFICHE_AGENDA, True)
            if nuovo is None:
                return
            if not nuovo:
                self.finestra.nascondi_avviso_agenda()
            self._aggiorna_menu()
        except Exception as ex:
            scrivi_log("SettingsView.alterna_notifiche_agenda", ex)

    def alterna_ricorda_volume(self):
        try:
            nuovo = self._alterna(CHIAVE_RICORDA_VOLUME, False)
            if nuovo is None:
                return
            if nuovo and self.engine is not None:
                self.engine.memorizza_volume()
            self._aggiorna_menu()
        except Exception as ex:
            scrivi_log("SettingsView.alterna_ricorda_volume", ex)

    def alterna_ricorda_posizione(self):
        try:
            nuovo = self._alterna(CHIAVE_RICORDA_POSIZIONE, False)
            if nuovo is None:
                return
            if nuovo and self.engine is not None:
                self.engine.memorizza_posizione()
            self._aggiorna_menu()
        except Exception as ex:
            scrivi_log("SettingsView.alterna_ricorda_posizione", ex)

    def alterna_ascolto_sottofondo(self):
        try:
            if self._alterna(CHIAVE_ASCOLTO_SOTTOFONDO, False) is None:
                return
            self._aggiorna_menu()
        except Exception as ex:
            scrivi_log("SettingsView.alterna_ascolto_sottofondo", ex)

    def cancella_posizioni(self):
        try:
            if self.impostazioni is None:
                self.finestra.mostra_messaggio(MESSAGGIO_NON_DISPONIBILI, MESSAGGIO_DETTAGLI_LOG)
                return
            totale = self.impostazioni.numero_posizioni()
            if totale == 0:
                self.finestra.mostra_messaggio("Nessuna posizione di ascolto salvata.")
                return
            descrizione = "1 posizione salvata" if totale == 1 else f"{totale} posizioni salvate"
            if not self.finestra.chiedi_conferma("Cancellare le posizioni di ascolto salvate?", f"Ci sono {descrizione}."):
                return
            if self.impostazioni.cancella_tutte_le_posizioni():
                self.finestra.mostra_stato("Posizioni di ascolto cancellate.")
            else:
                self.finestra.mostra_messaggio("Impossibile cancellare le posizioni di ascolto.", MESSAGGIO_DETTAGLI_LOG)
        except Exception as ex:
            scrivi_log("SettingsView.cancella_posizioni", ex)

    def _cartella_profilo(self):
        try:
            return Path(percorsi.cartella_profilo())
        except Exception as ex:
            scrivi_log("SettingsView._cartella_profilo", ex)
            return Path.home()

    def _cartella_configurazione(self):
        try:
            valore = os.environ.get("XDG_CONFIG_HOME", "").strip()
            if valore and os.path.isabs(valore):
                return Path(valore)
            return self._cartella_profilo() / ".config"
        except Exception as ex:
            scrivi_log("SettingsView._cartella_configurazione", ex)
            return Path.home() / ".config"

    def _cartella_applicazioni(self):
        try:
            valore = os.environ.get("XDG_DATA_HOME", "").strip()
            if valore and os.path.isabs(valore):
                return Path(valore) / "applications"
            return self._cartella_profilo() / ".local" / "share" / "applications"
        except Exception as ex:
            scrivi_log("SettingsView._cartella_applicazioni", ex)
            return Path.home() / ".local" / "share" / "applications"

    def _file_avvio(self):
        return self._cartella_configurazione() / "autostart" / NOME_FILE_AVVIO

    def _comando_programma(self):
        try:
            interprete = sys.executable or shutil.which("python3") or "python3"
            principale = sys.modules.get("__main__")
            specifica = getattr(principale, "__spec__", None)
            nome_modulo = getattr(specifica, "name", "") if specifica is not None else ""
            if nome_modulo and nome_modulo != "__main__":
                return [interprete, "-m", nome_modulo], CARTELLA_PROGETTO
            file_principale = getattr(principale, "__file__", "")
            if file_principale:
                percorso = Path(file_principale).resolve()
                if percorso.is_file():
                    return [interprete, str(percorso)], percorso.parent
            return [interprete, "-m", MODULO_PREDEFINITO], CARTELLA_PROGETTO
        except Exception as ex:
            scrivi_log("SettingsView._comando_programma", ex)
            return ["python3", "-m", MODULO_PREDEFINITO], CARTELLA_PROGETTO

    def _argomento_exec(self, testo):
        try:
            valore = str(testo)
            if valore and not any(carattere in CARATTERI_DA_RACCHIUDERE for carattere in valore):
                return valore.replace("%", "%%")
            protetto = (
                valore.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("`", "\\`")
                .replace("$", "\\$")
                .replace("%", "%%")
            )
            return f'"{protetto}"'
        except Exception as ex:
            scrivi_log(f"SettingsView._argomento_exec ({testo})", ex)
            return str(testo)

    def _valore_desktop(self, testo):
        try:
            return str(testo).replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
        except Exception as ex:
            scrivi_log("SettingsView._valore_desktop", ex)
            return str(testo)

    def _riga_exec(self, argomenti_file=""):
        try:
            comando, cartella = self._comando_programma()
            interno = f"cd {shlex.quote(str(cartella))} && exec {shlex.join(comando)}"
            if argomenti_file:
                interno = f'{interno} "$@"'
            parti = ["sh", "-c", interno]
            if argomenti_file:
                parti.append("sh")
            riga = " ".join(self._argomento_exec(parte) for parte in parti)
            if argomenti_file:
                riga = f"{riga} {argomenti_file}"
            return self._valore_desktop(riga), self._valore_desktop(str(cartella))
        except Exception as ex:
            scrivi_log("SettingsView._riga_exec", ex)
            return f"python3 -m {MODULO_PREDEFINITO}", self._valore_desktop(str(CARTELLA_PROGETTO))

    def _scrivi_file(self, percorso, contenuto):
        provvisorio = None
        try:
            percorso.parent.mkdir(parents=True, exist_ok=True)
            provvisorio = percorso.with_name(f".{percorso.name}.tmp")
            provvisorio.write_text(contenuto, encoding="utf-8")
            os.replace(provvisorio, percorso)
            return True
        except Exception as ex:
            scrivi_log(f"SettingsView._scrivi_file ({percorso})", ex)
            try:
                if provvisorio is not None and provvisorio.exists():
                    provvisorio.unlink()
            except Exception as ex_pulizia:
                scrivi_log(f"SettingsView._scrivi_file pulizia ({provvisorio})", ex_pulizia)
            return False

    def avvio_automatico_attivo(self):
        try:
            percorso = self._file_avvio()
            if not percorso.is_file():
                return False
            for riga in percorso.read_text(encoding="utf-8", errors="replace").splitlines():
                testo = riga.replace(" ", "").strip().lower()
                if testo in ("hidden=true", "x-gnome-autostart-enabled=false", "x-mate-autostart-enabled=false"):
                    return False
            return True
        except Exception as ex:
            scrivi_log("SettingsView.avvio_automatico_attivo", ex)
            return False

    def attiva_avvio_automatico(self):
        try:
            riga_exec, cartella = self._riga_exec()
            contenuto = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={NOME_PROGRAMMA}\n"
                "Comment=Radio, podcast, notizie e video accessibili\n"
                f"Exec={riga_exec}\n"
                f"Path={cartella}\n"
                "Terminal=false\n"
                "Hidden=false\n"
                "NoDisplay=false\n"
                "X-GNOME-Autostart-enabled=true\n"
                f"X-GNOME-Autostart-Delay={SECONDI_RITARDO_AVVIO}\n"
                "X-MATE-Autostart-enabled=true\n"
                f"X-MATE-Autostart-Delay={SECONDI_RITARDO_AVVIO}\n"
                "X-KDE-autostart-after=panel\n"
            )
            return self._scrivi_file(self._file_avvio(), contenuto)
        except Exception as ex:
            scrivi_log("SettingsView.attiva_avvio_automatico", ex)
            return False

    def disattiva_avvio_automatico(self):
        try:
            percorso = self._file_avvio()
            if percorso.exists() or percorso.is_symlink():
                percorso.unlink()
            return True
        except Exception as ex:
            scrivi_log("SettingsView.disattiva_avvio_automatico", ex)
            return False

    def alterna_avvio_automatico(self):
        try:
            if self.avvio_automatico_attivo():
                if not self.disattiva_avvio_automatico():
                    self.finestra.mostra_messaggio("Impossibile disattivare l'avvio automatico.", MESSAGGIO_DETTAGLI_LOG)
                    return
            else:
                if not self.attiva_avvio_automatico():
                    self.finestra.mostra_messaggio("Impossibile attivare l'avvio automatico.", MESSAGGIO_DETTAGLI_LOG)
                    return
            self._aggiorna_menu()
        except Exception as ex:
            scrivi_log("SettingsView.alterna_avvio_automatico", ex)

    def _aggiorna_database_applicazioni(self, cartella):
        try:
            programma = shutil.which("update-desktop-database")
            if not programma:
                return
            subprocess.Popen(
                [programma, str(cartella)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as ex:
            scrivi_log("SettingsView._aggiorna_database_applicazioni", ex)

    def setup_desktop_integration(self):
        try:
            cartella = self._cartella_applicazioni()
            riga_exec, cartella_lavoro = self._riga_exec("%U")
            contenuto = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Linux Easy\n"
                f"Exec={riga_exec}\n"
                f"Path={cartella_lavoro}\n"
                "Terminal=false\n"
                f"MimeType={TIPI_ASSOCIATI}\n"
                "Categories=AudioVideo;Player;\n"
            )
            if not self._scrivi_file(cartella / NOME_FILE_ASSOCIAZIONE, contenuto):
                self.finestra.mostra_messaggio("Impossibile associare i file al programma.", MESSAGGIO_DETTAGLI_LOG)
                return
            self._aggiorna_database_applicazioni(cartella)
            self.finestra.mostra_messaggio("Associazione con il file manager completata.")
        except Exception as ex:
            scrivi_log("SettingsView.setup_desktop_integration", ex)
            try:
                self.finestra.mostra_messaggio("Impossibile associare i file al programma.", MESSAGGIO_DETTAGLI_LOG)
            except Exception as ex_messaggio:
                scrivi_log("SettingsView.setup_desktop_integration messaggio", ex_messaggio)
