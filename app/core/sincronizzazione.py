import copy
import json
import socket
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from gi.repository import Gio, GLib

from app.core import sincronizzazione_sezioni as sezioni
from app.core.log import scrivi_log

NOME_FILE = "wingabriel-sincronizzazione.json"
PREFISSO_FILE = "wingabriel-sincronizzazione"
NOME_CARTELLA = "WinGabriel"
FORMATO = "wingabriel-sincronizzazione"
VERSIONE = 1
GIORNI_ELIMINAZIONI = 180
SECONDI_INTERVALLO = 120
SECONDI_PRIMA_SINCRONIZZAZIONE = 10
SECONDI_DOPO_MODIFICA = 15
SECONDI_IGNORA_SCRITTURA_PROPRIA = 10
SECONDI_ATTESA_CHIUSURA = 60

DESTINAZIONE_NESSUNA = "nessuna"
DESTINAZIONE_ONEDRIVE = "onedrive"
DESTINAZIONE_GOOGLE_DRIVE = "googledrive"
DESTINAZIONE_CARTELLA = "cartella"

CHIAVE_DESTINAZIONE = "sincronizzazione_destinazione"
CHIAVE_CARTELLA = "sincronizzazione_cartella"
CHIAVE_RUBRICA = "sincronizzazione_rubrica"
CHIAVE_AGENDA = "sincronizzazione_agenda"
CHIAVE_RADIO = "sincronizzazione_radio"
CHIAVE_NOTIZIE = "sincronizzazione_notizie"
CHIAVE_ULTIMA = "sincronizzazione_ultima"

NOMI_MIO_DRIVE = ("Il mio Drive", "Il mio drive", "My Drive", "Mio Drive")
CARTELLE_GOOGLE_LOCALI = ("GoogleDrive", "Google Drive", "google-drive", "gdrive", "Il mio Drive", "My Drive")
ATTRIBUTI_FIGLI = "standard::name,standard::display-name,standard::type"
NOMI_SEZIONI = {
    sezioni.SEZIONE_CONTATTI: "la rubrica",
    sezioni.SEZIONE_APPUNTAMENTI: "l'agenda",
    sezioni.SEZIONE_RADIO_PREFERITI: "le radio preferite",
    sezioni.SEZIONE_RADIO_RECENTI: "le radio recenti",
    sezioni.SEZIONE_CATEGORIE_TESTATE: "le categorie delle testate",
    sezioni.SEZIONE_TESTATE: "le testate",
}


class Esito:
    def __init__(self):
        self.riuscita = False
        self.messaggio = ""
        self.avvisi = []
        self.file_aggiornato = False
        self.dati_ricevuti = False

    def testo_completo(self):
        try:
            parti = [self.messaggio] + [avviso for avviso in self.avvisi if avviso]
            return " ".join(parte for parte in parti if parte)
        except Exception as ex:
            scrivi_log("Esito.testo_completo", ex)
            return self.messaggio


class ErroreSincronizzazione(Exception):
    pass


def _figlio_per_nome(cartella, nome):
    try:
        enumeratore = cartella.enumerate_children(ATTRIBUTI_FIGLI, Gio.FileQueryInfoFlags.NONE, None)
        try:
            while True:
                informazioni = enumeratore.next_file(None)
                if informazioni is None:
                    break
                if informazioni.get_display_name() == nome or informazioni.get_name() == nome:
                    return cartella.get_child(informazioni.get_name())
        finally:
            enumeratore.close(None)
        return None
    except GLib.Error as ex:
        scrivi_log(f"sincronizzazione._figlio_per_nome ({nome})", ex)
        return None
    except Exception as ex:
        scrivi_log(f"sincronizzazione._figlio_per_nome ({nome})", ex)
        return None


def _figli_con_prefisso(cartella, prefisso, estensione):
    risultato = []
    try:
        enumeratore = cartella.enumerate_children(ATTRIBUTI_FIGLI, Gio.FileQueryInfoFlags.NONE, None)
        try:
            while True:
                informazioni = enumeratore.next_file(None)
                if informazioni is None:
                    break
                nome = informazioni.get_display_name() or informazioni.get_name()
                if nome.startswith(prefisso) and nome.lower().endswith(estensione):
                    risultato.append((nome, cartella.get_child(informazioni.get_name())))
        finally:
            enumeratore.close(None)
    except Exception as ex:
        scrivi_log(f"sincronizzazione._figli_con_prefisso ({prefisso})", ex)
    return risultato


def _assicura_cartella(radice, nome):
    try:
        esistente = _figlio_per_nome(radice, nome)
        if esistente is not None:
            return esistente
        try:
            nuova = radice.get_child_for_display_name(nome)
        except Exception as exNome:
            scrivi_log(f"sincronizzazione._assicura_cartella nome visualizzato ({nome})", exNome)
            nuova = radice.get_child(nome)
        nuova.make_directory(None)
        ritrovata = _figlio_per_nome(radice, nome)
        return ritrovata if ritrovata is not None else nuova
    except Exception as ex:
        scrivi_log(f"sincronizzazione._assicura_cartella ({nome})", ex)
        return None


def _nome_leggibile(file_gio):
    try:
        return file_gio.get_parse_name()
    except Exception as ex:
        scrivi_log("sincronizzazione._nome_leggibile", ex)
        return ""


class Sincronizzazione:
    def __init__(self, db, impostazioni, client_radio=None):
        self.db = db
        self.impostazioni = impostazioni
        self.client_radio = client_radio
        self._blocco = threading.Lock()
        self._in_corso = False
        self._al_termine = None
        self._timer_periodico = 0
        self._timer_richiesta = 0
        self._osservatore = None
        self._ultima_scrittura_propria = 0.0
        self._radio_preferite = sezioni.SezioneRadio(
            db, sezioni.SEZIONE_RADIO_PREFERITI, "radio_favorites", client_radio, 0
        )
        self._radio_recenti = sezioni.SezioneRadio(
            db, sezioni.SEZIONE_RADIO_RECENTI, "radio_recent", client_radio, sezioni.MASSIMO_RECENTI_RADIO
        )

    def _leggi(self, chiave, predefinito=""):
        try:
            if self.impostazioni is None:
                return predefinito
            return self.impostazioni.leggi(chiave, predefinito)
        except Exception as ex:
            scrivi_log(f"Sincronizzazione._leggi ({chiave})", ex)
            return predefinito

    def _scrivi(self, chiave, valore):
        try:
            if self.impostazioni is None:
                return False
            return self.impostazioni.scrivi(chiave, valore)
        except Exception as ex:
            scrivi_log(f"Sincronizzazione._scrivi ({chiave})", ex)
            return False

    def destinazione(self):
        try:
            valore = self._leggi(CHIAVE_DESTINAZIONE, DESTINAZIONE_NESSUNA)
            if valore in (DESTINAZIONE_ONEDRIVE, DESTINAZIONE_GOOGLE_DRIVE, DESTINAZIONE_CARTELLA):
                return valore
            return DESTINAZIONE_NESSUNA
        except Exception as ex:
            scrivi_log("Sincronizzazione.destinazione", ex)
            return DESTINAZIONE_NESSUNA

    def attiva(self):
        return self.destinazione() != DESTINAZIONE_NESSUNA and bool(self._leggi(CHIAVE_CARTELLA, ""))

    def descrizione_destinazione(self):
        try:
            destinazione = self.destinazione()
            if destinazione == DESTINAZIONE_ONEDRIVE:
                return "OneDrive"
            if destinazione == DESTINAZIONE_GOOGLE_DRIVE:
                return "Google Drive"
            if destinazione == DESTINAZIONE_CARTELLA:
                return "cartella scelta"
            return "nessuna"
        except Exception as ex:
            scrivi_log("Sincronizzazione.descrizione_destinazione", ex)
            return "nessuna"

    def cartella_leggibile(self):
        try:
            indirizzo = self._leggi(CHIAVE_CARTELLA, "")
            if not indirizzo:
                return ""
            return _nome_leggibile(Gio.File.new_for_uri(indirizzo))
        except Exception as ex:
            scrivi_log("Sincronizzazione.cartella_leggibile", ex)
            return ""

    def percorso_file_leggibile(self):
        try:
            cartella = self.cartella_leggibile()
            if not cartella:
                return ""
            separatore = "" if cartella.endswith("/") else "/"
            return f"{cartella}{separatore}{NOME_FILE}"
        except Exception as ex:
            scrivi_log("Sincronizzazione.percorso_file_leggibile", ex)
            return ""

    def rubrica_sincronizzata(self):
        return self._attivo(CHIAVE_RUBRICA)

    def agenda_sincronizzata(self):
        return self._attivo(CHIAVE_AGENDA)

    def radio_sincronizzate(self):
        return self._attivo(CHIAVE_RADIO)

    def notizie_sincronizzate(self):
        return self._attivo(CHIAVE_NOTIZIE)

    def _attivo(self, chiave):
        try:
            if self.impostazioni is None:
                return False
            return self.impostazioni.attivo(chiave, False)
        except Exception as ex:
            scrivi_log(f"Sincronizzazione._attivo ({chiave})", ex)
            return False

    def imposta_rubrica(self, valore):
        return self._imposta_attivo(CHIAVE_RUBRICA, valore)

    def imposta_agenda(self, valore):
        return self._imposta_attivo(CHIAVE_AGENDA, valore)

    def imposta_radio(self, valore):
        return self._imposta_attivo(CHIAVE_RADIO, valore)

    def imposta_notizie(self, valore):
        return self._imposta_attivo(CHIAVE_NOTIZIE, valore)

    def _imposta_attivo(self, chiave, valore):
        try:
            if self.impostazioni is None:
                return False
            esito = self.impostazioni.imposta_attivo(chiave, valore)
            if esito and valore:
                self.richiedi()
            return esito
        except Exception as ex:
            scrivi_log(f"Sincronizzazione._imposta_attivo ({chiave})", ex)
            return False

    def ultima_sincronizzazione(self):
        try:
            valore = self._leggi(CHIAVE_ULTIMA, "")
            if not valore:
                return ""
            momento = datetime.fromtimestamp(float(valore))
            return momento.strftime("%d/%m/%Y alle %H:%M")
        except Exception as ex:
            scrivi_log("Sincronizzazione.ultima_sincronizzazione", ex)
            return ""

    def rileva_onedrive(self):
        try:
            candidati = []
            configurazione = Path.home() / ".config" / "onedrive" / "config"
            if configurazione.is_file():
                for riga in configurazione.read_text(encoding="utf-8", errors="replace").splitlines():
                    pulita = riga.strip()
                    if pulita.startswith("#") or "=" not in pulita:
                        continue
                    chiave, valore = pulita.split("=", 1)
                    if chiave.strip() == "sync_dir":
                        candidati.append(Path(valore.strip().strip('"').strip("'")).expanduser())
            candidati.append(Path.home() / "OneDrive")
            for candidato in candidati:
                if candidato.is_dir():
                    return candidato
            return None
        except Exception as ex:
            scrivi_log("Sincronizzazione.rileva_onedrive", ex)
            return None

    def rileva_google_drive(self):
        try:
            monitor = Gio.VolumeMonitor.get()
            for montaggio in monitor.get_mounts():
                try:
                    radice = montaggio.get_root()
                    if radice is None or not radice.get_uri().startswith("google-drive://"):
                        continue
                    for nome in NOMI_MIO_DRIVE:
                        mio_drive = _figlio_per_nome(radice, nome)
                        if mio_drive is not None:
                            return mio_drive, montaggio.get_name()
                    return radice, montaggio.get_name()
                except Exception as exMontaggio:
                    scrivi_log("Sincronizzazione.rileva_google_drive montaggio", exMontaggio)
            casa = Path.home()
            candidati = [casa / nome for nome in CARTELLE_GOOGLE_LOCALI]
            insync = casa / "Insync"
            if insync.is_dir():
                for account in sorted(insync.iterdir()):
                    for nome in ("My Drive", "Il mio Drive", "Google Drive"):
                        candidati.append(account / nome)
            for candidato in candidati:
                if candidato.is_dir():
                    return Gio.File.new_for_path(str(candidato)), str(candidato)
            return None, ""
        except Exception as ex:
            scrivi_log("Sincronizzazione.rileva_google_drive", ex)
            return None, ""

    def _imposta_destinazione(self, tipo, radice, crea_sottocartella):
        try:
            if radice is None:
                return False, "La cartella di destinazione non è disponibile."
            cartella = _assicura_cartella(radice, NOME_CARTELLA) if crea_sottocartella else radice
            if cartella is None:
                return False, "Non è stato possibile creare la cartella WinGabriel."
            if not self._scrivi(CHIAVE_CARTELLA, cartella.get_uri()) or not self._scrivi(CHIAVE_DESTINAZIONE, tipo):
                return False, "Non è stato possibile salvare l'impostazione."
            self.riavvia()
            return True, f"I dati verranno sincronizzati nella cartella {_nome_leggibile(cartella)}."
        except Exception as ex:
            scrivi_log(f"Sincronizzazione._imposta_destinazione ({tipo})", ex)
            return False, "Non è stato possibile impostare la destinazione."

    def imposta_onedrive(self):
        try:
            percorso = self.rileva_onedrive()
            if percorso is None:
                return False, "OneDrive non è stato trovato su questo computer."
            return self._imposta_destinazione(DESTINAZIONE_ONEDRIVE, Gio.File.new_for_path(str(percorso)), True)
        except Exception as ex:
            scrivi_log("Sincronizzazione.imposta_onedrive", ex)
            return False, "Non è stato possibile impostare OneDrive."

    def imposta_google_drive(self):
        try:
            radice, _descrizione = self.rileva_google_drive()
            if radice is None:
                return False, "Google Drive non è stato trovato su questo computer."
            return self._imposta_destinazione(DESTINAZIONE_GOOGLE_DRIVE, radice, True)
        except Exception as ex:
            scrivi_log("Sincronizzazione.imposta_google_drive", ex)
            return False, "Non è stato possibile impostare Google Drive."

    def imposta_cartella(self, percorso):
        try:
            cartella = Path(str(percorso))
            if not cartella.is_dir():
                return False, "La cartella scelta non esiste."
            return self._imposta_destinazione(DESTINAZIONE_CARTELLA, Gio.File.new_for_path(str(cartella)), False)
        except Exception as ex:
            scrivi_log(f"Sincronizzazione.imposta_cartella ({percorso})", ex)
            return False, "Non è stato possibile impostare la cartella."

    def disattiva(self):
        try:
            esito = self._scrivi(CHIAVE_DESTINAZIONE, DESTINAZIONE_NESSUNA)
            self.ferma()
            return esito
        except Exception as ex:
            scrivi_log("Sincronizzazione.disattiva", ex)
            return False

    def avvia(self, al_termine=None):
        try:
            if al_termine is not None:
                self._al_termine = al_termine
            self.ferma()
            if not self.attiva():
                return False
            self._timer_periodico = GLib.timeout_add_seconds(SECONDI_INTERVALLO, self._a_tempo)
            self._timer_richiesta = GLib.timeout_add_seconds(SECONDI_PRIMA_SINCRONIZZAZIONE, self._richiesta_scaduta)
            self._avvia_osservatore()
            return True
        except Exception as ex:
            scrivi_log("Sincronizzazione.avvia", ex)
            return False

    def riavvia(self):
        try:
            return self.avvia(self._al_termine)
        except Exception as ex:
            scrivi_log("Sincronizzazione.riavvia", ex)
            return False

    def ferma(self):
        try:
            if self._timer_periodico:
                GLib.source_remove(self._timer_periodico)
                self._timer_periodico = 0
            if self._timer_richiesta:
                GLib.source_remove(self._timer_richiesta)
                self._timer_richiesta = 0
            if self._osservatore is not None:
                self._osservatore.cancel()
                self._osservatore = None
        except Exception as ex:
            scrivi_log("Sincronizzazione.ferma", ex)

    def _avvia_osservatore(self):
        try:
            indirizzo = self._leggi(CHIAVE_CARTELLA, "")
            if not indirizzo:
                return
            cartella = Gio.File.new_for_uri(indirizzo)
            self._osservatore = cartella.monitor_directory(Gio.FileMonitorFlags.NONE, None)
            self._osservatore.connect("changed", self._cartella_cambiata)
        except Exception as ex:
            scrivi_log("Sincronizzazione._avvia_osservatore", ex)
            self._osservatore = None

    def _cartella_cambiata(self, osservatore, file_gio, altro, evento):
        try:
            nome = file_gio.get_basename() if file_gio is not None else ""
            if not nome or not nome.startswith(PREFISSO_FILE) or not nome.lower().endswith(".json"):
                return
            if time.time() - self._ultima_scrittura_propria < SECONDI_IGNORA_SCRITTURA_PROPRIA:
                return
            self.richiedi()
        except Exception as ex:
            scrivi_log("Sincronizzazione._cartella_cambiata", ex)

    def richiedi(self):
        try:
            if not self.attiva():
                return
            if self._timer_richiesta:
                GLib.source_remove(self._timer_richiesta)
            self._timer_richiesta = GLib.timeout_add_seconds(SECONDI_DOPO_MODIFICA, self._richiesta_scaduta)
        except Exception as ex:
            scrivi_log("Sincronizzazione.richiedi", ex)

    def _richiesta_scaduta(self):
        try:
            self._timer_richiesta = 0
            self.sincronizza_in_background()
        except Exception as ex:
            scrivi_log("Sincronizzazione._richiesta_scaduta", ex)
        return False

    def _a_tempo(self):
        try:
            self.sincronizza_in_background()
        except Exception as ex:
            scrivi_log("Sincronizzazione._a_tempo", ex)
        return True

    def in_corso(self):
        return self._in_corso

    def sincronizza_in_background(self, al_termine=None):
        try:
            if self._in_corso:
                return False
            threading.Thread(
                target=self._lavoro,
                args=(al_termine,),
                name="SincronizzazioneTraComputer",
                daemon=True,
            ).start()
            return True
        except Exception as ex:
            scrivi_log("Sincronizzazione.sincronizza_in_background", ex)
            return False

    def _lavoro(self, al_termine):
        esito = None
        try:
            esito = self.sincronizza()
        except Exception as ex:
            scrivi_log("Sincronizzazione._lavoro", ex)
            esito = Esito()
            esito.messaggio = "Sincronizzazione non riuscita."
        try:
            if self._al_termine is not None:
                GLib.idle_add(self._consegna, self._al_termine, esito)
            if al_termine is not None:
                GLib.idle_add(self._consegna, al_termine, esito)
        except Exception as ex:
            scrivi_log("Sincronizzazione._lavoro consegna", ex)

    def _consegna(self, funzione, esito):
        try:
            funzione(esito)
        except Exception as ex:
            scrivi_log("Sincronizzazione._consegna", ex)
        return False

    def sincronizza_alla_chiusura(self):
        try:
            self.ferma()
            if not self.attiva():
                return
            if not self._blocco.acquire(timeout=SECONDI_ATTESA_CHIUSURA):
                return
            self._blocco.release()
            self.sincronizza()
        except Exception as ex:
            scrivi_log("Sincronizzazione.sincronizza_alla_chiusura", ex)

    def _sezioni_attive(self):
        elenco = []
        try:
            if self.rubrica_sincronizzata():
                elenco.append(sezioni.SezioneContatti(self.db))
            if self.agenda_sincronizzata():
                elenco.append(sezioni.SezioneAppuntamenti(self.db))
            if self.radio_sincronizzate():
                elenco.append(self._radio_preferite)
                elenco.append(self._radio_recenti)
            if self.notizie_sincronizzate():
                elenco.append(sezioni.SezioneCategorieTestate(self.db))
                elenco.append(sezioni.SezioneTestate(self.db))
        except Exception as ex:
            scrivi_log("Sincronizzazione._sezioni_attive", ex)
        return elenco

    def _leggi_json(self, file_gio):
        _riuscito, contenuto, _etichetta = file_gio.load_contents(None)
        testo = bytes(contenuto).decode("utf-8-sig", errors="strict")
        if not testo.strip():
            return {}
        dati = json.loads(testo)
        if not isinstance(dati, dict):
            raise ErroreSincronizzazione("Il file di sincronizzazione non contiene un oggetto JSON.")
        return dati

    def _unisci_radici(self, principale, altra):
        try:
            for nome, valore in altra.items():
                if not isinstance(valore, list):
                    continue
                attuale = principale.get(nome)
                if not isinstance(attuale, list):
                    principale[nome] = copy.deepcopy(valore)
                    continue
                indice = {}
                senza_id = []
                for voce in attuale + valore:
                    if not isinstance(voce, dict):
                        continue
                    identificativo = sezioni.testo(voce, "id")
                    if not identificativo:
                        senza_id.append(voce)
                        continue
                    esistente = indice.get(identificativo)
                    if esistente is None or sezioni.leggi_utc(sezioni.testo(voce, "modificato")) > sezioni.leggi_utc(
                        sezioni.testo(esistente, "modificato")
                    ):
                        indice[identificativo] = voce
                principale[nome] = [indice[chiave] for chiave in sorted(indice)] + senza_id
        except Exception as ex:
            scrivi_log("Sincronizzazione._unisci_radici", ex)

    def _unisci_sezione(self, sezione, voci_remote):
        risultato = []
        ricevuti = False
        try:
            limite = datetime.utcnow() - timedelta(days=GIORNI_ELIMINAZIONI)
            sezione.pulisci_eliminazioni(limite)
            sezione.prepara(voci_remote)
            remote = {}
            for voce in voci_remote:
                if not isinstance(voce, dict):
                    continue
                identificativo = sezioni.testo(voce, "id")
                if not identificativo:
                    continue
                esistente = remote.get(identificativo)
                if esistente is None or sezioni.leggi_utc(sezioni.testo(voce, "modificato")) > sezioni.leggi_utc(
                    sezioni.testo(esistente, "modificato")
                ):
                    remote[identificativo] = voce
            locale = sezione.stato_locale()
            ordine = sorted(remote) + sorted(identificativo for identificativo in locale if identificativo not in remote)
            for identificativo in ordine:
                try:
                    remota = remote.get(identificativo)
                    stato = locale.get(identificativo)
                    if remota is not None:
                        data_remota = sezioni.leggi_utc(sezioni.testo(remota, "modificato"))
                        if stato is None or data_remota > stato[0]:
                            if sezioni.vero(remota, "eliminato"):
                                applicata = sezione.applica_eliminazione(identificativo, data_remota)
                            else:
                                applicata = sezione.applica(remota)
                            if applicata:
                                ricevuti = True
                            risultato.append(remota)
                            continue
                    if stato is None:
                        continue
                    data_locale, eliminata = stato
                    if eliminata:
                        if data_locale >= limite:
                            risultato.append(
                                {"id": identificativo, "modificato": sezioni.formato_utc(data_locale), "eliminato": True}
                            )
                        continue
                    voce_locale = sezione.voce_locale(identificativo)
                    if voce_locale is not None:
                        risultato.append(voce_locale)
                    elif remota is not None:
                        risultato.append(remota)
                except Exception as exVoce:
                    scrivi_log(f"Sincronizzazione._unisci_sezione voce ({sezione.nome}, {identificativo})", exVoce)
            risultato = sezione.rifinisci(risultato)
            risultato.sort(key=lambda voce: sezioni.testo(voce, "id"))
        except Exception as ex:
            scrivi_log(f"Sincronizzazione._unisci_sezione ({sezione.nome})", ex)
            return None, False
        return risultato, ricevuti

    def _senza_intestazione(self, radice):
        try:
            return {chiave: valore for chiave, valore in radice.items() if chiave not in ("aggiornato", "dispositivo")}
        except Exception as ex:
            scrivi_log("Sincronizzazione._senza_intestazione", ex)
            return radice

    def sincronizza(self):
        esito = Esito()
        if not self._blocco.acquire(blocking=False):
            esito.messaggio = "È già in corso una sincronizzazione."
            return esito
        self._in_corso = True
        try:
            if not self.attiva():
                esito.messaggio = "La sincronizzazione non è attiva."
                return esito
            cartella = Gio.File.new_for_uri(self._leggi(CHIAVE_CARTELLA, ""))
            if not cartella.query_exists(None):
                esito.messaggio = f"La cartella di sincronizzazione non è raggiungibile: {_nome_leggibile(cartella)}."
                return esito
            principale = _figlio_per_nome(cartella, NOME_FILE)
            esisteva = principale is not None
            if esisteva:
                try:
                    radice = self._leggi_json(principale)
                except Exception as exLettura:
                    scrivi_log("Sincronizzazione.sincronizza lettura del file", exLettura)
                    esito.messaggio = "Il file di sincronizzazione non è leggibile: non è stata scritta nessuna modifica."
                    return esito
            else:
                radice = {}
                try:
                    principale = cartella.get_child_for_display_name(NOME_FILE)
                except Exception as exNome:
                    scrivi_log("Sincronizzazione.sincronizza nome del file", exNome)
                    principale = cartella.get_child(NOME_FILE)
            copie = []
            for nome, copia in _figli_con_prefisso(cartella, PREFISSO_FILE, ".json"):
                if nome == NOME_FILE:
                    continue
                try:
                    self._unisci_radici(radice, self._leggi_json(copia))
                    copie.append(copia)
                except Exception as exCopia:
                    scrivi_log(f"Sincronizzazione.sincronizza copia di conflitto ({nome})", exCopia)
            prima = copy.deepcopy(self._senza_intestazione(radice))
            for sezione in self._sezioni_attive():
                voci = radice.get(sezione.nome)
                unite, ricevuti = self._unisci_sezione(sezione, voci if isinstance(voci, list) else [])
                if unite is None:
                    esito.avvisi.append(f"Non è stato possibile sincronizzare {NOMI_SEZIONI.get(sezione.nome, sezione.nome)}.")
                    continue
                radice[sezione.nome] = unite
                if ricevuti:
                    esito.dati_ricevuti = True
            radice["formato"] = FORMATO
            radice["versione"] = VERSIONE
            if not esisteva or copie or self._senza_intestazione(radice) != prima:
                radice["aggiornato"] = sezioni.ora_utc()
                radice["dispositivo"] = socket.gethostname()
                dati = json.dumps(radice, ensure_ascii=False, indent=2).encode("utf-8")
                self._ultima_scrittura_propria = time.time()
                principale.replace_contents(dati, None, False, Gio.FileCreateFlags.REPLACE_DESTINATION, None)
                self._ultima_scrittura_propria = time.time()
                esito.file_aggiornato = True
                for copia in copie:
                    try:
                        copia.delete(None)
                    except Exception as exEliminazione:
                        scrivi_log("Sincronizzazione.sincronizza eliminazione della copia di conflitto", exEliminazione)
            self._scrivi(CHIAVE_ULTIMA, f"{time.time():.0f}")
            esito.riuscita = True
            esito.messaggio = "Sincronizzazione completata." if not esito.avvisi else "Sincronizzazione completata con alcuni avvisi."
            return esito
        except Exception as ex:
            scrivi_log("Sincronizzazione.sincronizza", ex)
            esito.riuscita = False
            esito.messaggio = "Sincronizzazione non riuscita. I dettagli sono nel file di log."
            return esito
        finally:
            self._in_corso = False
            self._blocco.release()
