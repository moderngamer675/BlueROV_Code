import tkinter as tk
from tkinter import scrolledtext, font, ttk
from PIL import Image, ImageTk
from datetime import datetime
from RobotBackend import RobotLogic, TARGET_W, TARGET_H

from motor_controller import MotionController, KEY_TO_DIRECTION
from rov_config import (
    GUI_POLL_MS, THRUSTER_COUNT, THRUSTER_LABELS, THRUSTER_ROLES,
    GAMEPAD_ENABLED, MOTOR_A_KEY, MOTOR_B_KEY, MOTOR_ALL_OFF_KEY,
    AUTO_DEFAULT_SPEED,
)
from shared_state import SharedState, Command
from RobotBackend import RobotLogic
from RobotTelemetry import TelemetryHandler, SensorListenerThread, MotorCommandThread
from autonomous_controller import AutonomousController, AutonomousMode, AUTO_MODE_LABELS

try:
    from gamepad_controller import GamepadThread, PYGAME_AVAILABLE
except ImportError:
    PYGAME_AVAILABLE = False
    GamepadThread = None

THEME = {
    "bg":            "#1E1E24",
    "panel":         "#25252D",
    "card":          "#2D2D36",
    "card_hover":    "#3E3E4A",
    "border":        "#3F3F4A",
    "border_bright": "#00A8FF",
    "text":          "#E0E0E0",
    "text_dim":      "#8A8A93",
    "text_bright":   "#FFFFFF",
    "accent":        "#00A8FF",
    "accent_dim":    "#00538C",
    "success":       "#00E676",
    "success_dim":   "#2E7D32",
    "danger":        "#FF3366",
    "danger_dim":    "#C62828",
    "warning":       "#FFB300",
    "cyan":          "#29B6F6",
    "purple":        "#AB47BC",
    "log_bg":        "#121215",
    "log_text":      "#BDBDBD",
    "auto_active":   "#00E676",
    "auto_inactive": "#8A8A93",
}

CAM_W = 1280
CAM_H = 720
BLINK_INTERVAL_MS   = 800
THRUSTER_REFRESH_MS = 50
TELEMETRY_POLL_MS   = 200
RIGHT_PANEL_W       = 420
HUD_MAP = {
    "HEADING": "HUD_HDG", "ROLL": "HUD_ROLL", "PITCH": "HUD_PCH",
    "BATTERY": "HUD_BAT", "CURRENT": "HUD_CUR",
}
MOVEMENT_KEYS = tuple(KEY_TO_DIRECTION.keys())


def make_label(parent, text, size=8, bold=True, color=None, **kw):
    return tk.Label(
        parent, text=text,
        font=("Segoe UI", size, "bold" if bold else "normal"),
        bg=parent["bg"], fg=color or THEME["text_dim"], **kw
    )


def make_bar(parent, color, side=tk.LEFT, width=3):
    bar = tk.Frame(parent, bg=color, width=width)
    bar.pack(side=side, fill=tk.Y)
    return bar


def lerp_hex(c1, c2, t):
    c1 = [int(c1[i:i+2], 16) for i in (1, 3, 5)]
    c2 = [int(c2[i:i+2], 16) for i in (1, 3, 5)]
    return (f"#{int(c1[0]+(c2[0]-c1[0])*t):02x}"
            f"{int(c1[1]+(c2[1]-c1[1])*t):02x}"
            f"{int(c1[2]+(c2[2]-c1[2])*t):02x}")


def gradient_color(v, stops):
    v = max(0.0, min(1.0, v))
    if v <= 0: return stops[0]
    if v >= 1: return stops[-1]
    lo = int(v * (len(stops) - 1))
    return lerp_hex(stops[lo], stops[min(lo+1, len(stops)-1)], (v*(len(stops)-1))-lo)


class GlowButton(tk.Frame):
    def __init__(self, parent, text, color, command, icon="", disabled=False, **kw):
        super().__init__(parent, bg=THEME["panel"], cursor="hand2", **kw)
        self._color    = color
        self._command  = command
        self._disabled = disabled

        self._bar  = tk.Frame(self, bg=self._active_color, width=4)
        self._bar.pack(side=tk.LEFT, fill=tk.Y)
        self._body = tk.Frame(self, bg=THEME["card"])
        self._body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        row = tk.Frame(self._body, bg=THEME["card"])
        row.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        if icon:
            tk.Label(row, text=icon, font=("Segoe UI", 10),
                     bg=THEME["card"], fg=self._active_color).pack(side=tk.LEFT)

        self._lbl = tk.Label(row, text=text, font=("Segoe UI", 9, "bold"),
                             bg=THEME["card"], fg=self._active_color, padx=4)
        self._lbl.pack(side=tk.LEFT)
        self._chev = tk.Label(row, text="›", font=("Segoe UI", 12, "bold"),
                              bg=THEME["card"], fg=THEME["text_dim"])
        self._chev.pack(side=tk.RIGHT)

        for w in (self, self._body, self._bar, row, self._lbl, self._chev):
            w.bind("<Enter>",    self._on_enter)
            w.bind("<Leave>",    self._on_leave)
            w.bind("<Button-1>", self._on_click)

    @property
    def _active_color(self):
        return THEME["border"] if self._disabled else self._color

    def _on_enter(self, _=None):
        if not self._disabled:
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

    def set_disabled(self, state):
        self._disabled = state
        self._bar.config(bg=self._active_color)
        self._lbl.config(fg=self._active_color)
        self._body.config(bg=THEME["card"])

    def update_label(self, text, color=None):
        if color:
            self._color = color
        self._lbl.config(text=text, fg=self._active_color)
        self._bar.config(bg=self._active_color)


class TelemetryCard(tk.Frame):
    def __init__(self, parent, label, value, unit="", color=None, **kw):
        color = color or THEME["accent"]
        super().__init__(parent, bg=THEME["card"], relief=tk.FLAT, **kw)
        make_label(self, label, anchor="w").pack(fill=tk.X, padx=8, pady=(6, 0))
        self._val_lbl = tk.Label(self, text=value, font=("Consolas", 14, "bold"),
                                  bg=THEME["card"], fg=color, anchor="w")
        self._val_lbl.pack(fill=tk.X, padx=8)
        make_label(self, unit, bold=False, anchor="w").pack(fill=tk.X, padx=8, pady=(0, 4))
        self._accent = tk.Frame(self, bg=color, height=2)
        self._accent.pack(fill=tk.X)

    def update(self, value, color=None):
        self._val_lbl.config(text=str(value))
        if color:
            self._val_lbl.config(fg=color)
            self._accent.config(bg=color)


class ThrusterBar(tk.Frame):
    _POS = ["#004D20", "#007A30", "#00B344", "#00E676"]
    _NEG = ["#4D3300", "#997700", "#CC9900", "#FFB300"]

    def __init__(self, parent, label, role, index, **kw):
        super().__init__(parent, bg=THEME["card"], **kw)
        self._target  = 0.0
        self._current = 0.0

        badge = tk.Frame(self, bg=THEME["card"])
        badge.pack(fill=tk.X, padx=4, pady=(4, 1))
        make_label(badge, f"#{index+1}").pack(side=tk.LEFT)
        make_label(badge, label, size=8, color=THEME["accent"]).pack(side=tk.RIGHT)

        self._canvas = tk.Canvas(self, bg=THEME["log_bg"], highlightthickness=1,
                                  highlightbackground=THEME["border"], width=44, height=140)
        self._canvas.pack(padx=4, pady=2)
        make_label(self, role, size=7).pack(pady=(0, 1))
        self._pct_lbl = make_label(self, "0%", color=THEME["success"])
        self._pct_lbl.pack(pady=(0, 4))
        self._accent = tk.Frame(self, height=2, bg=THEME["border"])
        self._accent.pack(fill=tk.X)
        self._canvas.bind("<Configure>", lambda e: self._redraw())

    def set_value(self, v):
        self._target = max(-1.0, min(1.0, v))

    def step(self):
        diff = self._target - self._current
        self._current = self._target if abs(diff) < 0.005 else self._current + diff * 0.25
        self._redraw()

    def _redraw(self):
        c = self._canvas
        W, H = c.winfo_width(), c.winfo_height()
        c.delete("all")
        if W < 2 or H < 2:
            return
        mid   = H // 2
        v     = self._current
        bar_h = int(abs(v) * (mid - 4))

        for frac in (0.25, 0.5, 0.75):
            for y in (int(mid * frac), H - int(mid * frac)):
                c.create_line(0, y, W, y, fill=THEME["border"], dash=(2, 4))

        if bar_h > 0:
            colors = self._POS if v >= 0 else self._NEG
            y0, y1 = (mid - bar_h, mid) if v >= 0 else (mid, mid + bar_h)
            gy0 = y0 if v >= 0 else y1 - min(3, bar_h)
            gy1 = y0 + min(3, bar_h) if v >= 0 else y1
            c.create_rectangle(2, y0, W-2, y1, fill=gradient_color(abs(v), colors), outline="")
            c.create_rectangle(2, gy0, W-2, gy1, fill=colors[-1], outline="")

        c.create_line(0, mid, W, mid,
                      fill=THEME["accent"] if v == 0.0 else THEME["border_bright"], width=1)
        for y_off in (0, mid // 2, mid):
            for y in (y_off + 2, H - y_off - 2):
                c.create_line(W-6, y, W, y, fill=THEME["text_dim"], width=1)

        if v > 0.01:
            sign, fg = "+", THEME["success"]
        elif v < -0.01:
            sign, fg = "−", THEME["warning"]
        else:
            sign, fg = "", THEME["text_dim"]

        self._pct_lbl.config(text=f"{sign}{int(abs(v)*100)}%", fg=fg)
        self._accent.config(bg=(
            THEME["success"] if v > 0.01 else
            THEME["warning"] if v < -0.01 else THEME["border"]
        ))


class ThrusterPanel(tk.Frame):
    def __init__(self, parent, labels, roles, **kw):
        super().__init__(parent, bg=THEME["panel"], **kw)
        self._bars  = []
        self._count = len(labels)

        tb = tk.Frame(self, bg=THEME["panel"], height=24)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)
        make_bar(tb, THEME["success"])
        make_label(tb, "  THRUSTER OUTPUT", size=9, color=THEME["success"]).pack(side=tk.LEFT, pady=2)
        self._armed_badge = make_label(tb, "   ◼  DISARMED  ")
        self._armed_badge.pack(side=tk.RIGHT, padx=8)
        self._peak_lbl = make_label(tb, "PEAK: —%")
        self._peak_lbl.pack(side=tk.RIGHT, padx=12)
        make_label(tb, "WASD=Move  QE=Yaw  SPACE=Stop  🎮=Gamepad", bold=False).pack(side=tk.LEFT, padx=16)

        bar_row = tk.Frame(self, bg=THEME["panel"])
        bar_row.pack(fill=tk.X, padx=4, pady=(2, 4))

        for i, (lbl, role) in enumerate(zip(labels, roles)):
            if i > 0:
                tk.Frame(bar_row, bg=THEME["border"], width=1).pack(side=tk.LEFT, fill=tk.Y, pady=4)
            bar = ThrusterBar(bar_row, lbl, role, i)
            bar.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
            self._bars.append(bar)

    def update_values(self, values):
        vals = values if isinstance(values, list) else [
            values.get(THRUSTER_LABELS[i], 0) for i in range(self._count)
        ]
        for i, v in enumerate(vals):
            if i < len(self._bars):
                self._bars[i].set_value(float(v))
        peak = max((abs(b._target) for b in self._bars), default=0.0)
        self._peak_lbl.config(
            text=f"PEAK:{int(peak*100):3d}%",
            fg=THEME["danger"] if peak > 0.8 else THEME["warning"] if peak > 0.5 else THEME["success"]
        )

    def step_animation(self):
        for b in self._bars:
            b.step()

    def set_armed(self, armed):
        self._armed_badge.config(
            text="  ▲ ARMED  " if armed else "   ◼  DISARMED  ",
            fg=THEME["danger"] if armed else THEME["text_dim"]
        )
        for b in self._bars:
            b.set_value(0.0)


class RobotApp:
    def __init__(self, root: tk.Tk):
        self.root          = root
        self.armed_state   = False
        self._blink_state  = False
        self._current_frame = None
        self.telemetry_cards  = {}
        self.system_labels    = {}
        self.telemetry_labels = {}
        self._keys = {k: False for k in MOVEMENT_KEYS}

        self._state            = SharedState()
        self.motion            = MotionController(self._state)
        self.video_backend     = RobotLogic(self._state)
        self.telemetry_backend = TelemetryHandler(self._state)
        self.sensor_listener   = SensorListenerThread(self._state)
        self.motor_cmd_thread  = MotorCommandThread(self._state)
        self.auto_ctrl         = AutonomousController(self._state, self.motion)
        self.motion.set_auto_controller(self.auto_ctrl)

        self.gamepad_thread = None
        if GAMEPAD_ENABLED and PYGAME_AVAILABLE and GamepadThread:
            self.gamepad_thread = GamepadThread(self._state, self.motion)

        self.motion.set_speed_profile("bench")
        self._configure_window()
        self._build_ui()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

        for msg in [
            "Mission Control initialised.",
            f"Speed: {self.motion.profile.upper()} ({self.motion.speed_percent:.0f}%)",
            "Keys: WASD QE SPACE  |  1=MotA 2=MotB 3=AllOff",
            "🎮 A=Arm B=Disarm Y=Stop L3=MotA R3=MotB",
            "🎮 D-Up=Wander D-Dn=Corridor D-L=Wall← D-R=Wall→",
            "🎮 START=Auto-On  BACK=Auto-Off",
            "🎮 Controller support active" if self.gamepad_thread else "🎮 No controller",
        ]:
            self._log_to_widget(msg)

        for func, ms in [
            (self._blink_tick,        BLINK_INTERVAL_MS),
            (self._thruster_tick,     THRUSTER_REFRESH_MS),
            (self._poll_telemetry,    TELEMETRY_POLL_MS),
            (self._poll_shared_state, GUI_POLL_MS),
            (self._poll_auto_status,  200),
        ]:
            self._start_periodic(func, ms)

    def _start_periodic(self, func, ms):
        def _loop():
            func()
            self.root.after(ms, _loop)
        _loop()

    def _configure_window(self):
        self.root.title("BlueROV2 — Surface Vessel Control")
        self.root.resizable(False, False)
        self.root.configure(bg=THEME["bg"])

        win_w = CAM_W + RIGHT_PANEL_W + 50
        win_h = CAM_H + 260
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - win_w) // 2
        y  = (sh - win_h) // 2
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")

        self.fnt_header  = font.Font(family="Segoe UI", size=13, weight="bold")
        self.fnt_sub     = font.Font(family="Segoe UI", size=10, weight="bold")
        self.fnt_lbl     = font.Font(family="Segoe UI", size=8,  weight="bold")
        self.fnt_log     = font.Font(family="Consolas", size=9)
        self.fnt_mono_sm = font.Font(family="Consolas", size=9)

    def _build_ui(self):
        outer = tk.Frame(self.root, bg=THEME["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self._build_header(outer)
        body = tk.Frame(outer, bg=THEME["bg"])
        body.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self._build_left_column(body)
        self._build_right_panel(body)
        self.thruster_panel = ThrusterPanel(outer, labels=THRUSTER_LABELS, roles=THRUSTER_ROLES)
        self.thruster_panel.pack(fill=tk.X, pady=(6, 0))
        self._build_log_panel(outer)

    def _build_header(self, parent):
        hdr = tk.Frame(parent, bg=THEME["panel"], height=56)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Frame(hdr, bg=THEME["accent"], width=4).pack(side=tk.LEFT, fill=tk.Y)

        title_blk = tk.Frame(hdr, bg=THEME["panel"])
        title_blk.pack(side=tk.LEFT, fill=tk.Y, padx=(14, 0))
        tk.Label(title_blk, text="BLUEROV2  SURFACE VESSEL CONTROL",
                 font=self.fnt_header, bg=THEME["panel"], fg=THEME["accent"]).pack(anchor="w", pady=(8, 0))
        tk.Label(title_blk, text="Operations Dashboard  —  Autonomous Control System",
                 font=self.fnt_lbl, bg=THEME["panel"], fg=THEME["text_dim"]).pack(anchor="w")

        strip = tk.Frame(hdr, bg=THEME["panel"])
        strip.pack(side=tk.RIGHT, fill=tk.Y, padx=16)

        for abbr, val, key, color in [
            ("SYS",  "OFFLINE",                          "STATUS", THEME["danger"]),
            ("LINK", "NO LINK",                          "LINK",   THEME["danger"]),
            ("MODE", "—",                                "MODE",   THEME["text_dim"]),
            ("UTC",  datetime.utcnow().strftime("%H:%M:%S"), "CLOCK",  THEME["text_dim"]),
        ]:
            col = tk.Frame(strip, bg=THEME["panel"])
            col.pack(side=tk.LEFT, padx=12, pady=8)
            tk.Label(col, text=abbr, font=self.fnt_lbl, bg=THEME["panel"], fg=THEME["text_dim"]).pack()
            self.telemetry_labels[key] = tk.Label(col, text=val, font=self.fnt_sub,
                                                   bg=THEME["panel"], fg=color)
            self.telemetry_labels[key].pack()

        self._tick_clock()
        self.status_dot = tk.Label(strip, text="●", font=("Consolas", 16, "bold"),
                                    bg=THEME["panel"], fg=THEME["danger"])
        self.status_dot.pack(side=tk.LEFT, padx=(4, 0), pady=8)

    def _build_left_column(self, parent):
        left = tk.Frame(parent, bg=THEME["bg"], width=CAM_W + 4)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        left.pack_propagate(False)

        tb = tk.Frame(left, bg=THEME["panel"], height=26)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)
        tk.Frame(tb, bg=THEME["accent"], width=3).pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(tb, text=f"  PRIMARY CAMERA FEED  [{TARGET_W}×{TARGET_H}]",
                 font=self.fnt_sub, bg=THEME["panel"], fg=THEME["accent"]).pack(side=tk.LEFT, pady=3)

        self.ai_status_lbl = tk.Label(tb, text="AI: LOADING", font=self.fnt_lbl,
                                       bg=THEME["panel"], fg=THEME["warning"])
        self.ai_status_lbl.pack(side=tk.RIGHT, padx=8)
        self.cam_status_lbl = tk.Label(tb, text="● NO SIGNAL", font=self.fnt_lbl,
                                        bg=THEME["panel"], fg=THEME["danger"])
        self.cam_status_lbl.pack(side=tk.RIGHT, padx=8)

        cam_border = tk.Frame(left, bg=THEME["border"])
        cam_border.pack(fill=tk.X)

        # Fixed container — prevents layout stretch
        cam_container = tk.Frame(cam_border, bg="black", width=TARGET_W, height=TARGET_H)
        cam_container.pack(padx=1, pady=1)
        cam_container.pack_propagate(False)

        self.video_label = tk.Label(
            cam_container,
            text=" ◈   AWAITING VIDEO STREAM   ◈ \n\nConnect to begin.",
            bg="black", fg=THEME["accent_dim"],
            font=("Segoe UI", 12, "bold"),
        )
        self.video_label.pack(fill=tk.BOTH, expand=True)

        hud = tk.Frame(left, bg=THEME["panel"], height=46, width=CAM_W + 4)
        hud.pack(fill=tk.X, pady=(3, 0))
        hud.pack_propagate(False)

        items = [
            ("HEADING", "HUD_HDG"), ("ROLL", "HUD_ROLL"), ("PITCH", "HUD_PCH"),
            ("BATTERY", "HUD_BAT"), ("CURRENT", "HUD_CUR"),
        ]
        for i, (lbl_txt, key) in enumerate(items):
            cell = tk.Frame(hud, bg=THEME["panel"])
            cell.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
            tk.Label(cell, text=lbl_txt, font=self.fnt_lbl,
                     bg=THEME["panel"], fg=THEME["text_dim"]).pack(pady=(3, 0))
            self.telemetry_labels[key] = tk.Label(cell, text="—", font=self.fnt_mono_sm,
                                                   bg=THEME["panel"], fg=THEME["cyan"])
            self.telemetry_labels[key].pack()
            if i < len(items) - 1:
                tk.Frame(hud, bg=THEME["border"], width=1).pack(side=tk.LEFT, fill=tk.Y, pady=4)

    def _build_right_panel(self, parent):
        right = tk.Frame(parent, bg=THEME["panel"], width=RIGHT_PANEL_W)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right.pack_propagate(False)

        canvas = tk.Canvas(right, bg=THEME["panel"], highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(right, orient=tk.VERTICAL, command=canvas.yview)
        sf = tk.Frame(canvas, bg=THEME["panel"])

        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._section_header(sf, "VEHICLE TELEMETRY", THEME["accent"])
        grid = tk.Frame(sf, bg=THEME["panel"])
        grid.pack(fill=tk.X, padx=8, pady=(0, 4))
        grid.columnconfigure((0, 1), weight=1)

        for idx, (key, unit, col) in enumerate([
            ("BATTERY", "V",  THEME["warning"]),
            ("CURRENT", "A",  THEME["accent"]),
            ("HEADING", "°",  THEME["cyan"]),
            ("ROLL",    "°",  THEME["purple"]),
            ("PITCH",   "°",  THEME["purple"]),
        ]):
            card = TelemetryCard(grid, key, "—", unit, col)
            card.grid(row=idx//2, column=idx%2, padx=2, pady=2, sticky="nsew")
            self.telemetry_cards[key] = card

        self._section_header(sf, "PROXIMITY SENSORS", THEME["cyan"])
        sensor_grid = tk.Frame(sf, bg=THEME["panel"])
        sensor_grid.pack(fill=tk.X, padx=8, pady=(0, 4))
        sensor_grid.columnconfigure((0, 1, 2, 3), weight=1)

        for idx, (key, label) in enumerate([
            ("FRONT_DIST", "FRONT"), ("LEFT_DIST", "LEFT"),
            ("RIGHT_DIST", "RIGHT"), ("BACK_DIST",  "BACK"),
        ]):
            card = TelemetryCard(sensor_grid, label, "—", "cm", "#666666")
            card.grid(row=0, column=idx, padx=2, pady=2, sticky="nsew")
            self.telemetry_cards[key] = card

        self._section_header(sf, "DC MOTORS", THEME["warning"])
        motor_frame = tk.Frame(sf, bg=THEME["panel"])
        motor_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        motor_frame.columnconfigure((0, 1), weight=1)

        for idx, (key, label) in enumerate([
            ("MOT_A_STATUS", "MOTOR A"), ("MOT_B_STATUS", "MOTOR B"),
        ]):
            card = TelemetryCard(motor_frame, label, "OFF", "", "#666666")
            card.grid(row=0, column=idx, padx=2, pady=2, sticky="nsew")
            self.telemetry_cards[key] = card

        btn_frame = tk.Frame(sf, bg=THEME["panel"])
        btn_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        btn_frame.columnconfigure((0, 1, 2), weight=1)

        self.btn_motor_a = GlowButton(btn_frame, "MOTOR A  [1]", THEME["warning"],
                                       lambda: self.motion.toggle_motor_a(), icon="⚙ ")
        self.btn_motor_a.grid(row=0, column=0, padx=2, pady=2, sticky="nsew")

        self.btn_motor_b = GlowButton(btn_frame, "MOTOR B  [2]", THEME["warning"],
                                       lambda: self.motion.toggle_motor_b(), icon="⚙ ")
        self.btn_motor_b.grid(row=0, column=1, padx=2, pady=2, sticky="nsew")

        self.btn_motor_all_off = GlowButton(btn_frame, "ALL OFF  [3]", THEME["danger"],
                                             lambda: self.motion.all_motors_off(), icon="◼ ")
        self.btn_motor_all_off.grid(row=0, column=2, padx=2, pady=2, sticky="nsew")

        self._section_header(sf, "AUTONOMOUS MODES", THEME["auto_active"])
        auto_frame = tk.Frame(sf, bg=THEME["panel"])
        auto_frame.pack(fill=tk.X, padx=8, pady=(0, 4))

        status_card = tk.Frame(auto_frame, bg=THEME["card"])
        status_card.pack(fill=tk.X, pady=(0, 4))
        self._auto_side_bar = tk.Frame(status_card, bg=THEME["auto_inactive"], width=4)
        self._auto_side_bar.pack(side=tk.LEFT, fill=tk.Y)

        inner = tk.Frame(status_card, bg=THEME["card"])
        inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=6)
        top_row = tk.Frame(inner, bg=THEME["card"])
        top_row.pack(fill=tk.X)
        tk.Label(top_row, text="ACTIVE MODE", font=self.fnt_lbl,
                 bg=THEME["card"], fg=THEME["text_dim"]).pack(side=tk.LEFT)
        self._auto_indicator = tk.Label(top_row, text="● OFF", font=self.fnt_lbl,
                                         bg=THEME["card"], fg=THEME["auto_inactive"])
        self._auto_indicator.pack(side=tk.RIGHT)
        self._auto_mode_lbl = tk.Label(inner, text="MANUAL CONTROL",
                                        font=("Consolas", 12, "bold"),
                                        bg=THEME["card"], fg=THEME["text_dim"])
        self._auto_mode_lbl.pack(anchor="w")
        self._auto_state_lbl = tk.Label(inner, text="—", font=self.fnt_lbl,
                                         bg=THEME["card"], fg=THEME["text_dim"])
        self._auto_state_lbl.pack(anchor="w")
        self._auto_warn_lbl = tk.Label(inner, text="", font=self.fnt_lbl,
                                        bg=THEME["card"], fg=THEME["warning"])
        self._auto_warn_lbl.pack(anchor="w")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("ROV.TCombobox",
                         fieldbackground=THEME["card"], background=THEME["card"],
                         foreground=THEME["text_bright"], selectbackground=THEME["accent_dim"],
                         selectforeground=THEME["text_bright"], bordercolor=THEME["border"],
                         arrowcolor=THEME["accent"])
        style.map("ROV.TCombobox",
                  fieldbackground=[("readonly", THEME["card"])],
                  foreground=[("readonly", THEME["text_bright"])])

        selector_row = tk.Frame(auto_frame, bg=THEME["panel"])
        selector_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(selector_row, text="SELECT MODE", font=self.fnt_lbl,
                 bg=THEME["panel"], fg=THEME["text_dim"]).pack(side=tk.LEFT, padx=(0, 8))
        self._mode_var   = tk.StringVar(value="OFF")
        self._mode_combo = ttk.Combobox(selector_row, textvariable=self._mode_var,
                                         values=AUTO_MODE_LABELS, state="readonly",
                                         style="ROV.TCombobox", width=16,
                                         font=("Segoe UI", 9, "bold"))
        self._mode_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._mode_combo.bind("<<ComboboxSelected>>", self._on_mode_selected)

        speed_row = tk.Frame(auto_frame, bg=THEME["panel"])
        speed_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(speed_row, text="AUTO SPEED", font=self.fnt_lbl,
                 bg=THEME["panel"], fg=THEME["text_dim"]).pack(side=tk.LEFT, padx=(0, 8))
        self._auto_speed_var = tk.StringVar(value=AUTO_DEFAULT_SPEED.upper())
        self._speed_combo    = ttk.Combobox(speed_row, textvariable=self._auto_speed_var,
                                             values=["BENCH","CRAWL","POOL","UNDERWATER","SURFACE"],
                                             state="readonly", style="ROV.TCombobox", width=16,
                                             font=("Segoe UI", 9, "bold"))
        self._speed_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._speed_combo.bind("<<ComboboxSelected>>", self._on_auto_speed_selected)

        engage_row = tk.Frame(auto_frame, bg=THEME["panel"])
        engage_row.pack(fill=tk.X, pady=(0, 4))
        engage_row.columnconfigure((0, 1), weight=1)
        self.btn_auto_engage = GlowButton(engage_row, "ENGAGE AUTO", THEME["auto_active"],
                                           self._engage_auto, icon="▶ ", disabled=True)
        self.btn_auto_engage.grid(row=0, column=0, padx=(0, 2), pady=2, sticky="nsew")
        self.btn_auto_disengage = GlowButton(engage_row, "DISENGAGE", THEME["danger"],
                                              self._disengage_auto, icon="◼ ", disabled=True)
        self.btn_auto_disengage.grid(row=0, column=1, padx=(2, 0), pady=2, sticky="nsew")

        dpad_ref = tk.Frame(auto_frame, bg=THEME["card"])
        dpad_ref.pack(fill=tk.X, pady=(0, 4))
        tk.Label(dpad_ref,
                 text=(" 🎮 D-Up=Wander    D-Dn=Corridor\n"
                       " 🎮 D-L=Wall←      D-R=Wall→\n"
                       " 🎮 START=Engage   BACK=Disengage\n"
                       " ESC=Disengage Auto"),
                 font=("Consolas", 8), bg=THEME["card"], fg=THEME["text_dim"],
                 justify="left", anchor="w").pack(fill=tk.X, padx=8, pady=6)

        self._section_header(sf, "SYSTEMS STATUS", THEME["warning"])
        frame = tk.Frame(sf, bg=THEME["panel"])
        frame.pack(fill=tk.X, padx=8, pady=(0, 4))

        for name, status, color in [
            ("Video Feed",     "NO SIGNAL",  THEME["danger"]),
            ("Telemetry Link", "OFFLINE",    THEME["danger"]),
            ("Motor Control",  "DISARMED",   THEME["warning"]),
            ("Battery",        "UNKNOWN",    THEME["text_dim"]),
            ("AI Detection",   "LOADING",    THEME["warning"]),
            ("Controller",     "NO GAMEPAD", THEME["text_dim"]),
            ("Sensors",        "OFFLINE",    THEME["text_dim"]),
            ("DC Motors",      "OFFLINE",    THEME["text_dim"]),
            ("Autonomous",     "OFF",        THEME["text_dim"]),
        ]:
            row = tk.Frame(frame, bg=THEME["card"])
            row.pack(fill=tk.X, pady=1)
            bar = tk.Frame(row, bg=color, width=3)
            bar.pack(side=tk.LEFT, fill=tk.Y)
            tk.Label(row, text=f"  {name}", font=self.fnt_lbl, bg=THEME["card"],
                     fg=THEME["text"], width=16, anchor="w").pack(side=tk.LEFT, pady=5)
            lbl = tk.Label(row, text=status, font=self.fnt_lbl, bg=THEME["card"], fg=color)
            lbl.pack(side=tk.RIGHT, padx=8)
            self.system_labels[name]           = lbl
            self.system_labels[f"_{name}_bar"] = bar

        self._section_header(sf, "MISSION CONTROLS", THEME["success"])
        ctrl = tk.Frame(sf, bg=THEME["panel"])
        ctrl.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.btn_connect = GlowButton(ctrl, "CONNECT & INITIALISE", THEME["success"],
                                       self.start_system, icon=" ▶ ")
        self.btn_connect.pack(fill=tk.X, pady=2)
        self.btn_arm = GlowButton(ctrl, "ARM VEHICLE", THEME["text_dim"],
                                   self.toggle_arm, icon="▲", disabled=True)
        self.btn_arm.pack(fill=tk.X, pady=2)

        tk.Frame(ctrl, bg=THEME["border"], height=1).pack(fill=tk.X, pady=4)

        self.btn_deploy = GlowButton(ctrl, "DEPLOY", THEME["text_dim"],
                                      self.deploy_mission, icon=" ⬇ ", disabled=True)
        self.btn_deploy.pack(fill=tk.X, pady=2)
        self.btn_retrieve = GlowButton(ctrl, "RETRIEVE", THEME["text_dim"],
                                        self.retrieve_mission, icon=" ⬆ ", disabled=True)
        self.btn_retrieve.pack(fill=tk.X, pady=2)

        tk.Frame(ctrl, bg=THEME["border"], height=1).pack(fill=tk.X, pady=4)

        GlowButton(ctrl, "EMERGENCY STOP", THEME["danger"],
                   self.emergency_stop, icon=" ◼ ").pack(fill=tk.X, pady=2)
        GlowButton(ctrl, "QUIT", THEME["text_dim"],
                   self.close_app, icon=" ✕ ").pack(fill=tk.X, pady=2)

        self._section_header(sf, "CONTROLLER MAP", THEME["text_dim"])
        ref = tk.Frame(sf, bg=THEME["card"])
        ref.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Label(ref,
                 text=(" L-Stick = Move      R-Stick = Yaw\n"
                       " A = Arm   B = Disarm   Y = E-Stop\n"
                       " X = Cycle Speed    LB/RB = Speed ▼▲\n"
                       " L3 = Motor A       R3 = Motor B\n"
                       " 1 = Motor A   2 = Motor B   3 = All Off\n"
                       " D-Up=Wander   D-Dn=Corridor\n"
                       " D-L=Wall←     D-R=Wall→\n"
                       " START=Auto-On     BACK=Auto-Off\n"
                       " ESC=Disengage Auto"),
                 font=("Consolas", 8), bg=THEME["card"], fg=THEME["text_dim"],
                 justify="left", anchor="w").pack(fill=tk.X, padx=8, pady=6)

    def _section_header(self, parent, title, color):
        bar = tk.Frame(parent, bg=THEME["panel"])
        bar.pack(fill=tk.X, padx=8, pady=(10, 3))
        tk.Frame(bar, bg=color, width=3, height=14).pack(side=tk.LEFT)
        tk.Label(bar, text=f"  {title}", font=self.fnt_sub,
                 bg=THEME["panel"], fg=color).pack(side=tk.LEFT)

    def _build_log_panel(self, parent):
        wrapper = tk.Frame(parent, bg=THEME["panel"])
        wrapper.pack(fill=tk.X, pady=(4, 0))
        tb = tk.Frame(wrapper, bg=THEME["panel"], height=22)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)
        make_bar(tb, THEME["success"])
        tk.Label(tb, text="  MISSION LOG", font=self.fnt_sub,
                 bg=THEME["panel"], fg=THEME["success"]).pack(side=tk.LEFT, pady=1)
        tk.Button(tb, text="CLEAR", font=self.fnt_lbl, bg=THEME["panel"],
                  fg=THEME["text_dim"], bd=0, cursor="hand2",
                  command=self._clear_log).pack(side=tk.RIGHT, padx=8)
        self.log_box = scrolledtext.ScrolledText(
            wrapper, font=self.fnt_log, bg=THEME["log_bg"], fg=THEME["log_text"],
            insertbackground=THEME["log_text"], selectbackground=THEME["success_dim"],
            height=5, bd=0, relief=tk.FLAT
        )
        self.log_box.pack(fill=tk.X, padx=1, pady=(1, 0))
        self.log_box.config(state=tk.DISABLED)

    def _bind_keys(self):
        for key in MOVEMENT_KEYS:
            for case in (key, key.upper()):
                self.root.bind(f'<KeyPress-{case}>',   lambda e, k=key: self._set_key(k, True))
                self.root.bind(f'<KeyRelease-{case}>', lambda e, k=key: self._set_key(k, False))
        self.root.bind('<space>',  lambda e: self.emergency_stop())
        self.root.bind('<Escape>', lambda e: self._disengage_auto())
        self.root.bind(f'<KeyPress-{MOTOR_A_KEY}>',       lambda e: self.motion.toggle_motor_a())
        self.root.bind(f'<KeyPress-{MOTOR_B_KEY}>',       lambda e: self.motion.toggle_motor_b())
        self.root.bind(f'<KeyPress-{MOTOR_ALL_OFF_KEY}>', lambda e: self.motion.all_motors_off())
        self._process_keys()

    def _set_key(self, key, state):
        self._keys[key] = state
        if state and self.auto_ctrl:
            self.auto_ctrl.notify_user_override()

    def _process_keys(self):
        if self.armed_state and self.telemetry_backend.running:
            self.motion.move_from_keys(self._keys)
        self.root.after(100, self._process_keys)

    def _on_mode_selected(self, _=None):
        selected = self._mode_var.get()
        self._pending_mode = AutonomousMode.OFF
        for m in AutonomousMode:
            if m.value == selected:
                self._pending_mode = m
                break
        is_real = selected != "OFF"
        self.btn_auto_engage.set_disabled(not (is_real and self.armed_state))
        self.btn_auto_engage.update_label(
            f"ENGAGE: {selected}",
            THEME["auto_active"] if is_real else THEME["text_dim"]
        )

    def _on_auto_speed_selected(self, _=None):
        self.auto_ctrl.set_speed(self._auto_speed_var.get().lower())

    def _engage_auto(self):
        if not self.armed_state:
            self._state.log("[AUTO] ⚠ Cannot engage — vehicle not armed")
            return
        mode = getattr(self, "_pending_mode", AutonomousMode.OFF)
        if mode == AutonomousMode.OFF:
            self._state.log("[AUTO] ⚠ No mode selected")
            return
        speed = self._auto_speed_var.get().lower()
        self.auto_ctrl.set_speed(speed)
        self.auto_ctrl.set_mode(mode)
        self.auto_ctrl._last_active_mode = mode
        self.btn_auto_engage.set_disabled(True)
        self.btn_auto_disengage.set_disabled(False)
        self.btn_auto_disengage.update_label("DISENGAGE", THEME["danger"])
        self._state.log(f"[AUTO] ✅ Engaged: {mode.value} @ {speed.upper()}")

    def _disengage_auto(self):
        if self.auto_ctrl:
            self.auto_ctrl.set_mode(AutonomousMode.OFF)
        self._mode_var.set("OFF")
        self.btn_auto_engage.set_disabled(not self.armed_state)
        self.btn_auto_engage.update_label("ENGAGE AUTO", THEME["auto_active"])
        self.btn_auto_disengage.set_disabled(True)
        self._state.log("[AUTO] Disengaged → MANUAL CONTROL")

    def _poll_shared_state(self):
        for update in self._state.drain_telemetry_updates():
            self._apply_telemetry_update(update.key, update.value, update.color)
        if logs := self._state.drain_logs():
            self.log_box.config(state=tk.NORMAL)
            for msg in logs:
                self.log_box.insert(tk.END,
                    f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}]  {msg}\n")
            self.log_box.see(tk.END)
            self.log_box.config(state=tk.DISABLED)
        self._poll_video_frame()

    def _poll_video_frame(self):
        if not self.video_backend.running:
            return
        frame, fps = self._state.get_video_frame()
        if frame is not None:
            # frame already resized to TARGET_W×TARGET_H in RobotBackend
            img = Image.fromarray(frame)
            self._current_frame = ImageTk.PhotoImage(image=img)
            self.video_label.configure(image=self._current_frame, text="")

    def _poll_auto_status(self):
        if not hasattr(self, "auto_ctrl"):
            return
        status = self.auto_ctrl.get_status()
        if status.active:
            self._auto_mode_lbl.config(text=status.mode, fg=THEME["auto_active"])
            self._auto_indicator.config(text="● ACTIVE", fg=THEME["auto_active"])
            self._auto_side_bar.config(bg=THEME["auto_active"])
        else:
            self._auto_mode_lbl.config(text="MANUAL CONTROL", fg=THEME["text_dim"])
            self._auto_indicator.config(text="● OFF", fg=THEME["auto_inactive"])
            self._auto_side_bar.config(bg=THEME["auto_inactive"])

        self._auto_state_lbl.config(
            text=status.state_label,
            fg=THEME["cyan"] if status.active else THEME["text_dim"]
        )
        self._auto_warn_lbl.config(text=status.warning if status.warning else "",
                                    fg=THEME["warning"])
        if status.active:
            color = THEME["warning"] if not status.sensors_ok else THEME["auto_active"]
            self._set_system("Autonomous", f"{status.mode}: {status.state_label[:12]}", color)
        else:
            self._set_system("Autonomous", "OFF", THEME["text_dim"])

        if status.active:
            self.btn_auto_engage.set_disabled(True)
            self.btn_auto_disengage.set_disabled(False)
        else:
            self.btn_auto_engage.set_disabled(
                not (self._mode_var.get() != "OFF" and self.armed_state)
            )

    def _apply_telemetry_update(self, key, value, color_hex=None):
        if key in self.telemetry_cards:
            self.telemetry_cards[key].update(value, color_hex)
        if key in HUD_MAP and HUD_MAP[key] in self.telemetry_labels:
            self.telemetry_labels[HUD_MAP[key]].config(text=str(value))
        if key in self.telemetry_labels:
            self.telemetry_labels[key].config(
                text=str(value), **({"fg": color_hex} if color_hex else {})
            )
        if key == "STATUS" and "MODE" in self.telemetry_labels:
            self.telemetry_labels["MODE"].config(text=str(value), fg=THEME["accent"])
        if key == "ARMED_STATE":
            self._sync_armed_state(str(value) == " ⚠ ARMED")
        if key == "THRUSTERS" and isinstance(value, list):
            self.thruster_panel.update_values(value)
        if key == "BATTERY":
            try:
                v = float(str(value))
                if v > 0:
                    label, color = (
                        (f"{v:.1f}V GOOD", THEME["success"])  if v > 15.5 else
                        (f"{v:.1f}V OK",   THEME["warning"])  if v > 14.5 else
                        (f"{v:.1f}V LOW",  THEME["warning"])  if v > 13.5 else
                        (f"{v:.1f}V CRIT", THEME["danger"])
                    )
                    self._set_system("Battery", label, color)
            except (ValueError, TypeError):
                pass
        if key == "GAMEPAD":
            s = str(value)
            status, color = (
                ("DISCONNECTED", THEME["danger"])  if "DISCONNECTED" in s else
                ("CONNECTED",    THEME["success"]) if "CONNECTED"    in s else
                ("IDLE",         THEME["text_dim"])if "IDLE"         in s else
                ("ACTIVE",       THEME["success"])
            )
            self._set_system("Controller", status, color)
        if key in ("FRONT_DIST", "LEFT_DIST", "RIGHT_DIST", "BACK_DIST") and str(value) != "—":
            self._set_system("Sensors", "ACTIVE", THEME["success"])
        if key in ("MOT_A_STATUS", "MOT_B_STATUS"):
            self._update_dc_motor_system_status()

    def _update_dc_motor_system_status(self):
        states = self._state.get_motor_states()
        a_on, b_on = states.get("mot_a", False), states.get("mot_b", False)
        if a_on and b_on:
            self._set_system("DC Motors", "A:ON  B:ON",  THEME["success"])
        elif a_on:
            self._set_system("DC Motors", "A:ON  B:OFF", THEME["warning"])
        elif b_on:
            self._set_system("DC Motors", "A:OFF  B:ON", THEME["warning"])
        else:
            self._set_system("DC Motors", "ALL OFF",     THEME["text_dim"])

    def _sync_armed_state(self, is_armed):
        if is_armed == self.armed_state:
            return
        self.armed_state = is_armed
        self.thruster_panel.set_armed(is_armed)
        self.btn_arm.update_label(
            "DISARM VEHICLE" if is_armed else "ARM VEHICLE",
            THEME["danger"] if is_armed else THEME["warning"]
        )
        self.btn_arm.set_disabled(not is_armed and not self.telemetry_backend.running)
        self._set_ops_buttons(is_armed)
        self._set_system("Motor Control",
                          "ARMED"    if is_armed else "DISARMED",
                          THEME["success"] if is_armed else THEME["warning"])
        if not is_armed and self.auto_ctrl.get_mode() != AutonomousMode.OFF:
            self._disengage_auto()
            self._state.log("[AUTO] ⚠ Auto disengaged — vehicle disarmed")
        self.btn_auto_engage.set_disabled(
            not (self._mode_var.get() != "OFF" and is_armed)
        )

    def _set_ops_buttons(self, enabled):
        for btn, label in [(self.btn_deploy, "DEPLOY"), (self.btn_retrieve, "RETRIEVE")]:
            btn.set_disabled(not enabled)
            btn.update_label(label, THEME["cyan"] if enabled else THEME["text_dim"])

    def _blink_tick(self):
        self._blink_state = not self._blink_state
        self.status_dot.config(fg=(
            THEME["success"] if self.telemetry_backend.running else
            THEME["danger"]  if self._blink_state else THEME["danger_dim"]
        ))

    def _thruster_tick(self):
        self.thruster_panel.step_animation()

    def _poll_telemetry(self):
        if not self.video_backend.running:
            return
        frame, fps = self._state.get_video_frame()
        if frame is not None:
            self.cam_status_lbl.config(text=f"● LIVE  {fps:.0f}fps", fg=THEME["success"])
            self._set_system("Video Feed", f"LIVE {fps:.0f}fps", THEME["success"])
        else:
            self.cam_status_lbl.config(text="● WAITING…", fg=THEME["warning"])

        yolo_loaded, yolo_enabled = self._state.get_video_ai_status()
        active = yolo_enabled and yolo_loaded
        self.ai_status_lbl.config(
            text="AI: ACTIVE" if active else "AI: OFF",
            fg=THEME["success"] if active else THEME["text_dim"]
        )
        self._set_system("AI Detection",
                          "ACTIVE"   if active else "DISABLED",
                          THEME["success"] if active else THEME["text_dim"])

    def start_system(self):
        self._state.log("═" * 44)
        self._state.log("Initialising mission systems…")
        self.video_backend.start()
        self.telemetry_backend.start()
        self.sensor_listener.start()
        self.motor_cmd_thread.start()
        self.auto_ctrl.start()
        if self.gamepad_thread:
            self.gamepad_thread.start()

        self.telemetry_labels["STATUS"].config(text="ONLINE", fg=THEME["success"])
        self.telemetry_labels["LINK"].config(text="ACTIVE",   fg=THEME["success"])
        self.status_dot.config(fg=THEME["success"])

        self._set_system("Telemetry Link", "ACTIVE",       THEME["success"])
        self._set_system("Video Feed",     "CONNECTING…",  THEME["warning"])
        self._set_system("Battery",        "MONITOR",      THEME["warning"])
        self._set_system("Sensors",        "LISTENING…",   THEME["warning"])
        self._set_system("DC Motors",      "READY",        THEME["text_dim"])
        self._set_system("Autonomous",     "STANDBY",      THEME["text_dim"])
        if self.gamepad_thread:
            self._set_system("Controller", "SCANNING…",   THEME["warning"])

        self.btn_connect.set_disabled(True)
        self.btn_connect.update_label("SYSTEM ACTIVE", THEME["text_dim"])
        self.btn_arm.set_disabled(False)
        self.btn_arm.update_label("ARM VEHICLE", THEME["warning"])
        self._state.log("Systems online. Awaiting MAVLink heartbeat…")
        self._state.log("═" * 44)

    def toggle_arm(self):
        if not self.telemetry_backend.running:
            self._state.log("⚠ Not connected.")
            return
        self._state.send_command(Command(name="arm" if not self.armed_state else "disarm"))
        self._sync_armed_state(not self.armed_state)
        self._state.log(
            "Vehicle ARMED — control active." if self.armed_state else "Vehicle DISARMED."
        )

    def emergency_stop(self):
        self._state.log("⚠ EMERGENCY STOP!")
        if self.auto_ctrl:
            self.auto_ctrl.set_mode(AutonomousMode.OFF)
        self.motion.stop()
        if self.telemetry_backend.running:
            self._state.send_command(Command(name="stop_motors"))
        self.motion.all_motors_off()
        for k in self._keys:
            self._keys[k] = False
        self.thruster_panel.update_values([0.0] * THRUSTER_COUNT)
        self._mode_var.set("OFF")
        self.btn_auto_disengage.set_disabled(True)
        self.btn_auto_engage.set_disabled(not self.armed_state)

    def deploy_mission(self):
        if not self.armed_state:
            self._state.log("⚠ Arm vehicle first.")
            return
        self._state.log("Deploying…")
        self.btn_deploy.set_disabled(True)
        self.btn_deploy.update_label("DEPLOYING…", THEME["text_dim"])

    def retrieve_mission(self):
        if not self.telemetry_backend.running:
            self._state.log("⚠ Not connected.")
            return
        self._state.log("Retrieving…")
        self.btn_deploy.set_disabled(False)
        self.btn_deploy.update_label("DEPLOY", THEME["cyan"])

    def _set_system(self, name, status, color):
        if name in self.system_labels:
            self.system_labels[name].config(text=status, fg=color)
        if f"_{name}_bar" in self.system_labels:
            self.system_labels[f"_{name}_bar"].config(bg=color)

    def _tick_clock(self):
        if "CLOCK" in self.telemetry_labels:
            self.telemetry_labels["CLOCK"].config(text=datetime.utcnow().strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    def _log_to_widget(self, message):
        self.log_box.config(state=tk.NORMAL)
        self.log_box.insert(tk.END,
            f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}]  {message}\n")
        self.log_box.see(tk.END)
        self.log_box.config(state=tk.DISABLED)

    def _clear_log(self):
        self.log_box.config(state=tk.NORMAL)
        self.log_box.delete(1.0, tk.END)
        self.log_box.config(state=tk.DISABLED)

    def close_app(self):
        self._state.log("◼ SHUTDOWN initiated.")
        try:
            if self.auto_ctrl:
                self.auto_ctrl.set_mode(AutonomousMode.OFF)
                self.auto_ctrl.stop()
            if self.telemetry_backend.running:
                self._state.send_command(Command(name="stop_motors"))
            if self.armed_state:
                self._state.send_command(Command(name="disarm"))
            self.motion.all_motors_off()
            if self.gamepad_thread:
                self.gamepad_thread.stop()
            self.motor_cmd_thread.stop()
            self.sensor_listener.stop()
            self.video_backend.stop()
            self.telemetry_backend.stop()
        except Exception as e:
            self._state.log(f"Warning during shutdown: {e}")
        self.root.after(1200, self.root.destroy)


if __name__ == "__main__":
    root = tk.Tk()
    app  = RobotApp(root)
    root.mainloop()