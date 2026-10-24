import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.log import scrivi_log
from app.ocr.analisi_pagina import (
    TIPO_IMMAGINE,
    TIPO_TABELLA,
    TIPO_TITOLO,
    AnalizzatoreLayout,
)
from app.ocr.preparazione import migliora_immagine, opencv_disponibile
from app.ocr.testo import (
    SOGLIA_PAROLA,
    CorrettoreParole,
    filtra_righe,
    correggi_confusioni_comuni,
    impagina_pagina_intera,
    impagina_tabella,
    impagina_testo,
    impagina_titolo,
    righe_da_tabella,
)

PROGRAMMI_NECESSARI = (
    ("tesseract", "tesseract-ocr"),
    ("pdfinfo", "poppler-utils"),
    ("pdftoppm", "poppler-utils"),
    ("pdftotext", "poppler-utils"),
)
ESTENSIONI_PDF = (".pdf",)
ESTENSIONI_IMMAGINI = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
ESTENSIONI_SUPPORTATE = ESTENSIONI_PDF + ESTENSIONI_IMMAGINI
LINGUA_PREDEFINITA = "ita"
RISOLUZIONE_PAGINE = 300
SOGLIA_PAROLA_ZONA = 45.0
FRAZIONE_ALTEZZA_RIGA_SINGOLA = 0.036
FRAZIONE_MARGINE_ZONA = 0.005
FRAZIONE_MINIMA_IMMAGINE = 0.015
BORDO_ZONA = 10
MIN_CARATTERI_TESTO_PDF = 40
SECONDI_MASSIMI_COMANDO = 900
SECONDI_ATTESA_CICLO = 0.25
SECONDI_ATTESA_ARRESTO = 3
SECONDI_MASSIMI_ELENCO_LINGUE = 30
MARCATORE_IMMAGINE = "[Immagine]"
MARCATORE_TABELLA = "[Tabella]"
NOMI_LINGUE = {
    "ita": "Italiano",
    "eng": "Inglese",
    "fra": "Francese",
    "deu": "Tedesco",
    "spa": "Spagnolo",
    "por": "Portoghese",
    "lat": "Latino",
    "ell": "Greco",
    "rus": "Russo",
    "nld": "Olandese",
    "ron": "Rumeno",
    "pol": "Polacco",
    "ara": "Arabo",
    "jpn": "Giapponese",
    "chi_sim": "Cinese semplificato",
}


class ErroreOcr(Exception):
    pass


class OcrAnnullato(Exception):
    pass


def ultima_riga(testo):
    try:
        for riga in reversed(str(testo or "").splitlines()):
            pulita = riga.strip()
            if pulita:
                return pulita
        return ""
    except Exception as ex:
        scrivi_log("motore_ocr.ultima_riga", ex)
        return ""


def nome_lingua(codice):
    try:
        parti = [NOMI_LINGUE.get(parte, parte) for parte in str(codice).split("+") if parte]
        if not parti:
            return str(codice)
        testo = parti[0]
        for parte in parti[1:]:
            testo = f"{testo} e {parte[:1].lower()}{parte[1:]}"
        return testo
    except Exception as ex:
        scrivi_log(f"motore_ocr.nome_lingua ({codice})", ex)
        return str(codice)


@dataclass
class OpzioniOcr:
    ignora_disegni: bool = True
    usa_testo_pdf: bool = True
    usa_rete_neurale: bool = True
    segna_immagini: bool = True
    correggi_parole: bool = True


@dataclass
class EsitoOcr:
    pagine: list = field(default_factory=list)
    pagine_con_testo: int = 0
    pagine_con_rete: int = 0
    immagini_trovate: int = 0
    tabelle_trovate: int = 0
    parole_corrette: int = 0
    avvisi: list = field(default_factory=list)

    def numero_pagine(self):
        try:
            return len(self.pagine)
        except Exception as ex:
            scrivi_log("EsitoOcr.numero_pagine", ex)
            return 0

    def testo_pagina(self, indice):
        try:
            if 0 <= indice < len(self.pagine):
                return self.pagine[indice]
            return ""
        except Exception as ex:
            scrivi_log(f"EsitoOcr.testo_pagina ({indice})", ex)
            return ""

    def testo_completo(self):
        try:
            return "\n\n".join(pagina for pagina in self.pagine if pagina)
        except Exception as ex:
            scrivi_log("EsitoOcr.testo_completo", ex)
            return ""

    def numero_parole(self, indice=None):
        try:
            testo = self.testo_completo() if indice is None else self.testo_pagina(indice)
            return len(
                [parte for parte in testo.split() if parte not in (MARCATORE_IMMAGINE, MARCATORE_TABELLA)]
            )
        except Exception as ex:
            scrivi_log("EsitoOcr.numero_parole", ex)
            return 0

    def aggiungi_avviso(self, testo):
        try:
            if testo and testo not in self.avvisi:
                self.avvisi.append(testo)
        except Exception as ex:
            scrivi_log("EsitoOcr.aggiungi_avviso", ex)


@dataclass
class _Sessione:
    lingua: str
    opzioni: OpzioniOcr
    cartella: Path
    esito: EsitoOcr
    avanza: object = None
    analizzatore: object = None
    correttore: object = None
    contatore: int = 0

    def nome_file(self, prefisso):
        self.contatore += 1
        return self.cartella / f"{prefisso}-{self.contatore}.png"


class MotoreOcr:
    def __init__(self):
        self._blocco = threading.Lock()
        self._annulla = threading.Event()
        self._processo = None
        self._in_corso = False
        self._lingue = None

    @property
    def in_corso(self):
        try:
            with self._blocco:
                return self._in_corso
        except Exception as ex:
            scrivi_log("MotoreOcr.in_corso", ex)
            return False

    def programmi_mancanti(self):
        pacchetti = []
        try:
            for programma, pacchetto in PROGRAMMI_NECESSARI:
                if shutil.which(programma) is None and pacchetto not in pacchetti:
                    pacchetti.append(pacchetto)
        except Exception as ex:
            scrivi_log("MotoreOcr.programmi_mancanti", ex)
        return pacchetti

    def lingue_disponibili(self, aggiorna=False):
        try:
            if self._lingue is not None and not aggiorna:
                return list(self._lingue)
            if shutil.which("tesseract") is None:
                return []
            risultato = subprocess.run(
                ["tesseract", "--list-langs"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=SECONDI_MASSIMI_ELENCO_LINGUE,
            )
            lingue = []
            for riga in f"{risultato.stdout}\n{risultato.stderr}".splitlines():
                nome = riga.strip()
                if not nome or nome.lower().startswith("list of") or nome == "osd":
                    continue
                if re.fullmatch(r"[A-Za-z0-9_]+", nome) and nome not in lingue:
                    lingue.append(nome)
            self._lingue = lingue
            return list(lingue)
        except Exception as ex:
            scrivi_log("MotoreOcr.lingue_disponibili", ex)
            return []

    def annulla(self):
        try:
            with self._blocco:
                if not self._in_corso:
                    return False
                self._annulla.set()
                return True
        except Exception as ex:
            scrivi_log("MotoreOcr.annulla", ex)
            return False

    def riconosci(self, percorso, lingua, opzioni=None, avanza=None):
        with self._blocco:
            if self._in_corso:
                raise ErroreOcr("Un altro riconoscimento è già in corso.")
            self._in_corso = True
            self._annulla.clear()
        try:
            return self._riconosci(Path(percorso), lingua, opzioni or OpzioniOcr(), avanza)
        finally:
            with self._blocco:
                self._in_corso = False
                self._processo = None
                self._annulla.clear()

    def _riconosci(self, percorso, lingua, opzioni, avanza):
        sessione = None
        try:
            if not percorso.is_file():
                raise ErroreOcr(f"Il file non esiste: {percorso}")
            estensione = percorso.suffix.lower()
            if estensione not in ESTENSIONI_SUPPORTATE:
                raise ErroreOcr("Formato non supportato. Sono supportati PDF, PNG, JPG, TIF e BMP.")
            mancanti = self.programmi_mancanti()
            if mancanti:
                raise ErroreOcr(f"Mancano programmi necessari. Pacchetti da installare: {', '.join(mancanti)}.")
            self._verifica_lingua(lingua)
            esito = EsitoOcr()
            with tempfile.TemporaryDirectory(prefix="linuxeasy-ocr-") as cartella:
                sessione = _Sessione(lingua, opzioni, Path(cartella), esito, avanza)
                self._prepara_sessione(sessione)
                if estensione in ESTENSIONI_PDF:
                    self._elabora_pdf(percorso, sessione)
                else:
                    self._avvisa(avanza, "Riconoscimento dell'immagine in corso.")
                    esito.pagine.append(self._testo_immagine(percorso, sessione))
            return esito
        except (ErroreOcr, OcrAnnullato):
            raise
        except Exception as ex:
            scrivi_log(f"MotoreOcr._riconosci ({percorso})", ex)
            raise ErroreOcr("Errore imprevisto durante il riconoscimento.") from ex
        finally:
            self._chiudi_sessione(sessione)

    def _chiudi_sessione(self, sessione):
        try:
            if sessione is not None and sessione.analizzatore is not None:
                sessione.analizzatore.rilascia()
                sessione.analizzatore = None
        except Exception as ex:
            scrivi_log("MotoreOcr._chiudi_sessione", ex)

    def _prepara_sessione(self, sessione):
        try:
            opzioni = sessione.opzioni
            if opzioni.usa_rete_neurale:
                self._avvisa(sessione.avanza, "Preparazione dell'analisi della pagina.")
                analizzatore = AnalizzatoreLayout()
                if analizzatore.disponibile() and analizzatore.carica():
                    sessione.analizzatore = analizzatore
                else:
                    sessione.esito.aggiungi_avviso(
                        f"Analisi della pagina con rete neurale non disponibile: {analizzatore.motivo}. "
                        "Uso il riconoscimento semplice."
                    )
            if opzioni.correggi_parole:
                correttore = CorrettoreParole(sessione.lingua)
                if correttore.disponibile():
                    sessione.correttore = correttore
                else:
                    sessione.esito.aggiungi_avviso(
                        "Correzione con il dizionario non disponibile: installare hunspell e il dizionario della lingua."
                    )
            if not opencv_disponibile():
                sessione.esito.aggiungi_avviso(
                    "OpenCV non è installato: le immagini non vengono migliorate prima del riconoscimento."
                )
        except Exception as ex:
            scrivi_log("MotoreOcr._prepara_sessione", ex)

    def _verifica_lingua(self, lingua):
        try:
            installate = self.lingue_disponibili()
            if not installate:
                return
            for codice in str(lingua).split("+"):
                if codice and codice not in installate:
                    raise ErroreOcr(
                        f"La lingua {nome_lingua(codice)} non è installata. Pacchetto da installare: tesseract-ocr-{codice.replace('_', '-')}."
                    )
        except ErroreOcr:
            raise
        except Exception as ex:
            scrivi_log(f"MotoreOcr._verifica_lingua ({lingua})", ex)

    def _avvisa(self, avanza, testo):
        try:
            if avanza is not None:
                avanza(testo)
        except Exception as ex:
            scrivi_log(f"MotoreOcr._avvisa ({testo})", ex)

    def _controlla_annullamento(self):
        if self._annulla.is_set():
            raise OcrAnnullato()

    def _elabora_pdf(self, percorso, sessione):
        try:
            totale = self._numero_pagine(percorso)
            for numero in range(1, totale + 1):
                self._controlla_annullamento()
                self._avvisa(sessione.avanza, f"Pagina {numero} di {totale}")
                testo = self._testo_presente(percorso, numero) if sessione.opzioni.usa_testo_pdf else ""
                if testo:
                    sessione.esito.pagine_con_testo += 1
                else:
                    immagine = self._immagine_pagina(percorso, numero, sessione.cartella)
                    testo = self._testo_immagine(immagine, sessione)
                    self._elimina(immagine)
                sessione.esito.pagine.append(testo)
        except (ErroreOcr, OcrAnnullato):
            raise
        except Exception as ex:
            scrivi_log(f"MotoreOcr._elabora_pdf ({percorso})", ex)
            raise ErroreOcr("Impossibile elaborare il documento PDF.") from ex

    def _numero_pagine(self, percorso):
        try:
            uscita = self._esegui(["pdfinfo", str(percorso)])
            corrispondenza = re.search(r"^Pages:\s+(\d+)", uscita, re.MULTILINE)
            if corrispondenza is None or int(corrispondenza.group(1)) < 1:
                raise ErroreOcr("Impossibile leggere il numero di pagine del PDF.")
            return int(corrispondenza.group(1))
        except (ErroreOcr, OcrAnnullato):
            raise
        except Exception as ex:
            scrivi_log(f"MotoreOcr._numero_pagine ({percorso})", ex)
            raise ErroreOcr("Impossibile leggere il documento PDF.") from ex

    def _testo_presente(self, percorso, numero):
        try:
            uscita = self._esegui(
                ["pdftotext", "-f", str(numero), "-l", str(numero), "-enc", "UTF-8", str(percorso), "-"]
            )
            testo = uscita.replace("\f", "").strip()
            alfanumerici = sum(1 for carattere in testo if carattere.isalnum())
            return testo if alfanumerici >= MIN_CARATTERI_TESTO_PDF else ""
        except OcrAnnullato:
            raise
        except Exception as ex:
            scrivi_log(f"MotoreOcr._testo_presente ({percorso}, {numero})", ex)
            return ""

    def _immagine_pagina(self, percorso, numero, cartella):
        try:
            sottocartella = cartella / f"pagina{numero}"
            sottocartella.mkdir(parents=True, exist_ok=True)
            self._esegui(
                [
                    "pdftoppm",
                    "-r",
                    str(RISOLUZIONE_PAGINE),
                    "-gray",
                    "-f",
                    str(numero),
                    "-l",
                    str(numero),
                    "-png",
                    str(percorso),
                    str(sottocartella / "p"),
                ]
            )
            immagini = sorted(sottocartella.glob("p-*.png"))
            if not immagini:
                raise ErroreOcr(f"Impossibile convertire la pagina {numero} in immagine.")
            return immagini[0]
        except (ErroreOcr, OcrAnnullato):
            raise
        except Exception as ex:
            scrivi_log(f"MotoreOcr._immagine_pagina ({percorso}, {numero})", ex)
            raise ErroreOcr(f"Impossibile convertire la pagina {numero} in immagine.") from ex

    def _testo_immagine(self, immagine, sessione):
        preparata = None
        try:
            self._controlla_annullamento()
            lavoro = Path(immagine)
            candidata = sessione.nome_file("preparata")
            if migliora_immagine(lavoro, candidata):
                preparata = candidata
                lavoro = candidata
            zone = None
            if sessione.analizzatore is not None:
                self._controlla_annullamento()
                zone = sessione.analizzatore.analizza(lavoro)
                if not zone:
                    sessione.esito.aggiungi_avviso(
                        "Per alcune pagine l'analisi con rete neurale non ha dato risultati: usato il riconoscimento semplice."
                    )
                    zone = None
            if zone:
                sessione.esito.pagine_con_rete += 1
                return self._testo_da_zone(lavoro, zone, sessione)
            return self._testo_pagina_intera(lavoro, sessione)
        except (ErroreOcr, OcrAnnullato):
            raise
        except Exception as ex:
            scrivi_log(f"MotoreOcr._testo_immagine ({immagine})", ex)
            raise ErroreOcr("Impossibile riconoscere il testo dell'immagine.") from ex
        finally:
            if preparata is not None:
                self._elimina(preparata)

    def _testo_pagina_intera(self, immagine, sessione):
        try:
            soglia = SOGLIA_PAROLA if sessione.opzioni.ignora_disegni else 0.0
            tabella = self._esegui(
                ["tesseract", str(immagine), "stdout", "-l", str(sessione.lingua), "--psm", "3", "tsv"]
            )
            blocchi = {}
            for riga in righe_da_tabella(tabella, soglia):
                blocchi.setdefault(riga.paragrafo[0], []).append(riga)
            righe = []
            for chiave in sorted(blocchi):
                righe.extend(filtra_righe(blocchi[chiave], sessione.opzioni.ignora_disegni))
            self._correggi(sessione, [parola for riga in righe for parola in riga.parole])
            return impagina_pagina_intera(righe)
        except (ErroreOcr, OcrAnnullato):
            raise
        except Exception as ex:
            scrivi_log(f"MotoreOcr._testo_pagina_intera ({immagine})", ex)
            raise ErroreOcr("Impossibile riconoscere il testo dell'immagine.") from ex

    def _correggi(self, sessione, parole):
        try:
            if not parole:
                return
            sessione.esito.parole_corrette += correggi_confusioni_comuni(parole, sessione.lingua)
            if sessione.correttore is None:
                return
            self._controlla_annullamento()
            sessione.esito.parole_corrette += sessione.correttore.correggi(parole)
        except OcrAnnullato:
            raise
        except Exception as ex:
            scrivi_log("MotoreOcr._correggi", ex)

    def _testo_da_zone(self, immagine, zone, sessione):
        try:
            import cv2

            pagina = cv2.imread(str(immagine), cv2.IMREAD_GRAYSCALE)
            if pagina is None:
                raise ErroreOcr("Impossibile leggere l'immagine della pagina.")
            altezza, larghezza = pagina.shape[:2]
            area_pagina = float(larghezza * altezza)
            blocchi = []
            for zona in zone:
                self._controlla_annullamento()
                if zona.tipo == TIPO_IMMAGINE:
                    sessione.esito.immagini_trovate += 1
                    if sessione.opzioni.segna_immagini and zona.area() >= area_pagina * FRAZIONE_MINIMA_IMMAGINE:
                        blocchi.append((zona, []))
                    continue
                righe = self._righe_zona(cv2, pagina, zona, sessione)
                if righe:
                    blocchi.append((zona, righe))
            self._correggi(sessione, [parola for _zona, righe in blocchi for riga in righe for parola in riga.parole])
            testi = []
            for zona, righe in blocchi:
                if zona.tipo == TIPO_IMMAGINE:
                    testi.append(MARCATORE_IMMAGINE)
                elif zona.tipo == TIPO_TABELLA:
                    sessione.esito.tabelle_trovate += 1
                    testi.append(f"{MARCATORE_TABELLA}\n{impagina_tabella(righe)}")
                elif zona.tipo == TIPO_TITOLO:
                    testi.append(impagina_titolo(righe))
                else:
                    testi.append(impagina_testo(righe))
            return "\n\n".join(testo for testo in testi if testo.strip())
        except (ErroreOcr, OcrAnnullato):
            raise
        except Exception as ex:
            scrivi_log(f"MotoreOcr._testo_da_zone ({immagine})", ex)
            raise ErroreOcr("Impossibile riconoscere il testo della pagina.") from ex

    def _righe_zona(self, cv2, pagina, zona, sessione):
        file_zona = None
        try:
            altezza, larghezza = pagina.shape[:2]
            margine = max(6, int(larghezza * FRAZIONE_MARGINE_ZONA))
            x0 = max(0, zona.x0 - margine)
            y0 = max(0, zona.y0 - margine)
            x1 = min(larghezza, zona.x1 + margine)
            y1 = min(altezza, zona.y1 + margine)
            ritaglio = pagina[y0:y1, x0:x1]
            if ritaglio.size == 0:
                return []
            bordato = cv2.copyMakeBorder(
                ritaglio, BORDO_ZONA, BORDO_ZONA, BORDO_ZONA, BORDO_ZONA, cv2.BORDER_CONSTANT, value=255
            )
            file_zona = sessione.nome_file("zona")
            if not cv2.imwrite(str(file_zona), bordato):
                return []
            riga_singola = zona.tipo != TIPO_TABELLA and zona.altezza() < larghezza * FRAZIONE_ALTEZZA_RIGA_SINGOLA
            soglia = 0.0
            if sessione.opzioni.ignora_disegni:
                soglia = SOGLIA_PAROLA if zona.recuperata else SOGLIA_PAROLA_ZONA
            righe = []
            for modalita in (("7", "6") if riga_singola else ("6",)):
                tabella = self._esegui(
                    ["tesseract", str(file_zona), "stdout", "-l", str(sessione.lingua), "--psm", modalita, "tsv"],
                    {"OMP_THREAD_LIMIT": "1"},
                )
                righe = righe_da_tabella(tabella, soglia)
                if righe:
                    break
            return filtra_righe(righe, sessione.opzioni.ignora_disegni, zona.recuperata)
        except (ErroreOcr, OcrAnnullato):
            raise
        except Exception as ex:
            scrivi_log("MotoreOcr._righe_zona", ex)
            return []
        finally:
            if file_zona is not None:
                self._elimina(file_zona)

    def _elimina(self, percorso):
        try:
            Path(percorso).unlink()
        except FileNotFoundError:
            pass
        except Exception as ex:
            scrivi_log(f"MotoreOcr._elimina ({percorso})", ex)

    def _ferma(self, processo):
        try:
            processo.terminate()
            try:
                processo.wait(timeout=SECONDI_ATTESA_ARRESTO)
            except subprocess.TimeoutExpired:
                processo.kill()
                processo.wait(timeout=SECONDI_ATTESA_ARRESTO)
        except Exception as ex:
            scrivi_log("MotoreOcr._ferma", ex)

    def _chiudi_flussi(self, processo):
        for flusso in (processo.stdout, processo.stderr):
            try:
                if flusso is not None and not flusso.closed:
                    flusso.close()
            except Exception as ex:
                scrivi_log("MotoreOcr._chiudi_flussi", ex)

    def _esegui(self, comando, ambiente=None):
        processo = None
        try:
            variabili = None
            if ambiente:
                variabili = dict(os.environ)
                variabili.update(ambiente)
            processo = subprocess.Popen(
                comando,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=variabili,
            )
            with self._blocco:
                self._processo = processo
            inizio = time.monotonic()
            while True:
                if self._annulla.is_set():
                    self._ferma(processo)
                    raise OcrAnnullato()
                if time.monotonic() - inizio > SECONDI_MASSIMI_COMANDO:
                    self._ferma(processo)
                    raise ErroreOcr(f"Il programma {comando[0]} non ha risposto in tempo.")
                try:
                    uscita, errori = processo.communicate(timeout=SECONDI_ATTESA_CICLO)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if processo.returncode != 0:
                scrivi_log(f"MotoreOcr._esegui ({' '.join(comando)}) codice {processo.returncode}: {errori}")
                raise ErroreOcr(f"Il programma {comando[0]} ha restituito un errore. {ultima_riga(errori)}".strip())
            return uscita
        except (ErroreOcr, OcrAnnullato):
            raise
        except FileNotFoundError as ex:
            scrivi_log(f"MotoreOcr._esegui programma non trovato ({comando[0]})", ex)
            raise ErroreOcr(f"Programma non trovato: {comando[0]}.") from ex
        except Exception as ex:
            scrivi_log(f"MotoreOcr._esegui ({comando[0]})", ex)
            raise ErroreOcr(f"Impossibile eseguire il programma {comando[0]}.") from ex
        finally:
            if processo is not None:
                self._chiudi_flussi(processo)
            with self._blocco:
                if self._processo is processo:
                    self._processo = None
