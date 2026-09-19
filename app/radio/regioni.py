import re
import unicodedata

from app.core.log import scrivi_log

REGIONE_NON_INDICATA = "Regione non indicata"

NOMI_REGIONI = {
    "Abruzzo": ["abruzzo", "abruzzi"],
    "Basilicata": ["basilicata", "lucania"],
    "Calabria": ["calabria"],
    "Campania": ["campania"],
    "Emilia-Romagna": ["emilia romagna", "emilia", "romagna"],
    "Friuli-Venezia Giulia": ["friuli venezia giulia", "friuli", "venezia giulia"],
    "Lazio": ["lazio", "latium"],
    "Liguria": ["liguria"],
    "Lombardia": ["lombardia", "lombardy"],
    "Marche": ["marche"],
    "Molise": ["molise"],
    "Piemonte": ["piemonte", "piedmont"],
    "Puglia": ["puglia", "apulia", "salento"],
    "Sardegna": ["sardegna", "sardinia"],
    "Sicilia": ["sicilia", "sicily"],
    "Toscana": ["toscana", "tuscany"],
    "Trentino-Alto Adige": [
        "trentino alto adige",
        "trentino sudtirol",
        "trentino south tyrol",
        "trentino",
        "alto adige",
        "sudtirol",
        "suedtirol",
        "south tyrol",
    ],
    "Umbria": ["umbria"],
    "Valle d'Aosta": ["valle d aosta", "valle daosta", "vallee d aoste", "aosta valley", "val d aosta"],
    "Veneto": ["veneto"],
}

CITTA_REGIONI = {
    "Abruzzo": ["l aquila", "aquila", "chieti", "pescara", "teramo", "avezzano", "lanciano", "vasto"],
    "Basilicata": ["potenza", "matera"],
    "Calabria": [
        "catanzaro",
        "cosenza",
        "crotone",
        "reggio calabria",
        "reggio di calabria",
        "vibo valentia",
        "lamezia terme",
    ],
    "Campania": ["napoli", "naples", "avellino", "benevento", "caserta", "salerno", "ischia", "sorrento"],
    "Emilia-Romagna": [
        "bologna",
        "ferrara",
        "forli",
        "cesena",
        "forli cesena",
        "modena",
        "parma",
        "piacenza",
        "ravenna",
        "reggio emilia",
        "reggio nell emilia",
        "rimini",
        "imola",
        "carpi",
    ],
    "Friuli-Venezia Giulia": ["trieste", "gorizia", "pordenone", "udine"],
    "Lazio": ["roma", "rome", "frosinone", "latina", "rieti", "viterbo", "civitavecchia"],
    "Liguria": ["genova", "genoa", "imperia", "la spezia", "spezia", "savona", "sanremo"],
    "Lombardia": [
        "milano",
        "milan",
        "bergamo",
        "brescia",
        "como",
        "cremona",
        "lecco",
        "lodi",
        "mantova",
        "mantua",
        "monza",
        "monza e brianza",
        "brianza",
        "pavia",
        "sondrio",
        "varese",
        "busto arsizio",
    ],
    "Marche": ["ancona", "ascoli piceno", "fermo", "macerata", "pesaro", "urbino", "pesaro e urbino", "the marches"],
    "Molise": ["campobasso", "isernia", "termoli"],
    "Piemonte": [
        "torino",
        "turin",
        "alessandria",
        "asti",
        "biella",
        "cuneo",
        "novara",
        "verbania",
        "vercelli",
        "verbano cusio ossola",
    ],
    "Puglia": ["bari", "barletta", "andria", "trani", "barletta andria trani", "brindisi", "foggia", "lecce", "taranto"],
    "Sardegna": ["cagliari", "nuoro", "oristano", "sassari", "olbia", "sud sardegna"],
    "Sicilia": [
        "palermo",
        "agrigento",
        "caltanissetta",
        "catania",
        "enna",
        "messina",
        "ragusa",
        "siracusa",
        "syracuse",
        "trapani",
    ],
    "Toscana": [
        "firenze",
        "florence",
        "arezzo",
        "grosseto",
        "livorno",
        "lucca",
        "massa",
        "carrara",
        "massa carrara",
        "pisa",
        "pistoia",
        "prato",
        "siena",
        "viareggio",
        "empoli",
    ],
    "Trentino-Alto Adige": ["trento", "bolzano", "bozen", "merano", "meran", "bressanone", "brixen", "rovereto"],
    "Umbria": ["perugia", "terni", "foligno", "spoleto"],
    "Valle d'Aosta": ["aosta", "aoste"],
    "Veneto": ["venezia", "venice", "belluno", "padova", "padua", "rovigo", "treviso", "verona", "vicenza"],
}


def normalizza(testo):
    try:
        valore = unicodedata.normalize("NFKD", str(testo or ""))
        valore = "".join(carattere for carattere in valore if not unicodedata.combining(carattere)).lower()
        valore = re.sub(r"[^a-z0-9]+", " ", valore).strip()
        return f" {valore} " if valore else ""
    except Exception as ex:
        scrivi_log(f"regioni.normalizza ({testo})", ex)
        return ""


def _costruisci_alias(*dizionari):
    try:
        coppie = []
        for dizionario in dizionari:
            for regione, alias in dizionario.items():
                for nome in alias:
                    forma = normalizza(nome)
                    if forma:
                        coppie.append((forma, regione))
        coppie.sort(key=lambda coppia: len(coppia[0]), reverse=True)
        return coppie
    except Exception as ex:
        scrivi_log("regioni._costruisci_alias", ex)
        return []


_ALIAS_STATO = _costruisci_alias(NOMI_REGIONI, CITTA_REGIONI)
_ALIAS_NOME = _costruisci_alias(NOMI_REGIONI)


def elenco_regioni():
    try:
        return sorted(NOMI_REGIONI.keys(), key=lambda nome: normalizza(nome))
    except Exception as ex:
        scrivi_log("regioni.elenco_regioni", ex)
        return list(NOMI_REGIONI.keys())


def _cerca(testo, alias):
    try:
        forma = normalizza(testo)
        if not forma:
            return None
        for nome, regione in alias:
            if nome in forma:
                return regione
        return None
    except Exception as ex:
        scrivi_log(f"regioni._cerca ({testo})", ex)
        return None


def classifica(stato="", nome="", tag=""):
    try:
        regione = _cerca(stato, _ALIAS_STATO)
        if regione:
            return regione
        regione = _cerca(nome, _ALIAS_NOME)
        if regione:
            return regione
        return _cerca(str(tag or "").replace(",", " , "), _ALIAS_NOME)
    except Exception as ex:
        scrivi_log(f"regioni.classifica ({stato}, {nome})", ex)
        return None


def stessa_regione(testo, regione):
    try:
        return normalizza(testo) == normalizza(regione)
    except Exception as ex:
        scrivi_log(f"regioni.stessa_regione ({testo}, {regione})", ex)
        return False
