import sys
from pathlib import Path

NOME_PROGRAMMA = "LinuxEasy"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) LinuxEasy/1.0"


def cartella_profilo():
    try:
        return Path.home()
    except Exception as ex:
        try:
            sys.stderr.write(f"Cartella utente non determinabile: {ex}\n")
        except Exception:
            pass
        return Path("/tmp")


def cartella_log():
    return cartella_profilo() / "logs"


def file_log():
    return cartella_log() / "linux-easy.log"


def cartella_dati():
    return cartella_profilo() / "dati"


def cartella_podcast():
    return cartella_dati() / "podcast"


def cartella_config_vecchia():
    return cartella_profilo() / ".config" / "lettore-accessibile"
