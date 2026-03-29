# rov_config.py
# Central configuration for BlueROV2 Mission Control

# ── Network ───────────────────────────────────────────────
PI_IP       = "192.168.2.2"
LAPTOP_IP   = "192.168.2.1"
PI_USERNAME = "pi"
PI_PASSWORD = "raspberry"

# ── Ports ─────────────────────────────────────────────────
MAV_PORT    = 14551   # MAVLink UDP port
VIDEO_PORT  = 5000    # Camera stream UDP port

# ── Camera ────────────────────────────────────────────────
FRAME_WIDTH  = 640
FRAME_HEIGHT = 480
JPEG_QUALITY = 50
TARGET_FPS   = 25

# ── MAVLink ───────────────────────────────────────────────
SOURCE_SYSTEM = 255   # Must match SYSID_MYGCS

# ── Motor control ─────────────────────────────────────────
# MANUAL_CONTROL range = -1000 to +1000
# Safe limits for operation
MAX_SPEED_SURFACE    = 700   # 70% for surface ops
MAX_SPEED_UNDERWATER = 500   # 50% for underwater ops
MAX_SPEED_BENCH      = 100   # 10% for bench testing

# ── Thruster Configuration ────────────────────────────────
# 4-thruster vectored layout
THRUSTER_COUNT  = 4
THRUSTER_LABELS = ["T1", "T2", "T3", "T4"]
THRUSTER_ROLES  = ["FWD-L", "FWD-R", "VRT-L", "VRT-R"]

# ── YOLO ──────────────────────────────────────────────────
YOLO_MODEL       = "yolov8n.pt"   # Nano = fastest
YOLO_CONFIDENCE  = 0.45
YOLO_ENABLED     = True

# ── GUI Thread Bridge ────────────────────────────────────
GUI_POLL_MS       = 16    # ~60fps GUI refresh
LOG_QUEUE_MAXLEN  = 500   # Max buffered log lines in deque