# rov_tests/test_connection.py
# Replace your existing file with this version
# It has more detailed diagnostics

from pymavlink import mavutil
from Vision.rov_config import LAPTOP_IP, PI_IP, MAV_PORT
import socket
import time

print("=" * 55)
print("  TEST 1 — MAVLink Connection & Heartbeat")
print("=" * 55)

# ── Pre-checks ────────────────────────────────────────────
print(f"\n[0] Pre-flight checks...")

# Check if port is already in use
test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    test_sock.bind(('0.0.0.0', MAV_PORT))
    test_sock.close()
    print(f"    ✅ Port {MAV_PORT} is free")
except OSError as e:
    test_sock.close()
    print(f"    ❌ Port {MAV_PORT} already in use: {e}")
    print(f"    Is QGroundControl open? Close it and retry.")
    exit(1)

# Quick ping check
print(f"    Checking Pi is reachable ({PI_IP})...")
import subprocess
result = subprocess.run(
    ['ping', '-n', '2', '-w', '1000', PI_IP],
    capture_output=True, text=True
)
if 'TTL=' in result.stdout:
    print(f"    ✅ Pi responding to ping")
else:
    print(f"    ❌ Pi not responding to ping")
    print(f"    Check ethernet connection")
    exit(1)

# ── Open MAVLink connection ───────────────────────────────
print(f"\n[1] Opening UDP connection on port {MAV_PORT}...")
try:
    mav = mavutil.mavlink_connection(
        f'udp:0.0.0.0:{MAV_PORT}',
        input=True
    )
    print(f"    ✅ Socket opened")
except Exception as e:
    print(f"    ❌ Failed: {e}")
    exit(1)

# ── Wait for heartbeat ────────────────────────────────────
print(f"\n[2] Waiting for heartbeat...")
print(f"    Make sure MAVProxy is running on Pi:")
print(f"    Check: ps aux | grep mavproxy (on Pi SSH)")
print()

start = time.time()
hb    = mav.wait_heartbeat(timeout=15)
elapsed = round(time.time() - start, 2)

if hb is None:
    print(f"    ❌ NO HEARTBEAT after {elapsed}s")
    print(f"\n    Diagnosis:")
    print(f"    1. On Pi SSH run:")
    print(f"       ps aux | grep mavproxy | grep -v grep")
    print(f"       → If empty: MAVProxy not running")
    print(f"       → Restart it with state-basedir flag")
    print(f"\n    2. Check Windows Firewall:")
    print(f"       Run fix_firewall.py as Administrator")
    print(f"\n    3. Check QGroundControl is CLOSED")
    exit(1)

# ── Success ───────────────────────────────────────────────
print(f"    ✅ HEARTBEAT in {elapsed}s")
print(f"\n[3] Vehicle details:")
print(f"    System ID  : {mav.target_system}")
print(f"    Component  : {mav.target_component}")
print(f"    Mode       : {mavutil.mode_string_v10(hb)}")
armed = bool(
    hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
)
print(f"    Armed      : {'⚠️  YES' if armed else '✅ NO'}")

# ── Count messages ────────────────────────────────────────
print(f"\n[4] Counting messages for 5 seconds...")

counts = {}
start  = time.time()

while time.time() - start < 5:
    msg = mav.recv_match(blocking=True, timeout=0.5)
    if msg is None:
        continue
    t = msg.get_type()
    if t != 'BAD_DATA':
        counts[t] = counts.get(t, 0) + 1

print(f"\n    {'Message':<25} {'Count':>5}   {'Rate':>6}")
print(f"    {'─'*40}")
for mt, ct in sorted(counts.items(),
                     key=lambda x: x[1], reverse=True):
    rate = ct / 5.0
    bar  = '█' * min(int(rate), 15)
    print(f"    {mt:<25} {ct:>5}   {rate:>5.1f}Hz  {bar}")

print(f"\n{'='*55}")
print(f"  ✅ Connection test PASSED")
print(f"  Run: python rov_tests/test_telemetry.py")
print(f"{'='*55}")