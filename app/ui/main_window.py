import shutil
import subprocess
import threading
from datetime import date, datetime
from functools import partial

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Atk", "1.0")

from gi.repository import Atk, Gdk, Gio, GLib, GObject, Gtk

try:
    gi.require_version("GdkX11", "3.0")
    from gi.repository import GdkX11
except Exception:
    GdkX11 = None

from app.agenda.agenda_model import data_estesa, ora_breve
from app.agenda.agenda_notifier import TIPO_AVVISO, AgendaNotifier
from app.agenda.agenda_store import AgendaStore
from app.core.database import Database
from app.core.gestore_file import GestoreFile
from app.core.impostazioni import Impostazioni
from app.core.log import installa_gestori_globali, scrivi_log
from app.core.mpv_engine import MPVEngine, assicura_configurazione_globale
from app.librivox.librivox_catalog import LibriVoxCatalog
from app.librivox.librivox_downloads import LibriVoxDownloads
from app.librivox.librivox_library import LibriVoxLibrary
from app.news.article_text import ArticleTextExtractor
from app.news.headless_browser import HeadlessBrowser
from app.news.news_parser import NewsParser
from app.news.news_updater import NewsUpdater
from app.news.source_manager import SourceManager
from app.podcasts.podcast_downloads import PodcastDownloads
from app.podcasts.podcast_notifier import PodcastNotifier
from app.podcasts.podcast_search import PodcastSearchClient
from app.podcasts.subscriptions import PodcastLibrary
from app.radio.stations import RadioManager
from app.ui.control_center_view import ControlCenterView
from app.rubrica.rubrica_store import RubricaStore
from app.ui.agenda_view import AgendaView
from app.ui.librivox_view import LibriVoxView
from app.ui.modulo_dialogo import chiedi_modulo
from app.ui.news_view import NewsView
from app.ui.pagina import PaginaTesto
from app.ui.podcast_view import PodcastView
from app.ui.radio_view import RadioView
from app.ui.rubrica_view import RubricaView
from app.ui.selettore_file import SelettoreFile
from app.ui.settings_view import SettingsView
from app.ui.video_area import AreaVideo
from app.ui.wikipedia_view import WikipediaView
from app.ui.youtube_view import YouTubeView
from app.youtube.youtube_library import YouTubeLibrary
from app.wikipedia.wikipedia_client import WikipediaClient
from app.wikipedia.wikipedia_library import WikipediaLibrary
from app.youtube.youtube_search import YouTubeSearchClient

NOME_PROGRAMMA = "LinuxEasy"
TITOLO_PRINCIPALE = "Menu Principale"
TITOLO_CENTRO_CONTROLLO = "Centro di controllo"
TITOLO_NUOVI_EPISODI = "Nuovi episodi"
TASTI_AVANTI_INDIETRO = ("Right", "Left")
TASTI_VOLUME = ("Up", "Down")
TASTI_SU = ("Up", "KP_Up")
TASTI_GIU = ("Down", "KP_Down")
TASTI_TRACCIA = ("b", "B", "f", "F")
INCREMENTO_VOLUME = 5
TESTO_CARICAMENTO = "Caricamento in corso"
TASTI_INVIO = ("Return", "KP_Enter")
TASTI_INDIETRO = ("Escape", "BackSpace")
TASTI_AZIONI = ("Alt_L", "Alt_R", "ISO_Level3_Shift", "Meta_L", "Meta_R")
SECONDI_AVVISO_STATO = 10
ETICHETTE_ASCOLTO = {
    "brani": "Ascolto brani",
    "video": "Ascolto video",
    "youtube": "Ascolto YouTube",
    "stream": "Ascolto stream",
    "audiolibro": "Ascolto audiolibro",
}
TITOLO_ASCOLTO_PREDEFINITO = "Ascolto in corso"
ID_NOTIFICA_EPISODI = "linuxeasy-nuovi-episodi"
ID_NOTIFICA_NOTIZIE = "linuxeasy-nuove-notizie"
ID_NOTIFICA_AGENDA = "linuxeasy-appuntamenti"
VISTA_LISTA = "lista"
VISTA_TESTO = "testo"
ALTEZZA_AREA_VIDEO = 360


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=NOME_PROGRAMMA)
        installa_gestori_globali()
        self.history = []
        self.current_items = []
        self.current_source = []
        self.current_empty_message = None
        self.menu_positions = {}
        self.selection_enabled = False
        self.selected_indices = set()
        self.player_screen_active = False
        self._navigazione = 0
        self._timer_stato = 0
        self._annunci_disponibili = False
        self.box = None
        self.label = None
        self.listbox = None
        self.stack = None
        self.area_video = None
        self.textview = None
        self.avviso_episodi = None
        self.avviso_notizie = None
        self.avviso_agenda = None
        self.agenda_store = None
        self.agenda_notifier = None
        self.agenda_view = None
        self.rubrica_store = None
        self.rubrica_view = None
        self.avviso_stato = None
        self.db = None
        self.impostazioni = None
        self.engine = None
        self.radio_manager = None
        self.source_manager = None
        self.news_browser = None
        self.news_parser = None
        self.news_extractor = None
        self.news_updater = None
        self.podcast_library = None
        self.podcast_search = None
        self.podcast_downloads = None
        self.podcast_notifier = None
        self.youtube_library = None
        self.gestore_file = None
        self.selettore_file = None
        self.wikipedia_client = None
        self.wikipedia_library = None
        self.wikipedia_view = None
        self.librivox_catalog = None
        self.librivox_library = None
        self.librivox_downloads = None
        self.librivox_view = None
        self.youtube_search = None
        self.radio_view = None
        self.podcast_view = None
        self.news_view = None
        self.youtube_view = None
        self.settings_view = None
        self.control_center_view = None
        try:
            self.set_default_size(900, 600)
            self._crea_servizi()
            self._crea_interfaccia()
            self.connect("key-press-event", self.on_key_press)
            self.connect("destroy", self._alla_distruzione)
            self.show_main_menu()
            self._avvia_servizi()
            GLib.idle_add(self._collega_area_video)
        except Exception as ex:
            scrivi_log("MainWindow.__init__", ex)

    def _crea(self, nome, fabbrica):
        try:
            return fabbrica()
        except Exception as ex:
            scrivi_log(f"MainWindow._crea ({nome})", ex)
            return None

    def _crea_servizi(self):
        try:
            self.db = self._crea("database", Database)
            self.impostazioni = self._crea("impostazioni", lambda: Impostazioni(self.db))
            self._crea("configurazione globale di mpv", assicura_configurazione_globale)
            self.engine = self._crea(
                "motore di riproduzione",
                lambda: MPVEngine(
                    self._traccia_cambiata,
                    self._video_cambiato,
                    self.impostazioni,
                    self._posizione_ripristinata,
                ),
            )
            if self.db is not None:
                self.radio_manager = self._crea("gestore radio", lambda: RadioManager(self.db))
                self.podcast_library = self._crea("libreria podcast", lambda: PodcastLibrary(self.db))
                self.youtube_library = self._crea("libreria YouTube", lambda: YouTubeLibrary(self.db))
            self.youtube_search = self._crea("ricerca YouTube", YouTubeSearchClient)
            self.news_browser = self._crea("browser invisibile", HeadlessBrowser)
            self.news_parser = self._crea("lettore notizie", lambda: NewsParser(self.news_browser))
            if self.db is not None and self.news_parser is not None:
                self.source_manager = self._crea("gestore notizie", lambda: SourceManager(self.db, self.news_parser))
            if self.source_manager is not None:
                self.news_extractor = self._crea(
                    "estrazione testo notizie",
                    lambda: ArticleTextExtractor(self.source_manager, self.news_parser, self.news_browser),
                )
                self.news_updater = self._crea(
                    "aggiornamento notizie",
                    lambda: NewsUpdater(self.source_manager, self.notifica_nuove_notizie),
                )
            self.podcast_search = self._crea("ricerca podcast", PodcastSearchClient)
            if self.db is not None:
                self.podcast_downloads = self._crea(
                    "download podcast",
                    lambda: PodcastDownloads(self.db, self._download_completato, self._download_fallito),
                )
            if self.podcast_library is not None:
                self.podcast_notifier = self._crea(
                    "avvisi podcast",
                    lambda: PodcastNotifier(self.podcast_library, self.notifica_nuovi_episodi),
                )
            if self.db is not None:
                self.agenda_store = self._crea("archivio dell'agenda", lambda: AgendaStore(self.db))
                self.rubrica_store = self._crea("archivio della rubrica", lambda: RubricaStore(self.db))
            if self.agenda_store is not None:
                self.agenda_notifier = self._crea(
                    "notifiche dell'agenda",
                    lambda: AgendaNotifier(self.agenda_store, self.notifica_appuntamenti),
                )
                self.agenda_view = self._crea(
                    "vista agenda",
                    lambda: AgendaView(self, self.agenda_store, self.agenda_notifier),
                )
            self.gestore_file = self._crea("gestore dei file", GestoreFile)
            if self.gestore_file is not None:
                self.selettore_file = self._crea("selettore dei file", lambda: SelettoreFile(self, self.gestore_file))
            if self.rubrica_store is not None:
                self.rubrica_view = self._crea(
                    "vista rubrica",
                    lambda: RubricaView(self, self.rubrica_store, self.agenda_view, self.selettore_file),
                )
            self.wikipedia_client = self._crea("client Wikipedia", lambda: WikipediaClient(self.news_parser))
            if self.db is not None:
                self.wikipedia_library = self._crea("libreria Wikipedia", lambda: WikipediaLibrary(self.db))
            if self.wikipedia_client is not None and self.wikipedia_library is not None:
                self.wikipedia_view = self._crea(
                    "vista Wikipedia",
                    lambda: WikipediaView(self, self.wikipedia_client, self.wikipedia_library, self.selettore_file),
                )
            if self.db is not None:
                self.librivox_catalog = self._crea("catalogo LibriVox", lambda: LibriVoxCatalog(self.db))
            if self.librivox_catalog is not None:
                self.librivox_library = self._crea(
                    "libreria LibriVox",
                    lambda: LibriVoxLibrary(self.db, self.librivox_catalog),
                )
                self.librivox_downloads = self._crea(
                    "download LibriVox",
                    lambda: LibriVoxDownloads(
                        self.db,
                        self.librivox_catalog,
                        self._audiolibro_scaricato,
                        self._audiolibro_non_scaricato,
                    ),
                )
            if None not in (self.librivox_catalog, self.librivox_library, self.librivox_downloads):
                self.librivox_view = self._crea(
                    "vista LibriVox",
                    lambda: LibriVoxView(
                        self,
                        self.engine,
                        self.librivox_catalog,
                        self.librivox_library,
                        self.librivox_downloads,
                    ),
                )
            if self.radio_manager is not None:
                self.radio_view = self._crea("vista radio", lambda: RadioView(self, self.radio_manager, self.engine))
            if None not in (self.podcast_library, self.podcast_search, self.podcast_downloads, self.podcast_notifier):
                self.podcast_view = self._crea(
                    "vista podcast",
                    lambda: PodcastView(
                        self,
                        self.engine,
                        self.podcast_library,
                        self.podcast_search,
                        self.podcast_downloads,
                        self.podcast_notifier,
                    ),
                )
            if None not in (self.source_manager, self.news_extractor, self.news_updater):
                self.news_view = self._crea(
                    "vista notizie",
                    lambda: NewsView(self, self.source_manager, self.news_parser, self.news_extractor, self.news_updater),
                )
            if None not in (self.youtube_library, self.youtube_search):
                self.youtube_view = self._crea(
                    "vista YouTube",
                    lambda: YouTubeView(self, self.engine, self.youtube_library, self.youtube_search),
                )
            self.settings_view = self._crea(
                "vista impostazioni",
                lambda: SettingsView(self, self.impostazioni, self.engine),
            )
            self.control_center_view = self._crea(
                "centro di controllo",
                lambda: ControlCenterView(self, self.engine),
            )
        except Exception as ex:
            scrivi_log("MainWindow._crea_servizi", ex)

    def _verifica_annunci(self):
        try:
            accessibile = Gtk.Label().get_accessible()
            if accessibile is None:
                return False
            return GObject.signal_lookup("announcement", accessibile.__gtype__) != 0
        except Exception as ex:
            scrivi_log("MainWindow._verifica_annunci", ex)
            return False

    def _crea_avviso(self):
        etichetta = Gtk.Label()
        try:
            etichetta.set_xalign(0)
            etichetta.set_line_wrap(True)
            etichetta.set_no_show_all(True)
            etichetta.hide()
            if not self._annunci_disponibili:
                accessibile = etichetta.get_accessible()
                if accessibile is not None:
                    accessibile.set_role(getattr(Atk.Role, "NOTIFICATION", Atk.Role.ALERT))
            self.box.pack_start(etichetta, False, False, 0)
        except Exception as ex:
            scrivi_log("MainWindow._crea_avviso", ex)
        return etichetta

    def _crea_interfaccia(self):
        try:
            self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            self.box.set_border_width(8)
            self.add(self.box)
            self._annunci_disponibili = self._verifica_annunci()
            self.avviso_episodi = self._crea_avviso()
            self.avviso_notizie = self._crea_avviso()
            self.avviso_agenda = self._crea_avviso()
            self.avviso_stato = self._crea_avviso()
            self.label = Gtk.Label()
            self.label.set_xalign(0)
            self.box.pack_start(self.label, False, False, 4)
            self.area_video = self._crea("area video", lambda: AreaVideo(ALTEZZA_AREA_VIDEO))
            if self.area_video is not None:
                self.box.pack_start(self.area_video, False, False, 0)
                self.area_video.hide()
            self.stack = Gtk.Stack()
            self.stack.set_vexpand(True)
            scorrimento_lista = Gtk.ScrolledWindow()
            scorrimento_lista.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.listbox = Gtk.ListBox()
            self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
            self.listbox.set_activate_on_single_click(False)
            accessibile = self.listbox.get_accessible()
            if accessibile is not None:
                accessibile.set_role(Atk.Role.MENU)
            self.listbox.connect("row-activated", self._riga_attivata)
            scorrimento_lista.add(self.listbox)
            self.listbox.set_focus_vadjustment(scorrimento_lista.get_vadjustment())
            self.stack.add_named(scorrimento_lista, VISTA_LISTA)
            scorrimento_testo = Gtk.ScrolledWindow()
            scorrimento_testo.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.textview = Gtk.TextView()
            self.textview.set_editable(False)
            self.textview.set_cursor_visible(True)
            self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            self.textview.set_left_margin(8)
            self.textview.set_right_margin(8)
            self.textview.set_pixels_below_lines(4)
            scorrimento_testo.add(self.textview)
            self.stack.add_named(scorrimento_testo, VISTA_TESTO)
            self.box.pack_start(self.stack, True, True, 0)
        except Exception as ex:
            scrivi_log("MainWindow._crea_interfaccia", ex)

    def _avvia_servizi(self):
        try:
            if self.podcast_downloads is not None:
                self.podcast_downloads.avvia()
            if self.podcast_notifier is not None:
                self.podcast_notifier.avvia()
            if self.news_updater is not None:
                self.news_updater.avvia()
            if self.librivox_downloads is not None:
                self.librivox_downloads.avvia()
            if self.agenda_notifier is not None:
                self.agenda_notifier.avvia()
        except Exception as ex:
            scrivi_log("MainWindow._avvia_servizi", ex)

    def _alla_distruzione(self, widget):
        try:
            if self.podcast_notifier is not None:
                self.podcast_notifier.ferma()
            if self.news_updater is not None:
                self.news_updater.ferma()
            if self.podcast_downloads is not None:
                self.podcast_downloads.ferma()
            if self.librivox_downloads is not None:
                self.librivox_downloads.ferma()
            if self.librivox_catalog is not None:
                self.librivox_catalog.ferma()
            if self.agenda_notifier is not None:
                self.agenda_notifier.ferma()
            if self.area_video is not None:
                self.area_video.scollega()
            if self.engine is not None:
                self.engine.stop()
                self.engine.terminate()
        except Exception as ex:
            scrivi_log("MainWindow._alla_distruzione", ex)

    def show_main_menu(self):
        try:
            self.history.clear()
            self._navigazione += 1
            items = [
                ("Radio", self.open_radio_menu, None),
                ("Podcast", self.open_podcast_menu, None),
                ("Notizie", self.open_news_menu, None),
                ("YouTube", self.open_youtube_menu, None),
                ("LibriVox", self.open_librivox_menu, None),
                ("Wikipedia", self.open_wikipedia_menu, None),
                ("Agenda", self.open_agenda_menu, None),
                ("Rubrica", self.open_rubrica_menu, None),
                (TITOLO_CENTRO_CONTROLLO, self.open_control_center, None),
                ("Impostazioni", self.open_settings_menu, None),
                ("Esci", self.confirm_exit, None),
            ]
            self._costruisci(TITOLO_PRINCIPALE, items, self._risolvi(items), None)
        except Exception as ex:
            scrivi_log("MainWindow.show_main_menu", ex)

    def _modulo_non_disponibile(self, nome):
        self.mostra_messaggio(f"Il modulo {nome} non è disponibile.", "I dettagli sono nel file di log.")

    def open_radio_menu(self):
        try:
            if self.radio_view is None:
                self._modulo_non_disponibile("Radio")
                return
            self.push_menu("Menu Radio", self.radio_view.get_menu_items)
        except Exception as ex:
            scrivi_log("MainWindow.open_radio_menu", ex)

    def open_podcast_menu(self):
        try:
            if self.podcast_view is None:
                self._modulo_non_disponibile("Podcast")
                return
            self.push_menu("Menu Podcast", self.podcast_view.get_menu_items)
        except Exception as ex:
            scrivi_log("MainWindow.open_podcast_menu", ex)

    def open_news_menu(self):
        try:
            if self.news_view is None:
                self._modulo_non_disponibile("Notizie")
                return
            self.push_menu("Menu Notizie", self.news_view.get_menu_items)
        except Exception as ex:
            scrivi_log("MainWindow.open_news_menu", ex)

    def open_youtube_menu(self):
        try:
            if self.youtube_view is None:
                self._modulo_non_disponibile("YouTube")
                return
            self.push_menu("Menu YouTube", self.youtube_view.get_menu_items)
        except Exception as ex:
            scrivi_log("MainWindow.open_youtube_menu", ex)

    def open_librivox_menu(self):
        try:
            if self.librivox_view is None:
                self._modulo_non_disponibile("LibriVox")
                return
            if self.push_menu("Menu LibriVox", self.librivox_view.get_menu_items):
                self.librivox_view.proponi_catalogo()
        except Exception as ex:
            scrivi_log("MainWindow.open_librivox_menu", ex)

    def open_wikipedia_menu(self):
        try:
            if self.wikipedia_view is None:
                self._modulo_non_disponibile("Wikipedia")
                return
            self.push_menu("Menu Wikipedia", self.wikipedia_view.get_menu_items)
        except Exception as ex:
            scrivi_log("MainWindow.open_wikipedia_menu", ex)

    def open_agenda_menu(self):
        try:
            if self.agenda_view is None:
                self._modulo_non_disponibile("Agenda")
                return
            self.push_menu("Menu Agenda", self.agenda_view.get_menu_items)
        except Exception as ex:
            scrivi_log("MainWindow.open_agenda_menu", ex)

    def open_rubrica_menu(self):
        try:
            if self.rubrica_view is None:
                self._modulo_non_disponibile("Rubrica")
                return
            self.push_menu("Menu Rubrica", self.rubrica_view.get_menu_items)
        except Exception as ex:
            scrivi_log("MainWindow.open_rubrica_menu", ex)

    def open_appuntamenti_di_oggi(self):
        try:
            if self.agenda_view is None:
                self._modulo_non_disponibile("Agenda")
                return
            self.nascondi_avviso_agenda()
            self.agenda_view.apri_notificate()
        except Exception as ex:
            scrivi_log("MainWindow.open_appuntamenti_di_oggi", ex)

    def open_settings_menu(self):
        try:
            if self.settings_view is None:
                self._modulo_non_disponibile("Impostazioni")
                return
            self.push_menu("Menu Impostazioni", self.settings_view.get_menu_items)
        except Exception as ex:
            scrivi_log("MainWindow.open_settings_menu", ex)

    def open_control_center(self):
        try:
            if self.control_center_view is None:
                self._modulo_non_disponibile(TITOLO_CENTRO_CONTROLLO)
                return
            sorgente = self.control_center_view.get_menu_items
            if self.titolo_corrente() == TITOLO_CENTRO_CONTROLLO and not self.in_pagina():
                self.menu_positions[TITOLO_CENTRO_CONTROLLO] = self.get_current_selected_index()
                self._costruisci(TITOLO_CENTRO_CONTROLLO, sorgente, self._risolvi(sorgente), None)
                return
            self.push_menu(TITOLO_CENTRO_CONTROLLO, sorgente)
        except Exception as ex:
            scrivi_log("MainWindow.open_control_center", ex)

    def _identificativo_area_video(self):
        try:
            if self.area_video is None or GdkX11 is None:
                return 0
            if not self.area_video.get_realized():
                self.area_video.realize()
            finestra = self.area_video.get_window()
            if finestra is None or not isinstance(finestra, GdkX11.X11Window):
                return 0
            return int(finestra.get_xid())
        except Exception as ex:
            scrivi_log("MainWindow._identificativo_area_video", ex)
            return 0

    def _collega_area_video(self):
        try:
            if self.engine is None or self.area_video is None:
                return False
            if self.engine.imposta_render(self.area_video.crea_contesto):
                return False
            self.area_video.scollega()
            identificativo = self._identificativo_area_video()
            if identificativo:
                self.engine.imposta_finestra(identificativo)
                return False
            scrivi_log(
                "MainWindow._collega_area_video",
                RuntimeError("video non incastonabile: riproduzione del solo audio, nessuna finestra separata"),
            )
        except Exception as ex:
            scrivi_log("MainWindow._collega_area_video", ex)
        return False

    def _video_cambiato(self, presente):
        try:
            GLib.idle_add(self._aggiorna_area_video, bool(presente))
        except Exception as ex:
            scrivi_log("MainWindow._video_cambiato", ex)

    def _aggiorna_area_video(self, presente):
        try:
            if self.area_video is None:
                return False
            if presente and self.engine is not None and self.engine.ha_finestra_incastonata():
                self.area_video.show()
            else:
                self.area_video.hide()
        except Exception as ex:
            scrivi_log("MainWindow._aggiorna_area_video", ex)
        return False

    def _titolo_player(self):
        try:
            tipo = self.engine.get_kind() if self.engine is not None else ""
            return ETICHETTE_ASCOLTO.get(tipo, TITOLO_ASCOLTO_PREDEFINITO)
        except Exception as ex:
            scrivi_log("MainWindow._titolo_player", ex)
            return TITOLO_ASCOLTO_PREDEFINITO

    def _player_seek_consentito(self):
        try:
            return self.engine is not None and self.engine.get_kind() != "stream"
        except Exception as ex:
            scrivi_log("MainWindow._player_seek_consentito", ex)
            return True

    def _azioni_player(self):
        try:
            azioni = [("Pausa / Riprendi", self._player_toggle_pausa, None)]
            if self.engine is not None and self.engine.has_playlist():
                azioni.append(("Traccia successiva", self._player_successiva, None))
                azioni.append(("Traccia precedente", self._player_precedente, None))
            if self._player_seek_consentito():
                azioni.append(("Vai avanti di 10 secondi", self._player_avanti, None))
                azioni.append(("Vai indietro di 10 secondi", self._player_indietro, None))
            azioni.extend(
                [
                    ("Aumenta volume", self._player_volume_su, None),
                    ("Abbassa volume", self._player_volume_giu, None),
                    ("Interrompi riproduzione", self._player_interrompi, None),
                ]
            )
            return azioni
        except Exception as ex:
            scrivi_log("MainWindow._azioni_player", ex)
            return []

    def _voci_player(self):
        try:
            if self.engine is None:
                return []
            stato = "In riproduzione" if self.engine.is_playing() else "In pausa"
            volume = int(self.engine.get_volume())
            titolo_traccia = self.engine.current_title or ""
            azioni = self._azioni_player()
            etichetta_stato = f"{stato}: {titolo_traccia}" if titolo_traccia else stato
            return [
                (etichetta_stato, lambda: None, azioni),
                (f"Volume: {volume}%", lambda: None, azioni),
            ]
        except Exception as ex:
            scrivi_log("MainWindow._voci_player", ex)
            return []

    def apri_player(self):
        try:
            if self.engine is None or not self.engine.is_loaded():
                self.mostra_messaggio("Nessun ascolto in corso.")
                return
            titolo = self._titolo_player()
            if self.player_screen_active:
                voci = self._risolvi(self._voci_player)
                self._costruisci(titolo, self._voci_player, voci, None, is_player=True)
                return
            self.push_menu(titolo, self._voci_player, is_player=True)
        except Exception as ex:
            scrivi_log("MainWindow.apri_player", ex)

    def _player_toggle_pausa(self):
        try:
            if self.engine is None:
                return
            if self.engine.is_playing():
                self.engine.pause()
                self.mostra_stato("Pausa.")
            else:
                self.engine.resume()
                self.mostra_stato("Riproduzione ripresa.")
        except Exception as ex:
            scrivi_log("MainWindow._player_toggle_pausa", ex)

    def _player_avanti(self):
        try:
            if self.engine is not None and self._player_seek_consentito():
                self.engine.seek_forward()
                self.mostra_stato("Avanti di 10 secondi.")
        except Exception as ex:
            scrivi_log("MainWindow._player_avanti", ex)

    def _player_indietro(self):
        try:
            if self.engine is not None and self._player_seek_consentito():
                self.engine.seek_backward()
                self.mostra_stato("Indietro di 10 secondi.")
        except Exception as ex:
            scrivi_log("MainWindow._player_indietro", ex)

    def _player_volume_su(self):
        try:
            if self.engine is None:
                return
            valore = min(130, self.engine.get_volume() + INCREMENTO_VOLUME)
            self.engine.set_volume(valore)
            self.mostra_stato(f"Volume: {int(valore)}%")
        except Exception as ex:
            scrivi_log("MainWindow._player_volume_su", ex)

    def _player_volume_giu(self):
        try:
            if self.engine is None:
                return
            valore = max(0, self.engine.get_volume() - INCREMENTO_VOLUME)
            self.engine.set_volume(valore)
            self.mostra_stato(f"Volume: {int(valore)}%")
        except Exception as ex:
            scrivi_log("MainWindow._player_volume_giu", ex)

    def _player_successiva(self):
        try:
            if self.engine is not None:
                self.engine.next_track()
        except Exception as ex:
            scrivi_log("MainWindow._player_successiva", ex)

    def _player_precedente(self):
        try:
            if self.engine is not None:
                self.engine.previous_track()
        except Exception as ex:
            scrivi_log("MainWindow._player_precedente", ex)

    def _player_interrompi(self):
        try:
            if self.engine is not None:
                self.engine.stop()
            self.mostra_stato("Riproduzione interrotta.")
            self.go_back()
        except Exception as ex:
            scrivi_log("MainWindow._player_interrompi", ex)

    def open_new_episodes(self):
        try:
            if self.podcast_view is None:
                self._modulo_non_disponibile("Podcast")
                return
            if self.titolo_corrente() == TITOLO_NUOVI_EPISODI and not self.in_pagina():
                self.nascondi_avviso_episodi()
                self.ricarica_menu_corrente()
                return
            self.podcast_view.apri_nuovi_episodi()
        except Exception as ex:
            scrivi_log("MainWindow.open_new_episodes", ex)

    def open_new_news(self):
        try:
            if self.news_view is None:
                self._modulo_non_disponibile("Notizie")
                return
            self.news_view.apri_segnalate()
        except Exception as ex:
            scrivi_log("MainWindow.open_new_news", ex)

    def titolo_corrente(self):
        try:
            return self.label.get_text() if self.label is not None else ""
        except Exception as ex:
            scrivi_log("MainWindow.titolo_corrente", ex)
            return ""

    def in_pagina(self):
        return isinstance(self.current_source, PaginaTesto)

    def get_current_selected_index(self):
        try:
            if self.in_pagina():
                return 0
            selected = self.listbox.get_selected_row()
            if selected:
                return selected.get_index()
            return 0
        except Exception as ex:
            scrivi_log("MainWindow.get_current_selected_index", ex)
            return 0

    def _salva_posizione_pagina(self):
        try:
            if self.in_pagina():
                buffer = self.textview.get_buffer()
                self.current_source.posizione = buffer.get_iter_at_mark(buffer.get_insert()).get_offset()
        except Exception as ex:
            scrivi_log("MainWindow._salva_posizione_pagina", ex)

    def _risolvi(self, sorgente):
        risultato = []
        try:
            if isinstance(sorgente, PaginaTesto):
                return risultato
            voci = sorgente() if callable(sorgente) else sorgente
            for voce in voci or []:
                if not isinstance(voce, (list, tuple)) or not voce:
                    continue
                etichetta = str(voce[0])
                azione = voce[1] if len(voce) > 1 else None
                azioni = voce[2] if len(voce) > 2 else None
                risultato.append((etichetta, azione, azioni))
        except Exception as ex:
            scrivi_log("MainWindow._risolvi", ex)
        return risultato

    def _testo_riga(self, etichetta, indice):
        try:
            if self.selection_enabled and indice in self.selected_indices:
                return f"✓ {etichetta}"
            return etichetta
        except Exception as ex:
            scrivi_log(f"MainWindow._testo_riga ({indice})", ex)
            return etichetta

    def _nome_accessibile_riga(self, etichetta, indice):
        try:
            if not self.selection_enabled:
                return etichetta
            stato = "selezionato" if indice in self.selected_indices else "non selezionato"
            return f"{etichetta}, {stato}"
        except Exception as ex:
            scrivi_log(f"MainWindow._nome_accessibile_riga ({indice})", ex)
            return etichetta

    def _aggiorna_riga(self, indice):
        try:
            if not 0 <= indice < len(self.current_items):
                return
            riga = self.listbox.get_row_at_index(indice)
            if riga is None:
                return
            etichetta = self.current_items[indice][0]
            figlio = riga.get_child()
            if isinstance(figlio, Gtk.Label):
                figlio.set_text(self._testo_riga(etichetta, indice))
            accessibile_riga = riga.get_accessible()
            if accessibile_riga is not None:
                accessibile_riga.set_name(self._nome_accessibile_riga(etichetta, indice))
        except Exception as ex:
            scrivi_log(f"MainWindow._aggiorna_riga ({indice})", ex)

    def get_selected_indices(self):
        try:
            return sorted(self.selected_indices)
        except Exception as ex:
            scrivi_log("MainWindow.get_selected_indices", ex)
            return []

    def _alterna_selezione(self, indice):
        try:
            if not self.selection_enabled or not 0 <= indice < len(self.current_items):
                return
            etichetta = self.current_items[indice][0]
            if indice in self.selected_indices:
                self.selected_indices.discard(indice)
                stato = "non più selezionato"
            else:
                self.selected_indices.add(indice)
                stato = "selezionato"
            self._aggiorna_riga(indice)
            totale = len(self.selected_indices)
            if totale == 1:
                self.annuncia(f"{etichetta}, {stato}. 1 video selezionato.")
            elif totale > 1:
                self.annuncia(f"{etichetta}, {stato}. {totale} video selezionati.")
            else:
                self.annuncia(f"{etichetta}, {stato}.")
        except Exception as ex:
            scrivi_log(f"MainWindow._alterna_selezione ({indice})", ex)

    def _costruisci(self, titolo, sorgente, voci, messaggio_vuoto, selezione=False, is_player=False):
        try:
            if isinstance(sorgente, PaginaTesto):
                self._costruisci_pagina(titolo, sorgente)
                return
            self.label.set_text(titolo)
            self.set_title(f"{titolo} - {NOME_PROGRAMMA}")
            accessibile_lista = self.listbox.get_accessible()
            if accessibile_lista is not None:
                accessibile_lista.set_role(Atk.Role.PANEL if is_player else Atk.Role.MENU)
                accessibile_lista.set_name(titolo)
            for figlio in self.listbox.get_children():
                self.listbox.remove(figlio)
                figlio.destroy()
            self.current_source = sorgente
            self.current_items = voci
            self.current_empty_message = messaggio_vuoto
            self.selection_enabled = selezione
            self.selected_indices = set()
            self.player_screen_active = is_player
            for indice, (etichetta, _azione, _azioni) in enumerate(voci):
                riga = Gtk.ListBoxRow()
                testo = Gtk.Label(label=self._testo_riga(etichetta, indice))
                testo.set_xalign(0)
                testo.set_line_wrap(True)
                riga.add(testo)
                accessibile_riga = riga.get_accessible()
                if accessibile_riga is not None:
                    accessibile_riga.set_role(Atk.Role.LABEL if is_player else Atk.Role.MENU_ITEM)
                    accessibile_riga.set_name(self._nome_accessibile_riga(etichetta, indice))
                self.listbox.add(riga)
            self.show_all()
            self.stack.set_visible_child_name(VISTA_LISTA)
            indice = self.menu_positions.get(titolo, 0)
            if indice < 0 or indice >= len(voci):
                indice = 0
            riga = self.listbox.get_row_at_index(indice)
            if riga:
                self.listbox.select_row(riga)
                riga.grab_focus()
        except Exception as ex:
            scrivi_log(f"MainWindow._costruisci ({titolo})", ex)

    def _costruisci_pagina(self, titolo, pagina):
        try:
            self.label.set_text(titolo)
            self.set_title(f"{titolo} - {NOME_PROGRAMMA}")
            self.current_source = pagina
            self.current_items = []
            self.current_empty_message = None
            buffer = self.textview.get_buffer()
            buffer.set_text(pagina.testo or "")
            accessibile = self.textview.get_accessible()
            if accessibile is not None:
                accessibile.set_name(titolo)
            self.show_all()
            self.stack.set_visible_child_name(VISTA_TESTO)
            posizione = max(0, min(int(pagina.posizione or 0), buffer.get_char_count()))
            buffer.place_cursor(buffer.get_iter_at_offset(posizione))
            self.textview.grab_focus()
            GLib.idle_add(self._scorri_al_cursore)
        except Exception as ex:
            scrivi_log(f"MainWindow._costruisci_pagina ({titolo})", ex)

    def _scorri_al_cursore(self):
        try:
            if self.in_pagina():
                buffer = self.textview.get_buffer()
                self.textview.scroll_to_mark(buffer.get_insert(), 0.1, False, 0, 0)
        except Exception as ex:
            scrivi_log("MainWindow._scorri_al_cursore", ex)
        return False

    def build_menu(self, title, items):
        try:
            self._costruisci(title, items, self._risolvi(items), None)
        except Exception as ex:
            scrivi_log(f"MainWindow.build_menu ({title})", ex)

    def push_menu(self, title, items, messaggio_vuoto=None, selezione=False, is_player=False):
        try:
            voci = self._risolvi(items)
            if not isinstance(items, PaginaTesto) and not voci and messaggio_vuoto:
                self.mostra_messaggio(messaggio_vuoto)
                return False
            self._salva_posizione_pagina()
            titolo_corrente = self.titolo_corrente()
            indice = self.get_current_selected_index()
            self.menu_positions[titolo_corrente] = indice
            self.history.append(
                (
                    titolo_corrente,
                    self.current_source,
                    indice,
                    self.current_empty_message,
                    self.selection_enabled,
                    self.player_screen_active,
                )
            )
            self._navigazione += 1
            self._costruisci(title, items, voci, messaggio_vuoto, selezione=selezione, is_player=is_player)
            return True
        except Exception as ex:
            scrivi_log(f"MainWindow.push_menu ({title})", ex)
            return False

    def sostituisci_menu(self, titolo, sorgente, indice=0, messaggio_vuoto=None):
        try:
            voci = self._risolvi(sorgente)
            self.menu_positions[titolo] = max(0, int(indice or 0))
            self._navigazione += 1
            self._costruisci(titolo, sorgente, voci, messaggio_vuoto)
            return True
        except Exception as ex:
            scrivi_log(f"MainWindow.sostituisci_menu ({titolo})", ex)
            return False

    def mostra_pagina(self, pagina):
        try:
            if pagina is None:
                return False
            return self.push_menu(pagina.titolo, pagina)
        except Exception as ex:
            scrivi_log("MainWindow.mostra_pagina", ex)
            return False

    def go_back(self):
        try:
            if not self.history:
                self.confirm_exit()
                return
            self._salva_posizione_pagina()
            self.menu_positions[self.titolo_corrente()] = self.get_current_selected_index()
            self._navigazione += 1
            messaggio = None
            while self.history:
                titolo, sorgente, indice, vuoto, selezione, is_player = self.history.pop()
                self.menu_positions[titolo] = indice
                voci = self._risolvi(sorgente)
                if isinstance(sorgente, PaginaTesto) or voci or not vuoto or not self.history:
                    self._costruisci(titolo, sorgente, voci, vuoto, selezione=selezione, is_player=is_player)
                    break
                messaggio = vuoto
            if messaggio:
                self.mostra_messaggio(messaggio)
        except Exception as ex:
            scrivi_log("MainWindow.go_back", ex)

    def ricarica_menu_corrente(self, annuncia_vuoto=True):
        try:
            if self.in_pagina():
                buffer = self.textview.get_buffer()
                attuale = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
                if attuale != self.current_source.testo:
                    self._costruisci_pagina(self.titolo_corrente(), self.current_source)
                return
            titolo = self.titolo_corrente()
            voci = self._risolvi(self.current_source)
            if not voci and self.current_empty_message and self.history:
                messaggio = self.current_empty_message
                self.go_back()
                if annuncia_vuoto:
                    self.mostra_messaggio(messaggio)
                return
            if [voce[0] for voce in voci] == [voce[0] for voce in self.current_items]:
                self.current_items = voci
                return
            self.menu_positions[titolo] = self.get_current_selected_index()
            self._costruisci(
                titolo,
                self.current_source,
                voci,
                self.current_empty_message,
                selezione=self.selection_enabled,
                is_player=self.player_screen_active,
            )
        except Exception as ex:
            scrivi_log("MainWindow.ricarica_menu_corrente", ex)

    def _attiva(self, indice):
        try:
            self.menu_positions[self.titolo_corrente()] = indice
            if 0 <= indice < len(self.current_items):
                azione = self.current_items[indice][1]
                if callable(azione):
                    azione()
        except Exception as ex:
            scrivi_log(f"MainWindow._attiva ({indice})", ex)

    def _apri_menu_azioni(self, etichetta, azioni):
        try:
            voci = self._risolvi(azioni)
            if not voci:
                return
            avvolte = [(testo, partial(self._esegui_azione, azione), None) for testo, azione, _altro in voci]
            self.push_menu(f"Azioni per {etichetta}", avvolte)
        except Exception as ex:
            scrivi_log(f"MainWindow._apri_menu_azioni ({etichetta})", ex)

    def _apri_azioni(self, indice):
        try:
            self.menu_positions[self.titolo_corrente()] = indice
            if not 0 <= indice < len(self.current_items):
                return
            etichetta, _azione, azioni = self.current_items[indice]
            self._apri_menu_azioni(etichetta, azioni)
        except Exception as ex:
            scrivi_log(f"MainWindow._apri_azioni ({indice})", ex)

    def _esegui_azione(self, azione):
        try:
            self.go_back()
            token = self._navigazione
            if callable(azione):
                azione()
            if token == self._navigazione:
                self.ricarica_menu_corrente()
        except Exception as ex:
            scrivi_log("MainWindow._esegui_azione", ex)

    def _riga_attivata(self, listbox, riga):
        try:
            if riga is not None:
                self._attiva(riga.get_index())
        except Exception as ex:
            scrivi_log("MainWindow._riga_attivata", ex)

    def _spostamento_ciclico(self, verso_alto):
        try:
            if self.listbox is None or self.in_pagina():
                return False
            righe = self.listbox.get_children()
            totale = len(righe)
            if totale == 0:
                return False
            fuoco = self.get_focus()
            if isinstance(fuoco, Gtk.ListBoxRow) and fuoco.get_parent() is self.listbox:
                indice = fuoco.get_index()
            elif fuoco is None or fuoco is self.listbox:
                selezionata = self.listbox.get_selected_row()
                indice = selezionata.get_index() if selezionata is not None else -1
            else:
                return False
            if verso_alto:
                if indice > 0:
                    return False
                destinazione = totale - 1
            else:
                if 0 <= indice < totale - 1:
                    return False
                destinazione = 0
            riga = self.listbox.get_row_at_index(destinazione)
            if riga is None:
                return False
            self.listbox.select_row(riga)
            riga.grab_focus()
            return True
        except Exception as ex:
            scrivi_log(f"MainWindow._spostamento_ciclico ({verso_alto})", ex)
            return False

    def on_key_press(self, widget, event):
        try:
            keyname = Gdk.keyval_name(event.keyval)
            if keyname == "F6":
                self.open_control_center()
                return True
            if keyname == "F7":
                self.open_new_episodes()
                return True
            if keyname == "F8":
                self.open_new_news()
                return True
            if keyname == "F9":
                self.open_appuntamenti_di_oggi()
                return True
            if keyname in TASTI_AVANTI_INDIETRO and self.player_screen_active and not self.in_pagina():
                if self.engine is not None and self.engine.is_loaded() and self._player_seek_consentito():
                    self._player_avanti() if keyname == "Right" else self._player_indietro()
                    return True
                return False
            if keyname in TASTI_VOLUME and self.player_screen_active and not self.in_pagina():
                if self.engine is not None and self.engine.is_loaded():
                    self._player_volume_su() if keyname == "Up" else self._player_volume_giu()
                    self.ricarica_menu_corrente(annuncia_vuoto=False)
                    return True
                return False
            if keyname in TASTI_SU + TASTI_GIU and not self.in_pagina():
                modificatori = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.MOD1_MASK
                if not event.state & modificatori and self._spostamento_ciclico(keyname in TASTI_SU):
                    return True
                return False
            if keyname in TASTI_TRACCIA and event.state & Gdk.ModifierType.CONTROL_MASK and self.player_screen_active:
                if self.engine is not None and self.engine.is_loaded():
                    if keyname.lower() == "f":
                        self._player_successiva()
                    else:
                        self._player_precedente()
                    return True
                return False
            if keyname == "space" and event.state & Gdk.ModifierType.SHIFT_MASK:
                if self.selection_enabled and not self.in_pagina():
                    selected = self.listbox.get_selected_row()
                    if selected:
                        self._alterna_selezione(selected.get_index())
                    return True
                return False
            if keyname in TASTI_INVIO:
                if self.in_pagina():
                    return True
                selected = self.listbox.get_selected_row()
                if selected:
                    self._attiva(selected.get_index())
                return True
            if keyname in TASTI_INDIETRO:
                self.go_back()
                return True
            if keyname in TASTI_AZIONI:
                if self.in_pagina():
                    self._salva_posizione_pagina()
                    self._apri_menu_azioni(self.titolo_corrente(), self.current_source.azioni)
                    return True
                selected = self.listbox.get_selected_row()
                if selected:
                    self._apri_azioni(selected.get_index())
                return True
            return False
        except Exception as ex:
            scrivi_log("MainWindow.on_key_press", ex)
            return False

    def carica_in_background(
        self,
        titolo,
        lavoro,
        crea_voci,
        messaggio_vuoto="Nessun risultato trovato.",
        messaggio_errore="Impossibile caricare i dati. Riprovare più tardi.",
        titolo_risultato=None,
        selezione=False,
    ):
        try:
            if not self.push_menu(titolo, [(TESTO_CARICAMENTO, None, None)]):
                return
            token = self._navigazione
            threading.Thread(
                target=self._esegui_lavoro,
                args=(token, titolo, lavoro, crea_voci, messaggio_vuoto, messaggio_errore, titolo_risultato or titolo, selezione),
                name="CaricamentoMenu",
                daemon=True,
            ).start()
        except Exception as ex:
            scrivi_log(f"MainWindow.carica_in_background ({titolo})", ex)

    def _esegui_lavoro(self, token, titolo, lavoro, crea_voci, messaggio_vuoto, messaggio_errore, titolo_risultato, selezione):
        risultato = None
        errore = None
        try:
            risultato = lavoro()
        except Exception as ex:
            scrivi_log(f"MainWindow._esegui_lavoro ({titolo})", ex)
            errore = ex
        try:
            GLib.idle_add(
                self._lavoro_concluso,
                token,
                titolo_risultato,
                risultato,
                errore,
                crea_voci,
                messaggio_vuoto,
                messaggio_errore,
                selezione,
            )
        except Exception as ex:
            scrivi_log(f"MainWindow._esegui_lavoro consegna ({titolo})", ex)

    def _testo_errore(self, messaggio_errore, errore):
        try:
            if callable(messaggio_errore):
                return messaggio_errore(errore)
            return messaggio_errore
        except Exception as ex:
            scrivi_log("MainWindow._testo_errore", ex)
            return "Impossibile caricare i dati. Riprovare più tardi."

    def _lavoro_concluso(self, token, titolo, risultato, errore, crea_voci, messaggio_vuoto, messaggio_errore, selezione):
        try:
            if token != self._navigazione:
                return False
            if errore is not None:
                self.go_back()
                self.mostra_messaggio(self._testo_errore(messaggio_errore, errore))
                return False
            try:
                sorgente = crea_voci(risultato)
            except Exception as ex:
                scrivi_log(f"MainWindow._lavoro_concluso creazione voci ({titolo})", ex)
                self.go_back()
                self.mostra_messaggio(self._testo_errore(messaggio_errore, ex))
                return False
            if isinstance(sorgente, PaginaTesto):
                self._costruisci(titolo, sorgente, [], None)
                return False
            voci = self._risolvi(sorgente)
            if not voci:
                self.go_back()
                self.mostra_messaggio(messaggio_vuoto)
                return False
            if callable(sorgente):
                self._costruisci(titolo, sorgente, voci, messaggio_vuoto, selezione=selezione)
            else:
                self._costruisci(titolo, voci, voci, None, selezione=selezione)
        except Exception as ex:
            scrivi_log(f"MainWindow._lavoro_concluso ({titolo})", ex)
        return False

    def _collega_escape(self, dialogo, risposta):
        try:
            dialogo.connect("key-press-event", self._tasto_nel_dialogo, risposta)
        except Exception as ex:
            scrivi_log("MainWindow._collega_escape", ex)

    def _tasto_nel_dialogo(self, dialogo, evento, risposta):
        try:
            if Gdk.keyval_name(evento.keyval) == "Escape":
                dialogo.response(risposta)
                return True
            return False
        except Exception as ex:
            scrivi_log("MainWindow._tasto_nel_dialogo", ex)
            return False

    def mostra_messaggio(self, testo, dettaglio=""):
        dialogo = None
        try:
            dialogo = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.CLOSE,
                text=testo,
            )
            dialogo.set_title(NOME_PROGRAMMA)
            if dettaglio:
                dialogo.format_secondary_text(dettaglio)
            self._collega_escape(dialogo, Gtk.ResponseType.CLOSE)
            dialogo.run()
        except Exception as ex:
            scrivi_log(f"MainWindow.mostra_messaggio ({testo})", ex)
        finally:
            try:
                if dialogo is not None:
                    dialogo.destroy()
            except Exception as ex:
                scrivi_log("MainWindow.mostra_messaggio distruzione", ex)

    def chiedi_conferma(self, domanda, dettaglio=""):
        dialogo = None
        try:
            dialogo = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text=domanda,
            )
            dialogo.set_title(NOME_PROGRAMMA)
            if dettaglio:
                dialogo.format_secondary_text(dettaglio)
            self._collega_escape(dialogo, Gtk.ResponseType.NO)
            return dialogo.run() == Gtk.ResponseType.YES
        except Exception as ex:
            scrivi_log(f"MainWindow.chiedi_conferma ({domanda})", ex)
            return False
        finally:
            try:
                if dialogo is not None:
                    dialogo.destroy()
            except Exception as ex:
                scrivi_log("MainWindow.chiedi_conferma distruzione", ex)

    def chiedi_scelta(self, domanda, opzioni, dettaglio=""):
        dialogo = None
        try:
            dialogo = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text=domanda,
            )
            dialogo.set_title(NOME_PROGRAMMA)
            if dettaglio:
                dialogo.format_secondary_text(dettaglio)
            for posizione, testo in enumerate(opzioni):
                dialogo.add_button(testo, posizione)
            dialogo.add_button("Annulla", Gtk.ResponseType.CANCEL)
            if opzioni:
                dialogo.set_default_response(0)
            self._collega_escape(dialogo, Gtk.ResponseType.CANCEL)
            risposta = dialogo.run()
            return risposta if isinstance(risposta, int) and 0 <= risposta < len(opzioni) else -1
        except Exception as ex:
            scrivi_log(f"MainWindow.chiedi_scelta ({domanda})", ex)
            return -1
        finally:
            try:
                if dialogo is not None:
                    dialogo.destroy()
            except Exception as ex:
                scrivi_log("MainWindow.chiedi_scelta distruzione", ex)

    def chiedi_modulo(self, titolo, campi, convalida=None, testo_conferma="Salva", campo_iniziale=None):
        try:
            return chiedi_modulo(self, titolo, campi, convalida, testo_conferma, campo_iniziale)
        except Exception as ex:
            scrivi_log(f"MainWindow.chiedi_modulo ({titolo})", ex)
            return None

    def apri_azioni(self, etichetta, azioni):
        try:
            self._apri_menu_azioni(etichetta, azioni)
        except Exception as ex:
            scrivi_log(f"MainWindow.apri_azioni ({etichetta})", ex)

    def chiedi_testo(self, titolo, domanda, testo_iniziale=""):
        dialogo = None
        try:
            dialogo = Gtk.Dialog(title=titolo, transient_for=self, modal=True)
            dialogo.add_button("Annulla", Gtk.ResponseType.CANCEL)
            dialogo.add_button("Conferma", Gtk.ResponseType.OK)
            dialogo.set_default_response(Gtk.ResponseType.OK)
            area = dialogo.get_content_area()
            area.set_spacing(6)
            area.set_border_width(10)
            etichetta = Gtk.Label(label=domanda)
            etichetta.set_xalign(0)
            campo = Gtk.Entry()
            campo.set_text(testo_iniziale or "")
            campo.set_activates_default(True)
            etichetta.set_mnemonic_widget(campo)
            accessibile = campo.get_accessible()
            if accessibile is not None:
                accessibile.set_name(domanda)
            area.pack_start(etichetta, False, False, 0)
            area.pack_start(campo, False, False, 0)
            self._collega_escape(dialogo, Gtk.ResponseType.CANCEL)
            dialogo.show_all()
            campo.grab_focus()
            risposta = dialogo.run()
            testo = " ".join(campo.get_text().split())
            if risposta == Gtk.ResponseType.OK and testo:
                return testo
            return None
        except Exception as ex:
            scrivi_log(f"MainWindow.chiedi_testo ({titolo})", ex)
            return None
        finally:
            try:
                if dialogo is not None:
                    dialogo.destroy()
            except Exception as ex:
                scrivi_log("MainWindow.chiedi_testo distruzione", ex)

    def apri_nel_browser(self, indirizzo):
        try:
            if not indirizzo:
                return False
            try:
                Gio.AppInfo.launch_default_for_uri(indirizzo, None)
                return True
            except Exception as ex:
                scrivi_log(f"MainWindow.apri_nel_browser: apertura predefinita non riuscita ({indirizzo})", ex)
            programma = shutil.which("xdg-open")
            if programma:
                subprocess.Popen(
                    [programma, indirizzo],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True
            self.mostra_messaggio("Impossibile aprire il browser.")
            return False
        except Exception as ex:
            scrivi_log(f"MainWindow.apri_nel_browser ({indirizzo})", ex)
            return False

    def copia_negli_appunti(self, testo):
        try:
            appunti = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            appunti.set_text(testo or "", -1)
            appunti.store()
            return True
        except Exception as ex:
            scrivi_log("MainWindow.copia_negli_appunti", ex)
            return False

    def annuncia(self, testo):
        try:
            if not testo or not self._annunci_disponibili or self.listbox is None:
                return
            widget = self.textview if self.in_pagina() else self.listbox
            accessibile = widget.get_accessible()
            if accessibile is not None:
                accessibile.emit("announcement", testo)
        except Exception as ex:
            scrivi_log("MainWindow.annuncia", ex)

    def _mostra_avviso(self, etichetta, testo):
        try:
            if etichetta is None:
                return
            etichetta.hide()
            etichetta.set_text(testo)
            accessibile = etichetta.get_accessible()
            if accessibile is not None:
                accessibile.set_name(testo)
            etichetta.show()
            self.annuncia(testo)
        except Exception as ex:
            scrivi_log("MainWindow._mostra_avviso", ex)

    def mostra_stato(self, testo):
        try:
            if self._timer_stato:
                GLib.source_remove(self._timer_stato)
                self._timer_stato = 0
            self._mostra_avviso(self.avviso_stato, testo)
            self._timer_stato = GLib.timeout_add_seconds(SECONDI_AVVISO_STATO, self._nascondi_stato)
        except Exception as ex:
            scrivi_log(f"MainWindow.mostra_stato ({testo})", ex)

    def _nascondi_stato(self):
        try:
            self._timer_stato = 0
            if self.avviso_stato is not None:
                self.avviso_stato.hide()
        except Exception as ex:
            scrivi_log("MainWindow._nascondi_stato", ex)
        return False

    def nascondi_avviso_episodi(self):
        try:
            if self.avviso_episodi is not None:
                self.avviso_episodi.hide()
        except Exception as ex:
            scrivi_log("MainWindow.nascondi_avviso_episodi", ex)

    def nascondi_avviso_agenda(self):
        try:
            if self.avviso_agenda is not None:
                self.avviso_agenda.hide()
        except Exception as ex:
            scrivi_log("MainWindow.nascondi_avviso_agenda", ex)

    def nascondi_avviso_notizie(self):
        try:
            if self.avviso_notizie is not None:
                self.avviso_notizie.hide()
        except Exception as ex:
            scrivi_log("MainWindow.nascondi_avviso_notizie", ex)

    def _notifiche_attive(self, tipo):
        try:
            if self.impostazioni is None:
                return True
            if tipo == "podcast":
                return self.impostazioni.notifiche_podcast()
            if tipo == "notizie":
                return self.impostazioni.notifiche_notizie()
            if tipo == "agenda":
                return self.impostazioni.notifiche_agenda()
            return True
        except Exception as ex:
            scrivi_log(f"MainWindow._notifiche_attive ({tipo})", ex)
            return True

    def notifica_nuovi_episodi(self, episodi):
        try:
            if not episodi or not self._notifiche_attive("podcast"):
                return
            if len(episodi) == 1:
                episodio = episodi[0]
                testo = f"Nuovo episodio di {episodio.podcast_name}: {episodio.title}. Premi F7 per aprire i nuovi episodi."
            else:
                podcast = {episodio.podcast_name for episodio in episodi}
                testo = (
                    f"{len(episodi)} nuovi episodi da {len(podcast)} podcast. "
                    "Premi F7 per aprire i nuovi episodi."
                )
            self._mostra_avviso(self.avviso_episodi, testo)
            self._notifica_desktop(ID_NOTIFICA_EPISODI, "Nuovi episodi podcast", testo)
        except Exception as ex:
            scrivi_log("MainWindow.notifica_nuovi_episodi", ex)

    def notifica_nuove_notizie(self, articoli):
        try:
            if not articoli or not self._notifiche_attive("notizie"):
                return
            if len(articoli) == 1:
                articolo = articoli[0]
                testo = f"Nuova notizia da {articolo.source_name}: {articolo.title}. Premi F8 per aprire le notizie segnalate."
            else:
                conteggi = {}
                for articolo in articoli:
                    nome = articolo.category or articolo.source_name
                    conteggi[nome] = conteggi.get(nome, 0) + 1
                dettaglio = ", ".join(f"{nome} {numero}" for nome, numero in sorted(conteggi.items()))
                testo = f"{len(articoli)} nuove notizie: {dettaglio}. Premi F8 per aprire le notizie segnalate."
            self._mostra_avviso(self.avviso_notizie, testo)
            self._notifica_desktop(ID_NOTIFICA_NOTIZIE, "Nuove notizie", testo)
        except Exception as ex:
            scrivi_log("MainWindow.notifica_nuove_notizie", ex)

    def _testo_appuntamento(self, occorrenza, tipo):
        try:
            evento = occorrenza.evento
            titolo = evento.titolo or "Appuntamento senza titolo"
            luogo = f", presso {evento.luogo}" if evento.luogo else ""
            giorno = occorrenza.inizio.date()
            if evento.tutto_il_giorno:
                if tipo == TIPO_AVVISO:
                    return f"{data_estesa(giorno)[:1].upper()}{data_estesa(giorno)[1:]}: {titolo}{luogo}"
                return f"Oggi: {titolo}{luogo}"
            orario = ora_breve(occorrenza.inizio.time())
            if tipo == TIPO_AVVISO:
                minuti = max(1, int((occorrenza.inizio - datetime.now()).total_seconds() // 60) + 1)
                if giorno == date.today():
                    quando = f"tra {minuti} minuti, alle {orario}" if minuti < 60 else f"alle {orario}"
                else:
                    quando = f"{data_estesa(giorno)} alle {orario}"
                return f"Promemoria: {titolo}{luogo}, {quando}"
            return f"Adesso: {titolo}{luogo}, alle {orario}"
        except Exception as ex:
            scrivi_log("MainWindow._testo_appuntamento", ex)
            return str(getattr(occorrenza.evento, "titolo", "Appuntamento"))

    def notifica_appuntamenti(self, elenco):
        try:
            if not elenco or not self._notifiche_attive("agenda"):
                return
            frasi = [self._testo_appuntamento(occorrenza, tipo) for occorrenza, tipo in elenco]
            testo = ". ".join(frasi) + ". Premi F9 per aprire gli appuntamenti di oggi."
            self._mostra_avviso(self.avviso_agenda, testo)
            titolo = "Appuntamento" if len(elenco) == 1 else f"{len(elenco)} appuntamenti"
            self._notifica_desktop(ID_NOTIFICA_AGENDA, titolo, testo)
        except Exception as ex:
            scrivi_log("MainWindow.notifica_appuntamenti", ex)

    def _notifica_desktop(self, identificativo, titolo, testo):
        try:
            applicazione = self.get_application()
            if applicazione is not None and applicazione.get_application_id() and applicazione.get_is_registered():
                notifica = Gio.Notification.new(titolo)
                notifica.set_body(testo)
                applicazione.send_notification(identificativo, notifica)
                return
            programma = shutil.which("notify-send")
            if programma:
                subprocess.Popen(
                    [programma, "-a", NOME_PROGRAMMA, titolo, testo],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
        except Exception as ex:
            scrivi_log("MainWindow._notifica_desktop", ex)

    def _download_completato(self, episodio):
        try:
            if self.titolo_corrente() in ("Download in corso", "Episodi scaricati") and not self.in_pagina():
                self.ricarica_menu_corrente(annuncia_vuoto=False)
            self.mostra_stato(f"Download completato: {episodio.title}")
        except Exception as ex:
            scrivi_log("MainWindow._download_completato", ex)

    def _download_fallito(self, episodio):
        try:
            if self.titolo_corrente() == "Download in corso" and not self.in_pagina():
                self.ricarica_menu_corrente(annuncia_vuoto=False)
            self.mostra_stato(f"Download non riuscito: {episodio.title}")
        except Exception as ex:
            scrivi_log("MainWindow._download_fallito", ex)

    def _audiolibro_scaricato(self, libro):
        try:
            if self.librivox_view is not None:
                self.librivox_view.download_completato(libro)
        except Exception as ex:
            scrivi_log("MainWindow._audiolibro_scaricato", ex)

    def _audiolibro_non_scaricato(self, libro):
        try:
            if self.librivox_view is not None:
                self.librivox_view.download_fallito(libro)
        except Exception as ex:
            scrivi_log("MainWindow._audiolibro_non_scaricato", ex)

    def _traccia_cambiata(self, indice, titolo):
        try:
            GLib.idle_add(self._annuncia_traccia, indice, titolo)
        except Exception as ex:
            scrivi_log("MainWindow._traccia_cambiata", ex)

    def _posizione_ripristinata(self, secondi):
        try:
            GLib.idle_add(self._annuncia_ripristino, secondi)
        except Exception as ex:
            scrivi_log("MainWindow._posizione_ripristinata", ex)

    def _formatta_tempo(self, secondi):
        try:
            totale = max(0, int(secondi))
            ore, resto = divmod(totale, 3600)
            minuti, secondi_residui = divmod(resto, 60)
            if ore:
                return f"{ore}:{minuti:02d}:{secondi_residui:02d}"
            return f"{minuti}:{secondi_residui:02d}"
        except Exception as ex:
            scrivi_log(f"MainWindow._formatta_tempo ({secondi})", ex)
            return str(secondi)

    def _annuncia_ripristino(self, secondi):
        try:
            self.mostra_stato(f"Ripresa da {self._formatta_tempo(secondi)}.")
        except Exception as ex:
            scrivi_log("MainWindow._annuncia_ripristino", ex)
        return False

    def _annuncia_traccia(self, indice, titolo):
        try:
            if self.librivox_view is not None:
                self.librivox_view.traccia_cambiata(indice)
            self.mostra_stato(f"In riproduzione: {titolo}")
            if self.player_screen_active:
                self.ricarica_menu_corrente(annuncia_vuoto=False)
        except Exception as ex:
            scrivi_log("MainWindow._annuncia_traccia", ex)
        return False

    def confirm_exit(self):
        try:
            if self.chiedi_conferma("Vuoi davvero uscire dall'applicazione?"):
                self.close()
        except Exception as ex:
            scrivi_log("MainWindow.confirm_exit", ex)
