"""FlowType settings window (tkinter). Opened from the tray menu on the UI thread."""
import os
import tkinter as tk
from tkinter import messagebox, ttk

import platform_support as ps

_open = {}

RESTART_KEYS = ("hotkey_hold", "hotkey_toggle", "hotkey_learn", "hotkey_paste_last",
                "hotkey_read_aloud", "mouse_button", "device")

MODELS = [("base.en", "Fast - base.en"), ("small.en", "Balanced - small.en"),
          ("large-v3-turbo", "Most accurate - large-v3-turbo")]
TONES = [("auto", "Auto (by app)"), ("casual", "Casual"), ("professional", "Professional"),
         ("code", "Code"), ("plain", "Plain")]
GRAMMAR = [("off", "Off"), ("online", "Online (LanguageTool)"), ("offline", "Offline (needs Java 17+)")]
MOUSE = [("", "Off"), ("middle", "Middle button"), ("x1", "Back side button"), ("x2", "Forward side button")]


def _combo(parent, choices, current):
    labels = [lbl for _, lbl in choices]
    var = tk.StringVar(value=next((lbl for val, lbl in choices if val == current), labels[0]))
    box = ttk.Combobox(parent, textvariable=var, values=labels, state="readonly", width=34)
    return box, lambda: next(val for val, lbl in choices if lbl == var.get())


def _text(parent, value, height=10):
    frame = ttk.Frame(parent)
    t = tk.Text(frame, height=height, width=60, wrap="none", font=(ps.UI_FONT, 10), undo=True)
    sb = ttk.Scrollbar(frame, command=t.yview)
    t.configure(yscrollcommand=sb.set)
    t.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    t.insert("1.0", value)
    return frame, lambda: t.get("1.0", "end").strip()


def open_settings(root, app, save_settings, history_path, privacy_path, version):
    if _open.get("w") is not None:
        try:
            _open["w"].deiconify()
            _open["w"].lift()
            _open["w"].focus_force()
            return
        except tk.TclError:
            pass
    cfg = app.cfg
    w = tk.Toplevel(root)
    _open["w"] = w
    w.title("FlowType settings")
    w.attributes("-topmost", True)
    w.after(400, lambda: w.attributes("-topmost", False))
    w.minsize(560, 470)
    try:
        ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flowtype.ico")
        if ps.IS_WIN and os.path.exists(ico):
            w.iconbitmap(ico)
    except Exception:
        pass

    nb = ttk.Notebook(w)
    nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))
    getters = {}

    # ---------------------------------------------------------- General
    g = ttk.Frame(nb, padding=12)
    nb.add(g, text="General")
    row = 0

    def label(parent, text, r, **kw):
        ttk.Label(parent, text=text).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12), **kw)

    for key, text, default in (("hotkey_hold", "Hold to talk", "ctrl+alt"),
                               ("hotkey_toggle", "Hands-free on / off", "ctrl+shift+space"),
                               ("hotkey_paste_last", "Paste last dictation", "ctrl+alt+v"),
                               ("hotkey_read_aloud", "Read selection aloud", "ctrl+alt+r"),
                               ("hotkey_learn", "Learn selected word", "ctrl+alt+d")):
        label(g, text, row)
        var = tk.StringVar(value=cfg.get(key, default))
        ttk.Entry(g, textvariable=var, width=36).grid(row=row, column=1, sticky="w")
        getters[key] = (lambda v=var: v.get().strip().lower())
        row += 1

    for key, text, choices, current in (
            ("model", "Speed vs accuracy", MODELS + ([(cfg.get("model"), cfg.get("model"))]
                                                     if cfg.get("model") not in dict(MODELS) else []), cfg.get("model")),
            ("tone", "Tone", TONES, app.tone_setting()),
            ("_grammar", "Grammar check", GRAMMAR, app.grammar_state()),
            ("mouse_button", "Mouse / foot pedal (hold)", MOUSE, cfg.get("mouse_button") or "")):
        label(g, text, row)
        box, get = _combo(g, choices, current)
        box.grid(row=row, column=1, sticky="w")
        getters[key] = get
        row += 1

    checks = ttk.Frame(g)
    checks.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
    for i, (key, text, default) in enumerate((
            ("spoken_punctuation", 'Spoken punctuation ("comma", "new line")', False),
            ("live_preview", "Live preview while talking", True),
            ("email_format", "Email formatting in Gmail / Outlook", True),
            ("auto_send", "Auto-send (press Enter after each message)", False),
            ("sounds", "Start / stop sounds", True),
            ("show_overlay", "Show the floating pill", True))):
        var = tk.BooleanVar(value=bool(cfg.get(key, default)))
        ttk.Checkbutton(checks, text=text, variable=var).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 18), pady=2)
        getters[key] = (lambda v=var: bool(v.get()))

    # ---------------------------------------------------------- Snippets
    s = ttk.Frame(nb, padding=12)
    nb.add(s, text="Snippets")
    ttk.Label(s, text='Say "insert <name>" to type the text. One per line:  name = text   (write \\n for a new line)',
              wraplength=520).pack(anchor="w", pady=(0, 6))
    snip_lines = "\n".join(f"{k} = {v.replace(chr(10), chr(92) + 'n')}" for k, v in (cfg.get("snippets") or {}).items())
    f, get_snips = _text(s, snip_lines, 14)
    f.pack(fill="both", expand=True)

    def parse_snips():
        out = {}
        for line in get_snips().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip():
                    out[k.strip().lower()] = v.strip().replace("\\n", "\n")
        return out
    getters["snippets"] = parse_snips

    # ---------------------------------------------------------- Words
    wd = ttk.Frame(nb, padding=12)
    nb.add(wd, text="Words")
    ttk.Label(wd, text="Names and terms FlowType should know (one per line):").pack(anchor="w")
    f, get_dict = _text(wd, "\n".join(cfg.get("dictionary") or []), 6)
    f.pack(fill="both", expand=True, pady=(2, 10))
    ttk.Label(wd, text="Always replace (one per line):  heard -> wanted").pack(anchor="w")
    f, get_repl = _text(wd, "\n".join(f"{k} -> {v}" for k, v in (cfg.get("replacements") or {}).items()), 6)
    f.pack(fill="both", expand=True, pady=(2, 0))
    getters["dictionary"] = lambda: [x.strip() for x in get_dict().splitlines() if x.strip()]

    def parse_repl():
        out = {}
        for line in get_repl().splitlines():
            if "->" in line:
                a, b = line.split("->", 1)
                if a.strip() and b.strip():
                    out[a.strip().lower()] = b.strip()
        return out
    getters["replacements"] = parse_repl

    # ---------------------------------------------------------- Privacy
    pv = ttk.Frame(nb, padding=12)
    nb.add(pv, text="Privacy")
    ttk.Label(pv, text="Pause FlowType when the window title contains (one per line) - "
                       "for password managers, banking and other sensitive apps:", wraplength=520).pack(anchor="w")
    f, get_pause = _text(pv, "\n".join(cfg.get("pause_in_apps") or []), 7)
    f.pack(fill="both", expand=True, pady=(2, 10))
    getters["pause_in_apps"] = lambda: [x.strip().lower() for x in get_pause().splitlines() if x.strip()]
    for key, text, default in (("save_history", "Keep a history of what I dictated (on this computer only)", True),
                               ("check_updates", "Check GitHub for new versions", True)):
        var = tk.BooleanVar(value=bool(cfg.get(key, default)))
        ttk.Checkbutton(pv, text=text, variable=var).pack(anchor="w", pady=2)
        getters[key] = (lambda v=var: bool(v.get()))
    btns = ttk.Frame(pv)
    btns.pack(anchor="w", pady=(8, 0))

    def clear_history():
        if messagebox.askyesno("FlowType", "Delete your dictation history? This can't be undone.", parent=w):
            try:
                os.remove(history_path)
            except FileNotFoundError:
                pass
            app.ui.put(("info", "History deleted"))
    ttk.Button(btns, text="Delete history", command=clear_history).pack(side="left")
    ttk.Button(btns, text="Privacy policy", command=lambda: ps.open_path(privacy_path)
               if os.path.exists(privacy_path) else ps.open_path("https://github.com/soumyaswarrup/FlowType/blob/main/PRIVACY.md")
               ).pack(side="left", padx=8)

    # ---------------------------------------------------------- About
    ab = ttk.Frame(nb, padding=16)
    nb.add(ab, text="About")
    ttk.Label(ab, text=f"FlowType {version}", font=(ps.UI_FONT_BOLD, 15)).pack(anchor="w")
    ttk.Label(ab, text="Free, open-source voice typing. Speech recognition runs on your computer.").pack(anchor="w", pady=(4, 10))
    ttk.Label(ab, text=app.stats_text()).pack(anchor="w")
    ttk.Label(ab, text=app.status).pack(anchor="w", pady=(2, 10))
    ttk.Button(ab, text="Open GitHub page", command=lambda: ps.open_path("https://github.com/soumyaswarrup/FlowType")).pack(anchor="w")

    # ---------------------------------------------------------- buttons
    bar = ttk.Frame(w, padding=10)
    bar.pack(fill="x")

    def close():
        _open["w"] = None
        w.destroy()

    def save():
        try:
            new = {k: get() for k, get in getters.items()}
        except Exception as e:
            messagebox.showerror("FlowType", f"Could not read a setting: {e}", parent=w)
            return
        grammar = new.pop("_grammar")
        new_model = new.pop("model")
        new_tone = new.pop("tone")
        for key in ("hotkey_hold", "hotkey_toggle", "hotkey_paste_last", "hotkey_read_aloud", "hotkey_learn"):
            if not new[key] and key != "hotkey_paste_last" and key != "hotkey_read_aloud":
                messagebox.showerror("FlowType", "Hotkeys can't be empty.", parent=w)
                return
        need_restart = any(new.get(k) != cfg.get(k) for k in RESTART_KEYS if k in new)
        save_settings(new)
        cfg.update(new)
        if new_tone != app.tone_setting():
            app.set_tone(new_tone)
        if grammar != app.grammar_state():
            app.set_grammar(grammar)
        if new_model != cfg.get("model"):
            app.set_model(new_model)
        app.update_tray()
        close()
        if need_restart:
            if messagebox.askyesno("FlowType", "Restart FlowType now to use the new hotkeys / mouse button?"):
                app.restart()
        else:
            app.ui.put(("info", "Settings saved"))

    ttk.Button(bar, text="Save", command=save).pack(side="right")
    ttk.Button(bar, text="Cancel", command=close).pack(side="right", padx=8)
    w.protocol("WM_DELETE_WINDOW", close)
    w.bind("<Escape>", lambda e: close())
