import threading

from app.core import rete
from app.core.log import scrivi_log

SERVER = [
    "https://de1.api.radio-browser.info",
    "https://de2.api.radio-browser.info",
    "https://fi1.api.radio-browser.info",
    "https://all.api.radio-browser.info",
]


class ErroreRadio(Exception):
    pass


class RadioSearchResult:
    def __init__(self, name, url, stationuuid="", country="", countrycode="", state="", tags="", codec="", bitrate=0):
        self.name = name
        self.url = url
        self.stationuuid = stationuuid
        self.country = country
        self.countrycode = countrycode
        self.state = state
        self.tags = tags
        self.codec = codec
        self.bitrate = bitrate

    def to_dict(self):
        return {
            "name": self.name,
            "url": self.url,
            "uuid": self.stationuuid,
            "country": self.country,
            "countrycode": self.countrycode,
            "state": self.state,
            "tags": self.tags,
            "codec": self.codec,
            "bitrate": self.bitrate,
        }


class RadioBrowserClient:
    def __init__(self, timeout=20):
        self.timeout = timeout
        self._server_preferito = 0
        self._blocco = threading.Lock()

    def _ordine_server(self):
        with self._blocco:
            primo = self._server_preferito
        return [primo] + [indice for indice in range(len(SERVER)) if indice != primo]

    def _richiesta(self, percorso, parametri=None):
        ultimo_errore = None
        for indice in self._ordine_server():
            try:
                dati = rete.leggi_json(SERVER[indice] + percorso, parametri, self.timeout)
                with self._blocco:
                    self._server_preferito = indice
                return dati
            except Exception as ex:
                ultimo_errore = ex
        scrivi_log(f"RadioBrowserClient._richiesta: nessun server raggiungibile per {percorso}", ultimo_errore)
        raise ErroreRadio("Servizio delle radio non raggiungibile")

    def _converti(self, dati):
        risultati = []
        visti = set()
        try:
            for elemento in dati or []:
                try:
                    url = str(elemento.get("url_resolved") or elemento.get("url") or "").strip()
                    nome = " ".join(str(elemento.get("name") or "").split())
                    if not url or not nome:
                        continue
                    chiave = url.lower()
                    if chiave in visti:
                        continue
                    visti.add(chiave)
                    risultati.append(
                        RadioSearchResult(
                            name=nome,
                            url=url,
                            stationuuid=str(elemento.get("stationuuid") or ""),
                            country=str(elemento.get("country") or "").strip(),
                            countrycode=str(elemento.get("countrycode") or "").strip().upper(),
                            state=" ".join(str(elemento.get("state") or "").split()),
                            tags=str(elemento.get("tags") or ""),
                            codec=str(elemento.get("codec") or ""),
                            bitrate=int(elemento.get("bitrate") or 0),
                        ).to_dict()
                    )
                except Exception as ex:
                    scrivi_log("RadioBrowserClient._converti elemento", ex)
        except Exception as ex:
            scrivi_log("RadioBrowserClient._converti", ex)
        return risultati

    def stazioni_per_paese(self, codice_paese, limite=10000):
        try:
            dati = self._richiesta(
                "/json/stations/search",
                {
                    "countrycode": codice_paese,
                    "hidebroken": "true",
                    "order": "clickcount",
                    "reverse": "true",
                    "limit": limite,
                },
            )
            return self._converti(dati)
        except ErroreRadio:
            raise
        except Exception as ex:
            scrivi_log(f"RadioBrowserClient.stazioni_per_paese ({codice_paese})", ex)
            raise ErroreRadio(str(ex)) from ex

    def stazioni_popolari(self, limite=500, escludi_paese="IT"):
        try:
            dati = self._richiesta(
                "/json/stations/search",
                {
                    "hidebroken": "true",
                    "order": "clickcount",
                    "reverse": "true",
                    "limit": limite + 300,
                },
            )
            stazioni = [
                stazione
                for stazione in self._converti(dati)
                if not escludi_paese or stazione["countrycode"] != escludi_paese
            ]
            return stazioni[:limite]
        except ErroreRadio:
            raise
        except Exception as ex:
            scrivi_log("RadioBrowserClient.stazioni_popolari", ex)
            raise ErroreRadio(str(ex)) from ex

    def cerca(self, testo, limite=300):
        try:
            dati = self._richiesta(
                "/json/stations/search",
                {
                    "name": testo,
                    "hidebroken": "true",
                    "order": "clickcount",
                    "reverse": "true",
                    "limit": limite,
                },
            )
            return self._converti(dati)
        except ErroreRadio:
            raise
        except Exception as ex:
            scrivi_log(f"RadioBrowserClient.cerca ({testo})", ex)
            raise ErroreRadio(str(ex)) from ex

    def search_stations(self, name="", limit=20):
        try:
            return [
                RadioSearchResult(stazione["name"], stazione["url"], stazione["uuid"])
                for stazione in self.cerca(name, limit)
            ]
        except Exception as ex:
            scrivi_log(f"RadioBrowserClient.search_stations ({name})", ex)
            return []

    def registra_click(self, uuid):
        try:
            if uuid:
                self._richiesta(f"/json/url/{uuid}")
        except Exception as ex:
            scrivi_log(f"RadioBrowserClient.registra_click ({uuid})", ex)
