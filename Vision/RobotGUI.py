import tkinter as tk
from tkinter import scrolledtext, font
from PIL import Image, ImageTk
import cv2

# Custom Modules
from RobotBackend import RobotLogic
from RobotTelemetry import TelemetryHandler

# --- STYLE CONFIGURATION ---
THEME = {
    "bg": "#121212",
    "panel": "#1E1E1E",
    "card": "#252525",
    "text": "#FFFFFF",
    "accent": "#007ACC",
    "success": "#28A745",
    "danger": "#DC3545",
    "log_bg": "#000000",
    "log_text": "#00FF00",
    "cyan": "#00FFFF"
}

class RobotApp:
    def __init__(self, root):
        self.root = root
        self.armed_state = False
        self.telemetry_labels = {}

        # Initialize Backends
        self.video_backend = RobotLogic(self.log)
        self.telemetry_backend = TelemetryHandler(self.update_telemetry_display, self.log)

        self._configure_window()
        self._build_ui()
        
        self.log("Mission Control Initialized.")

    def _configure_window(self):
        """Sets up the main application window properties."""
        self.root.title("BlueROV Mission Control")
        self.root.geometry("1280x850")
        self.root.configure(bg=THEME["bg"])

        # Define Global Fonts
        self.font_header = font.Font(family="Segoe UI", size=16, weight="bold")
        self.font_sub    = font.Font(family="Segoe UI", size=11, weight="bold")
        self.font_val    = font.Font(family="Consolas", size=14, weight="bold")
        self.font_lbl    = font.Font(family="Segoe UI", size=9, weight="bold")
        self.font_log    = font.Font(family="Consolas", size=9)

    def _build_ui(self):
        """Main UI Assembly."""
        self.main_container = tk.Frame(self.root, bg=THEME["bg"])
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        self._create_header()
        
        # Content Body
        self.body = tk.Frame(self.main_container, bg=THEME["bg"])
        self.body.pack(fill=tk.BOTH, expand=True)
        
        self._create_video_panel()
        self._create_sidebar()
        self._create_footer_log()

    def _create_header(self):
        header = tk.Frame(self.main_container, bg=THEME["panel"], height=60)
        header.pack(fill=tk.X, pady=(0, 10))
        header.pack_propagate(False)

        tk.Label(header, text="BlueROV MISSION CONTROL", font=self.font_header, 
                 bg=THEME["panel"], fg=THEME["accent"]).pack(side=tk.LEFT, padx=20)

        self.lbl_status = tk.Label(header, text="DISCONNECTED", font=self.font_sub, 
                                   bg=THEME["panel"], fg="#888888")
        self.lbl_status.pack(side=tk.RIGHT, padx=20)
        self.telemetry_labels["STATUS"] = self.lbl_status

    def _create_video_panel(self):
        wrapper = tk.Frame(self.body, bg=THEME["bg"])
        wrapper.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        self.video_label = tk.Label(wrapper, text="WAITING FOR VIDEO STREAM...", 
                                   bg="black", fg="#444444", font=("Segoe UI", 12))
        self.video_label.pack(fill=tk.BOTH, expand=True)

    def _create_sidebar(self):
        sidebar = tk.Frame(self.body, bg=THEME["panel"], width=320)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Section: Telemetry
        tk.Label(sidebar, text="VEHICLE TELEMETRY", font=self.font_sub, 
                 bg=THEME["panel"], fg=THEME["text"]).pack(pady=(20, 10))
        
        grid = tk.Frame(sidebar, bg=THEME["panel"])
        grid.pack(fill=tk.X, padx=10)

        self._add_card(grid, "MODE", "MANUAL", 0, 0, 2)
        self._add_card(grid, "BATTERY", "0.00 V", 1, 0)
        self._add_card(grid, "CURRENT", "0.0 A", 1, 1)
        self._add_card(grid, "DEPTH", "0.00 m", 2, 0)
        self._add_card(grid, "HEADING", "0°", 2, 1)
        self._add_card(grid, "ATTITUDE", "R: 0.0°  P: 0.0°", 3, 0, 2, THEME["cyan"])

        # Section: Controls
        tk.Frame(sidebar, bg="#333", height=1).pack(fill=tk.X, pady=30, padx=20)
        
        self.btn_connect = self._add_button(sidebar, "CONNECT SYSTEM", THEME["success"], self.start_system)
        self.btn_arm     = self._add_button(sidebar, "ARM ROBOT", "#444", self.toggle_arm)
        
        # Spacer to push the exit button toward the bottom
        tk.Frame(sidebar, bg=THEME["panel"], height=40).pack()
        
        # Now using a larger padding for the Exit button
        self._add_button(sidebar, "EXIT APPLICATION", THEME["danger"], self.close_app, large=True)

    def _add_card(self, parent, title, value, r, c, span=1, text_color=None):
        """Helper to create a telemetry data card."""
        card = tk.Frame(parent, bg=THEME["card"], highlightthickness=1, highlightbackground="#333")
        card.grid(row=r, column=c, columnspan=span, sticky="nsew", padx=4, pady=4)
        parent.grid_columnconfigure(c, weight=1)

        tk.Label(card, text=title, font=self.font_lbl, bg=THEME["card"], fg="#888888", anchor="w").pack(fill=tk.X, padx=12, pady=(8,0))
        
        # Determine color (default or override)
        fg_color = text_color if text_color else THEME["text"]
        val_lbl = tk.Label(card, text=value, font=self.font_val, bg=THEME["card"], fg=fg_color)
        val_lbl.pack(fill=tk.X, padx=12, pady=(0, 12))
        
        self.telemetry_labels[title] = val_lbl

    def _add_button(self, parent, text, color, cmd, large=False):
        """Helper to create a standard button with adjustable size."""
        # Increased ipady (internal vertical padding) for the "large" look
        padding_y = 18 if large else 10
        font_size = 11 if large else 10
        
        btn = tk.Button(parent, text=text, bg=color, fg="white", 
                        font=("Segoe UI", font_size, "bold"), 
                        relief=tk.FLAT, cursor="hand2", command=cmd)
        
        btn.pack(fill=tk.X, padx=25, pady=8, ipady=padding_y)
        return btn

    def _create_footer_log(self):
        log_frame = tk.Frame(self.main_container, bg=THEME["panel"])
        log_frame.pack(fill=tk.X, pady=(15, 0))
        
        self.log_box = scrolledtext.ScrolledText(log_frame, font=self.font_log, 
                                                bg=THEME["log_bg"], fg=THEME["log_text"], 
                                                height=7, bd=0)
        self.log_box.pack(fill=tk.X, padx=10, pady=10)

    # --- LOGIC & CALLBACKS ---

    def log(self, message):
        self.log_box.insert(tk.END, f">> {message}\n")
        self.log_box.see(tk.END)

    def update_telemetry_display(self, key, value, color_hex=None):
        if key in self.telemetry_labels:
            color = color_hex if color_hex else THEME["text"]
            self.root.after(0, lambda: self.telemetry_labels[key].config(text=value, fg=color))

    def toggle_arm(self):
        if not self.telemetry_backend.running:
            self.log("Action Failed: Connect system before arming.")
            return

        if self.armed_state:
            self.telemetry_backend.arm_disarm(False)
            self.btn_arm.config(text="ARM ROBOT", bg="#444")
            self.armed_state = False
        else:
            self.telemetry_backend.arm_disarm(True)
            self.btn_arm.config(text="DISARM ROBOT", bg=THEME["danger"])
            self.armed_state = True

    def start_system(self):
        self.log("Initializing Video and Telemetry streams...")
        self.video_backend.start()
        self.telemetry_backend.start()
        self._update_video_loop()
        self.btn_connect.config(text="CONNECTION ACTIVE", state="disabled", bg="#222")

    def _update_video_loop(self):
        """Processes and displays the latest camera frame."""
        if self.video_backend.running:
            frame = self.video_backend.latest_frame
            if frame is not None:
                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                img_tk = ImageTk.PhotoImage(image=img)
                self.video_label.configure(image=img_tk)
                self.video_label.image = img_tk 
            self.root.after(30, self._update_video_loop)

    def close_app(self):
        self.log("Shutting down...")
        self.video_backend.stop()
        self.telemetry_backend.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = RobotApp(root)
    root.mainloop()


    