import logging
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler

from app.core import percorsi

_logger = None
_blocco = threading.Lock()


def _ottieni_logger():
    global _logger
    if _logger is not None:
        return _logger
    with _blocco:
        if _logger is None:
            registratore = logging.getLogger("linuxeasy")
            registratore.setLevel(logging.ERROR)
            registratore.propagate = False
            try:
                percorsi.cartella_log().mkdir(parents=True, exist_ok=True)
                gestore = RotatingFileHandler(
                    str(percorsi.file_log()),
                    maxBytes=2_000_000,
                    backupCount=3,
                    encoding="utf-8",
                )
            except Exception as ex:
                try:
                    sys.stderr.write(f"Log su file non disponibile: {ex}\n")
                except Exception:
                    pass
                gestore = logging.StreamHandler(sys.stderr)
            gestore.setFormatter(logging.Formatter("%(asctime)s | %(threadName)s | %(message)s"))
            registratore.addHandler(gestore)
            _logger = registratore
    return _logger


def scrivi_log(contesto, eccezione=None):
    try:
        testo = str(contesto)
        if eccezione is not None:
            dettaglio = "".join(
                traceback.format_exception(type(eccezione), eccezione, eccezione.__traceback__)
            )
            testo = f"{contesto} | {type(eccezione).__name__}: {eccezione}\n{dettaglio}"
        _ottieni_logger().error(testo)
    except Exception as ex:
        try:
            sys.stderr.write(f"Errore nella scrittura del log: {ex} | {contesto}\n")
        except Exception:
            pass


def _eccezione_non_gestita(tipo, valore, traccia):
    try:
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, valore, traccia)
            return
        dettaglio = "".join(traceback.format_exception(tipo, valore, traccia))
        _ottieni_logger().error(f"Eccezione non gestita | {tipo.__name__}: {valore}\n{dettaglio}")
    except Exception as ex:
        try:
            sys.stderr.write(f"Errore nel gestore globale: {ex}\n")
        except Exception:
            pass


def _eccezione_thread(argomenti):
    try:
        dettaglio = "".join(
            traceback.format_exception(argomenti.exc_type, argomenti.exc_value, argomenti.exc_traceback)
        )
        nome = argomenti.thread.name if argomenti.thread is not None else "sconosciuto"
        _ottieni_logger().error(f"Eccezione non gestita nel thread {nome} | {argomenti.exc_value}\n{dettaglio}")
    except Exception as ex:
        try:
            sys.stderr.write(f"Errore nel gestore dei thread: {ex}\n")
        except Exception:
            pass


def installa_gestori_globali():
    try:
        sys.excepthook = _eccezione_non_gestita
        threading.excepthook = _eccezione_thread
    except Exception as ex:
        scrivi_log("log.installa_gestori_globali", ex)
