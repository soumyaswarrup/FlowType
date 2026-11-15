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
    "grammar_check": True,
    "grammar_language": "en-US",
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


# ---------------------------------------------------------------- the app
class App:
    def __init__(self):
        import numpy as np
        import pyperclip
        import sounddevice as sd
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
        if self.recording and now - self.rec_started > self.cfg["max_seconds"]:
            self._request_stop()

    def beep(self, freq):
        if self.cfg.get("sounds"):
            ps.beep(freq)

    def start_recording(self, source):
        with self.lock:
            if self.recording:
                return
            self.frames = []
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
        prefix = "Hands-free · " if source == "toggle" else ""
        self.ui.put(("listening", prefix + label))
        self.set_icon(True)
        if self.cfg.get("live_preview", True) and self.model is not None:
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
                raw = self.transcribe_local(audio)
                if not raw.strip():
                    self.ui.put(("hide", ""))
                    continue
                if mode == "command":
                    self.run_command(raw, title)
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
                    text = tp.postprocess(raw, self.cfg, title, log) if raw else ""
                    if text and self.cfg.get("grammar_check", True) and tone != "plain":
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
        self.cfg["grammar_check"] = not self.cfg.get("grammar_check", True)
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

        menu = pystray.Menu(
            M(lambda item: self.status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            M(lambda item: "Command mode AI: " + self.LLM_NAMES.get((self.cfg.get("llm") or {}).get("provider", ""), "Custom"),
              pystray.Menu(*[llm_item(c) for c in ("", "ollama", "groq", "anthropic")])),
            M("Live preview while talking", self.toggle_key("live_preview", "Live preview ON", "Live preview OFF"),
              checked=lambda item: bool(self.cfg.get("live_preview", True))),
            M(lambda item: "Tone: " + TONES.get(self.tone_setting(), "Auto"),
              pystray.Menu(*[tone_item(t) for t in ("auto", "casual", "professional", "code", "plain")])),
            M("Grammar check (fix + suggest)", self.toggle_grammar,
              checked=lambda item: bool(self.cfg.get("grammar_check", True))),
            M("Email formatting in Gmail / Outlook", self.toggle_email,
              checked=lambda item: bool(self.cfg.get("email_format", True))),
            M("Auto-send (press Enter after each message)", self.toggle_auto_send,
              checked=lambda item: bool(self.cfg.get("auto_send"))),
            pystray.Menu.SEPARATOR,
            M("Edit snippets, words & settings", lambda *_: ps.open_path(CONFIG_PATH)),
            M("Reload settings", self.reload_config),
            M("Open history", lambda *_: os.path.exists(HISTORY_PATH) and ps.open_path(HISTORY_PATH)),
            M("Open log", lambda *_: ps.open_path(LOG_PATH)),
            pystray.Menu.SEPARATOR,
            M("Quit", self.quit),
        )
        self.icon = pystray.Icon(APP_NAME, self._icon_image(False), f"{APP_NAME}: {self.status}", menu)
        self.icon.run_detached()

    def quit(self, *_):
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
        overlay = Overlay(root, self)
        threading.Thread(target=self.model_loader, daemon=True).start()
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.hold_loop, daemon=True).start()
        threading.Thread(target=self.watch_for_updates, daemon=True).start()
        try:
            self.kb.add_hotkey(self.cfg["hotkey_toggle"], self.toggle)
        except Exception as e:
            log.error("Toggle hotkey '%s' not registered: %s", self.cfg["hotkey_toggle"], e)
        try:
            self.kb.add_hotkey(self.cfg.get("hotkey_learn", "ctrl+alt+d"), self.learn_selected)
        except Exception as e:
            log.error("Learn hotkey not registered: %s", e)
        self.kb.hook(self._on_key)
        self.start_tray()
        log.info("FlowType started")
        overlay.tick()
        root.mainloop()


class Overlay:
    """Click-through pill at the bottom of the screen that never takes focus.
    Listening: pulsing mic + live colour waveform + timer. Working: spinner. Done: tick / error."""
    KEY = "#010203"          # transparent colour key
    BG = "#14151c"
    EDGE = "#2a2c3a"
    TEXT = "#f3f4f6"
    MUTED = "#9ca3af"
    RED = "#ef4444"
    GREEN = "#22c55e"
    GRAD = ["#a78bfa", "#8b5cf6", "#6366f1", "#3b82f6", "#0ea5e9", "#22d3ee"]
    BARS = 23

    def __init__(self, root, app):
        import tkinter as tk
        import tkinter.font as tkfont
        self.root, self.app = root, app
        self.state, self.text, self.until = "hide", "", 0
        self.shown = "hide"   # what's drawn (kept while fading out)
        s = root.winfo_fpixels("1i") / 96.0
        self.s = s
        self.H = int(50 * s)
        self.W = int(300 * s)
        self.alpha = 0.0
        self.pos = None
        self.history = [0.0] * (self.BARS // 2 + 1)
        self.smooth = [0.0] * self.BARS
        self.f_label = tkfont.Font(family=ps.UI_FONT_BOLD, size=10, weight="normal" if ps.IS_WIN else "bold")
        self.f_small = tkfont.Font(family=ps.UI_FONT, size=9)
        self.colors = [self._grad(i / (self.BARS - 1)) for i in range(self.BARS)]
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.0)
        if ps.IS_WIN:                      # see-through corners
            root.configure(bg=self.KEY)
            root.attributes("-transparentcolor", self.KEY)
        elif ps.IS_MAC:
            self.KEY = "systemTransparent"
            try:
                root.attributes("-transparent", True)
            except Exception:
                self.KEY = self.BG
            root.configure(bg=self.KEY)
        else:                              # Linux: no colour-key transparency; corners match the pill
            self.KEY = self.BG
            root.configure(bg=self.KEY)
        self.c = tk.Canvas(root, width=self.W, height=self.H, bg=self.KEY, highlightthickness=0)
        self.c.pack()
        self._place()
        root.update_idletasks()
        try:
            hwnd = user32.GetParent(root.winfo_id())
            ex = user32.GetWindowLongW(hwnd, -20)
            # LAYERED | TRANSPARENT (click-through) | TOOLWINDOW (no taskbar) | NOACTIVATE
            user32.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x08000000)
        except Exception:
            pass

    # ---- helpers
    @staticmethod
    def _hex(c):
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))

    def _mix(self, a, b, t):
        a, b = self._hex(a), self._hex(b)
        return "#%02x%02x%02x" % tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))

    def _grad(self, t):
        n = len(self.GRAD) - 1
        k = min(int(t * n), n - 1)
        return self._mix(self.GRAD[k], self.GRAD[k + 1], t * n - k)

    def _place(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        slide = int((1 - min(self.alpha / 0.96, 1)) * 12 * self.s)
        pos = (self.W, self.H, (sw - self.W) // 2, sh - self.H - int(84 * self.s) + slide)
        if pos != self.pos:
            self.pos = pos
            self.root.geometry("%dx%d+%d+%d" % pos)
            self.c.config(width=self.W, height=self.H)

    def _pill(self, fill, edge):
        c, W, H = self.c, self.W, self.H
        for (col, inset) in ((edge, 0), (fill, max(1, int(1.5 * self.s)))):
            r = H / 2 - inset
            c.create_oval(inset, inset, H - inset, H - inset, fill=col, outline=col)
            c.create_oval(W - H + inset, inset, W - inset, H - inset, fill=col, outline=col)
            c.create_rectangle(H / 2, inset, W - H / 2, H - inset, fill=col, outline=col)

    # ---- drawing
    def draw(self):
        c, s, H = self.c, self.s, self.H
        c.delete("all")
        if self.state == "hide" and self.alpha <= 0.01:
            return
        t = time.time()
        cy = H / 2
        st = self.shown
        preview = (self.app.preview_text or "").strip() if st == "listening" else ""
        if st == "listening":
            self.W = int((560 if preview else 310) * s)
        else:
            self.W = int(min(max(self.f_label.measure(self.text + "...") + 70 * s, 200 * s),
                             self.root.winfo_screenwidth() * 0.9))
        self._place()
        self._pill(self.BG, self.EDGE if st != "error" else "#7f1d1d")

        if st == "listening":
            # pulsing mic dot with an expanding ring
            mx = 26 * s
            p = (t * 1.2) % 1.0
            ring = (7 + 9 * p) * s
            c.create_oval(mx - ring, cy - ring, mx + ring, cy + ring,
                          outline=self._mix("#f59e0b" if self.app.command else self.RED, self.BG, p),
                          width=max(1, int(2 * s)))
            dot = "#f59e0b" if self.app.command else self.RED   # amber = command mode
            r = (6.5 + 1.5 * min(1.0, self.app.level * 25)) * s
            c.create_oval(mx - r, cy - r, mx + r, cy + r, fill=dot, outline="")
            # mirrored, smoothed waveform: newest sound in the middle, rippling outwards
            x0, gap, bw = 50 * s, 7.2 * s, 3.6 * s
            mid = self.BARS // 2
            maxh = H - 16 * s
            for i in range(self.BARS):
                d = abs(i - mid)
                lv = self.history[-1 - d] if d < len(self.history) else 0.0
                target = min(1.0, (lv * 28) ** 0.75)
                idle = 0.07 + 0.05 * math.sin(t * 5 + i * 0.6)
                target = max(target * (1 - d / (mid + 3)), idle)
                self.smooth[i] += (target - self.smooth[i]) * 0.38
                h = max(3 * s, self.smooth[i] * maxh)
                x = x0 + i * gap
                c.create_rectangle(x, cy - h / 2, x + bw, cy + h / 2, fill=self.colors[i], outline="")
                c.create_oval(x, cy - h / 2 - bw / 2, x + bw, cy - h / 2 + bw / 2, fill=self.colors[i], outline="")
                c.create_oval(x, cy + h / 2 - bw / 2, x + bw, cy + h / 2 + bw / 2, fill=self.colors[i], outline="")
            # label + timer, or the live preview of what you're saying
            tx = x0 + self.BARS * gap + 10 * s
            secs = int(t - self.app.rec_started) if self.app.recording else 0
            timer = "%d:%02d" % (secs // 60, secs % 60)
            if preview:
                room = self.W - tx - 22 * s
                shown = preview
                while shown and self.f_label.measure("…" + shown) > room:
                    shown = shown[1:]
                if shown != preview:
                    shown = "…" + shown.lstrip()
                c.create_text(tx, cy - 7 * s, text=shown, fill=self.TEXT, font=self.f_label, anchor="w")
                c.create_text(tx, cy + 9 * s, text=f"{timer}  ·  {self.text}", fill=self.MUTED,
                              font=self.f_small, anchor="w")
            else:
                c.create_text(tx, cy - 7 * s, text=self.text, fill=self.TEXT, font=self.f_label, anchor="w")
                c.create_text(tx, cy + 9 * s, text=timer, fill=self.MUTED, font=self.f_small, anchor="w")
        else:
            ix = 26 * s
            if st == "working":
                ang = (t * 360 * 1.1) % 360
                r = 9 * s
                c.create_oval(ix - r, cy - r, ix + r, cy + r, outline=self.EDGE, width=max(2, int(3 * s)))
                c.create_arc(ix - r, cy - r, ix + r, cy + r, start=-ang, extent=100, style="arc",
                             outline=self._grad((math.sin(t * 2) + 1) / 2), width=max(2, int(3 * s)))
                dots = "." * (int(t * 3) % 4)
                label = self.text + dots
            else:
                good = st == "info"
                r = 9 * s
                c.create_oval(ix - r, cy - r, ix + r, cy + r, fill=self.GREEN if good else self.RED, outline="")
                if good:
                    c.create_line(ix - 4.5 * s, cy, ix - 1 * s, cy + 3.5 * s, ix + 5 * s, cy - 3.5 * s,
                                  fill="white", width=max(2, int(2.2 * s)), capstyle="round", joinstyle="round")
                else:
                    c.create_text(ix, cy, text="!", fill="white", font=self.f_label)
                label = self.text
            c.create_text(46 * s, cy, text=label, fill=self.TEXT, font=self.f_label, anchor="w")

    def tick(self):
        try:
            while True:
                state, text = self.app.ui.get_nowait()
                if state == "ask":  # input box requested from another thread
                    import tkinter as tk
                    from tkinter import simpledialog
                    prompt, answer = text
                    w = tk.Toplevel(self.root)
                    w.withdraw()
                    try:
                        answer.put(simpledialog.askstring("FlowType", prompt, parent=w) or "")
                    finally:
                        w.destroy()
                    continue
                if state == "hide":
                    self.state = "hide"
                    continue
                self.state, self.text, self.shown = state, text, state
                self.until = (time.time() + (2.2 if state == "error" else (7 if len(text) > 40 else 3.5))
                              if state in ("error", "info") else 0)
                if state == "listening":
                    self.history = [0.0] * len(self.history)
        except queue.Empty:
            pass
        if self.until and time.time() > self.until:
            self.state, self.until = "hide", 0
        if self.state == "listening":
            self.history = self.history[1:] + [self.app.level]
        visible = self.state != "hide" and self.app.cfg.get("show_overlay", True)
        target = 0.96 if visible else 0.0
        self.alpha += (target - self.alpha) * 0.3
        if abs(self.alpha - target) < 0.02:
            self.alpha = target
        try:
            self.root.attributes("-alpha", self.alpha)
        except Exception:
            pass
        if ps.IS_LINUX:  # no alpha without a compositor: hide/show the window instead
            if self.alpha <= 0.01 and self.root.state() != "withdrawn":
                self.root.withdraw()
            elif self.alpha > 0.01 and self.root.state() == "withdrawn":
                self.root.deiconify()
                self.root.overrideredirect(True)
        if visible:
            self.root.attributes("-topmost", True)
        self.draw()
        self.root.after(30, self.tick)


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
        import pyperclip, pystray, sounddevice, tkinter  # noqa: F401
        if ps.IS_WIN:
            import keyboard  # noqa: F401
        else:
            import pynput  # noqa: F401
        lines.append("platform: " + ps.PLATFORM)
        from PIL import Image  # noqa: F401
        import textproc  # noqa: F401
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
