import logging
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler

from app.core import percorsi

_logger = None
_blocco = threading.Lock()
_gestori_installati = False
_contatori = threading.local()


def errori_thread():
    try:
        return int(getattr(_contatori, "errori", 0))
    except Exception as ex:
        _scrivi_stderr(f"Errore nella lettura del contatore degli errori: {ex}")
        return 0


def _conta_errore():
    try:
        _contatori.errori = int(getattr(_contatori, "errori", 0)) + 1
    except Exception as ex:
        _scrivi_stderr(f"Errore nell'aggiornamento del contatore degli errori: {ex}")


def _scrivi_stderr(testo):
    try:
        sys.stderr.write(f"{testo}\n")
    except Exception:
        pass


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
                _scrivi_stderr(f"Log su file non disponibile: {ex}")
                gestore = logging.StreamHandler(sys.stderr)
            gestore.setFormatter(logging.Formatter("%(asctime)s | %(threadName)s | %(message)s"))
            registratore.addHandler(gestore)
            _logger = registratore
    return _logger


def _formatta(tipo, valore, traccia):
    try:
        return "".join(traceback.format_exception(tipo, valore, traccia))
    except Exception as ex:
        return f"Traccia non disponibile: {ex}"


def scrivi_log(contesto, eccezione=None, conta=True):
    try:
        if conta:
            _conta_errore()
        testo = str(contesto)
        if eccezione is not None:
            dettaglio = _formatta(type(eccezione), eccezione, eccezione.__traceback__)
            testo = f"{contesto} | {type(eccezione).__name__}: {eccezione}\n{dettaglio}"
        _ottieni_logger().error(testo)
    except Exception as ex:
        _scrivi_stderr(f"Errore nella scrittura del log: {ex} | {contesto}")


def _eccezione_non_gestita(tipo, valore, traccia):
    try:
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, valore, traccia)
            return
        dettaglio = _formatta(tipo, valore, traccia)
        _ottieni_logger().error(f"Eccezione non gestita | {tipo.__name__}: {valore}\n{dettaglio}")
        _scrivi_stderr(dettaglio)
    except Exception as ex:
        _scrivi_stderr(f"Errore nel gestore globale: {ex}")


def _eccezione_thread(argomenti):
    try:
        if argomenti.exc_type is SystemExit:
            return
        dettaglio = _formatta(argomenti.exc_type, argomenti.exc_value, argomenti.exc_traceback)
        nome = argomenti.thread.name if argomenti.thread is not None else "sconosciuto"
        tipo = argomenti.exc_type.__name__ if argomenti.exc_type is not None else "Eccezione"
        _ottieni_logger().error(f"Eccezione non gestita nel thread {nome} | {tipo}: {argomenti.exc_value}\n{dettaglio}")
    except Exception as ex:
        _scrivi_stderr(f"Errore nel gestore dei thread: {ex}")


def _eccezione_non_sollevabile(argomenti):
    try:
        tipo = argomenti.exc_type
        dettaglio = _formatta(tipo, argomenti.exc_value, argomenti.exc_traceback)
        messaggio = argomenti.err_msg or "Eccezione ignorata"
        oggetto = repr(argomenti.object) if argomenti.object is not None else ""
        nome = tipo.__name__ if tipo is not None else "Eccezione"
        _ottieni_logger().error(f"{messaggio} {oggetto} | {nome}: {argomenti.exc_value}\n{dettaglio}")
    except Exception as ex:
        _scrivi_stderr(f"Errore nel gestore delle eccezioni ignorate: {ex}")


def installa_gestori_globali():
    global _gestori_installati
    try:
        if _gestori_installati:
            return
        sys.excepthook = _eccezione_non_gestita
        threading.excepthook = _eccezione_thread
        sys.unraisablehook = _eccezione_non_sollevabile
        _gestori_installati = True
    except Exception as ex:
        scrivi_log("log.installa_gestori_globali", ex)
