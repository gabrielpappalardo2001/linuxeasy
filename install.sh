#!/usr/bin/env bash
set -Eeuo pipefail

NOME_PROGRAMMA="LinuxEasy"
REPOSITORY_URL="https://github.com/gabrielpappalardo2001/linuxeasy.git"
UTENTE=""
GRUPPO=""
CASA=""
INSTALL_DIR=""
SORGENTI_DIR=""
PROJECT_DIR=""
VENV_DIR=""
BIN_DIR=""
COMANDO=""
APPLICATIONS_DIR=""
ICON_DIR=""
ICON_FILE=""
DESKTOP_FILE_NAME="linux-easy.desktop"
LOG_DIR=""
LOG_FILE=""
PACCHETTI_PIP=(python-mpv feedparser trafilatura requests PyOpenGL)
ESEGUIBILI_CHROMIUM=(chromium-browser chromium google-chrome google-chrome-stable)
TEMPO_MASSIMO_PLAYWRIGHT=900
AVVISI=()
DISTRIBUZIONE=""
GESTORE=""

adesso() {
    date '+%d/%m/%Y %H:%M:%S'
}

errore() {
    echo "[$(adesso)] ERRORE: $*" >&2
}

per_altro_utente() {
    [[ ${EUID} -eq 0 && "${UTENTE}" != "root" ]]
}

amministratore() {
    if [[ ${EUID} -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

come_utente() {
    if per_altro_utente; then
        sudo -u "${UTENTE}" -H "$@"
    else
        "$@"
    fi
}

git_utente() {
    come_utente env GIT_TERMINAL_PROMPT=0 git "$@"
}

scrivi_file_utente() {
    come_utente tee "$1" >/dev/null
}

determina_utente() {
    if [[ ${EUID} -eq 0 ]]; then
        if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
            UTENTE="${SUDO_USER}"
        else
            UTENTE="root"
        fi
    else
        if ! command -v amministratore >/dev/null 2>&1; then
            echo "[$(date '+%d/%m/%Y %H:%M:%S')] ERRORE: sudo non è installato. Eseguire lo script come root." >&2
            exit 1
        fi
        UTENTE="$(id -un)"
    fi
    GRUPPO="$(id -gn "${UTENTE}")"
    CASA="$(getent passwd "${UTENTE}" | cut -d: -f6)"
    if [[ -z "${CASA}" || ! -d "${CASA}" ]]; then
        echo "[$(date '+%d/%m/%Y %H:%M:%S')] ERRORE: cartella personale dell'utente ${UTENTE} non trovata." >&2
        exit 1
    fi
    INSTALL_DIR="${CASA}/.local/share/linux-easy"
    SORGENTI_DIR="${INSTALL_DIR}/repository"
    VENV_DIR="${INSTALL_DIR}/venv"
    BIN_DIR="${CASA}/.local/bin"
    COMANDO="${BIN_DIR}/linux-easy"
    APPLICATIONS_DIR="${CASA}/.local/share/applications"
    ICON_DIR="${CASA}/.local/share/icons/hicolor/scalable/apps"
    ICON_FILE="${ICON_DIR}/linux-easy.svg"
    LOG_DIR="${CASA}/logs"
    LOG_FILE="${LOG_DIR}/linux-easy-installazione.log"
}

avvia_log() {
    come_utente mkdir -p "${LOG_DIR}"
    come_utente touch "${LOG_FILE}"
    exec 2> >(tee -a "${LOG_FILE}" >&2)
}

gestisci_errore() {
    local codice=$?
    local riga="$1"
    local comando="$2"
    echo "" >&2
    errore "il comando \"${comando}\" alla riga ${riga} è terminato con il codice ${codice}."
    echo "Gli errori dell'installazione sono registrati in ${LOG_FILE}" >&2
    exit "${codice}"
}

avviso() {
    AVVISI+=("$1")
    echo "[$(adesso)] ATTENZIONE: $1" >&2
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
        errore "distribuzione non riconosciuta, nessuno tra apt, dnf, pacman e zypper è disponibile."
        echo "Installare a mano con il gestore di pacchetti della distribuzione:"
        echo "  git"
        echo "  Python 3 con venv e pip"
        echo "  GTK 3 e PyGObject"
        echo "  mpv con la libreria libmpv, yt-dlp, ffmpeg"
        echo "  Chromium"
        echo "  libnotify e xdg-utils"
        echo "Poi rilanciare lo script."
        exit 1
    fi
    echo "Gestore di pacchetti: ${GESTORE}, distribuzione: ${DISTRIBUZIONE}"
    echo "Installazione per l'utente ${UTENTE} in ${INSTALL_DIR}"
}

aggiorna_indici() {
    echo ""
    echo "-- Aggiornamento degli elenchi dei pacchetti --"
    case "${GESTORE}" in
        apt)
            if ! amministratore apt-get update; then
                avviso "Aggiornamento degli elenchi di apt non riuscito del tutto, controllare le sorgenti in /etc/apt."
            fi
            ;;
        zypper)
            if ! amministratore zypper --non-interactive refresh; then
                avviso "Aggiornamento dei repository di zypper non riuscito del tutto."
            fi
            ;;
    esac
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

abilita_universe() {
    if [[ "${DISTRIBUZIONE}" != "ubuntu" && "${DISTRIBUZIONE}" != "derivata-ubuntu" ]]; then
        return 1
    fi
    echo "Abilito il repository universe di Ubuntu."
    if ! command -v add-apt-repository >/dev/null 2>&1; then
        if ! amministratore apt-get install -y software-properties-common; then
            errore "impossibile installare software-properties-common per abilitare universe."
            return 1
        fi
    fi
    if ! amministratore add-apt-repository -y universe; then
        errore "impossibile abilitare il repository universe."
        return 1
    fi
    if ! amministratore apt-get update; then
        avviso "Aggiornamento degli elenchi di apt dopo l'abilitazione di universe non riuscito del tutto."
    fi
    return 0
}

installa_mpv() {
    echo ""
    echo "-- mpv --"
    if command -v mpv >/dev/null 2>&1; then
        echo "mpv è già installato: $(command -v mpv)"
        return 0
    fi
    case "${GESTORE}" in
        apt)
            if ! amministratore apt-get install -y mpv; then
                if abilita_universe; then
                    amministratore apt-get install -y mpv || true
                fi
            fi
            ;;
        dnf)
            amministratore dnf install -y mpv mpv-libs || true
            ;;
        pacman)
            amministratore pacman -S --needed --noconfirm mpv || true
            ;;
        zypper)
            amministratore zypper --non-interactive install mpv || true
            ;;
    esac
    if ! command -v mpv >/dev/null 2>&1; then
        errore "mpv non è installato e non è stato possibile installarlo con ${GESTORE}."
        if [[ "${GESTORE}" == "dnf" ]]; then
            echo "Su Fedora abilitare i repository RPM Fusion e rilanciare lo script." >&2
        fi
        exit 1
    fi
    echo "mpv installato: $(command -v mpv)"
}

installa_git() {
    echo ""
    echo "-- git --"
    if command -v git >/dev/null 2>&1; then
        echo "git è già installato: $(command -v git)"
        return 0
    fi
    case "${GESTORE}" in
        apt) amministratore apt-get install -y git || true ;;
        dnf) amministratore dnf install -y git || true ;;
        pacman) amministratore pacman -S --needed --noconfirm git || true ;;
        zypper) amministratore zypper --non-interactive install git || true ;;
    esac
    if ! command -v git >/dev/null 2>&1; then
        errore "git non è installato e non è stato possibile installarlo con ${GESTORE}."
        exit 1
    fi
}

prepara_repository() {
    echo ""
    echo "-- Repository di ${NOME_PROGRAMMA} in ${SORGENTI_DIR} --"
    come_utente mkdir -p "${INSTALL_DIR}"
    if per_altro_utente; then
        chown -R "${UTENTE}:${GRUPPO}" "${INSTALL_DIR}"
    fi
    if [[ -d "${SORGENTI_DIR}/.git" ]]; then
        git_utente -C "${SORGENTI_DIR}" remote set-url origin "${REPOSITORY_URL}"
        if ! git_utente -C "${SORGENTI_DIR}" pull --ff-only; then
            avviso "git pull non riuscito, riallineo il repository alla versione di GitHub."
            git_utente -C "${SORGENTI_DIR}" fetch --prune origin
            git_utente -C "${SORGENTI_DIR}" reset --hard "@{u}"
        fi
        echo "Repository aggiornato."
    else
        if [[ -e "${SORGENTI_DIR}" ]]; then
            rm -rf "${SORGENTI_DIR}"
        fi
        if ! git_utente clone "${REPOSITORY_URL}" "${SORGENTI_DIR}"; then
            errore "impossibile scaricare il repository ${REPOSITORY_URL}."
            exit 1
        fi
        echo "Repository scaricato."
    fi
    PROJECT_DIR="${SORGENTI_DIR}"
    if [[ ! -d "${PROJECT_DIR}/app" || ! -f "${PROJECT_DIR}/main.py" ]]; then
        errore "nel repository ${PROJECT_DIR} mancano la cartella app o il file main.py."
        exit 1
    fi
}

installa_pacchetti_apt() {
    echo ""
    echo "-- Pacchetti di sistema con apt --"
    amministratore apt-get install -y \
        python3 python3-venv python3-pip \
        python3-gi gir1.2-gtk-3.0 gir1.2-atk-1.0 at-spi2-core \
        libnotify-bin xdg-utils ca-certificates
    if ! amministratore apt-get install -y libmpv2; then
        installa_facoltativo "libmpv" amministratore apt-get install -y libmpv1 || true
    fi
    installa_facoltativo "librerie OpenGL" amministratore apt-get install -y libgl1 libglx-mesa0 || \
        installa_facoltativo "libreria OpenGL (mesa)" amministratore apt-get install -y libgl1-mesa-glx || true
    installa_facoltativo "driver grafici mesa" amministratore apt-get install -y libgl1-mesa-dri || true
    installa_facoltativo "libreria EGL" amministratore apt-get install -y libegl1 || true
    installa_facoltativo "driver EGL di mesa" amministratore apt-get install -y libegl-mesa0 || true
    installa_facoltativo "PyOpenGL di sistema" amministratore apt-get install -y python3-opengl || true
    installa_facoltativo "typelib GdkX11 (ripiego X11)" amministratore apt-get install -y gir1.2-gdkx11-3.0 || true
    installa_facoltativo "yt-dlp" amministratore apt-get install -y yt-dlp || true
    installa_facoltativo "ffmpeg" amministratore apt-get install -y ffmpeg || true
}

installa_pacchetti_dnf() {
    echo ""
    echo "-- Pacchetti di sistema con dnf --"
    amministratore dnf install -y \
        python3 python3-pip python3-gobject gtk3 atk at-spi2-core \
        libnotify xdg-utils ca-certificates
    installa_facoltativo "libmpv" amministratore dnf install -y mpv-libs || true
    installa_facoltativo "librerie OpenGL/EGL (mesa)" \
        amministratore dnf install -y mesa-libGL mesa-libEGL mesa-dri-drivers || true
    installa_facoltativo "PyOpenGL di sistema" amministratore dnf install -y python3-pyopengl || true
    installa_facoltativo "yt-dlp" amministratore dnf install -y yt-dlp || true
    if ! amministratore dnf install -y ffmpeg; then
        installa_facoltativo "ffmpeg" amministratore dnf install -y ffmpeg-free || true
    fi
}

installa_pacchetti_pacman() {
    echo ""
    echo "-- Pacchetti di sistema con pacman --"
    amministratore pacman -S --needed --noconfirm \
        python python-pip python-gobject gtk3 at-spi2-core \
        libnotify xdg-utils ca-certificates
    installa_facoltativo "mesa (OpenGL/EGL)" amministratore pacman -S --needed --noconfirm mesa || true
    installa_facoltativo "PyOpenGL di sistema" amministratore pacman -S --needed --noconfirm python-pyopengl || true
    installa_facoltativo "yt-dlp" amministratore pacman -S --needed --noconfirm yt-dlp || true
    installa_facoltativo "ffmpeg" amministratore pacman -S --needed --noconfirm ffmpeg || true
}

installa_pacchetti_zypper() {
    echo ""
    echo "-- Pacchetti di sistema con zypper --"
    amministratore zypper --non-interactive install \
        python3 python3-pip python3-gobject gtk3 at-spi2-core \
        libnotify-tools xdg-utils ca-certificates
    if ! amministratore zypper --non-interactive install libmpv2; then
        installa_facoltativo "libmpv" amministratore zypper --non-interactive install libmpv1 || true
    fi
    installa_facoltativo "librerie OpenGL/EGL (mesa)" \
        amministratore zypper --non-interactive install Mesa-libGL1 Mesa-libEGL1 Mesa-dri || true
    installa_facoltativo "PyOpenGL di sistema" amministratore zypper --non-interactive install python3-PyOpenGL || true
    installa_facoltativo "yt-dlp" amministratore zypper --non-interactive install yt-dlp || true
    installa_facoltativo "ffmpeg" amministratore zypper --non-interactive install ffmpeg || true
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
                if amministratore snap install chromium; then
                    return 0
                fi
                avviso "Installazione di Chromium con snap non riuscita, provo con apt."
            fi
            if ! amministratore apt-get install -y chromium; then
                installa_facoltativo "Chromium" amministratore apt-get install -y chromium-browser || true
            fi
            ;;
        dnf)
            installa_facoltativo "Chromium" amministratore dnf install -y chromium || true
            ;;
        pacman)
            installa_facoltativo "Chromium" amministratore pacman -S --needed --noconfirm chromium || true
            ;;
        zypper)
            installa_facoltativo "Chromium" amministratore zypper --non-interactive install chromium || true
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
    rm -rf "${INSTALL_DIR}/app"
    come_utente cp -r "${PROJECT_DIR}/app" "${INSTALL_DIR}/app"
    come_utente cp "${PROJECT_DIR}/main.py" "${INSTALL_DIR}/main.py"
    find "${INSTALL_DIR}/app" -type d -name "__pycache__" -prune -exec rm -rf {} +
    if [[ -f "${PROJECT_DIR}/requirements.txt" ]]; then
        come_utente cp "${PROJECT_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.txt"
    fi
    if [[ -f "${PROJECT_DIR}/app.db" && ! -f "${INSTALL_DIR}/app.db" ]]; then
        come_utente cp "${PROJECT_DIR}/app.db" "${INSTALL_DIR}/app.db"
        echo "Copiato il database iniziale con preferiti, fonti e iscrizioni."
    fi
}

prepara_ambiente_python() {
    echo ""
    echo "-- Ambiente virtuale Python --"
    if [[ ! -x "${VENV_DIR}/bin/python3" ]]; then
        come_utente python3 -m venv --system-site-packages "${VENV_DIR}"
    fi
    come_utente "${VENV_DIR}/bin/python3" -m pip install --upgrade pip
    come_utente "${VENV_DIR}/bin/python3" -m pip install --upgrade "${PACCHETTI_PIP[@]}"
    if [[ -f "${INSTALL_DIR}/requirements.txt" ]]; then
        installa_facoltativo "pacchetti elencati in requirements.txt" \
            come_utente "${VENV_DIR}/bin/python3" -m pip install -r "${INSTALL_DIR}/requirements.txt" || true
    fi
}

verifica_moduli_python() {
    echo ""
    echo "-- Verifica dei moduli Python --"
    local esito
    if esito="$(come_utente "${VENV_DIR}/bin/python3" - <<'PYTHON' 2>&1
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
    if esito="$(come_utente "${VENV_DIR}/bin/python3" - <<'PYTHON' 2>&1
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
    from gi.repository import GdkX11
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
        from OpenGL import GL
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
    local opzioni=(--headless=new --disable-gpu --no-first-run --no-default-browser-check)
    if [[ "${UTENTE}" == "root" ]]; then
        opzioni+=(--no-sandbox)
    fi
    profilo="$(come_utente mktemp -d)"
    uscita="$(come_utente timeout 90 "${eseguibile}" "${opzioni[@]}" --user-data-dir="${profilo}" \
        --dump-dom 'data:text/html,<p>linuxeasy-prova-browser</p>' 2>/dev/null || true)"
    rm -rf "${profilo}"
    [[ "${uscita}" == *"linuxeasy-prova-browser"* ]]
}

installa_playwright() {
    echo "Installo il Chromium di Playwright nell'ambiente del programma."
    if ! installa_facoltativo "Playwright" come_utente "${VENV_DIR}/bin/python3" -m pip install --upgrade playwright; then
        return 0
    fi
    if [[ "${GESTORE}" == "apt" ]]; then
        installa_facoltativo "librerie di sistema per Playwright" \
            amministratore timeout "${TEMPO_MASSIMO_PLAYWRIGHT}" "${VENV_DIR}/bin/python3" -m playwright install-deps chromium || true
    fi
    if installa_facoltativo "Chromium di Playwright" come_utente timeout "${TEMPO_MASSIMO_PLAYWRIGHT}" "${VENV_DIR}/bin/python3" -m playwright install chromium; then
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
    come_utente mkdir -p "${ICON_DIR}"
    scrivi_file_utente "${ICON_FILE}" <<'ICONA'
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
    come_utente mkdir -p "${BIN_DIR}"
    scrivi_file_utente "${COMANDO}" <<COMANDO_AVVIO
#!/usr/bin/env bash
export PATH="\${PATH}:/snap/bin:${BIN_DIR}"
mkdir -p "${LOG_DIR}"
cd "${INSTALL_DIR}" || exit 1
exec "${VENV_DIR}/bin/python3" "${INSTALL_DIR}/main.py" "\$@" 2>>"${LOG_DIR}/linux-easy-avvio.log"
COMANDO_AVVIO
    come_utente chmod +x "${COMANDO}"
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
        cartella="$(come_utente env HOME="${CASA}" xdg-user-dir DESKTOP 2>/dev/null || true)"
    fi
    if [[ -z "${cartella}" || "${cartella}" == "${CASA}" ]]; then
        if [[ -d "${CASA}/Scrivania" ]]; then
            cartella="${CASA}/Scrivania"
        else
            cartella="${CASA}/Desktop"
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
    come_utente mkdir -p "${APPLICATIONS_DIR}"
    contenuto_desktop | scrivi_file_utente "${APPLICATIONS_DIR}/${DESKTOP_FILE_NAME}"
    come_utente chmod +x "${APPLICATIONS_DIR}/${DESKTOP_FILE_NAME}"
    local scrivania
    scrivania="$(cartella_scrivania)"
    come_utente mkdir -p "${scrivania}"
    contenuto_desktop | scrivi_file_utente "${scrivania}/${DESKTOP_FILE_NAME}"
    come_utente chmod +x "${scrivania}/${DESKTOP_FILE_NAME}"
    if command -v gio >/dev/null 2>&1; then
        come_utente gio set "${scrivania}/${DESKTOP_FILE_NAME}" metadata::trusted true >/dev/null 2>&1 || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        come_utente update-desktop-database "${APPLICATIONS_DIR}" >/dev/null 2>&1 || true
    fi
    echo "Comando: ${COMANDO}"
    echo "Voce nel menu: ${APPLICATIONS_DIR}/${DESKTOP_FILE_NAME}"
    echo "Icona sul desktop: ${scrivania}/${DESKTOP_FILE_NAME}"
    if ! per_altro_utente && ! tr ':' '\n' <<<"${PATH}" | grep -qx "${BIN_DIR}"; then
        echo ""
        echo "La cartella ${BIN_DIR} non è nel PATH."
        echo "Per avviare il programma dal terminale aggiungere a ~/.bashrc questa riga e riaprire il terminale:"
        echo "  export PATH=\"\$PATH:${BIN_DIR}\""
    fi
}

sistema_proprieta() {
    if per_altro_utente; then
        chown -R "${UTENTE}:${GRUPPO}" "${INSTALL_DIR}" "${LOG_DIR}"
    fi
}

riepilogo() {
    echo ""
    echo "== Installazione completata =="
    echo "Avviare ${NOME_PROGRAMMA} come utente ${UTENTE} dall'icona sul desktop, dal menu applicazioni o con il comando linux-easy."
    if [[ ${#AVVISI[@]} -gt 0 ]]; then
        echo ""
        echo "Problemi da controllare:"
        local voce
        for voce in "${AVVISI[@]}"; do
            echo "  ${voce}"
        done
        echo ""
        echo "Gli errori sono registrati in ${LOG_FILE}"
    fi
}

main() {
    determina_utente
    avvia_log
    trap 'gestisci_errore "${LINENO}" "${BASH_COMMAND}"' ERR
    rileva_distribuzione
    aggiorna_indici
    installa_mpv
    installa_git
    prepara_repository
    installa_pacchetti_sistema
    prepara_applicazione
    prepara_ambiente_python
    verifica_moduli_python
    verifica_browser_invisibile
    installa_collegamenti
    sistema_proprieta
    riepilogo
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
