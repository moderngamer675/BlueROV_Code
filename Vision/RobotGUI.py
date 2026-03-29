# RobotApp.py
# BlueROV2 Mission Control GUI — Modular Refactor
# Fixed 720x480 camera view
#
# THREAD SAFETY:
#   This file runs ENTIRELY on the tkinter main thread.
#   All data from background threads is read via SharedState snapshots
#   in .after() poll loops.  No background thread ever touches a widget.

import tkinter as tk
from tkinter import scrolledtext, font
from PIL import Image, ImageTk
import cv2
from datetime import datetime

from rov_config import (
    GUI_POLL_MS, THRUSTER_COUNT, THRUSTER_LABELS, THRUSTER_ROLES
)
from shared_state import SharedState, Command
from RobotBackend import RobotLogic
from RobotTelemetry import TelemetryHandler


# =============================================================================
#  THEME & CONSTANTS
# =============================================================================

THEME = {
    "bg": "#060912", "panel": "#0D1117", "card": "#161B27",
    "card_hover": "#1E2535", "border": "#1F2D45", "border_bright": "#2A4080",
    "text": "#C9D8E8", "text_dim": "#5A7090", "text_bright": "#EAF4FF",
    "accent": "#00C8FF", "accent_dim": "#005F78",
    "success": "#00E676", "success_dim": "#004D26",
    "danger": "#FF1744", "danger_dim": "#4D0010",
    "warning": "#FFD600", "warning_dim": "#4D4000",
    "cyan": "#18FFFF", "purple": "#7C4DFF",
    "log_bg": "#020408", "log_text": "#00E676", "log_dim": "#005520",
}

CAM_W, CAM_H = 720, 480
VIDEO_REFRESH_MS = 30
SHUTDOWN_DELAY_MS = 1200
BLINK_INTERVAL_MS = 800
THRUSTER_REFRESH_MS = 50
TELEMETRY_POLL_MS = 200
CONTROL_SPEED = 0.30

HUD_MAP = {
    "DEPTH": "HUD_DEPTH", "HEADING": "HUD_HDG", "ROLL": "HUD_ROLL",
    "PITCH": "HUD_PCH", "BATTERY": "HUD_BAT", "CURRENT": "HUD_CUR",
}

MOVEMENT_KEYS = ('w', 's', 'a', 'd', 'q', 'e', 'r', 'f')


# =============================================================================
#  HELPERS
# =============================================================================

def make_label(parent, text, size=7, bold=True, color=None, **kw):
    weight = "bold" if bold else "normal"
    return tk.Label(parent, text=text, font=("Courier New", size, weight),
                    bg=parent["bg"], fg=color or THEME["text_dim"], **kw)


def make_bar(parent, color, side=tk.LEFT, width=3):
    bar = tk.Frame(parent, bg=color, width=width)
    bar.pack(side=side, fill=tk.Y)
    return bar


def make_separator(parent, color=None, width=1, **pack_kw):
    sep = tk.Frame(parent, bg=color or THEME["border"], width=width)
    sep.pack(side=tk.LEFT, fill=tk.Y, **pack_kw)
    return sep


def lerp_hex(c1, c2, t):
    r1, g1, b1 = (int(c1[i:i+2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(c2[i:i+2], 16) for i in (1, 3, 5))
    return (f"#{int(r1+(r2-r1)*t):02x}"
            f"{int(g1+(g2-g1)*t):02x}"
            f"{int(b1+(b2-b1)*t):02x}")


def gradient_color(v, stops):
    v = max(0.0, min(1.0, v))
    if v <= 0: return stops[0]
    if v >= 1: return stops[-1]
    n = len(stops) - 1
    s = v * n
    lo = int(s)
    return lerp_hex(stops[lo], stops[min(lo+1, n)], s - lo)


# =============================================================================
#  SEPARATOR LINE WIDGET
# =============================================================================

class SeparatorLine(tk.Canvas):
    def __init__(self, parent, label="", color=None, **kw):
        self._label = label
        self._color = color or THEME["border"]
        super().__init__(parent, height=14, bg=THEME["panel"],
                         highlightthickness=0, **kw)
        self.bind("<Configure>", self._draw)

    def _draw(self, _=None):
        self.delete("all")
        w, cy, c = self.winfo_width(), 7, self._color
        if self._label:
            self.create_line(0, cy, w*0.06, cy, fill=c, width=1)
            self.create_text(w*0.07, cy, text=self._label, anchor="w",
                             fill=c, font=("Courier New", 7, "bold"))
            self.create_line(w*0.07 + len(self._label)*5.5 + 6, cy, w, cy,
                             fill=c, width=1)
        else:
            self.create_line(0, cy, w, cy, fill=c, width=1)


# =============================================================================
#  GLOW BUTTON
# =============================================================================

class GlowButton(tk.Frame):
    def __init__(self, parent, text, color, command,
                 icon="", disabled=False, **kw):
        super().__init__(parent, bg=THEME["panel"], cursor="hand2", **kw)
        self._color, self._command, self._disabled = color, command, disabled

        self._bar = tk.Frame(self, bg=self._active_color, width=4)
        self._bar.pack(side=tk.LEFT, fill=tk.Y)

        self._body = tk.Frame(self, bg=THEME["card"])
        self._body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        row = tk.Frame(self._body, bg=THEME["card"])
        row.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        if icon:
            tk.Label(row, text=icon, font=("Courier New", 10),
                     bg=THEME["card"], fg=self._active_color).pack(
                         side=tk.LEFT)

        self._lbl = tk.Label(row, text=text,
                             font=("Courier New", 9, "bold"),
                             bg=THEME["card"], fg=self._active_color, padx=4)
        self._lbl.pack(side=tk.LEFT)

        self._chev = tk.Label(row, text="›",
                              font=("Courier New", 12, "bold"),
                              bg=THEME["card"], fg=THEME["text_dim"])
        self._chev.pack(side=tk.RIGHT)

        for w in (self, self._body, self._bar, row, self._lbl, self._chev):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._on_click)

    @property
    def _active_color(self):
        return THEME["border"] if self._disabled else self._color

    def _on_enter(self, _=None):
        if self._disabled: return
        for w in (self._body, self._lbl, self._chev):
            w.config(bg=THEME["card_hover"])
        self._lbl.config(fg=THEME["text_bright"])
        self._chev.config(fg=self._color)

    def _on_leave(self, _=None):
        for w in (self._body, self._lbl, self._chev):
            w.config(bg=THEME["card"])
        self._lbl.config(fg=self._active_color)
        self._chev.config(fg=THEME["text_dim"])

    def _on_click(self, _=None):
        if not self._disabled and self._command:
            self._command()

    def set_disabled(self, state: bool):
        self._disabled = state
        self._bar.config(bg=self._active_color)
        self._lbl.config(fg=self._active_color)
        self._body.config(bg=THEME["card"])

    def update_label(self, text, color=None):
        if color:
            self._color = color
        self._lbl.config(text=text, fg=self._active_color)
        self._bar.config(bg=self._active_color)


# =============================================================================
#  TELEMETRY CARD
# =============================================================================

class TelemetryCard(tk.Frame):
    def __init__(self, parent, label, value, unit="", color=None, **kw):
        color = color or THEME["accent"]
        super().__init__(parent, bg=THEME["card"], relief=tk.FLAT, **kw)

        make_label(self, label, anchor="w").pack(
            fill=tk.X, padx=8, pady=(6, 0))

        self._val_lbl = tk.Label(self, text=value,
                                 font=("Courier New", 13, "bold"),
                                 bg=THEME["card"], fg=color, anchor="w")
        self._val_lbl.pack(fill=tk.X, padx=8)

        make_label(self, unit, bold=False, anchor="w").pack(
            fill=tk.X, padx=8, pady=(0, 4))

        tk.Frame(self, bg=color, height=2).pack(fill=tk.X)

    def update(self, value, color=None):
        kw = {"text": str(value)}
        if color:
            kw["fg"] = color
        self._val_lbl.config(**kw)


# =============================================================================
#  THRUSTER BAR
# =============================================================================

class ThrusterBar(tk.Frame):
    _POS = ["#004D20", "#007A30", "#00B344", "#00E676"]
    _NEG = ["#4D3300", "#997700", "#CC9900", "#FFD600"]

    def __init__(self, parent, label, role, index, **kw):
        super().__init__(parent, bg=THEME["card"], **kw)
        self._target = self._current = 0.0

        badge = tk.Frame(self, bg=THEME["card"])
        badge.pack(fill=tk.X, padx=4, pady=(4, 1))
        make_label(badge, f"#{index+1}").pack(side=tk.LEFT)
        make_label(badge, label, size=8,
                   color=THEME["accent"]).pack(side=tk.RIGHT)

        self._canvas = tk.Canvas(
            self, bg=THEME["log_bg"], highlightthickness=1,
            highlightbackground=THEME["border"], width=44, height=140)
        self._canvas.pack(padx=4, pady=2)

        make_label(self, role, size=6).pack(pady=(0, 1))
        self._pct_lbl = make_label(self, "0%", color=THEME["success"])
        self._pct_lbl.pack(pady=(0, 4))
        self._accent = tk.Frame(self, height=2, bg=THEME["border"])
        self._accent.pack(fill=tk.X)

        self._canvas.bind("<Configure>", lambda e: self._redraw())

    def set_value(self, v):
        self._target = max(-1.0, min(1.0, v))

    def step(self):
        diff = self._target - self._current
        if abs(diff) < 0.005:
            self._current = self._target
        else:
            self._current += diff * 0.25
        self._redraw()

    def _redraw(self):
        c = self._canvas
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W < 2 or H < 2: return

        mid, v = H // 2, self._current
        pct = int(abs(v) * 100)
        bar_h = int(abs(v) * (mid - 4))

        for frac in (0.25, 0.5, 0.75):
            for y in (int(mid * frac), H - int(mid * frac)):
                c.create_line(0, y, W, y, fill=THEME["border"], dash=(2, 4))

        if bar_h > 0:
            colors = self._POS if v >= 0 else self._NEG
            fc = gradient_color(abs(v), colors)
            gc = colors[-1]
            if v >= 0:
                y0, y1 = mid - bar_h, mid
                gy0, gy1 = y0, y0 + min(3, bar_h)
            else:
                y0, y1 = mid, mid + bar_h
                gy0, gy1 = y1 - min(3, bar_h), y1
            c.create_rectangle(2, y0, W-2, y1, fill=fc, outline="")
            c.create_rectangle(2, gy0, W-2, gy1, fill=gc, outline="")

        zc = THEME["accent"] if v == 0.0 else THEME["border_bright"]
        c.create_line(0, mid, W, mid, fill=zc, width=1)

        for y_off in (0, mid // 2, mid):
            for y in (y_off + 2, H - y_off - 2):
                c.create_line(W-6, y, W, y, fill=THEME["text_dim"], width=1)

        if v > 0.01:
            self._pct_lbl.config(text=f"+{pct}%", fg=THEME["success"])
            self._accent.config(bg=THEME["success"])
        elif v < -0.01:
            self._pct_lbl.config(text=f"−{pct}%", fg=THEME["warning"])
            self._accent.config(bg=THEME["warning"])
        else:
            self._pct_lbl.config(text="0%", fg=THEME["text_dim"])
            self._accent.config(bg=THEME["border"])


# =============================================================================
#  THRUSTER PANEL  (now driven by THRUSTER_COUNT from config)
# =============================================================================

class ThrusterPanel(tk.Frame):
    def __init__(self, parent, labels, roles, **kw):
        super().__init__(parent, bg=THEME["panel"], **kw)
        self._bars: list[ThrusterBar] = []
        self._count = len(labels)

        tb = tk.Frame(self, bg=THEME["panel"], height=24)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)

        make_bar(tb, THEME["success"])
        make_label(tb, "  THRUSTER OUTPUT", size=9,
                   color=THEME["success"]).pack(side=tk.LEFT, pady=2)

        self._armed_badge = make_label(tb, "  ◼ DISARMED  ")
        self._armed_badge.pack(side=tk.RIGHT, padx=8)

        self._peak_lbl = make_label(tb, "PEAK: —%")
        self._peak_lbl.pack(side=tk.RIGHT, padx=12)

        make_label(
            tb,
            "W/S=Fwd  A/D=Strafe  Q/E=Yaw  R/F=Depth  SPACE=Stop",
            bold=False).pack(side=tk.LEFT, padx=16)

        bar_row = tk.Frame(self, bg=THEME["panel"])
        bar_row.pack(fill=tk.X, padx=4, pady=(2, 4))

        for i, (lbl, role) in enumerate(zip(labels, roles)):
            if i > 0:
                make_separator(bar_row, pady=4)
            bar = ThrusterBar(bar_row, lbl, role, i)
            bar.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
            self._bars.append(bar)

    def update_values(self, values):
        data = ([values.get(THRUSTER_LABELS[i], 0)
                 for i in range(self._count)]
                if isinstance(values, dict) else list(values))
        for i, v in enumerate(data):
            if i < len(self._bars):
                self._bars[i].set_value(float(v))

        peak = max((abs(b._target) for b in self._bars), default=0.0)
        pp = int(peak * 100)
        col = (THEME["danger"] if peak > 0.8 else
               THEME["warning"] if peak > 0.5 else THEME["success"])
        self._peak_lbl.config(text=f"PEAK:{pp:3d}%", fg=col)

    def step_animation(self):
        for b in self._bars:
            b.step()

    def set_armed(self, armed: bool):
        if armed:
            self._armed_badge.config(
                text="  ▲ ARMED  ", fg=THEME["danger"])
        else:
            self._armed_badge.config(
                text="  ◼ DISARMED  ", fg=THEME["text_dim"])
            for b in self._bars:
                b.set_value(0.0)


# =============================================================================
#  MAIN APPLICATION
# =============================================================================

class RobotApp:
    """
    GUI controller — runs entirely on the tkinter main thread.

    Communication with background threads:
        READ:   self._state.drain_telemetry_updates()
                self._state.get_video_frame()
                self._state.drain_logs()
        WRITE:  self._state.send_command(Command(...))
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.armed_state = False
        self._blink_state = False
        self._current_frame = None

        self.telemetry_cards: dict[str, TelemetryCard] = {}
        self.system_labels: dict[str, tk.Label] = {}
        self.telemetry_labels: dict[str, tk.Label] = {}

        self._keys = {k: False for k in MOVEMENT_KEYS}

        # ── Shared state bridge ──────────────────────────────────────────
        self._state = SharedState()

        # ── Backend instances ────────────────────────────────────────────
        self.video_backend = RobotLogic(self._state)
        self.telemetry_backend = TelemetryHandler(self._state)

        self._configure_window()
        self._build_ui()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

        self._log_to_widget(
            "Mission Control initialised. Awaiting connection.")
        self._log_to_widget(
            "Keys: W/S A/D Q/E R/F  |  SPACE = Emergency Stop")

        # ── Start periodic GUI poll loops ────────────────────────────────
        self._start_periodic(self._blink_tick, BLINK_INTERVAL_MS)
        self._start_periodic(self._thruster_tick, THRUSTER_REFRESH_MS)
        self._start_periodic(self._poll_telemetry, TELEMETRY_POLL_MS)
        self._start_periodic(self._poll_shared_state, GUI_POLL_MS)

    # ── Periodic timer helper ────────────────────────────────────────────

    def _start_periodic(self, func, interval_ms):
        def _loop():
            func()
            self.root.after(interval_ms, _loop)
        _loop()

    # =====================================================================
    #  WINDOW CONFIG
    # =====================================================================

    def _configure_window(self):
        self.root.title("BlueROV2 — Mission Control")
        self.root.geometry("1420x900")
        self.root.resizable(False, False)
        self.root.configure(bg=THEME["bg"])

        self.fnt_header = font.Font(
            family="Courier New", size=14, weight="bold")
        self.fnt_sub = font.Font(
            family="Courier New", size=9, weight="bold")
        self.fnt_lbl = font.Font(
            family="Courier New", size=7, weight="bold")
        self.fnt_log = font.Font(family="Courier New", size=8)
        self.fnt_mono_sm = font.Font(family="Courier New", size=8)

    # =====================================================================
    #  UI ASSEMBLY
    # =====================================================================

    def _build_ui(self):
        outer = tk.Frame(self.root, bg=THEME["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        self._build_header(outer)

        body = tk.Frame(outer, bg=THEME["bg"])
        body.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self._build_left_column(body)
        self._build_right_panel(body)

        # Thruster panel uses config-driven labels and roles
        self.thruster_panel = ThrusterPanel(
            outer, labels=THRUSTER_LABELS, roles=THRUSTER_ROLES)
        self.thruster_panel.pack(fill=tk.X, pady=(8, 0))

        self._build_log_panel(outer)

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self, parent):
        hdr = tk.Frame(parent, bg=THEME["panel"], height=56)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        tk.Frame(hdr, bg=THEME["accent"], width=4).pack(
            side=tk.LEFT, fill=tk.Y)

        title_blk = tk.Frame(hdr, bg=THEME["panel"])
        title_blk.pack(side=tk.LEFT, fill=tk.Y, padx=(14, 0))

        tk.Label(title_blk, text="BLUEROV2  MISSION CONTROL",
                 font=self.fnt_header, bg=THEME["panel"],
                 fg=THEME["accent"]).pack(anchor="w", pady=(8, 0))
        tk.Label(title_blk,
                 text="Underwater Vehicle Operations  //  v2.4.1",
                 font=self.fnt_lbl, bg=THEME["panel"],
                 fg=THEME["text_dim"]).pack(anchor="w")

        strip = tk.Frame(hdr, bg=THEME["panel"])
        strip.pack(side=tk.RIGHT, fill=tk.Y, padx=16)
        self._build_status_strip(strip)

    def _build_status_strip(self, parent):
        items = [
            ("SYS", "OFFLINE", "STATUS", THEME["danger"]),
            ("LINK", "NO LINK", "LINK", THEME["danger"]),
            ("MODE", "—", "MODE", THEME["text_dim"]),
            ("UTC", datetime.utcnow().strftime("%H:%M:%S"), "CLOCK",
             THEME["text_dim"]),
        ]
        for abbr, val, key, color in items:
            col = tk.Frame(parent, bg=THEME["panel"])
            col.pack(side=tk.LEFT, padx=12, pady=8)
            tk.Label(col, text=abbr, font=self.fnt_lbl,
                     bg=THEME["panel"], fg=THEME["text_dim"]).pack()
            lbl = tk.Label(col, text=val, font=self.fnt_sub,
                           bg=THEME["panel"], fg=color)
            lbl.pack()
            self.telemetry_labels[key] = lbl

        self._tick_clock()

        self.status_dot = tk.Label(
            parent, text="●", font=("Courier New", 16, "bold"),
            bg=THEME["panel"], fg=THEME["danger"])
        self.status_dot.pack(side=tk.LEFT, padx=(4, 0), pady=8)

    # =====================================================================
    #  LEFT COLUMN
    # =====================================================================

    def _build_left_column(self, parent):
        left = tk.Frame(parent, bg=THEME["bg"], width=CAM_W + 4)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        left.pack_propagate(False)

        tb = tk.Frame(left, bg=THEME["panel"], height=26)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)

        tk.Frame(tb, bg=THEME["accent"], width=3).pack(
            side=tk.LEFT, fill=tk.Y)
        tk.Label(tb, text=f"  PRIMARY CAMERA FEED  [{CAM_W}×{CAM_H}]",
                 font=self.fnt_sub, bg=THEME["panel"],
                 fg=THEME["accent"]).pack(side=tk.LEFT, pady=3)

        self.ai_status_lbl = tk.Label(
            tb, text="AI: LOADING", font=self.fnt_lbl,
            bg=THEME["panel"], fg=THEME["warning"])
        self.ai_status_lbl.pack(side=tk.RIGHT, padx=8)

        self.cam_status_lbl = tk.Label(
            tb, text="● NO SIGNAL", font=self.fnt_lbl,
            bg=THEME["panel"], fg=THEME["danger"])
        self.cam_status_lbl.pack(side=tk.RIGHT, padx=8)

        cam_border = tk.Frame(left, bg=THEME["border"])
        cam_border.pack()

        cam_inner = tk.Frame(
            cam_border, bg="black", width=CAM_W, height=CAM_H)
        cam_inner.pack(padx=1, pady=1)
        cam_inner.pack_propagate(False)

        self.video_label = tk.Label(
            cam_inner,
            text="◈  AWAITING VIDEO STREAM  ◈\n\nConnect to begin.",
            bg="black", fg=THEME["accent_dim"],
            font=("Courier New", 11, "bold"),
            width=CAM_W, height=CAM_H, compound=tk.CENTER)
        self.video_label.pack()

        self._build_hud_strip(left)

    def _build_hud_strip(self, parent):
        hud = tk.Frame(parent, bg=THEME["panel"], height=34,
                       width=CAM_W + 4)
        hud.pack(fill=tk.X, pady=(3, 0))
        hud.pack_propagate(False)

        items = [
            ("DEPTH", "HUD_DEPTH"), ("HEADING", "HUD_HDG"),
            ("ROLL", "HUD_ROLL"), ("PITCH", "HUD_PCH"),
            ("BATTERY", "HUD_BAT"), ("CURRENT", "HUD_CUR"),
        ]
        for i, (lbl_txt, key) in enumerate(items):
            cell = tk.Frame(hud, bg=THEME["panel"])
            cell.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

            tk.Label(cell, text=lbl_txt, font=self.fnt_lbl,
                     bg=THEME["panel"], fg=THEME["text_dim"]).pack(
                         pady=(3, 0))

            v = tk.Label(cell, text="—", font=self.fnt_mono_sm,
                         bg=THEME["panel"], fg=THEME["cyan"])
            v.pack()
            self.telemetry_labels[key] = v

            if i < len(items) - 1:
                tk.Frame(hud, bg=THEME["border"], width=1).pack(
                    side=tk.LEFT, fill=tk.Y, pady=4)

    # =====================================================================
    #  RIGHT PANEL
    # =====================================================================

    def _build_right_panel(self, parent):
        right = tk.Frame(parent, bg=THEME["panel"], width=360)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right.pack_propagate(False)

        canvas = tk.Canvas(right, bg=THEME["panel"],
                           highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(
            right, orient=tk.VERTICAL, command=canvas.yview)

        sf = tk.Frame(canvas, bg=THEME["panel"])
        sf.bind("<Configure>",
                lambda e: canvas.configure(
                    scrollregion=canvas.bbox("all")))

        win_id = canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(
                            int(-1 * (e.delta / 120)), "units"))

        self._build_telemetry_section(sf)
        self._build_systems_section(sf)
        self._build_controls_section(sf)

    def _section_header(self, parent, title, color):
        bar = tk.Frame(parent, bg=THEME["panel"])
        bar.pack(fill=tk.X, padx=8, pady=(10, 3))
        tk.Frame(bar, bg=color, width=3, height=14).pack(side=tk.LEFT)
        tk.Label(bar, text=f"  {title}", font=self.fnt_sub,
                 bg=THEME["panel"], fg=color).pack(side=tk.LEFT)

    def _build_telemetry_section(self, parent):
        self._section_header(parent, "VEHICLE TELEMETRY", THEME["accent"])

        grid = tk.Frame(parent, bg=THEME["panel"])
        grid.pack(fill=tk.X, padx=8, pady=(0, 4))
        grid.columnconfigure((0, 1), weight=1)

        cards = [
            ("BATTERY", "V", THEME["warning"]),
            ("CURRENT", "A", THEME["accent"]),
            ("DEPTH", "m", THEME["cyan"]),
            ("HEADING", "°", THEME["cyan"]),
            ("ROLL", "°", THEME["purple"]),
            ("PITCH", "°", THEME["purple"]),
        ]
        for idx, (key, unit, col) in enumerate(cards):
            r, c = divmod(idx, 2)
            card = TelemetryCard(grid, key, "—", unit, col)
            card.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
            self.telemetry_cards[key] = card

    def _build_systems_section(self, parent):
        self._section_header(parent, "SYSTEMS STATUS", THEME["warning"])

        frame = tk.Frame(parent, bg=THEME["panel"])
        frame.pack(fill=tk.X, padx=8, pady=(0, 4))

        systems = [
            ("Video Feed", "NO SIGNAL", THEME["danger"]),
            ("Telemetry Link", "OFFLINE", THEME["danger"]),
            ("Motor Control", "DISARMED", THEME["warning"]),
            ("Battery", "UNKNOWN", THEME["text_dim"]),
            ("AI Detection", "LOADING", THEME["warning"]),
        ]
        for name, status, color in systems:
            row = tk.Frame(frame, bg=THEME["card"])
            row.pack(fill=tk.X, pady=1)

            bar = tk.Frame(row, bg=color, width=3)
            bar.pack(side=tk.LEFT, fill=tk.Y)

            tk.Label(row, text=f"  {name}", font=self.fnt_lbl,
                     bg=THEME["card"], fg=THEME["text"], width=16,
                     anchor="w").pack(side=tk.LEFT, pady=5)

            lbl = tk.Label(row, text=status, font=self.fnt_lbl,
                           bg=THEME["card"], fg=color)
            lbl.pack(side=tk.RIGHT, padx=8)

            self.system_labels[name] = lbl
            self.system_labels[f"_{name}_bar"] = bar

    def _build_controls_section(self, parent):
        self._section_header(parent, "MISSION CONTROLS", THEME["success"])

        frame = tk.Frame(parent, bg=THEME["panel"])
        frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.btn_connect = GlowButton(
            frame, "CONNECT & INITIALISE",
            THEME["success"], self.start_system, icon="▶")
        self.btn_connect.pack(fill=tk.X, pady=2)

        self.btn_arm = GlowButton(
            frame, "ARM VEHICLE", THEME["text_dim"],
            self.toggle_arm, icon="▲", disabled=True)
        self.btn_arm.pack(fill=tk.X, pady=2)

        SeparatorLine(frame, label=" OPERATIONS").pack(
            fill=tk.X, pady=(4, 1))

        self.btn_deploy = GlowButton(
            frame, "DEPLOY", THEME["text_dim"],
            self.deploy_mission, icon="⬇", disabled=True)
        self.btn_deploy.pack(fill=tk.X, pady=2)

        self.btn_retrieve = GlowButton(
            frame, "RETRIEVE", THEME["text_dim"],
            self.retrieve_mission, icon="⬆", disabled=True)
        self.btn_retrieve.pack(fill=tk.X, pady=2)

        SeparatorLine(frame, label=" SAFETY").pack(
            fill=tk.X, pady=(4, 1))

        GlowButton(frame, "EMERGENCY STOP", THEME["danger"],
                   self.emergency_stop, icon="◼").pack(
                       fill=tk.X, pady=2)
        GlowButton(frame, "QUIT", THEME["text_dim"],
                   self.close_app, icon="✕").pack(
                       fill=tk.X, pady=2)

    # =====================================================================
    #  LOG PANEL
    # =====================================================================

    def _build_log_panel(self, parent):
        wrapper = tk.Frame(parent, bg=THEME["panel"])
        wrapper.pack(fill=tk.X, pady=(4, 0))

        tb = tk.Frame(wrapper, bg=THEME["panel"], height=20)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)

        make_bar(tb, THEME["success"])
        tk.Label(tb, text="  MISSION LOG", font=self.fnt_sub,
                 bg=THEME["panel"], fg=THEME["success"]).pack(
                     side=tk.LEFT, pady=1)
        tk.Button(tb, text="CLEAR", font=self.fnt_lbl,
                  bg=THEME["panel"], fg=THEME["text_dim"], bd=0,
                  cursor="hand2", command=self._clear_log).pack(
                      side=tk.RIGHT, padx=8)

        self.log_box = scrolledtext.ScrolledText(
            wrapper, font=self.fnt_log, bg=THEME["log_bg"],
            fg=THEME["log_text"], insertbackground=THEME["log_text"],
            selectbackground=THEME["success_dim"],
            height=4, bd=0, relief=tk.FLAT)
        self.log_box.pack(fill=tk.X, padx=1, pady=(1, 0))
        self.log_box.config(state=tk.DISABLED)

    # =====================================================================
    #  KEYBOARD
    # =====================================================================

    def _bind_keys(self):
        for key in MOVEMENT_KEYS:
            for case in (key, key.upper()):
                self.root.bind(
                    f'<KeyPress-{case}>',
                    lambda e, k=key: self._set_key(k, True))
                self.root.bind(
                    f'<KeyRelease-{case}>',
                    lambda e, k=key: self._set_key(k, False))
        self.root.bind('<space>', lambda e: self.emergency_stop())
        self._process_keys()

    def _set_key(self, key, state):
        self._keys[key] = state

    def _process_keys(self):
        if self.armed_state and self.telemetry_backend.running:
            S = CONTROL_SPEED
            pairs = [('w', 's'), ('d', 'a'), ('e', 'q'), ('r', 'f')]
            vals = [S if self._keys[p] else (-S if self._keys[n] else 0.0)
                    for p, n in pairs]

            if any(self._keys.values()):
                self._state.send_command(Command(
                    name="set_motion",
                    kwargs=dict(forward=vals[0], lateral=vals[1],
                                throttle=vals[3], yaw=vals[2])))

        self.root.after(100, self._process_keys)

    # =====================================================================
    #  SHARED STATE POLLING
    # =====================================================================

    def _poll_shared_state(self):
        # 1. Drain telemetry display updates
        for update in self._state.drain_telemetry_updates():
            self._apply_telemetry_update(
                update.key, update.value, update.color)

        # 2. Drain log messages
        logs = self._state.drain_logs()
        if logs:
            self.log_box.config(state=tk.NORMAL)
            for msg in logs:
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self.log_box.insert(tk.END, f"[{ts}]  {msg}\n")
            self.log_box.see(tk.END)
            self.log_box.config(state=tk.DISABLED)

        # 3. Update video frame
        self._poll_video_frame()

    def _poll_video_frame(self):
        if not self.video_backend.running:
            return

        frame, fps = self._state.get_video_frame()
        if frame is not None:
            frame = cv2.resize(frame, (CAM_W, CAM_H),
                               interpolation=cv2.INTER_LINEAR)
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            img_tk = ImageTk.PhotoImage(image=img)
            self.video_label.configure(image=img_tk, text="")
            self._current_frame = img_tk

    # =====================================================================
    #  TELEMETRY UPDATE DISPATCH
    # =====================================================================

    def _apply_telemetry_update(self, key, value, color_hex=None):
        if key in self.telemetry_cards:
            self.telemetry_cards[key].update(value, color_hex)

        if key in HUD_MAP and HUD_MAP[key] in self.telemetry_labels:
            self.telemetry_labels[HUD_MAP[key]].config(text=str(value))

        if key in self.telemetry_labels:
            kw = {"text": str(value)}
            if color_hex:
                kw["fg"] = color_hex
            self.telemetry_labels[key].config(**kw)

        if key == "STATUS" and "MODE" in self.telemetry_labels:
            self.telemetry_labels["MODE"].config(
                text=str(value), fg=THEME["accent"])

        if key == "ARMED_STATE":
            self._sync_armed_state(str(value) == "⚠ ARMED")

        if key == "THRUSTERS" and isinstance(value, list):
            self.thruster_panel.update_values(value)

        if key == "BATTERY":
            self._update_battery_health(value)

    def _update_battery_health(self, value):
        try:
            v = float(str(value))
            if v <= 0:
                return
            status, color = (
                (f"{v:.1f}V GOOD", THEME["success"]) if v > 15.5 else
                (f"{v:.1f}V OK",   THEME["warning"]) if v > 14.5 else
                (f"{v:.1f}V LOW",  THEME["warning"]) if v > 13.5 else
                (f"{v:.1f}V CRIT", THEME["danger"])
            )
            self._set_system("Battery", status, color)
        except (ValueError, TypeError):
            pass

    def _sync_armed_state(self, is_armed: bool):
        if is_armed == self.armed_state:
            return
        self.armed_state = is_armed
        self.thruster_panel.set_armed(is_armed)

        if is_armed:
            self.btn_arm.update_label("DISARM VEHICLE", THEME["danger"])
            self.btn_arm.set_disabled(False)
            self._set_ops_buttons(True)
            self._set_system("Motor Control", "ARMED", THEME["success"])
        else:
            self.btn_arm.update_label("ARM VEHICLE", THEME["warning"])
            self._set_ops_buttons(False)
            self._set_system("Motor Control", "DISARMED",
                             THEME["warning"])

    def _set_ops_buttons(self, enabled: bool):
        color = THEME["cyan"] if enabled else THEME["text_dim"]
        for btn, label in [(self.btn_deploy, "DEPLOY"),
                           (self.btn_retrieve, "RETRIEVE")]:
            btn.set_disabled(not enabled)
            btn.update_label(label, color)

    # =====================================================================
    #  PERIODIC TICKS
    # =====================================================================

    def _blink_tick(self):
        self._blink_state = not self._blink_state
        if not self.telemetry_backend.running:
            col = (THEME["danger"] if self._blink_state
                   else THEME["danger_dim"])
            self.status_dot.config(fg=col)
        else:
            self.status_dot.config(fg=THEME["success"])

    def _thruster_tick(self):
        self.thruster_panel.step_animation()

    def _poll_telemetry(self):
        if not self.video_backend.running:
            return

        frame, fps = self._state.get_video_frame()
        has_frame = frame is not None

        if has_frame:
            self.cam_status_lbl.config(
                text=f"● LIVE  {fps:.0f}fps", fg=THEME["success"])
            self._set_system("Video Feed", f"LIVE {fps:.0f}fps",
                             THEME["success"])
        else:
            self.cam_status_lbl.config(
                text="● WAITING…", fg=THEME["warning"])

        yolo_loaded, yolo_enabled = self._state.get_video_ai_status()
        if yolo_enabled and yolo_loaded:
            self.ai_status_lbl.config(
                text="AI: ACTIVE", fg=THEME["success"])
            self._set_system("AI Detection", "ACTIVE",
                             THEME["success"])
        elif not yolo_enabled:
            self.ai_status_lbl.config(
                text="AI: OFF", fg=THEME["text_dim"])
            self._set_system("AI Detection", "DISABLED",
                             THEME["text_dim"])

    # =====================================================================
    #  ACTIONS
    # =====================================================================

    def start_system(self):
        self._state.log("═" * 44)
        self._state.log("Initialising mission systems…")

        for name, fn in [("Video backend", self.video_backend.start),
                         ("Telemetry link",
                          self.telemetry_backend.start)]:
            self._state.log(f"  ▶ {name} starting…")
            fn()

        self._state.log("  ▶ Video display loop starting…")

        self.telemetry_labels["STATUS"].config(
            text="ONLINE", fg=THEME["success"])
        self.telemetry_labels["LINK"].config(
            text="ACTIVE", fg=THEME["success"])
        self.status_dot.config(fg=THEME["success"])

        self._set_system("Telemetry Link", "ACTIVE", THEME["success"])
        self._set_system("Video Feed", "CONNECTING…", THEME["warning"])
        self._set_system("Battery", "MONITOR", THEME["warning"])

        self.btn_connect.set_disabled(True)
        self.btn_connect.update_label("SYSTEM ACTIVE",
                                      THEME["text_dim"])
        self.btn_arm.set_disabled(False)
        self.btn_arm.update_label("ARM VEHICLE", THEME["warning"])

        self._state.log("Systems online.")
        self._state.log("Awaiting MAVLink heartbeat…")
        self._state.log("═" * 44)

    def toggle_arm(self):
        if not self.telemetry_backend.running:
            self._state.log("⚠  Not connected.")
            return

        new_state = not self.armed_state
        action = "Arming" if new_state else "Disarming"
        self._state.log(f"{action}…")

        cmd_name = "arm" if new_state else "disarm"
        self._state.send_command(Command(name=cmd_name))
        self._sync_armed_state(new_state)

        if new_state:
            self._state.log(
                "Vehicle ARMED — keyboard control active.")
        else:
            self._state.log("Vehicle DISARMED.")

    def emergency_stop(self):
        self._state.log("⚠  EMERGENCY STOP!")
        if self.telemetry_backend.running:
            self._state.send_command(Command(name="stop_motors"))
        for k in self._keys:
            self._keys[k] = False
        self.thruster_panel.update_values(
            [0.0] * THRUSTER_COUNT)

    def deploy_mission(self):
        if not self.armed_state:
            self._state.log("⚠  Arm vehicle first.")
            return
        self._state.log("Deploying…")
        self.btn_deploy.set_disabled(True)
        self.btn_deploy.update_label("DEPLOYING…", THEME["text_dim"])

    def retrieve_mission(self):
        if not self.telemetry_backend.running:
            self._state.log("⚠  Not connected.")
            return
        self._state.log("Retrieving…")
        self.btn_deploy.set_disabled(False)
        self.btn_deploy.update_label("DEPLOY", THEME["cyan"])

    # =====================================================================
    #  UTILITIES
    # =====================================================================

    def _set_system(self, name, status, color):
        if name in self.system_labels:
            self.system_labels[name].config(text=status, fg=color)
        bar_key = f"_{name}_bar"
        if bar_key in self.system_labels:
            self.system_labels[bar_key].config(bg=color)

    def _tick_clock(self):
        if "CLOCK" in self.telemetry_labels:
            self.telemetry_labels["CLOCK"].config(
                text=datetime.utcnow().strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    def _log_to_widget(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_box.config(state=tk.NORMAL)
        self.log_box.insert(tk.END, f"[{ts}]  {message}\n")
        self.log_box.see(tk.END)
        self.log_box.config(state=tk.DISABLED)

    def _clear_log(self):
        self.log_box.config(state=tk.NORMAL)
        self.log_box.delete(1.0, tk.END)
        self.log_box.config(state=tk.DISABLED)

    # =====================================================================
    #  SHUTDOWN
    # =====================================================================

    def close_app(self):
        self._state.log("◼  SHUTDOWN initiated.")
        try:
            if self.telemetry_backend.running:
                self._state.send_command(Command(name="stop_motors"))
            if self.armed_state:
                self._state.send_command(Command(name="disarm"))
            self.video_backend.stop()
            self.telemetry_backend.stop()
        except Exception as e:
            self._state.log(f"  Warning: {e}")
        self.root.after(SHUTDOWN_DELAY_MS, self.root.destroy)


# =============================================================================
#  ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    root = tk.Tk()
    app = RobotApp(root)
    root.mainloop()