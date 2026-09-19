import gzip
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime
from html.parser import HTMLParser

from app.core import rete
from app.core.log import scrivi_log
from app.news.models import Article

try:
    import feedparser
except Exception as errore_importazione:
    feedparser = None
    scrivi_log("news_parser: impossibile importare feedparser", errore_importazione)

TEMPO_MASSIMO = 20
TEMPO_SONDAGGIO = 8
LIMITE_BYTE = 8 * 1024 * 1024
MASSIMI_TENTATIVI_FEED = 24

AGENTE = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
INTESTAZIONI_PAGINA = {
    "User-Agent": AGENTE,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "close",
}
INTESTAZIONI_FEED = dict(INTESTAZIONI_PAGINA)
INTESTAZIONI_FEED["Accept"] = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
    "application/rdf+xml;q=0.9, text/xml;q=0.9, */*;q=0.8"
)
INTESTAZIONI_JSON = dict(INTESTAZIONI_PAGINA)
INTESTAZIONI_JSON["Accept"] = "application/json, */*;q=0.8"

CODICI_DA_BROWSER = (401, 403, 405, 406, 409, 429, 500, 503)

TIPI_FEED = (
    "application/rss+xml",
    "application/atom+xml",
    "application/rdf+xml",
    "application/feed+json",
    "application/json",
    "text/xml",
    "application/xml",
)
PERCORSI_FEED = [
    "/feed/",
    "/feed",
    "/rss/",
    "/rss",
    "/rss.xml",
    "/rss.php",
    "/feed.xml",
    "/atom.xml",
    "/index.xml",
    "/feeds/posts/default",
    "/blog/feed/",
    "/news/feed/",
    "/rss/home.xml",
    "/?feed=rss2",
    "/?format=feed&type=rss",
]
INDIZI_FEED = ("rss", "feed", "atom", ".xml", "syndicat")
TAG_BLOCCO = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
    "tr", "section", "article", "header", "footer", "pre", "figcaption", "table", "dd", "dt",
}
TAG_ESCLUSI = {"script", "style", "noscript", "iframe", "svg", "form", "button", "select", "template"}


class ErroreNotizie(Exception):
    pass


class SitoNonRaggiungibile(ErroreNotizie):
    pass


class FeedNonTrovato(ErroreNotizie):
    pass


class _ConvertitoreTesto(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parti = []
        self.esclusi = 0

    def handle_starttag(self, tag, attrs):
        if tag in TAG_ESCLUSI:
            self.esclusi += 1
        elif tag in TAG_BLOCCO:
            self.parti.append("\n")

    def handle_endtag(self, tag):
        if tag in TAG_ESCLUSI:
            self.esclusi = max(0, self.esclusi - 1)
        elif tag in TAG_BLOCCO:
            self.parti.append("\n")

    def handle_data(self, data):
        if not self.esclusi:
            self.parti.append(data)


class _LettoreParagrafi(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragrafi = []
        self.corrente = None
        self.esclusi = 0

    def handle_starttag(self, tag, attrs):
        if tag in TAG_ESCLUSI:
            self.esclusi += 1
        elif tag == "p" and not self.esclusi:
            self.corrente = []

    def handle_endtag(self, tag):
        if tag in TAG_ESCLUSI:
            self.esclusi = max(0, self.esclusi - 1)
        elif tag == "p" and self.corrente is not None:
            testo = " ".join("".join(self.corrente).split())
            if len(testo) >= 40:
                self.paragrafi.append(testo)
            self.corrente = None

    def handle_data(self, data):
        if self.corrente is not None and not self.esclusi:
            self.corrente.append(data)


class _LettoreIntestazione(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.indirizzi_feed = []
        self.collegamenti = []
        self.api_wordpress = ""
        self.generatore = ""
        self.titolo = ""
        self._nel_titolo = False

    def handle_starttag(self, tag, attrs):
        try:
            attributi = {str(chiave).lower(): str(valore or "") for chiave, valore in attrs}
            if tag == "link":
                relazione = attributi.get("rel", "").lower()
                tipo = attributi.get("type", "").lower().split(";")[0].strip()
                indirizzo = attributi.get("href", "").strip()
                if not indirizzo:
                    return
                relazioni = relazione.split()
                if ("alternate" in relazioni or "feed" in relazioni) and tipo in TIPI_FEED:
                    self.indirizzi_feed.append(indirizzo)
                elif tipo in TIPI_FEED or _sembra_feed(indirizzo):
                    self.collegamenti.append(indirizzo)
                if relazione == "https://api.w.org/":
                    self.api_wordpress = indirizzo
            elif tag == "a":
                indirizzo = attributi.get("href", "").strip()
                if indirizzo and _sembra_feed(indirizzo):
                    self.collegamenti.append(indirizzo)
            elif tag == "meta" and attributi.get("name", "").lower() == "generator":
                self.generatore = attributi.get("content", "")
            elif tag == "title" and not self.titolo:
                self._nel_titolo = True
        except Exception as ex:
            scrivi_log("news_parser._LettoreIntestazione.handle_starttag", ex)

    def handle_endtag(self, tag):
        if tag == "title":
            self._nel_titolo = False

    def handle_data(self, data):
        if self._nel_titolo:
            self.titolo += data


def _sembra_feed(indirizzo):
    try:
        testo = str(indirizzo or "").lower()
        if not testo or testo.startswith(("javascript:", "mailto:", "#")):
            return False
        return any(indizio in testo for indizio in INDIZI_FEED)
    except Exception as ex:
        scrivi_log(f"news_parser._sembra_feed ({indirizzo})", ex)
        return False


def pulisci_righe(testo):
    try:
        righe = [" ".join(riga.split()) for riga in str(testo or "").splitlines()]
        return "\n\n".join(riga for riga in righe if riga)
    except Exception as ex:
        scrivi_log("news_parser.pulisci_righe", ex)
        return ""


def html_in_testo(frammento):
    try:
        if not frammento:
            return ""
        if "<" not in frammento:
            return pulisci_righe(html.unescape(frammento))
        convertitore = _ConvertitoreTesto()
        convertitore.feed(frammento)
        convertitore.close()
        return pulisci_righe("".join(convertitore.parti))
    except Exception as ex:
        scrivi_log("news_parser.html_in_testo", ex)
        return ""


def paragrafi_da_pagina(contenuto_html):
    try:
        lettore = _LettoreParagrafi()
        lettore.feed(contenuto_html or "")
        lettore.close()
        return "\n\n".join(lettore.paragrafi)
    except Exception as ex:
        scrivi_log("news_parser.paragrafi_da_pagina", ex)
        return ""


def decodifica(contenuto):
    try:
        if isinstance(contenuto, str):
            return contenuto
        corrispondenza = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', contenuto[:4096])
        if corrispondenza:
            try:
                return contenuto.decode(corrispondenza.group(1).decode("ascii"), errors="replace")
            except LookupError:
                pass
        return contenuto.decode("utf-8", errors="replace")
    except Exception as ex:
        scrivi_log("news_parser.decodifica", ex)
        return ""


def _decomprimi(dati, codifica):
    try:
        etichetta = (codifica or "").lower()
        if "gzip" in etichetta or "x-gzip" in etichetta:
            return gzip.decompress(dati)
        if "deflate" in etichetta:
            try:
                return zlib.decompress(dati)
            except zlib.error:
                return zlib.decompress(dati, -zlib.MAX_WBITS)
        return dati
    except Exception as ex:
        scrivi_log("news_parser._decomprimi", ex)
        return dati


def _data_voce(voce):
    try:
        struttura = voce.get("published_parsed") or voce.get("updated_parsed")
        if not struttura:
            return None
        return datetime(*struttura[:6])
    except Exception as ex:
        scrivi_log("news_parser._data_voce", ex)
        return None


def _base_sito(indirizzo):
    try:
        parti = urllib.parse.urlparse(indirizzo)
        return f"{parti.scheme}://{parti.netloc}"
    except Exception as ex:
        scrivi_log(f"news_parser._base_sito ({indirizzo})", ex)
        return indirizzo


def _senza_www(base):
    try:
        parti = urllib.parse.urlparse(base)
        if parti.netloc.lower().startswith("www."):
            return f"{parti.scheme}://{parti.netloc[4:]}"
        return f"{parti.scheme}://www.{parti.netloc}"
    except Exception as ex:
        scrivi_log(f"news_parser._senza_www ({base})", ex)
        return base


def candidati_indirizzo(indirizzo):
    try:
        testo = str(indirizzo or "").strip()
        if not testo:
            return []
        if "://" in testo:
            return [testo]
        testo = testo.lstrip("/")
        candidati = [f"https://{testo}"]
        if not testo.lower().startswith("www."):
            candidati.append(f"https://www.{testo}")
        candidati.append(f"http://{testo}")
        return candidati
    except Exception as ex:
        scrivi_log(f"news_parser.candidati_indirizzo ({indirizzo})", ex)
        return []


class NewsParser:
    def __init__(self, browser=None, timeout=TEMPO_MASSIMO):
        self.browser = browser
        self.timeout = timeout


    def _richiedi(self, indirizzo, intestazioni, timeout):
        richiesta = urllib.request.Request(indirizzo, headers=dict(intestazioni))
        with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
            dati = risposta.read(LIMITE_BYTE)
            dati = _decomprimi(dati, risposta.headers.get("Content-Encoding"))
            return dati, risposta.geturl()

    def _con_browser(self, indirizzo):
        try:
            if self.browser is None or not self.browser.disponibile():
                return None
            testo = self.browser.scarica_html(indirizzo)
            return testo.encode("utf-8") if testo else None
        except Exception as ex:
            scrivi_log(f"NewsParser._con_browser ({indirizzo})", ex)
            return None

    def _scarica(self, indirizzo, feed=False, timeout=None, consenti_browser=True, intestazioni=None):
        attesa = timeout or self.timeout
        if intestazioni is None:
            intestazioni = INTESTAZIONI_FEED if feed else INTESTAZIONI_PAGINA
        try:
            return self._richiedi(indirizzo, intestazioni, attesa)
        except urllib.error.HTTPError as ex:
            scrivi_log(f"NewsParser._scarica: risposta {ex.code} da {indirizzo}", ex)
            if consenti_browser and ex.code in CODICI_DA_BROWSER:
                dati = self._con_browser(indirizzo)
                if dati:
                    return dati, indirizzo
            return b"", indirizzo
        except Exception as ex:
            scrivi_log(f"NewsParser._scarica ({indirizzo})", ex)
        try:
            dati = rete.leggi_bytes(indirizzo, None, attesa)
            if dati:
                return dati, indirizzo
        except Exception as ex:
            scrivi_log(f"NewsParser._scarica con rete.leggi_bytes ({indirizzo})", ex)
        if consenti_browser:
            dati = self._con_browser(indirizzo)
            if dati:
                return dati, indirizzo
        return None

    def _scarica_pagina(self, indirizzo):
        risultato = self._scarica(indirizzo)
        return None if risultato is None else risultato[0]

    def scarica_testo(self, indirizzo, timeout=None, consenti_browser=True):
        try:
            risultato = self._scarica(indirizzo, timeout=timeout, consenti_browser=consenti_browser)
            if risultato is None:
                raise SitoNonRaggiungibile(f"Sito non raggiungibile: {indirizzo}")
            dati, finale = risultato
            if not dati:
                raise ErroreNotizie(f"Il sito ha rifiutato la richiesta: {indirizzo}")
            return decodifica(dati), finale
        except ErroreNotizie:
            raise
        except Exception as ex:
            scrivi_log(f"NewsParser.scarica_testo ({indirizzo})", ex)
            raise ErroreNotizie(str(ex)) from ex

    def scarica_json(self, indirizzo, parametri=None, timeout=None):
        completo = indirizzo
        try:
            if parametri:
                completo = f"{indirizzo}?{urllib.parse.urlencode(parametri)}"
            risultato = self._scarica(
                completo,
                timeout=timeout,
                consenti_browser=False,
                intestazioni=INTESTAZIONI_JSON,
            )
            if risultato is None:
                raise SitoNonRaggiungibile(f"Sito non raggiungibile: {indirizzo}")
            if not risultato[0]:
                raise ErroreNotizie(f"Il sito ha rifiutato la richiesta: {indirizzo}")
            return json.loads(risultato[0].decode("utf-8", errors="replace"))
        except ErroreNotizie:
            raise
        except Exception as ex:
            scrivi_log(f"NewsParser.scarica_json ({completo})", ex)
            raise ErroreNotizie(str(ex)) from ex

    def _scarica_json(self, indirizzo, parametri=None):
        try:
            completo = indirizzo
            if parametri:
                completo = f"{indirizzo}?{urllib.parse.urlencode(parametri)}"
            risultato = self._scarica(completo, timeout=TEMPO_SONDAGGIO, consenti_browser=False)
            if not risultato or not risultato[0]:
                return None
            return json.loads(risultato[0].decode("utf-8", errors="replace"))
        except Exception as ex:
            scrivi_log(f"NewsParser._scarica_json ({indirizzo})", ex)
            return None


    def _analizza_feed(self, contenuto):
        try:
            if feedparser is None or not contenuto:
                return None
            documento = feedparser.parse(contenuto)
            if documento.entries:
                return documento
            if documento.get("version") and not documento.get("bozo"):
                return documento
            return None
        except Exception as ex:
            scrivi_log("NewsParser._analizza_feed", ex)
            return None

    def _nome_feed(self, documento, riserva):
        try:
            titolo = " ".join(html.unescape(str(documento.feed.get("title") or "")).split())
            return titolo or riserva
        except Exception as ex:
            scrivi_log("NewsParser._nome_feed", ex)
            return riserva

    def _verifica_wordpress(self, base, intestazione=None):
        try:
            if intestazione is not None and (intestazione.api_wordpress or "wordpress" in intestazione.generatore.lower()):
                return True
            dati = self._scarica_json(base.rstrip("/") + "/wp-json/")
            return isinstance(dati, dict) and "wp/v2" in (dati.get("namespaces") or [])
        except Exception as ex:
            scrivi_log(f"NewsParser._verifica_wordpress: {base} non espone le API di WordPress", ex)
            return False

    def _possibili_feed(self, candidato, base, intestazione):
        possibili = []
        try:
            for indirizzo in intestazione.indirizzi_feed:
                possibili.append(urllib.parse.urljoin(candidato, indirizzo))
            for indirizzo in intestazione.collegamenti:
                possibili.append(urllib.parse.urljoin(candidato, indirizzo))
            for percorso in PERCORSI_FEED:
                possibili.append(base + percorso)
            alternativa = _senza_www(base)
            if alternativa != base:
                for percorso in PERCORSI_FEED[:6]:
                    possibili.append(alternativa + percorso)
        except Exception as ex:
            scrivi_log("NewsParser._possibili_feed", ex)
        ordinati = []
        visti = set()
        for indirizzo in possibili:
            if indirizzo and indirizzo not in visti:
                visti.add(indirizzo)
                ordinati.append(indirizzo)
        return ordinati

    def _descrivi(self, documento, indirizzo, base, riserva, wordpress):
        return {
            "name": self._nome_feed(documento, riserva),
            "feed_url": indirizzo,
            "site_url": base,
            "kind": "wordpress" if wordpress else "rss",
        }

    def detect_source(self, url):
        try:
            candidati = candidati_indirizzo(url)
            if not candidati:
                raise FeedNonTrovato("Indirizzo vuoto")
            raggiunto = False
            provati = set()
            for candidato in candidati:
                risultato = self._scarica(candidato, feed=True)
                if risultato is None:
                    continue
                contenuto, finale = risultato
                raggiunto = True
                if not contenuto:
                    continue
                base = _base_sito(finale)
                dominio = urllib.parse.urlparse(finale).netloc

                documento = self._analizza_feed(contenuto)
                if documento is not None:
                    return self._descrivi(documento, finale, base, dominio, self._verifica_wordpress(base))

                intestazione = _LettoreIntestazione()
                try:
                    intestazione.feed(decodifica(contenuto))
                    intestazione.close()
                except Exception as ex:
                    scrivi_log(f"NewsParser.detect_source lettura pagina ({candidato})", ex)
                wordpress = self._verifica_wordpress(base, intestazione)
                titolo_pagina = " ".join(html.unescape(intestazione.titolo).split())
                tentativi = 0
                for possibile in self._possibili_feed(finale, base, intestazione):
                    if possibile in provati:
                        continue
                    provati.add(possibile)
                    tentativi += 1
                    if tentativi > MASSIMI_TENTATIVI_FEED:
                        break
                    prova = self._scarica(
                        possibile,
                        feed=True,
                        timeout=TEMPO_SONDAGGIO,
                        consenti_browser=False,
                    )
                    if not prova or not prova[0]:
                        continue
                    documento = self._analizza_feed(prova[0])
                    if documento is not None:
                        return self._descrivi(
                            documento,
                            prova[1] or possibile,
                            base,
                            titolo_pagina or dominio,
                            wordpress,
                        )
            if not raggiunto:
                raise SitoNonRaggiungibile(str(url))
            raise FeedNonTrovato(str(url))
        except ErroreNotizie as ex:
            scrivi_log(f"NewsParser.detect_source ({url})", ex)
            raise
        except Exception as ex:
            scrivi_log(f"NewsParser.detect_source ({url})", ex)
            raise ErroreNotizie(str(ex)) from ex

    def fetch_articles(self, source, limite=100):
        try:
            if feedparser is None:
                raise ErroreNotizie("Libreria feedparser non installata")
            indirizzo = source.get("url", "") if isinstance(source, dict) else str(source)
            if not indirizzo:
                raise ErroreNotizie("Indirizzo del feed mancante")
            risultato = self._scarica(indirizzo, feed=True)
            if risultato is None:
                raise ErroreNotizie(f"Feed non raggiungibile: {indirizzo}")
            contenuto = risultato[0]
            if not contenuto:
                raise ErroreNotizie(f"Il sito ha rifiutato la richiesta: {indirizzo}")
            documento = feedparser.parse(contenuto)
            if not documento.entries:
                if documento.get("bozo"):
                    raise ErroreNotizie(f"Feed non valido: {documento.get('bozo_exception', '')}")
                return []
            articoli = []
            adesso = datetime.now()
            for voce in documento.entries[:limite]:
                try:
                    titolo = " ".join(html_in_testo(voce.get("title") or "").split()) or "Articolo senza titolo"
                    collegamento = str(voce.get("link") or "").strip()
                    contenuti = voce.get("content") or []
                    testo_contenuto = html_in_testo(contenuti[0].get("value", "")) if contenuti else ""
                    riassunto = html_in_testo(voce.get("summary") or "")
                    guid = str(voce.get("id") or collegamento or f"{titolo}|{voce.get('published', '')}").strip()
                    articoli.append(
                        Article(
                            title=titolo,
                            link=collegamento,
                            summary=riassunto,
                            published=_data_voce(voce) or adesso,
                            content=testo_contenuto,
                            guid=guid,
                            source_url=indirizzo,
                        )
                    )
                except Exception as ex:
                    scrivi_log(f"NewsParser.fetch_articles voce ({indirizzo})", ex)
            return articoli
        except ErroreNotizie:
            raise
        except Exception as ex:
            scrivi_log(f"NewsParser.fetch_articles ({source})", ex)
            raise ErroreNotizie(str(ex)) from ex

    def fetch_feed(self, url):
        try:
            return self.fetch_articles({"url": url})
        except Exception as ex:
            scrivi_log(f"NewsParser.fetch_feed ({url})", ex)
            return []

    def testo_wordpress(self, site_url, link):
        try:
            if not site_url or not link:
                return ""
            percorso = urllib.parse.urlparse(link).path.strip("/")
            slug = percorso.split("/")[-1] if percorso else ""
            if not slug:
                return ""
            dati = self._scarica_json(
                site_url.rstrip("/") + "/wp-json/wp/v2/posts",
                {"slug": urllib.parse.unquote(slug), "_fields": "content"},
            )
            if isinstance(dati, list) and dati:
                return html_in_testo(((dati[0] or {}).get("content") or {}).get("rendered", ""))
            return ""
        except Exception as ex:
            scrivi_log(f"NewsParser.testo_wordpress ({link})", ex)
            return ""
