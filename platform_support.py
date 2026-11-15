"""Everything that differs between Windows, macOS and Linux lives here, so the
rest of FlowType can stay the same on all three."""
import os
import subprocess
import sys
import threading
import time

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
PLATFORM = "Windows" if IS_WIN else "macOS" if IS_MAC else "Linux"

# Paste / copy / "send email" use Cmd on a Mac, Ctrl elsewhere.
MOD = "cmd" if IS_MAC else "ctrl"
PASTE = MOD + "+v"
COPY = MOD + "+c"
SEND_EMAIL = MOD + "+enter"

MODIFIER_NAMES = {"ctrl", "left ctrl", "right ctrl", "alt", "left alt", "right alt", "alt gr", "shift",
                  "left shift", "right shift", "windows", "left windows", "right windows", "cmd",
                  "left cmd", "right cmd", "option"}

UI_FONT = "Segoe UI" if IS_WIN else "Helvetica Neue" if IS_MAC else "DejaVu Sans"
UI_FONT_BOLD = "Segoe UI Semibold" if IS_WIN else "Helvetica Neue" if IS_MAC else "DejaVu Sans"

_NO_WINDOW = 0x08000000 if IS_WIN else 0


# ---------------------------------------------------------------- keyboard
class WindowsKeys:
    """Windows: the `keyboard` package (no admin rights needed)."""

    def __init__(self):
        import keyboard
        self.k = keyboard

    def valid(self, name):
        try:
            self.k.key_to_scan_codes(name)
            return True
        except Exception:
            return False

    def is_pressed(self, name):
        try:
            return self.k.is_pressed(name)
        except Exception:
            return False

    def send(self, combo):
        self.k.send(combo)

    def add_hotkey(self, combo, callback):
        # never suppress: suppression delays and replays Ctrl/Alt, which triggers other shortcuts
        self.k.add_hotkey(combo, callback, suppress=False)

    def hook(self, callback):
        self.k.hook(lambda e: callback(e.event_type, (e.name or "").lower()))


class PynputKeys:
    """macOS and Linux (X11): `pynput`. On a Mac, FlowType needs Accessibility and
    Input Monitoring permission (System Settings -> Privacy & Security)."""

    ALIASES = {"ctrl": ("ctrl", "ctrl_l", "ctrl_r"), "alt": ("alt", "alt_l", "alt_r", "alt_gr"),
               "shift": ("shift", "shift_l", "shift_r"), "windows": ("cmd", "cmd_l", "cmd_r"),
               "cmd": ("cmd", "cmd_l", "cmd_r"), "option": ("alt", "alt_l", "alt_r")}
    # Option+letter on a Mac produces a symbol; map the ones FlowType's shortcuts use back to letters.
    MAC_OPTION = {"∂": "d", "\xa0": "space"}

    def __init__(self):
        from pynput import keyboard as pk
        self.pk = pk
        self.down = set()
        self.ctl = pk.Controller()
        self.hotkeys = []
        self.hooks = []
        self.listener = pk.Listener(on_press=self._press, on_release=self._release)
        self.listener.daemon = True
        self.listener.start()

    def _names(self, key):
        pk = self.pk
        if isinstance(key, pk.Key):
            n = key.name  # ctrl_l, alt_r, cmd, space, enter...
            out = {n}
            for generic, members in self.ALIASES.items():
                if n in members:
                    out.add(generic)
            return out
        ch = getattr(key, "char", None)
        if ch:
            ch = self.MAC_OPTION.get(ch, ch)
            if len(ch) == 1 and ord(ch) < 32:  # Ctrl+letter on some systems
                ch = chr(ord(ch) + 96)
            return {ch.lower()}
        vk = getattr(key, "vk", None)
        return {f"vk{vk}"} if vk is not None else set()

    def _press(self, key):
        names = self._names(key)
        self.down |= names
        name = sorted(names, key=len)[-1] if names else ""
        for cb in self.hooks:
            try:
                cb("down", "space" if name == "space" else name)
            except Exception:
                pass
        for keys, cb in self.hotkeys:
            if names & keys and keys <= self.down:
                threading.Thread(target=cb, daemon=True).start()

    def _release(self, key):
        self.down -= self._names(key)

    def valid(self, name):
        name = name.lower()
        return name in self.ALIASES or len(name) == 1 or hasattr(self.pk.Key, name.replace(" ", "_")) \
            or name.split(" ")[-1] in self.ALIASES

    def is_pressed(self, name):
        name = name.lower()
        if name.startswith(("left ", "right ")):
            side, base = name.split(" ", 1)
            base = {"windows": "cmd"}.get(base, base)
            return f"{base}_{side[0]}" in self.down
        return name in self.down

    def _key(self, name):
        pk = self.pk
        name = {"windows": "cmd", "option": "alt", "return": "enter"}.get(name, name)
        return getattr(pk.Key, name) if hasattr(pk.Key, name) else name

    def send(self, combo):
        keys = [self._key(p.strip().lower()) for p in combo.split("+")]
        for k in keys:
            self.ctl.press(k)
        for k in reversed(keys):
            self.ctl.release(k)

    def add_hotkey(self, combo, callback):
        parts = set()
        for p in combo.lower().split("+"):
            p = p.strip()
            parts.add({"win": "windows", "option": "alt"}.get(p, p))
        self.hotkeys.append((parts, callback))

    def hook(self, callback):
        self.hooks.append(callback)


def make_keys():
    return WindowsKeys() if IS_WIN else PynputKeys()


# ---------------------------------------------------------------- active window
def foreground_title():
    """Title of the window you're typing into (used for tone / email detection)."""
    try:
        if IS_WIN:
            import ctypes
            u = ctypes.windll.user32
            hwnd = u.GetForegroundWindow()
            n = u.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            return buf.value
        if IS_MAC:
            script = ('tell application "System Events" to tell (first process whose frontmost is true) to '
                      'return name & " - " & (name of front window)')
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=1.5)
            if out.returncode == 0:
                return out.stdout.strip()
            try:
                from AppKit import NSWorkspace
                return NSWorkspace.sharedWorkspace().frontmostApplication().localizedName() or ""
            except Exception:
                return ""
        # Linux / X11
        try:
            from Xlib import X, display
            d = display.Display()
            root = d.screen().root
            atom = d.intern_atom("_NET_ACTIVE_WINDOW")
            wid = root.get_full_property(atom, X.AnyPropertyType).value[0]
            win = d.create_resource_object("window", wid)
            name = win.get_full_property(d.intern_atom("_NET_WM_NAME"), 0)
            title = name.value.decode("utf-8", "replace") if name else (win.get_wm_name() or "")
            d.close()
            return title
        except Exception:
            out = subprocess.run(["xdotool", "getactivewindow", "getwindowname"],
                                 capture_output=True, text=True, timeout=1)
            return out.stdout.strip()
    except Exception:
        return ""


def mask_alt_win():
    """Windows only: a no-op key press so releasing Alt/Win doesn't open menus."""
    if IS_WIN:
        try:
            import ctypes
            u = ctypes.windll.user32
            u.keybd_event(0xE8, 0, 0, 0)
            u.keybd_event(0xE8, 0, 2, 0)
        except Exception:
            pass


# ---------------------------------------------------------------- one copy at a time
_LOCK = None


def single_instance(data_dir, wait=False):
    """True if this is the only FlowType running. wait=True retries for ~5 s (used when restarting)."""
    global _LOCK
    for _ in range(20 if wait else 1):
        if IS_WIN:
            import ctypes
            k = ctypes.windll.kernel32
            handle = k.CreateMutexW(None, False, "FlowTypeSingleInstanceMutex")
            if k.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
                _LOCK = handle
                return True
            k.CloseHandle(handle)
        else:
            import fcntl
            f = open(os.path.join(data_dir, ".flowtype.lock"), "w")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _LOCK = f
                return True
            except OSError:
                f.close()
        if wait:
            time.sleep(0.25)
    return False


def release_instance():
    global _LOCK
    try:
        if IS_WIN and _LOCK:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(_LOCK)
        elif _LOCK:
            _LOCK.close()
    except Exception:
        pass
    _LOCK = None


# ---------------------------------------------------------------- small helpers
def open_path(path):
    try:
        if IS_WIN:
            os.startfile(path)
        elif IS_MAC:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def beep(freq, ms=45):
    """Short start/stop tone."""
    def run():
        try:
            if IS_WIN:
                import winsound
                winsound.Beep(freq, ms)
                return
            import numpy as np
            import sounddevice as sd
            sr = 44100
            t = np.arange(int(sr * ms / 1000)) / sr
            tone = 0.15 * np.sin(2 * np.pi * freq * t) * np.hanning(len(t))
            sd.play(tone.astype("float32"), sr)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def ask_text_native(prompt, title="FlowType"):
    """Small input box without needing the GUI thread. Returns '' if cancelled/unavailable."""
    try:
        if IS_WIN:
            p, t = prompt.replace("'", "''"), title.replace("'", "''")
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "Add-Type -AssemblyName Microsoft.VisualBasic; "
                                  f"[Microsoft.VisualBasic.Interaction]::InputBox('{p}', '{t}', '')"],
                                 capture_output=True, text=True, timeout=300, creationflags=_NO_WINDOW)
            return out.stdout.strip()
        if IS_MAC:
            p = prompt.replace('"', '\\"')
            out = subprocess.run(["osascript", "-e",
                                  f'text returned of (display dialog "{p}" default answer "" with title "{title}")'],
                                 capture_output=True, text=True, timeout=300)
            return out.stdout.strip()
        for cmd in (["zenity", "--entry", "--title", title, "--text", prompt],
                    ["kdialog", "--title", title, "--inputbox", prompt]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                return out.stdout.strip()
            except FileNotFoundError:
                continue
    except Exception:
        pass
    return None  # caller falls back to a Tk dialog


def message_box(text, title="FlowType"):
    try:
        if IS_WIN:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
        elif IS_MAC:
            subprocess.run(["osascript", "-e", f'display dialog "{text}" with title "{title}" buttons {{"OK"}}'],
                           timeout=300)
        else:
            subprocess.run(["notify-send", title, text], timeout=5)
    except Exception:
        pass


def set_dpi_aware():
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
