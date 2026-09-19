from app.core import rete
from app.core.log import scrivi_log
from app.news.headless_browser import BrowserNonDisponibile
from app.news.news_parser import ErroreNotizie, decodifica, paragrafi_da_pagina, pulisci_righe

try:
    import trafilatura
except Exception as errore_importazione:
    trafilatura = None
    scrivi_log("article_text: impossibile importare trafilatura, uso l'estrazione semplice", errore_importazione)

LUNGHEZZA_SUFFICIENTE = 900
TEMPO_MASSIMO = 25

METODO_SALVATO = "salvato"
METODO_FEED = "feed"
METODO_WORDPRESS = "wordpress"
METODO_PAGINA = "pagina"
METODO_BROWSER = "browser"
METODO_RIASSUNTO = "riassunto"


class TestoNonDisponibile(ErroreNotizie):
    pass


def estrai_da_html(contenuto, url=""):
    try:
        if not contenuto:
            return ""
        if trafilatura is not None:
            try:
                testo = trafilatura.extract(
                    contenuto,
                    url=url or None,
                    include_comments=False,
                    include_tables=False,
                    include_images=False,
                    favor_recall=True,
                )
                if testo:
                    return pulisci_righe(testo)
            except Exception as ex:
                scrivi_log(f"article_text.estrai_da_html trafilatura ({url})", ex)
        return paragrafi_da_pagina(decodifica(contenuto))
    except Exception as ex:
        scrivi_log(f"article_text.estrai_da_html ({url})", ex)
        return ""


def togli_titolo_iniziale(testo, titolo):
    try:
        if not testo or not titolo:
            return testo
        righe = testo.split("\n\n")
        if righe and " ".join(righe[0].split()).lower() == " ".join(titolo.split()).lower():
            return "\n\n".join(righe[1:]).strip()
        return testo
    except Exception as ex:
        scrivi_log("article_text.togli_titolo_iniziale", ex)
        return testo


class ArticleTextExtractor:
    def __init__(self, manager, parser, browser):
        self.manager = manager
        self.parser = parser
        self.browser = browser

    def browser_disponibile(self):
        try:
            return self.browser is not None and self.browser.disponibile()
        except Exception as ex:
            scrivi_log("ArticleTextExtractor.browser_disponibile", ex)
            return False

    def _con_browser(self, articolo):
        try:
            contenuto = self.browser.scarica_html(articolo.link)
            return togli_titolo_iniziale(estrai_da_html(contenuto, articolo.link), articolo.title)
        except BrowserNonDisponibile:
            raise
        except Exception as ex:
            scrivi_log(f"ArticleTextExtractor._con_browser ({articolo.link})", ex)
            return ""

    def estrai(self, articolo, forza_browser=False):
        try:
            if forza_browser:
                if not articolo.link:
                    raise TestoNonDisponibile("L'articolo non ha un indirizzo")
                if not self.browser_disponibile():
                    raise BrowserNonDisponibile("Nessun browser invisibile installato")
                testo = self._con_browser(articolo)
                if not testo:
                    raise TestoNonDisponibile("Il browser non ha restituito testo")
                self._memorizza(articolo, testo)
                return {"testo": testo, "metodo": METODO_BROWSER}
            if articolo.full_text:
                return {"testo": articolo.full_text, "metodo": METODO_SALVATO}
            candidati = []
            testo_feed = togli_titolo_iniziale(articolo.content, articolo.title)
            candidati.append((METODO_FEED, testo_feed))
            if len(testo_feed) < LUNGHEZZA_SUFFICIENTE and articolo.link:
                fonte = self.manager.get_source(articolo.source_url)
                if fonte is not None and fonte.get("kind") == "wordpress":
                    testo = togli_titolo_iniziale(self.parser.testo_wordpress(fonte.get("site_url"), articolo.link), articolo.title)
                    candidati.append((METODO_WORDPRESS, testo))
                if max(len(testo) for _metodo, testo in candidati) < LUNGHEZZA_SUFFICIENTE:
                    candidati.append((METODO_PAGINA, self._da_pagina(articolo)))
                if max(len(testo) for _metodo, testo in candidati) < LUNGHEZZA_SUFFICIENTE and self.browser_disponibile():
                    try:
                        candidati.append((METODO_BROWSER, self._con_browser(articolo)))
                    except BrowserNonDisponibile as ex:
                        scrivi_log("ArticleTextExtractor.estrai: browser non disponibile", ex)
            metodo, testo = self._scegli(candidati)
            if not testo:
                testo = togli_titolo_iniziale(articolo.summary, articolo.title)
                metodo = METODO_RIASSUNTO
            if not testo:
                raise TestoNonDisponibile("Nessun testo recuperabile")
            if metodo != METODO_RIASSUNTO:
                self._memorizza(articolo, testo)
            return {"testo": testo, "metodo": metodo}
        except (TestoNonDisponibile, BrowserNonDisponibile) as ex:
            scrivi_log(f"ArticleTextExtractor.estrai ({articolo.link})", ex)
            raise
        except Exception as ex:
            scrivi_log(f"ArticleTextExtractor.estrai ({articolo.link})", ex)
            raise TestoNonDisponibile(str(ex)) from ex

    def _da_pagina(self, articolo):
        try:
            contenuto = rete.leggi_bytes(articolo.link, None, TEMPO_MASSIMO)
            return togli_titolo_iniziale(estrai_da_html(contenuto, articolo.link), articolo.title)
        except Exception as ex:
            scrivi_log(f"ArticleTextExtractor._da_pagina ({articolo.link})", ex)
            return ""

    def _scegli(self, candidati):
        try:
            validi = [(metodo, testo) for metodo, testo in candidati if testo]
            if not validi:
                return "", ""
            for metodo, testo in validi:
                if len(testo) >= LUNGHEZZA_SUFFICIENTE:
                    return metodo, testo
            return max(validi, key=lambda coppia: len(coppia[1]))
        except Exception as ex:
            scrivi_log("ArticleTextExtractor._scegli", ex)
            return "", ""

    def _memorizza(self, articolo, testo):
        try:
            articolo.full_text = testo
            if articolo.id:
                self.manager.save_full_text(articolo.id, testo)
        except Exception as ex:
            scrivi_log("ArticleTextExtractor._memorizza", ex)
