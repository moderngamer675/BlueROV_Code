import tkinter as tk
from tkinter import scrolledtext, font
from PIL import Image, ImageTk
import cv2
from RobotBackend import RobotLogic
from RobotTelemetry import TelemetryHandler  # Import the new file

# --- MODERN DARK THEME PALETTE ---
COLOR_BG        = "#121212"       # Main Window Background
COLOR_PANEL     = "#1E1E1E"       # Panel/Sidebar Background
COLOR_TEXT      = "#E0E0E0"       # Primary Text
COLOR_ACCENT    = "#007ACC"       # Blue Accents
COLOR_SUCCESS   = "#28A745"       # Green (Connect)
COLOR_WARNING   = "#FFC107"       # Yellow (Disconnect)
COLOR_DANGER    = "#DC3545"       # Red (Exit)
COLOR_LOG_BG    = "#000000"       # Terminal Background
COLOR_LOG_TEXT  = "#00FF00"       # Terminal Text
COLOR_CARD_BG   = "#252525"       # Background for data cards

class RobotApp:
    def __init__(self, root):
        self.root = root
        self.setup_window()
        
        # 1. Initialize Video Backend
        self.video_backend = RobotLogic(self.log)
        
        # 2. Initialize Telemetry Backend
        # We pass self.update_telemetry_display so the backend can update the GUI
        self.telemetry_backend = TelemetryHandler(self.update_telemetry_display, self.log)

        # Main Layout
        self.main_container = tk.Frame(self.root, bg=COLOR_BG)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Dictionary to store our data labels so we can update them later
        self.telemetry_labels = {} 

        self.create_header()
        self.create_content_area()
        self.create_footer()

        self.log("System Initialized. Ready for Mission.")

    def setup_window(self):
        self.root.title("BlueROV Command Station")
        self.root.geometry("1100x750")
        self.root.configure(bg=COLOR_BG)
        
        # Fonts
        self.font_header = font.Font(family="Segoe UI", size=16, weight="bold")
        self.font_sub = font.Font(family="Segoe UI", size=11, weight="bold")
        self.font_val = font.Font(family="Consolas", size=14, weight="bold") # Digital look
        self.font_lbl = font.Font(family="Segoe UI", size=8)
        self.font_log = font.Font(family="Consolas", size=9)

    def create_header(self):
        header = tk.Frame(self.main_container, bg=COLOR_PANEL, height=50)
        header.pack(fill=tk.X, pady=(0, 10))
        header.pack_propagate(False)

        tk.Label(header, text="BlueROV MISSION CONTROL", font=self.font_header, bg=COLOR_PANEL, fg=COLOR_ACCENT).pack(side=tk.LEFT, padx=15)
        self.lbl_status = tk.Label(header, text="STATUS: STANDBY", font=self.font_sub, bg=COLOR_PANEL, fg="#888888")
        self.lbl_status.pack(side=tk.RIGHT, padx=15)

    def create_content_area(self):
        content = tk.Frame(self.main_container, bg=COLOR_BG)
        content.pack(fill=tk.BOTH, expand=True)

        # --- LEFT: VIDEO ---
        wrapper = tk.Frame(content, bg=COLOR_BG)
        wrapper.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        border = tk.Frame(wrapper, bg=COLOR_PANEL, bd=1)
        border.pack(anchor=tk.CENTER, expand=True)
        
        self.video_label = tk.Label(border, text="NO VIDEO SIGNAL", bg="black", fg="#444444", font=("Segoe UI", 14))
        self.video_label.pack(padx=2, pady=2)

        # --- RIGHT: SIDEBAR ---
        sidebar = tk.Frame(content, bg=COLOR_PANEL, width=240) # Slightly wider for data
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # 1. Telemetry Section
        tk.Label(sidebar, text="TELEMETRY DATA", font=self.font_sub, bg=COLOR_PANEL, fg=COLOR_TEXT).pack(pady=(20, 10))
        
        # Grid Container for Data Cards
        data_grid = tk.Frame(sidebar, bg=COLOR_PANEL)
        data_grid.pack(fill=tk.X, padx=10)

        # Create Cards (Key, Initial Value, Row, Col)
        self.create_data_card(data_grid, "MODE", "STABILIZE", 0, 0, colspan=2) # Full width
        self.create_data_card(data_grid, "BATTERY", "--- V", 1, 0)
        self.create_data_card(data_grid, "DEPTH", "--- m", 1, 1)
        self.create_data_card(data_grid, "HEADING", "---°", 2, 0)
        self.create_data_card(data_grid, "ATTITUDE", "R:0 P:0", 2, 1)

        # Separator
        tk.Frame(sidebar, bg="#333", height=1).pack(fill=tk.X, pady=20, padx=10)

        # 2. Controls Section
        tk.Label(sidebar, text="OPERATIONS", font=self.font_sub, bg=COLOR_PANEL, fg=COLOR_TEXT).pack(pady=(0, 10))
        self.create_btn(sidebar, "CONNECT SYSTEM", COLOR_SUCCESS, self.start_system)
        self.create_btn(sidebar, "DISCONNECT", COLOR_WARNING, self.stop_system)
        tk.Frame(sidebar, bg=COLOR_PANEL, height=20).pack()
        self.create_btn(sidebar, "SHUTDOWN APP", COLOR_DANGER, self.close_app)

    def create_data_card(self, parent, title, value, r, c, colspan=1):
        """Creates a professional looking 'data card'."""
        card = tk.Frame(parent, bg=COLOR_CARD_BG, bd=0, highlightthickness=1, highlightbackground="#333")
        # Padding logic for grid
        card.grid(row=r, column=c, columnspan=colspan, sticky="nsew", padx=4, pady=4)
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)

        # Label (Top left of card, small)
        tk.Label(card, text=title, font=self.font_lbl, bg=COLOR_CARD_BG, fg="#888888", anchor="w").pack(fill=tk.X, padx=5, pady=(5,0))
        
        # Value (Center, large, bold)
        val_lbl = tk.Label(card, text=value, font=self.font_val, bg=COLOR_CARD_BG, fg=COLOR_TEXT)
        val_lbl.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        # Store the label widget so we can update it later
        self.telemetry_labels[title] = val_lbl

    def create_btn(self, parent, text, color, cmd):
        btn = tk.Button(parent, text=text, bg=color, fg="white", font=("Segoe UI", 10, "bold"), 
                        relief=tk.FLAT, activebackground=color, activeforeground="white", cursor="hand2", command=cmd)
        btn.pack(fill=tk.X, padx=15, pady=6, ipady=6)

    def create_footer(self):
        log_frame = tk.Frame(self.main_container, bg=COLOR_PANEL)
        log_frame.pack(fill=tk.X, pady=(10, 0))
        tk.Label(log_frame, text=" SYSTEM LOG", font=("Segoe UI", 9, "bold"), bg=COLOR_PANEL, fg="#888888", anchor="w").pack(fill=tk.X, padx=5, pady=(5,0))
        self.log_box = scrolledtext.ScrolledText(log_frame, font=self.font_log, bg=COLOR_LOG_BG, fg=COLOR_LOG_TEXT, height=8, bd=0)
        self.log_box.pack(fill=tk.X, padx=5, pady=5)

    # --- UPDATER FUNCTIONS ---
    
    def log(self, message):
        self.log_box.insert(tk.END, f">> {message}\n")
        self.log_box.see(tk.END)

    def update_telemetry_display(self, key, value, color_hex="#E0E0E0"):
        """Called by the Telemetry Thread. Updates the GUI securely."""
        if key in self.telemetry_labels:
            # We use after() to ensure thread safety with Tkinter
            self.root.after(0, lambda: self._safe_label_update(key, value, color_hex))

    def _safe_label_update(self, key, value, color):
        lbl = self.telemetry_labels[key]
        lbl.config(text=value, fg=color)

    def update_video(self):
        if self.video_backend.running:
            frame = self.video_backend.latest_frame
            if frame is not None:
                # Note: No Flip, No Resize (Native)
                img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img_tk = ImageTk.PhotoImage(image=Image.fromarray(img_rgb))
                self.video_label.configure(image=img_tk)
                self.video_label.image = img_tk 
            self.root.after(30, self.update_video)

    # --- CONTROLS ---

    def start_system(self):
        self.log("Starting System...")
        self.lbl_status.config(text="STATUS: CONNECTING...", fg=COLOR_WARNING)
        
        # Start both threads
        self.video_backend.start()
        self.telemetry_backend.start()
        
        self.update_video()
        self.lbl_status.config(text="STATUS: ONLINE", fg=COLOR_SUCCESS)

    def stop_system(self):
        self.log("Stopping System...")
        self.video_backend.stop()
        self.telemetry_backend.stop()
        self.video_label.configure(image='', text="NO VIDEO SIGNAL")
        self.lbl_status.config(text="STATUS: DISCONNECTED", fg=COLOR_DANGER)

    def close_app(self):
        self.stop_system()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = RobotApp(root)
    root.mainloop()