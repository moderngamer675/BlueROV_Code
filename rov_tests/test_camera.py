# rov_tests/test_telemetry.py
# Live dashboard of all ROV sensor data
# Run with: python rov_tests/test_telemetry.py

from pymavlink import mavutil
from Vision.rov_config import MAV_PORT
import time
import os

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

# ── Connect ───────────────────────────────────────────────
print("Connecting to MAVLink...")
mav = mavutil.mavlink_connection(f'udp:0.0.0.0:{MAV_PORT}')
hb  = mav.wait_heartbeat(timeout=15)

if hb is None:
    print("No heartbeat — run test_connection.py first")
    exit(1)

print(f"Connected! System {mav.target_system}")
print("Press Ctrl+C to stop\n")
time.sleep(0.5)

# ── Telemetry store ───────────────────────────────────────
t = {
    "mode":      "—",
    "armed":     "NO",
    "battery":   "—",
    "current":   "—",
    "depth":     "—",
    "heading":   "—",
    "throttle":  "—",
    "roll":      "—",
    "pitch":     "—",
    "yaw":       "—",
    "pressure":  "—",
    "temp":      "—",
    "vibration": "—",
    "ekf":       "—",
    "servo1":    1500,
    "servo2":    1500,
    "servo3":    1500,
    "servo4":    1500,
    "servo5":    1500,
    "servo6":    1500,
    "named_vals": {},
    "msg_count":  0,
    "hz":         0.0,
    "last_hb":    time.time(),
}

last_refresh  = time.time()
last_hz_count = 0
last_hz_time  = time.time()

def pwm_bar(pwm, width=12):
    """Visual bar for PWM 1100-1900."""
    pct    = (pwm - 1100) / 800.0
    filled = int(pct * width)
    empty  = width - filled
    if pwm > 1520:
        col = "+"
    elif pwm < 1480:
        col = "-"
    else:
        col = "░"
    bar = "█" * filled + "░" * empty
    return f"{bar} {pwm}"

try:
    while True:

        # ── Send heartbeat every 1s ───────────────────────
        if time.time() - t["last_hb"] >= 1.0:
            mav.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0, 0, 0
            )
            t["last_hb"] = time.time()

        # ── Receive message ───────────────────────────────
        msg = mav.recv_match(blocking=True, timeout=0.1)
        if msg is None:
            continue

        mt = msg.get_type()
        if mt == 'BAD_DATA':
            continue

        t["msg_count"] += 1

        # ── Calculate Hz ──────────────────────────────────
        now = time.time()
        if now - last_hz_time >= 1.0:
            t["hz"]    = (t["msg_count"] - last_hz_count) / \
                          (now - last_hz_time)
            last_hz_count = t["msg_count"]
            last_hz_time  = now

        # ── Parse messages ────────────────────────────────
        if mt == 'HEARTBEAT':
            t["mode"]  = mavutil.mode_string_v10(msg)
            t["armed"] = (
                "⚠ ARMED"
                if msg.base_mode &
                   mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                else "SAFE"
            )

        elif mt == 'SYS_STATUS':
            v = msg.voltage_battery / 1000.0
            a = (msg.current_battery / 100.0
                 if msg.current_battery != -1 else 0.0)
            t["battery"] = f"{v:.2f}V"
            t["current"] = f"{a:.1f}A"

        elif mt == 'VFR_HUD':
            t["depth"]    = f"{abs(msg.alt):.3f}m"
            t["heading"]  = f"{msg.heading}°"
            t["throttle"] = f"{msg.throttle}%"

        elif mt == 'ATTITUDE':
            t["roll"]  = f"{msg.roll  * 57.2958:+.1f}°"
            t["pitch"] = f"{msg.pitch * 57.2958:+.1f}°"
            t["yaw"]   = f"{msg.yaw   * 57.2958:+.1f}°"

        elif mt == 'SCALED_PRESSURE':
            t["pressure"] = f"{msg.press_abs:.1f}hPa"
            t["temp"]     = f"{msg.temperature/100:.1f}°C"

        elif mt == 'VIBRATION':
            t["vibration"] = (
                f"X:{msg.vibration_x:.2f} "
                f"Y:{msg.vibration_y:.2f} "
                f"Z:{msg.vibration_z:.2f}"
            )

        elif mt == 'EKF_STATUS_REPORT':
            flags = msg.flags
            t["ekf"] = "OK" if flags & 0x1F == 0x1F else \
                       f"WARN (0x{flags:04X})"

        elif mt == 'SERVO_OUTPUT_RAW':
            t["servo1"] = msg.servo1_raw
            t["servo2"] = msg.servo2_raw
            t["servo3"] = msg.servo3_raw
            t["servo4"] = msg.servo4_raw
            t["servo5"] = msg.servo5_raw
            t["servo6"] = msg.servo6_raw

        elif mt == 'NAMED_VALUE_FLOAT':
            name = msg.name.strip('\x00').strip()
            t["named_vals"][name] = f"{msg.value:.3f}"

        # ── Refresh display every 0.15s ───────────────────
        if time.time() - last_refresh >= 0.15:
            clear()
            print("╔══════════════════════════════════════════╗")
            print("║      BlueROV2 Live Telemetry Dashboard   ║")
            print("║      Ctrl+C to stop                      ║")
            print("╠══════════════════════════════════════════╣")
            print(f"║  Mode    : {t['mode']:<10}  "
                  f"Armed : {t['armed']:<12}║")
            print("╠══════════════════════════════════════════╣")
            print(f"║  Battery : {t['battery']:<8}   "
                  f"Current: {t['current']:<10}  ║")
            print(f"║  Depth   : {t['depth']:<8}   "
                  f"Heading: {t['heading']:<10}  ║")
            print(f"║  Throttle: {t['throttle']:<8}   "
                  f"Pressure:{t['pressure']:<10} ║")
            print(f"║  Temp    : {t['temp']:<8}   "
                  f"EKF    : {t['ekf']:<10}  ║")
            print("╠══════════════════════════════════════════╣")
            print(f"║  Roll    : {t['roll']:<8}   "
                  f"Pitch  : {t['pitch']:<10}  ║")
            print(f"║  Yaw     : {t['yaw']:<8}   "
                  f"Vibr   : {t['vibration'][:14]:<14}║")
            print("╠══════════════════════════════════════════╣")
            print("║  THRUSTER OUTPUT (PWM)                   ║")
            print(f"║  T1: {pwm_bar(t['servo1'])}  ║")
            print(f"║  T2: {pwm_bar(t['servo2'])}  ║")
            print(f"║  T3: {pwm_bar(t['servo3'])}  ║")
            print(f"║  T4: {pwm_bar(t['servo4'])}  ║")
            print(f"║  T5: {pwm_bar(t['servo5'])}  ║")
            print(f"║  T6: {pwm_bar(t['servo6'])}  ║")

            if t["named_vals"]:
                print("╠══════════════════════════════════════════╣")
                print("║  ARDUINO SENSOR DATA                     ║")
                for k, v in list(t["named_vals"].items())[:6]:
                    print(f"║  {k:<10}: {v:<30}║")

            print("╠══════════════════════════════════════════╣")
            print(f"║  Messages: {t['msg_count']:<8}  "
                  f"Rate: {t['hz']:>5.1f} msg/s         ║")
            print("╚══════════════════════════════════════════╝")

            last_refresh = time.time()

except KeyboardInterrupt:
    print(f"\nStopped. Total messages: {t['msg_count']}")
    print("Run test_motors.py next (REMOVE PROPS FIRST)")
    