import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Set

from app.core.log import scrivi_log

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]
FREQUENZA_NESSUNA = "nessuna"
FREQUENZA_GIORNALIERA = "giornaliera"
FREQUENZA_SETTIMANALE = "settimanale"
FREQUENZA_MENSILE = "mensile"
FREQUENZA_ANNUALE = "annuale"
FREQUENZE = (FREQUENZA_NESSUNA, FREQUENZA_GIORNALIERA, FREQUENZA_SETTIMANALE, FREQUENZA_MENSILE, FREQUENZA_ANNUALE)
FINE_MAI = "mai"
FINE_DATA = "data"
FINE_VOLTE = "volte"
NESSUNA_NOTIFICA = -1
MASSIMO_CICLI = 200000


@dataclass
class Evento:
    id: int = 0
    titolo: str = ""
    luogo: str = ""
    note: str = ""
    inizio: datetime = field(default_factory=lambda: datetime.now().replace(second=0, microsecond=0))
    fine: datetime = field(default_factory=lambda: datetime.now().replace(second=0, microsecond=0) + timedelta(hours=1))
    tutto_il_giorno: bool = False
    frequenza: str = FREQUENZA_NESSUNA
    intervallo: int = 1
    giorni_settimana: List[int] = field(default_factory=list)
    fine_ripetizione: str = FINE_MAI
    ripeti_fino: Optional[date] = None
    ripeti_volte: int = 0
    avviso_minuti: int = 15
    esclusioni: Set[date] = field(default_factory=set)

    @property
    def durata(self):
        try:
            return max(timedelta(0), self.fine - self.inizio)
        except Exception as ex:
            scrivi_log("Evento.durata", ex)
            return timedelta(0)

    @property
    def ricorrente(self):
        return self.frequenza in FREQUENZE and self.frequenza != FREQUENZA_NESSUNA

    @property
    def ultimo_giorno(self):
        try:
            if self.tutto_il_giorno:
                return (self.fine - timedelta(days=1)).date()
            if self.fine.time() == time(0, 0) and self.fine.date() > self.inizio.date():
                return (self.fine - timedelta(minutes=1)).date()
            return self.fine.date()
        except Exception as ex:
            scrivi_log("Evento.ultimo_giorno", ex)
            return self.inizio.date()


@dataclass
class Occorrenza:
    evento: Evento
    inizio: datetime
    fine: datetime

    @property
    def ultimo_giorno(self):
        try:
            if self.evento.tutto_il_giorno:
                return (self.fine - timedelta(days=1)).date()
            if self.fine.time() == time(0, 0) and self.fine.date() > self.inizio.date():
                return (self.fine - timedelta(minutes=1)).date()
            return self.fine.date()
        except Exception as ex:
            scrivi_log("Occorrenza.ultimo_giorno", ex)
            return self.inizio.date()

    @property
    def piu_giorni(self):
        return self.ultimo_giorno > self.inizio.date()


def _aggiungi_mesi(anno, mese, quanti):
    try:
        totale = anno * 12 + (mese - 1) + quanti
        return totale // 12, totale % 12 + 1
    except Exception as ex:
        scrivi_log("agenda_model._aggiungi_mesi", ex)
        return anno, mese


def _inizi(evento, dal_giorno=None):
    try:
        base = evento.inizio
        passo = max(1, int(evento.intervallo or 1))
        orario = base.time()
        if evento.frequenza == FREQUENZA_GIORNALIERA:
            primo = 0
            if dal_giorno is not None and evento.fine_ripetizione != FINE_VOLTE:
                primo = max(0, (dal_giorno - base.date()).days // passo - 1)
            for indice in range(primo, primo + MASSIMO_CICLI):
                yield base + timedelta(days=indice * passo)
        elif evento.frequenza == FREQUENZA_SETTIMANALE:
            giorni = sorted({giorno for giorno in (evento.giorni_settimana or []) if 0 <= giorno <= 6}) or [base.weekday()]
            lunedi = base.date() - timedelta(days=base.weekday())
            prima_settimana = 0
            if dal_giorno is not None and evento.fine_ripetizione != FINE_VOLTE:
                prima_settimana = max(0, (dal_giorno - lunedi).days // (7 * passo) - 1)
            for settimana in range(prima_settimana, prima_settimana + MASSIMO_CICLI):
                inizio_settimana = lunedi + timedelta(days=settimana * passo * 7)
                for giorno in giorni:
                    candidato = inizio_settimana + timedelta(days=giorno)
                    if candidato < base.date():
                        continue
                    yield datetime.combine(candidato, orario)
        elif evento.frequenza == FREQUENZA_MENSILE:
            for indice in range(MASSIMO_CICLI):
                anno, mese = _aggiungi_mesi(base.year, base.month, indice * passo)
                if anno > 9999:
                    return
                if base.day <= calendar.monthrange(anno, mese)[1]:
                    yield datetime.combine(date(anno, mese, base.day), orario)
        elif evento.frequenza == FREQUENZA_ANNUALE:
            for indice in range(MASSIMO_CICLI):
                anno = base.year + indice * passo
                if anno > 9999:
                    return
                if base.month == 2 and base.day == 29 and not calendar.isleap(anno):
                    continue
                yield datetime.combine(date(anno, base.month, base.day), orario)
        else:
            yield base
    except Exception as ex:
        scrivi_log(f"agenda_model._inizi ({evento.id})", ex)


def occorrenze(evento, da, a):
    risultati = []
    try:
        durata = evento.durata
        if not evento.ricorrente:
            if evento.inizio < a and (evento.inizio + durata > da or (durata == timedelta(0) and evento.inizio >= da)):
                if evento.inizio.date() not in evento.esclusioni:
                    risultati.append(Occorrenza(evento, evento.inizio, evento.inizio + durata))
            return risultati
        limite_volte = int(evento.ripeti_volte or 0) if evento.fine_ripetizione == FINE_VOLTE else 0
        limite_data = evento.ripeti_fino if evento.fine_ripetizione == FINE_DATA else None
        dal_giorno = (da - durata).date() if evento.fine_ripetizione != FINE_VOLTE else None
        conteggio = 0
        for inizio in _inizi(evento, dal_giorno):
            conteggio += 1
            if limite_volte and conteggio > limite_volte:
                break
            if limite_data is not None and inizio.date() > limite_data:
                break
            if inizio >= a:
                break
            fine = inizio + durata
            if fine <= da and not (durata == timedelta(0) and inizio >= da):
                continue
            if inizio.date() in evento.esclusioni:
                continue
            risultati.append(Occorrenza(evento, inizio, fine))
    except Exception as ex:
        scrivi_log(f"agenda_model.occorrenze ({evento.id})", ex)
    return risultati


def occorrenze_di(eventi, da, a):
    elenco = []
    try:
        for evento in eventi:
            elenco.extend(occorrenze(evento, da, a))
        elenco.sort(key=lambda occorrenza: (occorrenza.inizio, not occorrenza.evento.tutto_il_giorno, occorrenza.evento.titolo.lower()))
    except Exception as ex:
        scrivi_log("agenda_model.occorrenze_di", ex)
    return elenco


def prossima_occorrenza(evento, dopo):
    try:
        for passo in (31, 366, 3660):
            trovate = occorrenze(evento, dopo, dopo + timedelta(days=passo))
            if trovate:
                return trovate[0]
        return None
    except Exception as ex:
        scrivi_log(f"agenda_model.prossima_occorrenza ({evento.id})", ex)
        return None


def leggi_data(testo, riferimento=None):
    try:
        oggi = riferimento or date.today()
        valore = " ".join(str(testo or "").lower().split())
        if not valore:
            return None
        parole = {"oggi": 0, "domani": 1, "dopodomani": 2, "ieri": -1}
        if valore in parole:
            return oggi + timedelta(days=parole[valore])
        corrispondenza = re.fullmatch(r"(\d{1,2})\s*[/\-. ]\s*(\d{1,2})(?:\s*[/\-. ]\s*(\d{2,4}))?", valore)
        if corrispondenza:
            giorno = int(corrispondenza.group(1))
            mese = int(corrispondenza.group(2))
            anno_testo = corrispondenza.group(3)
            if anno_testo is None:
                anno = oggi.year
            elif len(anno_testo) == 2:
                anno = 2000 + int(anno_testo)
            elif len(anno_testo) == 4:
                anno = int(anno_testo)
            else:
                return None
            return date(anno, mese, giorno)
        corrispondenza = re.fullmatch(r"(\d{1,2})\s+([a-zà-ù]+)(?:\s+(\d{4}))?", valore)
        if corrispondenza:
            nome = corrispondenza.group(2)
            for posizione, mese_nome in enumerate(MESI, start=1):
                if mese_nome.startswith(nome[:3]) and len(nome) >= 3:
                    anno = int(corrispondenza.group(3)) if corrispondenza.group(3) else oggi.year
                    return date(anno, posizione, int(corrispondenza.group(1)))
        corrispondenza = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", valore)
        if corrispondenza:
            return date(int(corrispondenza.group(1)), int(corrispondenza.group(2)), int(corrispondenza.group(3)))
        return None
    except ValueError:
        return None
    except Exception as ex:
        scrivi_log(f"agenda_model.leggi_data ({testo})", ex)
        return None


def leggi_ora(testo):
    try:
        valore = str(testo or "").strip().lower()
        if not valore:
            return None
        corrispondenza = re.fullmatch(r"(\d{1,2})(?:\s*[:.,h ]\s*(\d{2}))?", valore)
        if not corrispondenza:
            corrispondenza = re.fullmatch(r"(\d{2})(\d{2})", valore)
        if not corrispondenza:
            return None
        ore = int(corrispondenza.group(1))
        minuti = int(corrispondenza.group(2) or 0)
        if ore == 24 and minuti == 0:
            return time(0, 0)
        if not (0 <= ore <= 23 and 0 <= minuti <= 59):
            return None
        return time(ore, minuti)
    except Exception as ex:
        scrivi_log(f"agenda_model.leggi_ora ({testo})", ex)
        return None


def data_breve(giorno):
    try:
        return giorno.strftime("%d/%m/%Y") if giorno else ""
    except Exception as ex:
        scrivi_log("agenda_model.data_breve", ex)
        return ""


def ora_breve(orario):
    try:
        return orario.strftime("%H:%M") if orario else ""
    except Exception as ex:
        scrivi_log("agenda_model.ora_breve", ex)
        return ""


def nome_mese(anno, mese):
    try:
        return f"{MESI[mese - 1]} {anno}"
    except Exception as ex:
        scrivi_log(f"agenda_model.nome_mese ({anno}, {mese})", ex)
        return f"{mese}/{anno}"


def data_estesa(giorno, oggi=None, con_relativo=True):
    try:
        riferimento = oggi or date.today()
        testo = f"{GIORNI[giorno.weekday()]} {giorno.day} {MESI[giorno.month - 1]}"
        if giorno.year != riferimento.year:
            testo = f"{testo} {giorno.year}"
        if con_relativo:
            differenza = (giorno - riferimento).days
            relativi = {0: "oggi", 1: "domani", -1: "ieri", 2: "dopodomani"}
            if differenza in relativi:
                testo = f"{relativi[differenza]}, {testo}"
        return testo
    except Exception as ex:
        scrivi_log("agenda_model.data_estesa", ex)
        return data_breve(giorno)


def _elenco_con_e(parti):
    try:
        if len(parti) <= 1:
            return "".join(parti)
        return f"{', '.join(parti[:-1])} e {parti[-1]}"
    except Exception as ex:
        scrivi_log("agenda_model._elenco_con_e", ex)
        return ", ".join(parti)


def descrizione_ricorrenza(evento):
    try:
        if not evento.ricorrente:
            return ""
        passo = max(1, int(evento.intervallo or 1))
        if evento.frequenza == FREQUENZA_GIORNALIERA:
            testo = "ogni giorno" if passo == 1 else f"ogni {passo} giorni"
        elif evento.frequenza == FREQUENZA_SETTIMANALE:
            giorni = sorted(set(evento.giorni_settimana or [evento.inizio.weekday()]))
            if giorni == [0, 1, 2, 3, 4] and passo == 1:
                testo = "dal lunedì al venerdì"
            else:
                testo = "ogni settimana" if passo == 1 else f"ogni {passo} settimane"
                testo = f"{testo}, {_elenco_con_e([GIORNI[giorno] for giorno in giorni])}"
        elif evento.frequenza == FREQUENZA_MENSILE:
            base = "ogni mese" if passo == 1 else f"ogni {passo} mesi"
            testo = f"{base}, il giorno {evento.inizio.day}"
        else:
            base = "ogni anno" if passo == 1 else f"ogni {passo} anni"
            testo = f"{base}, il {evento.inizio.day} {MESI[evento.inizio.month - 1]}"
        if evento.fine_ripetizione == FINE_DATA and evento.ripeti_fino:
            testo = f"{testo}, fino al {data_breve(evento.ripeti_fino)}"
        elif evento.fine_ripetizione == FINE_VOLTE and evento.ripeti_volte:
            testo = f"{testo}, per {evento.ripeti_volte} volte"
        return testo
    except Exception as ex:
        scrivi_log(f"agenda_model.descrizione_ricorrenza ({evento.id})", ex)
        return ""


def orario_occorrenza(occorrenza, giorno_riferimento=None):
    try:
        evento = occorrenza.evento
        if occorrenza.piu_giorni:
            if evento.tutto_il_giorno:
                return f"dal {data_breve(occorrenza.inizio.date())} al {data_breve(occorrenza.ultimo_giorno)}"
            return (
                f"dal {data_breve(occorrenza.inizio.date())} alle {ora_breve(occorrenza.inizio.time())} "
                f"al {data_breve(occorrenza.fine.date())} alle {ora_breve(occorrenza.fine.time())}"
            )
        if evento.tutto_il_giorno:
            return "tutto il giorno"
        if occorrenza.fine > occorrenza.inizio:
            return f"dalle {ora_breve(occorrenza.inizio.time())} alle {ora_breve(occorrenza.fine.time())}"
        return f"alle {ora_breve(occorrenza.inizio.time())}"
    except Exception as ex:
        scrivi_log("agenda_model.orario_occorrenza", ex)
        return ""


def descrizione_avviso(minuti):
    try:
        valore = int(minuti)
        if valore < 0:
            return "nessuna notifica"
        if valore == 0:
            return "notifica all'inizio"
        if valore % 10080 == 0:
            settimane = valore // 10080
            return f"notifica {settimane} {'settimana' if settimane == 1 else 'settimane'} prima"
        if valore % 1440 == 0:
            giorni = valore // 1440
            return f"notifica {giorni} {'giorno' if giorni == 1 else 'giorni'} prima"
        if valore % 60 == 0:
            ore = valore // 60
            return f"notifica {ore} {'ora' if ore == 1 else 'ore'} prima"
        return f"notifica {valore} minuti prima"
    except Exception as ex:
        scrivi_log(f"agenda_model.descrizione_avviso ({minuti})", ex)
        return ""
