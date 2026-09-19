import re
import urllib.request
from pathlib import Path

from app.core import percorsi
from app.core.log import scrivi_log

DIMENSIONE_INTESTAZIONE = 10
DIMENSIONE_ID3V1 = 128
MASSIMO_TAG = 524288
PRIMA_LETTURA_REMOTA = 65536
CAMPI_TITOLO = ("TIT2", "TT2")
CAMPI_TRACCIA = ("TRCK", "TRK")
CAMPI_ALBUM = ("TALB", "TAL")
CAMPI_ARTISTA = ("TPE1", "TP1")


def _intero_sincronizzato(dati):
    try:
        valore = 0
        for byte in dati:
            valore = (valore << 7) | (byte & 0x7F)
        return valore
    except Exception as ex:
        scrivi_log("tag_audio._intero_sincronizzato", ex)
        return 0


def _togli_sincronizzazione(dati):
    try:
        return dati.replace(b"\xff\x00", b"\xff")
    except Exception as ex:
        scrivi_log("tag_audio._togli_sincronizzazione", ex)
        return dati


def _decodifica_testo(dati):
    try:
        if not dati:
            return ""
        codifica = dati[0]
        corpo = dati[1:]
        if codifica == 0:
            testo = corpo.decode("latin-1", errors="replace")
        elif codifica == 1:
            if corpo[:2] in (b"\xff\xfe", b"\xfe\xff"):
                testo = corpo.decode("utf-16", errors="replace")
            else:
                testo = corpo.decode("utf-16-le", errors="replace")
        elif codifica == 2:
            testo = corpo.decode("utf-16-be", errors="replace")
        elif codifica == 3:
            testo = corpo.decode("utf-8", errors="replace")
        else:
            testo = dati.decode("latin-1", errors="replace")
        primo = testo.split("\x00")[0]
        return " ".join(primo.replace("\ufeff", "").split())
    except Exception as ex:
        scrivi_log("tag_audio._decodifica_testo", ex)
        return ""


def dimensione_tag_id3v2(intestazione):
    try:
        if len(intestazione) < DIMENSIONE_INTESTAZIONE or intestazione[:3] != b"ID3":
            return 0
        piede = 10 if intestazione[5] & 0x10 else 0
        return DIMENSIONE_INTESTAZIONE + _intero_sincronizzato(intestazione[6:10]) + piede
    except Exception as ex:
        scrivi_log("tag_audio.dimensione_tag_id3v2", ex)
        return 0


def analizza_id3v2(dati):
    risultato = {}
    try:
        if len(dati) < DIMENSIONE_INTESTAZIONE or dati[:3] != b"ID3":
            return risultato
        versione = dati[3]
        opzioni = dati[5]
        if versione not in (2, 3, 4):
            return risultato
        dimensione = _intero_sincronizzato(dati[6:10])
        corpo = dati[DIMENSIONE_INTESTAZIONE:DIMENSIONE_INTESTAZIONE + dimensione]
        if opzioni & 0x80 and versione < 4:
            corpo = _togli_sincronizzazione(corpo)
        posizione = 0
        if opzioni & 0x40 and versione >= 3 and len(corpo) >= 4:
            if versione == 3:
                posizione = 4 + int.from_bytes(corpo[0:4], "big")
            else:
                posizione = _intero_sincronizzato(corpo[0:4])
        lunghezza_nome = 3 if versione == 2 else 4
        lunghezza_testata = 6 if versione == 2 else 10
        while posizione + lunghezza_testata <= len(corpo):
            testata = corpo[posizione:posizione + lunghezza_testata]
            if testata[0:1] == b"\x00":
                break
            if not re.fullmatch(rb"[A-Z0-9]{3,4}", testata[:lunghezza_nome]):
                break
            nome = testata[:lunghezza_nome].decode("ascii", errors="replace")
            if versione == 2:
                dimensione_campo = int.from_bytes(testata[3:6], "big")
                opzioni_campo = 0
            elif versione == 3:
                dimensione_campo = int.from_bytes(testata[4:8], "big")
                opzioni_campo = int.from_bytes(testata[8:10], "big")
            else:
                dimensione_campo = _intero_sincronizzato(testata[4:8])
                opzioni_campo = int.from_bytes(testata[8:10], "big")
            inizio = posizione + lunghezza_testata
            fine = inizio + dimensione_campo
            if dimensione_campo <= 0:
                break
            contenuto = corpo[inizio:min(fine, len(corpo))]
            posizione = fine
            if nome not in CAMPI_TITOLO + CAMPI_TRACCIA + CAMPI_ALBUM + CAMPI_ARTISTA:
                continue
            if versione == 3 and opzioni_campo & 0x00C0:
                continue
            if versione == 4:
                if opzioni_campo & 0x000C:
                    continue
                if opzioni_campo & 0x0001 and len(contenuto) >= 4:
                    contenuto = contenuto[4:]
                if opzioni_campo & 0x0002:
                    contenuto = _togli_sincronizzazione(contenuto)
            testo = _decodifica_testo(contenuto)
            if not testo:
                continue
            if nome in CAMPI_TITOLO:
                risultato.setdefault("title", testo)
            elif nome in CAMPI_TRACCIA:
                risultato.setdefault("track", testo)
            elif nome in CAMPI_ALBUM:
                risultato.setdefault("album", testo)
            elif nome in CAMPI_ARTISTA:
                risultato.setdefault("artist", testo)
    except Exception as ex:
        scrivi_log("tag_audio.analizza_id3v2", ex)
    return risultato


def analizza_id3v1(dati):
    risultato = {}
    try:
        if len(dati) < DIMENSIONE_ID3V1:
            return risultato
        blocco = dati[-DIMENSIONE_ID3V1:]
        if blocco[:3] != b"TAG":
            return risultato
        campi = {
            "title": blocco[3:33],
            "artist": blocco[33:63],
            "album": blocco[63:93],
        }
        for chiave, valore in campi.items():
            testo = " ".join(valore.split(b"\x00")[0].decode("latin-1", errors="replace").split())
            if testo:
                risultato[chiave] = testo
        if blocco[125] == 0 and blocco[126] != 0:
            risultato["track"] = str(blocco[126])
    except Exception as ex:
        scrivi_log("tag_audio.analizza_id3v1", ex)
    return risultato


def leggi_tag_file(percorso):
    try:
        file_audio = Path(percorso)
        if not file_audio.is_file():
            return {}
        with open(file_audio, "rb") as flusso:
            intestazione = flusso.read(DIMENSIONE_INTESTAZIONE)
            risultato = {}
            dimensione = dimensione_tag_id3v2(intestazione)
            if dimensione:
                flusso.seek(0)
                risultato = analizza_id3v2(flusso.read(min(dimensione, MASSIMO_TAG)))
            if not risultato.get("title"):
                lunghezza = file_audio.stat().st_size
                if lunghezza >= DIMENSIONE_ID3V1:
                    flusso.seek(lunghezza - DIMENSIONE_ID3V1)
                    for chiave, valore in analizza_id3v1(flusso.read(DIMENSIONE_ID3V1)).items():
                        risultato.setdefault(chiave, valore)
        return risultato
    except Exception as ex:
        scrivi_log(f"tag_audio.leggi_tag_file ({percorso})", ex)
        return {}


def _leggi_intervallo(url, intervallo, massimo, timeout):
    richiesta = urllib.request.Request(
        url,
        headers={"User-Agent": percorsi.USER_AGENT, "Range": f"bytes={intervallo}", "Accept": "*/*"},
    )
    with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
        return getattr(risposta, "status", 200), risposta.read(massimo)


def leggi_tag_remoto(url, timeout=10):
    try:
        if not url:
            return {}
        _stato, dati = _leggi_intervallo(url, f"0-{PRIMA_LETTURA_REMOTA - 1}", PRIMA_LETTURA_REMOTA, timeout)
        risultato = {}
        dimensione = dimensione_tag_id3v2(dati)
        if dimensione:
            risultato = analizza_id3v2(dati)
            if not risultato.get("title") and dimensione > len(dati):
                _stato_completo, completi = _leggi_intervallo(
                    url,
                    f"0-{min(dimensione, MASSIMO_TAG) - 1}",
                    min(dimensione, MASSIMO_TAG),
                    timeout,
                )
                risultato = analizza_id3v2(completi)
        if not risultato.get("title"):
            try:
                stato_coda, coda = _leggi_intervallo(url, f"-{DIMENSIONE_ID3V1}", DIMENSIONE_ID3V1, timeout)
                if stato_coda == 206 and len(coda) == DIMENSIONE_ID3V1:
                    for chiave, valore in analizza_id3v1(coda).items():
                        risultato.setdefault(chiave, valore)
            except Exception as ex:
                scrivi_log(f"tag_audio.leggi_tag_remoto ID3v1 ({url})", ex)
        return risultato
    except Exception as ex:
        scrivi_log(f"tag_audio.leggi_tag_remoto ({url})", ex)
        return {}
