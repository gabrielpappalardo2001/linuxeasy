import re
import urllib.parse
from datetime import date, datetime, timedelta
from functools import partial

from app.agenda.agenda_model import FREQUENZA_ANNUALE, MESI, Evento, leggi_data
from app.core.log import scrivi_log
from app.rubrica.rubrica_store import (
    TIPO_EMAIL,
    TIPO_INDIRIZZO,
    TIPO_SITO,
    TIPO_TELEFONO,
    Contatto,
    Valore,
    solo_cifre,
)
from app.ui.modulo_dialogo import TIPO_MULTIRIGA, TIPO_SCELTA, TIPO_SPUNTA, Campo

TITOLO_MENU = "Menu Rubrica"
TITOLO_TUTTI = "Tutti i contatti"
TITOLO_PREFERITI = "Contatti preferiti"
TITOLO_RECENTI = "Contatti recenti"
TITOLO_RICERCHE = "Ricerche recenti della rubrica"
SOGLIA_INIZIALI = 200
ERRORE_LOG = "I dettagli sono nel file di log."
ETICHETTE = {
    TIPO_TELEFONO: ["Cellulare", "Casa", "Lavoro", "Altro"],
    TIPO_EMAIL: ["Personale", "Lavoro", "Altro"],
    TIPO_INDIRIZZO: ["Casa", "Lavoro", "Altro"],
    TIPO_SITO: ["Sito web", "Lavoro", "Altro"],
}
NOMI_TIPI = {
    TIPO_TELEFONO: "numero di telefono",
    TIPO_EMAIL: "indirizzo email",
    TIPO_INDIRIZZO: "indirizzo",
    TIPO_SITO: "sito web",
}
ARTICOLI_AGGIUNTA = {
    TIPO_TELEFONO: "Aggiungi un numero di telefono",
    TIPO_EMAIL: "Aggiungi un indirizzo email",
    TIPO_INDIRIZZO: "Aggiungi un indirizzo",
    TIPO_SITO: "Aggiungi un sito web",
}


def conta(numero, singolare, plurale):
    try:
        return f"1 {singolare}" if numero == 1 else f"{numero} {plurale}"
    except Exception as ex:
        scrivi_log("rubrica_view.conta", ex)
        return str(numero)


def email_valida(testo):
    try:
        return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(testo or "").strip()) is not None
    except Exception as ex:
        scrivi_log(f"rubrica_view.email_valida ({testo})", ex)
        return False


def telefono_valido(testo):
    try:
        valore = str(testo or "").strip()
        return re.fullmatch(r"[0-9+()./\- ]+", valore) is not None and len(solo_cifre(valore).lstrip("+")) >= 3
    except Exception as ex:
        scrivi_log(f"rubrica_view.telefono_valido ({testo})", ex)
        return False


def leggi_compleanno(testo):
    try:
        valore = str(testo or "").strip()
        if not valore:
            return None, True, True
        anno_noto = re.fullmatch(r"\d{1,2}\s*[/\-. ]\s*\d{1,2}", valore) is None
        riferimento = date(2000, 1, 1) if not anno_noto else date.today()
        giorno = leggi_data(valore, riferimento)
        if giorno is None:
            return None, True, False
        return giorno, anno_noto, True
    except Exception as ex:
        scrivi_log(f"rubrica_view.leggi_compleanno ({testo})", ex)
        return None, True, False


class RubricaView:
    def __init__(self, finestra, store, agenda_view=None, selettore=None):
        self.finestra = finestra
        self.store = store
        self.agenda_view = agenda_view
        self.selettore = selettore

    def get_menu_items(self):
        try:
            return [
                (f"{TITOLO_TUTTI}, {self.store.numero()}", self.apri_tutti, None),
                ("Cerca un contatto", self.cerca, None),
                ("Ricerche recenti", self.apri_ricerche, None),
                (TITOLO_PREFERITI, self.apri_preferiti, None),
                (TITOLO_RECENTI, self.apri_recenti, None),
                ("Nuovo contatto", self.aggiungi, None),
            ]
        except Exception as ex:
            scrivi_log("RubricaView.get_menu_items", ex)
            return [("Nuovo contatto", self.aggiungi, None)]

    def _etichetta(self, contatto):
        try:
            parti = [contatto.nome_ordinato()]
            if contatto.azienda and (contatto.nome or contatto.cognome):
                parti.append(contatto.azienda)
            telefoni = contatto.di_tipo(TIPO_TELEFONO)
            email = contatto.di_tipo(TIPO_EMAIL)
            if telefoni:
                parti.append(telefoni[0].valore)
            elif email:
                parti.append(email[0].valore)
            if contatto.preferito:
                parti.append("preferito")
            return ", ".join(parti)
        except Exception as ex:
            scrivi_log("RubricaView._etichetta", ex)
            return str(getattr(contatto, "nome", ""))

    def _voci_contatti(self, contatti, recenti=False):
        voci = []
        try:
            for contatto in contatti:
                voci.append(
                    (
                        self._etichetta(contatto),
                        partial(self.apri_scheda, contatto.id),
                        partial(self._azioni_contatto, contatto.id, recenti),
                    )
                )
        except Exception as ex:
            scrivi_log("RubricaView._voci_contatti", ex)
        return voci

    def _azioni_contatto(self, identificativo, recenti=False):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None:
                return []
            azioni = [("Apri la scheda", partial(self.apri_scheda, identificativo), None)]
            telefoni = contatto.di_tipo(TIPO_TELEFONO)
            if telefoni:
                azioni.append((f"Chiama {telefoni[0].valore}", partial(self.chiama, telefoni[0].valore), None))
                azioni.append((f"Copia il numero {telefoni[0].valore}", partial(self.copia, telefoni[0].valore, "Numero copiato."), None))
            email = contatto.di_tipo(TIPO_EMAIL)
            if email:
                azioni.append((f"Scrivi a {email[0].valore}", partial(self.scrivi_email, email[0].valore), None))
            if contatto.preferito:
                azioni.append(("Rimuovi dai preferiti", partial(self.imposta_preferito, identificativo, False), None))
            else:
                azioni.append(("Aggiungi ai preferiti", partial(self.imposta_preferito, identificativo, True), None))
            azioni.append(("Modifica il contatto", partial(self.modifica, identificativo), None))
            if recenti:
                azioni.append(("Rimuovi dai contatti recenti", partial(self.rimuovi_recente, identificativo), None))
                azioni.append(("Svuota i contatti recenti", self.svuota_recenti, None))
            azioni.append(("Elimina il contatto", partial(self.elimina, identificativo), None))
            azioni.append(("Nuovo contatto", self.aggiungi, None))
            return azioni
        except Exception as ex:
            scrivi_log(f"RubricaView._azioni_contatto ({identificativo})", ex)
            return []

    def apri_tutti(self):
        try:
            totale = self.store.numero()
            if totale == 0:
                if self.finestra.chiedi_conferma("La rubrica è vuota. Creare un nuovo contatto?"):
                    self.aggiungi()
                return
            if totale <= SOGLIA_INIZIALI:
                self.finestra.push_menu(TITOLO_TUTTI, lambda: self._voci_contatti(self.store.tutti()), "La rubrica è vuota.")
                return
            self.finestra.push_menu(TITOLO_TUTTI, self._voci_iniziali, "La rubrica è vuota.")
        except Exception as ex:
            scrivi_log("RubricaView.apri_tutti", ex)

    def _voci_iniziali(self):
        voci = []
        try:
            for lettera, numero in self.store.iniziali():
                nome = "Numeri e simboli" if lettera == "#" else lettera
                voci.append((f"{nome}, {conta(numero, 'contatto', 'contatti')}", partial(self.apri_iniziale, lettera), None))
        except Exception as ex:
            scrivi_log("RubricaView._voci_iniziali", ex)
        return voci

    def apri_iniziale(self, lettera):
        try:
            nome = "numeri e simboli" if lettera == "#" else lettera
            self.finestra.push_menu(
                f"Contatti, {nome}",
                lambda: self._voci_contatti(self.store.per_iniziale(lettera)),
                "Nessun contatto con questa iniziale.",
            )
        except Exception as ex:
            scrivi_log(f"RubricaView.apri_iniziale ({lettera})", ex)

    def cerca(self):
        try:
            testo = self.finestra.chiedi_testo("Cerca un contatto", "Nome, cognome, azienda, numero o email")
            if testo:
                self.esegui_ricerca(testo)
        except Exception as ex:
            scrivi_log("RubricaView.cerca", ex)

    def esegui_ricerca(self, testo):
        try:
            self.store.aggiungi_ricerca(testo)
            self.finestra.push_menu(
                f"Contatti trovati per {testo}",
                lambda: self._voci_contatti(self.store.cerca(testo)),
                "Nessun contatto trovato.",
            )
        except Exception as ex:
            scrivi_log(f"RubricaView.esegui_ricerca ({testo})", ex)

    def apri_ricerche(self):
        try:
            self.finestra.push_menu(TITOLO_RICERCHE, self._voci_ricerche, "Nessuna ricerca recente.")
        except Exception as ex:
            scrivi_log("RubricaView.apri_ricerche", ex)

    def _voci_ricerche(self):
        voci = []
        try:
            for testo in self.store.ricerche():
                voci.append(
                    (
                        testo,
                        partial(self.esegui_ricerca, testo),
                        [
                            ("Cerca di nuovo", partial(self.esegui_ricerca, testo), None),
                            ("Rimuovi dalle ricerche recenti", partial(self.rimuovi_ricerca, testo), None),
                            ("Svuota le ricerche recenti", self.svuota_ricerche, None),
                        ],
                    )
                )
        except Exception as ex:
            scrivi_log("RubricaView._voci_ricerche", ex)
        return voci

    def rimuovi_ricerca(self, testo):
        try:
            if self.store.rimuovi_ricerca(testo):
                self.finestra.mostra_stato("Ricerca rimossa dalle recenti.")
            else:
                self.finestra.mostra_messaggio("Impossibile rimuovere la ricerca.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"RubricaView.rimuovi_ricerca ({testo})", ex)

    def svuota_ricerche(self):
        try:
            if not self.finestra.chiedi_conferma("Svuotare le ricerche recenti della rubrica?"):
                return
            if self.store.svuota_ricerche():
                self.finestra.mostra_stato("Ricerche recenti svuotate.")
            else:
                self.finestra.mostra_messaggio("Impossibile svuotare le ricerche recenti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("RubricaView.svuota_ricerche", ex)

    def apri_preferiti(self):
        try:
            self.finestra.push_menu(TITOLO_PREFERITI, lambda: self._voci_contatti(self.store.preferiti()), "Nessun contatto preferito.")
        except Exception as ex:
            scrivi_log("RubricaView.apri_preferiti", ex)

    def apri_recenti(self):
        try:
            self.finestra.push_menu(
                TITOLO_RECENTI,
                lambda: self._voci_contatti(self.store.recenti(), recenti=True),
                "Nessun contatto consultato di recente.",
            )
        except Exception as ex:
            scrivi_log("RubricaView.apri_recenti", ex)

    def rimuovi_recente(self, identificativo):
        try:
            if self.store.rimuovi_da_recenti(identificativo):
                self.finestra.mostra_stato("Contatto rimosso dai recenti.")
            else:
                self.finestra.mostra_messaggio("Impossibile rimuovere il contatto dai recenti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"RubricaView.rimuovi_recente ({identificativo})", ex)

    def svuota_recenti(self):
        try:
            if not self.finestra.chiedi_conferma("Svuotare l'elenco dei contatti recenti?"):
                return
            if self.store.svuota_recenti():
                self.finestra.mostra_stato("Elenco dei contatti recenti svuotato.")
            else:
                self.finestra.mostra_messaggio("Impossibile svuotare l'elenco dei contatti recenti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("RubricaView.svuota_recenti", ex)

    def _testo_compleanno(self, contatto):
        try:
            if contatto.compleanno is None:
                return ""
            testo = f"{contatto.compleanno.day} {MESI[contatto.compleanno.month - 1]}"
            if contatto.anno_noto:
                oggi = date.today()
                anni = oggi.year - contatto.compleanno.year - ((oggi.month, oggi.day) < (contatto.compleanno.month, contatto.compleanno.day))
                testo = f"{testo} {contatto.compleanno.year}, {conta(anni, 'anno', 'anni')}"
            return testo
        except Exception as ex:
            scrivi_log("RubricaView._testo_compleanno", ex)
            return ""

    def _titolo_scheda(self, contatto):
        return f"Contatto {contatto.nome_completo()}"

    def apri_scheda(self, identificativo):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None:
                self.finestra.mostra_messaggio("Il contatto non esiste più.")
                return
            self.store.segna_consultato(identificativo)
            self.finestra.push_menu(self._titolo_scheda(contatto), partial(self._voci_scheda, identificativo), "Il contatto non esiste più.")
        except Exception as ex:
            scrivi_log(f"RubricaView.apri_scheda ({identificativo})", ex)

    def _voci_scheda(self, identificativo):
        voci = []
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None:
                return voci
            righe = []
            if contatto.nome or contatto.cognome:
                nome = " ".join(parte for parte in (contatto.nome, contatto.cognome) if parte)
                righe.append((f"Nome: {nome}", nome, None))
            if contatto.azienda:
                righe.append((f"Azienda: {contatto.azienda}", contatto.azienda, None))
            for posizione, valore in enumerate(contatto.valori):
                righe.append(
                    (
                        f"{valore.etichetta or NOMI_TIPI.get(valore.tipo, valore.tipo)}: {valore.valore}",
                        valore.valore,
                        posizione,
                    )
                )
            if contatto.compleanno is not None:
                testo = self._testo_compleanno(contatto)
                righe.append((f"Compleanno: {testo}", testo, None))
            if contatto.note:
                for numero, riga in enumerate(riga for riga in contatto.note.splitlines() if riga.strip()):
                    righe.append((f"Note: {riga.strip()}" if numero == 0 else riga.strip(), riga.strip(), None))
            for etichetta, testo, posizione in righe:
                azioni = partial(self._azioni_riga, identificativo, posizione, testo)
                voci.append((etichetta, partial(self.finestra.apri_azioni, etichetta, azioni), azioni))
        except Exception as ex:
            scrivi_log(f"RubricaView._voci_scheda ({identificativo})", ex)
        return voci

    def _azioni_riga(self, identificativo, posizione, testo):
        try:
            azioni = []
            if posizione is not None:
                azioni.extend(self._azioni_valore(identificativo, posizione))
            else:
                azioni.append(("Copia questa informazione", partial(self.copia, testo, "Informazione copiata."), None))
            azioni.extend(self._azioni_scheda(identificativo))
            return azioni
        except Exception as ex:
            scrivi_log(f"RubricaView._azioni_riga ({identificativo}, {posizione})", ex)
            return []

    def _azioni_scheda(self, identificativo):
        azioni = []
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None:
                return azioni
            for tipo in (TIPO_TELEFONO, TIPO_EMAIL, TIPO_INDIRIZZO, TIPO_SITO):
                azioni.append((ARTICOLI_AGGIUNTA[tipo], partial(self.aggiungi_valore, identificativo, tipo), None))
            azioni.append(("Modifica il contatto", partial(self.modifica, identificativo), None))
            if contatto.preferito:
                azioni.append(("Rimuovi dai preferiti", partial(self.imposta_preferito, identificativo, False), None))
            else:
                azioni.append(("Aggiungi ai preferiti", partial(self.imposta_preferito, identificativo, True), None))
            if contatto.compleanno is not None and self.agenda_view is not None:
                azioni.append(("Aggiungi il compleanno all'agenda", partial(self.compleanno_in_agenda, identificativo), None))
            if self.selettore is not None:
                azioni.append(("Salva la scheda in un file di testo", partial(self.salva_scheda, identificativo), None))
            azioni.append(("Elimina il contatto", partial(self.elimina, identificativo), None))
        except Exception as ex:
            scrivi_log(f"RubricaView._azioni_scheda ({identificativo})", ex)
        return azioni

    def _azioni_valore(self, identificativo, posizione):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None or not 0 <= posizione < len(contatto.valori):
                return []
            valore = contatto.valori[posizione]
            azioni = []
            if valore.tipo == TIPO_TELEFONO:
                azioni.append(("Chiama", partial(self.chiama, valore.valore), None))
                azioni.append(("Invia un SMS", partial(self.invia_sms, valore.valore), None))
                azioni.append(("Copia il numero", partial(self.copia, valore.valore, "Numero copiato."), None))
            elif valore.tipo == TIPO_EMAIL:
                azioni.append(("Scrivi un'email", partial(self.scrivi_email, valore.valore), None))
                azioni.append(("Copia l'indirizzo email", partial(self.copia, valore.valore, "Indirizzo email copiato."), None))
            elif valore.tipo == TIPO_INDIRIZZO:
                azioni.append(("Apri sulla mappa", partial(self.apri_mappa, valore.valore), None))
                azioni.append(("Copia l'indirizzo", partial(self.copia, valore.valore, "Indirizzo copiato."), None))
            else:
                azioni.append(("Apri il sito", partial(self.apri_sito, valore.valore), None))
                azioni.append(("Copia l'indirizzo del sito", partial(self.copia, valore.valore, "Indirizzo copiato."), None))
            nome = NOMI_TIPI.get(valore.tipo, "valore")
            azioni.append((f"Modifica questo {nome}" if valore.tipo != TIPO_EMAIL else "Modifica questo indirizzo email", partial(self.modifica_valore, identificativo, posizione), None))
            azioni.append((f"Elimina questo {nome}" if valore.tipo != TIPO_EMAIL else "Elimina questo indirizzo email", partial(self.elimina_valore, identificativo, posizione), None))
            return azioni
        except Exception as ex:
            scrivi_log(f"RubricaView._azioni_valore ({identificativo}, {posizione})", ex)
            return []

    def _apri(self, indirizzo, errore):
        try:
            if not self.finestra.apri_nel_browser(indirizzo):
                self.finestra.mostra_messaggio(errore, "Nessun programma associato a questo tipo di collegamento.")
        except Exception as ex:
            scrivi_log(f"RubricaView._apri ({indirizzo})", ex)

    def chiama(self, numero):
        self._apri(f"tel:{solo_cifre(numero)}", "Impossibile avviare la chiamata.")

    def invia_sms(self, numero):
        self._apri(f"sms:{solo_cifre(numero)}", "Impossibile aprire il programma degli SMS.")

    def scrivi_email(self, indirizzo):
        self._apri(f"mailto:{str(indirizzo).strip()}", "Impossibile aprire il programma di posta.")

    def apri_mappa(self, indirizzo):
        self._apri(
            f"https://www.openstreetmap.org/search?query={urllib.parse.quote(str(indirizzo))}",
            "Impossibile aprire la mappa.",
        )

    def apri_sito(self, indirizzo):
        try:
            valore = str(indirizzo).strip()
            if "://" not in valore:
                valore = f"https://{valore}"
            self._apri(valore, "Impossibile aprire il sito.")
        except Exception as ex:
            scrivi_log(f"RubricaView.apri_sito ({indirizzo})", ex)

    def copia(self, testo, messaggio):
        try:
            if self.finestra.copia_negli_appunti(testo):
                self.finestra.mostra_stato(messaggio)
            else:
                self.finestra.mostra_messaggio("Impossibile copiare negli appunti.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log("RubricaView.copia", ex)

    def _campi_contatto(self, contatto, completo):
        try:
            compleanno = ""
            if contatto.compleanno is not None:
                compleanno = (
                    contatto.compleanno.strftime("%d/%m/%Y") if contatto.anno_noto else contatto.compleanno.strftime("%d/%m")
                )
            campi = [
                Campo("nome", "Nome", valore=contatto.nome),
                Campo("cognome", "Cognome", valore=contatto.cognome),
                Campo("azienda", "Azienda", valore=contatto.azienda),
            ]
            if completo:
                campi.extend(
                    [
                        Campo("cellulare", "Cellulare"),
                        Campo("casa", "Telefono di casa"),
                        Campo("lavoro", "Telefono di lavoro"),
                        Campo("email", "Email"),
                        Campo("email_lavoro", "Email di lavoro"),
                        Campo("indirizzo", "Indirizzo"),
                        Campo("sito", "Sito web"),
                    ]
                )
            campi.extend(
                [
                    Campo("compleanno", "Compleanno", valore=compleanno, suggerimento="gg/mm/aaaa oppure gg/mm"),
                    Campo("note", "Note", TIPO_MULTIRIGA, contatto.note),
                    Campo("preferito", "Contatto preferito", TIPO_SPUNTA, contatto.preferito),
                ]
            )
            return campi
        except Exception as ex:
            scrivi_log("RubricaView._campi_contatto", ex)
            return []

    def _convalida_contatto(self, valori):
        try:
            if not any(valori.get(chiave, "").strip() for chiave in ("nome", "cognome", "azienda")):
                return ("Scrivere almeno il nome, il cognome o l'azienda.", "nome")
            for chiave in ("cellulare", "casa", "lavoro"):
                testo = valori.get(chiave, "").strip()
                if testo and not telefono_valido(testo):
                    return ("Il numero di telefono non è valido.", chiave)
            for chiave in ("email", "email_lavoro"):
                testo = valori.get(chiave, "").strip()
                if testo and not email_valida(testo):
                    return ("L'indirizzo email non è valido.", chiave)
            _giorno, _anno, valido = leggi_compleanno(valori.get("compleanno"))
            if not valido:
                return ("La data del compleanno non è valida.", "compleanno")
            return None
        except Exception as ex:
            scrivi_log("RubricaView._convalida_contatto", ex)
            return ("I dati inseriti non sono validi.", None)

    def _applica_valori(self, contatto, valori):
        try:
            contatto.nome = valori.get("nome", "").strip()
            contatto.cognome = valori.get("cognome", "").strip()
            contatto.azienda = valori.get("azienda", "").strip()
            contatto.note = valori.get("note", "").strip()
            contatto.preferito = bool(valori.get("preferito"))
            giorno, anno_noto, _valido = leggi_compleanno(valori.get("compleanno"))
            contatto.compleanno = giorno
            contatto.anno_noto = anno_noto
            aggiunte = [
                ("cellulare", TIPO_TELEFONO, "Cellulare"),
                ("casa", TIPO_TELEFONO, "Casa"),
                ("lavoro", TIPO_TELEFONO, "Lavoro"),
                ("email", TIPO_EMAIL, "Personale"),
                ("email_lavoro", TIPO_EMAIL, "Lavoro"),
                ("indirizzo", TIPO_INDIRIZZO, "Casa"),
                ("sito", TIPO_SITO, "Sito web"),
            ]
            for chiave, tipo, etichetta in aggiunte:
                testo = valori.get(chiave, "").strip() if chiave in valori else ""
                if testo:
                    contatto.valori.append(Valore(tipo, etichetta, testo))
            return contatto
        except Exception as ex:
            scrivi_log("RubricaView._applica_valori", ex)
            return contatto

    def aggiungi(self):
        try:
            contatto = Contatto()
            valori = self.finestra.chiedi_modulo("Nuovo contatto", self._campi_contatto(contatto, True), self._convalida_contatto)
            if valori is None:
                return
            self._applica_valori(contatto, valori)
            if not self.store.salva(contatto):
                self.finestra.mostra_messaggio("Impossibile salvare il contatto.", ERRORE_LOG)
                return
            self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            self.finestra.mostra_stato(f"Contatto aggiunto: {contatto.nome_completo()}.")
        except Exception as ex:
            scrivi_log("RubricaView.aggiungi", ex)

    def modifica(self, identificativo):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None:
                self.finestra.mostra_messaggio("Il contatto non esiste più.")
                return
            valori = self.finestra.chiedi_modulo(
                f"Modifica {contatto.nome_completo()}",
                self._campi_contatto(contatto, False),
                self._convalida_contatto,
            )
            if valori is None:
                return
            titolo_precedente = self._titolo_scheda(contatto)
            self._applica_valori(contatto, valori)
            if not self.store.salva(contatto):
                self.finestra.mostra_messaggio("Impossibile salvare il contatto.", ERRORE_LOG)
                return
            self._aggiorna_scheda(identificativo, titolo_precedente)
            self.finestra.mostra_stato("Contatto modificato.")
        except Exception as ex:
            scrivi_log(f"RubricaView.modifica ({identificativo})", ex)

    def _aggiorna_scheda(self, identificativo, titolo_precedente):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is not None and self.finestra.titolo_corrente() == titolo_precedente:
                nuovo_titolo = self._titolo_scheda(contatto)
                if nuovo_titolo != titolo_precedente:
                    self.finestra.sostituisci_menu(
                        nuovo_titolo,
                        partial(self._voci_scheda, identificativo),
                        self.finestra.get_current_selected_index(),
                    )
                    return
            self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
        except Exception as ex:
            scrivi_log(f"RubricaView._aggiorna_scheda ({identificativo})", ex)

    def _campi_valore(self, tipo, valore=None):
        try:
            etichette = ETICHETTE.get(tipo, ["Altro"])
            attuale = valore.etichetta if valore is not None and valore.etichetta in etichette else etichette[0]
            nome = NOMI_TIPI.get(tipo, "valore")
            return [
                Campo("etichetta", "Tipo", TIPO_SCELTA, attuale, [(testo, testo) for testo in etichette]),
                Campo("valore", nome[0].upper() + nome[1:], valore=valore.valore if valore is not None else ""),
            ]
        except Exception as ex:
            scrivi_log(f"RubricaView._campi_valore ({tipo})", ex)
            return []

    def _convalida_valore(self, tipo):
        def convalida(valori):
            try:
                testo = valori.get("valore", "").strip()
                if not testo:
                    return ("Il campo è vuoto.", "valore")
                if tipo == TIPO_TELEFONO and not telefono_valido(testo):
                    return ("Il numero di telefono non è valido.", "valore")
                if tipo == TIPO_EMAIL and not email_valida(testo):
                    return ("L'indirizzo email non è valido.", "valore")
                return None
            except Exception as ex:
                scrivi_log(f"RubricaView._convalida_valore ({tipo})", ex)
                return ("Il valore non è valido.", "valore")

        return convalida

    def aggiungi_valore(self, identificativo, tipo):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None:
                return
            valori = self.finestra.chiedi_modulo(
                ARTICOLI_AGGIUNTA[tipo],
                self._campi_valore(tipo),
                self._convalida_valore(tipo),
                campo_iniziale="valore",
            )
            if valori is None:
                return
            contatto.valori.append(Valore(tipo, valori.get("etichetta", ""), valori.get("valore", "").strip()))
            if not self.store.salva(contatto):
                self.finestra.mostra_messaggio("Impossibile salvare il contatto.", ERRORE_LOG)
                return
            self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            self.finestra.mostra_stato(f"Aggiunto: {valori.get('valore', '').strip()}.")
        except Exception as ex:
            scrivi_log(f"RubricaView.aggiungi_valore ({identificativo}, {tipo})", ex)

    def modifica_valore(self, identificativo, posizione):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None or not 0 <= posizione < len(contatto.valori):
                return
            attuale = contatto.valori[posizione]
            valori = self.finestra.chiedi_modulo(
                f"Modifica {NOMI_TIPI.get(attuale.tipo, 'valore')}",
                self._campi_valore(attuale.tipo, attuale),
                self._convalida_valore(attuale.tipo),
                campo_iniziale="valore",
            )
            if valori is None:
                return
            attuale.etichetta = valori.get("etichetta", "")
            attuale.valore = valori.get("valore", "").strip()
            if not self.store.salva(contatto):
                self.finestra.mostra_messaggio("Impossibile salvare il contatto.", ERRORE_LOG)
                return
            self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            self.finestra.mostra_stato("Modifica salvata.")
        except Exception as ex:
            scrivi_log(f"RubricaView.modifica_valore ({identificativo}, {posizione})", ex)

    def elimina_valore(self, identificativo, posizione):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None or not 0 <= posizione < len(contatto.valori):
                return
            attuale = contatto.valori[posizione]
            if not self.finestra.chiedi_conferma(f"Eliminare {attuale.valore} dal contatto?"):
                return
            del contatto.valori[posizione]
            if not self.store.salva(contatto):
                self.finestra.mostra_messaggio("Impossibile salvare il contatto.", ERRORE_LOG)
                return
            self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            self.finestra.mostra_stato("Eliminato.")
        except Exception as ex:
            scrivi_log(f"RubricaView.elimina_valore ({identificativo}, {posizione})", ex)

    def imposta_preferito(self, identificativo, preferito):
        try:
            if not self.store.imposta_preferito(identificativo, preferito):
                self.finestra.mostra_messaggio("Impossibile salvare il contatto.", ERRORE_LOG)
                return
            self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            self.finestra.mostra_stato("Contatto aggiunto ai preferiti." if preferito else "Contatto rimosso dai preferiti.")
        except Exception as ex:
            scrivi_log(f"RubricaView.imposta_preferito ({identificativo})", ex)

    def elimina(self, identificativo):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None:
                return
            if not self.finestra.chiedi_conferma(f"Eliminare il contatto {contatto.nome_completo()}?"):
                return
            titolo_scheda = self._titolo_scheda(contatto)
            if not self.store.elimina(identificativo):
                self.finestra.mostra_messaggio("Impossibile eliminare il contatto.", ERRORE_LOG)
                return
            if self.finestra.titolo_corrente() == titolo_scheda:
                self.finestra.go_back()
            self.finestra.ricarica_menu_corrente(annuncia_vuoto=False)
            self.finestra.mostra_stato("Contatto eliminato.")
        except Exception as ex:
            scrivi_log(f"RubricaView.elimina ({identificativo})", ex)

    def compleanno_in_agenda(self, identificativo):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None or contatto.compleanno is None or self.agenda_view is None:
                return
            titolo = f"Compleanno di {contatto.nome_completo()}"
            if any(evento.titolo == titolo for evento in self.agenda_view.store.cerca(titolo)):
                self.finestra.mostra_messaggio("Il compleanno è già presente nell'agenda.")
                return
            anno = contatto.compleanno.year if contatto.anno_noto else date.today().year
            try:
                giorno = date(anno, contatto.compleanno.month, contatto.compleanno.day)
            except ValueError:
                giorno = date(2000, contatto.compleanno.month, contatto.compleanno.day)
            inizio = datetime.combine(giorno, datetime.min.time())
            evento = Evento(
                titolo=titolo,
                inizio=inizio,
                fine=inizio + timedelta(days=1),
                tutto_il_giorno=True,
                frequenza=FREQUENZA_ANNUALE,
                avviso_minuti=0,
            )
            if self.agenda_view.aggiungi_evento(evento):
                self.finestra.mostra_stato(f"{titolo} aggiunto all'agenda, ogni anno il {giorno.day} {MESI[giorno.month - 1]}.")
            else:
                self.finestra.mostra_messaggio("Impossibile aggiungere il compleanno all'agenda.", ERRORE_LOG)
        except Exception as ex:
            scrivi_log(f"RubricaView.compleanno_in_agenda ({identificativo})", ex)

    def testo_scheda(self, contatto):
        try:
            righe = [contatto.nome_completo()]
            if contatto.azienda and (contatto.nome or contatto.cognome):
                righe.append(f"Azienda: {contatto.azienda}")
            for valore in contatto.valori:
                righe.append(f"{valore.etichetta or NOMI_TIPI.get(valore.tipo, valore.tipo)}: {valore.valore}")
            if contatto.compleanno is not None:
                righe.append(f"Compleanno: {self._testo_compleanno(contatto)}")
            if contatto.note:
                righe.append(f"Note: {contatto.note}")
            return "\n".join(righe)
        except Exception as ex:
            scrivi_log("RubricaView.testo_scheda", ex)
            return contatto.nome_completo()

    def salva_scheda(self, identificativo):
        try:
            contatto = self.store.contatto(identificativo)
            if contatto is None or self.selettore is None:
                return
            self.selettore.salva_testo(self.testo_scheda(contatto), contatto.nome_completo())
        except Exception as ex:
            scrivi_log(f"RubricaView.salva_scheda ({identificativo})", ex)
