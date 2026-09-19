import os
import sys
import urllib.request
import json
import zipfile
import shutil
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

class UpdateManager:
    def __init__(self, current_version, repo_owner="UTENTE", repo_name="LinuxAccessibile"):
        self.current_version = current_version
        self.api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"

    def check_for_updates(self, parent_window=None):
        try:
            req = urllib.request.Request(self.api_url, headers={'User-Agent': 'LinuxEasyApp'})
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    latest_tag = data.get('tag_name', '').lstrip('v')
                    if latest_tag and latest_tag != self.current_version:
                        download_url = data.get('zipball_url') or data.get('tarball_url')
                        if download_url and self._prompt_user(parent_window):
                            self._perform_update(download_url)
        except Exception:
            pass

    def _prompt_user(self, parent_window):
        dialog = Gtk.MessageDialog(
            transient_for=parent_window,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Si vuole aggiornare il programma?"
        )
        dialog.format_secondary_text("È disponibile una nuova versione dell'applicazione.")
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def _perform_update(self, download_url):
        app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        archive_path = os.path.join(app_dir, "update.zip")
        
        try:
            urllib.request.urlretrieve(download_url, archive_path)
            
            extract_dir = os.path.join(app_dir, "update_temp")
            os.makedirs(extract_dir, exist_ok=True)
            
            if zipfile.is_zipfile(archive_path):
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
            
            subdirs = [os.path.join(extract_dir, d) for d in os.listdir(extract_dir) if os.path.isdir(os.path.join(extract_dir, d))]
            source_dir = subdirs[0] if subdirs else extract_dir

            for item in os.listdir(source_dir):
                s = os.path.join(source_dir, item)
                d = os.path.join(app_dir, item)
                if os.path.isdir(s):
                    if os.path.exists(d):
                        shutil.rmtree(d)
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)

            os.remove(archive_path)
            shutil.rmtree(extract_dir)

            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            if os.path.exists(archive_path):
                os.remove(archive_path)