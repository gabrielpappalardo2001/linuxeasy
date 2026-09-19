import getpass
import os
import re
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.log import scrivi_log

CARATTERI_VIETATI = re.compile(r"[/\x00-\x1f]")
LUNGHEZZA_MASSIMA_NOME = 200
CARTELLE_UTENTE = (
    ("XDG_DESKTOP_DIR", "Scrivania", "Desktop"),
    ("XDG_DOCUMENTS_DIR", "Documenti", "Documents"),
    ("XDG_DOWNLOAD_DIR", "Scaricati", "Downloads"),
    ("XDG_MUSIC_DIR", "Musica", "Music"),
    ("XDG_PICTURES_DIR", "Immagini", "Pictures"),
    ("XDG_VIDEOS_DIR", "Video", "Videos"),
)


class ErroreFile(Exception):
    pass


class FileEsistente(ErroreFile):
    pass


@dataclass
class VoceFile:
    nome: str
    percorso: Path
    cartella: bool
    dimensione: int = 0
    modificato: float = 0.0
    nascosto: bool = False


def ordine_naturale(testo):
    try:
        return [int(parte) if parte.isdigit() else parte.casefold() for parte in re.split(r"(\d+)", str(testo))]
    except Exception as ex:
        scrivi_log(f"gestore_file.ordine_naturale ({testo})", ex)
        return [str(testo)]


def dimensione_leggibile(byte):
    try:
        valore = float(byte or 0)
        for unita in ("byte", "KB", "MB", "GB"):
            if valore < 1024 or unita == "GB":
                if unita == "byte":
                    return f"{int(valore)} byte"
                return f"{valore:.1f} {unita}".replace(".", ",")
            valore /= 1024
        return f"{valore:.1f} TB".replace(".", ",")
    except Exception as ex:
        scrivi_log(f"gestore_file.dimensione_leggibile ({byte})", ex)
        return str(byte)


def _messaggio_errore(eccezione, percorso):
    try:
        if isinstance(eccezione, PermissionError):
            return f"Permesso negato: {percorso}"
        if isinstance(eccezione, FileNotFoundError):
            return f"Percorso inesistente: {percorso}"
        if isinstance(eccezione, NotADirectoryError):
            return f"Non è una cartella: {percorso}"
        if isinstance(eccezione, IsADirectoryError):
            return f"È una cartella: {percorso}"
        if isinstance(eccezione, FileExistsError):
            return f"Esiste già: {percorso}"
        if isinstance(eccezione, OSError) and eccezione.strerror:
            return f"{eccezione.strerror}: {percorso}"
        return f"{eccezione}: {percorso}"
    except Exception as ex:
        scrivi_log("gestore_file._messaggio_errore", ex)
        return str(percorso)


class GestoreFile:
    def __init__(self, cartella_iniziale=None):
        self.cartella_iniziale = Path(cartella_iniziale) if cartella_iniziale else None

    def cartella_home(self):
        try:
            return Path.home()
        except Exception as ex:
            scrivi_log("GestoreFile.cartella_home", ex)
            return Path("/")

    def _leggi_cartelle_utente(self):
        valori = {}
        try:
            base = os.environ.get("XDG_CONFIG_HOME", "").strip()
            configurazione = Path(base) if base and os.path.isabs(base) else self.cartella_home() / ".config"
            percorso = configurazione / "user-dirs.dirs"
            if not percorso.is_file():
                return valori
            home = str(self.cartella_home())
            for riga in percorso.read_text(encoding="utf-8", errors="replace").splitlines():
                riga = riga.strip()
                if not riga or riga.startswith("#") or "=" not in riga:
                    continue
                chiave, valore = riga.split("=", 1)
                parti = shlex.split(valore)
                if not parti:
                    continue
                testo = parti[0].replace("$HOME", home)
                if os.path.isabs(testo):
                    valori[chiave.strip()] = Path(testo)
        except Exception as ex:
            scrivi_log("GestoreFile._leggi_cartelle_utente", ex)
        return valori

    def cartella_documenti(self):
        try:
            for nome, percorso in self.cartelle_principali():
                if nome == "Documenti":
                    return percorso
            return self.cartella_home()
        except Exception as ex:
            scrivi_log("GestoreFile.cartella_documenti", ex)
            return self.cartella_home()

    def cartelle_principali(self):
        elenco = []
        try:
            home = self.cartella_home()
            elenco.append(("Cartella personale", home))
            configurate = self._leggi_cartelle_utente()
            visti = {home}
            for chiave, nome, predefinita in CARTELLE_UTENTE:
                percorso = configurate.get(chiave) or home / predefinita
                if percorso.is_dir() and percorso not in visti:
                    visti.add(percorso)
                    elenco.append((nome, percorso))
            try:
                utente = getpass.getuser()
            except Exception as ex:
                scrivi_log("GestoreFile.cartelle_principali utente", ex)
                utente = ""
            for base in (Path("/media") / utente, Path("/run/media") / utente, Path("/mnt")):
                try:
                    if base.is_dir():
                        for voce in sorted(base.iterdir(), key=lambda v: ordine_naturale(v.name)):
                            if voce.is_dir() and voce not in visti:
                                visti.add(voce)
                                elenco.append((f"Dispositivo {voce.name}", voce))
                except Exception as ex:
                    scrivi_log(f"GestoreFile.cartelle_principali dispositivi ({base})", ex)
            elenco.append(("Radice del sistema", Path("/")))
        except Exception as ex:
            scrivi_log("GestoreFile.cartelle_principali", ex)
        return elenco

    def normalizza(self, percorso):
        try:
            return Path(os.path.abspath(os.path.expanduser(str(percorso))))
        except Exception as ex:
            scrivi_log(f"GestoreFile.normalizza ({percorso})", ex)
            return Path(str(percorso))

    def nome_visualizzato(self, percorso):
        try:
            cartella = self.normalizza(percorso)
            if str(cartella) == "/":
                return "Radice del sistema"
            if cartella == self.cartella_home():
                return "Cartella personale"
            return cartella.name
        except Exception as ex:
            scrivi_log(f"GestoreFile.nome_visualizzato ({percorso})", ex)
            return str(percorso)

    def cartella_superiore(self, percorso):
        try:
            cartella = self.normalizza(percorso)
            genitore = cartella.parent
            return None if genitore == cartella else genitore
        except Exception as ex:
            scrivi_log(f"GestoreFile.cartella_superiore ({percorso})", ex)
            return None

    def elenco(self, cartella, con_file=True, nascosti=False, estensioni=None):
        percorso = self.normalizza(cartella)
        try:
            filtri = tuple(estensione.lower() for estensione in estensioni) if estensioni else None
            cartelle = []
            files = []
            with os.scandir(percorso) as voci:
                for voce in voci:
                    try:
                        nascosto = voce.name.startswith(".")
                        if nascosto and not nascosti:
                            continue
                        e_cartella = voce.is_dir(follow_symlinks=True)
                        if not e_cartella and not con_file:
                            continue
                        if not e_cartella and filtri and not voce.name.lower().endswith(filtri):
                            continue
                        informazioni = voce.stat(follow_symlinks=True)
                        elemento = VoceFile(
                            nome=voce.name,
                            percorso=Path(voce.path),
                            cartella=e_cartella,
                            dimensione=0 if e_cartella else informazioni.st_size,
                            modificato=informazioni.st_mtime,
                            nascosto=nascosto,
                        )
                        (cartelle if e_cartella else files).append(elemento)
                    except FileNotFoundError:
                        continue
                    except Exception as ex:
                        scrivi_log(f"GestoreFile.elenco voce ({voce.path})", ex)
            cartelle.sort(key=lambda elemento: ordine_naturale(elemento.nome))
            files.sort(key=lambda elemento: ordine_naturale(elemento.nome))
            return cartelle + files
        except Exception as ex:
            scrivi_log(f"GestoreFile.elenco ({percorso})", ex)
            raise ErroreFile(_messaggio_errore(ex, percorso)) from ex

    def esiste(self, percorso):
        try:
            return self.normalizza(percorso).exists()
        except Exception as ex:
            scrivi_log(f"GestoreFile.esiste ({percorso})", ex)
            return False

    def e_cartella(self, percorso):
        try:
            return self.normalizza(percorso).is_dir()
        except Exception as ex:
            scrivi_log(f"GestoreFile.e_cartella ({percorso})", ex)
            return False

    def scrivibile(self, cartella):
        try:
            percorso = self.normalizza(cartella)
            return percorso.is_dir() and os.access(percorso, os.W_OK | os.X_OK)
        except Exception as ex:
            scrivi_log(f"GestoreFile.scrivibile ({cartella})", ex)
            return False

    def nome_valido(self, nome, predefinito=""):
        try:
            valore = CARATTERI_VIETATI.sub(" ", str(nome or ""))
            valore = " ".join(valore.split()).strip()
            if valore in (".", ".."):
                valore = ""
            if len(valore.encode("utf-8")) > LUNGHEZZA_MASSIMA_NOME:
                valore = valore.encode("utf-8")[:LUNGHEZZA_MASSIMA_NOME].decode("utf-8", errors="ignore").rstrip()
            return valore or predefinito
        except Exception as ex:
            scrivi_log(f"GestoreFile.nome_valido ({nome})", ex)
            return predefinito

    def con_estensione(self, nome, estensione):
        try:
            if not estensione:
                return nome
            suffisso = estensione if estensione.startswith(".") else f".{estensione}"
            if nome.lower().endswith(suffisso.lower()):
                return nome
            return f"{nome}{suffisso}"
        except Exception as ex:
            scrivi_log(f"GestoreFile.con_estensione ({nome})", ex)
            return nome

    def crea_cartella(self, genitore, nome):
        destinazione = None
        try:
            valido = self.nome_valido(nome)
            if not valido:
                raise ErroreFile("Il nome della cartella non è valido.")
            destinazione = self.normalizza(genitore) / valido
            if destinazione.exists():
                raise FileEsistente(f"Esiste già: {destinazione}")
            destinazione.mkdir()
            return destinazione
        except ErroreFile:
            raise
        except Exception as ex:
            scrivi_log(f"GestoreFile.crea_cartella ({genitore}, {nome})", ex)
            raise ErroreFile(_messaggio_errore(ex, destinazione or genitore)) from ex

    def salva_testo(self, cartella, nome, testo, sovrascrivi=False, codifica="utf-8"):
        destinazione = None
        temporaneo = None
        try:
            valido = self.nome_valido(nome)
            if not valido:
                raise ErroreFile("Il nome del file non è valido.")
            base = self.normalizza(cartella)
            if not base.is_dir():
                raise ErroreFile(f"La cartella non esiste: {base}")
            destinazione = base / valido
            if destinazione.is_dir():
                raise ErroreFile(f"Esiste già una cartella con questo nome: {destinazione}")
            if destinazione.exists() and not sovrascrivi:
                raise FileEsistente(f"Il file esiste già: {destinazione}")
            contenuto = str(testo or "").replace("\r\n", "\n")
            if not contenuto.endswith("\n"):
                contenuto += "\n"
            descrittore, nome_temporaneo = tempfile.mkstemp(prefix=".linuxeasy-", suffix=".tmp", dir=str(base))
            temporaneo = Path(nome_temporaneo)
            with os.fdopen(descrittore, "w", encoding=codifica, newline="\n") as flusso:
                flusso.write(contenuto)
            os.chmod(temporaneo, 0o644)
            os.replace(temporaneo, destinazione)
            temporaneo = None
            return destinazione
        except ErroreFile:
            raise
        except Exception as ex:
            scrivi_log(f"GestoreFile.salva_testo ({cartella}, {nome})", ex)
            raise ErroreFile(_messaggio_errore(ex, destinazione or cartella)) from ex
        finally:
            try:
                if temporaneo is not None and temporaneo.exists():
                    temporaneo.unlink()
            except Exception as ex:
                scrivi_log(f"GestoreFile.salva_testo pulizia ({temporaneo})", ex)

    def leggi_testo(self, percorso, codifica="utf-8"):
        file_testo = self.normalizza(percorso)
        try:
            return file_testo.read_text(encoding=codifica, errors="replace")
        except Exception as ex:
            scrivi_log(f"GestoreFile.leggi_testo ({file_testo})", ex)
            raise ErroreFile(_messaggio_errore(ex, file_testo)) from ex

    def rinomina(self, percorso, nuovo_nome):
        origine = self.normalizza(percorso)
        try:
            valido = self.nome_valido(nuovo_nome)
            if not valido:
                raise ErroreFile("Il nuovo nome non è valido.")
            destinazione = origine.with_name(valido)
            if destinazione.exists():
                raise FileEsistente(f"Esiste già: {destinazione}")
            origine.rename(destinazione)
            return destinazione
        except ErroreFile:
            raise
        except Exception as ex:
            scrivi_log(f"GestoreFile.rinomina ({origine}, {nuovo_nome})", ex)
            raise ErroreFile(_messaggio_errore(ex, origine)) from ex

    def copia(self, percorso, cartella_destinazione, sovrascrivi=False):
        origine = self.normalizza(percorso)
        try:
            destinazione = self.normalizza(cartella_destinazione) / origine.name
            if destinazione.exists() and not sovrascrivi:
                raise FileEsistente(f"Esiste già: {destinazione}")
            if origine.is_dir():
                shutil.copytree(origine, destinazione, dirs_exist_ok=sovrascrivi)
            else:
                shutil.copy2(origine, destinazione)
            return destinazione
        except ErroreFile:
            raise
        except Exception as ex:
            scrivi_log(f"GestoreFile.copia ({origine}, {cartella_destinazione})", ex)
            raise ErroreFile(_messaggio_errore(ex, origine)) from ex

    def sposta(self, percorso, cartella_destinazione):
        origine = self.normalizza(percorso)
        try:
            destinazione = self.normalizza(cartella_destinazione) / origine.name
            if destinazione.exists():
                raise FileEsistente(f"Esiste già: {destinazione}")
            return Path(shutil.move(str(origine), str(destinazione)))
        except ErroreFile:
            raise
        except Exception as ex:
            scrivi_log(f"GestoreFile.sposta ({origine}, {cartella_destinazione})", ex)
            raise ErroreFile(_messaggio_errore(ex, origine)) from ex

    def elimina(self, percorso, ricorsivo=False):
        bersaglio = self.normalizza(percorso)
        try:
            if str(bersaglio) == "/" or bersaglio == self.cartella_home():
                raise ErroreFile(f"Eliminazione non consentita: {bersaglio}")
            if bersaglio.is_dir() and not bersaglio.is_symlink():
                if ricorsivo:
                    shutil.rmtree(bersaglio)
                else:
                    bersaglio.rmdir()
            else:
                bersaglio.unlink()
            return True
        except ErroreFile:
            raise
        except Exception as ex:
            scrivi_log(f"GestoreFile.elimina ({bersaglio})", ex)
            raise ErroreFile(_messaggio_errore(ex, bersaglio)) from ex

    def informazioni(self, percorso):
        bersaglio = self.normalizza(percorso)
        try:
            stato = bersaglio.stat()
            return {
                "nome": bersaglio.name or str(bersaglio),
                "percorso": str(bersaglio),
                "cartella": bersaglio.is_dir(),
                "dimensione": stato.st_size,
                "modificato": time.strftime("%d/%m/%Y %H:%M", time.localtime(stato.st_mtime)),
                "scrivibile": os.access(bersaglio, os.W_OK),
            }
        except Exception as ex:
            scrivi_log(f"GestoreFile.informazioni ({bersaglio})", ex)
            raise ErroreFile(_messaggio_errore(ex, bersaglio)) from ex
