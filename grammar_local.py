"""Offline grammar check: runs LanguageTool on this computer (needs Java 17+),
so dictated text never leaves the machine."""
import os
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile

LT_ZIP = "https://languagetool.org/download/LanguageTool-stable.zip"
PORT = 8081


class LocalLanguageTool:
    def __init__(self, data_dir, log, ui):
        self.dir = os.path.join(data_dir, "languagetool")
        self.log, self.ui = log, ui
        self.proc = None
        self.lock = threading.Lock()

    @staticmethod
    def java():
        return shutil.which("java")

    def jar(self):
        if not os.path.isdir(self.dir):
            return None
        for root, _, files in os.walk(self.dir):
            if "languagetool-server.jar" in files:
                return os.path.join(root, "languagetool-server.jar")
        return None

    def running(self):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v2/languages", timeout=1):
                return True
        except Exception:
            return False

    def ensure(self):
        """Download (once, ~250 MB) and start the local server. Returns True when it's ready."""
        with self.lock:
            if self.running():
                return True
            if not self.java():
                self.ui.put(("error", "Offline grammar needs Java 17+ (free: adoptium.net)"))
                self.log.error("Offline grammar: Java not found")
                return False
            jar = self.jar()
            if not jar:
                os.makedirs(self.dir, exist_ok=True)
                tmp = os.path.join(self.dir, "lt.zip")
                self.ui.put(("working", "Downloading offline grammar checker (one time, ~250 MB)"))
                try:
                    urllib.request.urlretrieve(LT_ZIP, tmp)
                    with zipfile.ZipFile(tmp) as z:
                        z.extractall(self.dir)
                    os.remove(tmp)
                except Exception as e:
                    self.log.error("LanguageTool download failed: %s", e)
                    self.ui.put(("error", "Couldn't download the offline grammar checker"))
                    return False
                jar = self.jar()
            flags = 0x08000000 if os.name == "nt" else 0  # no console window
            self.proc = subprocess.Popen(
                [self.java(), "-cp", jar, "org.languagetool.server.HTTPServer", "--port", str(PORT)],
                cwd=os.path.dirname(jar), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=flags)
            for _ in range(60):
                if self.running():
                    self.log.info("Local LanguageTool running on port %d", PORT)
                    return True
                time.sleep(0.5)
            self.ui.put(("error", "Offline grammar checker didn't start - see log"))
            return False

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
