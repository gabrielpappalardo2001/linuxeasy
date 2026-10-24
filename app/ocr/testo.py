import csv
import io
import os
import re
import shutil
import statistics
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.core.log import scrivi_log

SOGLIA_PAROLA = 60.0
SOGLIA_RIGA = 70.0
SOGLIA_ZONA = 55.0
SOGLIA_ZONA_RECUPERATA = 68.0
MIN_RAPPORTO_ALFANUMERICI = 0.6
MIN_CARATTERI_PAROLA_VALIDA = 3
SOGLIA_CORREZIONE = 88.0
LUNGHEZZA_MINIMA_CORREZIONE = 4
MASSIMO_PAROLE_DIZIONARIO = 600
SECONDI_MASSIMI_DIZIONARIO = 60
FATTORE_NUOVO_PARAGRAFO = 1.45
FATTORE_SEPARATORE_CELLE = 2.5
MODELLO_ELENCO = re.compile(r"^\s*(?:[•·▪●○◦■□\-–—*]|\(?\d{1,3}[.)]|\(?[a-zA-Z][.)])\s+\S")
MODELLO_PAROLA = re.compile(r"^(\W*)(\w+)(\W*)$", re.UNICODE)
CARTELLE_DIZIONARI = (
    "/usr/share/hunspell",
    "/usr/share/myspell",
    "/usr/share/myspell/dicts",
    "/usr/local/share/hunspell",
    "/usr/share/hunspell/dicts",
)
DIZIONARI_PER_LINGUA = {
    "ita": ("it_IT",),
    "eng": ("en_US", "en_GB"),
    "fra": ("fr_FR",),
    "deu": ("de_DE",),
    "spa": ("es_ES",),
    "por": ("pt_PT", "pt_BR"),
}
SOSTITUZIONI = (
    ("rn", "m"),
    ("m", "rn"),
    ("cl", "d"),
    ("d", "cl"),
    ("vv", "w"),
    ("l", "i"),
    ("i", "l"),
    ("c", "e"),
    ("e", "c"),
    ("u", "n"),
    ("n", "u"),
    ("o", "a"),
    ("a", "o"),
    ("1", "l"),
    ("0", "o"),
    ("h", "b"),
    ("b", "h"),
)
MASSIMO_VARIANTI = 60
CONFUSIONI = (
    ("rn", "m"),
    ("cl", "d"),
    ("vv", "w"),
    ("1", "l"),
    ("0", "o"),
    ("I", "l"),
    ("l", "i"),
)


@dataclass
class Parola:
    testo: str
    confidenza: float
    sinistra: int = 0
    larghezza: int = 0


@dataclass
class Riga:
    parole: list = field(default_factory=list)
    sinistra: int = 0
    destra: int = 0
    alto: int = 0
    altezza: int = 0
    paragrafo: tuple = (0, 0)

    def testo(self):
        return " ".join(parola.testo for parola in self.parole)

    def confidenza_media(self):
        if not self.parole:
            return 0.0
        return sum(parola.confidenza for parola in self.parole) / len(self.parole)


def righe_da_tabella(tsv, soglia_parola=0.0):
    righe = {}
    try:
        lettore = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
        for voce in lettore:
            if voce.get("level") != "5":
                continue
            testo = (voce.get("text") or "").strip()
            if not testo:
                continue
            try:
                confidenza = float(voce.get("conf"))
                chiave = (
                    int(voce.get("block_num")),
                    int(voce.get("par_num")),
                    int(voce.get("line_num")),
                )
                sinistra = int(voce.get("left"))
                alto = int(voce.get("top"))
                larghezza = int(voce.get("width"))
                altezza = int(voce.get("height"))
            except (TypeError, ValueError):
                continue
            if confidenza < soglia_parola:
                continue
            riga = righe.get(chiave)
            if riga is None:
                riga = Riga(
                    sinistra=sinistra,
                    destra=sinistra + larghezza,
                    alto=alto,
                    altezza=altezza,
                    paragrafo=(chiave[0], chiave[1]),
                )
                righe[chiave] = riga
            riga.parole.append(Parola(testo, confidenza, sinistra, larghezza))
            riga.sinistra = min(riga.sinistra, sinistra)
            riga.destra = max(riga.destra, sinistra + larghezza)
            riga.alto = min(riga.alto, alto)
            riga.altezza = max(riga.altezza, altezza)
    except Exception as ex:
        scrivi_log("testo.righe_da_tabella", ex)
    return [righe[chiave] for chiave in sorted(righe)]


def riga_valida(riga):
    try:
        if not riga.parole:
            return False
        if riga.confidenza_media() < SOGLIA_RIGA:
            return False
        testo = "".join(parola.testo for parola in riga.parole)
        if not testo:
            return False
        alfanumerici = sum(1 for carattere in testo if carattere.isalnum())
        if alfanumerici / len(testo) < MIN_RAPPORTO_ALFANUMERICI:
            return False
        return any(
            sum(1 for carattere in parola.testo if carattere.isalnum()) >= MIN_CARATTERI_PAROLA_VALIDA
            for parola in riga.parole
        )
    except Exception as ex:
        scrivi_log("testo.riga_valida", ex)
        return False


def filtra_righe(righe, ignora_disegni, recuperata=False):
    try:
        if not ignora_disegni:
            return list(righe)
        valide = [riga for riga in righe if riga_valida(riga)]
        if not valide:
            return []
        parole = [parola for riga in valide for parola in riga.parole]
        media = sum(parola.confidenza for parola in parole) / len(parole)
        soglia = SOGLIA_ZONA_RECUPERATA if recuperata else SOGLIA_ZONA
        if media < soglia:
            return []
        return valide
    except Exception as ex:
        scrivi_log("testo.filtra_righe", ex)
        return list(righe)


def _unisci_righe(precedente, successiva):
    try:
        if len(precedente) >= 2 and precedente.endswith(("-", "­")):
            prima = precedente[:-1]
            if prima and prima[-1].isalpha() and successiva and successiva[0].islower():
                return prima + successiva
        return f"{precedente} {successiva}"
    except Exception as ex:
        scrivi_log("testo._unisci_righe", ex)
        return f"{precedente} {successiva}"


def _paragrafi_da_righe(righe):
    gruppi = []
    try:
        if not righe:
            return gruppi
        distanze = [
            righe[indice].alto - righe[indice - 1].alto
            for indice in range(1, len(righe))
            if righe[indice].alto > righe[indice - 1].alto
        ]
        passo = statistics.median(distanze) if distanze else 0
        altezza = statistics.median([riga.altezza for riga in righe if riga.altezza > 0] or [0])
        destra_massima = max(riga.destra for riga in righe)
        sinistra_minima = min(riga.sinistra for riga in righe)
        larghezza = max(1, destra_massima - sinistra_minima)
        corrente = [righe[0]]
        for indice in range(1, len(righe)):
            precedente = righe[indice - 1]
            riga = righe[indice]
            distanza = riga.alto - precedente.alto
            nuovo = False
            if len(distanze) >= 2 and passo > 0 and distanza > passo * FATTORE_NUOVO_PARAGRAFO:
                nuovo = True
            elif len(distanze) < 2 and altezza > 0 and distanza > altezza * 1.9:
                nuovo = True
            elif MODELLO_ELENCO.match(riga.testo()):
                nuovo = True
            elif (
                altezza > 0
                and riga.sinistra - sinistra_minima > altezza * 1.2
                and precedente.destra < destra_massima - altezza
            ):
                nuovo = True
            elif precedente.destra < sinistra_minima + larghezza * 0.5 and len(righe) > 2:
                nuovo = True
            if nuovo:
                gruppi.append(corrente)
                corrente = []
            corrente.append(riga)
        gruppi.append(corrente)
    except Exception as ex:
        scrivi_log("testo._paragrafi_da_righe", ex)
        return [list(righe)] if righe else []
    return gruppi


def impagina_testo(righe):
    try:
        paragrafi = []
        for gruppo in _paragrafi_da_righe(righe):
            testo = ""
            for riga in gruppo:
                parziale = riga.testo()
                testo = parziale if not testo else _unisci_righe(testo, parziale)
            if testo.strip():
                paragrafi.append(testo.strip())
        return "\n\n".join(paragrafi)
    except Exception as ex:
        scrivi_log("testo.impagina_testo", ex)
        return " ".join(riga.testo() for riga in righe)


def impagina_titolo(righe):
    try:
        return " ".join(riga.testo() for riga in righe if riga.parole).strip()
    except Exception as ex:
        scrivi_log("testo.impagina_titolo", ex)
        return ""


def impagina_tabella(righe):
    try:
        linee = []
        for riga in righe:
            if not riga.parole:
                continue
            soglia = max(1, riga.altezza) * FATTORE_SEPARATORE_CELLE
            pezzi = [riga.parole[0].testo]
            for indice in range(1, len(riga.parole)):
                precedente = riga.parole[indice - 1]
                parola = riga.parole[indice]
                vuoto = parola.sinistra - (precedente.sinistra + precedente.larghezza)
                pezzi.append(" | " if vuoto > soglia else " ")
                pezzi.append(parola.testo)
            linee.append("".join(pezzi).strip())
        return "\n".join(linea for linea in linee if linea)
    except Exception as ex:
        scrivi_log("testo.impagina_tabella", ex)
        return "\n".join(riga.testo() for riga in righe)


def impagina_pagina_intera(righe):
    try:
        blocchi = {}
        for riga in righe:
            blocchi.setdefault(riga.paragrafo[0], []).append(riga)
        testi = [impagina_testo(blocchi[chiave]) for chiave in sorted(blocchi)]
        return "\n\n".join(testo for testo in testi if testo)
    except Exception as ex:
        scrivi_log("testo.impagina_pagina_intera", ex)
        return ""


def _distanza(a, b):
    try:
        if a == b:
            return 0
        if abs(len(a) - len(b)) > 2:
            return 3
        precedente = list(range(len(b) + 1))
        for i, carattere_a in enumerate(a, 1):
            corrente = [i]
            for j, carattere_b in enumerate(b, 1):
                costo = 0 if carattere_a == carattere_b else 1
                corrente.append(min(corrente[j - 1] + 1, precedente[j] + 1, precedente[j - 1] + costo))
            precedente = corrente
        return precedente[-1]
    except Exception as ex:
        scrivi_log("testo._distanza", ex)
        return 3


def _normalizza_confusioni(parola):
    try:
        risultato = parola.lower()
        for errato, corretto in CONFUSIONI:
            risultato = risultato.replace(errato.lower(), corretto.lower())
        return risultato
    except Exception as ex:
        scrivi_log("testo._normalizza_confusioni", ex)
        return parola


def varianti_per_confusione(parola):
    varianti = []
    try:
        minuscola = parola.lower()
        for errata, giusta in SOSTITUZIONI:
            inizio = 0
            while True:
                posizione = minuscola.find(errata, inizio)
                if posizione < 0:
                    break
                variante = minuscola[:posizione] + giusta + minuscola[posizione + len(errata):]
                if variante != minuscola and variante not in varianti:
                    varianti.append(variante)
                inizio = posizione + 1
                if len(varianti) >= MASSIMO_VARIANTI:
                    return varianti
    except Exception as ex:
        scrivi_log(f"testo.varianti_per_confusione ({parola})", ex)
    return varianti


def _applica_maiuscole(originale, suggerita):
    try:
        if originale.isupper() and len(originale) > 1:
            return suggerita.upper()
        if originale[:1].isupper():
            return suggerita[:1].upper() + suggerita[1:]
        return suggerita
    except Exception as ex:
        scrivi_log("testo._applica_maiuscole", ex)
        return suggerita


def dizionari_per_lingua(lingua):
    nomi = []
    try:
        cartelle = [Path(cartella) for cartella in CARTELLE_DIZIONARI]
        percorso_extra = os.environ.get("DICPATH", "")
        cartelle.extend(Path(voce) for voce in percorso_extra.split(":") if voce)
        for codice in str(lingua).split("+"):
            for nome in DIZIONARI_PER_LINGUA.get(codice, ()):
                if any((cartella / f"{nome}.dic").is_file() for cartella in cartelle):
                    if nome not in nomi:
                        nomi.append(nome)
                    break
    except Exception as ex:
        scrivi_log(f"testo.dizionari_per_lingua ({lingua})", ex)
        return []
    return nomi


def correggi_confusioni_comuni(parole, lingua):
    corrette = 0
    try:
        if "ita" not in str(lingua).split("+"):
            return 0
        for parola in parole:
            if parola.testo == "II":
                parola.testo = "Il"
                corrette += 1
    except Exception as ex:
        scrivi_log("testo.correggi_confusioni_comuni", ex)
    return corrette


class CorrettoreParole:
    def __init__(self, lingua):
        self._dizionari = []
        self._programma = None
        try:
            self._programma = shutil.which("hunspell")
            if self._programma is not None:
                self._dizionari = dizionari_per_lingua(lingua)
        except Exception as ex:
            scrivi_log("CorrettoreParole.__init__", ex)
            self._programma = None
            self._dizionari = []

    def disponibile(self):
        return self._programma is not None and bool(self._dizionari)

    def _esegui(self, opzione, parole):
        try:
            risultato = subprocess.run(
                [self._programma, "-d", ",".join(self._dizionari), "-i", "utf-8", opzione],
                input="\n".join(parole) + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=SECONDI_MASSIMI_DIZIONARIO,
            )
            if risultato.returncode != 0:
                scrivi_log(f"CorrettoreParole._esegui ({opzione}) codice {risultato.returncode}: {risultato.stderr}")
                return None
            return risultato.stdout
        except Exception as ex:
            scrivi_log(f"CorrettoreParole._esegui ({opzione})", ex)
            return None

    def _sbagliate(self, parole):
        uscita = self._esegui("-l", parole)
        if uscita is None:
            return []
        return [riga.strip() for riga in uscita.splitlines() if riga.strip()]

    def _suggerimenti(self, parole):
        suggerimenti = {}
        try:
            uscita = self._esegui("-a", parole)
            if uscita is None:
                return suggerimenti
            for riga in uscita.splitlines():
                if not riga or riga[0] not in "&?":
                    continue
                testa, _separatore, coda = riga.partition(":")
                campi = testa.split()
                if len(campi) < 2:
                    continue
                elenco = [voce.strip() for voce in coda.split(",") if voce.strip()]
                suggerimenti[campi[1]] = elenco
        except Exception as ex:
            scrivi_log("CorrettoreParole._suggerimenti", ex)
        return suggerimenti

    def _variante_valida(self, originale, valide, elenco):
        try:
            if not valide:
                return None
            if len(valide) == 1:
                return valide[0]
            proposte = [voce.lower() for voce in elenco]
            comuni = [voce for voce in valide if voce in proposte]
            if len(comuni) == 1:
                return comuni[0]
            return None
        except Exception as ex:
            scrivi_log(f"CorrettoreParole._variante_valida ({originale})", ex)
            return None

    def _migliore(self, originale, elenco, confidenza):
        try:
            minuscola = originale.lower()
            migliore = None
            distanza_migliore = 99
            for suggerita in elenco[:6]:
                if " " in suggerita or "-" in suggerita or not suggerita.isalpha():
                    continue
                distanza = _distanza(minuscola, suggerita.lower())
                if _normalizza_confusioni(originale) == _normalizza_confusioni(suggerita):
                    distanza = min(distanza, 0.5)
                limite = 1
                if len(originale) >= 6 and confidenza < 75:
                    limite = 2
                if distanza <= limite and distanza < distanza_migliore:
                    migliore = suggerita
                    distanza_migliore = distanza
            if migliore is None:
                return None
            return _applica_maiuscole(originale, migliore)
        except Exception as ex:
            scrivi_log(f"CorrettoreParole._migliore ({originale})", ex)
            return None

    def correggi(self, parole):
        corrette = 0
        try:
            if not self.disponibile():
                return 0
            candidate = {}
            for parola in parole:
                if parola.confidenza >= SOGLIA_CORREZIONE:
                    continue
                corrispondenza = MODELLO_PAROLA.match(parola.testo)
                if corrispondenza is None:
                    continue
                nucleo = corrispondenza.group(2)
                if len(nucleo) < LUNGHEZZA_MINIMA_CORREZIONE or not nucleo.isalpha():
                    continue
                candidate.setdefault(nucleo, []).append(parola)
            if not candidate:
                return 0
            elenco = list(candidate)[:MASSIMO_PAROLE_DIZIONARIO]
            sbagliate = [voce for voce in self._sbagliate(elenco) if voce in candidate]
            if not sbagliate:
                return 0
            suggerimenti = self._suggerimenti(sbagliate)
            varianti = {nucleo: varianti_per_confusione(nucleo) for nucleo in sbagliate}
            tutte = sorted({voce for elenco_varianti in varianti.values() for voce in elenco_varianti})
            non_valide = set(self._sbagliate(tutte)) if tutte else set()
            for nucleo in sbagliate:
                proposte = suggerimenti.get(nucleo) or []
                valide = [voce for voce in varianti.get(nucleo, []) if voce not in non_valide]
                for parola in candidate[nucleo]:
                    scelta = self._variante_valida(nucleo, valide, proposte)
                    if scelta is not None:
                        scelta = _applica_maiuscole(nucleo, scelta)
                    elif proposte:
                        scelta = self._migliore(nucleo, proposte, parola.confidenza)
                    if scelta is None or scelta == nucleo:
                        continue
                    corrispondenza = MODELLO_PAROLA.match(parola.testo)
                    if corrispondenza is None:
                        continue
                    parola.testo = f"{corrispondenza.group(1)}{scelta}{corrispondenza.group(3)}"
                    corrette += 1
        except Exception as ex:
            scrivi_log("CorrettoreParole.correggi", ex)
        return corrette
