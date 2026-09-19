"""Area grafica in cui mpv disegna il video dentro la finestra del programma.

Usa l'API di render di libmpv con OpenGL, quindi funziona sia su X11 sia su Wayland,
al contrario dell'opzione wid che esiste solo su X11. L'area non prende mai il fuoco
e non riceve tasti: i comandi restano quelli del menu.
"""

import ctypes

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk

from app.core.log import scrivi_log

try:
    import mpv
except Exception as errore_importazione:
    mpv = None
    scrivi_log("video_area: impossibile importare python-mpv", errore_importazione)

# PyOpenGL e' facoltativo: serve solo come ulteriore via per trovare le funzioni OpenGL
# quando ne' EGL ne' GLX rispondono (pacchetto python3-opengl su Debian e Ubuntu).
try:
    from OpenGL import GL as _GL
except Exception:
    _GL = None

try:
    from OpenGL import EGL as _EGL
except Exception:
    _EGL = None

ALTEZZA_MINIMA = 240
GL_DRAW_FRAMEBUFFER_BINDING = 0x8CA6
LIBRERIE_EGL = ("libEGL.so.1", "libEGL.so")
LIBRERIE_GLX = ("libGLX.so.0", "libGL.so.1", "libGL.so")
LIBRERIE_GL = ("libGL.so.1", "libGL.so", "libGLESv2.so.2", "libGLESv2.so")


class _RisolutoreOpenGL:
    """Trova l'indirizzo delle funzioni OpenGL senza dipendere da PyOpenGL."""

    def __init__(self, preferisci_egl):
        self.preferisci_egl = preferisci_egl
        self.egl = self._carica(LIBRERIE_EGL, "eglGetProcAddress")
        self.glx = self._carica(LIBRERIE_GLX, "glXGetProcAddressARB")
        if self.glx is None:
            self.glx = self._carica(LIBRERIE_GLX, "glXGetProcAddress")
        self.simboli = []
        for nome in LIBRERIE_GL:
            try:
                self.simboli.append(ctypes.CDLL(nome))
            except OSError:
                continue

    def _carica(self, nomi, funzione):
        for nome in nomi:
            try:
                libreria = ctypes.CDLL(nome)
                riferimento = getattr(libreria, funzione)
                riferimento.restype = ctypes.c_void_p
                riferimento.argtypes = [ctypes.c_char_p]
                return riferimento
            except (OSError, AttributeError):
                continue
        return None

    def indirizzo(self, nome):
        try:
            if isinstance(nome, str):
                nome = nome.encode("utf-8")
            ordine = [self.egl, self.glx] if self.preferisci_egl else [self.glx, self.egl]
            for funzione in ordine:
                if funzione is None:
                    continue
                valore = funzione(nome)
                if valore:
                    return int(valore)
            etichetta = nome.decode("utf-8", errors="replace")
            for libreria in self.simboli:
                try:
                    return ctypes.cast(getattr(libreria, etichetta), ctypes.c_void_p).value or 0
                except AttributeError:
                    continue
            if _EGL is not None:
                try:
                    valore = _EGL.eglGetProcAddress(etichetta)
                    if valore:
                        return int(ctypes.cast(valore, ctypes.c_void_p).value or 0)
                except Exception as ex:
                    scrivi_log(f"video_area: eglGetProcAddress di PyOpenGL non riuscito ({etichetta})", ex)
            return 0
        except Exception as ex:
            scrivi_log("video_area._RisolutoreOpenGL.indirizzo", ex)
            return 0


def _sessione_wayland():
    try:
        schermo = Gdk.Display.get_default()
        return "wayland" in type(schermo).__name__.lower() if schermo is not None else False
    except Exception as ex:
        scrivi_log("video_area._sessione_wayland", ex)
        return False


class AreaVideo(Gtk.GLArea):
    def __init__(self, altezza=ALTEZZA_MINIMA):
        super().__init__()
        self._contesto = None
        self._proc = None
        self._risolutore = None
        self._leggi_intero = None
        try:
            self.set_size_request(-1, altezza)
            self.set_can_focus(False)
            self.set_has_depth_buffer(False)
            self.set_has_stencil_buffer(False)
            self.set_auto_render(False)
            self.set_no_show_all(True)
            self.connect("render", self._disegna)
            accessibile = self.get_accessible()
            if accessibile is not None:
                accessibile.set_name("Video in riproduzione")
            self.hide()
        except Exception as ex:
            scrivi_log("AreaVideo.__init__", ex)

    def disponibile(self):
        return self._contesto is not None

    def crea_contesto(self, player):
        """Chiamata dal motore: costruisce il contesto di render di libmpv."""
        try:
            if mpv is None or player is None:
                return None
            if not hasattr(mpv, "MpvRenderContext"):
                scrivi_log(
                    "AreaVideo.crea_contesto",
                    RuntimeError("python-mpv troppo vecchio: manca MpvRenderContext"),
                )
                return None
            if not self.get_realized():
                self.realize()
            self.make_current()
            if self.get_error() is not None:
                # Alcuni driver, soprattutto su Wayland, accettano solo OpenGL ES.
                try:
                    self.set_use_es(True)
                    self.unrealize()
                    self.realize()
                    self.make_current()
                except Exception as ex:
                    scrivi_log("AreaVideo.crea_contesto: secondo tentativo con OpenGL ES", ex)
            errore = self.get_error()
            if errore is not None:
                scrivi_log("AreaVideo.crea_contesto", RuntimeError(f"OpenGL non disponibile: {errore.message}"))
                return None
            self._risolutore = _RisolutoreOpenGL(_sessione_wayland())
            self._proc = mpv.MpvGlGetProcAddressFn(self._indirizzo_funzione)
            self._contesto = mpv.MpvRenderContext(
                player,
                "opengl",
                opengl_init_params={"get_proc_address": self._proc},
            )
            self._contesto.update_cb = self._sveglia
            return self._contesto
        except Exception as ex:
            scrivi_log("AreaVideo.crea_contesto", ex)
            self._contesto = None
            return None

    def _indirizzo_funzione(self, _contesto, nome):
        try:
            if self._risolutore is None:
                return 0
            return self._risolutore.indirizzo(nome)
        except Exception as ex:
            scrivi_log("AreaVideo._indirizzo_funzione", ex)
            return 0

    def _sveglia(self):
        try:
            GLib.idle_add(self._ridisegna)
        except Exception as ex:
            scrivi_log("AreaVideo._sveglia", ex)

    def _ridisegna(self):
        try:
            if self.get_mapped():
                self.queue_render()
        except Exception as ex:
            scrivi_log("AreaVideo._ridisegna", ex)
        return False

    def _framebuffer(self):
        try:
            if self._leggi_intero is None:
                indirizzo = self._risolutore.indirizzo(b"glGetIntegerv") if self._risolutore else 0
                if indirizzo:
                    prototipo = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.POINTER(ctypes.c_int))
                    self._leggi_intero = prototipo(indirizzo)
                elif _GL is not None:
                    return int(_GL.glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING))
                else:
                    return 0
            valore = ctypes.c_int(0)
            self._leggi_intero(GL_DRAW_FRAMEBUFFER_BINDING, ctypes.byref(valore))
            return int(valore.value)
        except Exception as ex:
            scrivi_log("video_area.AreaVideo._framebuffer", ex)
            return 0

    def _disegna(self, area, contesto_gl):
        try:
            if self._contesto is None:
                return False
            fattore = self.get_scale_factor() or 1
            larghezza = max(1, self.get_allocated_width() * fattore)
            altezza = max(1, self.get_allocated_height() * fattore)
            self._contesto.render(
                flip_y=True,
                opengl_fbo={"w": larghezza, "h": altezza, "fbo": self._framebuffer()},
            )
            return True
        except Exception as ex:
            scrivi_log("AreaVideo._disegna", ex)
            return False

    def scollega(self):
        """Smette di disegnare. Il contesto viene liberato dal motore, che ne e' il proprietario."""
        try:
            self._contesto = None
        except Exception as ex:
            scrivi_log("AreaVideo.scollega", ex)
