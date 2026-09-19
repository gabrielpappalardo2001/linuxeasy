import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List

from app.core.log import scrivi_log

TAG_VUOTI = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
TAG_BLOCCO = {
    "address", "article", "aside", "blockquote", "caption", "center", "dd", "div", "dl", "dt", "figure",
    "footer", "header", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tbody", "thead",
    "tfoot", "tr", "ul",
}
TAG_ESCLUSI = {"audio", "button", "canvas", "figure", "iframe", "noscript", "object", "script", "style", "svg", "template", "video"}
TAG_TITOLO = {"h1": 2, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
CLASSI_ESCLUSE = {
    "catlinks", "gallery", "hatnote", "mw-authority-control", "mw-cite-backlink", "mw-editsection",
    "mw-empty-elt", "mw-references-wrap", "mw-jump-link", "noprint", "printfooter", "reference",
    "references", "reflist", "sistersitebox", "thumb", "toc", "vertical-navbox", "mw-kartographer-maplink",
    "noexcerpt", "navigation-not-searchable", "mbox-small", "side-box",
}
PREFISSI_CLASSI_ESCLUSE = ("ambox", "avviso", "infobox", "metadata", "navbox", "sinottico", "box-", "cmbox", "ombox", "tmbox")
IDENTIFICATIVI_ESCLUSI = {"coordinates", "toc", "catlinks", "mw-navigation"}
TITOLO_INTRODUZIONE = "Introduzione"


@dataclass
class Sezione:
    livello: int
    titolo: str
    righe: List[str] = field(default_factory=list)
    numero: str = ""

    @property
    def testo(self):
        return "\n".join(self.righe)


def pulisci_tex(testo):
    try:
        valore = " ".join(str(testo or "").split())
        corrispondenza = re.fullmatch(r"\{\\(?:displaystyle|textstyle)\s*(.*)\}", valore)
        if corrispondenza:
            valore = corrispondenza.group(1).strip()
        return valore
    except Exception as ex:
        scrivi_log("pulizia_html.pulisci_tex", ex)
        return str(testo or "")


class PulitoreWikipedia(HTMLParser):
    def __init__(self, solo_contenuto=False):
        super().__init__(convert_charrefs=True)
        self._solo_contenuto = solo_contenuto
        self._contenuto_tag = None
        self._contenuto_profondita = 0
        self._contenuto_finito = False
        self.sezioni = [Sezione(1, TITOLO_INTRODUZIONE)]
        self._blocco = []
        self._titolo = None
        self._livello_titolo = 0
        self._escluso = None
        self._profondita_esclusione = 0
        self._pre = 0
        self._elenchi = []
        self._prefisso = ""
        self._celle = 0

    def _da_escludere(self, tag, attributi):
        try:
            if tag in TAG_ESCLUSI:
                return True
            classi = set((attributi.get("class") or "").split())
            if classi & CLASSI_ESCLUSE:
                return True
            if any(classe.startswith(PREFISSI_CLASSI_ESCLUSE) for classe in classi):
                return True
            if (attributi.get("id") or "") in IDENTIFICATIVI_ESCLUSI:
                return True
            if (attributi.get("role") or "") in ("note", "navigation", "presentation") and tag in ("div", "table"):
                return True
            stile = (attributi.get("style") or "").replace(" ", "").lower()
            if "display:none" in stile:
                return True
            if tag == "sup" and "reference" in (attributi.get("class") or ""):
                return True
            return False
        except Exception as ex:
            scrivi_log(f"PulitoreWikipedia._da_escludere ({tag})", ex)
            return False

    def _aggiungi(self, testo):
        try:
            if self._titolo is not None:
                self._titolo.append(testo)
            else:
                self._blocco.append(testo)
        except Exception as ex:
            scrivi_log("PulitoreWikipedia._aggiungi", ex)

    def _chiudi_blocco(self):
        try:
            if self._titolo is not None:
                return
            testo = "".join(self._blocco)
            self._blocco = []
            if self._pre:
                righe = [riga.rstrip() for riga in testo.split("\n")]
            else:
                righe = [" ".join(testo.split())]
            for riga in righe:
                pulita = re.sub(r"\s+([,.;:!?)\]])", r"\1", riga) if not self._pre else riga
                pulita = re.sub(r"([(\[])\s+", r"\1", pulita) if not self._pre else pulita
                if pulita.strip(" |"):
                    self.sezioni[-1].righe.append(f"{self._prefisso}{pulita}" if self._prefisso else pulita)
            self._prefisso = ""
        except Exception as ex:
            scrivi_log("PulitoreWikipedia._chiudi_blocco", ex)

    def _fuori_dal_contenuto_inizio(self, tag, attributi):
        try:
            if not self._solo_contenuto:
                return False
            if self._contenuto_finito:
                return True
            if self._contenuto_tag is None:
                classi = (attributi.get("class") or "").split()
                if attributi.get("id") == "mw-content-text" or "mw-parser-output" in classi:
                    self._contenuto_tag = tag
                    self._contenuto_profondita = 1
                return True
            if tag == self._contenuto_tag and tag not in TAG_VUOTI:
                self._contenuto_profondita += 1
            return False
        except Exception as ex:
            scrivi_log(f"PulitoreWikipedia._fuori_dal_contenuto_inizio ({tag})", ex)
            return False

    def _fuori_dal_contenuto_fine(self, tag):
        try:
            if not self._solo_contenuto:
                return False
            if self._contenuto_finito or self._contenuto_tag is None:
                return True
            if tag == self._contenuto_tag:
                self._contenuto_profondita -= 1
                if self._contenuto_profondita <= 0:
                    self._chiudi_blocco()
                    self._contenuto_finito = True
                    return True
            return False
        except Exception as ex:
            scrivi_log(f"PulitoreWikipedia._fuori_dal_contenuto_fine ({tag})", ex)
            return False

    def handle_starttag(self, tag, attrs):
        try:
            attributi = {nome: (valore or "") for nome, valore in attrs}
            if self._fuori_dal_contenuto_inizio(tag, attributi):
                return
            if self._escluso is not None:
                if tag == self._escluso and tag not in TAG_VUOTI:
                    self._profondita_esclusione += 1
                return
            if tag == "math":
                testo = pulisci_tex(attributi.get("alttext"))
                if testo:
                    self._aggiungi(f" {testo} ")
                self._escluso = "math"
                self._profondita_esclusione = 1
                return
            if tag == "img":
                if "mwe-math-fallback" in attributi.get("class", ""):
                    testo = pulisci_tex(attributi.get("alt"))
                    if testo:
                        self._aggiungi(f" {testo} ")
                return
            if self._da_escludere(tag, attributi):
                if tag not in TAG_VUOTI:
                    self._escluso = tag
                    self._profondita_esclusione = 1
                return
            if tag in TAG_TITOLO:
                self._chiudi_blocco()
                self._titolo = []
                self._livello_titolo = TAG_TITOLO[tag]
                return
            if tag == "br":
                if self._pre:
                    self._aggiungi("\n")
                else:
                    self._chiudi_blocco()
                return
            if tag == "pre":
                self._chiudi_blocco()
                self._pre += 1
                return
            if tag in ("ul", "ol"):
                self._chiudi_blocco()
                self._elenchi.append([tag, 0])
                return
            if tag == "li":
                self._chiudi_blocco()
                rientro = "  " * max(0, len(self._elenchi) - 1)
                if self._elenchi and self._elenchi[-1][0] == "ol":
                    self._elenchi[-1][1] += 1
                    self._prefisso = f"{rientro}{self._elenchi[-1][1]}. "
                else:
                    self._prefisso = f"{rientro}- "
                return
            if tag == "tr":
                self._chiudi_blocco()
                self._celle = 0
                return
            if tag in ("td", "th"):
                if self._celle > 0:
                    self._aggiungi(" | ")
                self._celle += 1
                return
            if tag in TAG_BLOCCO:
                self._chiudi_blocco()
        except Exception as ex:
            scrivi_log(f"PulitoreWikipedia.handle_starttag ({tag})", ex)

    def handle_startendtag(self, tag, attrs):
        try:
            self.handle_starttag(tag, attrs)
            if tag not in TAG_VUOTI:
                self.handle_endtag(tag)
        except Exception as ex:
            scrivi_log(f"PulitoreWikipedia.handle_startendtag ({tag})", ex)

    def handle_endtag(self, tag):
        try:
            if self._fuori_dal_contenuto_fine(tag):
                return
            if self._escluso is not None:
                if tag == self._escluso:
                    self._profondita_esclusione -= 1
                    if self._profondita_esclusione <= 0:
                        self._escluso = None
                        self._profondita_esclusione = 0
                return
            if tag in TAG_TITOLO and self._titolo is not None:
                titolo = " ".join("".join(self._titolo).split())
                self._titolo = None
                if titolo:
                    self.sezioni.append(Sezione(self._livello_titolo, titolo))
                return
            if tag == "pre":
                self._chiudi_blocco()
                self._pre = max(0, self._pre - 1)
                return
            if tag in ("ul", "ol"):
                self._chiudi_blocco()
                if self._elenchi:
                    self._elenchi.pop()
                return
            if tag in TAG_BLOCCO or tag in ("td", "th"):
                if tag in ("td", "th"):
                    return
                self._chiudi_blocco()
        except Exception as ex:
            scrivi_log(f"PulitoreWikipedia.handle_endtag ({tag})", ex)

    def handle_data(self, data):
        try:
            if self._solo_contenuto and (self._contenuto_tag is None or self._contenuto_finito):
                return
            if self._escluso is not None or not data:
                return
            if self._pre:
                self._aggiungi(data)
            else:
                self._aggiungi(re.sub(r"\s+", " ", data))
        except Exception as ex:
            scrivi_log("PulitoreWikipedia.handle_data", ex)

    def risultato(self):
        try:
            self._chiudi_blocco()
            return self.sezioni
        except Exception as ex:
            scrivi_log("PulitoreWikipedia.risultato", ex)
            return self.sezioni


def _ha_contenuto(sezioni, indice):
    try:
        if sezioni[indice].righe:
            return True
        livello = sezioni[indice].livello
        for successiva in sezioni[indice + 1:]:
            if successiva.livello <= livello:
                break
            if successiva.righe:
                return True
        return False
    except Exception as ex:
        scrivi_log("pulizia_html._ha_contenuto", ex)
        return True


def _numera(sezioni):
    try:
        contatori = [0, 0, 0, 0, 0, 0, 0]
        for sezione in sezioni:
            if sezione.livello < 2:
                sezione.numero = ""
                continue
            livello = max(2, min(6, sezione.livello))
            contatori[livello] += 1
            for successivo in range(livello + 1, len(contatori)):
                contatori[successivo] = 0
            parti = [str(contatori[posizione]) for posizione in range(2, livello + 1) if contatori[posizione]]
            sezione.numero = ".".join(parti)
    except Exception as ex:
        scrivi_log("pulizia_html._numera", ex)


def sezioni_da_html(frammento, solo_contenuto=False):
    try:
        pulitore = PulitoreWikipedia(solo_contenuto)
        pulitore.feed(str(frammento or ""))
        pulitore.close()
        grezze = pulitore.risultato()
        sezioni = [
            sezione
            for indice, sezione in enumerate(grezze)
            if (indice == 0 and sezione.righe) or (indice > 0 and _ha_contenuto(grezze, indice))
        ]
        if not sezioni:
            sezioni = [Sezione(1, TITOLO_INTRODUZIONE)]
        _numera(sezioni)
        return sezioni
    except Exception as ex:
        scrivi_log("pulizia_html.sezioni_da_html", ex)
        return [Sezione(1, TITOLO_INTRODUZIONE, [" ".join(re.sub(r"<[^>]+>", " ", str(frammento or "")).split())])]
