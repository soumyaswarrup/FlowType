"""FlowType's on-screen pill: drawn with Pillow (smooth, anti-aliased) and shown in a
click-through, never-focused Tk window.

States:  listening  - glowing mic + flowing colour voice waves + live words + timer
         working    - spinning gradient ring + gently bouncing dots
         info       - green tick that draws itself
         error      - red badge with a small shake
"""
import math
import os
import queue
import time

from PIL import Image, ImageDraw, ImageFont, ImageTk

import platform_support as ps

SS = 2  # draw at 2x, then scale down = smooth edges

BG_TOP = (30, 32, 46)
BG_BOTTOM = (14, 15, 24)
EDGE = (255, 255, 255, 26)
TEXT = (243, 244, 246)
MUTED = (156, 163, 175)
GREEN = (34, 197, 94)
RED = (239, 68, 68)
AMBER = (245, 158, 11)
WAVES = [(167, 139, 250), (96, 165, 250), (34, 211, 238)]           # dictation: violet, blue, cyan
WAVES_CMD = [(251, 191, 36), (249, 115, 22), (244, 63, 94)]         # command mode: amber, orange, rose

FONT_FILES = {
    "bold": [r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
             "/System/Library/Fonts/SFNSDisplay.ttf", "/System/Library/Fonts/Helvetica.ttc",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"],
    "regular": [r"C:\Windows\Fonts\segoeui.ttf", "/System/Library/Fonts/SFNS.ttf",
                "/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/opentype/inter/Inter-Regular.otf"],
}


def load_font(kind, size):
    for path in FONT_FILES[kind]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Overlay:
    def __init__(self, root, app, user32=None):
        import tkinter as tk
        self.root, self.app = root, app
        self.state, self.shown, self.text, self.until = "hide", "hide", "", 0
        self.t_state = time.time()
        s = root.winfo_fpixels("1i") / 96.0
        self.s = s
        self.H = int(56 * s)
        self.W = int(340 * s)
        self.alpha = 0.0
        self.pos = None
        self.lvl = 0.0
        self.f_main = load_font("bold", int(15 * s * SS))
        self.f_sub = load_font("regular", int(12 * s * SS))
        self.f_badge = load_font("bold", int(14 * s * SS))

        # The window: borderless, always on top, see-through corners, click-through, never takes focus.
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.0)
        self.key = (1, 2, 3)
        if ps.IS_WIN:
            root.configure(bg="#010203")
            root.attributes("-transparentcolor", "#010203")
        elif ps.IS_MAC:
            try:
                root.attributes("-transparent", True)
                root.configure(bg="systemTransparent")
                self.key = None  # real per-pixel transparency
            except Exception:
                self.key = BG_BOTTOM
        else:
            self.key = BG_BOTTOM
            root.configure(bg="#%02x%02x%02x" % BG_BOTTOM)
        bg = "systemTransparent" if self.key is None else "#%02x%02x%02x" % self.key
        self.c = tk.Canvas(root, width=self.W, height=self.H, bg=bg, highlightthickness=0, bd=0)
        self.c.pack()
        self.img_id = self.c.create_image(0, 0, anchor="nw")
        self.photo = None
        self._place()
        root.update_idletasks()
        if user32 is not None:
            try:
                hwnd = user32.GetParent(root.winfo_id())
                ex = user32.GetWindowLongW(hwnd, -20)
                # LAYERED | TRANSPARENT (click-through) | TOOLWINDOW (no taskbar) | NOACTIVATE
                user32.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x08000000)
            except Exception:
                pass

    # ---------------------------------------------------------------- window placement
    def _place(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        k = min(self.alpha / 0.96, 1.0)
        slide = int((1 - k) * 14 * self.s)
        pos = (self.W, self.H, (sw - self.W) // 2, sh - self.H - int(86 * self.s) + slide)
        if pos != self.pos:
            self.pos = pos
            self.root.geometry("%dx%d+%d+%d" % pos)
            self.c.config(width=self.W, height=self.H)

    # ---------------------------------------------------------------- drawing helpers
    def _pill(self, W, H, edge=EDGE):
        """Rounded pill with a soft vertical gradient and a hairline border (RGBA, 2x size)."""
        grad = Image.new("RGBA", (1, H))
        for y in range(H):
            grad.putpixel((0, y), mix(BG_TOP, BG_BOTTOM, y / max(1, H - 1)) + (255,))
        grad = grad.resize((W, H))
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), radius=H // 2, fill=255)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.paste(grad, (0, 0), mask)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((1, 1, W - 2, H - 2), radius=H // 2 - 1, outline=edge, width=max(2, SS))
        return img

    def _text_fit(self, text, font, room):
        if font.getlength(text) <= room:
            return text
        while text and font.getlength("…" + text) > room:
            text = text[1:]
        return "…" + text.lstrip()

    def _waves(self, d, x0, x1, cy, amp, t, colors, glow_layer):
        """Three overlapping sine waves that taper at both ends - a 'voice' ribbon."""
        n = 90
        for i, col in enumerate(colors):
            freq = (2.2 + i * 0.55) * math.pi
            speed = 2.6 + i * 0.9
            ph = t * speed + i * 1.7
            a = amp * (1.0 - i * 0.22)
            pts = []
            for k in range(n + 1):
                u = k / n
                env = math.sin(math.pi * u) ** 1.6
                y = cy + a * env * math.sin(freq * u + ph) * (0.85 + 0.15 * math.sin(t * 1.3 + i))
                pts.append((x0 + (x1 - x0) * u, y))
            glow_layer.line(pts, fill=col + (60,), width=int(7 * self.s * SS), joint="curve")
            d.line(pts, fill=col + (255,), width=int(2.4 * self.s * SS), joint="curve")

    # ---------------------------------------------------------------- render one frame
    def render(self):
        s, t = self.s, time.time()
        st = self.shown
        age = t - self.t_state
        preview = (self.app.preview_text or "").strip() if st == "listening" else ""
        command = bool(getattr(self.app, "command", False))

        if st == "listening":
            self.W = int((600 if preview else 340) * s)
        else:
            tw = self.f_main.getlength(self.text + "...") / SS
            self.W = int(min(max(tw + 80 * s, 220 * s), self.root.winfo_screenwidth() * 0.9))
        self._place()
        W, H = self.W * SS, self.H * SS
        cy = H / 2

        border = (RED + (140,)) if st == "error" else (AMBER + (120,)) if (st == "listening" and command) else EDGE
        bg = self._pill(W, H, border)
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))    # soft light under the content
        content = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        g = ImageDraw.Draw(glow)
        d = ImageDraw.Draw(content)

        # error shake
        shake = int(math.sin(age * 40) * 5 * s * SS * max(0.0, 1 - age / 0.35)) if st == "error" else 0
        ix = int(30 * s * SS) + shake

        if st == "listening":
            target = min(1.0, (self.app.level * 28) ** 0.7)
            self.lvl += (target - self.lvl) * (0.35 if target > self.lvl else 0.12)
            accent = AMBER if command else RED
            # glowing mic badge
            pulse = (math.sin(t * 3.2) + 1) / 2
            r = (11 + 2 * self.lvl) * s * SS
            for k, a in ((2.2, 30), (1.7, 55)):
                rr = r * (k - 0.25 + 0.25 * pulse + 0.4 * self.lvl)
                g.ellipse((ix - rr, cy - rr, ix + rr, cy + rr), fill=accent + (a,))
            d.ellipse((ix - r, cy - r, ix + r, cy + r), fill=accent + (255,))
            self._mic_glyph(d, ix, cy, r * 0.62)
            # waves
            x0, x1 = int(56 * s * SS), int(214 * s * SS)
            amp = (3 + 15 * self.lvl) * s * SS
            self._waves(d, x0, x1, cy, amp, t, WAVES_CMD if command else WAVES, g)
            # words / label + timer
            tx = int(228 * s * SS)
            secs = int(t - self.app.rec_started) if self.app.recording else 0
            timer = "%d:%02d" % (secs // 60, secs % 60)
            room = W - tx - int(24 * s * SS)
            main = self._text_fit(preview, self.f_main, room) if preview else self.text
            sub = f"{timer}  ·  {self.text}" if preview else timer
            d.text((tx, cy - 3 * s * SS), main, font=self.f_main, fill=TEXT + (255,), anchor="ls")
            d.text((tx, cy + 15 * s * SS), sub, font=self.f_sub, fill=MUTED + (255,), anchor="ls")
        else:
            r = 11 * s * SS
            if st == "working":
                # spinning gradient ring
                ang = (t * 300) % 360
                box = (ix - r, cy - r, ix + r, cy + r)
                d.ellipse(box, outline=(55, 58, 75, 255), width=int(3 * s * SS))
                for k in range(12):
                    col = WAVES[0] if k < 4 else WAVES[1] if k < 8 else WAVES[2]
                    d.arc(box, start=ang + k * 10, end=ang + k * 10 + 11, fill=col + (255,), width=int(3 * s * SS))
                label = self.text
                tx = int(52 * s * SS)
                d.text((tx, cy + 5 * s * SS), label, font=self.f_main, fill=TEXT + (255,), anchor="ls")
                # three soft bouncing dots after the label
                dx = tx + self.f_main.getlength(label) + 8 * s * SS
                for k in range(3):
                    bounce = max(0.0, math.sin(t * 6 - k * 0.6)) * 4 * s * SS
                    dr = 2.2 * s * SS
                    col = WAVES[k]
                    d.ellipse((dx + k * 9 * s * SS - dr, cy + 1 * s * SS - bounce - dr,
                               dx + k * 9 * s * SS + dr, cy + 1 * s * SS - bounce + dr), fill=col + (255,))
            else:
                good = st == "info"
                pop = min(1.0, age / 0.18)
                rr = r * (0.6 + 0.4 * pop + 0.08 * math.sin(min(1, age / 0.3) * math.pi))
                col = GREEN if good else RED
                g.ellipse((ix - rr * 1.8, cy - rr * 1.8, ix + rr * 1.8, cy + rr * 1.8), fill=col + (45,))
                d.ellipse((ix - rr, cy - rr, ix + rr, cy + rr), fill=col + (255,))
                if good:  # tick draws itself
                    p = min(1.0, max(0.0, (age - 0.08) / 0.3))
                    a = (ix - 5 * s * SS, cy + 0.5 * s * SS)
                    b = (ix - 1.5 * s * SS, cy + 4 * s * SS)
                    c = (ix + 5.5 * s * SS, cy - 4 * s * SS)
                    pts = [a]
                    if p < 0.4:
                        q = p / 0.4
                        pts.append((a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q))
                    else:
                        q = (p - 0.4) / 0.6
                        pts += [b, (b[0] + (c[0] - b[0]) * q, b[1] + (c[1] - b[1]) * q)]
                    if len(pts) > 1:
                        d.line(pts, fill=(255, 255, 255, 255), width=int(2.6 * s * SS), joint="curve")
                else:
                    d.text((ix, cy + 1 * s * SS), "!", font=self.f_badge, fill=(255, 255, 255, 255), anchor="mm")
                slide = int((1 - min(1, age / 0.25)) * 8 * s * SS)
                d.text((int(52 * s * SS) + slide + shake, cy + 5 * s * SS), self.text, font=self.f_main,
                       fill=TEXT + (255,), anchor="ls")

        img = Image.alpha_composite(Image.alpha_composite(bg, glow), content)
        # keep everything outside the pill fully transparent
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), radius=H // 2, fill=255)
        img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (W, H), 0), mask))
        img = img.resize((self.W, self.H), Image.LANCZOS)
        if self.key is not None:  # flatten onto the colour that the window treats as see-through
            base = Image.new("RGBA", img.size, self.key + (255,))
            img = Image.alpha_composite(base, img).convert("RGB")
        return img

    def _mic_glyph(self, d, cx, cy, size):
        w = size * 0.55
        d.rounded_rectangle((cx - w / 2, cy - size * 0.95, cx + w / 2, cy + size * 0.25), radius=w / 2,
                            fill=(255, 255, 255, 255))
        d.arc((cx - size * 0.75, cy - size * 0.75, cx + size * 0.75, cy + size * 0.55), start=20, end=160,
              fill=(255, 255, 255, 255), width=max(2, int(size * 0.18)))
        d.line((cx, cy + size * 0.55, cx, cy + size * 0.9), fill=(255, 255, 255, 255), width=max(2, int(size * 0.18)))

    def draw(self):
        if self.shown == "hide" or self.alpha <= 0.01:
            return
        try:
            self.photo = ImageTk.PhotoImage(self.render())
            self.c.itemconfig(self.img_id, image=self.photo)
        except Exception:
            pass

    # ---------------------------------------------------------------- main loop
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
                if state != self.shown or text != self.text:
                    self.t_state = time.time()
                if state == "listening" and self.shown != "listening":
                    self.lvl = 0.0
                self.state, self.text, self.shown = state, text, state
                self.until = (time.time() + (2.2 if state == "error" else (7 if len(text) > 40 else 3.5))
                              if state in ("error", "info") else 0)
        except queue.Empty:
            pass
        if self.until and time.time() > self.until:
            self.state, self.until = "hide", 0
        visible = self.state != "hide" and self.app.cfg.get("show_overlay", True)
        target = 0.97 if visible else 0.0
        self.alpha += (target - self.alpha) * 0.28
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
        self.root.after(33, self.tick)
