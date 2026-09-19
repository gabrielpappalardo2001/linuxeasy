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
