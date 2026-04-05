# Central configuration for BlueROV2 Surface Vessel
PI_IP = "192.168.2.2"
LAPTOP_IP = "192.168.2.1"
PI_USERNAME, PI_PASSWORD = "pi", "raspberry"

MAV_PORT = 14551
VIDEO_PORT = 5000
SENSOR_PORT = 14553                    # Sensor + motor status IN from Pi
MOTOR_CMD_PORT = 14554                 # Motor commands OUT to Pi

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
GAMEPAD_DEADZONE = 0.12               # ignore stick below 12%
GAMEPAD_TRIGGER_DEADZONE = 0.05

# Xbox 360 axis indices (verify with gamepad_test.py)
GAMEPAD_AXIS_LEFT_X = 0
GAMEPAD_AXIS_LEFT_Y = 1               # inverted: up = negative in pygame
GAMEPAD_AXIS_RIGHT_X = 3
GAMEPAD_AXIS_RIGHT_Y = 4
GAMEPAD_AXIS_LT = 2                   # left trigger
GAMEPAD_AXIS_RT = 5                   # right trigger (verify these!)

# Xbox 360 button indices (verify with gamepad_test.py)
GAMEPAD_BTN_A = 0
GAMEPAD_BTN_B = 1
GAMEPAD_BTN_X = 2
GAMEPAD_BTN_Y = 3
GAMEPAD_BTN_LB = 4
GAMEPAD_BTN_RB = 5
GAMEPAD_BTN_BACK = 6
GAMEPAD_BTN_START = 7
GAMEPAD_BTN_L3 = 8                    # Left stick click  → Motor A toggle
GAMEPAD_BTN_R3 = 9                    # Right stick click → Motor B toggle
GAMEPAD_HAT_INDEX = 0

# Speed profiles cycleable via LB/RB
GAMEPAD_SPEED_PROFILES = ["bench", "crawl", "pool", "underwater", "surface"]

# ── DC Motor Configuration ──
MOTOR_CMD_NAMES = {
    "mot_a": {"on": "MOT_A_ON", "off": "MOT_A_OFF"},
    "mot_b": {"on": "MOT_B_ON", "off": "MOT_B_OFF"},
    "mot_all": {"on": "MOT_ALL_ON", "off": "MOT_ALL_OFF"},
}
MOTOR_ON_VALUE = 1.0
MOTOR_OFF_VALUE = 0.0

# Keyboard motor keys
MOTOR_A_KEY = "1"                     # Press 1 → toggle Motor A
MOTOR_B_KEY = "2"                     # Press 2 → toggle Motor B
MOTOR_ALL_OFF_KEY = "3"               # Press 3 → kill all DC motors

# Sensor names (all four)
SENSOR_NAMES = {"dst_front", "dst_left", "dst_right", "dst_back"}
MOTOR_STATUS_NAMES = {"mot_a", "mot_b"}