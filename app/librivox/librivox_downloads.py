import collections
import json
import re
import shutil
import threading
import time
import urllib.parse
from pathlib import Path

from gi.repository import GLib

from app.core import percorsi, rete
from app.core.log import scrivi_log
from app.librivox import tag_audio
from app.librivox.librivox_catalog import Capitolo, Libro

STATO_COMPLETATO = "completato"
STATO_IN_CORSO = "in_corso"
STATO_IN_CODA = "in_coda"
STATO_ERRORE = "errore"
ESITO_ACCODATO = "accodato"
ESTENSIONI_AUDIO = (".mp3", ".ogg", ".oga", ".opus", ".m4a", ".m4b", ".aac", ".flac", ".wav")
FILE_INFORMAZIONI = "librivox.json"
LUNGHEZZA_NOME = 90
TIMEOUT_CAPITOLO = 60


def cartella_librivox():
    return percorsi.cartella_dati() / "librivox"


def nome_sicuro(testo, predefinito="audiolibro"):
    try:
        valore = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", str(testo or ""))
        valore = " ".join(valore.split()).strip(" .")
        if len(valore) > LUNGHEZZA_NOME:
            valore = valore[:LUNGHEZZA_NOME].rstrip(" .")
        return valore or predefinito
    except Exception as ex:
        scrivi_log(f"librivox_downloads.nome_sicuro ({testo})", ex)
        return predefinito


def ordine_naturale(nome):
    try:
        return [int(parte) if parte.isdigit() else parte.lower() for parte in re.split(r"(\d+)", str(nome))]
    except Exception as ex:
        scrivi_log(f"librivox_downloads.ordine_naturale ({nome})", ex)
        return [str(nome)]


def estensione_audio(url):
    try:
        percorso = urllib.parse.urlparse(url).path.lower()
        for estensione in ESTENSIONI_AUDIO:
            if percorso.endswith(estensione):
                return estensione
        return ".mp3"
    except Exception as ex:
        scrivi_log(f"librivox_downloads.estensione_audio ({url})", ex)
        return ".mp3"


def leggi_informazioni(cartella):
    try:
        percorso = Path(cartella) / FILE_INFORMAZIONI
        if not percorso.is_file():
            return {}
        with open(percorso, "r", encoding="utf-8") as flusso:
            dati = json.load(flusso)
        return dati if isinstance(dati, dict) else {}
    except Exception as ex:
        scrivi_log(f"librivox_downloads.leggi_informazioni ({cartella})", ex)
        return {}


def capitoli_locali(cartella):
    capitoli = []
    try:
        base = Path(cartella)
        if not base.is_dir():
            return capitoli
        informazioni = leggi_informazioni(base)
        titoli_salvati = {}
        for elemento in informazioni.get("capitoli") or []:
            if isinstance(elemento, dict) and elemento.get("file"):
                titoli_salvati[str(elemento["file"])] = str(elemento.get("title") or "")
        file_audio = sorted(
            (voce for voce in base.iterdir() if voce.is_file() and voce.suffix.lower() in ESTENSIONI_AUDIO),
            key=lambda voce: ordine_naturale(voce.name),
        )
        for numero, voce in enumerate(file_audio, start=1):
            tag = tag_audio.leggi_tag_file(voce)
            titolo = tag.get("title") or titoli_salvati.get(voce.name) or voce.stem
            capitoli.append(Capitolo(numero=numero, title=titolo, url=str(voce), file_name=voce.name))
    except Exception as ex:
        scrivi_log(f"librivox_downloads.capitoli_locali ({cartella})", ex)
    return capitoli


class LibriVoxDownloads:
    def __init__(self, db, catalogo, al_completamento=None, al_errore=None):
        self.db = db
        self.catalogo = catalogo
        self.al_completamento = al_completamento
        self.al_errore = al_errore
        self._coda = collections.deque()
        self._blocco = threading.Lock()
        self._evento = threading.Event()
        self._fermo = threading.Event()
        self._corrente = None
        self._da_eliminare = set()
        self._thread = None
        self._ripresi = False

    def avvia(self):
        try:
            with self._blocco:
                if self._thread is not None and self._thread.is_alive():
                    return
                self._fermo.clear()
                if not self._ripresi:
                    self._ripresi = True
                    for riga in self.db.leggi_tutti(
                        "SELECT book_id, title, authors, language FROM librivox_downloads WHERE status IN (?, ?) "
                        "ORDER BY added_at",
                        (STATO_IN_CODA, STATO_IN_CORSO),
                    ):
                        self._coda.append(self._libro(riga[0], riga[1], riga[2], riga[3]))
                self._thread = threading.Thread(target=self._lavoro, name="DownloadLibriVox", daemon=True)
                self._thread.start()
            self._evento.set()
        except Exception as ex:
            scrivi_log("LibriVoxDownloads.avvia", ex)

    def ferma(self):
        try:
            self._fermo.set()
            with self._blocco:
                if self._corrente is not None:
                    self._corrente["annulla"].set()
            self._evento.set()
        except Exception as ex:
            scrivi_log("LibriVoxDownloads.ferma", ex)

    def _libro(self, identificativo, titolo, autori, lingua):
        try:
            if self.catalogo is not None:
                trovato = self.catalogo.libro(identificativo)
                if trovato is not None:
                    return trovato
            return Libro(id=int(identificativo), title=titolo, authors=autori, language=lingua)
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads._libro ({identificativo})", ex)
            return Libro(id=int(identificativo), title=str(titolo), authors=str(autori), language=str(lingua))

    def _riga(self, id_libro):
        try:
            return self.db.leggi_uno(
                "SELECT book_id, title, authors, language, folder, chapters_total, chapters_done, size, status, error "
                "FROM librivox_downloads WHERE book_id = ?",
                (int(id_libro),),
            )
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads._riga ({id_libro})", ex)
            return None

    def stato(self, id_libro):
        try:
            with self._blocco:
                if self._corrente is not None and self._corrente["libro"].id == int(id_libro):
                    return STATO_IN_CORSO
                if any(libro.id == int(id_libro) for libro in self._coda):
                    return STATO_IN_CODA
            riga = self._riga(id_libro)
            if riga is None:
                return None
            if riga[8] == STATO_COMPLETATO:
                return STATO_COMPLETATO if riga[4] and Path(riga[4]).is_dir() else None
            if riga[8] == STATO_ERRORE:
                return STATO_ERRORE
            return STATO_IN_CODA
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads.stato ({id_libro})", ex)
            return None

    def cartella(self, id_libro):
        try:
            riga = self._riga(id_libro)
            if riga is not None and riga[8] == STATO_COMPLETATO and riga[4] and Path(riga[4]).is_dir():
                return Path(riga[4])
            return None
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads.cartella ({id_libro})", ex)
            return None

    def accoda(self, libro):
        try:
            if self._in_memoria(libro.id):
                return self.stato(libro.id)
            if self.stato(libro.id) == STATO_COMPLETATO:
                return STATO_COMPLETATO
            if not self.db.esegui(
                "INSERT INTO librivox_downloads (book_id, title, authors, language, status, error, added_at) "
                "VALUES (?, ?, ?, ?, ?, '', ?) "
                "ON CONFLICT (book_id) DO UPDATE SET status = excluded.status, error = '', title = excluded.title, "
                "authors = excluded.authors, language = excluded.language",
                (int(libro.id), libro.title, libro.authors, libro.language, STATO_IN_CODA, time.time()),
            ):
                return None
            with self._blocco:
                self._da_eliminare.discard(int(libro.id))
                self._coda.append(libro)
            self.avvia()
            self._evento.set()
            return ESITO_ACCODATO
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads.accoda ({getattr(libro, 'id', '')})", ex)
            return None

    def _in_memoria(self, id_libro):
        try:
            with self._blocco:
                if self._corrente is not None and self._corrente["libro"].id == int(id_libro):
                    return True
                return any(libro.id == int(id_libro) for libro in self._coda)
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads._in_memoria ({id_libro})", ex)
            return False

    def riprova(self, id_libro):
        try:
            riga = self._riga(id_libro)
            if riga is None:
                return None
            return self.accoda(self._libro(riga[0], riga[1], riga[2], riga[3]))
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads.riprova ({id_libro})", ex)
            return None

    def _rimuovi_cartella(self, cartella):
        try:
            if not cartella:
                return True
            percorso = Path(cartella).resolve()
            base = cartella_librivox().resolve()
            if percorso == base or base not in percorso.parents:
                scrivi_log(f"LibriVoxDownloads._rimuovi_cartella: cartella fuori da {base} ({percorso})")
                return False
            if percorso.is_dir():
                shutil.rmtree(percorso)
            return True
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads._rimuovi_cartella ({cartella})", ex)
            return False

    def elimina(self, id_libro):
        try:
            identificativo = int(id_libro)
            with self._blocco:
                for libro in list(self._coda):
                    if libro.id == identificativo:
                        self._coda.remove(libro)
                if self._corrente is not None and self._corrente["libro"].id == identificativo:
                    self._da_eliminare.add(identificativo)
                    self._corrente["annulla"].set()
                    return True
            riga = self._riga(identificativo)
            if riga is not None and not self._rimuovi_cartella(riga[4]):
                return False
            return self.db.esegui("DELETE FROM librivox_downloads WHERE book_id = ?", (identificativo,))
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads.elimina ({id_libro})", ex)
            return False

    def elenco(self):
        risultati = []
        try:
            mancanti = []
            for riga in self.db.leggi_tutti(
                "SELECT book_id, title, authors, language, folder, chapters_total, size FROM librivox_downloads "
                "WHERE status = ? ORDER BY title COLLATE NOCASE",
                (STATO_COMPLETATO,),
            ):
                if not riga[4] or not Path(riga[4]).is_dir():
                    mancanti.append((riga[0],))
                    continue
                risultati.append(
                    {
                        "libro": self._libro(riga[0], riga[1], riga[2], riga[3]),
                        "cartella": Path(riga[4]),
                        "capitoli": int(riga[5] or 0),
                        "size": int(riga[6] or 0),
                    }
                )
            if mancanti:
                self.db.esegui_molti("DELETE FROM librivox_downloads WHERE book_id = ?", mancanti)
        except Exception as ex:
            scrivi_log("LibriVoxDownloads.elenco", ex)
        return risultati

    def in_corso(self):
        elenco = []
        try:
            identificativi = set()
            with self._blocco:
                if self._corrente is not None:
                    corrente = dict(self._corrente)
                    identificativi.add(corrente["libro"].id)
                    totale = corrente["totale"]
                    elenco.append(
                        {
                            "libro": corrente["libro"],
                            "stato": STATO_IN_CORSO,
                            "capitolo": corrente["capitolo"],
                            "capitoli": corrente["capitoli"],
                            "percentuale": int(corrente["letti"] * 100 / totale) if totale else None,
                            "errore": "",
                        }
                    )
                for libro in self._coda:
                    identificativi.add(libro.id)
                    elenco.append(
                        {"libro": libro, "stato": STATO_IN_CODA, "capitolo": 0, "capitoli": 0, "percentuale": None, "errore": ""}
                    )
            for riga in self.db.leggi_tutti(
                "SELECT book_id, title, authors, language, chapters_total, chapters_done, error FROM librivox_downloads "
                "WHERE status = ? ORDER BY added_at",
                (STATO_ERRORE,),
            ):
                if int(riga[0]) in identificativi:
                    continue
                elenco.append(
                    {
                        "libro": self._libro(riga[0], riga[1], riga[2], riga[3]),
                        "stato": STATO_ERRORE,
                        "capitolo": int(riga[5] or 0),
                        "capitoli": int(riga[4] or 0),
                        "percentuale": None,
                        "errore": riga[6] or "",
                    }
                )
        except Exception as ex:
            scrivi_log("LibriVoxDownloads.in_corso", ex)
        return elenco

    def numero_in_corso(self):
        try:
            return len(self.in_corso())
        except Exception as ex:
            scrivi_log("LibriVoxDownloads.numero_in_corso", ex)
            return 0

    def _lavoro(self):
        try:
            while not self._fermo.is_set():
                with self._blocco:
                    libro = self._coda.popleft() if self._coda else None
                    if libro is not None:
                        self._corrente = {
                            "libro": libro,
                            "annulla": threading.Event(),
                            "capitolo": 0,
                            "capitoli": 0,
                            "letti": 0,
                            "totale": 0,
                        }
                    else:
                        self._evento.clear()
                if libro is None:
                    self._evento.wait(60)
                    continue
                try:
                    self._scarica(libro)
                finally:
                    with self._blocco:
                        self._corrente = None
        except Exception as ex:
            scrivi_log("LibriVoxDownloads._lavoro", ex)

    def _aggiorna_avanzamento(self, letti, totale):
        try:
            with self._blocco:
                if self._corrente is not None:
                    self._corrente["letti"] = letti
                    self._corrente["totale"] = totale
        except Exception as ex:
            scrivi_log("LibriVoxDownloads._aggiorna_avanzamento", ex)

    def _cartella_nuova(self, libro):
        try:
            base = cartella_librivox()
            nome = nome_sicuro(f"{libro.authors} - {libro.title}" if libro.authors else libro.title)
            candidata = base / nome
            if candidata.exists() and str(leggi_informazioni(candidata).get("id", "")) != str(libro.id):
                candidata = base / f"{nome} ({libro.id})"
            return candidata
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads._cartella_nuova ({libro.id})", ex)
            return cartella_librivox() / str(libro.id)

    def _scrivi_informazioni(self, cartella, libro, capitoli, nomi_file):
        try:
            dati = {
                "id": libro.id,
                "title": libro.title,
                "authors": libro.authors,
                "language": libro.language,
                "totaltime": libro.totaltime,
                "url_librivox": libro.url_librivox,
                "capitoli": [
                    {"numero": capitolo.numero, "title": capitolo.title, "file": nome, "url": capitolo.url}
                    for capitolo, nome in zip(capitoli, nomi_file)
                ],
            }
            temporaneo = Path(cartella) / (FILE_INFORMAZIONI + ".tmp")
            with open(temporaneo, "w", encoding="utf-8") as flusso:
                json.dump(dati, flusso, ensure_ascii=False, indent=1)
            temporaneo.replace(Path(cartella) / FILE_INFORMAZIONI)
            return True
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads._scrivi_informazioni ({cartella})", ex)
            return False

    def _scarica(self, libro):
        identificativo = int(libro.id)
        try:
            with self._blocco:
                annulla = self._corrente["annulla"] if self._corrente is not None else threading.Event()
            self.db.esegui(
                "UPDATE librivox_downloads SET status = ?, error = '' WHERE book_id = ?",
                (STATO_IN_CORSO, identificativo),
            )
            capitoli = self.catalogo.capitoli(libro)
            riga = self._riga(identificativo)
            cartella = Path(riga[4]) if riga is not None and riga[4] else self._cartella_nuova(libro)
            cartella.mkdir(parents=True, exist_ok=True)
            nomi_file = [
                f"{posizione:03d} - {nome_sicuro(capitolo.title, 'Capitolo')}{estensione_audio(capitolo.url)}"
                for posizione, capitolo in enumerate(capitoli, start=1)
            ]
            self._scrivi_informazioni(cartella, libro, capitoli, nomi_file)
            self.db.esegui(
                "UPDATE librivox_downloads SET folder = ?, chapters_total = ? WHERE book_id = ?",
                (str(cartella), len(capitoli), identificativo),
            )
            dimensione = 0
            for posizione, (capitolo, nome) in enumerate(zip(capitoli, nomi_file), start=1):
                if annulla.is_set() or self._fermo.is_set():
                    raise rete.DownloadAnnullato(libro.title)
                with self._blocco:
                    if self._corrente is not None:
                        self._corrente.update({"capitolo": posizione, "capitoli": len(capitoli), "letti": 0, "totale": 0})
                destinazione = cartella / nome
                if destinazione.is_file() and destinazione.stat().st_size > 0:
                    dimensione += destinazione.stat().st_size
                else:
                    dimensione += rete.scarica_file(
                        capitolo.url,
                        destinazione,
                        self._aggiorna_avanzamento,
                        annulla,
                        TIMEOUT_CAPITOLO,
                    )
                self.db.esegui(
                    "UPDATE librivox_downloads SET chapters_done = ?, size = ? WHERE book_id = ?",
                    (posizione, dimensione, identificativo),
                )
            if not self.db.esegui(
                "UPDATE librivox_downloads SET status = ?, size = ?, completed_at = ? WHERE book_id = ?",
                (STATO_COMPLETATO, dimensione, time.time(), identificativo),
            ):
                raise RuntimeError("Registrazione del download nel database non riuscita")
            if self.al_completamento is not None:
                GLib.idle_add(self._consegna, self.al_completamento, libro)
        except rete.DownloadAnnullato:
            try:
                with self._blocco:
                    da_eliminare = identificativo in self._da_eliminare
                    self._da_eliminare.discard(identificativo)
                if da_eliminare:
                    riga = self._riga(identificativo)
                    if riga is not None:
                        self._rimuovi_cartella(riga[4])
                    self.db.esegui("DELETE FROM librivox_downloads WHERE book_id = ?", (identificativo,))
            except Exception as ex:
                scrivi_log(f"LibriVoxDownloads._scarica annullamento ({identificativo})", ex)
        except Exception as ex:
            scrivi_log(f"LibriVoxDownloads._scarica ({identificativo})", ex)
            try:
                self.db.esegui(
                    "UPDATE librivox_downloads SET status = ?, error = ? WHERE book_id = ?",
                    (STATO_ERRORE, str(ex)[:300], identificativo),
                )
            except Exception as ex_stato:
                scrivi_log(f"LibriVoxDownloads._scarica stato errore ({identificativo})", ex_stato)
            if self.al_errore is not None and not self._fermo.is_set():
                GLib.idle_add(self._consegna, self.al_errore, libro)

    def _consegna(self, funzione, libro):
        try:
            funzione(libro)
        except Exception as ex:
            scrivi_log("LibriVoxDownloads._consegna", ex)
        return False
