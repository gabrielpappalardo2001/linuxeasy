from functools import partial
from pathlib import Path

from app.core.gestore_file import ErroreFile, FileEsistente, GestoreFile, dimensione_leggibile
from app.core.log import scrivi_log

CHIAVE_ULTIMA_CARTELLA = "ultima_cartella_salvataggio"
TITOLO_CARTELLE_PRINCIPALI = "Cartelle principali"
SCELTA_SELEZIONA = 0
SCELTA_APRI = 1
MODO_SALVA = "salva"
MODO_CARTELLA = "cartella"
MODO_FILE = "file"


class SelettoreFile:
    def __init__(self, finestra, gestore=None):
        self.finestra = finestra
        self.gestore = gestore if gestore is not None else GestoreFile()
        self.cartella = None
        self.nascosti = False
        self._modo = MODO_SALVA
        self._testo = ""
        self._nome_suggerito = ""
        self._estensione = ""
        self._estensioni = None
        self._al_termine = None
        self._titolo = ""

    def _impostazioni(self):
        return getattr(self.finestra, "impostazioni", None)

    def _cartella_di_partenza(self):
        try:
            impostazioni = self._impostazioni()
            if impostazioni is not None:
                salvata = impostazioni.leggi(CHIAVE_ULTIMA_CARTELLA, "")
                if salvata and self.gestore.e_cartella(salvata):
                    return self.gestore.normalizza(salvata)
            if self.gestore.cartella_iniziale is not None and self.gestore.e_cartella(self.gestore.cartella_iniziale):
                return self.gestore.normalizza(self.gestore.cartella_iniziale)
            return self.gestore.cartella_documenti()
        except Exception as ex:
            scrivi_log("SelettoreFile._cartella_di_partenza", ex)
            return self.gestore.cartella_home()

    def _ricorda_cartella(self, cartella):
        try:
            impostazioni = self._impostazioni()
            if impostazioni is not None:
                impostazioni.scrivi(CHIAVE_ULTIMA_CARTELLA, str(cartella))
        except Exception as ex:
            scrivi_log("SelettoreFile._ricorda_cartella", ex)

    def salva_testo(self, testo, nome_suggerito, al_termine=None, estensione=".txt", titolo="Salva in"):
        try:
            self._modo = MODO_SALVA
            self._testo = str(testo or "")
            self._nome_suggerito = self.gestore.nome_valido(nome_suggerito, "documento")
            self._estensione = estensione
            self._estensioni = (estensione,) if estensione else None
            self._al_termine = al_termine
            self._titolo = titolo
            return self._apri(self._cartella_di_partenza())
        except Exception as ex:
            scrivi_log("SelettoreFile.salva_testo", ex)
            return False

    def scegli_cartella(self, al_termine, titolo="Scegli la cartella"):
        try:
            self._modo = MODO_CARTELLA
            self._al_termine = al_termine
            self._estensioni = None
            self._titolo = titolo
            return self._apri(self._cartella_di_partenza())
        except Exception as ex:
            scrivi_log("SelettoreFile.scegli_cartella", ex)
            return False

    def scegli_file(self, al_termine, estensioni=None, titolo="Apri da"):
        try:
            self._modo = MODO_FILE
            self._al_termine = al_termine
            self._estensioni = tuple(estensioni) if estensioni else None
            self._titolo = titolo
            return self._apri(self._cartella_di_partenza())
        except Exception as ex:
            scrivi_log("SelettoreFile.scegli_file", ex)
            return False

    def _titolo_menu(self, cartella):
        return f"{self._titolo} {cartella}"

    def _verifica_cartella(self, cartella):
        try:
            self.gestore.elenco(cartella, con_file=False, nascosti=self.nascosti)
            return True
        except ErroreFile as ex:
            self.finestra.mostra_messaggio("Impossibile aprire la cartella.", str(ex))
            return False
        except Exception as ex:
            scrivi_log(f"SelettoreFile._verifica_cartella ({cartella})", ex)
            self.finestra.mostra_messaggio("Impossibile aprire la cartella.", "I dettagli sono nel file di log.")
            return False

    def _apri(self, cartella):
        try:
            destinazione = self.gestore.normalizza(cartella)
            if not self._verifica_cartella(destinazione):
                destinazione = self.gestore.cartella_home()
            self.cartella = destinazione
            return self.finestra.push_menu(self._titolo_menu(destinazione), self._voci)
        except Exception as ex:
            scrivi_log(f"SelettoreFile._apri ({cartella})", ex)
            return False

    def vai_a(self, cartella, cartella_da_evidenziare=None):
        try:
            destinazione = self.gestore.normalizza(cartella)
            if not self._verifica_cartella(destinazione):
                return False
            self.cartella = destinazione
            indice = 0
            if cartella_da_evidenziare is not None:
                for posizione, voce in enumerate(self._voci()):
                    if voce[0] == self._etichetta_cartella(cartella_da_evidenziare):
                        indice = posizione
                        break
            self.finestra.sostituisci_menu(self._titolo_menu(destinazione), self._voci, indice)
            return True
        except Exception as ex:
            scrivi_log(f"SelettoreFile.vai_a ({cartella})", ex)
            return False

    def _etichetta_cartella(self, percorso):
        return f"{Path(percorso).name}, cartella"

    def _voci(self):
        voci = []
        try:
            cartella = self.cartella or self.gestore.cartella_home()
            nome = self.gestore.nome_visualizzato(cartella)
            if self._modo == MODO_SALVA:
                voci.append((f"Salva in questa cartella: {nome}", partial(self.seleziona, cartella), None))
            elif self._modo == MODO_CARTELLA:
                voci.append((f"Scegli questa cartella: {nome}", partial(self.seleziona, cartella), None))
            superiore = self.gestore.cartella_superiore(cartella)
            if superiore is not None:
                voci.append(
                    (
                        f"Cartella superiore: {self.gestore.nome_visualizzato(superiore)}",
                        partial(self.vai_a, superiore, cartella),
                        None,
                    )
                )
            voci.append((TITOLO_CARTELLE_PRINCIPALI, self.apri_cartelle_principali, None))
            if self._modo != MODO_FILE:
                voci.append(("Crea una nuova cartella", partial(self.crea_cartella, cartella), None))
            try:
                elementi = self.gestore.elenco(
                    cartella,
                    con_file=True,
                    nascosti=self.nascosti,
                    estensioni=self._estensioni,
                )
            except ErroreFile as ex:
                scrivi_log(f"SelettoreFile._voci elenco ({cartella})", ex)
                elementi = []
            for elemento in elementi:
                if elemento.cartella:
                    voci.append(
                        (
                            self._etichetta_cartella(elemento.percorso),
                            partial(self.chiedi_azione_cartella, elemento.percorso),
                            partial(self._azioni_cartella, elemento.percorso),
                        )
                    )
                else:
                    voci.append(
                        (
                            f"{elemento.nome}, file, {dimensione_leggibile(elemento.dimensione)}",
                            partial(self.file_attivato, elemento.percorso),
                            None,
                        )
                    )
            stato = "sì" if self.nascosti else "no"
            voci.append((f"Mostra gli elementi nascosti: {stato}", self.alterna_nascosti, None))
        except Exception as ex:
            scrivi_log("SelettoreFile._voci", ex)
        return voci

    def _azioni_cartella(self, percorso):
        try:
            azioni = [("Apri la cartella", partial(self.vai_a, percorso), None)]
            if self._modo == MODO_SALVA:
                azioni.append(("Salva in questa cartella", partial(self.seleziona, percorso), None))
            elif self._modo == MODO_CARTELLA:
                azioni.append(("Scegli questa cartella", partial(self.seleziona, percorso), None))
            return azioni
        except Exception as ex:
            scrivi_log(f"SelettoreFile._azioni_cartella ({percorso})", ex)
            return []

    def chiedi_azione_cartella(self, percorso):
        try:
            nome = self.gestore.nome_visualizzato(percorso)
            if self._modo == MODO_FILE:
                self.vai_a(percorso)
                return
            etichetta = "Salva in questa cartella" if self._modo == MODO_SALVA else "Scegli questa cartella"
            scelta = self.finestra.chiedi_scelta(
                f"Cartella {nome}",
                [etichetta, "Apri la cartella"],
                "Selezionare la cartella oppure aprirla per vederne il contenuto?",
            )
            if scelta == SCELTA_SELEZIONA:
                self.seleziona(percorso)
            elif scelta == SCELTA_APRI:
                self.vai_a(percorso)
        except Exception as ex:
            scrivi_log(f"SelettoreFile.chiedi_azione_cartella ({percorso})", ex)

    def apri_cartelle_principali(self):
        try:
            voci = []
            for nome, percorso in self.gestore.cartelle_principali():
                voci.append((f"{nome}, {percorso}", partial(self._principale_scelta, percorso), None))
            self.finestra.push_menu(TITOLO_CARTELLE_PRINCIPALI, voci, "Nessuna cartella disponibile.")
        except Exception as ex:
            scrivi_log("SelettoreFile.apri_cartelle_principali", ex)

    def _principale_scelta(self, percorso):
        try:
            if self._modo == MODO_FILE:
                self.finestra.go_back()
                self.vai_a(percorso)
                return
            etichetta = "Salva in questa cartella" if self._modo == MODO_SALVA else "Scegli questa cartella"
            scelta = self.finestra.chiedi_scelta(
                f"Cartella {self.gestore.nome_visualizzato(percorso)}",
                [etichetta, "Apri la cartella"],
                "Selezionare la cartella oppure aprirla per vederne il contenuto?",
            )
            if scelta == SCELTA_SELEZIONA:
                self.finestra.go_back()
                self.seleziona(percorso)
            elif scelta == SCELTA_APRI:
                self.finestra.go_back()
                self.vai_a(percorso)
        except Exception as ex:
            scrivi_log(f"SelettoreFile._principale_scelta ({percorso})", ex)

    def alterna_nascosti(self):
        try:
            self.nascosti = not self.nascosti
            voci = self._voci()
            self.finestra.sostituisci_menu(self._titolo_menu(self.cartella), self._voci, len(voci) - 1)
        except Exception as ex:
            scrivi_log("SelettoreFile.alterna_nascosti", ex)

    def crea_cartella(self, genitore):
        try:
            nome = self.finestra.chiedi_testo("Crea una nuova cartella", f"Nome della nuova cartella in {genitore}")
            if not nome:
                return
            try:
                nuova = self.gestore.crea_cartella(genitore, nome)
            except ErroreFile as ex:
                self.finestra.mostra_messaggio("Impossibile creare la cartella.", str(ex))
                return
            self.vai_a(genitore, nuova)
            self.finestra.mostra_stato(f"Cartella creata: {nuova.name}.")
        except Exception as ex:
            scrivi_log(f"SelettoreFile.crea_cartella ({genitore})", ex)

    def file_attivato(self, percorso):
        try:
            if self._modo == MODO_FILE:
                self._concludi(percorso)
                return
            if self._modo == MODO_SALVA:
                self._chiedi_nome(Path(percorso).parent, Path(percorso).name)
        except Exception as ex:
            scrivi_log(f"SelettoreFile.file_attivato ({percorso})", ex)

    def seleziona(self, cartella):
        try:
            destinazione = self.gestore.normalizza(cartella)
            if self._modo == MODO_CARTELLA:
                self._concludi(destinazione)
                return
            if not self.gestore.scrivibile(destinazione):
                self.finestra.mostra_messaggio(
                    "Non è possibile scrivere in questa cartella.",
                    f"Scegliere un'altra cartella. Percorso: {destinazione}",
                )
                return
            self._chiedi_nome(destinazione, self.gestore.con_estensione(self._nome_suggerito, self._estensione))
        except Exception as ex:
            scrivi_log(f"SelettoreFile.seleziona ({cartella})", ex)

    def _chiedi_nome(self, cartella, nome_iniziale):
        try:
            proposta = nome_iniziale
            while True:
                nome = self.finestra.chiedi_testo("Nome del file", f"Nome del file da salvare in {cartella}", proposta)
                if not nome:
                    return
                pulito = self.gestore.nome_valido(nome)
                if not pulito:
                    self.finestra.mostra_messaggio("Il nome del file non è valido.")
                    continue
                valido = self.gestore.con_estensione(pulito, self._estensione)
                proposta = valido
                try:
                    percorso = self.gestore.salva_testo(cartella, valido, self._testo, sovrascrivi=False)
                except FileEsistente:
                    if not self.finestra.chiedi_conferma(f"Il file {valido} esiste già. Sostituirlo?"):
                        continue
                    try:
                        percorso = self.gestore.salva_testo(cartella, valido, self._testo, sovrascrivi=True)
                    except ErroreFile as ex:
                        self.finestra.mostra_messaggio("Impossibile salvare il file.", str(ex))
                        return
                except ErroreFile as ex:
                    self.finestra.mostra_messaggio("Impossibile salvare il file.", str(ex))
                    return
                self._ricorda_cartella(cartella)
                self._concludi(percorso, f"File salvato: {percorso}")
                return
        except Exception as ex:
            scrivi_log(f"SelettoreFile._chiedi_nome ({cartella})", ex)

    def _concludi(self, percorso, messaggio=""):
        try:
            if self._modo != MODO_SALVA:
                self._ricorda_cartella(percorso if Path(percorso).is_dir() else Path(percorso).parent)
            self.finestra.go_back()
            if messaggio:
                self.finestra.mostra_stato(messaggio)
            funzione = self._al_termine
            self._al_termine = None
            self._testo = ""
            if funzione is not None:
                funzione(Path(percorso))
        except Exception as ex:
            scrivi_log(f"SelettoreFile._concludi ({percorso})", ex)
