import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from app.core.log import scrivi_log

URL_ULTIMA_VERSIONE_YTDLP = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
URL_YTDLP = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
URL_DENO = "https://github.com/denoland/deno/releases/latest/download/deno-{architettura}-unknown-linux-gnu.zip"
ARCHITETTURE_DENO = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}
SECONDI_RICHIESTA = 60
SECONDI_SCARICAMENTO = 600
SECONDI_PROVA = 40
SECONDI_VALIDITA_YTDLP = 24 * 3600
SECONDI_VALIDITA_DENO = 30 * 24 * 3600
SECONDI_TRA_TENTATIVI = 6 * 3600
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) LinuxEasy/1.0"

_blocco = threading.Lock()
_manutenzione_avviata = False


def cartella_strumenti():
    return Path.home() / ".local" / "share" / "linux-easy" / "strumenti"


def cartella_eseguibili():
    return cartella_strumenti() / "bin"


def _file_stato():
    return cartella_strumenti() / "stato.json"


def _leggi_stato():
    try:
        percorso = _file_stato()
        if not percorso.is_file():
            return {}
        dati = json.loads(percorso.read_text(encoding="utf-8"))
        return dati if isinstance(dati, dict) else {}
    except Exception as ex:
        scrivi_log("strumenti_youtube._leggi_stato", ex)
        return {}


def _scrivi_stato(stato):
    try:
        cartella_strumenti().mkdir(parents=True, exist_ok=True)
        _file_stato().write_text(json.dumps(stato), encoding="utf-8")
    except Exception as ex:
        scrivi_log("strumenti_youtube._scrivi_stato", ex)


def _aggiungi_al_percorso(cartella):
    try:
        voci = [voce for voce in os.environ.get("PATH", "").split(os.pathsep) if voce]
        if cartella in voci:
            voci.remove(cartella)
        os.environ["PATH"] = os.pathsep.join([cartella] + voci)
    except Exception as ex:
        scrivi_log(f"strumenti_youtube._aggiungi_al_percorso ({cartella})", ex)


def prepara_ambiente():
    try:
        cartella = cartella_eseguibili()
        cartella.mkdir(parents=True, exist_ok=True)
        _aggiungi_al_percorso(str(Path(sys.executable).parent))
        _aggiungi_al_percorso(str(cartella))
        programma = cartella / "yt-dlp"
        if programma.is_file() and str(programma) not in sys.path:
            sys.path.insert(0, str(programma))
        return True
    except Exception as ex:
        scrivi_log("strumenti_youtube.prepara_ambiente", ex)
        return False


def _scarica(url, destinazione, secondi):
    richiesta = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(richiesta, timeout=secondi) as risposta:
        with open(destinazione, "wb") as file:
            shutil.copyfileobj(risposta, file)


def _file_temporaneo(suffisso):
    descrittore, percorso = tempfile.mkstemp(prefix="nuovo-", suffix=suffisso, dir=str(cartella_eseguibili()))
    os.close(descrittore)
    return Path(percorso)


def _rendi_eseguibile(percorso):
    modalita = os.stat(percorso).st_mode
    os.chmod(percorso, modalita | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _versione(comando):
    try:
        esito = subprocess.run(comando, capture_output=True, text=True, timeout=SECONDI_PROVA)
        if esito.returncode != 0:
            return ""
        return (esito.stdout or "").strip().splitlines()[0].strip() if (esito.stdout or "").strip() else ""
    except Exception as ex:
        scrivi_log(f"strumenti_youtube._versione ({comando})", ex)
        return ""


def versione_ytdlp_installata():
    programma = cartella_eseguibili() / "yt-dlp"
    if not programma.is_file():
        return ""
    return _versione([sys.executable, str(programma), "--version"])


def _ultima_versione_ytdlp():
    richiesta = urllib.request.Request(
        URL_ULTIMA_VERSIONE_YTDLP,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(richiesta, timeout=SECONDI_RICHIESTA) as risposta:
        dati = json.loads(risposta.read().decode("utf-8"))
    return str(dati.get("tag_name") or "").strip()


def _deve_provare(stato, nome, validita, forza):
    adesso = time.time()
    if forza:
        return True
    if adesso - float(stato.get(f"tentativo_{nome}", 0) or 0) < SECONDI_TRA_TENTATIVI:
        return False
    return adesso - float(stato.get(f"riuscito_{nome}", 0) or 0) >= validita


def aggiorna_ytdlp(forza=False):
    try:
        stato = _leggi_stato()
        programma = cartella_eseguibili() / "yt-dlp"
        if programma.is_file() and not _deve_provare(stato, "ytdlp", SECONDI_VALIDITA_YTDLP, forza):
            return versione_ytdlp_installata()
        cartella_eseguibili().mkdir(parents=True, exist_ok=True)
        stato["tentativo_ytdlp"] = time.time()
        _scrivi_stato(stato)
        temporaneo = None
        try:
            installata = versione_ytdlp_installata()
            ultima = _ultima_versione_ytdlp()
            if installata and ultima and installata == ultima:
                stato["riuscito_ytdlp"] = time.time()
                _scrivi_stato(stato)
                return installata
            temporaneo = _file_temporaneo(".ytdlp")
            _scarica(URL_YTDLP, temporaneo, SECONDI_SCARICAMENTO)
            _rendi_eseguibile(temporaneo)
            nuova = _versione([sys.executable, str(temporaneo), "--version"])
            if not nuova:
                raise RuntimeError("il file di yt-dlp scaricato non si avvia con questa versione di Python")
            os.replace(temporaneo, programma)
            temporaneo = None
            stato["riuscito_ytdlp"] = time.time()
            _scrivi_stato(stato)
            return nuova
        finally:
            if temporaneo is not None:
                try:
                    temporaneo.unlink()
                except Exception as ex_pulizia:
                    scrivi_log("strumenti_youtube.aggiorna_ytdlp pulizia", ex_pulizia)
    except Exception as ex:
        scrivi_log("strumenti_youtube.aggiorna_ytdlp", ex)
        return ""


def _deno_di_sistema():
    try:
        nostra = str(cartella_eseguibili())
        percorso = os.pathsep.join(
            voce for voce in os.environ.get("PATH", "").split(os.pathsep) if voce and voce != nostra
        )
        return shutil.which("deno", path=percorso) or ""
    except Exception as ex:
        scrivi_log("strumenti_youtube._deno_di_sistema", ex)
        return ""


def aggiorna_deno(forza=False):
    try:
        if _deno_di_sistema():
            return "sistema"
        stato = _leggi_stato()
        programma = cartella_eseguibili() / "deno"
        if programma.is_file() and not _deve_provare(stato, "deno", SECONDI_VALIDITA_DENO, forza):
            return _versione([str(programma), "--version"])
        architettura = ARCHITETTURE_DENO.get(platform.machine().lower())
        if architettura is None:
            scrivi_log(f"strumenti_youtube.aggiorna_deno: architettura non supportata ({platform.machine()})")
            return ""
        cartella_eseguibili().mkdir(parents=True, exist_ok=True)
        stato["tentativo_deno"] = time.time()
        _scrivi_stato(stato)
        archivio = None
        estratto = None
        try:
            archivio = _file_temporaneo(".zip")
            _scarica(URL_DENO.format(architettura=architettura), archivio, SECONDI_SCARICAMENTO)
            estratto = _file_temporaneo(".deno")
            with zipfile.ZipFile(archivio) as contenitore:
                with contenitore.open("deno") as sorgente, open(estratto, "wb") as destinazione:
                    shutil.copyfileobj(sorgente, destinazione)
            _rendi_eseguibile(estratto)
            nuova = _versione([str(estratto), "--version"])
            if not nuova:
                raise RuntimeError("deno scaricato non si avvia su questo sistema")
            os.replace(estratto, programma)
            estratto = None
            stato["riuscito_deno"] = time.time()
            _scrivi_stato(stato)
            return nuova
        finally:
            for residuo in (archivio, estratto):
                if residuo is not None:
                    try:
                        residuo.unlink()
                    except FileNotFoundError:
                        pass
                    except Exception as ex_pulizia:
                        scrivi_log("strumenti_youtube.aggiorna_deno pulizia", ex_pulizia)
    except Exception as ex:
        scrivi_log("strumenti_youtube.aggiorna_deno", ex)
        return ""


def aggiorna_tutto(forza=False):
    try:
        with _blocco:
            ytdlp = aggiorna_ytdlp(forza)
            deno = aggiorna_deno(forza)
        return ytdlp, deno
    except Exception as ex:
        scrivi_log("strumenti_youtube.aggiorna_tutto", ex)
        return "", ""


def _lavoro_in_secondo_piano():
    try:
        aggiorna_tutto(False)
    except Exception as ex:
        scrivi_log("strumenti_youtube._lavoro_in_secondo_piano", ex)


def avvia_manutenzione():
    global _manutenzione_avviata
    try:
        with _blocco:
            if _manutenzione_avviata:
                return False
            _manutenzione_avviata = True
        threading.Thread(target=_lavoro_in_secondo_piano, name="strumenti-youtube", daemon=True).start()
        return True
    except Exception as ex:
        scrivi_log("strumenti_youtube.avvia_manutenzione", ex)
        return False


def esegui():
    try:
        prepara_ambiente()
        ytdlp, deno = aggiorna_tutto(True)
        print(f"yt-dlp: {ytdlp}" if ytdlp else "yt-dlp: non installato, vedere ~/logs/linux-easy.log")
        if deno == "sistema":
            print("deno: già presente nel sistema")
        else:
            print(f"deno: {deno}" if deno else "deno: non installato, vedere ~/logs/linux-easy.log")
    except Exception as ex:
        scrivi_log("strumenti_youtube.esegui", ex)
    return 0


if __name__ == "__main__":
    sys.exit(esegui())
