import shutil
import subprocess
import tempfile
import threading
import time

from app.core import percorsi
from app.core.log import scrivi_log

ESEGUIBILI_CHROMIUM = [
    "chromium-browser",
    "chromium",
    "google-chrome",
    "google-chrome-stable",
    "brave-browser",
    "microsoft-edge",
    "vivaldi",
]
TEMPO_MASSIMO = 45
ATTESA_SCRIPT_MILLISECONDI = 8000
DIMENSIONE_MINIMA_PAGINA = 200


class BrowserNonDisponibile(Exception):
    pass


class ErroreBrowser(Exception):
    pass


class HeadlessBrowser:
    def __init__(self, timeout=TEMPO_MASSIMO):
        self.timeout = timeout
        self._blocco = threading.Lock()
        self._metodo = None
        self._verificato = False

    def _playwright_presente(self):
        try:
            import playwright.sync_api
            return True
        except ImportError:
            return False
        except Exception as ex:
            scrivi_log("HeadlessBrowser._playwright_presente", ex)
            return False

    def _selenium_presente(self):
        try:
            import selenium.webdriver
            return shutil.which("firefox") is not None
        except ImportError:
            return False
        except Exception as ex:
            scrivi_log("HeadlessBrowser._selenium_presente", ex)
            return False

    def eseguibile_chromium(self):
        try:
            for nome in ESEGUIBILI_CHROMIUM:
                percorso = shutil.which(nome)
                if percorso:
                    return percorso
            return None
        except Exception as ex:
            scrivi_log("HeadlessBrowser.eseguibile_chromium", ex)
            return None

    def metodi_disponibili(self):
        metodi = []
        try:
            if self._playwright_presente():
                metodi.append("playwright")
            if self.eseguibile_chromium():
                metodi.append("chromium")
            if self._selenium_presente():
                metodi.append("selenium")
        except Exception as ex:
            scrivi_log("HeadlessBrowser.metodi_disponibili", ex)
        return metodi

    def disponibile(self):
        try:
            return bool(self.metodi_disponibili())
        except Exception as ex:
            scrivi_log("HeadlessBrowser.disponibile", ex)
            return False

    def descrizione(self):
        try:
            metodi = self.metodi_disponibili()
            if not metodi:
                return "nessun browser invisibile disponibile"
            nomi = {"playwright": "Playwright", "chromium": "Chromium", "selenium": "Firefox con Selenium"}
            return ", ".join(nomi[metodo] for metodo in metodi)
        except Exception as ex:
            scrivi_log("HeadlessBrowser.descrizione", ex)
            return ""

    def scarica_html(self, url):
        metodi = self.metodi_disponibili()
        if not metodi:
            raise BrowserNonDisponibile("Nessun browser invisibile installato")
        ultimo_errore = None
        with self._blocco:
            for metodo in metodi:
                try:
                    if metodo == "playwright":
                        contenuto = self._con_playwright(url)
                    elif metodo == "chromium":
                        contenuto = self._con_chromium(url)
                    else:
                        contenuto = self._con_selenium(url)
                    if contenuto and len(contenuto) >= DIMENSIONE_MINIMA_PAGINA:
                        return contenuto
                    ultimo_errore = ErroreBrowser(f"Pagina vuota con {metodo}")
                    scrivi_log(f"HeadlessBrowser.scarica_html: pagina vuota con {metodo} ({url})")
                except Exception as ex:
                    ultimo_errore = ex
                    scrivi_log(f"HeadlessBrowser.scarica_html con {metodo} ({url})", ex)
        raise ErroreBrowser(str(ultimo_errore))

    def _con_playwright(self, url):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as gestore:
            browser = None
            ultimo_errore = None
            for tipo in (gestore.chromium, gestore.firefox):
                try:
                    browser = tipo.launch(headless=True)
                    break
                except Exception as ex:
                    ultimo_errore = ex
                    scrivi_log(f"HeadlessBrowser._con_playwright: avvio di {tipo.name} non riuscito", ex)
            if browser is None:
                raise ErroreBrowser(str(ultimo_errore))
            try:
                contesto = browser.new_context(user_agent=percorsi.USER_AGENT, locale="it-IT")
                pagina = contesto.new_page()
                risposta = pagina.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                if risposta is not None and risposta.status >= 400:
                    raise ErroreBrowser(f"Il sito ha risposto con il codice {risposta.status}")
                try:
                    pagina.wait_for_load_state("networkidle", timeout=ATTESA_SCRIPT_MILLISECONDI)
                except Exception as ex:
                    scrivi_log(f"HeadlessBrowser._con_playwright: la pagina continua a caricare ({url})", ex)
                return pagina.content()
            finally:
                try:
                    browser.close()
                except Exception as ex:
                    scrivi_log("HeadlessBrowser._con_playwright chiusura", ex)

    def _esegui_chromium(self, eseguibile, modalita, url, profilo):
        comando = [
            eseguibile,
            modalita,
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
            "--mute-audio",
            "--hide-scrollbars",
            "--lang=it-IT",
            f"--user-data-dir={profilo}",
            f"--virtual-time-budget={ATTESA_SCRIPT_MILLISECONDI}",
            "--dump-dom",
            url,
        ]
        esito = subprocess.run(
            comando,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout,
            check=False,
        )
        testo = esito.stdout.decode("utf-8", errors="replace")
        if esito.returncode != 0 and len(testo) < DIMENSIONE_MINIMA_PAGINA:
            errore = esito.stderr.decode("utf-8", errors="replace")[-800:]
            raise ErroreBrowser(f"Chromium ha restituito {esito.returncode}: {errore}")
        return testo

    def _con_chromium(self, url):
        eseguibile = self.eseguibile_chromium()
        if not eseguibile:
            raise BrowserNonDisponibile("Chromium non trovato")
        with tempfile.TemporaryDirectory(prefix="linuxeasy-browser-") as profilo:
            try:
                testo = self._esegui_chromium(eseguibile, "--headless=new", url, profilo)
                if len(testo) >= DIMENSIONE_MINIMA_PAGINA:
                    return testo
            except subprocess.TimeoutExpired:
                raise
            except Exception as ex:
                scrivi_log(f"HeadlessBrowser._con_chromium: modalità headless nuova non riuscita ({url})", ex)
            return self._esegui_chromium(eseguibile, "--headless", url, profilo)

    def _con_selenium(self, url):
        from selenium import webdriver

        opzioni = webdriver.FirefoxOptions()
        opzioni.add_argument("-headless")
        opzioni.set_preference("intl.accept_languages", "it-IT, it")
        opzioni.set_preference("general.useragent.override", percorsi.USER_AGENT)
        driver = webdriver.Firefox(options=opzioni)
        try:
            driver.set_page_load_timeout(self.timeout)
            driver.get(url)
            time.sleep(ATTESA_SCRIPT_MILLISECONDI / 4000)
            return driver.page_source
        finally:
            try:
                driver.quit()
            except Exception as ex:
                scrivi_log("HeadlessBrowser._con_selenium chiusura", ex)
