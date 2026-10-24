import importlib.util
from pathlib import Path

from app.core.log import scrivi_log

LARGHEZZA_MINIMA = 1800
LARGHEZZA_MASSIMA_ANALISI = 700
ANGOLO_MASSIMO = 8.0
ANGOLO_MINIMO = 0.15
PASSO_GROSSOLANO = 0.5
PASSO_FINE = 0.1
PIXEL_MINIMI_INCHIOSTRO = 500
SOGLIA_RUMORE = 5.0
LATO_MASSIMO_RUMORE = 2600
LATO_MASSIMO_IMMAGINE = 4200


def opencv_disponibile():
    try:
        return importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None
    except Exception as ex:
        scrivi_log("preparazione.opencv_disponibile", ex)
        return False


def _normalizza_sfondo(cv2, grigio):
    try:
        altezza, larghezza = grigio.shape[:2]
        piccola = cv2.resize(grigio, (max(1, larghezza // 4), max(1, altezza // 4)), interpolation=cv2.INTER_AREA)
        nucleo = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        dilatata = cv2.dilate(piccola, nucleo)
        sfondo = cv2.medianBlur(dilatata, 21)
        sfondo = cv2.resize(sfondo, (larghezza, altezza), interpolation=cv2.INTER_LINEAR)
        sfondo = cv2.max(sfondo, 1)
        return cv2.divide(grigio, sfondo, scale=255)
    except Exception as ex:
        scrivi_log("preparazione._normalizza_sfondo", ex)
        return grigio


def _stima_rumore(cv2, np, grigio):
    try:
        altezza, larghezza = grigio.shape[:2]
        passo = max(1, max(altezza, larghezza) // 1200)
        campione = grigio[::passo, ::passo]
        laplaciano = cv2.Laplacian(campione, cv2.CV_64F)
        return float(np.median(np.abs(laplaciano)) / 0.6745)
    except Exception as ex:
        scrivi_log("preparazione._stima_rumore", ex)
        return 0.0


def _riduci_rumore(cv2, np, grigio):
    try:
        if max(grigio.shape[:2]) > LATO_MASSIMO_RUMORE:
            return grigio
        if _stima_rumore(cv2, np, grigio) < SOGLIA_RUMORE:
            return grigio
        return cv2.fastNlMeansDenoising(grigio, None, 10, 7, 21)
    except Exception as ex:
        scrivi_log("preparazione._riduci_rumore", ex)
        return grigio


def _punteggio_angolo(cv2, np, binaria, angolo):
    try:
        altezza, larghezza = binaria.shape[:2]
        matrice = cv2.getRotationMatrix2D((larghezza / 2, altezza / 2), angolo, 1.0)
        ruotata = cv2.warpAffine(binaria, matrice, (larghezza, altezza), flags=cv2.INTER_NEAREST, borderValue=0)
        proiezione = ruotata.sum(axis=1, dtype=np.float64)
        return float(np.var(proiezione))
    except Exception as ex:
        scrivi_log(f"preparazione._punteggio_angolo ({angolo})", ex)
        return -1.0


def _stima_inclinazione(cv2, np, grigio):
    try:
        altezza, larghezza = grigio.shape[:2]
        fattore = LARGHEZZA_MASSIMA_ANALISI / float(larghezza)
        if fattore >= 1.0:
            fattore = 1.0
        piccola = cv2.resize(
            grigio,
            (max(1, int(larghezza * fattore)), max(1, int(altezza * fattore))),
            interpolation=cv2.INTER_AREA,
        )
        _soglia, binaria = cv2.threshold(piccola, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        if int(np.count_nonzero(binaria)) < PIXEL_MINIMI_INCHIOSTRO:
            return 0.0
        migliore = 0.0
        punteggio_migliore = _punteggio_angolo(cv2, np, binaria, 0.0)
        angolo = -ANGOLO_MASSIMO
        while angolo <= ANGOLO_MASSIMO + 1e-9:
            punteggio = _punteggio_angolo(cv2, np, binaria, angolo)
            if punteggio > punteggio_migliore:
                punteggio_migliore = punteggio
                migliore = angolo
            angolo += PASSO_GROSSOLANO
        centro = migliore
        angolo = centro - PASSO_GROSSOLANO
        while angolo <= centro + PASSO_GROSSOLANO + 1e-9:
            punteggio = _punteggio_angolo(cv2, np, binaria, angolo)
            if punteggio > punteggio_migliore:
                punteggio_migliore = punteggio
                migliore = angolo
            angolo += PASSO_FINE
        return float(migliore)
    except Exception as ex:
        scrivi_log("preparazione._stima_inclinazione", ex)
        return 0.0


def _raddrizza(cv2, grigio, angolo):
    try:
        if abs(angolo) < ANGOLO_MINIMO:
            return grigio
        altezza, larghezza = grigio.shape[:2]
        matrice = cv2.getRotationMatrix2D((larghezza / 2, altezza / 2), angolo, 1.0)
        return cv2.warpAffine(grigio, matrice, (larghezza, altezza), flags=cv2.INTER_CUBIC, borderValue=255)
    except Exception as ex:
        scrivi_log(f"preparazione._raddrizza ({angolo})", ex)
        return grigio


def migliora_immagine(percorso_ingresso, percorso_uscita):
    try:
        if not opencv_disponibile():
            return False
        import cv2
        import numpy as np

        immagine = cv2.imread(str(percorso_ingresso), cv2.IMREAD_COLOR)
        if immagine is None or immagine.size == 0:
            return False
        grigio = cv2.cvtColor(immagine, cv2.COLOR_BGR2GRAY)
        del immagine
        altezza, larghezza = grigio.shape[:2]
        if larghezza < LARGHEZZA_MINIMA:
            fattore = min(3.0, LARGHEZZA_MINIMA / float(larghezza))
            grigio = cv2.resize(
                grigio,
                (int(larghezza * fattore), int(altezza * fattore)),
                interpolation=cv2.INTER_CUBIC,
            )
        lato_massimo = max(grigio.shape[:2])
        if lato_massimo > LATO_MASSIMO_IMMAGINE:
            fattore = LATO_MASSIMO_IMMAGINE / float(lato_massimo)
            grigio = cv2.resize(
                grigio,
                (max(1, int(grigio.shape[1] * fattore)), max(1, int(grigio.shape[0] * fattore))),
                interpolation=cv2.INTER_AREA,
            )
        grigio = _normalizza_sfondo(cv2, grigio)
        grigio = _riduci_rumore(cv2, np, grigio)
        angolo = _stima_inclinazione(cv2, np, grigio)
        grigio = _raddrizza(cv2, grigio, angolo)
        Path(percorso_uscita).parent.mkdir(parents=True, exist_ok=True)
        return bool(cv2.imwrite(str(percorso_uscita), grigio))
    except Exception as ex:
        scrivi_log(f"preparazione.migliora_immagine ({percorso_ingresso})", ex)
        return False
