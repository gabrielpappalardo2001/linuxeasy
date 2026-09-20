import concurrent.futures
import html
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as albero
from contextlib import closing
from dataclasses import dataclass

from gi.repository import GLib

from app.core import percorsi
from app.core.log import scrivi_log
from app.librivox import tag_audio

API_LIBRI = "https://librivox.org/api/feed/audiobooks/"
API_TRACCE = "https://librivox.org/api/feed/audiotracks/"
RSS_LIBRO = "https://librivox.org/rss/{id}"
PAGINA_CATALOGO = 1000
MASSIMO_PAGINE = 200
TENTATIVI = 3
PAUSA_TENTATIVO = 4
TIMEOUT_CATALOGO = 120
TIMEOUT_DETTAGLI = 30
TIMEOUT_TAG = 12
LETTORI_TAG = 6
ATTESA_MASSIMA_TAG = 40
MASSIMO_RISULTATI = 500
CAMPI_CATALOGO = (
    "id",
    "title",
    "language",
    "authors",
    "totaltime",
    "totaltimesecs",
    "num_sections",
    "copyright_year",
    "url_rss",
    "url_zip_file",
    "url_librivox",
)
TUTTE_LE_LINGUE = "*"
LINGUA_PREDEFINITA = "Italian"
CHIAVE_LINGUA = "librivox_lingua"
CHIAVE_DATA_CATALOGO = "librivox_catalogo_data"
INIZIALE_ALTRI = "#"

NOMI_LINGUE = {
    "Afrikaans": "Afrikaans",
    "Ancient Greek": "Greco antico",
    "Arabic": "Arabo",
    "Bengali": "Bengalese",
    "Bulgarian": "Bulgaro",
    "Catalan": "Catalano",
    "Chinese": "Cinese",
    "Church Slavonic": "Slavo ecclesiastico",
    "Croatian": "Croato",
    "Czech": "Ceco",
    "Danish": "Danese",
    "Dutch": "Olandese",
    "English": "Inglese",
    "Esperanto": "Esperanto",
    "Estonian": "Estone",
    "Finnish": "Finlandese",
    "French": "Francese",
    "Frisian": "Frisone",
    "Galician": "Galiziano",
    "German": "Tedesco",
    "Greek": "Greco",
    "Hebrew": "Ebraico",
    "Hindi": "Hindi",
    "Hungarian": "Ungherese",
    "Icelandic": "Islandese",
    "Indonesian": "Indonesiano",
    "Irish": "Irlandese",
    "Italian": "Italiano",
    "Japanese": "Giapponese",
    "Javanese": "Giavanese",
    "Korean": "Coreano",
    "Latin": "Latino",
    "Latvian": "Lettone",
    "Lithuanian": "Lituano",
    "Middle English": "Inglese medio",
    "Multilingual": "Multilingue",
    "Norwegian": "Norvegese",
    "Old English": "Inglese antico",
    "Old Norse": "Norreno",
    "Persian": "Persiano",
    "Polish": "Polacco",
    "Portuguese": "Portoghese",
    "Romanian": "Rumeno",
    "Russian": "Russo",
    "Scots": "Scozzese",
    "Serbian": "Serbo",
    "Slovak": "Slovacco",
    "Slovenian": "Sloveno",
    "Spanish": "Spagnolo",
    "Swedish": "Svedese",
    "Tagalog": "Tagalog",
    "Tamil": "Tamil",
    "Turkish": "Turco",
    "Ukrainian": "Ucraino",
    "Urdu": "Urdu",
    "Welsh": "Gallese",
    "Yiddish": "Yiddish",
}

AGGETTIVI_LINGUE = {
    "English": "in inglese",
    "Italian": "in italiano",
    "German": "in tedesco",
    "French": "in francese",
    "Spanish": "in spagnolo",
    "Portuguese": "in portoghese",
    "Dutch": "in olandese",
    "Latin": "in latino",
    "Russian": "in russo",
}

ARTICOLI = {
    "English": ("the ", "a ", "an "),
    "Italian": ("il ", "lo ", "la ", "i ", "gli ", "le ", "l'", "un ", "uno ", "una ", "un'"),
    "French": ("le ", "la ", "les ", "l'", "un ", "une "),
    "German": ("der ", "die ", "das ", "ein ", "eine "),
    "Spanish": ("el ", "la ", "los ", "las ", "un ", "una "),
    "Portuguese": ("o ", "a ", "os ", "as ", "um ", "uma "),
    "Dutch": ("de ", "het ", "een "),
}


class ErroreLibriVox(Exception):
    pass


@dataclass
class Libro:
    id: int
    title: str
    authors: str = ""
    language: str = ""
    totaltime: str = ""
    num_sections: int = 0
    copyright_year: str = ""
    url_rss: str = ""
    url_zip_file: str = ""
    url_librivox: str = ""


@dataclass
class Autore:
    id: int
    first_name: str
    last_name: str
    dob: str = ""
    dod: str = ""
    opere: int = 0

    def nome(self):
        try:
            return " ".join(parte for parte in (self.first_name, self.last_name) if parte) or "Autore sconosciuto"
        except Exception as ex:
            scrivi_log("Autore.nome", ex)
            return "Autore sconosciuto"

    def nome_ordinato(self):
        try:
            if self.last_name and self.first_name:
                return f"{self.last_name}, {self.first_name}"
            return self.nome()
        except Exception as ex:
            scrivi_log("Autore.nome_ordinato", ex)
            return self.nome()

    def date(self):
        try:
            nascita = str(self.dob or "").strip()
            morte = str(self.dod or "").strip()
            if nascita and morte:
                return f"{nascita}-{morte}"
            if nascita:
                return f"nato nel {nascita}"
            if morte:
                return f"morto nel {morte}"
            return ""
        except Exception as ex:
            scrivi_log("Autore.date", ex)
            return ""


@dataclass
class Capitolo:
    numero: int
    title: str
    url: str
    durata: str = ""
    file_name: str = ""


def normalizza(testo):
    try:
        valore = unicodedata.normalize("NFKD", str(testo or ""))
        valore = "".join(carattere for carattere in valore if not unicodedata.combining(carattere)).lower()
        return " ".join(re.sub(r"[^a-z0-9']+", " ", valore).split())
    except Exception as ex:
        scrivi_log(f"librivox_catalog.normalizza ({testo})", ex)
        return ""


def chiave_ordinamento(testo, lingua=""):
    try:
        valore = normalizza(testo).lstrip("' ")
        for articolo in ARTICOLI.get(lingua, ()):
            if valore.startswith(articolo) and len(valore) > len(articolo):
                valore = valore[len(articolo):].lstrip("' ")
                break
        valore = valore.replace("'", "")
        return re.sub(r"\d+", lambda numero: numero.group(0).zfill(8), valore)
    except Exception as ex:
        scrivi_log(f"librivox_catalog.chiave_ordinamento ({testo})", ex)
        return normalizza(testo)


def iniziale(chiave):
    try:
        if chiave and "a" <= chiave[0] <= "z":
            return chiave[0].upper()
        return INIZIALE_ALTRI
    except Exception as ex:
        scrivi_log(f"librivox_catalog.iniziale ({chiave})", ex)
        return INIZIALE_ALTRI


def nome_lingua(lingua):
    try:
        if lingua == TUTTE_LE_LINGUE:
            return "Tutte le lingue"
        return NOMI_LINGUE.get(lingua, lingua or "Lingua non indicata")
    except Exception as ex:
        scrivi_log(f"librivox_catalog.nome_lingua ({lingua})", ex)
        return str(lingua)


def in_lingua(lingua):
    try:
        if lingua == TUTTE_LE_LINGUE:
            return "in tutte le lingue"
        if lingua in AGGETTIVI_LINGUE:
            return AGGETTIVI_LINGUE[lingua]
        return f"in {nome_lingua(lingua).lower()}"
    except Exception as ex:
        scrivi_log(f"librivox_catalog.in_lingua ({lingua})", ex)
        return ""


def durata_leggibile(valore):
    try:
        testo = str(valore or "").strip()
        if not testo:
            return ""
        if testo.isdigit():
            totale = int(testo)
        else:
            parti = testo.split(":")
            if not all(parte.strip().isdigit() for parte in parti) or len(parti) > 3:
                return ""
            totale = 0
            for parte in parti:
                totale = totale * 60 + int(parte)
        if totale <= 0:
            return ""
        ore, resto = divmod(totale, 3600)
        minuti, secondi = divmod(resto, 60)
        if ore:
            return f"{ore} {'ora' if ore == 1 else 'ore'} e {minuti} {'minuto' if minuti == 1 else 'minuti'}"
        if minuti:
            return f"{minuti} {'minuto' if minuti == 1 else 'minuti'}"
        return f"{secondi} secondi"
    except Exception as ex:
        scrivi_log(f"librivox_catalog.durata_leggibile ({valore})", ex)
        return ""


def durata_breve(valore):
    try:
        testo = str(valore or "").strip()
        if not testo:
            return ""
        if testo.isdigit():
            totale = int(testo)
        else:
            parti = testo.split(":")
            if not all(parte.strip().isdigit() for parte in parti) or len(parti) > 3:
                return ""
            totale = 0
            for parte in parti:
                totale = totale * 60 + int(parte)
        if totale <= 0:
            return ""
        ore, resto = divmod(totale, 3600)
        minuti, secondi = divmod(resto, 60)
        if ore:
            return f"{ore}:{minuti:02d}:{secondi:02d}"
        return f"{minuti}:{secondi:02d}"
    except Exception as ex:
        scrivi_log(f"librivox_catalog.durata_breve ({valore})", ex)
        return ""


def testo_da_html(frammento):
    try:
        testo = re.sub(r"<br\s*/?>|</p>|</li>", "\n", str(frammento or ""), flags=re.IGNORECASE)
        testo = re.sub(r"<[^>]+>", " ", testo)
        testo = html.unescape(testo)
        righe = [" ".join(riga.split()) for riga in testo.splitlines()]
        return "\n".join(riga for riga in righe if riga)
    except Exception as ex:
        scrivi_log("librivox_catalog.testo_da_html", ex)
        return ""


def _pulisci(testo):
    try:
        return " ".join(html.unescape(str(testo or "")).split())
    except Exception as ex:
        scrivi_log("librivox_catalog._pulisci", ex)
        return ""


def _elenco(valore):
    try:
        if isinstance(valore, list):
            return valore
        if isinstance(valore, dict):
            return list(valore.values())
        return []
    except Exception as ex:
        scrivi_log("librivox_catalog._elenco", ex)
        return []


def _intero(valore, predefinito=0):
    try:
        testo = str(valore if valore is not None else "").strip()
        if re.fullmatch(r"-?\d+", testo):
            return int(testo)
        return predefinito
    except Exception as ex:
        scrivi_log(f"librivox_catalog._intero ({valore})", ex)
        return predefinito


def _leggi_json(indirizzo, parametri, timeout):
    url = indirizzo + "?" + urllib.parse.urlencode(parametri)
    richiesta = urllib.request.Request(url, headers={"User-Agent": percorsi.USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
            corpo = risposta.read()
    except urllib.error.HTTPError as ex:
        if ex.code == 404:
            try:
                corpo = ex.read()
            except Exception as ex_lettura:
                scrivi_log(f"librivox_catalog._leggi_json corpo 404 ({url})", ex_lettura)
                return {}
        else:
            raise ErroreLibriVox(f"Errore HTTP {ex.code} da {url}") from ex
    except Exception as ex:
        raise ErroreLibriVox(f"{ex} ({url})") from ex
    try:
        dati = json.loads(corpo.decode("utf-8", errors="replace"))
    except Exception as ex:
        raise ErroreLibriVox(f"Risposta non valida da {url}") from ex
    return dati if isinstance(dati, dict) else {}


class LibriVoxCatalog:
    def __init__(self, db):
        self.db = db
        self._blocco = threading.Lock()
        self._thread = None
        self._fermo = threading.Event()
        self._chiusura = False
        self._attivo = False
        self._letti = 0
        self._eventi = []
        self._ascoltatore = None

    @property
    def aggiornamento_in_corso(self):
        try:
            return self._attivo
        except Exception as ex:
            scrivi_log("LibriVoxCatalog.aggiornamento_in_corso", ex)
            return False

    @property
    def libri_letti(self):
        return self._letti

    def eventi(self):
        try:
            with self._blocco:
                return list(self._eventi)
        except Exception as ex:
            scrivi_log("LibriVoxCatalog.eventi", ex)
            return []

    def imposta_ascoltatore(self, funzione):
        try:
            self._ascoltatore = funzione
        except Exception as ex:
            scrivi_log("LibriVoxCatalog.imposta_ascoltatore", ex)

    def _annota(self, testo):
        try:
            with self._blocco:
                self._eventi.append(str(testo))
            if self._ascoltatore is not None:
                GLib.idle_add(self._avvisa_ascoltatore)
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog._annota ({testo})", ex)

    def _avvisa_ascoltatore(self):
        try:
            if self._ascoltatore is not None:
                self._ascoltatore()
        except Exception as ex:
            scrivi_log("LibriVoxCatalog._avvisa_ascoltatore", ex)
        return False

    def lingua_preferita(self):
        try:
            return self.db.leggi_impostazione(CHIAVE_LINGUA, LINGUA_PREDEFINITA) or LINGUA_PREDEFINITA
        except Exception as ex:
            scrivi_log("LibriVoxCatalog.lingua_preferita", ex)
            return LINGUA_PREDEFINITA

    def imposta_lingua(self, lingua):
        try:
            return self.db.scrivi_impostazione(CHIAVE_LINGUA, lingua or TUTTE_LE_LINGUE)
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.imposta_lingua ({lingua})", ex)
            return False

    def numero_libri(self, lingua=TUTTE_LE_LINGUE):
        try:
            riga = self.db.leggi_uno(
                "SELECT COUNT(*) FROM librivox_books WHERE (? = '*' OR language = ?)",
                (lingua, lingua),
            )
            return int(riga[0]) if riga else 0
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.numero_libri ({lingua})", ex)
            return 0

    def ha_catalogo(self):
        return self.numero_libri() > 0

    def data_aggiornamento(self):
        try:
            valore = self.db.leggi_impostazione(CHIAVE_DATA_CATALOGO, "")
            if not valore:
                return ""
            return time.strftime("%d/%m/%Y", time.localtime(float(valore)))
        except Exception as ex:
            scrivi_log("LibriVoxCatalog.data_aggiornamento", ex)
            return ""

    def avvia_aggiornamento(self, al_termine=None):
        try:
            with self._blocco:
                if self._attivo:
                    return False
                self._fermo.clear()
                self._chiusura = False
                self._letti = 0
                self._attivo = True
                self._eventi = ["Avvio del download del catalogo di LibriVox."]
                self._thread = threading.Thread(
                    target=self._esegui_aggiornamento,
                    args=(al_termine,),
                    name="CatalogoLibriVox",
                    daemon=True,
                )
                self._thread.start()
            return True
        except Exception as ex:
            self._attivo = False
            scrivi_log("LibriVoxCatalog.avvia_aggiornamento", ex)
            return False

    def ferma(self):
        try:
            self._chiusura = True
            self._fermo.set()
        except Exception as ex:
            scrivi_log("LibriVoxCatalog.ferma", ex)

    def annulla_aggiornamento(self):
        try:
            if not self._attivo:
                return False
            self._fermo.set()
            return True
        except Exception as ex:
            scrivi_log("LibriVoxCatalog.annulla_aggiornamento", ex)
            return False

    def _esegui_aggiornamento(self, al_termine):
        esito = {"libri": 0, "errore": "", "annullato": False}
        try:
            libri = self.scarica_catalogo()
            if self._fermo.is_set():
                esito["annullato"] = True
                self._annota("Download del catalogo annullato. Il catalogo precedente è rimasto invariato.")
            else:
                self._annota(f"Download completato: {len(libri)} audiolibri ricevuti.")
                self._annota("Salvataggio del catalogo nell'archivio del programma in corso.")
                esito["libri"] = self._salva_catalogo(libri)
                self._annota(f"Catalogo aggiornato: {esito['libri']} audiolibri disponibili.")
        except Exception as ex:
            scrivi_log("LibriVoxCatalog._esegui_aggiornamento", ex)
            esito["errore"] = str(ex) or "errore sconosciuto"
            self._annota("Download del catalogo non riuscito. Controllare la connessione e riprovare.")
        finally:
            self._attivo = False
        try:
            if al_termine is not None and not self._chiusura:
                GLib.idle_add(self._consegna, al_termine, esito)
        except Exception as ex:
            scrivi_log("LibriVoxCatalog._esegui_aggiornamento consegna", ex)

    def _consegna(self, funzione, esito):
        try:
            funzione(esito)
        except Exception as ex:
            scrivi_log("LibriVoxCatalog._consegna", ex)
        return False

    def _pagina(self, offset, con_campi=True):
        parametri = [("format", "json"), ("limit", PAGINA_CATALOGO), ("offset", offset)]
        if con_campi:
            parametri.extend(("fields[]", campo) for campo in CAMPI_CATALOGO)
        ultimo_errore = None
        for tentativo in range(TENTATIVI):
            if self._fermo.is_set():
                return []
            try:
                dati = _leggi_json(API_LIBRI, parametri, TIMEOUT_CATALOGO)
                return _elenco(dati.get("books"))
            except Exception as ex:
                ultimo_errore = ex
                scrivi_log(f"LibriVoxCatalog._pagina tentativo {tentativo + 1} (offset {offset})", ex)
                if tentativo + 1 < TENTATIVI:
                    self._annota(
                        f"Connessione non riuscita, nuovo tentativo tra {PAUSA_TENTATIVO * (tentativo + 1)} secondi."
                    )
                if self._fermo.wait(PAUSA_TENTATIVO * (tentativo + 1)):
                    return []
        raise ErroreLibriVox(f"Pagina del catalogo non scaricata: {ultimo_errore}")

    def scarica_catalogo(self):
        libri = {}
        try:
            con_campi = True
            for numero in range(MASSIMO_PAGINE):
                if self._fermo.is_set():
                    break
                pagina = self._pagina(numero * PAGINA_CATALOGO, con_campi)
                if numero == 0 and pagina and con_campi and all("authors" not in elemento for elemento in pagina[:20]):
                    con_campi = False
                    pagina = self._pagina(0, False)
                for elemento in pagina:
                    if isinstance(elemento, dict):
                        identificativo = _intero(elemento.get("id"))
                        if identificativo > 0:
                            libri[identificativo] = elemento
                self._letti = len(libri)
                if pagina:
                    self._annota(f"Pagina {numero + 1} ricevuta: {len(libri)} audiolibri letti finora.")
                if len(pagina) < PAGINA_CATALOGO:
                    break
            if not libri and not self._fermo.is_set():
                raise ErroreLibriVox("Il catalogo scaricato è vuoto")
            return list(libri.values())
        except ErroreLibriVox:
            raise
        except Exception as ex:
            scrivi_log("LibriVoxCatalog.scarica_catalogo", ex)
            raise ErroreLibriVox(str(ex)) from ex

    def _righe_catalogo(self, elementi):
        libri = []
        autori = {}
        collegamenti = []
        for elemento in elementi:
            try:
                identificativo = _intero(elemento.get("id"))
                titolo = _pulisci(elemento.get("title")) or "Titolo non indicato"
                lingua = _pulisci(elemento.get("language"))
                nomi = []
                for posizione, autore in enumerate(_elenco(elemento.get("authors"))):
                    if not isinstance(autore, dict):
                        continue
                    id_autore = _intero(autore.get("id"))
                    nome = _pulisci(autore.get("first_name"))
                    cognome = _pulisci(autore.get("last_name"))
                    completo = " ".join(parte for parte in (nome, cognome) if parte)
                    if completo:
                        nomi.append(completo)
                    if id_autore <= 0:
                        continue
                    if id_autore not in autori:
                        ordinamento = chiave_ordinamento(cognome or nome)
                        autori[id_autore] = (
                            id_autore,
                            nome,
                            cognome,
                            _pulisci(autore.get("dob")),
                            _pulisci(autore.get("dod")),
                            ordinamento + " " + normalizza(nome),
                            iniziale(ordinamento),
                            normalizza(completo),
                        )
                    collegamenti.append((identificativo, id_autore, posizione))
                ordinamento = chiave_ordinamento(titolo, lingua)
                libri.append(
                    (
                        identificativo,
                        titolo,
                        ordinamento,
                        iniziale(ordinamento),
                        lingua,
                        ", ".join(nomi),
                        _pulisci(elemento.get("totaltime")),
                        _intero(elemento.get("num_sections")),
                        _pulisci(elemento.get("copyright_year")),
                        str(elemento.get("url_rss") or ""),
                        str(elemento.get("url_zip_file") or ""),
                        str(elemento.get("url_librivox") or ""),
                        normalizza(titolo),
                    )
                )
            except Exception as ex:
                scrivi_log("LibriVoxCatalog._righe_catalogo elemento", ex)
        return libri, list(autori.values()), collegamenti

    def _salva_catalogo(self, elementi):
        try:
            libri, autori, collegamenti = self._righe_catalogo(elementi)
            if not libri:
                raise ErroreLibriVox("Nessun libro valido nel catalogo")
            with closing(self.db.get_connection()) as connessione:
                with connessione:
                    connessione.execute("DELETE FROM librivox_book_authors")
                    connessione.execute("DELETE FROM librivox_books")
                    connessione.execute("DELETE FROM librivox_authors")
                    connessione.executemany(
                        "INSERT OR REPLACE INTO librivox_books (id, title, title_sort, initial, language, authors, "
                        "totaltime, num_sections, copyright_year, url_rss, url_zip_file, url_librivox, search_text) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        libri,
                    )
                    connessione.executemany(
                        "INSERT OR REPLACE INTO librivox_authors (id, first_name, last_name, dob, dod, name_sort, "
                        "initial, search_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        autori,
                    )
                    connessione.executemany(
                        "INSERT OR IGNORE INTO librivox_book_authors (book_id, author_id, position) VALUES (?, ?, ?)",
                        collegamenti,
                    )
                    connessione.execute(
                        "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                        (CHIAVE_DATA_CATALOGO, str(time.time())),
                    )
            return len(libri)
        except ErroreLibriVox:
            raise
        except Exception as ex:
            scrivi_log("LibriVoxCatalog._salva_catalogo", ex)
            raise ErroreLibriVox(str(ex)) from ex

    def _libro_da_riga(self, riga):
        try:
            return Libro(
                id=int(riga[0]),
                title=riga[1],
                authors=riga[2],
                language=riga[3],
                totaltime=riga[4],
                num_sections=int(riga[5] or 0),
                copyright_year=riga[6],
                url_rss=riga[7],
                url_zip_file=riga[8],
                url_librivox=riga[9],
            )
        except Exception as ex:
            scrivi_log("LibriVoxCatalog._libro_da_riga", ex)
            return None

    def _libri(self, condizione, parametri, ordine="b.title_sort", limite=None):
        try:
            sql = (
                "SELECT b.id, b.title, b.authors, b.language, b.totaltime, b.num_sections, b.copyright_year, "
                f"b.url_rss, b.url_zip_file, b.url_librivox FROM librivox_books b WHERE {condizione} ORDER BY {ordine}"
            )
            if limite:
                sql += f" LIMIT {int(limite)}"
            return [libro for libro in (self._libro_da_riga(riga) for riga in self.db.leggi_tutti(sql, parametri)) if libro]
        except Exception as ex:
            scrivi_log("LibriVoxCatalog._libri", ex)
            return []

    def libro(self, identificativo):
        try:
            elenco = self._libri("b.id = ?", (int(identificativo),))
            return elenco[0] if elenco else None
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.libro ({identificativo})", ex)
            return None

    def lingue(self):
        try:
            righe = self.db.leggi_tutti(
                "SELECT language, COUNT(*) FROM librivox_books GROUP BY language"
            )
            elenco = [(riga[0], int(riga[1])) for riga in righe if riga[0]]
            elenco.sort(key=lambda coppia: normalizza(nome_lingua(coppia[0])))
            return elenco
        except Exception as ex:
            scrivi_log("LibriVoxCatalog.lingue", ex)
            return []

    def iniziali_opere(self, lingua):
        try:
            righe = self.db.leggi_tutti(
                "SELECT initial, COUNT(*) FROM librivox_books WHERE (? = '*' OR language = ?) "
                "GROUP BY initial ORDER BY CASE WHEN initial = '#' THEN 1 ELSE 0 END, initial",
                (lingua, lingua),
            )
            return [(riga[0], int(riga[1])) for riga in righe]
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.iniziali_opere ({lingua})", ex)
            return []

    def opere(self, lingua, lettera=None):
        try:
            if lettera:
                return self._libri(
                    "(? = '*' OR b.language = ?) AND b.initial = ?",
                    (lingua, lingua, lettera),
                )
            return self._libri("(? = '*' OR b.language = ?)", (lingua, lingua))
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.opere ({lingua}, {lettera})", ex)
            return []

    def _parole(self, testo):
        try:
            return [parola for parola in normalizza(testo).replace("'", " ").split() if parola][:8]
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog._parole ({testo})", ex)
            return []

    def cerca_opere(self, testo, lingua):
        try:
            parole = self._parole(testo)
            if not parole:
                return []
            condizione = " AND ".join("b.search_text LIKE ?" for _parola in parole)
            parametri = tuple(f"%{parola}%" for parola in parole)
            return self._libri(
                f"(? = '*' OR b.language = ?) AND {condizione}",
                (lingua, lingua) + parametri,
                limite=MASSIMO_RISULTATI,
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.cerca_opere ({testo})", ex)
            return []

    def _autori(self, condizione, parametri, lingua, limite=None):
        try:
            sql = (
                "SELECT a.id, a.first_name, a.last_name, a.dob, a.dod, COUNT(b.id) "
                "FROM librivox_authors a "
                "JOIN librivox_book_authors ba ON ba.author_id = a.id "
                "JOIN librivox_books b ON b.id = ba.book_id "
                f"WHERE (? = '*' OR b.language = ?) AND {condizione} "
                "GROUP BY a.id ORDER BY a.name_sort"
            )
            if limite:
                sql += f" LIMIT {int(limite)}"
            righe = self.db.leggi_tutti(sql, (lingua, lingua) + tuple(parametri))
            return [Autore(int(riga[0]), riga[1], riga[2], riga[3], riga[4], int(riga[5])) for riga in righe]
        except Exception as ex:
            scrivi_log("LibriVoxCatalog._autori", ex)
            return []

    def iniziali_autori(self, lingua):
        try:
            righe = self.db.leggi_tutti(
                "SELECT a.initial, COUNT(DISTINCT a.id) FROM librivox_authors a "
                "JOIN librivox_book_authors ba ON ba.author_id = a.id "
                "JOIN librivox_books b ON b.id = ba.book_id "
                "WHERE (? = '*' OR b.language = ?) "
                "GROUP BY a.initial ORDER BY CASE WHEN a.initial = '#' THEN 1 ELSE 0 END, a.initial",
                (lingua, lingua),
            )
            return [(riga[0], int(riga[1])) for riga in righe]
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.iniziali_autori ({lingua})", ex)
            return []

    def numero_autori(self, lingua):
        try:
            return sum(numero for _lettera, numero in self.iniziali_autori(lingua))
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.numero_autori ({lingua})", ex)
            return 0

    def autori(self, lingua, lettera=None):
        try:
            if lettera:
                return self._autori("a.initial = ?", (lettera,), lingua)
            return self._autori("1 = 1", (), lingua)
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.autori ({lingua}, {lettera})", ex)
            return []

    def cerca_autori(self, testo, lingua):
        try:
            parole = self._parole(testo)
            if not parole:
                return []
            condizione = " AND ".join("a.search_text LIKE ?" for _parola in parole)
            return self._autori(condizione, tuple(f"%{parola}%" for parola in parole), lingua, MASSIMO_RISULTATI)
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.cerca_autori ({testo})", ex)
            return []

    def opere_autore(self, id_autore, lingua):
        try:
            return self._libri(
                "(? = '*' OR b.language = ?) AND b.id IN (SELECT book_id FROM librivox_book_authors WHERE author_id = ?)",
                (lingua, lingua, int(id_autore)),
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.opere_autore ({id_autore})", ex)
            return []

    def autori_libro(self, id_libro):
        try:
            righe = self.db.leggi_tutti(
                "SELECT a.id, a.first_name, a.last_name, a.dob, a.dod FROM librivox_authors a "
                "JOIN librivox_book_authors ba ON ba.author_id = a.id WHERE ba.book_id = ? ORDER BY ba.position",
                (int(id_libro),),
            )
            return [Autore(int(riga[0]), riga[1], riga[2], riga[3], riga[4]) for riga in righe]
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.autori_libro ({id_libro})", ex)
            return []

    def _capitoli_da_sezioni(self, sezioni):
        capitoli = []
        try:
            for sezione in _elenco(sezioni):
                if not isinstance(sezione, dict):
                    continue
                url = str(sezione.get("listen_url") or "").strip()
                if not url:
                    continue
                capitoli.append(
                    Capitolo(
                        numero=_intero(sezione.get("section_number"), len(capitoli) + 1),
                        title=_pulisci(sezione.get("title")),
                        url=url,
                        durata=durata_breve(sezione.get("playtime")),
                        file_name=str(sezione.get("file_name") or ""),
                    )
                )
            capitoli.sort(key=lambda capitolo: capitolo.numero)
        except Exception as ex:
            scrivi_log("LibriVoxCatalog._capitoli_da_sezioni", ex)
        return capitoli

    def _capitoli_da_rss(self, id_libro, url_rss):
        capitoli = []
        try:
            indirizzo = url_rss or RSS_LIBRO.format(id=int(id_libro))
            richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": percorsi.USER_AGENT})
            with urllib.request.urlopen(richiesta, timeout=TIMEOUT_DETTAGLI) as risposta:
                radice = albero.fromstring(risposta.read())
            for elemento in radice.iter("item"):
                allegato = elemento.find("enclosure")
                url = allegato.get("url") if allegato is not None else ""
                if not url:
                    continue
                durata = ""
                for figlio in elemento:
                    if figlio.tag.endswith("}duration"):
                        durata = durata_breve(figlio.text)
                capitoli.append(
                    Capitolo(
                        numero=len(capitoli) + 1,
                        title=_pulisci(elemento.findtext("title")),
                        url=url,
                        durata=durata,
                    )
                )
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog._capitoli_da_rss ({id_libro})", ex)
        return capitoli

    def sezioni(self, libro):
        try:
            capitoli = []
            try:
                dati = _leggi_json(
                    API_LIBRI,
                    [("id", int(libro.id)), ("format", "json"), ("fields[]", "sections")],
                    TIMEOUT_DETTAGLI,
                )
                for elemento in _elenco(dati.get("books")):
                    if isinstance(elemento, dict):
                        capitoli = self._capitoli_da_sezioni(elemento.get("sections"))
                        break
            except Exception as ex:
                scrivi_log(f"LibriVoxCatalog.sezioni API libri ({libro.id})", ex)
            if not capitoli:
                try:
                    dati = _leggi_json(
                        API_TRACCE,
                        [("project_id", int(libro.id)), ("format", "json")],
                        TIMEOUT_DETTAGLI,
                    )
                    capitoli = self._capitoli_da_sezioni(dati.get("sections"))
                except Exception as ex:
                    scrivi_log(f"LibriVoxCatalog.sezioni API tracce ({libro.id})", ex)
            if not capitoli:
                capitoli = self._capitoli_da_rss(libro.id, libro.url_rss)
            if not capitoli:
                raise ErroreLibriVox(f"Nessun capitolo trovato per il libro {libro.id}")
            return capitoli
        except ErroreLibriVox:
            raise
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.sezioni ({libro.id})", ex)
            raise ErroreLibriVox(str(ex)) from ex

    def _titoli_in_cache(self, indirizzi):
        try:
            if not indirizzi:
                return {}
            trovati = {}
            elenco = list(indirizzi)
            for inizio in range(0, len(elenco), 400):
                blocco = elenco[inizio:inizio + 400]
                segnaposto = ", ".join("?" for _url in blocco)
                for riga in self.db.leggi_tutti(
                    f"SELECT url, title FROM librivox_tag_cache WHERE url IN ({segnaposto})",
                    tuple(blocco),
                ):
                    trovati[riga[0]] = riga[1]
            return trovati
        except Exception as ex:
            scrivi_log("LibriVoxCatalog._titoli_in_cache", ex)
            return {}

    def capitoli(self, libro):
        try:
            capitoli = self.sezioni(libro)
            cache = self._titoli_in_cache([capitolo.url for capitolo in capitoli])
            mancanti = [capitolo for capitolo in capitoli if capitolo.url not in cache]
            letti = {}
            if mancanti:
                esecutore = concurrent.futures.ThreadPoolExecutor(max_workers=LETTORI_TAG, thread_name_prefix="TagLibriVox")
                try:
                    futuri = {
                        esecutore.submit(tag_audio.leggi_tag_remoto, capitolo.url, TIMEOUT_TAG): capitolo.url
                        for capitolo in mancanti
                    }
                    completati, _non_completati = concurrent.futures.wait(futuri, timeout=ATTESA_MASSIMA_TAG)
                    for futuro in completati:
                        try:
                            letti[futuri[futuro]] = (futuro.result() or {}).get("title", "")
                        except Exception as ex:
                            scrivi_log("LibriVoxCatalog.capitoli risultato tag", ex)
                finally:
                    esecutore.shutdown(wait=False, cancel_futures=True)
                if letti:
                    adesso = time.time()
                    self.db.esegui_molti(
                        "INSERT INTO librivox_tag_cache (url, title, read_at) VALUES (?, ?, ?) "
                        "ON CONFLICT (url) DO UPDATE SET title = excluded.title, read_at = excluded.read_at",
                        [(url, titolo, adesso) for url, titolo in letti.items()],
                    )
            for capitolo in capitoli:
                titolo_tag = cache.get(capitolo.url) or letti.get(capitolo.url) or ""
                capitolo.title = titolo_tag or capitolo.title or f"Capitolo {capitolo.numero}"
            return capitoli
        except ErroreLibriVox:
            raise
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.capitoli ({libro.id})", ex)
            raise ErroreLibriVox(str(ex)) from ex

    def dettagli(self, libro):
        try:
            dati = _leggi_json(
                API_LIBRI,
                [
                    ("id", int(libro.id)),
                    ("format", "json"),
                    ("fields[]", "description"),
                    ("fields[]", "genres"),
                    ("fields[]", "translators"),
                    ("fields[]", "authors"),
                ],
                TIMEOUT_DETTAGLI,
            )
            for elemento in _elenco(dati.get("books")):
                if not isinstance(elemento, dict):
                    continue
                generi = [
                    _pulisci(genere.get("name"))
                    for genere in _elenco(elemento.get("genres"))
                    if isinstance(genere, dict) and genere.get("name")
                ]
                traduttori = [
                    " ".join(parte for parte in (_pulisci(t.get("first_name")), _pulisci(t.get("last_name"))) if parte)
                    for t in _elenco(elemento.get("translators"))
                    if isinstance(t, dict)
                ]
                return {
                    "descrizione": testo_da_html(elemento.get("description")),
                    "generi": [genere for genere in generi if genere],
                    "traduttori": [nome for nome in traduttori if nome],
                }
            return {"descrizione": "", "generi": [], "traduttori": []}
        except Exception as ex:
            scrivi_log(f"LibriVoxCatalog.dettagli ({libro.id})", ex)
            raise ErroreLibriVox(str(ex)) from ex
