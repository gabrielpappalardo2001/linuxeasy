#!/usr/bin/env bash
set -Eeuo pipefail

NOME_PROGRAMMA="LinuxEasy"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.local/share/linux-easy"
VENV_DIR="${INSTALL_DIR}/venv"
BIN_DIR="${HOME}/.local/bin"
COMANDO="${BIN_DIR}/linux-easy"
APPLICATIONS_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
ICON_FILE="${ICON_DIR}/linux-easy.svg"
DESKTOP_FILE_NAME="linux-easy.desktop"
LOG_DIR="${HOME}/logs"
LOG_FILE="${LOG_DIR}/linux-easy-installazione.log"
# python-mpv: motore di riproduzione. feedparser: lettura dei feed di notizie.
# trafilatura: estrazione del testo dagli articoli. requests: rete di appoggio.
# PyOpenGL: usato solo come ultima via per trovare le funzioni OpenGL quando il video
# viene disegnato dentro la finestra del programma (mai in una finestra separata).
PACCHETTI_PIP=(python-mpv feedparser trafilatura requests PyOpenGL)
ESEGUIBILI_CHROMIUM=(chromium-browser chromium google-chrome google-chrome-stable)
TEMPO_MASSIMO_PLAYWRIGHT=900
AVVISI=()
DISTRIBUZIONE=""
GESTORE=""

avvia_log() {
    mkdir -p "${LOG_DIR}"
    exec > >(tee -a "${LOG_FILE}") 2>&1
    echo ""
    echo "== ${NOME_PROGRAMMA}: installazione del $(date '+%d/%m/%Y %H:%M:%S') =="
}

gestisci_errore() {
    local codice=$?
    local riga="$1"
    local comando="$2"
    echo ""
    echo "ERRORE: il comando \"${comando}\" alla riga ${riga} è terminato con il codice ${codice}."
    echo "Il registro completo dell'installazione è in ${LOG_FILE}"
    exit "${codice}"
}

avviso() {
    AVVISI+=("$1")
    echo "ATTENZIONE: $1"
}

controlla_utente() {
    if [[ ${EUID} -eq 0 ]]; then
        echo "Eseguire lo script come utente normale, senza sudo."
        echo "La password di amministratore viene chiesta solo quando serve."
        exit 1
    fi
    if [[ ! -d "${PROJECT_DIR}/app" || ! -f "${PROJECT_DIR}/main.py" ]]; then
        echo "Nella cartella ${PROJECT_DIR} mancano la cartella app o il file main.py."
        echo "Avviare lo script dalla cartella del progetto."
        exit 1
    fi
}

rileva_distribuzione() {
    local identificativo=""
    local simili=""
    if [[ -r /etc/os-release ]]; then
        identificativo="$(. /etc/os-release && echo "${ID:-}")"
        simili="$(. /etc/os-release && echo "${ID_LIKE:-}")"
    fi
    if command -v apt-get >/dev/null 2>&1; then
        GESTORE="apt"
        if [[ "${identificativo}" == "ubuntu" ]]; then
            DISTRIBUZIONE="ubuntu"
        elif [[ "${identificativo}" == "linuxmint" || "${identificativo}" == "debian" ]]; then
            DISTRIBUZIONE="${identificativo}"
        elif [[ " ${simili} " == *" ubuntu "* ]]; then
            DISTRIBUZIONE="derivata-ubuntu"
        else
            DISTRIBUZIONE="debian"
        fi
    elif command -v dnf >/dev/null 2>&1; then
        GESTORE="dnf"
        DISTRIBUZIONE="fedora"
    elif command -v pacman >/dev/null 2>&1; then
        GESTORE="pacman"
        DISTRIBUZIONE="arch"
    elif command -v zypper >/dev/null 2>&1; then
        GESTORE="zypper"
        if [[ "${identificativo}" == "opensuse-tumbleweed" ]]; then
            DISTRIBUZIONE="opensuse-tumbleweed"
        else
            DISTRIBUZIONE="opensuse-leap"
        fi
    else
        echo "Distribuzione non riconosciuta (nessuno tra apt, dnf, pacman, zypper è disponibile)."
        echo "Installare a mano con il gestore di pacchetti della distribuzione:"
        echo "  Python 3 con venv e pip"
        echo "  GTK 3 e PyGObject"
        echo "  mpv con la libreria libmpv, yt-dlp, ffmpeg"
        echo "  Chromium"
        echo "  libnotify e xdg-utils"
        echo "Poi rilanciare lo script."
        exit 1
    fi
    echo "Gestore di pacchetti: ${GESTORE}, distribuzione: ${DISTRIBUZIONE}"
}

installa_facoltativo() {
    local descrizione="$1"
    shift
    if ! "$@"; then
        avviso "Installazione non riuscita: ${descrizione}."
        return 1
    fi
    return 0
}

installa_pacchetti_apt() {
    echo ""
    echo "-- Pacchetti di sistema con apt --"
    sudo apt-get update
    sudo apt-get install -y \
        python3 python3-venv python3-pip \
        python3-gi gir1.2-gtk-3.0 gir1.2-atk-1.0 at-spi2-core \
        mpv libnotify-bin xdg-utils ca-certificates
    if ! sudo apt-get install -y libmpv2; then
        installa_facoltativo "libmpv" sudo apt-get install -y libmpv1 || true
    fi
    # Video incastonato nella finestra del programma (mai una finestra separata di mpv):
    # librerie OpenGL/EGL per il render e, dove esiste, il typelib GdkX11 per il ripiego
    # su X11 quando il render diretto non e' disponibile.
    installa_facoltativo "librerie OpenGL" sudo apt-get install -y libgl1 libglx-mesa0 || \
        installa_facoltativo "libreria OpenGL (mesa)" sudo apt-get install -y libgl1-mesa-glx || true
    installa_facoltativo "driver grafici mesa" sudo apt-get install -y libgl1-mesa-dri || true
    installa_facoltativo "libreria EGL" sudo apt-get install -y libegl1 || true
    installa_facoltativo "driver EGL di mesa" sudo apt-get install -y libegl-mesa0 || true
    installa_facoltativo "PyOpenGL di sistema" sudo apt-get install -y python3-opengl || true
    installa_facoltativo "typelib GdkX11 (ripiego X11)" sudo apt-get install -y gir1.2-gdkx11-3.0 || true
    installa_facoltativo "yt-dlp" sudo apt-get install -y yt-dlp || true
    installa_facoltativo "ffmpeg" sudo apt-get install -y ffmpeg || true
}

installa_pacchetti_dnf() {
    echo ""
    echo "-- Pacchetti di sistema con dnf --"
    sudo dnf install -y \
        python3 python3-pip python3-gobject gtk3 atk at-spi2-core \
        mpv mpv-libs libnotify xdg-utils ca-certificates
    # Video incastonato nella finestra del programma: librerie OpenGL/EGL di mesa.
    # Il typelib GdkX11 e' gia' incluso nel pacchetto gtk3.
    installa_facoltativo "librerie OpenGL/EGL (mesa)" \
        sudo dnf install -y mesa-libGL mesa-libEGL mesa-dri-drivers || true
    installa_facoltativo "PyOpenGL di sistema" sudo dnf install -y python3-pyopengl || true
    installa_facoltativo "yt-dlp" sudo dnf install -y yt-dlp || true
    if ! sudo dnf install -y ffmpeg; then
        installa_facoltativo "ffmpeg" sudo dnf install -y ffmpeg-free || true
    fi
}

installa_pacchetti_pacman() {
    echo ""
    echo "-- Pacchetti di sistema con pacman --"
    sudo pacman -S --needed --noconfirm \
        python python-pip python-gobject gtk3 at-spi2-core \
        mpv libnotify xdg-utils ca-certificates
    # Video incastonato nella finestra del programma: mesa fornisce sia OpenGL sia EGL.
    # Il typelib GdkX11 e' gia' incluso nel pacchetto gtk3.
    installa_facoltativo "mesa (OpenGL/EGL)" sudo pacman -S --needed --noconfirm mesa || true
    installa_facoltativo "PyOpenGL di sistema" sudo pacman -S --needed --noconfirm python-pyopengl || true
    installa_facoltativo "yt-dlp" sudo pacman -S --needed --noconfirm yt-dlp || true
    installa_facoltativo "ffmpeg" sudo pacman -S --needed --noconfirm ffmpeg || true
}

installa_pacchetti_zypper() {
    echo ""
    echo "-- Pacchetti di sistema con zypper --"
    sudo zypper --non-interactive refresh
    sudo zypper --non-interactive install \
        python3 python3-pip python3-gobject gtk3 at-spi2-core \
        mpv libnotify-tools xdg-utils ca-certificates
    if ! sudo zypper --non-interactive install libmpv2; then
        installa_facoltativo "libmpv" sudo zypper --non-interactive install libmpv1 || true
    fi
    # Video incastonato nella finestra del programma: librerie OpenGL/EGL di mesa.
    # Il typelib GdkX11 e' gia' incluso nel pacchetto gtk3.
    installa_facoltativo "librerie OpenGL/EGL (mesa)" \
        sudo zypper --non-interactive install Mesa-libGL1 Mesa-libEGL1 Mesa-dri || true
    installa_facoltativo "PyOpenGL di sistema" sudo zypper --non-interactive install python3-PyOpenGL || true
    installa_facoltativo "yt-dlp" sudo zypper --non-interactive install yt-dlp || true
    installa_facoltativo "ffmpeg" sudo zypper --non-interactive install ffmpeg || true
}

trova_chromium() {
    local nome
    for nome in "${ESEGUIBILI_CHROMIUM[@]}"; do
        if command -v "${nome}" >/dev/null 2>&1; then
            command -v "${nome}"
            return 0
        fi
    done
    if [[ -x /snap/bin/chromium ]]; then
        echo /snap/bin/chromium
        return 0
    fi
    return 1
}

installa_chromium() {
    echo ""
    echo "-- Chromium --"
    if trova_chromium >/dev/null; then
        echo "Chromium è già installato: $(trova_chromium)"
        return 0
    fi
    case "${GESTORE}" in
        apt)
            if [[ "${DISTRIBUZIONE}" == "ubuntu" || "${DISTRIBUZIONE}" == "derivata-ubuntu" ]] && command -v snap >/dev/null 2>&1; then
                if sudo snap install chromium; then
                    return 0
                fi
                avviso "Installazione di Chromium con snap non riuscita, provo con apt."
            fi
            if ! sudo apt-get install -y chromium; then
                installa_facoltativo "Chromium" sudo apt-get install -y chromium-browser || true
            fi
            ;;
        dnf)
            installa_facoltativo "Chromium" sudo dnf install -y chromium || true
            ;;
        pacman)
            installa_facoltativo "Chromium" sudo pacman -S --needed --noconfirm chromium || true
            ;;
        zypper)
            installa_facoltativo "Chromium" sudo zypper --non-interactive install chromium || true
            ;;
    esac
}

installa_pacchetti_sistema() {
    case "${GESTORE}" in
        apt) installa_pacchetti_apt ;;
        dnf) installa_pacchetti_dnf ;;
        pacman) installa_pacchetti_pacman ;;
        zypper) installa_pacchetti_zypper ;;
    esac
    installa_chromium
}

prepara_applicazione() {
    echo ""
    echo "-- Copia del programma in ${INSTALL_DIR} --"
    mkdir -p "${INSTALL_DIR}"
    rm -rf "${INSTALL_DIR}/app"
    cp -r "${PROJECT_DIR}/app" "${INSTALL_DIR}/app"
    cp "${PROJECT_DIR}/main.py" "${INSTALL_DIR}/main.py"
    find "${INSTALL_DIR}/app" -type d -name "__pycache__" -prune -exec rm -rf {} +
    if [[ -f "${PROJECT_DIR}/requirements.txt" ]]; then
        cp "${PROJECT_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.txt"
    fi
    if [[ -f "${PROJECT_DIR}/app.db" && ! -f "${INSTALL_DIR}/app.db" ]]; then
        cp "${PROJECT_DIR}/app.db" "${INSTALL_DIR}/app.db"
        echo "Copiato il database esistente con preferiti, fonti e iscrizioni."
    fi
}

prepara_ambiente_python() {
    echo ""
    echo "-- Ambiente virtuale Python --"
    if [[ ! -x "${VENV_DIR}/bin/python3" ]]; then
        python3 -m venv --system-site-packages "${VENV_DIR}"
    fi
    "${VENV_DIR}/bin/python3" -m pip install --upgrade pip
    "${VENV_DIR}/bin/python3" -m pip install --upgrade "${PACCHETTI_PIP[@]}"
    if [[ -f "${INSTALL_DIR}/requirements.txt" ]]; then
        installa_facoltativo "pacchetti elencati in requirements.txt" \
            "${VENV_DIR}/bin/python3" -m pip install -r "${INSTALL_DIR}/requirements.txt" || true
    fi
}

verifica_moduli_python() {
    echo ""
    echo "-- Verifica dei moduli Python --"
    local esito
    if esito="$("${VENV_DIR}/bin/python3" - <<'PYTHON' 2>&1
import importlib
import sys

problemi = []
try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
except Exception as ex:
    problemi.append(f"GTK 3 e PyGObject: {ex}")
for nome in ("feedparser", "trafilatura", "mpv"):
    try:
        importlib.import_module(nome)
    except Exception as ex:
        problemi.append(f"{nome}: {ex}")
print("\n".join(problemi))
sys.exit(1 if problemi else 0)
PYTHON
)"; then
        echo "GTK 3, feedparser, trafilatura e mpv sono disponibili."
    else
        avviso "Moduli Python con problemi: ${esito}"
    fi
    verifica_video_incastonato
}

verifica_video_incastonato() {
    echo ""
    echo "-- Verifica del video incastonato nella finestra --"
    local esito
    if esito="$("${VENV_DIR}/bin/python3" - <<'PYTHON' 2>&1
import sys

vie = []
try:
    import mpv
    if hasattr(mpv, "MpvRenderContext"):
        vie.append("render diretto (funziona su X11 e su Wayland)")
    else:
        print("python-mpv non ha MpvRenderContext: aggiornarlo con pip install --upgrade python-mpv")
except Exception as ex:
    print(f"python-mpv non disponibile: {ex}")

try:
    import gi
    gi.require_version("GdkX11", "3.0")
    from gi.repository import GdkX11  # noqa: F401
    vie.append("ripiego su X11 (wid)")
except Exception:
    pass

risolutore = False
import ctypes
for nome in ("libEGL.so.1", "libGL.so.1", "libGLX.so.0"):
    try:
        ctypes.CDLL(nome)
        risolutore = True
        break
    except OSError:
        continue
if not risolutore:
    try:
        from OpenGL import GL  # noqa: F401
        risolutore = True
    except Exception:
        pass

if not vie:
    print("Nessuna via per incastonare il video: verrà riprodotto solo l'audio, mai in una finestra separata.")
    sys.exit(1)
if not risolutore:
    print("Nessuna libreria OpenGL/EGL trovata: il render diretto potrebbe non funzionare.")
    sys.exit(1)
print("Video incastonabile con: " + ", ".join(vie))
sys.exit(0)
PYTHON
)"; then
        echo "${esito}"
    else
        avviso "Video: ${esito}"
        avviso "Senza queste librerie il programma riproduce comunque l'audio, ma non mostra mai il video in una finestra separata."
    fi
}

chromium_funziona() {
    local eseguibile="$1"
    local profilo
    local uscita
    profilo="$(mktemp -d)"
    uscita="$(timeout 90 "${eseguibile}" --headless=new --disable-gpu --no-first-run \
        --no-default-browser-check --user-data-dir="${profilo}" \
        --dump-dom 'data:text/html,<p>linuxeasy-prova-browser</p>' 2>/dev/null || true)"
    rm -rf "${profilo}"
    [[ "${uscita}" == *"linuxeasy-prova-browser"* ]]
}

installa_playwright() {
    echo "Installo il Chromium di Playwright nell'ambiente del programma."
    if ! installa_facoltativo "Playwright" "${VENV_DIR}/bin/python3" -m pip install --upgrade playwright; then
        return 0
    fi
    if [[ "${GESTORE}" == "apt" ]]; then
        installa_facoltativo "librerie di sistema per Playwright" \
            sudo timeout "${TEMPO_MASSIMO_PLAYWRIGHT}" "${VENV_DIR}/bin/python3" -m playwright install-deps chromium || true
    fi
    if installa_facoltativo "Chromium di Playwright" timeout "${TEMPO_MASSIMO_PLAYWRIGHT}" "${VENV_DIR}/bin/python3" -m playwright install chromium; then
        echo "Il Chromium di Playwright è pronto."
    fi
}

verifica_browser_invisibile() {
    echo ""
    echo "-- Verifica del browser invisibile --"
    local eseguibile
    eseguibile="$(trova_chromium || true)"
    if [[ -n "${eseguibile}" ]]; then
        if chromium_funziona "${eseguibile}"; then
            echo "Il browser invisibile funziona: ${eseguibile}"
            return 0
        fi
        avviso "Chromium è installato ma non funziona in modalità invisibile."
    else
        echo "Chromium non è disponibile."
    fi
    installa_playwright
}

scrivi_icona() {
    mkdir -p "${ICON_DIR}"
    cat > "${ICON_FILE}" <<'ICONA'
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <rect x="8" y="8" width="240" height="240" rx="48" fill="#1b5fa8"/>
  <rect x="8" y="136" width="240" height="112" rx="48" fill="#174f8c"/>
  <rect x="8" y="136" width="240" height="40" fill="#174f8c"/>
  <path d="M70 84 L112 84 L150 50 L150 206 L112 172 L70 172 Z" fill="#ffffff"/>
  <path d="M172 98 Q192 128 172 158" fill="none" stroke="#ffd23f" stroke-width="14" stroke-linecap="round"/>
  <path d="M192 74 Q228 128 192 182" fill="none" stroke="#ffd23f" stroke-width="14" stroke-linecap="round"/>
</svg>
ICONA
}

scrivi_comando() {
    mkdir -p "${BIN_DIR}"
    cat > "${COMANDO}" <<COMANDO_AVVIO
#!/usr/bin/env bash
export PATH="\${PATH}:/snap/bin:${BIN_DIR}"
mkdir -p "${LOG_DIR}"
cd "${INSTALL_DIR}" || exit 1
exec "${VENV_DIR}/bin/python3" "${INSTALL_DIR}/main.py" "\$@" 2>>"${LOG_DIR}/linux-easy-avvio.log"
COMANDO_AVVIO
    chmod +x "${COMANDO}"
}

contenuto_desktop() {
    cat <<VOCE
[Desktop Entry]
Type=Application
Version=1.0
Name=${NOME_PROGRAMMA}
GenericName=Radio, podcast e notizie
Comment=Radio, podcast e notizie da usare con Orca
Exec=${COMANDO}
Icon=${ICON_FILE}
Terminal=false
StartupNotify=true
Categories=AudioVideo;Audio;Network;News;Utility;Accessibility;
Keywords=radio;podcast;notizie;news;orca;
VOCE
}

cartella_scrivania() {
    local cartella=""
    if command -v xdg-user-dir >/dev/null 2>&1; then
        cartella="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
    fi
    if [[ -z "${cartella}" || "${cartella}" == "${HOME}" ]]; then
        if [[ -d "${HOME}/Scrivania" ]]; then
            cartella="${HOME}/Scrivania"
        else
            cartella="${HOME}/Desktop"
        fi
    fi
    echo "${cartella}"
}

rimuovi_vecchi_collegamenti() {
    local vecchio
    for vecchio in "${BIN_DIR}/lettore-accessibile" "${APPLICATIONS_DIR}/org.gabriel.lettoreaccessibile.desktop"; do
        if [[ -e "${vecchio}" ]]; then
            rm -f "${vecchio}"
            echo "Rimosso il vecchio collegamento ${vecchio}"
        fi
    done
}

installa_collegamenti() {
    echo ""
    echo "-- Comando, voce nel menu e icona sul desktop --"
    rimuovi_vecchi_collegamenti
    scrivi_icona
    scrivi_comando
    mkdir -p "${APPLICATIONS_DIR}"
    contenuto_desktop > "${APPLICATIONS_DIR}/${DESKTOP_FILE_NAME}"
    chmod +x "${APPLICATIONS_DIR}/${DESKTOP_FILE_NAME}"
    local scrivania
    scrivania="$(cartella_scrivania)"
    mkdir -p "${scrivania}"
    contenuto_desktop > "${scrivania}/${DESKTOP_FILE_NAME}"
    chmod +x "${scrivania}/${DESKTOP_FILE_NAME}"
    if command -v gio >/dev/null 2>&1; then
        gio set "${scrivania}/${DESKTOP_FILE_NAME}" metadata::trusted true >/dev/null 2>&1 || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "${APPLICATIONS_DIR}" >/dev/null 2>&1 || true
    fi
    echo "Comando: ${COMANDO}"
    echo "Voce nel menu: ${APPLICATIONS_DIR}/${DESKTOP_FILE_NAME}"
    echo "Icona sul desktop: ${scrivania}/${DESKTOP_FILE_NAME}"
    if ! tr ':' '\n' <<<"${PATH}" | grep -qx "${BIN_DIR}"; then
        echo ""
        echo "La cartella ${BIN_DIR} non è nel PATH."
        echo "Per avviare il programma dal terminale aggiungere a ~/.bashrc questa riga e riaprire il terminale:"
        echo "  export PATH=\"\$PATH:${BIN_DIR}\""
    fi
}

riepilogo() {
    echo ""
    echo "== Installazione completata =="
    echo "Avviare ${NOME_PROGRAMMA} dall'icona sul desktop, dal menu applicazioni o con il comando linux-easy."
    if [[ ${#AVVISI[@]} -gt 0 ]]; then
        echo ""
        echo "Problemi da controllare:"
        local voce
        for voce in "${AVVISI[@]}"; do
            echo "  ${voce}"
        done
    fi
    echo ""
    echo "Registro dell'installazione: ${LOG_FILE}"
}

main() {
    controlla_utente
    avvia_log
    trap 'gestisci_errore "${LINENO}" "${BASH_COMMAND}"' ERR
    rileva_distribuzione
    installa_pacchetti_sistema
    prepara_applicazione
    prepara_ambiente_python
    verifica_moduli_python
    verifica_browser_invisibile
    installa_collegamenti
    riepilogo
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi