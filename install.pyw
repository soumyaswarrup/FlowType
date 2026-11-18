"""FlowType installer that needs no .bat or .exe - just Python.

Double-click this file (Python 3.10+ must be installed, e.g. from the Microsoft Store).
It creates a private Python environment in the FlowType folder, installs the
libraries FlowType needs, and puts a FlowType shortcut on the desktop and in the
Start menu.
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv")
IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WIN else 0


def venv_python(gui=False):
    if IS_WIN:
        return os.path.join(VENV, "Scripts", "pythonw.exe" if gui else "python.exe")
    return os.path.join(VENV, "bin", "python")


def base_python():
    """python.exe next to the interpreter running this file (pythonw has no console output)."""
    exe = sys.executable
    if IS_WIN and os.path.basename(exe).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(cand):
            return cand
    return exe


class Installer:
    def __init__(self):
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.title("Install FlowType")
        self.root.geometry("620x420")
        self.root.minsize(520, 360)
        try:
            self.root.iconbitmap(os.path.join(HERE, "flowtype.ico"))
        except Exception:
            pass
        frm = ttk.Frame(self.root, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Installing FlowType", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        self.step = ttk.Label(frm, text="Starting…", font=("Segoe UI", 10))
        self.step.pack(anchor="w", pady=(4, 8))
        self.bar = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.bar.pack(fill="x")
        self.log = tk.Text(frm, height=14, font=("Consolas", 9), wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, pady=(10, 8))
        self.btn = ttk.Button(frm, text="Please wait…", state="disabled", command=self.finish)
        self.btn.pack(anchor="e")
        self.done_ok = False
        threading.Thread(target=self.work, daemon=True).start()
        self.root.after(100, self.poll)

    # ---- UI plumbing
    def say(self, kind, value):
        self.q.put((kind, value))

    def poll(self):
        try:
            while True:
                kind, value = self.q.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", value + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif kind == "step":
                    self.step.configure(text=value[1])
                    self.bar["value"] = value[0]
                elif kind == "done":
                    ok, msg = value
                    self.done_ok = ok
                    self.step.configure(text=msg, foreground="#0a7d32" if ok else "#b00020")
                    self.bar["value"] = 100 if ok else self.bar["value"]
                    self.btn.configure(text="Start FlowType" if ok else "Close", state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def run(self, cmd):
        self.say("log", "> " + " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)))
        p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        for line in p.stdout:
            line = line.rstrip()
            if line and not line.startswith("  Downloading") or "Successfully" in line:
                self.say("log", line[:200])
        if p.wait() != 0:
            raise RuntimeError(f"step failed (exit code {p.returncode})")

    # ---- the actual install
    def work(self):
        try:
            if sys.version_info < (3, 9):
                raise RuntimeError("FlowType needs Python 3.9 or newer (3.12 recommended).")
            self.say("step", (5, "Creating FlowType's own Python environment…"))
            if not os.path.exists(venv_python()):
                self.run([base_python(), "-m", "venv", VENV])
            self.say("step", (15, "Updating pip…"))
            self.run([venv_python(), "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check"])
            self.say("step", (25, "Downloading FlowType's libraries (a few minutes, about 300 MB)…"))
            self.run([venv_python(), "-m", "pip", "install", "-r", os.path.join(HERE, "requirements.txt"),
                      "--disable-pip-version-check"])
            self.say("step", (85, "Creating shortcuts…"))
            made = self.shortcuts()
            self.say("log", "Shortcuts: " + (", ".join(made) if made else "none (start FlowType with FlowType.pyw)"))
            self.say("done", (True, "Done! Click Start FlowType. Then hold Ctrl + Alt and talk."))
        except Exception as e:
            self.say("log", "ERROR: " + str(e))
            self.say("done", (False, "Installation failed - see the messages above."))

    def shortcuts(self):
        if not IS_WIN:
            return []
        target = venv_python(gui=True)
        script = os.path.join(HERE, "flowtype.py")
        icon = os.path.join(HERE, "flowtype.ico")
        places = [os.path.join(os.path.expanduser("~"), "Desktop"),
                  os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")]
        try:  # OneDrive often moves the Desktop
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
            if buf.value:
                places[0] = buf.value
        except Exception:
            pass
        made = []
        for folder in places:
            if not os.path.isdir(folder):
                continue
            lnk = os.path.join(folder, "FlowType.lnk")
            vbs = os.path.join(HERE, "_shortcut.vbs")
            # VBScript via cscript is built into Windows; no PowerShell needed.
            with open(vbs, "w", encoding="utf-16") as f:
                f.write('Set s = CreateObject("WScript.Shell").CreateShortcut("%s")\n' % lnk)
                f.write('s.TargetPath = "%s"\n' % target)
                f.write('s.Arguments = """%s"""\n' % script)
                f.write('s.WorkingDirectory = "%s"\n' % HERE)
                f.write('s.IconLocation = "%s"\n' % icon)
                f.write('s.Description = "FlowType voice typing"\n')
                f.write("s.Save\n")
            try:
                subprocess.run(["cscript", "//nologo", vbs], creationflags=NO_WINDOW, timeout=30, check=True)
                if os.path.exists(lnk):
                    made.append(os.path.basename(folder))
            except Exception as e:
                self.say("log", f"Couldn't create a shortcut in {folder}: {e}")
            finally:
                try:
                    os.remove(vbs)
                except OSError:
                    pass
        return made

    def finish(self):
        if self.done_ok:
            subprocess.Popen([venv_python(gui=True), os.path.join(HERE, "flowtype.py")], cwd=HERE,
                             creationflags=NO_WINDOW)
        self.root.destroy()


if __name__ == "__main__":
    Installer().root.mainloop()
