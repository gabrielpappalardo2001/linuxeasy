import urllib.parse
from dataclasses import dataclass, field
from typing import List

import html
import re

from app.core import rete
from app.core.log import scrivi_log
from app.news.news_parser import pulisci_righe
from app.wikipedia.pulizia_html import TITOLO_INTRODUZIONE, Sezione, sezioni_da_html

try:
    from app.news.article_text import estrai_da_html
except Exception as errore_importazione:
    estrai_da_html = None
    scrivi_log("wikipedia_client: estrazione delle notizie non disponibile", errore_importazione)

LINGUA_PREDEFINITA = "it"
TIMEOUT = 25
RISULTATI_RICERCA = 50


class ErroreWikipedia(Exception):
    pass


class PaginaNonTrovata(ErroreWikipedia):
    pass


@dataclass
class RisultatoRicerca:
    title: str
    description: str = ""
    pageid: int = 0


@dataclass
class EsitoRicerca:
    testo: str
    risultati: List[RisultatoRicerca] = field(default_factory=list)
    corretto: str = ""


@dataclass
class PaginaWiki:
    title: str
    lingua: str
    url: str
    sezioni: List[Sezione] = field(default_factory=list)
    description: str = ""

    def _titolo_sezione(self, sezione):
        try:
            return f"{sezione.numero} {sezione.titolo}" if sezione.numero else sezione.titolo
        except Exception as ex:
            scrivi_log("PaginaWiki._titolo_sezione", ex)
            return str(getattr(sezione, "titolo", ""))

    def etichetta_sezione(self, indice):
        try:
            return self._titolo_sezione(self.sezioni[indice])
        except Exception as ex:
            scrivi_log(f"PaginaWiki.etichetta_sezione ({indice})", ex)
            return ""

    def fine_sezione(self, indice):
        try:
            livello = self.sezioni[indice].livello
            fine = indice + 1
            if livello < 2:
                return fine
            while fine < len(self.sezioni) and self.sezioni[fine].livello > livello:
                fine += 1
            return fine
        except Exception as ex:
            scrivi_log(f"PaginaWiki.fine_sezione ({indice})", ex)
            return indice + 1

    def _componi(self, inizio, fine, intestazione_prima):
        try:
            righe = []
            for posizione in range(inizio, fine):
                sezione = self.sezioni[posizione]
                if intestazione_prima or posizione > inizio or sezione.livello >= 2:
                    righe.append(self._titolo_sezione(sezione))
                righe.extend(sezione.righe)
            return pulisci_righe("\n".join(righe))
        except Exception as ex:
            scrivi_log("PaginaWiki._componi", ex)
            return ""

    def testo_completo(self):
        try:
            corpo = self._componi(0, len(self.sezioni), False)
            return f"{self.title}\n\n{corpo}" if corpo else self.title
        except Exception as ex:
            scrivi_log("PaginaWiki.testo_completo", ex)
            return self.title

    def testo_sezione(self, indice):
        try:
            return self._componi(indice, self.fine_sezione(indice), True)
        except Exception as ex:
            scrivi_log(f"PaginaWiki.testo_sezione ({indice})", ex)
            return ""

    def numero_parole(self):
        try:
            return sum(len(sezione.testo.split()) for sezione in self.sezioni)
        except Exception as ex:
            scrivi_log("PaginaWiki.numero_parole", ex)
            return 0


def indirizzo_pagina(titolo, lingua=LINGUA_PREDEFINITA):
    try:
        return f"https://{lingua}.wikipedia.org/wiki/{urllib.parse.quote(str(titolo).replace(' ', '_'), safe='()_,-.:')}"
    except Exception as ex:
        scrivi_log(f"wikipedia_client.indirizzo_pagina ({titolo})", ex)
        return f"https://{lingua}.wikipedia.org/"


class WikipediaClient:
    def __init__(self, parser=None, lingua=LINGUA_PREDEFINITA):
        self.parser = parser
        self.lingua = lingua or LINGUA_PREDEFINITA

    @property
    def indirizzo_api(self):
        return f"https://{self.lingua}.wikipedia.org/w/api.php"

    def _richiesta(self, parametri):
        try:
            completi = {"format": "json", "formatversion": "2", "utf8": "1"}
            completi.update(parametri)
            if self.parser is not None:
                dati = self.parser.scarica_json(self.indirizzo_api, completi, TIMEOUT)
            else:
                dati = rete.leggi_json(self.indirizzo_api, completi, TIMEOUT)
            if not isinstance(dati, dict):
                raise ErroreWikipedia("Risposta non valida da Wikipedia")
            errore = dati.get("error")
            if isinstance(errore, dict):
                codice = str(errore.get("code") or "")
                if codice in ("missingtitle", "invalidtitle", "nosuchpageid"):
                    raise PaginaNonTrovata(str(errore.get("info") or codice))
                raise ErroreWikipedia(str(errore.get("info") or codice))
            return dati
        except ErroreWikipedia:
            raise
        except Exception as ex:
            scrivi_log(f"WikipediaClient._richiesta ({parametri.get('action')})", ex)
            raise ErroreWikipedia(str(ex)) from ex

    def _risultati(self, testo):
        try:
            return self._leggi_risultati(testo)
        except ErroreWikipedia:
            raise
        except Exception as ex:
            scrivi_log(f"WikipediaClient._risultati ({testo})", ex)
            raise ErroreWikipedia(str(ex)) from ex

    def _leggi_risultati(self, testo):
        dati = self._richiesta(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": testo,
                "gsrlimit": str(RISULTATI_RICERCA),
                "gsrnamespace": "0",
                "prop": "description",
            }
        )
        pagine = ((dati.get("query") or {}).get("pages")) or []
        pagine = sorted((pagina for pagina in pagine if isinstance(pagina, dict)), key=lambda pagina: pagina.get("index", 0))
        risultati = []
        for pagina in pagine:
            titolo = " ".join(str(pagina.get("title") or "").split())
            if titolo:
                risultati.append(
                    RisultatoRicerca(
                        title=titolo,
                        description=" ".join(str(pagina.get("description") or "").split()),
                        pageid=int(pagina.get("pageid") or 0),
                    )
                )
        return risultati

    def _suggerimento(self, testo):
        try:
            dati = self._richiesta(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": testo,
                    "srlimit": "1",
                    "srinfo": "suggestion",
                    "srprop": "",
                }
            )
            return str(((dati.get("query") or {}).get("searchinfo") or {}).get("suggestion") or "").strip()
        except Exception as ex:
            scrivi_log(f"WikipediaClient._suggerimento ({testo})", ex)
            return ""

    def cerca(self, testo):
        try:
            richiesta = " ".join(str(testo or "").split())
            esito = EsitoRicerca(testo=richiesta)
            if not richiesta:
                return esito
            esito.risultati = self._risultati(richiesta)
            if not esito.risultati:
                suggerimento = self._suggerimento(richiesta)
                if suggerimento and suggerimento.lower() != richiesta.lower():
                    esito.risultati = self._risultati(suggerimento)
                    if esito.risultati:
                        esito.corretto = suggerimento
            return esito
        except ErroreWikipedia:
            raise
        except Exception as ex:
            scrivi_log(f"WikipediaClient.cerca ({testo})", ex)
            raise ErroreWikipedia(str(ex)) from ex

    def descrizione(self, titolo):
        try:
            dati = self._richiesta({"action": "query", "prop": "description", "titles": titolo, "redirects": "1"})
            for pagina in ((dati.get("query") or {}).get("pages")) or []:
                if isinstance(pagina, dict):
                    return " ".join(str(pagina.get("description") or "").split())
            return ""
        except Exception as ex:
            scrivi_log(f"WikipediaClient.descrizione ({titolo})", ex)
            return ""

    def _pagina_web(self, titolo):
        try:
            indirizzo = indirizzo_pagina(titolo, self.lingua)
            if self.parser is not None:
                contenuto, _finale = self.parser.scarica_testo(indirizzo, TIMEOUT, consenti_browser=True)
            else:
                contenuto = rete.leggi_bytes(indirizzo, None, TIMEOUT).decode("utf-8", errors="replace")
            corrispondenza = re.search(r'<h1[^>]*id="firstHeading"[^>]*>([\s\S]*?)</h1>', contenuto)
            titolo_reale = titolo
            if corrispondenza:
                titolo_reale = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", corrispondenza.group(1))).split()) or titolo
            sezioni = sezioni_da_html(contenuto, solo_contenuto=True)
            if not any(sezione.righe for sezione in sezioni) and estrai_da_html is not None:
                testo = estrai_da_html(contenuto, indirizzo)
                if testo:
                    paragrafi = [riga for riga in testo.split("\n\n") if riga.strip()]
                    if paragrafi and " ".join(paragrafi[0].split()).lower() == " ".join(titolo_reale.split()).lower():
                        paragrafi = paragrafi[1:]
                    sezioni = [Sezione(1, TITOLO_INTRODUZIONE, paragrafi)]
            if not any(sezione.righe for sezione in sezioni):
                raise ErroreWikipedia(f"Nessun testo nella pagina {indirizzo}")
            return PaginaWiki(
                title=titolo_reale,
                lingua=self.lingua,
                url=indirizzo_pagina(titolo_reale, self.lingua),
                sezioni=sezioni,
            )
        except ErroreWikipedia:
            raise
        except Exception as ex:
            scrivi_log(f"WikipediaClient._pagina_web ({titolo})", ex)
            raise ErroreWikipedia(str(ex)) from ex

    def pagina(self, titolo):
        try:
            try:
                return self._pagina_da_api(titolo)
            except PaginaNonTrovata:
                raise
            except ErroreWikipedia as ex:
                scrivi_log(f"WikipediaClient.pagina: API non disponibile, provo la pagina web ({titolo})", ex)
                pagina = self._pagina_web(titolo)
                pagina.description = self.descrizione(pagina.title)
                return pagina
        except ErroreWikipedia:
            raise
        except Exception as ex:
            scrivi_log(f"WikipediaClient.pagina ({titolo})", ex)
            raise ErroreWikipedia(str(ex)) from ex

    def _pagina_da_api(self, titolo):
        try:
            dati = self._richiesta(
                {
                    "action": "parse",
                    "page": titolo,
                    "prop": "text",
                    "redirects": "1",
                    "disableeditsection": "1",
                    "disabletoc": "1",
                    "disablelimitreport": "1",
                }
            )
            analisi = dati.get("parse") or {}
            titolo_reale = " ".join(str(analisi.get("title") or titolo).split())
            testo = analisi.get("text")
            if isinstance(testo, dict):
                testo = testo.get("*", "")
            if not testo:
                raise PaginaNonTrovata(titolo)
            return PaginaWiki(
                title=titolo_reale,
                lingua=self.lingua,
                url=indirizzo_pagina(titolo_reale, self.lingua),
                sezioni=sezioni_da_html(testo),
                description=self.descrizione(titolo_reale),
            )
        except ErroreWikipedia:
            raise
        except Exception as ex:
            scrivi_log(f"WikipediaClient.pagina ({titolo})", ex)
            raise ErroreWikipedia(str(ex)) from ex
