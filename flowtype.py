"""FlowType - hold-to-talk voice dictation for Windows.

Hold the hotkey (default Ctrl+Alt), speak, release. Your speech is transcribed
locally with Whisper, cleaned up, and typed into whatever app has focus.
Ctrl+Shift+Space toggles hands-free mode (tap the hold hotkey or press it again to stop).
"""
import ctypes
import datetime
import json
import math
import logging
import os
import queue
import sys
import threading
import time
import traceback

APP_NAME = "FlowType"
APP_VERSION = "1.6.0"
try:  # release builds write the exact tag into _version.py
    from _version import __version__ as APP_VERSION  # noqa: F811
except Exception:
    pass
GITHUB_REPO = "soumyaswarrup/FlowType"
FROZEN = getattr(sys, "frozen", False)  # True when running as the packaged FlowType.exe
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
# The packaged app keeps settings in %APPDATA%\FlowType so each user has their own.
DATA_DIR = os.path.join(os.environ.get("APPDATA", APP_DIR), "FlowType") if FROZEN else APP_DIR
os.makedirs(DATA_DIR, exist_ok=True)
INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", APP_DIR), "Programs", "FlowType")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.jsonl")
LOG_PATH = os.path.join(DATA_DIR, "flowtype.log")
SAMPLE_RATE = 16000

DEFAULT_CONFIG = {
    "hotkey_hold": "ctrl+alt",
    "hotkey_toggle": "ctrl+shift+space",
    "model": "small.en",
    "device": "auto",            # auto = use an NVIDIA GPU if one is set up, else CPU
    "compute_type": "auto",
    "grammar_check": False,       # opt-in: sends dictated text to LanguageTool (see PRIVACY.md)
    "grammar_language": "en-US",
    "grammar_mode": "online",     # online = LanguageTool website, offline = LanguageTool on this PC (Java)
    "spoken_punctuation": False,  # say "comma", "question mark", "new line"...
    "email_format": True,
    "input_device": None,
    "cleanup": "basic",
    "llm": {                      # the AI used by command mode (tray -> Command mode AI)
        "provider": "",
        "model": "",
        "api_key": "",
        "base_url": "",
        "timeout_seconds": 25,
        "send_window_title": True,
    },
    "hotkey_learn": "ctrl+alt+d",
    "hotkey_paste_last": "ctrl+alt+v",
    "hotkey_read_aloud": "ctrl+alt+r",
    "mouse_button": "",           # "", "middle", "x1" (back), "x2" (forward): hold it to talk
    "check_updates": True,
    "pause_in_apps": ["1password", "bitwarden", "keepass", "lastpass", "dashlane", "netbanking",
                      "internet banking"],
    "meeting_folder": "",
    "command_mode": True,
    "tone": "auto",               # auto | casual | professional | code | plain (tray -> Tone)
    "live_preview": True,
    "snippets": {
        "signature": "Best regards,\nYour Name",
        "email address": "you@example.com",
    },
    "dictionary": [],
    "replacements": {},
    "voice_commands": True,
    "auto_send": False,
    "add_trailing_space": True,
    "restore_clipboard": True,
    "sounds": True,
    "show_overlay": True,
    "save_history": True,
    "min_seconds": 0.35,
    "max_seconds": 600,
    "meeting_max_minutes": 180,
}

# Running without a console (pythonw / the .exe): give progress bars somewhere to write.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

logging.basicConfig(
    filename=LOG_PATH, level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(APP_NAME)


def load_dotenv():
    """Read KEY=value lines from .env next to this file into the environment."""
    path = os.path.join(DATA_DIR, ".env")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


load_dotenv()


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            log.error("Could not read config.json (%s); using defaults", e)
    else:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
    return cfg


def save_settings(updates):
    """Write a few keys into config.json, keeping everything else the user has there."""
    data = {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = json.loads(json.dumps(DEFAULT_CONFIG))
    data.update(updates)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


import platform_support as ps  # noqa: E402  (Windows / macOS / Linux differences)

user32 = ctypes.windll.user32 if ps.IS_WIN else None
foreground_title = ps.foreground_title
mask_win_key = ps.mask_alt_win


def single_instance():
    return ps.single_instance(DATA_DIR, wait="--restarted" in sys.argv)


def add_cuda_dll_dirs():
    """Make pip-installed NVIDIA libraries (enable-gpu.bat) visible to ctranslate2 on Windows."""
    if os.name != "nt":
        return
    import site
    roots = list(getattr(site, "getsitepackages", lambda: [])()) + [os.path.join(sys.prefix, "Lib", "site-packages")]
    for root in roots:
        nv = os.path.join(root, "nvidia")
        if not os.path.isdir(nv):
            continue
        for sub in os.listdir(nv):
            b = os.path.join(nv, sub, "bin")
            if os.path.isdir(b):
                try:
                    os.add_dll_directory(b)
                except Exception:
                    pass
                os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")


def load_model(cfg):
    """Uses an NVIDIA GPU when one works (much faster), otherwise the CPU."""
    from faster_whisper import WhisperModel
    import numpy as np
    device, ctype = cfg.get("device", "auto"), cfg.get("compute_type", "auto")
    if device in ("auto", "cuda"):
        try:
            import ctranslate2
            add_cuda_dll_dirs()
            if ctranslate2.get_cuda_device_count() > 0:
                m = WhisperModel(cfg["model"], device="cuda",
                                 compute_type="float16" if ctype == "auto" else ctype)
                segs, _ = m.transcribe(np.zeros(16000, dtype="float32"), language="en")
                list(segs)  # make sure the GPU libraries really work
                m.flowtype_device = "GPU"
                log.info("Speech model running on the NVIDIA GPU")
                return m
        except Exception as e:
            log.warning("GPU not usable (%s) - using CPU", e)
    m = WhisperModel(cfg["model"], device="cpu",
                     compute_type="int8" if ctype in ("auto", "float16") else ctype)
    m.flowtype_device = "CPU"
    return m


def _ver(v):
    out = []
    for part in v.split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


# ---------------------------------------------------------------- the app
class App:
    def __init__(self):
        import numpy as np
        import pyperclip
        try:
            import sounddevice as sd
        except Exception as e:  # no audio system (e.g. a server without sound) - start anyway
            log.error("Audio system not available: %s", e)
            sd = None
        self.kb, self.np, self.pc, self.sd = ps.make_keys(), np, pyperclip, sd

        self.cfg = load_config()
        self.ui = queue.Queue()
        self.jobs = queue.Queue()
        self.lock = threading.Lock()
        self.recording = False
        self.rec_source = None
        self.rec_started = 0.0
        self.frames = []
        self.level = 0.0
        self.stream = None
        self.model = None
        self.model_ready = threading.Event()
        self.status = "Loading speech model..."
        self.stop_requested = False
        self.busy = False
        self.command = False       # Ctrl+Alt+Shift held -> command mode
        self.cancel_hold = False   # another key pressed while holding -> it was a shortcut, not dictation
        self.preview_text = ""
        self.rec_token = 0
        self.last_typed = ""
        self.model_lock = threading.Lock()
        self.icon = None
        self.update_info = None    # (version, setup_url) when a newer release exists
        self.tts = None
        self.local_lt = None
        self.root = None

    # ---- hotkeys
    def _key_groups(self, combo):
        groups = []
        for k in [p.strip().lower() for p in combo.split("+") if p.strip()]:
            if k in ("win", "super", "cmd"):
                k = "windows"
            cands = []
            for name in (k, "left " + k, "right " + k):
                if self.kb.valid(name):
                    cands.append(name)
            if not cands:
                raise ValueError(f"Unknown key '{k}' in hotkey '{combo}'")
            groups.append(cands)
        return groups

    def _pressed(self, groups):
        try:
            return all(any(self.kb.is_pressed(n) for n in g) for g in groups)
        except Exception:
            return False

    def hold_loop(self):
        combo = self.cfg["hotkey_hold"]
        try:
            groups = self._key_groups(combo)
        except ValueError as e:
            log.error("%s - falling back to 'right ctrl'", e)
            combo, groups = "right ctrl", self._key_groups("right ctrl")
        # Releasing Win or Alt on its own can open the Start menu / an app's menu bar;
        # a harmless dummy key press while they're held prevents that.
        uses_win = any(k in combo.lower().split("+") for k in ("windows", "win", "alt"))
        was = False
        while True:
            pressed = self._pressed(groups)
            if pressed and not was:
                if uses_win:
                    mask_win_key()
                if self.recording and self.rec_source == "toggle":
                    self.stop_recording()
                else:
                    self.start_recording("hold")
            elif not pressed and was:
                if self.recording and self.rec_source == "hold":
                    self.stop_recording()
            elif pressed and self.recording and self.rec_source == "hold" and not self.command \
                    and self.cfg.get("command_mode", True) and self._safe_pressed("shift"):
                self.command = True
                self.ui.put(("listening", "Command · say what to do"))
            was = pressed
            time.sleep(0.012)

    def _on_key(self, event_type, name):
        # Pressing a normal key while holding Ctrl+Alt means a shortcut (Ctrl+Alt+D, Ctrl+Alt+Del...), not dictation.
        if event_type == "down" and self.recording and self.rec_source == "hold" and name not in ps.MODIFIER_NAMES:
            self.cancel_hold = True

    def toggle(self):
        if self.recording:
            threading.Thread(target=self.stop_recording, daemon=True).start()
        else:
            threading.Thread(target=self.start_recording, args=("toggle",), daemon=True).start()

    # ---- audio
    def _request_stop(self):
        if self.recording and not self.stop_requested:
            self.stop_requested = True
            threading.Thread(target=self.stop_recording, daemon=True).start()

    def _on_audio(self, indata, frames, t, status):
        self.frames.append(indata.copy())
        self.level = float(self.np.sqrt(self.np.mean(indata ** 2)))
        now = time.time()
        limit = self.cfg.get("meeting_max_minutes", 180) * 60 if self.rec_source == "meeting" else self.cfg["max_seconds"]
        if self.recording and now - self.rec_started > limit:
            self._request_stop()

    def beep(self, freq):
        if self.cfg.get("sounds"):
            ps.beep(freq)

    def start_recording(self, source):
        import textproc as tp
        if source in ("hold", "toggle", "mouse") and tp.is_paused_app(foreground_title(), self.cfg.get("pause_in_apps")):
            self.ui.put(("info", "FlowType is paused in this app (Settings → Privacy)"))
            return
        with self.lock:
            if self.recording:
                return
            self.frames = []
            if self.sd is None:
                self.ui.put(("error", "No microphone / audio system found"))
                return
            try:
                self.stream = self.sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                    device=self.cfg.get("input_device"), callback=self._on_audio,
                )
                self.stream.start()
            except Exception as e:
                log.error("Microphone error: %s", e)
                self.ui.put(("error", "Microphone not available"))
                return
            self.recording = True
            self.rec_source = source
            self.rec_started = time.time()
            self.stop_requested = False
            self.command = False
            self.cancel_hold = False
            self.preview_text = ""
            self.rec_token += 1
            token = self.rec_token
        self.beep(880)
        import textproc as tp
        tone = self.tone_setting()
        label = "Listening" + ("" if tone == "auto" else " · " + tp.TONES[tone])
        prefix = {"toggle": "Hands-free · ", "meeting": "Meeting notes · "}.get(source, "")
        if source == "meeting":
            label = "recording - tray menu to stop"
        self.ui.put(("listening", prefix + label))
        self.set_icon(True)
        if self.cfg.get("live_preview", True) and self.model is not None and source != "meeting":
            threading.Thread(target=self.preview_loop, args=(token,), daemon=True).start()

    def stop_recording(self):
        with self.lock:
            if not self.recording:
                return
            self.recording = False
            stream, self.stream = self.stream, None
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        self.beep(660)
        self.set_icon(False)
        frames, self.frames = self.frames, []
        if not frames or self.cancel_hold:
            self.ui.put(("hide", ""))
            return
        audio = self.np.concatenate(frames).flatten()
        if len(audio) / SAMPLE_RATE < self.cfg["min_seconds"] or float(self.np.abs(audio).max()) < 0.004:
            self.ui.put(("hide", ""))
            return
        if self.rec_source == "meeting":
            self.ui.put(("working", "Writing up your meeting notes"))
            self.jobs.put((audio, "", "meeting"))
            self.update_tray()
            return
        mode = "command" if self.command else "dictate"
        self.ui.put(("working", "Understanding your command" if mode == "command" else "Transcribing"))
        self.jobs.put((audio, foreground_title(), mode))

    # ---- transcription
    def model_loader(self):
        try:
            self.ui.put(("working", "Getting speech model ready (first run can take a few minutes)"))
            self.model = load_model(self.cfg)
            self.ui.put(("info", f"FlowType ready - hold {self.cfg['hotkey_hold'].title()} and talk"))
            self.status = f"Ready ({getattr(self.model, 'flowtype_device', 'CPU')}) - hold {self.cfg['hotkey_hold']} to talk"
            log.info("Model %s loaded", self.cfg["model"])
        except Exception as e:
            self.status = "Model failed to load - see flowtype.log"
            log.error("Model load failed: %s\n%s", e, traceback.format_exc())
        self.model_ready.set()
        self.update_tray()

    def worker(self):
        import textproc as tp
        while True:
            audio, title, mode = self.jobs.get()
            self.busy = True
            try:
                t0 = time.time()
                if mode in ("meeting", "file"):
                    self.long_transcription(audio, mode)
                    continue
                raw = self.transcribe_local(audio)
                if not raw.strip():
                    self.ui.put(("hide", ""))
                    continue
                if mode == "command":
                    self.run_command(raw, title)
                    continue
                if tp.is_undo_command(raw):                   # "undo that"
                    self.wait_for_modifiers(("windows", "left windows", "alt", "shift", "ctrl", "cmd"))
                    self.kb.send(ps.MOD + "+z")
                    self.ui.put(("info", "Undone"))
                    continue
                raw, said_send = tp.split_send_command(raw)
                tone = tp.choose_tone(self.tone_setting(), title)
                kind = tone  # kept for the log line
                email = self.cfg.get("email_format", True) and tp.is_email_window(title)
                fixes, sugg = [], []
                snippet = tp.find_snippet(raw, self.cfg.get("snippets")) if raw else None
                if snippet is not None:                       # "insert my signature"
                    text = snippet
                elif tone == "code":                          # code tone: symbols, no capitals / full stops
                    text = tp.code_format(tp.FILLER_RE.sub(" ", tp.apply_replacements(raw, self.cfg.get("replacements"))))
                else:
                    if self.cfg.get("cleanup") == "llm":
                        self.ui.put(("working", "Polishing"))
                    if raw and self.cfg.get("spoken_punctuation"):
                        raw = tp.spoken_punctuation(raw)
                    text = tp.postprocess(raw, self.cfg, title, log) if raw else ""
                    if text and self.cfg.get("grammar_check", False) and tone != "plain":
                        self.ui.put(("working", "Checking grammar"))
                        try:
                            text, fixes, sugg = tp.grammar_fix(text, self.cfg)
                        except Exception as e:  # offline / LanguageTool busy -> type it as is
                            log.warning("Grammar check skipped: %s", e)
                    if text and tone == "professional":
                        text = tp.professional_style(text)
                    elif text and tone == "casual" and not email:
                        text = tp.casual_style(text)
                    if text and email:
                        text = tp.format_email(text)
                log.info("Transcribed %.1fs audio in %.1fs (tone=%s, snippet=%s, fixes=%d, suggestions=%d)",
                         len(audio) / SAMPLE_RATE, time.time() - t0, kind, snippet is not None, len(fixes), len(sugg))
                press_enter = said_send or (self.cfg.get("auto_send") and bool(text) and not email)
                if text:
                    self.type_text(text, sending=press_enter or tone == "code")
                    self.last_typed = text
                    self.save_history(raw, text, title, len(audio) / SAMPLE_RATE)
                if press_enter:
                    # Gmail / Outlook send with Ctrl+Enter; chats send with Enter
                    self.press_enter(ps.SEND_EMAIL if email else "enter")
                note = self.grammar_note(fixes, sugg)
                self.ui.put(("info", note) if note else ("hide", ""))
            except Exception as e:
                log.error("Transcription error: %s\n%s", e, traceback.format_exc())
                self.ui.put(("error", "Something went wrong - see log"))
            finally:
                self.busy = False

    # ---- 1. command mode: select text, hold Ctrl+Alt+Shift, say what to do
    def run_command(self, instruction, title):
        import textproc as tp
        if not tp.llm_configured(self.cfg):
            self.ui.put(("error", "Command mode needs an AI - tray menu → Command mode AI"))
            return
        terminal = tp.app_kind(title) == "code" and any(
            k in title.lower() for k in ("terminal", "powershell", "command prompt", "cmd.exe", "bash"))
        selection = "" if terminal else self.grab_selection()  # Ctrl+C would stop a program in a terminal
        self.ui.put(("working", "Rewriting your selection" if selection.strip() else "Writing"))
        try:
            out = tp.llm_command(instruction, selection, self.cfg, title)
        except Exception as e:
            log.error("Command mode AI failed: %s", e)
            self.ui.put(("error", "The AI didn't answer - check tray → Command mode AI"))
            return
        self.type_text(out, sending=True)
        self.last_typed = out
        self.save_history("[command] " + instruction, out, title, 0)
        self.ui.put(("info", "Done - press Ctrl+Z to undo" if selection.strip() else "Done"))
        log.info("Command: %r (selection %d chars)", instruction, len(selection))

    def grab_selection(self):
        """Copy whatever is selected in the active app, then put the clipboard back."""
        self.wait_for_modifiers(("windows", "left windows", "alt", "shift", "ctrl", "cmd"))
        try:
            old = self.pc.paste()
        except Exception:
            old = None
        marker = "\u2063flowtype-empty\u2063"
        self.pc.copy(marker)
        time.sleep(0.05)
        self.kb.send(ps.COPY)
        selection = ""
        for _ in range(12):
            time.sleep(0.05)
            try:
                cur = self.pc.paste()
            except Exception:
                cur = marker
            if cur != marker:
                selection = cur
                break
        if old is not None:
            try:
                self.pc.copy(old)
            except Exception:
                pass
        return selection

    # ---- 3. learn words: select the right spelling, press Ctrl+Alt+D
    def learn_selected(self):
        threading.Thread(target=self._learn, daemon=True).start()

    def _learn(self):
        import textproc as tp
        sel = self.grab_selection().strip()
        if not sel or "\n" in sel or len(sel) > 60:
            self.ui.put(("error", "Select a word or name first, then press " + self.cfg.get("hotkey_learn", "ctrl+alt+d").title()))
            return
        wrong, right = tp.learn_correction(sel, self.last_typed)
        dictionary = list(self.cfg.get("dictionary") or [])
        if right not in dictionary:
            dictionary.append(right)
        updates = {"dictionary": dictionary}
        if wrong:
            repl = dict(self.cfg.get("replacements") or {})
            repl[wrong.lower()] = right
            updates["replacements"] = repl
        self.cfg.update(updates)
        save_settings(updates)
        self.ui.put(("info", f"Learned: {wrong} → {right}" if wrong else f"Added to your words: {right}"))
        log.info("Learned word %r (fixes %r)", right, wrong)

    # ---- 6. live preview while you talk
    def preview_loop(self, token):
        while self.recording and self.rec_token == token:
            time.sleep(1.0)
            frames = list(self.frames)
            if not frames or self.model is None:
                continue
            audio = self.np.concatenate(frames).flatten()[-SAMPLE_RATE * 6:]
            if len(audio) < SAMPLE_RATE * 0.6 or float(self.np.abs(audio).max()) < 0.01:
                continue
            try:
                with self.model_lock:
                    if not (self.recording and self.rec_token == token):
                        break
                    segs, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                                    condition_on_previous_text=False, without_timestamps=True)
                    text = " ".join(x.text.strip() for x in segs).strip()
            except Exception as e:
                log.warning("Live preview stopped: %s", e)
                break
            if self.recording and self.rec_token == token:
                self.preview_text = text

    def watch_for_updates(self):
        """Running from source: restart by itself when flowtype.py / textproc.py change."""
        if FROZEN:
            return
        files = [os.path.join(APP_DIR, f) for f in ("flowtype.py", "textproc.py")]

        def stamp():
            return tuple(os.path.getmtime(f) if os.path.exists(f) else 0 for f in files)
        first = stamp()
        while True:
            time.sleep(3)
            if stamp() == first:
                continue
            time.sleep(2)  # let the file finish writing
            while self.recording or self.busy or not self.jobs.empty():
                time.sleep(1)
            log.info("Code updated - restarting")
            import subprocess
            ps.release_instance()
            subprocess.Popen([sys.executable, os.path.join(APP_DIR, "flowtype.py"), "--restarted"],
                             cwd=APP_DIR, close_fds=True)
            os._exit(0)

    def transcribe_local(self, audio):
        if not self.model_ready.is_set():
            self.ui.put(("working", "Loading model"))
        self.model_ready.wait()
        if self.model is None:
            raise RuntimeError("Speech model not loaded")
        prompt = None
        if self.cfg.get("dictionary"):
            prompt = "Glossary: " + ", ".join(self.cfg["dictionary"]) + "."
        with self.model_lock:
            segments, _ = self.model.transcribe(
                audio, language="en", beam_size=5, vad_filter=True,
                condition_on_previous_text=False, initial_prompt=prompt,
            )
            return " ".join(s.text.strip() for s in segments).strip()

    def grammar_note(self, fixes, sugg):
        parts = []
        if fixes:
            shown = ", ".join(f"{w} → {r}" for w, r in fixes[:3])
            parts.append(f"Fixed: {shown}" + (f" +{len(fixes) - 3}" if len(fixes) > 3 else ""))
        if sugg:
            w, opts = sugg[0]
            parts.append(f"Check: \"{w}\" → {' / '.join(opts)}" + (f" (+{len(sugg) - 1} more)" if len(sugg) > 1 else ""))
        return "   ·   ".join(parts)

    def toggle_grammar(self, *_):
        self.cfg["grammar_check"] = not self.cfg.get("grammar_check", False)
        save_settings({"grammar_check": self.cfg["grammar_check"]})
        self.ui.put(("info", "Grammar check ON" if self.cfg["grammar_check"] else "Grammar check OFF"))

    def toggle_email(self, *_):
        self.cfg["email_format"] = not self.cfg.get("email_format", True)
        save_settings({"email_format": self.cfg["email_format"]})
        self.ui.put(("info", "Email formatting ON" if self.cfg["email_format"] else "Email formatting OFF"))

    def wait_for_modifiers(self, keys=("windows", "left windows", "alt", "shift", "cmd")):
        # Wait for the user to let go of modifiers so Ctrl+V isn't read as Win+V etc.
        end = time.time() + 3
        while time.time() < end and any(self._safe_pressed(k) for k in keys):
            time.sleep(0.02)

    def press_enter(self, combo="enter"):
        self.wait_for_modifiers(("windows", "left windows", "alt", "shift", "ctrl", "cmd"))
        time.sleep(0.15)
        self.kb.send(combo)

    def toggle_auto_send(self, *_):
        self.cfg["auto_send"] = not self.cfg.get("auto_send", False)
        save_settings({"auto_send": self.cfg["auto_send"]})
        self.ui.put(("info", "Auto-send ON - Enter is pressed after each message" if self.cfg["auto_send"] else "Auto-send OFF"))

    def type_text(self, text, sending=False):
        if self.cfg.get("add_trailing_space") and not sending and not text.endswith(("\n", " ")):
            text += " "
        self.wait_for_modifiers()
        old = None
        if self.cfg.get("restore_clipboard"):
            try:
                old = self.pc.paste()
            except Exception:
                old = None
        self.pc.copy(text)
        time.sleep(0.04)
        self.kb.send(ps.PASTE)
        if old is not None:
            time.sleep(0.35)
            try:
                self.pc.copy(old)
            except Exception:
                pass

    def _safe_pressed(self, k):
        return self.kb.is_pressed(k)

    def save_history(self, raw, text, title, secs):
        if not self.cfg.get("save_history"):
            return
        try:
            with open(HISTORY_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "time": datetime.datetime.now().isoformat(timespec="seconds"),
                    "seconds": round(secs, 1), "app": title, "raw": raw, "text": text,
                }, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning("History write failed: %s", e)


    # ---- meeting notes & file transcription (long audio, with timestamps)
    def meetings_dir(self):
        d = self.cfg.get("meeting_folder") or os.path.join(os.path.expanduser("~"), "Documents", "FlowType")
        os.makedirs(d, exist_ok=True)
        return d

    def long_transcription(self, audio, mode):
        import textproc as tp
        if not self.model_ready.is_set():
            self.ui.put(("working", "Loading model"))
        self.model_ready.wait()
        if self.model is None:
            raise RuntimeError("Speech model not loaded")
        src = audio if mode == "file" else None
        self.ui.put(("working", "Transcribing " + (os.path.basename(src) if src else "your meeting")))
        lines, plain = [], []
        with self.model_lock:
            segments, info = self.model.transcribe(audio, language="en", beam_size=5, vad_filter=True)
            for seg in segments:
                t = int(seg.start)
                stamp = f"{t // 3600:d}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"
                text = seg.text.strip()
                if text:
                    lines.append(f"[{stamp}] {text}")
                    plain.append(text)
        if not plain:
            self.ui.put(("error", "No speech found"))
            return
        transcript = "\n".join(lines)
        now = datetime.datetime.now()
        if mode == "file":
            out = os.path.splitext(src)[0] + " - transcript.txt"
            with open(out, "w", encoding="utf-8") as f:
                f.write(transcript + "\n")
        else:
            summary = ""
            if tp.llm_configured(self.cfg):
                self.ui.put(("working", "Summarising with AI"))
                try:
                    summary = tp.llm_chat(tp.MEETING_SYSTEM, " ".join(plain)[:60000], self.cfg,
                                          timeout=120, max_tokens=1500).strip()
                except Exception as e:
                    log.warning("Meeting summary failed: %s", e)
            out = os.path.join(self.meetings_dir(), now.strftime("Meeting %Y-%m-%d %H-%M.md"))
            with open(out, "w", encoding="utf-8") as f:
                f.write(f"# Meeting notes — {now:%A %d %B %Y, %H:%M}\n\n")
                if summary:
                    f.write(summary + "\n\n")
                else:
                    f.write("_Turn on an AI in the tray menu (Command mode AI) to get a summary and action items here._\n\n")
                f.write("## Transcript\n\n" + transcript + "\n")
        log.info("Long transcription (%s) written to %s", mode, out)
        self.ui.put(("info", "Saved: " + os.path.basename(out)))
        ps.open_path(out)

    def toggle_meeting(self, *_):
        if self.recording and self.rec_source == "meeting":
            threading.Thread(target=self.stop_recording, daemon=True).start()
        elif not self.recording:
            threading.Thread(target=self.start_recording, args=("meeting",), daemon=True).start()
        self.update_tray()

    def transcribe_file(self, *_):
        self.ui.put(("pick_file", None))   # file dialog must open on the UI thread

    def file_picked(self, path):
        if path:
            self.jobs.put((path, "", "file"))

    # ---- paste last dictation again
    def paste_last(self):
        text = self.last_typed
        if not text and os.path.exists(HISTORY_PATH):
            try:
                with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                    last = f.readlines()[-1]
                text = json.loads(last).get("text", "")
            except Exception:
                text = ""
        if text:
            threading.Thread(target=self.type_text, args=(text,), daemon=True).start()
        else:
            self.ui.put(("error", "Nothing dictated yet"))

    # ---- read selected text aloud
    def read_aloud(self, *_):
        threading.Thread(target=self._read_aloud, daemon=True).start()

    def _read_aloud(self):
        if self.tts is not None:          # pressed again while speaking -> stop
            self.stop_speaking()
            return
        text = self.grab_selection().strip()
        if not text:
            self.ui.put(("error", "Select some text first, then press " + self.cfg.get("hotkey_read_aloud", "ctrl+alt+r").title()))
            return
        self.ui.put(("info", "Reading aloud - press again to stop"))
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", int(self.cfg.get("read_aloud_rate", 185)))
            self.tts = engine
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            log.info("pyttsx3 unavailable (%s) - using the system voice command", e)
            import shutil
            import subprocess
            if ps.IS_WIN:   # Windows' built-in voice via PowerShell; the text goes in through stdin
                proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-Command",
                     "Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                     "$s.Speak([Console]::In.ReadToEnd())"],
                    stdin=subprocess.PIPE, creationflags=0x08000000)
                self.tts = proc
                proc.communicate(text.encode("utf-8", "replace"))
                return
            cmd = ["say"] if shutil.which("say") else ["spd-say", "-w"] if shutil.which("spd-say") else \
                ["espeak"] if shutil.which("espeak") else None
            if cmd is None:
                self.ui.put(("error", "No text-to-speech voice found on this computer"))
                return
            proc = subprocess.Popen(cmd + [text])
            self.tts = proc
            proc.wait()
        finally:
            self.tts = None

    def stop_speaking(self):
        tts, self.tts = self.tts, None
        try:
            (tts.terminate if hasattr(tts, "terminate") else tts.stop)()
        except Exception:
            pass

    # ---- mouse button / foot pedal (most pedals act as a mouse button or a key)
    def mouse_loop(self):
        btn = (self.cfg.get("mouse_button") or "").lower().strip()
        if not btn:
            return
        try:
            from pynput import mouse
        except Exception as e:
            log.error("Mouse trigger needs pynput: %s", e)
            return

        def down():
            if not self.recording:
                threading.Thread(target=self.start_recording, args=("mouse",), daemon=True).start()

        def up():
            if self.recording and self.rec_source == "mouse":
                threading.Thread(target=self.stop_recording, daemon=True).start()

        kwargs = {}
        if ps.IS_WIN:
            # handle the button here and swallow it, so it doesn't also go Back/Forward in a browser
            codes = {"middle": (0x0207, 0x0208, None), "x1": (0x020B, 0x020C, 1), "x2": (0x020B, 0x020C, 2)}
            if btn not in codes:
                log.error("mouse_button must be middle, x1 or x2 (got %r)", btn)
                return
            d_msg, u_msg, which = codes[btn]
            holder = {}

            def filt(msg, data):
                if msg in (d_msg, u_msg) and (which is None or (data.mouseData >> 16) == which):
                    (down if msg == d_msg else up)()
                    holder["l"].suppress_event()
                return True
            kwargs["win32_event_filter"] = filt
            listener = mouse.Listener(**kwargs)
            holder["l"] = listener
        else:
            names = {"middle": "middle", "x1": "x1", "x2": "x2", "back": "x1", "forward": "x2"}
            target = getattr(mouse.Button, names.get(btn, btn), None) or getattr(mouse.Button, "button8", None)

            def on_click(x, y, button, pressed):
                if button == target:
                    (down if pressed else up)()
            listener = mouse.Listener(on_click=on_click)
        listener.start()
        log.info("Mouse trigger on button %s", btn)

    def set_mouse_button(self, btn):
        self.cfg["mouse_button"] = btn
        save_settings({"mouse_button": btn})
        self.ui.put(("info", "Mouse trigger " + (btn.upper() + " - restarting" if btn else "off - restarting")))
        threading.Thread(target=lambda: (time.sleep(1.2), self.restart()), daemon=True).start()

    # ---- speed vs accuracy
    MODELS = {"base.en": "Fast (base.en)", "small.en": "Balanced (small.en)", "large-v3-turbo": "Most accurate (large-v3-turbo)"}

    def set_model(self, name):
        if name == self.cfg.get("model"):
            return

        def run():
            self.cfg["model"] = name
            save_settings({"model": name})
            self.ui.put(("working", "Switching to " + self.MODELS.get(name, name) + " (first time downloads it)"))
            try:
                m = load_model(self.cfg)
                with self.model_lock:
                    self.model = m
                self.status = f"Ready ({getattr(m, 'flowtype_device', 'CPU')}) - {self.MODELS.get(name, name)}"
                self.ui.put(("info", "Now using " + self.MODELS.get(name, name)))
            except Exception as e:
                log.error("Model switch failed: %s", e)
                self.ui.put(("error", "Could not load that model - see log"))
            self.update_tray()
        threading.Thread(target=run, daemon=True).start()

    # ---- grammar: off / online / fully offline
    def set_grammar(self, mode):
        on = mode != "off"
        self.cfg["grammar_check"] = on
        if on:
            self.cfg["grammar_mode"] = mode
        save_settings({"grammar_check": on, "grammar_mode": self.cfg.get("grammar_mode", "online")})
        self.update_tray()
        if mode == "offline":
            threading.Thread(target=self.start_local_grammar, daemon=True).start()
        else:
            self.ui.put(("info", {"off": "Grammar check OFF", "online": "Grammar check ON (online)"}[mode]))

    def grammar_state(self):
        return self.cfg.get("grammar_mode", "online") if self.cfg.get("grammar_check") else "off"

    def start_local_grammar(self):
        from grammar_local import LocalLanguageTool
        if self.local_lt is None:
            self.local_lt = LocalLanguageTool(DATA_DIR, log, self.ui)
        if self.local_lt.ensure():
            self.ui.put(("info", "Offline grammar ready - nothing leaves your computer"))

    # ---- updates
    def check_updates(self):
        if not self.cfg.get("check_updates", True):
            return
        import urllib.request
        time.sleep(25)
        while True:
            try:
                req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                                             headers={"User-Agent": "FlowType", "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    rel = json.loads(r.read().decode("utf-8"))
                latest = rel.get("tag_name", "").lstrip("vV")
                if latest and _ver(latest) > _ver(APP_VERSION):
                    setup = next((a["browser_download_url"] for a in rel.get("assets", [])
                                  if a.get("name") == "FlowType-Setup.exe"), "")
                    first = self.update_info is None
                    self.update_info = (latest, setup, rel.get("html_url", ""))
                    self.update_tray()
                    if first:
                        self.ui.put(("info", f"FlowType {latest} is available - tray menu → Update"))
                        log.info("Update available: %s", latest)
            except Exception as e:
                log.info("Update check skipped: %s", e)
            time.sleep(12 * 3600)

    def install_update(self, *_):
        if not self.update_info:
            return
        latest, setup, page = self.update_info
        if not (FROZEN and ps.IS_WIN and setup):
            ps.open_path(page or f"https://github.com/{GITHUB_REPO}/releases/latest")
            return

        def run():
            import tempfile
            import urllib.request
            import subprocess
            self.ui.put(("working", f"Downloading FlowType {latest}"))
            try:
                dest = os.path.join(tempfile.gettempdir(), f"FlowType-Setup-{latest}.exe")
                urllib.request.urlretrieve(setup, dest)
                subprocess.Popen([dest, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], close_fds=True)
                self.quit()
            except Exception as e:
                log.error("Update failed: %s", e)
                self.ui.put(("error", "Update download failed - opening the release page"))
                ps.open_path(page)
        threading.Thread(target=run, daemon=True).start()

    def restart(self, *_):
        import subprocess
        ps.release_instance()
        if FROZEN:
            subprocess.Popen([sys.executable, "--no-install"], cwd=APP_DIR, close_fds=True)
        else:
            subprocess.Popen([sys.executable, os.path.join(APP_DIR, "flowtype.py"), "--restarted"], cwd=APP_DIR, close_fds=True)
        try:
            self.icon.stop()
        except Exception:
            pass
        os._exit(0)

    def stats_text(self):
        import textproc as tp
        try:
            return tp.stats_line(tp.compute_stats(HISTORY_PATH))
        except Exception:
            return "This week: -"

    def open_settings(self, *_):
        self.ui.put(("settings", None))

    def show_settings(self):
        import settings_window
        settings_window.open_settings(self.root, self, save_settings, HISTORY_PATH,
                                      os.path.join(APP_DIR, "PRIVACY.md"), APP_VERSION)

    # ---- tray
    def _icon_image(self, recording):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((2, 2, 62, 62), fill=(220, 38, 38) if recording else (79, 70, 229))
        d.rounded_rectangle((25, 12, 39, 38), radius=7, fill="white")
        d.arc((17, 20, 47, 46), start=0, end=180, fill="white", width=4)
        d.line((32, 46, 32, 53), fill="white", width=4)
        d.line((24, 53, 40, 53), fill="white", width=4)
        return img

    def set_icon(self, recording):
        if self.icon:
            try:
                self.icon.icon = self._icon_image(recording)
            except Exception:
                pass

    def update_tray(self):
        if self.icon:
            try:
                self.icon.title = f"{APP_NAME}: {self.status}"
                self.icon.update_menu()
            except Exception:
                pass

    def reload_config(self, *_):
        old_model = (self.cfg["model"], self.cfg["device"], self.cfg["hotkey_hold"], self.cfg["hotkey_toggle"])
        self.cfg = load_config()
        new = (self.cfg["model"], self.cfg["device"], self.cfg["hotkey_hold"], self.cfg["hotkey_toggle"])
        if new != old_model:
            self.ui.put(("error", "Restart FlowType to apply model/hotkey changes"))
        else:
            self.ui.put(("info", "Settings reloaded"))

    # ---- AI for command mode
    LLM_PRESETS = {
        "ollama": {"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.2", "api_key": ""},
        "groq": {"provider": "groq", "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-20b"},
        "anthropic": {"provider": "anthropic", "base_url": "", "model": "claude-haiku-5-5"},
    }
    LLM_NAMES = {"": "Off", "ollama": "Ollama (free, on this PC)", "groq": "Groq (free key)",
                 "anthropic": "Claude (Anthropic key)", "openai": "Custom (OpenAI-compatible)"}

    def set_llm(self, which):
        def run():
            llm = dict(self.cfg.get("llm") or {})
            if which == "":
                llm["provider"] = ""
            else:
                preset = dict(self.LLM_PRESETS[which])
                if which in ("groq", "anthropic"):
                    where = "console.groq.com/keys (free)" if which == "groq" else "console.anthropic.com"
                    key = self.ask(f"Paste your API key from {where}. It is stored only on this computer.")
                    if not key:
                        return
                    preset["api_key"] = key.strip()
                llm.update(preset)
            self.cfg["llm"] = llm
            save_settings({"llm": llm})
            self.update_tray()
            msg = {"": "Command mode AI off",
                   "ollama": "Using Ollama - install it from ollama.com and run: ollama pull llama3.2"}.get(
                which, "Command mode AI ready - select text, hold Ctrl+Alt+Shift and speak")
            self.ui.put(("info", msg))
        threading.Thread(target=run, daemon=True).start()

    def tone_setting(self):
        t = self.cfg.get("tone")
        if not t:  # older settings files
            t = "auto" if self.cfg.get("tone_by_app", True) else "plain"
        return t

    def set_tone(self, tone):
        import textproc as tp
        self.cfg["tone"] = tone
        save_settings({"tone": tone})
        self.update_tray()
        self.ui.put(("info", "Tone: " + tp.TONES[tone] + (" - casual in chats, code in editors, formal in email"
                                                            if tone == "auto" else " everywhere")))

    def ask(self, prompt):
        """Input box: the system's own if it has one, otherwise a small FlowType window."""
        value = ps.ask_text_native(prompt)
        if value is not None:
            return value
        answer = queue.Queue()
        self.ui.put(("ask", (prompt, answer)))
        try:
            return answer.get(timeout=600) or ""
        except queue.Empty:
            return ""

    def toggle_key(self, key, on_msg, off_msg):
        def f(*_):
            self.cfg[key] = not self.cfg.get(key, True)
            save_settings({key: self.cfg[key]})
            self.ui.put(("info", on_msg if self.cfg[key] else off_msg))
        return f

    def start_tray(self):
        import pystray
        M = pystray.MenuItem

        from textproc import TONES

        def tone_item(t):
            return M(TONES[t], lambda *_: self.set_tone(t),
                     checked=lambda item: self.tone_setting() == t, radio=True)

        def llm_item(code):
            return M(self.LLM_NAMES[code], lambda *_: self.set_llm(code),
                     checked=lambda item: (self.cfg.get("llm") or {}).get("provider", "") == code, radio=True)

        def model_item(name):
            return M(self.MODELS[name], lambda *_: self.set_model(name),
                     checked=lambda item: self.cfg.get("model") == name, radio=True)

        def grammar_item(mode, label):
            return M(label, lambda *_: self.set_grammar(mode),
                     checked=lambda item: self.grammar_state() == mode, radio=True)

        def mouse_item(btn, label):
            return M(label, lambda *_: self.set_mouse_button(btn),
                     checked=lambda item: (self.cfg.get("mouse_button") or "") == btn, radio=True)

        menu = pystray.Menu(
            M(lambda item: self.status, None, enabled=False),
            M(lambda item: self.stats_text(), None, enabled=False),
            M(lambda item: f"Update to FlowType {self.update_info[0]}" if self.update_info else "Up to date",
              self.install_update, visible=lambda item: bool(self.update_info)),
            pystray.Menu.SEPARATOR,
            M("Settings…", self.open_settings, default=True),
            M(lambda item: "Stop meeting notes" if self.recording and self.rec_source == "meeting" else "Start meeting notes",
              self.toggle_meeting),
            M("Transcribe an audio / video file…", self.transcribe_file),
            M(lambda item: f"Paste last dictation ({self.cfg.get('hotkey_paste_last', 'ctrl+alt+v').title()})",
              lambda *_: self.paste_last()),
            M(lambda item: f"Read selection aloud ({self.cfg.get('hotkey_read_aloud', 'ctrl+alt+r').title()})", self.read_aloud),
            pystray.Menu.SEPARATOR,
            M(lambda item: "Speed: " + self.MODELS.get(self.cfg.get("model"), self.cfg.get("model")),
              pystray.Menu(*[model_item(n) for n in self.MODELS])),
            M(lambda item: "Tone: " + TONES.get(self.tone_setting(), "Auto"),
              pystray.Menu(*[tone_item(t) for t in ("auto", "casual", "professional", "code", "plain")])),
            M(lambda item: "Grammar: " + {"off": "Off", "online": "Online", "offline": "Offline"}[self.grammar_state()],
              pystray.Menu(grammar_item("off", "Off"), grammar_item("online", "Online (LanguageTool)"),
                           grammar_item("offline", "Offline (on this computer, needs Java)"))),
            M(lambda item: "Command mode AI: " + self.LLM_NAMES.get((self.cfg.get("llm") or {}).get("provider", ""), "Custom"),
              pystray.Menu(*[llm_item(c) for c in ("", "ollama", "groq", "anthropic")])),
            M("Mouse / foot-pedal trigger", pystray.Menu(
                mouse_item("", "Off"), mouse_item("middle", "Middle button (hold)"),
                mouse_item("x1", "Back side button (hold)"), mouse_item("x2", "Forward side button (hold)"))),
            M("Spoken punctuation (say \"comma\", \"new line\")",
              self.toggle_key("spoken_punctuation", "Spoken punctuation ON", "Spoken punctuation OFF"),
              checked=lambda item: bool(self.cfg.get("spoken_punctuation"))),
            M("Live preview while talking", self.toggle_key("live_preview", "Live preview ON", "Live preview OFF"),
              checked=lambda item: bool(self.cfg.get("live_preview", True))),
            M("Email formatting in Gmail / Outlook", self.toggle_email,
              checked=lambda item: bool(self.cfg.get("email_format", True))),
            M("Auto-send (press Enter after each message)", self.toggle_auto_send,
              checked=lambda item: bool(self.cfg.get("auto_send"))),
            pystray.Menu.SEPARATOR,
            M("Open meeting notes folder", lambda *_: ps.open_path(self.meetings_dir())),
            M("Open history", lambda *_: os.path.exists(HISTORY_PATH) and ps.open_path(HISTORY_PATH)),
            M("Open log", lambda *_: ps.open_path(LOG_PATH)),
            M("Restart FlowType", self.restart),
            pystray.Menu.SEPARATOR,
            M("Quit", self.quit),
        )
        self.icon = pystray.Icon(APP_NAME, self._icon_image(False), f"{APP_NAME}: {self.status}", menu)
        self.icon.run_detached()

    def quit(self, *_):
        self.stop_speaking()
        if self.local_lt is not None:
            self.local_lt.stop()
        try:
            self.icon.stop()
        except Exception:
            pass
        os._exit(0)

    # ---- main
    def run(self):
        import tkinter as tk
        ps.set_dpi_aware()
        root = tk.Tk()
        self.root = root
        from overlay import Overlay
        overlay = Overlay(root, self, user32)
        threading.Thread(target=self.model_loader, daemon=True).start()
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.hold_loop, daemon=True).start()
        threading.Thread(target=self.watch_for_updates, daemon=True).start()
        threading.Thread(target=self.check_updates, daemon=True).start()
        threading.Thread(target=self.mouse_loop, daemon=True).start()
        if self.cfg.get("grammar_check") and self.cfg.get("grammar_mode") == "offline":
            threading.Thread(target=self.start_local_grammar, daemon=True).start()
        try:
            self.kb.add_hotkey(self.cfg["hotkey_toggle"], self.toggle)
        except Exception as e:
            log.error("Toggle hotkey '%s' not registered: %s", self.cfg["hotkey_toggle"], e)
        try:
            self.kb.add_hotkey(self.cfg.get("hotkey_learn", "ctrl+alt+d"), self.learn_selected)
        except Exception as e:
            log.error("Learn hotkey not registered: %s", e)
        for key, default, fn in (("hotkey_paste_last", "ctrl+alt+v", self.paste_last),
                                 ("hotkey_read_aloud", "ctrl+alt+r", self.read_aloud)):
            try:
                if self.cfg.get(key, default):
                    self.kb.add_hotkey(self.cfg.get(key, default), fn)
            except Exception as e:
                log.error("Hotkey %s not registered: %s", key, e)
        self.kb.hook(self._on_key)
        self.start_tray()
        log.info("FlowType started")
        overlay.tick()
        root.mainloop()


def make_icon_file():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 248, 248), fill=(79, 70, 229))
    d.rounded_rectangle((100, 48, 156, 152), radius=28, fill="white")
    d.arc((68, 80, 188, 184), start=0, end=180, fill="white", width=16)
    d.line((128, 184, 128, 212), fill="white", width=16)
    d.line((96, 212, 160, 212), fill="white", width=16)
    img.save(os.path.join(APP_DIR, "flowtype.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])


message_box = ps.message_box


def make_shortcuts(exe):
    import subprocess
    ps = (
        "$w=New-Object -ComObject WScript.Shell; "
        "foreach($p in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'),"
        "[Environment]::GetFolderPath('Startup'))){ $s=$w.CreateShortcut($p+'\\FlowType.lnk'); "
        f"$s.TargetPath='{exe}'; $s.WorkingDirectory='{os.path.dirname(exe)}'; "
        "$s.Description='FlowType voice typing'; $s.Save() }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000, timeout=60)


def self_install():
    r"""When FlowType.exe is run from a download/unzip folder, copy it into
    %LOCALAPPDATA%\Programs\FlowType, add shortcuts, start it from there.
    Returns True if this process should exit."""
    import shutil
    import subprocess
    here = os.path.normcase(os.path.abspath(APP_DIR))
    if here == os.path.normcase(os.path.abspath(INSTALL_DIR)):
        return False
    if os.path.exists(os.path.join(APP_DIR, "portable.txt")):
        return False
    answer = ctypes.windll.user32.MessageBoxW(
        None,
        "Install FlowType for your Windows account?\n\n"
        "Yes: copies FlowType to your user folder and adds Start-menu and Desktop shortcuts, "
        "and starts it when you sign in (you can remove it later).\n\n"
        "No: just run it from this folder, without changing anything on your PC.",
        "FlowType", 0x04 | 0x20)  # Yes/No, question icon
    if answer != 6:  # not Yes -> run portable, don't touch the system
        with open(os.path.join(APP_DIR, "portable.txt"), "w") as f:
            f.write("FlowType runs from this folder without installing. Delete this file to be asked again.\n")
        return False
    # stop an older installed copy so its files can be replaced
    subprocess.run(["taskkill", "/f", "/im", "FlowType.exe", "/fi", f"PID ne {os.getpid()}"],
                   capture_output=True, creationflags=0x08000000)
    time.sleep(1)
    try:
        shutil.copytree(APP_DIR, INSTALL_DIR, dirs_exist_ok=True)
        exe = os.path.join(INSTALL_DIR, "FlowType.exe")
        make_shortcuts(exe)
        subprocess.Popen([exe], close_fds=True)
    except Exception as e:
        log.error("Install failed: %s\n%s", e, traceback.format_exc())
        message_box(f"FlowType could not install itself:\n{e}")
        return True
    message_box(
        "FlowType is installed and running.\n\n"
        "How to use: click where you want to type, HOLD Ctrl + Alt, speak, then let go.\n\n"
        "First time only: it downloads the speech model (about 500 MB), which takes a few minutes.\n\n"
        "Settings (grammar check, email formatting): click the ^ arrow next to the clock and RIGHT-click the purple mic.\n"
        "It also starts automatically when Windows starts.",
    )
    return True


def selftest(out_path):
    """Used by the build script: checks every bundled piece loads and transcribes."""
    lines = []
    try:
        import numpy as np
        import pyperclip, pystray, tkinter  # noqa: F401
        try:
            import sounddevice  # noqa: F401
            lines.append("audio ok")
        except Exception as e:  # e.g. CI machines without a sound server
            lines.append("audio: not available here (%s)" % str(e).split(":")[0])
        if ps.IS_WIN:
            import keyboard  # noqa: F401
        lines.append("platform: " + ps.PLATFORM)
        from PIL import Image  # noqa: F401
        import textproc, overlay, settings_window, grammar_local  # noqa: F401
        import pynput  # noqa: F401  (mouse / foot-pedal trigger)
        try:
            import pyttsx3  # noqa: F401
            lines.append("tts ok")
        except Exception as e:
            lines.append("tts: not available here (%s)" % e)
        lines.append("imports ok")
        cfg = load_config()
        m = load_model(cfg)
        segs, _ = m.transcribe(np.zeros(16000, dtype="float32"), language="en", vad_filter=True)
        list(segs)
        lines.append("model ok")
        lines.append("SELFTEST OK")
    except Exception as e:
        lines.append("SELFTEST FAILED: " + repr(e))
        lines.append(traceback.format_exc())
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    if "--selftest" in sys.argv:
        selftest(sys.argv[sys.argv.index("--selftest") + 1])
        return
    if FROZEN and ps.IS_WIN and "--no-install" not in sys.argv and self_install():
        return
    if "--make-icon" in sys.argv:
        make_icon_file()
        return
    if "--download-model" in sys.argv:
        cfg = load_config()
        print(f"Downloading/loading Whisper model '{cfg['model']}' (one time, a few hundred MB)...")
        load_model(cfg)
        print("Model ready.")
        return
    if not single_instance():
        return
    try:
        App().run()
    except Exception as e:
        log.error("Fatal: %s\n%s", e, traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
