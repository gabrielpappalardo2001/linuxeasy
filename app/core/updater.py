import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk

from app.core import percorsi
from app.core.log import scrivi_log

REPOSITORY_URL = "https://github.com/gabrielpappalardo2001/linuxeasy.git"
NOME_REPOSITORY = "repository"
FILE_VERSIONE = ".versione_installata"
SECONDI_CONTROLLO = 25
SECONDI_GIT_BREVE = 30
SECONDI_SCARICAMENTO = 600
SECONDI_PIP = 900
SECONDI_RIAVVIO = 3
MILLISECONDI_PULSAZIONE = 150
TITOLO_FINESTRA = f"{percorsi.NOME_PROGRAMMA} - Aggiornamento"
FASE_CONTROLLO = "controllo"
FASE_DOMANDA = "domanda"
FASE_INSTALLAZIONE = "installazione"
FASE_FINE = "fine"


class ErroreAggiornamento(Exception):
    pass


class EsitoControllo:
    def __init__(self, disponibile=False, descrizione="", versione="", errore=""):
        self.disponibile = disponibile
        self.descrizione = descrizione
        self.versione = versione
        self.errore = errore


class Aggiornatore:
    def __init__(self, cartella_programma=None):
        try:
            if cartella_programma is not None:
                base = Path(cartella_programma).resolve()
            else:
                base = Path(__file__).resolve().parents[2]
        except Exception as ex:
            scrivi_log("Aggiornatore.__init__ cartella del programma", ex)
            base = Path.cwd()
        self.cartella_programma = base
        self.cartella_repository = base / NOME_REPOSITORY
        self.file_versione = base / FILE_VERSIONE
        self.git = shutil.which("git")

    def _ambiente(self):
        ambiente = dict(os.environ)
        ambiente["GIT_TERMINAL_PROMPT"] = "0"
        ambiente["LC_ALL"] = "C"
        return ambiente

    def _git(self, argomenti, cartella=None, secondi=SECONDI_GIT_BREVE):
        if self.git is None:
            raise ErroreAggiornamento("git non è installato.")
        comando = [self.git]
        if cartella is not None:
            comando += ["-c", f"safe.directory={cartella}", "-C", str(cartella)]
        comando += list(argomenti)
        try:
            risultato = subprocess.run(
                comando,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=secondi,
                env=self._ambiente(),
            )
        except subprocess.TimeoutExpired as ex:
            raise ErroreAggiornamento(f"git {' '.join(argomenti)} non ha risposto entro {secondi} secondi.") from ex
        if risultato.returncode != 0:
            dettaglio = (risultato.stderr or risultato.stdout or "").strip()
            raise ErroreAggiornamento(f"git {' '.join(argomenti)} terminato con il codice {risultato.returncode}: {dettaglio}")
        return (risultato.stdout or "").strip()

    def _leggi_file(self, percorso):
        try:
            if percorso.is_file():
                return percorso.read_bytes()
        except Exception as ex:
            scrivi_log(f"Aggiornatore._leggi_file ({percorso})", ex)
        return None

    def _aggiornamento_possibile(self):
        if (self.cartella_programma / ".git").exists():
            return False
        if self.git is None:
            scrivi_log("Aggiornatore: git non è installato, controllo degli aggiornamenti impossibile.")
            return False
        if not os.access(str(self.cartella_programma), os.W_OK):
            scrivi_log(f"Aggiornatore: la cartella {self.cartella_programma} non è scrivibile, aggiornamento impossibile.")
            return False
        return True

    def versione_installata(self):
        try:
            if self.file_versione.is_file():
                testo = self.file_versione.read_text(encoding="utf-8").strip()
                if testo:
                    return testo
        except Exception as ex:
            scrivi_log("Aggiornatore.versione_installata file", ex)
        try:
            if (self.cartella_repository / ".git").is_dir():
                return self._git(["rev-parse", "HEAD"], self.cartella_repository)
        except Exception as ex:
            scrivi_log("Aggiornatore.versione_installata repository", ex)
        return ""

    def controlla(self):
        try:
            if not self._aggiornamento_possibile():
                return EsitoControllo()
            risposta = self._git(["ls-remote", REPOSITORY_URL, "HEAD"], secondi=SECONDI_CONTROLLO).split()
            if not risposta:
                raise ErroreAggiornamento("GitHub non ha restituito la versione disponibile.")
            versione_remota = risposta[0]
            if self.versione_installata() == versione_remota:
                return EsitoControllo()
            descrizione = ""
            if (self.cartella_repository / ".git").is_dir():
                try:
                    self._git(["remote", "set-url", "origin", REPOSITORY_URL], self.cartella_repository)
                    self._git(["fetch", "--quiet", "origin"], self.cartella_repository, SECONDI_SCARICAMENTO)
                    descrizione = self._git(["log", "-1", "--format=%s", versione_remota], self.cartella_repository)
                except Exception as ex:
                    scrivi_log("Aggiornatore.controlla descrizione", ex)
            else:
                descrizione = "Prima configurazione del sistema di aggiornamento."
            return EsitoControllo(True, descrizione, versione_remota)
        except Exception as ex:
            scrivi_log("Aggiornatore.controlla", ex)
            return EsitoControllo(errore=str(ex))

    def installa(self, avanza):
        requisiti_vecchi = self._leggi_file(self.cartella_programma / "requirements.txt")
        avanza("Scaricamento dell'aggiornamento da GitHub.", 0.1)
        self._scarica()
        avanza("Controllo dei file scaricati.", 0.35)
        self._controlla_sorgenti()
        avanza("Copia dei nuovi file del programma.", 0.5)
        self._copia_programma()
        requisiti_nuovi = self._leggi_file(self.cartella_programma / "requirements.txt")
        if requisiti_nuovi is not None and requisiti_nuovi != requisiti_vecchi:
            avanza("Aggiornamento delle librerie Python. L'operazione può durare alcuni minuti.", 0.65)
            if not self._aggiorna_librerie():
                avanza("Aggiornamento delle librerie Python non riuscito, i dettagli sono nel registro.", 0.8)
        avanza("Registrazione della nuova versione.", 0.9)
        versione = self._git(["rev-parse", "HEAD"], self.cartella_repository)
        self.file_versione.write_text(versione + "\n", encoding="utf-8")
        self._sistema_proprieta()
        return versione

    def _scarica(self):
        if (self.cartella_repository / ".git").is_dir():
            self._git(["remote", "set-url", "origin", REPOSITORY_URL], self.cartella_repository)
            try:
                self._git(["pull", "--ff-only"], self.cartella_repository, SECONDI_SCARICAMENTO)
            except Exception as ex:
                scrivi_log("Aggiornatore._scarica pull, riallineo il repository", ex)
                self._git(["fetch", "--prune", "origin"], self.cartella_repository, SECONDI_SCARICAMENTO)
                self._git(["reset", "--hard", "@{u}"], self.cartella_repository)
            return
        if self.cartella_repository.exists():
            shutil.rmtree(str(self.cartella_repository))
        self._git(["clone", REPOSITORY_URL, str(self.cartella_repository)], secondi=SECONDI_SCARICAMENTO)

    def _controlla_sorgenti(self):
        if not (self.cartella_repository / "app").is_dir() or not (self.cartella_repository / "main.py").is_file():
            raise ErroreAggiornamento(f"Nel repository {self.cartella_repository} mancano la cartella app o il file main.py.")

    def _rimuovi(self, percorso):
        if percorso.is_dir() and not percorso.is_symlink():
            shutil.rmtree(str(percorso))
        elif percorso.exists() or percorso.is_symlink():
            percorso.unlink()

    def _copia_programma(self):
        base = self.cartella_programma
        app_attuale = base / "app"
        app_nuova = base / "app.nuova"
        app_vecchia = base / "app.vecchia"
        main_nuovo = base / "main.py.nuovo"
        requisiti_sorgente = self.cartella_repository / "requirements.txt"
        requisiti_nuovi = base / "requirements.txt.nuovo"
        for residuo in (app_nuova, app_vecchia, main_nuovo, requisiti_nuovi):
            self._rimuovi(residuo)
        shutil.copytree(
            str(self.cartella_repository / "app"),
            str(app_nuova),
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copy2(str(self.cartella_repository / "main.py"), str(main_nuovo))
        if requisiti_sorgente.is_file():
            shutil.copy2(str(requisiti_sorgente), str(requisiti_nuovi))
        spostata = False
        try:
            if app_attuale.exists():
                os.rename(str(app_attuale), str(app_vecchia))
                spostata = True
            os.rename(str(app_nuova), str(app_attuale))
            os.replace(str(main_nuovo), str(base / "main.py"))
            if requisiti_nuovi.is_file():
                os.replace(str(requisiti_nuovi), str(base / "requirements.txt"))
        except Exception:
            try:
                if spostata:
                    if app_attuale.exists():
                        self._rimuovi(app_attuale)
                    os.rename(str(app_vecchia), str(app_attuale))
            except Exception as ex:
                scrivi_log("Aggiornatore._copia_programma ripristino della versione precedente", ex)
            raise
        try:
            self._rimuovi(app_vecchia)
        except Exception as ex:
            scrivi_log("Aggiornatore._copia_programma rimozione della versione precedente", ex)

    def _aggiorna_librerie(self):
        try:
            risultato = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(self.cartella_programma / "requirements.txt")],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=SECONDI_PIP,
                env=self._ambiente(),
            )
            if risultato.returncode != 0:
                dettaglio = (risultato.stderr or risultato.stdout or "").strip()[-4000:]
                scrivi_log(f"Aggiornatore._aggiorna_librerie: pip terminato con il codice {risultato.returncode}\n{dettaglio}")
                return False
            return True
        except Exception as ex:
            scrivi_log("Aggiornatore._aggiorna_librerie", ex)
            return False

    def _sistema_proprieta(self):
        try:
            if not hasattr(os, "geteuid") or os.geteuid() != 0:
                return
            informazioni = os.stat(str(self.cartella_programma))
            utente = informazioni.st_uid
            gruppo = informazioni.st_gid
            if utente == 0:
                return
            errori = 0
            ultimo_errore = None
            for radice, cartelle, file in os.walk(str(self.cartella_programma)):
                for nome in [radice] + [os.path.join(radice, voce) for voce in cartelle + file]:
                    try:
                        os.lchown(nome, utente, gruppo)
                    except Exception as ex:
                        errori += 1
                        ultimo_errore = ex
            if errori:
                scrivi_log(f"Aggiornatore._sistema_proprieta: {errori} file senza il proprietario corretto", ultimo_errore)
        except Exception as ex:
            scrivi_log("Aggiornatore._sistema_proprieta", ex)

    def riavvia(self):
        os.execv(sys.executable, [sys.executable] + sys.argv)


class FinestraAggiornamento(Gtk.ApplicationWindow):
    def __init__(self, applicazione, al_termine):
        super().__init__(application=applicazione, title=TITOLO_FINESTRA)
        self.al_termine = al_termine
        self.aggiornatore = Aggiornatore()
        self.fase = FASE_CONTROLLO
        self._concluso = False
        self._timer_pulsazione = 0
        self.etichetta = None
        self.barra = None
        self.lista = None
        try:
            self.set_default_size(640, 420)
            self._crea_interfaccia()
            self.connect("key-press-event", self._tasto_premuto)
            self.connect("delete-event", self._chiusura_richiesta)
        except Exception as ex:
            scrivi_log("FinestraAggiornamento.__init__", ex)

    def _crea_interfaccia(self):
        contenitore = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        contenitore.set_border_width(10)
        self.etichetta = Gtk.Label(label="Controllo degli aggiornamenti")
        self.etichetta.set_xalign(0)
        self.etichetta.set_line_wrap(True)
        contenitore.pack_start(self.etichetta, False, False, 0)
        self.barra = Gtk.ProgressBar()
        self.barra.set_show_text(True)
        contenitore.pack_start(self.barra, False, False, 0)
        self.lista = Gtk.ListBox()
        self.lista.set_selection_mode(Gtk.SelectionMode.SINGLE)
        accessibile = self.lista.get_accessible()
        if accessibile is not None:
            accessibile.set_name("Avanzamento dell'aggiornamento")
        scorrimento = Gtk.ScrolledWindow()
        scorrimento.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scorrimento.add(self.lista)
        contenitore.pack_start(scorrimento, True, True, 0)
        self.add(contenitore)

    def avvia(self):
        try:
            self.show_all()
            self.present()
            self._aggiungi_passo("Controllo degli aggiornamenti in corso. Premere Escape per avviare subito il programma.")
            self.barra.set_text("Controllo")
            self._timer_pulsazione = GLib.timeout_add(MILLISECONDI_PULSAZIONE, self._pulsa)
            threading.Thread(target=self._thread_controllo, name="controllo-aggiornamenti", daemon=True).start()
        except Exception as ex:
            scrivi_log("FinestraAggiornamento.avvia", ex)
            self._termina()

    def _pulsa(self):
        try:
            if self.fase != FASE_CONTROLLO or self._concluso:
                self._timer_pulsazione = 0
                return False
            self.barra.pulse()
            return True
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._pulsa", ex)
            self._timer_pulsazione = 0
            return False

    def _ferma_pulsazione(self):
        try:
            if self._timer_pulsazione:
                GLib.source_remove(self._timer_pulsazione)
                self._timer_pulsazione = 0
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._ferma_pulsazione", ex)

    def _aggiungi_passo(self, testo):
        try:
            self.etichetta.set_text(testo)
            riga = Gtk.ListBoxRow()
            testo_riga = Gtk.Label(label=testo)
            testo_riga.set_xalign(0)
            testo_riga.set_line_wrap(True)
            riga.add(testo_riga)
            accessibile = riga.get_accessible()
            if accessibile is not None:
                accessibile.set_name(testo)
            self.lista.add(riga)
            riga.show_all()
            self.lista.select_row(riga)
            riga.grab_focus()
        except Exception as ex:
            scrivi_log(f"FinestraAggiornamento._aggiungi_passo ({testo})", ex)

    def _thread_controllo(self):
        try:
            esito = self.aggiornatore.controlla()
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._thread_controllo", ex)
            esito = EsitoControllo(errore=str(ex))
        GLib.idle_add(self._controllo_concluso, esito)

    def _controllo_concluso(self, esito):
        try:
            if self._concluso or self.fase != FASE_CONTROLLO:
                return False
            self._ferma_pulsazione()
            if not esito.disponibile:
                self._termina()
                return False
            self.fase = FASE_DOMANDA
            self.barra.set_fraction(0)
            self.barra.set_text("")
            self._aggiungi_passo("È disponibile un aggiornamento.")
            if self._chiedi_conferma(esito):
                self._avvia_installazione()
            else:
                self._termina()
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._controllo_concluso", ex)
            self._termina()
        return False

    def _collega_escape(self, dialogo, risposta):
        try:
            dialogo.connect("key-press-event", self._tasto_nel_dialogo, risposta)
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._collega_escape", ex)

    def _tasto_nel_dialogo(self, dialogo, evento, risposta):
        try:
            if Gdk.keyval_name(evento.keyval) == "Escape":
                dialogo.response(risposta)
                return True
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._tasto_nel_dialogo", ex)
        return False

    def _chiedi_conferma(self, esito):
        dialogo = None
        try:
            dialogo = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text=f"È disponibile un aggiornamento di {percorsi.NOME_PROGRAMMA}. Installarlo adesso?",
            )
            dialogo.set_title(TITOLO_FINESTRA)
            if esito.descrizione:
                dialogo.format_secondary_text(f"Nuova versione: {esito.descrizione}")
            dialogo.set_default_response(Gtk.ResponseType.YES)
            self._collega_escape(dialogo, Gtk.ResponseType.NO)
            return dialogo.run() == Gtk.ResponseType.YES
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._chiedi_conferma", ex)
            return False
        finally:
            try:
                if dialogo is not None:
                    dialogo.destroy()
            except Exception as ex:
                scrivi_log("FinestraAggiornamento._chiedi_conferma distruzione", ex)

    def _mostra_messaggio(self, testo, dettaglio=""):
        dialogo = None
        try:
            dialogo = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.CLOSE,
                text=testo,
            )
            dialogo.set_title(TITOLO_FINESTRA)
            if dettaglio:
                dialogo.format_secondary_text(dettaglio)
            self._collega_escape(dialogo, Gtk.ResponseType.CLOSE)
            dialogo.run()
        except Exception as ex:
            scrivi_log(f"FinestraAggiornamento._mostra_messaggio ({testo})", ex)
        finally:
            try:
                if dialogo is not None:
                    dialogo.destroy()
            except Exception as ex:
                scrivi_log("FinestraAggiornamento._mostra_messaggio distruzione", ex)

    def _avvia_installazione(self):
        try:
            self.fase = FASE_INSTALLAZIONE
            self.barra.set_fraction(0)
            self.barra.set_text("0%")
            self._aggiungi_passo("Installazione dell'aggiornamento avviata. Non chiudere il programma.")
            threading.Thread(target=self._thread_installazione, name="installazione-aggiornamento", daemon=True).start()
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._avvia_installazione", ex)
            self._installazione_fallita(str(ex))

    def _thread_installazione(self):
        try:
            self.aggiornatore.installa(self._avanza_da_thread)
            GLib.idle_add(self._installazione_riuscita)
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._thread_installazione", ex)
            GLib.idle_add(self._installazione_fallita, str(ex))

    def _avanza_da_thread(self, testo, frazione):
        GLib.idle_add(self._mostra_avanzamento, testo, frazione)

    def _mostra_avanzamento(self, testo, frazione):
        try:
            valore = max(0.0, min(1.0, float(frazione)))
            self.barra.set_fraction(valore)
            self.barra.set_text(f"{int(round(valore * 100))}%")
            self._aggiungi_passo(testo)
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._mostra_avanzamento", ex)
        return False

    def _installazione_riuscita(self):
        try:
            self.fase = FASE_FINE
            self.barra.set_fraction(1.0)
            self.barra.set_text("100%")
            self._aggiungi_passo(f"Aggiornamento completato. Il programma si riavvia tra {SECONDI_RIAVVIO} secondi.")
            GLib.timeout_add_seconds(SECONDI_RIAVVIO, self._riavvia)
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._installazione_riuscita", ex)
            self._riavvia()
        return False

    def _riavvia(self):
        try:
            self.aggiornatore.riavvia()
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._riavvia", ex)
            self._mostra_messaggio(
                "Aggiornamento installato, ma il riavvio automatico non è riuscito.",
                "Chiudere il programma e riaprirlo per usare la nuova versione.",
            )
            self._termina()
        return False

    def _installazione_fallita(self, motivo):
        try:
            self.fase = FASE_FINE
            self._aggiungi_passo("Aggiornamento non riuscito.")
            self._mostra_messaggio(
                "Aggiornamento non riuscito.",
                f"Il programma parte con la versione attuale. I dettagli sono nel registro {percorsi.file_log()}.",
            )
        except Exception as ex:
            scrivi_log(f"FinestraAggiornamento._installazione_fallita ({motivo})", ex)
        self._termina()
        return False

    def _termina(self):
        try:
            if self._concluso:
                return
            self._concluso = True
            self._ferma_pulsazione()
            if self.al_termine is not None:
                self.al_termine()
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._termina", ex)

    def _tasto_premuto(self, finestra, evento):
        try:
            if Gdk.keyval_name(evento.keyval) != "Escape":
                return False
            if self.fase == FASE_CONTROLLO:
                self._aggiungi_passo("Controllo interrotto, avvio del programma.")
                self._termina()
                return True
            if self.fase == FASE_INSTALLAZIONE:
                self._aggiungi_passo("Aggiornamento in corso, attendere la fine.")
                return True
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._tasto_premuto", ex)
        return False

    def _chiusura_richiesta(self, finestra, evento):
        try:
            if self.fase == FASE_INSTALLAZIONE:
                self._aggiungi_passo("Aggiornamento in corso, la finestra non può essere chiusa adesso.")
                return True
            self._concluso = True
            self._ferma_pulsazione()
        except Exception as ex:
            scrivi_log("FinestraAggiornamento._chiusura_richiesta", ex)
        return False