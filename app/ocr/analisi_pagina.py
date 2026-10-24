import contextlib
import gc
import importlib.util
import os
import sys
from dataclasses import dataclass

from app.core.log import scrivi_log

MODELLO_LAYOUT = "pp_layout_cdla"
SOGLIA_CONFIDENZA_LAYOUT = 0.45
SOGLIA_SOVRAPPOSIZIONE = 0.7
SOGLIA_DENTRO_IMMAGINE = 0.5
SOGLIA_ASSEGNAZIONE_RIGA = 0.3
LATO_MINIMO_ZONA = 12
MEMORIA_MINIMA_MB = 700
INCHIOSTRO_MINIMO_RECUPERO = 60
LATO_MINIMO_RECUPERO = 18
ETICHETTE_IMMAGINE = ("figure",)
ETICHETTE_TABELLA = ("table",)
ETICHETTE_TITOLO = ("title",)
TIPO_TESTO = "testo"
TIPO_TITOLO = "titolo"
TIPO_IMMAGINE = "immagine"
TIPO_TABELLA = "tabella"


@dataclass
class Zona:
    x0: int
    y0: int
    x1: int
    y1: int
    tipo: str
    etichetta: str = ""
    punteggio: float = 0.0
    recuperata: bool = False

    def larghezza(self):
        return max(0, self.x1 - self.x0)

    def altezza(self):
        return max(0, self.y1 - self.y0)

    def area(self):
        return self.larghezza() * self.altezza()


@contextlib.contextmanager
def errori_silenziosi():
    salvato = None
    nullo = None
    try:
        try:
            sys.stderr.flush()
        except Exception as ex:
            scrivi_log("analisi_pagina.errori_silenziosi flush", ex)
        salvato = os.dup(2)
        nullo = os.open(os.devnull, os.O_WRONLY)
        os.dup2(nullo, 2)
    except Exception as ex:
        scrivi_log("analisi_pagina.errori_silenziosi avvio", ex)
    try:
        yield
    finally:
        try:
            if salvato is not None:
                os.dup2(salvato, 2)
        except Exception as ex:
            scrivi_log("analisi_pagina.errori_silenziosi ripristino", ex)
        for descrittore in (nullo, salvato):
            try:
                if descrittore is not None:
                    os.close(descrittore)
            except Exception as ex:
                scrivi_log("analisi_pagina.errori_silenziosi chiusura", ex)


def memoria_disponibile_mb():
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as file:
            for riga in file:
                if riga.startswith("MemAvailable:"):
                    return int(riga.split()[1]) // 1024
        return None
    except FileNotFoundError:
        return None
    except Exception as ex:
        scrivi_log("analisi_pagina.memoria_disponibile_mb", ex)
        return None


def _area_intersezione(a, b):
    try:
        larghezza = min(a.x1, b.x1) - max(a.x0, b.x0)
        altezza = min(a.y1, b.y1) - max(a.y0, b.y0)
        if larghezza <= 0 or altezza <= 0:
            return 0
        return larghezza * altezza
    except Exception as ex:
        scrivi_log("analisi_pagina._area_intersezione", ex)
        return 0


def _frazione_dentro(zona, contenitore):
    try:
        area = zona.area()
        if area <= 0:
            return 0.0
        return _area_intersezione(zona, contenitore) / float(area)
    except Exception as ex:
        scrivi_log("analisi_pagina._frazione_dentro", ex)
        return 0.0


def _sovrapposizione(a, b):
    try:
        comune = _area_intersezione(a, b)
        if comune <= 0:
            return 0.0
        return comune / float(min(a.area(), b.area()) or 1)
    except Exception as ex:
        scrivi_log("analisi_pagina._sovrapposizione", ex)
        return 0.0


def _gruppi(zone, inizio, fine, distanza_minima):
    try:
        ordinate = sorted(zone, key=lambda z: (inizio(z), fine(z)))
        gruppi = []
        corrente = []
        limite = None
        distanza_massima = 0
        for zona in ordinate:
            if corrente and inizio(zona) - limite > distanza_minima:
                distanza_massima = max(distanza_massima, inizio(zona) - limite)
                gruppi.append(corrente)
                corrente = []
                limite = None
            corrente.append(zona)
            limite = fine(zona) if limite is None else max(limite, fine(zona))
        if corrente:
            gruppi.append(corrente)
        return gruppi, distanza_massima
    except Exception as ex:
        scrivi_log("analisi_pagina._gruppi", ex)
        return [list(zone)], 0


def _intervallo(gruppo):
    return min(z.x0 for z in gruppo), max(z.x1 for z in gruppo)


def _intervalli_sovrapposti(primo, secondo):
    try:
        comune = min(primo[1], secondo[1]) - max(primo[0], secondo[0])
        minimo = min(primo[1] - primo[0], secondo[1] - secondo[0])
        return comune > 0 and comune >= minimo * 0.5
    except Exception as ex:
        scrivi_log("analisi_pagina._intervalli_sovrapposti", ex)
        return False


def _colonne(gruppo, distanza):
    colonne, _massima = _gruppi(gruppo, lambda z: z.x0, lambda z: z.x1, distanza)
    return colonne


def _ordina_fasce(fasce, larghezza_pagina):
    risultato = []
    try:
        distanza = max(4, int(larghezza_pagina * 0.02))
        indice = 0
        while indice < len(fasce):
            colonne = _colonne(fasce[indice], distanza)
            successivo = indice + 1
            if len(colonne) >= 2:
                fuse = [list(colonna) for colonna in colonne]
                while successivo < len(fasce):
                    prossime = _colonne(fasce[successivo], distanza)
                    if len(prossime) != len(fuse):
                        break
                    if not all(
                        _intervalli_sovrapposti(_intervallo(a), _intervallo(b)) for a, b in zip(fuse, prossime)
                    ):
                        break
                    for a, b in zip(fuse, prossime):
                        a.extend(b)
                    successivo += 1
                if successivo > indice + 1:
                    for colonna in fuse:
                        risultato.extend(ordine_di_lettura(colonna, larghezza_pagina))
                    indice = successivo
                    continue
            risultato.extend(ordine_di_lettura(fasce[indice], larghezza_pagina))
            indice += 1
    except Exception as ex:
        scrivi_log("analisi_pagina._ordina_fasce", ex)
        return [zona for fascia in fasce for zona in sorted(fascia, key=lambda z: (z.y0, z.x0))]
    return risultato


def ordine_di_lettura(zone, larghezza_pagina):
    try:
        if len(zone) <= 1:
            return list(zone)
        verticali, distanza_y = _gruppi(zone, lambda z: z.y0, lambda z: z.y1, 0)
        distanza = max(4, int(larghezza_pagina * 0.02))
        orizzontali, distanza_x = _gruppi(zone, lambda z: z.x0, lambda z: z.x1, distanza)
        if len(orizzontali) > 1 and (len(verticali) <= 1 or distanza_x >= distanza_y):
            risultato = []
            for gruppo in orizzontali:
                risultato.extend(ordine_di_lettura(gruppo, larghezza_pagina))
            return risultato
        if len(verticali) > 1:
            return _ordina_fasce(verticali, larghezza_pagina)
        return sorted(zone, key=lambda z: (z.y0, z.x0))
    except Exception as ex:
        scrivi_log("analisi_pagina.ordine_di_lettura", ex)
        return sorted(zone, key=lambda z: (z.y0, z.x0))


class AnalizzatoreLayout:
    def __init__(self):
        self._motore = None
        self._motivo = ""

    @property
    def motivo(self):
        return self._motivo

    def disponibile(self):
        try:
            if importlib.util.find_spec("rapid_layout") is None:
                self._motivo = "il modulo rapid-layout non è installato"
                return False
            if importlib.util.find_spec("onnxruntime") is None:
                self._motivo = "il modulo onnxruntime non è installato"
                return False
            if importlib.util.find_spec("cv2") is None or importlib.util.find_spec("numpy") is None:
                self._motivo = "mancano OpenCV o NumPy"
                return False
            memoria = memoria_disponibile_mb()
            if memoria is not None and memoria < MEMORIA_MINIMA_MB:
                self._motivo = f"memoria libera insufficiente ({memoria} MB)"
                return False
            self._motivo = ""
            return True
        except Exception as ex:
            scrivi_log("AnalizzatoreLayout.disponibile", ex)
            self._motivo = "controllo non riuscito"
            return False

    def carica(self):
        try:
            if self._motore is not None:
                return True
            with errori_silenziosi():
                from rapid_layout import RapidLayout

                self._motore = RapidLayout(
                    model_type=MODELLO_LAYOUT,
                    conf_thresh=SOGLIA_CONFIDENZA_LAYOUT,
                    iou_thresh=0.5,
                )
            return True
        except Exception as ex:
            scrivi_log("AnalizzatoreLayout.carica", ex)
            self._motore = None
            self._motivo = "il modello di analisi non si è avviato"
            return False

    def rilascia(self):
        try:
            self._motore = None
            gc.collect()
        except Exception as ex:
            scrivi_log("AnalizzatoreLayout.rilascia", ex)

    def analizza(self, percorso_immagine):
        try:
            if self._motore is None and not self.carica():
                return None
            import cv2

            immagine = cv2.imread(str(percorso_immagine), cv2.IMREAD_GRAYSCALE)
            if immagine is None:
                self._motivo = "immagine non leggibile"
                return None
            altezza, larghezza = immagine.shape[:2]
            colori = cv2.cvtColor(immagine, cv2.COLOR_GRAY2BGR)
            with errori_silenziosi():
                risultato = self._motore(colori)
            del colori
            zone = self._zone_da_risultato(risultato, larghezza, altezza)
            zone = self._elimina_testo_nelle_immagini(zone)
            zone = self._elimina_doppioni(zone)
            zone = self._affina_zone(cv2, immagine, zone)
            zone.extend(self._recupera_testo_mancante(cv2, immagine, zone))
            return ordine_di_lettura(zone, larghezza)
        except Exception as ex:
            scrivi_log(f"AnalizzatoreLayout.analizza ({percorso_immagine})", ex)
            self._motivo = "l'analisi della pagina non è riuscita"
            return None

    def _tipo(self, etichetta):
        if etichetta in ETICHETTE_IMMAGINE:
            return TIPO_IMMAGINE
        if etichetta in ETICHETTE_TABELLA:
            return TIPO_TABELLA
        if etichetta in ETICHETTE_TITOLO:
            return TIPO_TITOLO
        return TIPO_TESTO

    def _zone_da_risultato(self, risultato, larghezza, altezza):
        zone = []
        try:
            riquadri = getattr(risultato, "boxes", None)
            etichette = getattr(risultato, "class_names", None)
            punteggi = getattr(risultato, "scores", None)
            if riquadri is None or etichette is None:
                return zone
            for indice, riquadro in enumerate(riquadri):
                try:
                    x0 = max(0, int(round(float(riquadro[0]))))
                    y0 = max(0, int(round(float(riquadro[1]))))
                    x1 = min(larghezza, int(round(float(riquadro[2]))))
                    y1 = min(altezza, int(round(float(riquadro[3]))))
                    if x1 - x0 < LATO_MINIMO_ZONA or y1 - y0 < LATO_MINIMO_ZONA:
                        continue
                    etichetta = str(etichette[indice])
                    punteggio = float(punteggi[indice]) if punteggi is not None else 0.0
                    zone.append(Zona(x0, y0, x1, y1, self._tipo(etichetta), etichetta, punteggio))
                except Exception as ex:
                    scrivi_log(f"AnalizzatoreLayout._zone_da_risultato ({indice})", ex)
        except Exception as ex:
            scrivi_log("AnalizzatoreLayout._zone_da_risultato", ex)
        return zone

    def _elimina_testo_nelle_immagini(self, zone):
        try:
            immagini = [zona for zona in zone if zona.tipo == TIPO_IMMAGINE]
            if not immagini:
                return zone
            risultato = []
            for zona in zone:
                if zona.tipo == TIPO_IMMAGINE:
                    risultato.append(zona)
                    continue
                if any(_frazione_dentro(zona, immagine) >= SOGLIA_DENTRO_IMMAGINE for immagine in immagini):
                    continue
                risultato.append(zona)
            return risultato
        except Exception as ex:
            scrivi_log("AnalizzatoreLayout._elimina_testo_nelle_immagini", ex)
            return zone

    def _elimina_doppioni(self, zone):
        try:
            ordinate = sorted(zone, key=lambda z: z.punteggio, reverse=True)
            tenute = []
            for zona in ordinate:
                doppione = False
                for altra in tenute:
                    if (zona.tipo == TIPO_IMMAGINE) != (altra.tipo == TIPO_IMMAGINE):
                        continue
                    if _sovrapposizione(zona, altra) >= SOGLIA_SOVRAPPOSIZIONE:
                        doppione = True
                        break
                if not doppione:
                    tenute.append(zona)
            return tenute
        except Exception as ex:
            scrivi_log("AnalizzatoreLayout._elimina_doppioni", ex)
            return zone

    def _affina_zone(self, cv2, immagine, zone):
        try:
            import numpy as np

            testuali = [zona for zona in zone if zona.tipo != TIPO_IMMAGINE]
            if not testuali:
                return zone
            altezza, larghezza = immagine.shape[:2]
            _soglia, inchiostro = cv2.threshold(immagine, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            for zona in zone:
                if zona.tipo == TIPO_IMMAGINE:
                    inchiostro[zona.y0:zona.y1, zona.x0:zona.x1] = 0
            lato_x = max(25, larghezza // 80)
            nucleo = cv2.getStructuringElement(cv2.MORPH_RECT, (lato_x, 3))
            unito = cv2.dilate(inchiostro, nucleo)
            totale, _etichette, statistiche, _centri = cv2.connectedComponentsWithStats(unito, connectivity=8)
            assegnate = {id(zona): [] for zona in testuali}
            non_assegnate = []
            for indice in range(1, totale):
                x, y, w, h, _area = (int(valore) for valore in statistiche[indice])
                area_riga = float(max(1, w * h))
                migliore = None
                frazione_migliore = SOGLIA_ASSEGNAZIONE_RIGA
                for zona in testuali:
                    larghezza_comune = min(x + w, zona.x1) - max(x, zona.x0)
                    altezza_comune = min(y + h, zona.y1) - max(y, zona.y0)
                    if larghezza_comune <= 0 or altezza_comune <= 0:
                        continue
                    frazione = larghezza_comune * altezza_comune / area_riga
                    if frazione > frazione_migliore:
                        frazione_migliore = frazione
                        migliore = zona
                if migliore is not None:
                    assegnate[id(migliore)].append((x, y, x + w, y + h))
                else:
                    non_assegnate.append((x, y, x + w, y + h))
            for zona in testuali:
                righe = assegnate[id(zona)]
                if not righe:
                    continue
                x0 = max(0, min(riga[0] for riga in righe))
                y0 = max(0, min(riga[1] for riga in righe))
                x1 = min(larghezza, max(riga[2] for riga in righe))
                y1 = min(altezza, max(riga[3] for riga in righe))
                parte = inchiostro[y0:y1, x0:x1]
                punti = cv2.findNonZero(parte)
                if punti is None:
                    continue
                bx, by, bw, bh = cv2.boundingRect(punti)
                if bw < LATO_MINIMO_ZONA or bh < LATO_MINIMO_ZONA:
                    continue
                zona.x0 = x0 + bx
                zona.y0 = y0 + by
                zona.x1 = x0 + bx + bw
                zona.y1 = y0 + by + bh
            for x0, y0, x1, y1 in non_assegnate:
                self._attacca_a_zona_vicina(testuali, x0, y0, x1, y1)
            return zone
        except Exception as ex:
            scrivi_log("AnalizzatoreLayout._affina_zone", ex)
            return zone

    def _attacca_a_zona_vicina(self, zone, x0, y0, x1, y1):
        try:
            altezza = y1 - y0
            migliore = None
            distanza_migliore = max(60, int(altezza * 2.5)) + 1
            for zona in zone:
                comune = min(y1, zona.y1) - max(y0, zona.y0)
                if comune < altezza * 0.6:
                    continue
                if x1 <= zona.x0:
                    distanza = zona.x0 - x1
                elif x0 >= zona.x1:
                    distanza = x0 - zona.x1
                else:
                    distanza = 0
                if distanza < distanza_migliore:
                    distanza_migliore = distanza
                    migliore = zona
            if migliore is None:
                return False
            migliore.x0 = min(migliore.x0, x0)
            migliore.x1 = max(migliore.x1, x1)
            migliore.y0 = min(migliore.y0, y0)
            migliore.y1 = max(migliore.y1, y1)
            return True
        except Exception as ex:
            scrivi_log("AnalizzatoreLayout._attacca_a_zona_vicina", ex)
            return False

    def _recupera_testo_mancante(self, cv2, immagine, zone):
        recuperate = []
        try:
            import numpy as np

            altezza, larghezza = immagine.shape[:2]
            _soglia, inchiostro = cv2.threshold(immagine, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            for zona in zone:
                inchiostro[zona.y0:zona.y1, zona.x0:zona.x1] = 0
            lato_x = max(15, larghezza // 60)
            lato_y = max(5, larghezza // 200)
            nucleo = cv2.getStructuringElement(cv2.MORPH_RECT, (lato_x, lato_y))
            unito = cv2.dilate(inchiostro, nucleo)
            contorni, _gerarchia = cv2.findContours(unito, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contorno in contorni:
                x, y, w, h = cv2.boundingRect(contorno)
                if w < LATO_MINIMO_RECUPERO * 2 or h < LATO_MINIMO_RECUPERO:
                    continue
                pixel = int(np.count_nonzero(inchiostro[y:y + h, x:x + w]))
                if pixel < INCHIOSTRO_MINIMO_RECUPERO:
                    continue
                recuperate.append(
                    Zona(
                        max(0, x),
                        max(0, y),
                        min(larghezza, x + w),
                        min(altezza, y + h),
                        TIPO_TESTO,
                        "recupero",
                        0.0,
                        True,
                    )
                )
        except Exception as ex:
            scrivi_log("AnalizzatoreLayout._recupera_testo_mancante", ex)
        return recuperate
