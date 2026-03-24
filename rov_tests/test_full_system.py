# rov_tests/test_full_system.py
# Runs all checks in one go
# Run with: python rov_tests/test_full_system.py

from pymavlink import mavutil
import socket
import numpy as np
import cv2
import time
import subprocess
from Vision.rov_config import (PI_IP, LAPTOP_IP, PI_USERNAME,
                        PI_PASSWORD, MAV_PORT, VIDEO_PORT)

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = {}

def check(name, passed, detail=""):
    results[name] = passed
    icon = PASS if passed else FAIL
    print(f"  {icon}  {name:<30} {detail}")

print("=" * 60)
print("  BlueROV2 Full System Check")
print("=" * 60)

# ── 1. Network ────────────────────────────────────────────
print(f"\n[1] Network")
r = subprocess.run(
    ['ping', '-n', '3', '-w', '1000', PI_IP],
    capture_output=True, text=True
)
ping_ok = 'TTL=' in r.stdout
check("Pi reachable (ping)", ping_ok, PI_IP)

# ── 2. MAVLink ────────────────────────────────────────────
print(f"\n[2] MAVLink & Telemetry")
try:
    mav = mavutil.mavlink_connection(
        f'udp:0.0.0.0:{MAV_PORT}')
    hb  = mav.wait_heartbeat(timeout=10)

    if hb:
        mode  = mavutil.mode_string_v10(hb)
        armed = bool(
            hb.base_mode &
            mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        )
        check("MAVLink heartbeat",   True,  f"System {mav.target_system}")
        check("ArduSub mode",        True,  mode)
        check("Vehicle safe",        not armed,
              "SAFE" if not armed else "⚠️  ARMED")

        # Read 3 seconds of telemetry
        telem = {}
        deadline = time.time() + 3
        while time.time() < deadline:
            msg = mav.recv_match(blocking=True, timeout=0.5)
            if msg:
                telem[msg.get_type()] = msg

        check("ATTITUDE data",       'ATTITUDE'       in telem)
        check("VFR_HUD data",        'VFR_HUD'        in telem)
        check("SYS_STATUS data",     'SYS_STATUS'     in telem)
        check("SERVO_OUTPUT data",   'SERVO_OUTPUT_RAW' in telem)
        check("SCALED_PRESSURE",     'SCALED_PRESSURE' in telem)

        if 'SYS_STATUS' in telem:
            v = telem['SYS_STATUS'].voltage_battery / 1000.0
            check("Battery reading",
                  v > 0,
                  f"{v:.2f}V" if v > 0 else "Not configured")

        if 'ATTITUDE' in telem:
            att = telem['ATTITUDE']
            r   = att.roll  * 57.2958
            p   = att.pitch * 57.2958
            check("IMU/EKF working",
                  True,
                  f"Roll:{r:.1f}° Pitch:{p:.1f}°")

    else:
        check("MAVLink heartbeat", False, "No response in 10s")

except Exception as e:
    check("MAVLink connection", False, str(e))
    mav = None

# ── 3. Camera ─────────────────────────────────────────────
print(f"\n[3] Camera Stream")

cam_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
cam_sock.setsockopt(
    socket.SOL_SOCKET, socket.SO_RCVBUF, 131072)

try:
    cam_sock.bind(('0.0.0.0', VIDEO_PORT))
    check("Video port free", True, f"Port {VIDEO_PORT}")

    cam_sock.settimeout(6.0)
    frame_count = 0
    sizes       = []
    start       = time.time()

    try:
        while time.time() - start < 5:
            try:
                data, addr = cam_sock.recvfrom(131072)
                frame = cv2.imdecode(
                    np.frombuffer(data, np.uint8),
                    cv2.IMREAD_COLOR
                )
                if frame is not None:
                    frame_count += 1
                    sizes.append(len(data))
            except socket.timeout:
                break
    except Exception:
        pass

    fps     = frame_count / 5.0
    avg_pkt = sum(sizes) // len(sizes) if sizes else 0

    check("Camera frames received",
          frame_count > 0,
          f"{frame_count} frames in 5s")
    check("Camera FPS acceptable",
          fps >= 10,
          f"{fps:.1f} fps (target: 25)")
    check("Packet size safe",
          avg_pkt < 65507,
          f"Avg {avg_pkt}B (max 65507B)")

except OSError as e:
    check("Video port free", False, str(e))

finally:
    cam_sock.close()

# ── 4. Summary ────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  Results Summary")
print(f"{'='*60}")

passed = sum(1 for v in results.values() if v)
total  = len(results)
pct    = int(passed / total * 100) if total > 0 else 0

for name, ok in results.items():
    icon = PASS if ok else FAIL
    print(f"  {icon}  {name}")

print(f"\n  Score: {passed}/{total} ({pct}%)")
print()

if passed == total:
    print("  ✅ ALL SYSTEMS GO")
    print("  System is ready for operation")
    print()
    print("  Next steps:")
    print("  1. Remove propellers from thrusters")
    print("  2. python rov_tests/test_motors.py")
    print("  3. Refit propellers")
    print("  4. python RobotApp.py")
elif pct >= 80:
    print("  ⚠️  MOSTLY READY — minor issues to fix")
    failed = [n for n, v in results.items() if not v]
    for f in failed:
        print(f"  Fix: {f}")
else:
    print("  ❌ SYSTEM NOT READY")
    print("  Resolve failed checks before operating")

print(f"{'='*60}")