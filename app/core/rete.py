import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from app.core import percorsi
from app.core.log import scrivi_log

DIMENSIONE_BLOCCO = 65536


class ErroreRete(Exception):
    pass


class DownloadAnnullato(Exception):
    pass


def componi_url(url, parametri=None):
    try:
        if not parametri:
            return url
        separatore = "&" if "?" in url else "?"
        return url + separatore + urllib.parse.urlencode(parametri)
    except Exception as ex:
        scrivi_log(f"rete.componi_url ({url})", ex)
        return url


def _apri(url, parametri, timeout):
    richiesta = urllib.request.Request(
        componi_url(url, parametri),
        headers={"User-Agent": percorsi.USER_AGENT, "Accept": "*/*"},
    )
    return urllib.request.urlopen(richiesta, timeout=timeout)


def leggi_bytes(url, parametri=None, timeout=20):
    try:
        with _apri(url, parametri, timeout) as risposta:
            return risposta.read()
    except Exception as ex:
        scrivi_log(f"rete.leggi_bytes ({componi_url(url, parametri)})", ex)
        raise ErroreRete(str(ex)) from ex


def leggi_json(url, parametri=None, timeout=20):
    dati = leggi_bytes(url, parametri, timeout)
    try:
        return json.loads(dati.decode("utf-8", errors="replace"))
    except Exception as ex:
        scrivi_log(f"rete.leggi_json: risposta non valida da {componi_url(url, parametri)}", ex)
        raise ErroreRete(str(ex)) from ex


def scarica_file(url, destinazione, avanzamento=None, annulla=None, timeout=30):
    destinazione = Path(destinazione)
    temporaneo = destinazione.with_name(destinazione.name + ".part")
    completato = False
    try:
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        letti = 0
        with _apri(url, None, timeout) as risposta:
            try:
                totale = int(risposta.headers.get("Content-Length") or 0)
            except Exception as ex:
                scrivi_log(f"rete.scarica_file: dimensione non leggibile ({url})", ex)
                totale = 0
            with open(temporaneo, "wb") as file_destinazione:
                while True:
                    if annulla is not None and annulla.is_set():
                        raise DownloadAnnullato(url)
                    blocco = risposta.read(DIMENSIONE_BLOCCO)
                    if not blocco:
                        break
                    file_destinazione.write(blocco)
                    letti += len(blocco)
                    if avanzamento is not None:
                        try:
                            avanzamento(letti, totale)
                        except Exception as ex:
                            scrivi_log("rete.scarica_file avanzamento", ex)
        if letti == 0:
            raise ErroreRete(f"Nessun dato ricevuto da {url}")
        os.replace(temporaneo, destinazione)
        completato = True
        return letti
    except DownloadAnnullato:
        raise
    except ErroreRete as ex:
        scrivi_log(f"rete.scarica_file ({url})", ex)
        raise
    except Exception as ex:
        scrivi_log(f"rete.scarica_file ({url})", ex)
        raise ErroreRete(str(ex)) from ex
    finally:
        if not completato:
            try:
                if temporaneo.exists():
                    temporaneo.unlink()
            except Exception as ex:
                scrivi_log(f"rete.scarica_file pulizia ({temporaneo})", ex)
