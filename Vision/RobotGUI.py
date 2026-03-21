import tkinter as tk
from tkinter import scrolledtext, font
from PIL import Image, ImageTk
import cv2
from datetime import datetime

# Custom Modules
from RobotBackend import RobotLogic
from RobotTelemetry import TelemetryHandler

# =============================================================================
#  THEME & CONSTANTS
# =============================================================================
THEME = {
    "bg":           "#060912",
    "panel":        "#0D1117",
    "card":         "#161B27",
    "card_hover":   "#1E2535",
    "border":       "#1F2D45",
    "border_bright":"#2A4080",
    "text":         "#C9D8E8",
    "text_dim":     "#5A7090",
    "text_bright":  "#EAF4FF",
    "accent":       "#00C8FF",
    "accent_dim":   "#005F78",
    "success":      "#00E676",
    "success_dim":  "#004D26",
    "danger":       "#FF1744",
    "danger_dim":   "#4D0010",
    "warning":      "#FFD600",
    "warning_dim":  "#4D4000",
    "cyan":         "#18FFFF",
    "purple":       "#7C4DFF",
    "log_bg":       "#020408",
    "log_text":     "#00E676",
    "log_dim":      "#005520",
}

VIDEO_REFRESH_MS    = 30
SHUTDOWN_DELAY_MS   = 1200
BLINK_INTERVAL_MS   = 800
THRUSTER_REFRESH_MS = 50   # 20 Hz thruster bar refresh

# BlueROV2 thruster layout labels
THRUSTER_LABELS = ["T1", "T2", "T3", "T4", "T5", "T6"]
THRUSTER_ROLES  = [
    "FWD-L", "FWD-R",   # Horizontal vectored
    "LAT-F", "LAT-A",   # Lateral
    "VRT-FL","VRT-FR",  # Vertical
]


# =============================================================================
#  HELPER WIDGETS
# =============================================================================
class SeparatorLine(tk.Canvas):
    """Slim horizontal rule with optional inline label."""
    def __init__(self, parent, label="", color=None, **kw):
        color = color or THEME["border"]
        super().__init__(parent, height=14, bg=THEME["panel"],
                         highlightthickness=0, **kw)
        self.bind("<Configure>", lambda e: self._draw(label, color))

    def _draw(self, label, color):
        self.delete("all")
        w  = self.winfo_width()
        cy = 7
        if label:
            self.create_line(0, cy, w * 0.06, cy, fill=color, width=1)
            self.create_text(w * 0.07, cy, text=label, anchor="w",
                             fill=color, font=("Courier New", 7, "bold"))
            txt_w = len(label) * 5.5
            self.create_line(w * 0.07 + txt_w + 6, cy, w, cy,
                             fill=color, width=1)
        else:
            self.create_line(0, cy, w, cy, fill=color, width=1)


class GlowButton(tk.Frame):
    """Button with coloured left-accent bar, hover glow, chevron."""
    def __init__(self, parent, text, color, command,
                 icon="", disabled=False, **kw):
        super().__init__(parent, bg=THEME["panel"], cursor="hand2", **kw)
        self._color    = color
        self._command  = command
        self._disabled = disabled

        self._bar = tk.Frame(self,
                             bg=color if not disabled else THEME["border"],
                             width=4)
        self._bar.pack(side=tk.LEFT, fill=tk.Y)

        self._body = tk.Frame(self, bg=THEME["card"])
        self._body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        row = tk.Frame(self._body, bg=THEME["card"])
        row.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        if icon:
            tk.Label(row, text=icon, font=("Courier New", 11),
                     bg=THEME["card"],
                     fg=color if not disabled else THEME["text_dim"]).pack(
                         side=tk.LEFT)

        self._lbl = tk.Label(row, text=text,
                             font=("Courier New", 10, "bold"),
                             bg=THEME["card"],
                             fg=color if not disabled else THEME["text_dim"],
                             padx=6)
        self._lbl.pack(side=tk.LEFT)

        self._chev = tk.Label(row, text="›",
                              font=("Courier New", 14, "bold"),
                              bg=THEME["card"], fg=THEME["text_dim"])
        self._chev.pack(side=tk.RIGHT)

        for w in (self, self._body, self._bar, row, self._lbl, self._chev):
            w.bind("<Enter>",    self._on_enter)
            w.bind("<Leave>",    self._on_leave)
            w.bind("<Button-1>", self._on_click)

    def _on_enter(self, _=None):
        if self._disabled:
            return
        self._body.config(bg=THEME["card_hover"])
        self._lbl.config(bg=THEME["card_hover"], fg=THEME["text_bright"])
        self._chev.config(bg=THEME["card_hover"], fg=self._color)

    def _on_leave(self, _=None):
        self._body.config(bg=THEME["card"])
        self._lbl.config(bg=THEME["card"],
                         fg=self._color if not self._disabled
                         else THEME["text_dim"])
        self._chev.config(bg=THEME["card"], fg=THEME["text_dim"])

    def _on_click(self, _=None):
        if not self._disabled and self._command:
            self._command()

    def set_disabled(self, state: bool):
        self._disabled = state
        col = THEME["border"] if state else self._color
        self._bar.config(bg=col)
        self._lbl.config(fg=col)
        self._body.config(bg=THEME["card"])

    def update_label(self, text, color=None):
        if color:
            self._color = color
        self._lbl.config(
            text=text,
            fg=self._color if not self._disabled else THEME["text_dim"])
        self._bar.config(
            bg=self._color if not self._disabled else THEME["border"])


class TelemetryCard(tk.Frame):
    """Single telemetry metric card."""
    def __init__(self, parent, label, value, unit="", color=None, **kw):
        color = color or THEME["accent"]
        super().__init__(parent, bg=THEME["card"], relief=tk.FLAT, **kw)

        tk.Label(self, text=label,
                 font=("Courier New", 7, "bold"),
                 bg=THEME["card"], fg=THEME["text_dim"],
                 anchor="w").pack(fill=tk.X, padx=10, pady=(8, 0))

        self._val_lbl = tk.Label(self, text=value,
                                 font=("Courier New", 16, "bold"),
                                 bg=THEME["card"], fg=color, anchor="w")
        self._val_lbl.pack(fill=tk.X, padx=10)

        tk.Label(self, text=unit,
                 font=("Courier New", 7),
                 bg=THEME["card"], fg=THEME["text_dim"],
                 anchor="w").pack(fill=tk.X, padx=10, pady=(0, 4))

        tk.Frame(self, bg=color, height=2).pack(fill=tk.X)

    def update(self, value, color=None):
        kw = {"text": value}
        if color:
            kw["fg"] = color
        self._val_lbl.config(**kw)


# =============================================================================
#  THRUSTER BAR WIDGET
# =============================================================================
class ThrusterBar(tk.Frame):
    """
    Vertical bi-directional bar for a single thruster.

    value range : -1.0  →  +1.0
      positive  : bar grows upward   (green shades)
      negative  : bar grows downward (amber shades)
      idle (0)  : only the centre tick is visible
    """

    # Colour stops for positive thrust (dim → bright)
    _POS_COLORS = ["#004D20", "#007A30", "#00B344", "#00E676"]
    # Colour stops for negative thrust (dim → bright)
    _NEG_COLORS = ["#4D3300", "#997700", "#CC9900", "#FFD600"]

    def __init__(self, parent, label: str, role: str, index: int, **kw):
        super().__init__(parent, bg=THEME["card"], **kw)
        self._value  = 0.0
        self._label  = label
        self._target = 0.0   # for smooth animation
        self._current = 0.0

        # ── Layout: index badge + canvas + label row ──────────────────────
        badge_row = tk.Frame(self, bg=THEME["card"])
        badge_row.pack(fill=tk.X, padx=4, pady=(6, 2))

        tk.Label(badge_row,
                 text=f"#{index + 1}",
                 font=("Courier New", 7, "bold"),
                 bg=THEME["card"], fg=THEME["text_dim"]).pack(side=tk.LEFT)

        tk.Label(badge_row,
                 text=label,
                 font=("Courier New", 9, "bold"),
                 bg=THEME["card"], fg=THEME["accent"]).pack(side=tk.RIGHT)

        # Canvas for the bar
        self._canvas = tk.Canvas(
            self, bg=THEME["log_bg"],
            highlightthickness=1,
            highlightbackground=THEME["border"],
            width=46, height=160
        )
        self._canvas.pack(padx=6, pady=2)

        # Role sub-label
        tk.Label(self, text=role,
                 font=("Courier New", 6),
                 bg=THEME["card"], fg=THEME["text_dim"]).pack(pady=(0, 2))

        # Percentage readout
        self._pct_lbl = tk.Label(
            self, text="0 %",
            font=("Courier New", 8, "bold"),
            bg=THEME["card"], fg=THEME["success"])
        self._pct_lbl.pack(pady=(0, 6))

        # Accent line at bottom matches polarity
        self._accent = tk.Frame(self, height=2, bg=THEME["border"])
        self._accent.pack(fill=tk.X)

        self._canvas.bind("<Configure>", lambda e: self._redraw())
        self._redraw()

    # ------------------------------------------------------------------
    def set_value(self, v: float):
        """Accept –1.0 … +1.0 and animate toward it."""
        self._target = max(-1.0, min(1.0, v))

    def _lerp(self, a: float, b: float, t: float = 0.25) -> float:
        return a + (b - a) * t

    def step(self):
        """Called every THRUSTER_REFRESH_MS to smooth-animate the bar."""
        self._current = self._lerp(self._current, self._target)
        if abs(self._current - self._target) < 0.005:
            self._current = self._target
        self._redraw()

    # ------------------------------------------------------------------
    def _redraw(self):
        c = self._canvas
        c.delete("all")

        W = c.winfo_width()
        H = c.winfo_height()
        if W < 2 or H < 2:
            return

        mid   = H // 2
        v     = self._current           # –1 … +1
        pct   = int(abs(v) * 100)
        bar_h = int(abs(v) * (mid - 4))

        # ── Background guide lines ────────────────────────────────────
        for frac in (0.25, 0.5, 0.75):
            y_top = int(mid * frac)
            y_bot = H - y_top
            c.create_line(0, y_top, W, y_top,
                          fill=THEME["border"], dash=(2, 4))
            c.create_line(0, y_bot, W, y_bot,
                          fill=THEME["border"], dash=(2, 4))

        # ── Bar fill ──────────────────────────────────────────────────
        if v >= 0:
            # Positive → grow upward
            fill_color = self._gradient_color(v, self._POS_COLORS)
            glow_color = self._POS_COLORS[-1]
            if bar_h > 0:
                c.create_rectangle(2, mid - bar_h, W - 2, mid,
                                   fill=fill_color, outline="")
                # Top glow strip
                c.create_rectangle(2, mid - bar_h, W - 2,
                                   mid - bar_h + min(3, bar_h),
                                   fill=glow_color, outline="")
        else:
            # Negative → grow downward
            fill_color = self._gradient_color(abs(v), self._NEG_COLORS)
            glow_color = self._NEG_COLORS[-1]
            if bar_h > 0:
                c.create_rectangle(2, mid, W - 2, mid + bar_h,
                                   fill=fill_color, outline="")
                # Bottom glow strip
                c.create_rectangle(2, mid + bar_h - min(3, bar_h),
                                   W - 2, mid + bar_h,
                                   fill=glow_color, outline="")

        # ── Centre zero line ─────────────────────────────────────────
        zero_col = THEME["accent"] if v == 0.0 else THEME["border_bright"]
        c.create_line(0, mid, W, mid, fill=zero_col, width=1)

        # ── Tick marks on right edge (0 / 50 / 100 %) ────────────────
        for y_off, txt in ((0, "100"), (mid // 2, " 50"), (mid, "  0")):
            c.create_line(W - 6, y_off + 2,
                          W,     y_off + 2,
                          fill=THEME["text_dim"], width=1)
            c.create_line(W - 6, H - y_off - 2,
                          W,     H - y_off - 2,
                          fill=THEME["text_dim"], width=1)

        # ── Update readout label & accent bar ─────────────────────────
        if v > 0.01:
            self._pct_lbl.config(text=f"+{pct} %", fg=THEME["success"])
            self._accent.config(bg=THEME["success"])
        elif v < -0.01:
            self._pct_lbl.config(text=f"−{pct} %", fg=THEME["warning"])
            self._accent.config(bg=THEME["warning"])
        else:
            self._pct_lbl.config(text="0 %", fg=THEME["text_dim"])
            self._accent.config(bg=THEME["border"])

    # ------------------------------------------------------------------
    @staticmethod
    def _gradient_color(v: float, stops: list) -> str:
        """Interpolate between colour stops based on 0..1 intensity."""
        if v <= 0:
            return stops[0]
        if v >= 1:
            return stops[-1]
        n       = len(stops) - 1
        scaled  = v * n
        lo      = int(scaled)
        hi      = min(lo + 1, n)
        t       = scaled - lo
        return ThrusterBar._lerp_hex(stops[lo], stops[hi], t)

    @staticmethod
    def _lerp_hex(c1: str, c2: str, t: float) -> str:
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"


# =============================================================================
#  THRUSTER PANEL  (houses all ThrusterBar widgets)
# =============================================================================
class ThrusterPanel(tk.Frame):
    """
    Full-width panel displaying one ThrusterBar per thruster.
    Call  update(values)  with a list/dict of –1..+1 floats.
    """
    def __init__(self, parent, labels: list, roles: list, **kw):
        super().__init__(parent, bg=THEME["panel"], **kw)
        self._bars: list[ThrusterBar] = []

        # ── Title bar ─────────────────────────────────────────────────
        title_bar = tk.Frame(self, bg=THEME["panel"], height=26)
        title_bar.pack(fill=tk.X)
        title_bar.pack_propagate(False)

        tk.Frame(title_bar, bg=THEME["success"], width=3).pack(
            side=tk.LEFT, fill=tk.Y)

        tk.Label(title_bar,
                 text="  THRUSTER OUTPUT",
                 font=("Courier New", 10, "bold"),
                 bg=THEME["panel"], fg=THEME["success"]).pack(
                     side=tk.LEFT, pady=3)

        self._armed_badge = tk.Label(
            title_bar,
            text="  ◼ DISARMED  ",
            font=("Courier New", 8, "bold"),
            bg=THEME["panel"], fg=THEME["text_dim"])
        self._armed_badge.pack(side=tk.RIGHT, padx=10)

        # Max single-thruster readout
        self._peak_lbl = tk.Label(
            title_bar,
            text="PEAK: — %",
            font=("Courier New", 8, "bold"),
            bg=THEME["panel"], fg=THEME["text_dim"])
        self._peak_lbl.pack(side=tk.RIGHT, padx=16)

        # ── Bar container ─────────────────────────────────────────────
        bar_row = tk.Frame(self, bg=THEME["panel"])
        bar_row.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 6))

        for i, (lbl, role) in enumerate(zip(labels, roles)):
            # Vertical divider between bars
            if i > 0:
                tk.Frame(bar_row, bg=THEME["border"], width=1).pack(
                    side=tk.LEFT, fill=tk.Y, pady=4)

            bar = ThrusterBar(bar_row, lbl, role, i)
            bar.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
            self._bars.append(bar)

    # ------------------------------------------------------------------
    def update_values(self, values):
        """
        values : list of floats  OR  dict {label: float}
        Each value in range –1.0 … +1.0.
        """
        if isinstance(values, dict):
            for i, lbl in enumerate(THRUSTER_LABELS):
                if lbl in values and i < len(self._bars):
                    self._bars[i].set_value(values[lbl])
        else:
            for i, v in enumerate(values):
                if i < len(self._bars):
                    self._bars[i].set_value(v)

        # Peak display
        peak = max((abs(b._target) for b in self._bars), default=0.0)
        peak_pct = int(peak * 100)
        col = (THEME["danger"]  if peak > 0.8 else
               THEME["warning"] if peak > 0.5 else
               THEME["success"])
        self._peak_lbl.config(text=f"PEAK: {peak_pct:3d} %", fg=col)

    def step_animation(self):
        """Advance every bar's smooth interpolation one step."""
        for bar in self._bars:
            bar.step()

    def set_armed(self, armed: bool):
        if armed:
            self._armed_badge.config(text="  ▲ ARMED  ",
                                     fg=THEME["danger"])
        else:
            self._armed_badge.config(text="  ◼ DISARMED  ",
                                     fg=THEME["text_dim"])
            # Zero all bars on disarm
            for bar in self._bars:
                bar.set_value(0.0)


# =============================================================================
#  MAIN APPLICATION
# =============================================================================
class RobotApp:

    def __init__(self, root: tk.Tk):
        self.root          = root
        self.armed_state   = False
        self._blink_state  = False

        self.telemetry_cards:  dict[str, TelemetryCard] = {}
        self.system_labels:    dict[str, tk.Label]       = {}
        self.telemetry_labels: dict[str, tk.Label]       = {}

        # ── Backends ──────────────────────────────────────────────────
        self.video_backend     = RobotLogic(self.log)
        self.telemetry_backend = TelemetryHandler(
            self.update_telemetry_display, self.log
        )

        self._configure_window()
        self._build_ui()

        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

        self.log("Mission Control initialised. Awaiting connection.")
        self._start_status_blink()
        self._start_thruster_animation()

    # =========================================================================
    #  WINDOW
    # =========================================================================
    def _configure_window(self):
        self.root.title("BlueROV2 — Mission Control System")
        self.root.geometry("1680x1020")
        self.root.minsize(1280, 860)
        self.root.configure(bg=THEME["bg"])

        self.fnt_header  = font.Font(family="Courier New", size=16, weight="bold")
        self.fnt_title   = font.Font(family="Courier New", size=10, weight="bold")
        self.fnt_sub     = font.Font(family="Courier New", size=9,  weight="bold")
        self.fnt_val     = font.Font(family="Courier New", size=14, weight="bold")
        self.fnt_lbl     = font.Font(family="Courier New", size=7,  weight="bold")
        self.fnt_log     = font.Font(family="Courier New", size=8)
        self.fnt_mono_sm = font.Font(family="Courier New", size=8)

    # =========================================================================
    #  UI ASSEMBLY
    # =========================================================================
    def _build_ui(self):
        outer = tk.Frame(self.root, bg=THEME["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        self._create_header(outer)

        # ── Main body: video-left  |  controls-right ──────────────────
        body = tk.Frame(outer, bg=THEME["bg"])
        body.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self._create_video_panel(body)
        self._create_right_panel(body)

        # ── Thruster panel (full width, above log) ─────────────────────
        self._create_thruster_panel(outer)

        # ── Mission log ───────────────────────────────────────────────
        self._create_log_panel(outer)

    # =========================================================================
    #  HEADER
    # =========================================================================
    def _create_header(self, parent):
        hdr = tk.Frame(parent, bg=THEME["panel"], height=64)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        tk.Frame(hdr, bg=THEME["accent"], width=4).pack(
            side=tk.LEFT, fill=tk.Y)

        title_blk = tk.Frame(hdr, bg=THEME["panel"])
        title_blk.pack(side=tk.LEFT, fill=tk.Y, padx=(16, 0))

        tk.Label(title_blk, text="BLUEROV2  MISSION CONTROL",
                 font=self.fnt_header,
                 bg=THEME["panel"], fg=THEME["accent"]).pack(
                     anchor="w", pady=(10, 0))

        tk.Label(title_blk,
                 text="Underwater Vehicle Operations Platform  //  v2.4.1",
                 font=self.fnt_lbl,
                 bg=THEME["panel"], fg=THEME["text_dim"]).pack(anchor="w")

        strip = tk.Frame(hdr, bg=THEME["panel"])
        strip.pack(side=tk.RIGHT, fill=tk.Y, padx=20)
        self._build_status_strip(strip)

    def _build_status_strip(self, parent):
        items = [
            ("SYS",  "OFFLINE",  "STATUS"),
            ("LINK", "NO LINK",  "LINK"),
            ("UTC",  datetime.utcnow().strftime("%H:%M:%S"), "CLOCK"),
        ]
        for abbr, val, key in items:
            col = tk.Frame(parent, bg=THEME["panel"])
            col.pack(side=tk.LEFT, padx=14, pady=10)
            tk.Label(col, text=abbr, font=self.fnt_lbl,
                     bg=THEME["panel"], fg=THEME["text_dim"]).pack()
            lbl = tk.Label(
                col, text=val, font=self.fnt_sub,
                bg=THEME["panel"],
                fg=THEME["danger"] if key in ("STATUS", "LINK")
                else THEME["text_dim"])
            lbl.pack()
            self.telemetry_labels[key] = lbl

        self._tick_clock()

        self.status_dot = tk.Label(
            parent, text="●",
            font=("Courier New", 18, "bold"),
            bg=THEME["panel"], fg=THEME["danger"])
        self.status_dot.pack(side=tk.LEFT, padx=(4, 0), pady=10)

    # =========================================================================
    #  VIDEO PANEL
    # =========================================================================
    def _create_video_panel(self, parent):
        left = tk.Frame(parent, bg=THEME["bg"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # Title bar
        title_bar = tk.Frame(left, bg=THEME["panel"], height=28)
        title_bar.pack(fill=tk.X)
        title_bar.pack_propagate(False)

        tk.Frame(title_bar, bg=THEME["accent"], width=3).pack(
            side=tk.LEFT, fill=tk.Y)
        tk.Label(title_bar, text="  PRIMARY CAMERA FEED",
                 font=self.fnt_sub,
                 bg=THEME["panel"], fg=THEME["accent"]).pack(
                     side=tk.LEFT, pady=4)

        self.cam_status_lbl = tk.Label(
            title_bar, text="● NO SIGNAL",
            font=self.fnt_lbl,
            bg=THEME["panel"], fg=THEME["danger"])
        self.cam_status_lbl.pack(side=tk.RIGHT, padx=12)

        # Video canvas
        border = tk.Frame(left, bg=THEME["border"])
        border.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

        inner = tk.Frame(border, bg="black")
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.video_label = tk.Label(
            inner,
            text="◈  AWAITING VIDEO STREAM  ◈\n\nConnect and initialise to begin.",
            bg="black", fg=THEME["accent_dim"],
            font=("Courier New", 13, "bold"),
            compound=tk.CENTER)
        self.video_label.pack(fill=tk.BOTH, expand=True)

        self._create_hud_strip(left)

    def _create_hud_strip(self, parent):
        hud = tk.Frame(parent, bg=THEME["panel"], height=36)
        hud.pack(fill=tk.X, pady=(3, 0))
        hud.pack_propagate(False)

        hud_items = [
            ("DEPTH",   "— m", "HUD_DEPTH"),
            ("HEADING", "— °", "HUD_HDG"),
            ("ROLL",    "— °", "HUD_ROLL"),
            ("PITCH",   "— °", "HUD_PCH"),
            ("BATTERY", "— V", "HUD_BAT"),
            ("CURRENT", "— A", "HUD_CUR"),
        ]
        for lbl_txt, val_txt, key in hud_items:
            cell = tk.Frame(hud, bg=THEME["panel"])
            cell.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
            tk.Label(cell, text=lbl_txt, font=self.fnt_lbl,
                     bg=THEME["panel"], fg=THEME["text_dim"]).pack(pady=(4, 0))
            v = tk.Label(cell, text=val_txt, font=self.fnt_mono_sm,
                         bg=THEME["panel"], fg=THEME["cyan"])
            v.pack()
            self.telemetry_labels[key] = v
            if lbl_txt != "CURRENT":
                tk.Frame(hud, bg=THEME["border"], width=1).pack(
                    side=tk.LEFT, fill=tk.Y, pady=6)

    # =========================================================================
    #  RIGHT PANEL
    # =========================================================================
    def _create_right_panel(self, parent):
        right = tk.Frame(parent, bg=THEME["panel"], width=400)
        right.pack(side=tk.RIGHT, fill=tk.Y)
        right.pack_propagate(False)

        canvas    = tk.Canvas(right, bg=THEME["panel"],
                              highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(right, orient=tk.VERTICAL,
                                 command=canvas.yview)
        self._scroll_frame = tk.Frame(canvas, bg=THEME["panel"])

        self._scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        win_id = canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(
                int(-1 * (e.delta / 120)), "units"))

        sf = self._scroll_frame
        self._create_telemetry_section(sf)
        self._create_systems_section(sf)
        self._create_controls_section(sf)

    # ── Telemetry ──────────────────────────────────────────────────────────
    def _create_telemetry_section(self, parent):
        self._section_header(parent, "VEHICLE TELEMETRY", THEME["accent"])

        grid = tk.Frame(parent, bg=THEME["panel"])
        grid.pack(fill=tk.X, padx=10, pady=(0, 4))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        card_defs = [
            ("BATTERY", "0.00", "V",  THEME["warning"], "BATTERY"),
            ("CURRENT", "0.0",  "A",  THEME["accent"],  "CURRENT"),
            ("DEPTH",   "0.00", "m",  THEME["cyan"],    "DEPTH"),
            ("HEADING", "0",    "°",  THEME["cyan"],    "HEADING"),
            ("ROLL",    "0.0",  "°",  THEME["purple"],  "ROLL"),
            ("PITCH",   "0.0",  "°",  THEME["purple"],  "PITCH"),
        ]
        for idx, (label, val, unit, color, key) in enumerate(card_defs):
            r, c = divmod(idx, 2)
            card = TelemetryCard(grid, label, val, unit, color)
            card.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
            self.telemetry_cards[key] = card

    # ── Systems ────────────────────────────────────────────────────────────
    def _create_systems_section(self, parent):
        self._section_header(parent, "SYSTEMS STATUS", THEME["warning"])

        frame = tk.Frame(parent, bg=THEME["panel"])
        frame.pack(fill=tk.X, padx=10, pady=(0, 4))

        systems = [
            ("Video Feed",     "NO SIGNAL", THEME["danger"]),
            ("Telemetry Link", "OFFLINE",   THEME["danger"]),
            ("Motor Control",  "DISARMED",  THEME["warning"]),
            ("Battery",        "UNKNOWN",   THEME["text_dim"]),
        ]
        for name, status, color in systems:
            row = tk.Frame(frame, bg=THEME["card"])
            row.pack(fill=tk.X, pady=2)

            tk.Frame(row, bg=color, width=3).pack(side=tk.LEFT, fill=tk.Y)
            tk.Label(row, text=f"  {name}",
                     font=self.fnt_lbl,
                     bg=THEME["card"], fg=THEME["text"],
                     width=18, anchor="w").pack(side=tk.LEFT, pady=6)

            lbl = tk.Label(row, text=status,
                           font=self.fnt_lbl,
                           bg=THEME["card"], fg=color)
            lbl.pack(side=tk.RIGHT, padx=10)
            self.system_labels[name] = lbl
            self.system_labels[f"_{name}_bar"] = row.winfo_children()[0]

    # ── Controls ───────────────────────────────────────────────────────────
    def _create_controls_section(self, parent):
        self._section_header(parent, "MISSION CONTROLS", THEME["success"])

        frame = tk.Frame(parent, bg=THEME["panel"])
        frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.btn_connect = GlowButton(
            frame, "CONNECT & INITIALISE", THEME["success"],
            self.start_system, icon="▶")
        self.btn_connect.pack(fill=tk.X, pady=3)

        self.btn_arm = GlowButton(
            frame, "ARM VEHICLE", THEME["text_dim"],
            self.toggle_arm, icon="▲", disabled=True)
        self.btn_arm.pack(fill=tk.X, pady=3)

        SeparatorLine(frame, label=" OPERATIONS").pack(
            fill=tk.X, pady=(6, 2))

        self.btn_deploy = GlowButton(
            frame, "DEPLOY", THEME["text_dim"],
            self.deploy_mission, icon="⬇", disabled=True)
        self.btn_deploy.pack(fill=tk.X, pady=3)

        self.btn_retrieve = GlowButton(
            frame, "RETRIEVE", THEME["text_dim"],
            self.retrieve_mission, icon="⬆", disabled=True)
        self.btn_retrieve.pack(fill=tk.X, pady=3)

        SeparatorLine(frame, label=" SAFETY").pack(
            fill=tk.X, pady=(6, 2))

        GlowButton(frame, "EMERGENCY STOP", THEME["danger"],
                   self.close_app, icon="◼").pack(fill=tk.X, pady=3)

    # =========================================================================
    #  THRUSTER PANEL
    # =========================================================================
    def _create_thruster_panel(self, parent):
        """Full-width thruster visualisation panel."""
        self.thruster_panel = ThrusterPanel(
            parent,
            labels=THRUSTER_LABELS,
            roles=THRUSTER_ROLES,
        )
        self.thruster_panel.pack(fill=tk.X, pady=(10, 0))

    # =========================================================================
    #  MISSION LOG
    # =========================================================================
    def _create_log_panel(self, parent):
        wrapper = tk.Frame(parent, bg=THEME["panel"])
        wrapper.pack(fill=tk.X, pady=(6, 0))

        title_bar = tk.Frame(wrapper, bg=THEME["panel"], height=22)
        title_bar.pack(fill=tk.X)
        title_bar.pack_propagate(False)

        tk.Frame(title_bar, bg=THEME["success"], width=3).pack(
            side=tk.LEFT, fill=tk.Y)
        tk.Label(title_bar, text="  MISSION LOG",
                 font=self.fnt_sub,
                 bg=THEME["panel"], fg=THEME["success"]).pack(
                     side=tk.LEFT, pady=2)

        self.log_box = scrolledtext.ScrolledText(
            wrapper, font=self.fnt_log,
            bg=THEME["log_bg"], fg=THEME["log_text"],
            insertbackground=THEME["log_text"],
            selectbackground=THEME["success_dim"],
            height=5, bd=0, relief=tk.FLAT)
        self.log_box.pack(fill=tk.X, padx=1, pady=(1, 0))
        self.log_box.config(state=tk.DISABLED)

    # =========================================================================
    #  UTILITIES
    # =========================================================================
    def _section_header(self, parent, title, color):
        bar = tk.Frame(parent, bg=THEME["panel"])
        bar.pack(fill=tk.X, padx=10, pady=(12, 4))
        tk.Frame(bar, bg=color, width=3, height=16).pack(side=tk.LEFT)
        tk.Label(bar, text=f"  {title}",
                 font=self.fnt_sub,
                 bg=THEME["panel"], fg=color).pack(side=tk.LEFT)

    def _tick_clock(self):
        now = datetime.utcnow().strftime("%H:%M:%S")
        if "CLOCK" in self.telemetry_labels:
            self.telemetry_labels["CLOCK"].config(text=now)
        self.root.after(1000, self._tick_clock)

    def _start_status_blink(self):
        self._blink_state = not self._blink_state
        if not self.telemetry_backend.running:
            col = (THEME["danger"] if self._blink_state
                   else THEME["danger_dim"])
            self.status_dot.config(fg=col)
        self.root.after(BLINK_INTERVAL_MS, self._start_status_blink)

    def _start_thruster_animation(self):
        """Drives the smooth bar interpolation at THRUSTER_REFRESH_MS."""
        self.thruster_panel.step_animation()
        self.root.after(THRUSTER_REFRESH_MS, self._start_thruster_animation)

    # =========================================================================
    #  LOGGING
    # =========================================================================
    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        entry = f"[{timestamp}]  {message}\n"
        self.log_box.config(state=tk.NORMAL)
        self.log_box.insert(tk.END, entry)
        self.log_box.see(tk.END)
        self.log_box.config(state=tk.DISABLED)

    # =========================================================================
    #  TELEMETRY CALLBACK  (called from TelemetryHandler thread)
    # =========================================================================
    def update_telemetry_display(self, key: str, value: str,
                                 color_hex: str = None):
        color = color_hex or THEME["text"]

        def _apply():
            if key in self.telemetry_cards:
                self.telemetry_cards[key].update(value, color_hex)

            hud_map = {
                "DEPTH":   "HUD_DEPTH",
                "HEADING": "HUD_HDG",
                "ROLL":    "HUD_ROLL",
                "PITCH":   "HUD_PCH",
                "BATTERY": "HUD_BAT",
                "CURRENT": "HUD_CUR",
            }
            if key in hud_map and hud_map[key] in self.telemetry_labels:
                self.telemetry_labels[hud_map[key]].config(text=value)

            if key in self.telemetry_labels:
                self.telemetry_labels[key].config(text=value, fg=color)

            # ── Thruster values fed through telemetry ──────────────────
            # TelemetryHandler should call update_telemetry_display with
            # key="THRUSTERS" and value = list of 6 floats (–1..+1).
            # e.g.  update_telemetry_display("THRUSTERS", [0.5, -0.3, ...])
            if key == "THRUSTERS" and isinstance(value, list):
                self.thruster_panel.update_values(value)

        self.root.after(0, _apply)

    # =========================================================================
    #  SYSTEM START
    # =========================================================================
    def start_system(self):
        self.log("Initialising mission systems…")
        self.log("  ▶ Starting video backend…")
        self.log("  ▶ Starting telemetry link…")

        self.video_backend.start()
        self.telemetry_backend.start()
        self._update_video_loop()

        self.telemetry_labels["STATUS"].config(
            text="ONLINE", fg=THEME["success"])
        self.telemetry_labels["LINK"].config(
            text="ACTIVE", fg=THEME["success"])
        self.status_dot.config(fg=THEME["success"])
        self.cam_status_lbl.config(text="● LIVE", fg=THEME["success"])

        self._set_system("Video Feed",     "ACTIVE",  THEME["success"])
        self._set_system("Telemetry Link", "ACTIVE",  THEME["success"])
        self._set_system("Battery",        "MONITOR", THEME["warning"])

        self.btn_connect.set_disabled(True)
        self.btn_connect.update_label("SYSTEM ACTIVE")
        self.btn_arm.set_disabled(False)
        self.btn_arm.update_label("ARM VEHICLE", THEME["warning"])

        self.log("Mission systems online. Ready for operations.")

    # =========================================================================
    #  ARM / DISARM
    # =========================================================================
    def toggle_arm(self):
        if not self.telemetry_backend.running:
            self.log("⚠  ACTION DENIED — system not connected.")
            return

        if self.armed_state:
            self.telemetry_backend.arm_disarm(False)
            self.armed_state = False

            self.btn_arm.update_label("ARM VEHICLE", THEME["warning"])
            self.btn_deploy.set_disabled(True)
            self.btn_deploy.update_label("DEPLOY", THEME["text_dim"])
            self.btn_retrieve.set_disabled(True)
            self.btn_retrieve.update_label("RETRIEVE", THEME["text_dim"])

            self._set_system("Motor Control", "DISARMED", THEME["warning"])
            self.thruster_panel.set_armed(False)
            self.log("Vehicle DISARMED — all thrusters offline.")
        else:
            self.telemetry_backend.arm_disarm(True)
            self.armed_state = True

            self.btn_arm.update_label("DISARM VEHICLE", THEME["danger"])
            self.btn_deploy.set_disabled(False)
            self.btn_deploy.update_label("DEPLOY", THEME["cyan"])
            self.btn_retrieve.set_disabled(False)
            self.btn_retrieve.update_label("RETRIEVE", THEME["cyan"])

            self._set_system("Motor Control", "ARMED", THEME["success"])
            self.thruster_panel.set_armed(True)
            self.log("Vehicle ARMED — thrusters active. Ready for deployment.")

    # =========================================================================
    #  DEPLOY / RETRIEVE
    # =========================================================================
    def deploy_mission(self):
        if not self.armed_state:
            self.log("⚠  DEPLOYMENT DENIED — arm vehicle first.")
            return
        self.log("Initiating deployment sequence…")
        self.log("  ⬇ Descending to operational depth.")
        self.btn_deploy.set_disabled(True)
        self.btn_deploy.update_label("DEPLOYING…", THEME["text_dim"])

    def retrieve_mission(self):
        if not self.telemetry_backend.running:
            self.log("⚠  RETRIEVAL DENIED — system not connected.")
            return
        self.log("Initiating retrieval sequence…")
        self.log("  ⬆ Ascending to surface.")
        self.btn_deploy.set_disabled(False)
        self.btn_deploy.update_label("DEPLOY", THEME["cyan"])

    # =========================================================================
    #  VIDEO LOOP
    # =========================================================================
    def _update_video_loop(self):
        if not self.video_backend.running:
            return
        frame = self.video_backend.latest_frame
        if frame is not None:
            w = self.video_label.winfo_width()
            h = self.video_label.winfo_height()
            if w > 1 and h > 1:
                frame = cv2.resize(frame, (w, h),
                                   interpolation=cv2.INTER_LINEAR)
            img    = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            img_tk = ImageTk.PhotoImage(image=img)
            self.video_label.configure(image=img_tk, text="")
            self._current_frame = img_tk
        self.root.after(VIDEO_REFRESH_MS, self._update_video_loop)

    # =========================================================================
    #  HELPERS
    # =========================================================================
    def _set_system(self, name: str, status: str, color: str):
        if name in self.system_labels:
            self.system_labels[name].config(text=status, fg=color)
        bar_key = f"_{name}_bar"
        if bar_key in self.system_labels:
            self.system_labels[bar_key].config(bg=color)

    # =========================================================================
    #  SHUTDOWN
    # =========================================================================
    def close_app(self):
        self.log("◼  EMERGENCY SHUTDOWN initiated.")
        self.log("  Disarming vehicle…")
        self.log("  Terminating all subsystems…")
        try:
            if self.armed_state:
                self.telemetry_backend.arm_disarm(False)
            self.video_backend.stop()
            self.telemetry_backend.stop()
        except Exception as exc:
            self.log(f"  Warning during shutdown: {exc}")
        self.root.after(SHUTDOWN_DELAY_MS, self._finalize_shutdown)

    def _finalize_shutdown(self):
        self.root.destroy()


# =============================================================================
#  ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app  = RobotApp(root)
    root.mainloop()