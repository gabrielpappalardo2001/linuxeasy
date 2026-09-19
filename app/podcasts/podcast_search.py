from dataclasses import dataclass, field
from typing import List

from app.core import rete
from app.core.log import scrivi_log

REQUEST_TIMEOUT = 20
SEARCH_ENDPOINT = "https://itunes.apple.com/search"
LOOKUP_ENDPOINT = "https://itunes.apple.com/lookup"
DIMENSIONE_BLOCCO_LOOKUP = 100
MINIMO_RISULTATI_CATEGORIA = 10

CATEGORIE = [
    (1301, "Arte"),
    (1305, "Bambini e famiglia"),
    (1303, "Comicità"),
    (1321, "Economia"),
    (1511, "Governo"),
    (1304, "Istruzione"),
    (1310, "Musica"),
    (1483, "Narrativa"),
    (1489, "Notizie"),
    (1314, "Religione e spiritualità"),
    (1512, "Salute e benessere"),
    (1533, "Scienze"),
    (1324, "Società e cultura"),
    (1545, "Sport"),
    (1487, "Storia"),
    (1318, "Tecnologia"),
    (1502, "Tempo libero"),
    (1488, "True crime"),
    (1309, "TV e cinema"),
]


class ErrorePodcast(Exception):
    pass


@dataclass
class PodcastResult:
    name: str
    author: str
    feed_url: str
    genre: str = ""
    episode_count: int = 0
    itunes_id: str = ""
    genre_ids: List[str] = field(default_factory=list)


def nome_categoria(genre_id):
    try:
        for identificativo, nome in CATEGORIE:
            if str(identificativo) == str(genre_id):
                return nome
        return ""
    except Exception as ex:
        scrivi_log(f"podcast_search.nome_categoria ({genre_id})", ex)
        return ""


class PodcastSearchClient:
    def _converti(self, elemento):
        try:
            feed_url = str(elemento.get("feedUrl") or "").strip()
            if not feed_url:
                return None
            return PodcastResult(
                name=" ".join(str(elemento.get("collectionName") or elemento.get("trackName") or "Podcast senza titolo").split()),
                author=" ".join(str(elemento.get("artistName") or "").split()),
                feed_url=feed_url,
                genre=str(elemento.get("primaryGenreName") or ""),
                episode_count=int(elemento.get("trackCount") or 0),
                itunes_id=str(elemento.get("collectionId") or elemento.get("trackId") or ""),
                genre_ids=[str(valore) for valore in (elemento.get("genreIds") or [])],
            )
        except Exception as ex:
            scrivi_log("PodcastSearchClient._converti", ex)
            return None

    def _senza_duplicati(self, elenco):
        risultati = []
        visti = set()
        try:
            for podcast in elenco:
                if podcast is None:
                    continue
                chiave = podcast.feed_url.lower()
                if chiave in visti:
                    continue
                visti.add(chiave)
                risultati.append(podcast)
        except Exception as ex:
            scrivi_log("PodcastSearchClient._senza_duplicati", ex)
        return risultati

    def search(self, query, country="IT", limit=50):
        try:
            testo = str(query or "").strip()
            if not testo:
                return []
            dati = rete.leggi_json(
                SEARCH_ENDPOINT,
                {"term": testo, "media": "podcast", "entity": "podcast", "country": country, "limit": limit},
                REQUEST_TIMEOUT,
            )
            return self._senza_duplicati(self._converti(elemento) for elemento in (dati or {}).get("results", []))
        except Exception as ex:
            scrivi_log(f"PodcastSearchClient.search ({query})", ex)
            raise ErrorePodcast(str(ex)) from ex

    def lookup(self, ids, country="IT"):
        try:
            identificativi = [str(valore) for valore in ids if str(valore or "").strip()]
            trovati = {}
            for inizio in range(0, len(identificativi), DIMENSIONE_BLOCCO_LOOKUP):
                blocco = identificativi[inizio:inizio + DIMENSIONE_BLOCCO_LOOKUP]
                try:
                    dati = rete.leggi_json(
                        LOOKUP_ENDPOINT,
                        {"id": ",".join(blocco), "country": country, "entity": "podcast"},
                        REQUEST_TIMEOUT,
                    )
                    for elemento in (dati or {}).get("results", []):
                        podcast = self._converti(elemento)
                        if podcast is not None and podcast.itunes_id:
                            trovati[podcast.itunes_id] = podcast
                except Exception as ex:
                    scrivi_log(f"PodcastSearchClient.lookup blocco da {inizio}", ex)
            if identificativi and not trovati:
                raise ErrorePodcast("Nessun dato ricevuto dal servizio di Apple")
            return self._senza_duplicati(trovati.get(identificativo) for identificativo in identificativi)
        except ErrorePodcast:
            raise
        except Exception as ex:
            scrivi_log("PodcastSearchClient.lookup", ex)
            raise ErrorePodcast(str(ex)) from ex

    def _id_classifica(self, country, limite):
        codice = str(country or "IT").lower()
        indirizzi = [f"https://rss.marketingtools.apple.com/api/v2/{codice}/podcasts/top/{limite}/podcasts.json"]
        if limite != 100:
            indirizzi.append(f"https://rss.marketingtools.apple.com/api/v2/{codice}/podcasts/top/100/podcasts.json")
        indirizzi.append(f"https://rss.applemarketingtools.com/api/v2/{codice}/podcasts/top/100/podcasts.json")
        for indirizzo in indirizzi:
            try:
                dati = rete.leggi_json(indirizzo, None, REQUEST_TIMEOUT)
                risultati = ((dati or {}).get("feed") or {}).get("results") or []
                ids = [str(elemento.get("id")) for elemento in risultati if elemento.get("id")]
                if ids:
                    return ids
            except Exception as ex:
                scrivi_log(f"PodcastSearchClient._id_classifica ({indirizzo})", ex)
        try:
            dati = rete.leggi_json(f"https://itunes.apple.com/{codice}/rss/toppodcasts/limit={limite}/json", None, REQUEST_TIMEOUT)
            voci = ((dati or {}).get("feed") or {}).get("entry") or []
            if isinstance(voci, dict):
                voci = [voci]
            ids = []
            for voce in voci:
                identificativo = (((voce.get("id") or {}).get("attributes")) or {}).get("im:id")
                if identificativo:
                    ids.append(str(identificativo))
            if ids:
                return ids
        except Exception as ex:
            scrivi_log(f"PodcastSearchClient._id_classifica classifica storica ({codice})", ex)
        raise ErrorePodcast("Classifica non disponibile")

    def chart(self, country="IT", limit=100):
        try:
            return self.lookup(self._id_classifica(country, limit), country)
        except ErrorePodcast:
            raise
        except Exception as ex:
            scrivi_log("PodcastSearchClient.chart", ex)
            raise ErrorePodcast(str(ex)) from ex

    def _classifica_genere_storica(self, genre_id, country):
        try:
            codice = str(country or "IT").lower()
            dati = rete.leggi_json(
                f"https://itunes.apple.com/{codice}/rss/toppodcasts/limit=100/genre={genre_id}/json",
                None,
                REQUEST_TIMEOUT,
            )
            voci = ((dati or {}).get("feed") or {}).get("entry") or []
            if isinstance(voci, dict):
                voci = [voci]
            ids = []
            corrispondenti = 0
            for voce in voci:
                identificativo = (((voce.get("id") or {}).get("attributes")) or {}).get("im:id")
                categoria = (((voce.get("category") or {}).get("attributes")) or {}).get("im:id")
                if not identificativo:
                    continue
                ids.append(str(identificativo))
                if str(categoria) == str(genre_id):
                    corrispondenti += 1
            if not ids or corrispondenti * 2 < len(ids):
                return []
            return self.lookup(ids, country)
        except Exception as ex:
            scrivi_log(f"PodcastSearchClient._classifica_genere_storica ({genre_id})", ex)
            return []

    def category(self, genre_id, country="IT"):
        try:
            genere = str(genre_id)
            risultati = list(self._classifica_genere_storica(genere, country))
            errori = 0
            if len(risultati) < MINIMO_RISULTATI_CATEGORIA:
                try:
                    for podcast in self.lookup(self._id_classifica(country, 200), country):
                        if genere in podcast.genre_ids:
                            risultati.append(podcast)
                except Exception as ex:
                    errori += 1
                    scrivi_log(f"PodcastSearchClient.category classifica generale ({genere})", ex)
                try:
                    nome = nome_categoria(genere)
                    if nome:
                        for podcast in self.search(nome, country, 200):
                            if genere in podcast.genre_ids:
                                risultati.append(podcast)
                except Exception as ex:
                    errori += 1
                    scrivi_log(f"PodcastSearchClient.category ricerca per nome ({genere})", ex)
            risultati = self._senza_duplicati(risultati)
            if not risultati and errori >= 2:
                raise ErrorePodcast("Servizio di Apple non raggiungibile")
            return risultati
        except ErrorePodcast:
            raise
        except Exception as ex:
            scrivi_log(f"PodcastSearchClient.category ({genre_id})", ex)
            raise ErrorePodcast(str(ex)) from ex
