from app.core.log import scrivi_log


class PaginaTesto:
    def __init__(self, titolo, testo, azioni=None):
        self.titolo = titolo
        self.testo = testo
        self.azioni = azioni
        self.posizione = 0

    def aggiorna(self, testo):
        try:
            self.testo = testo
            self.posizione = 0
        except Exception as ex:
            scrivi_log("PaginaTesto.aggiorna", ex)


class PaginaProgresso(PaginaTesto):
    def __init__(self, titolo, righe=None, azioni=None):
        self.righe = [str(riga) for riga in (righe or [])]
        super().__init__(titolo, "\n".join(self.righe), azioni)

    def aggiungi(self, riga):
        try:
            self.righe.append(str(riga))
            self.testo = "\n".join(self.righe)
        except Exception as ex:
            scrivi_log("PaginaProgresso.aggiungi", ex)
