# Central configuration for BlueROV2 Surface Vessel
PI_IP = "192.168.2.2"
LAPTOP_IP = "192.168.2.1"
PI_USERNAME, PI_PASSWORD = "pi", "raspberry"

MAV_PORT = 14551
VIDEO_PORT = 5000
SENSOR_PORT = 14553                    # NEW — dedicated sensor UDP port
FRAME_WIDTH, FRAME_HEIGHT = 640, 480
JPEG_QUALITY, TARGET_FPS = 50, 25
SOURCE_SYSTEM = 255

MAX_SPEED_SURFACE = 700
MAX_SPEED_UNDERWATER = 500
MAX_SPEED_BENCH = 100

THRUSTER_COUNT = 4
THRUSTER_LABELS = ["T1", "T2", "T3", "T4"]
THRUSTER_ROLES = ["FWD-L", "FWD-R", "VRT-L", "VRT-R"]

YOLO_MODEL = "yolov8n.pt"
YOLO_CONFIDENCE = 0.45
YOLO_ENABLED = True

GUI_POLL_MS = 16
LOG_QUEUE_MAXLEN = 500

# ── Gamepad Configuration ──
GAMEPAD_ENABLED = True
GAMEPAD_POLL_MS = 50                   # 20Hz polling
GAMEPAD_DEADZONE = 0.12                # ignore stick below 12%
GAMEPAD_TRIGGER_DEADZONE = 0.05

# Xbox 360 axis indices (verify with gamepad_test.py)
GAMEPAD_AXIS_LEFT_X = 0
GAMEPAD_AXIS_LEFT_Y = 1                # inverted: up = negative in pygame
GAMEPAD_AXIS_RIGHT_X = 3
GAMEPAD_AXIS_RIGHT_Y = 4
GAMEPAD_AXIS_LT = 2                    # left trigger
GAMEPAD_AXIS_RT = 5                    # right trigger (verify these!)

# Xbox 360 button indices (verify with gamepad_test.py)
GAMEPAD_BTN_A = 0
GAMEPAD_BTN_B = 1
GAMEPAD_BTN_X = 2
GAMEPAD_BTN_Y = 3
GAMEPAD_BTN_LB = 4
GAMEPAD_BTN_RB = 5
GAMEPAD_BTN_BACK = 6
GAMEPAD_BTN_START = 7
GAMEPAD_HAT_INDEX = 0

# Speed profiles cycleable via LB/RB
GAMEPAD_SPEED_PROFILES = ["bench", "crawl", "pool", "underwater", "surface"]