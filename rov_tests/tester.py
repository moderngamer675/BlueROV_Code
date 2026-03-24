# rov_tests/test_motors.py
# SAFE individual motor test
# MAX 10% thrust — safe for out of water
# Run with: python rov_tests/test_motors.py

from pymavlink import mavutil
from rov_config import MAV_PORT
import time

# ══════════════════════════════════════════════
#  SAFETY SETTINGS — DO NOT INCREASE
#  These are safe for out-of-water testing
# ══════════════════════════════════════════════
TEST_SPEED    = 100    # 10% MAX — safe out of water
TEST_DURATION = 2.0    # 2 seconds per motor
RAMP_STEPS    = 20     # slow smooth ramp
RAMP_DELAY    = 0.05   # seconds between steps

# ══════════════════════════════════════════════
#  EMERGENCY STOP
#  If anything goes wrong press Ctrl+C
#  The finally block will disarm immediately
# ══════════════════════════════════════════════

# Mixing matrix from servo_watch diagnostic:
# Forward:   M1- M2- M3+ M4+
# Reverse:   M1+ M2+ M3- M4-
# Strafe-R:  M1+ M2- M3+ M4-
# Strafe-L:  M1- M2+ M3- M4+
# Yaw-R:     M1+ M2- M3- M4+
# Yaw-L:     M1- M2+ M3+ M4-
# Descend:   M5+ M6+

S = TEST_SPEED

MOTORS = {
    1: {
        "name":  "Front-Left  Horizontal",
        "x": -S, "y":  S, "r":  S, "z": 500,
        "note":  "Reverse + StrafeR + YawR",
    },
    2: {
        "name":  "Front-Right Horizontal",
        "x": -S, "y": -S, "r": -S, "z": 500,
        "note":  "Reverse + StrafeL + YawL",
    },
    3: {
        "name":  "Rear-Left   Horizontal",
        "x":  S, "y":  S, "r": -S, "z": 500,
        "note":  "Forward + StrafeR + YawL",
    },
    4: {
        "name":  "Rear-Right  Horizontal",
        "x":  S, "y": -S, "r":  S, "z": 500,
        "note":  "Forward + StrafeL + YawR",
    },
    5: {
        "name":  "Front-Left  Vertical",
        "x":  0, "y":  0, "r":  0, "z": 500 - S,
        "note":  "Descend — M5+M6 vertical pair",
    },
    6: {
        "name":  "Front-Right Vertical",
        "x":  0, "y":  0, "r":  0, "z": 500 - S,
        "note":  "Descend — M5+M6 vertical pair",
    },
}

# ── Safety banner ─────────────────────────────────────────
print("=" * 62)
print("  BlueROV2 Safe Motor Test")
print("  MAX SPEED: 10% thrust")
print("=" * 62)
print()
print(f"  Speed    : {TEST_SPEED}/1000  ({TEST_SPEED/10:.0f}% thrust)")
print(f"  Duration : {TEST_DURATION}s per motor")
print()
print("  SAFETY CHECKLIST:")
print("  [ ] Props removed from ALL thrusters")
print("  [ ] ROV secured — cannot fall or move")
print("  [ ] Someone watching the ROV physically")
print("  [ ] Hand near keyboard to press Ctrl+C")
print()
print("  Ctrl+C at ANY TIME = immediate disarm")
print()
confirm = input("  Type CONFIRM to begin: ").strip()
if confirm.upper() != "CONFIRM":
    print("  Aborted.")
    exit(0)

# ── Connect ───────────────────────────────────────────────
print(f"\n[1] Connecting...")
mav = mavutil.mavlink_connection(
    f'udp:0.0.0.0:{MAV_PORT}',
    source_system=255
)
hb = mav.wait_heartbeat(timeout=15)
if hb is None:
    print("    ❌ No heartbeat — check MAVProxy on Pi")
    exit(1)
print(f"    ✅ Connected")

# ── Core functions ────────────────────────────────────────
_last_hb = [time.time()]

def send_hb():
    if time.time() - _last_hb[0] >= 0.5:
        mav.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0, 0, 0
        )
        _last_hb[0] = time.time()

def send_manual(x=0, y=0, z=500, r=0):
    """
    Send MANUAL_CONTROL
    All values clamped to safe range
    """
    # Hard clamp — never exceed safe speed
    limit = max(TEST_SPEED, 150)
    x = max(-limit, min(limit, int(x)))
    y = max(-limit, min(limit, int(y)))
    r = max(-limit, min(limit, int(r)))
    z = max(500 - limit, min(500 + limit, int(z)))
    mav.mav.manual_control_send(
        mav.target_system,
        x, y, z, r, 0
    )

def send_neutral():
    """Always safe — sends zero movement"""
    mav.mav.manual_control_send(
        mav.target_system,
        0, 0, 500, 0, 0
    )

def neutral_hold(seconds: float):
    """
    Hold neutral for N seconds
    Keeps ArduSub armed by sending every 100ms
    """
    t_end = time.time() + seconds
    while time.time() < t_end:
        send_hb()
        send_neutral()
        time.sleep(0.1)

def ramp_up(x=0, y=0, z=500, r=0):
    """Slowly ramp from zero to target over RAMP_STEPS"""
    for step in range(RAMP_STEPS + 1):
        f = step / RAMP_STEPS
        send_hb()
        send_manual(
            x=x * f,
            y=y * f,
            z=500 + (z - 500) * f,
            r=r * f
        )
        time.sleep(RAMP_DELAY)

def ramp_down(x=0, y=0, z=500, r=0):
    """Slowly ramp from target back to zero"""
    for step in range(RAMP_STEPS, -1, -1):
        f = step / RAMP_STEPS
        send_hb()
        send_manual(
            x=x * f,
            y=y * f,
            z=500 + (z - 500) * f,
            r=r * f
        )
        time.sleep(RAMP_DELAY)

def emergency_stop():
    """Immediate stop and disarm"""
    send_neutral()
    time.sleep(0.2)
    mav.mav.command_long_send(
        mav.target_system,
        mav.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 0, 0, 0, 0, 0, 0, 0
    )

def check_armed() -> bool:
    msg = mav.recv_match(
        type='HEARTBEAT',
        blocking=True,
        timeout=0.5
    )
    if msg:
        return bool(
            msg.base_mode &
            mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        )
    return False

def arm() -> bool:
    mav.mav.command_long_send(
        mav.target_system,
        mav.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 1, 21196, 0, 0, 0, 0, 0
    )
    deadline = time.time() + 8
    while time.time() < deadline:
        send_hb()
        send_neutral()
        msg = mav.recv_match(
            type='HEARTBEAT',
            blocking=True,
            timeout=1
        )
        if msg and bool(
            msg.base_mode &
            mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        ):
            return True
    return False

def read_servos() -> dict:
    msg = mav.recv_match(
        type='SERVO_OUTPUT_RAW',
        blocking=True,
        timeout=0.3
    )
    if msg:
        return {
            i: getattr(msg, f'servo{i}_raw', 0)
            for i in range(1, 7)
        }
    return {i: 0 for i in range(1, 7)}

# ── Set MANUAL mode ───────────────────────────────────────
print(f"\n[2] Setting MANUAL mode...")
mode_id = mav.mode_mapping().get('MANUAL')
if mode_id is None:
    print("    ❌ MANUAL mode not found")
    exit(1)
mav.mav.set_mode_send(
    mav.target_system,
    mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
    mode_id
)
time.sleep(2)

msg = mav.recv_match(
    type='HEARTBEAT', blocking=True, timeout=3)
if msg:
    actual = mavutil.mode_string_v10(msg)
    ok     = actual == 'MANUAL'
    print(f"    Mode: {actual} {'✅' if ok else '❌'}")
    if not ok:
        print("    ❌ Not in MANUAL — aborting")
        exit(1)

# ── Arm ───────────────────────────────────────────────────
print(f"\n[3] Arming...")
if not arm():
    print("    ❌ Could not arm — check QGC parameters")
    exit(1)
print(f"    ✅ ARMED")

# ── Warm up ───────────────────────────────────────────────
print(f"\n[4] Stabilising connection (2 seconds)...")
neutral_hold(2.0)
still = check_armed()
print(f"    Arm state: {'✅ still armed' if still else '❌ disarmed'}")
if not still:
    print("    Set DISARM_DELAY=0 in QGC and retry")
    exit(1)

# ── Motor tests ───────────────────────────────────────────
print(f"\n[5] Starting motor tests")
print(f"    Speed  : {TEST_SPEED}/1000 = {TEST_SPEED/10:.0f}% thrust")
print(f"    Duration: {TEST_DURATION}s each")
print(f"    Ctrl+C  : emergency stop\n")

results = {}

try:
    for num, cfg in MOTORS.items():
        name = cfg["name"]
        x    = cfg["x"]
        y    = cfg["y"]
        z    = cfg["z"]
        r    = cfg["r"]
        note = cfg["note"]

        print(f"  {'─'*58}")
        print(f"  Motor {num}/{len(MOTORS)} — {name}")
        print(f"  Method: {note}")

        # ── Check armed ───────────────────────────────────
        if not check_armed():
            print(f"  ⚠️  Disarmed — re-arming...")
            if not arm():
                print(f"  ❌ Cannot re-arm — skipping")
                results[num] = {
                    "name":         name,
                    "passed":       False,
                    "skipped":      True,
                    "target_moved": False,
                    "note":         "could not arm",
                }
                continue
            print(f"  ✅ Re-armed")

        neutral_hold(0.3)

        # ── Ramp up slowly ────────────────────────────────
        print(f"  Ramping up slowly to {TEST_SPEED}/1000...",
              end="", flush=True)
        ramp_up(x=x, y=y, z=z, r=r)
        print(f" ✅ at speed")

        # ── Run and monitor ───────────────────────────────
        servo_readings = {i: [] for i in range(1, 7)}
        t_end = time.time() + TEST_DURATION

        while time.time() < t_end:
            send_hb()
            send_manual(x=x, y=y, z=z, r=r)

            svs = read_servos()
            for i in range(1, 7):
                if svs.get(i, 0) > 0:
                    servo_readings[i].append(svs[i])

            remaining = t_end - time.time()
            # Show all 6 servo values live
            sv_str = "  ".join(
                f"{'►' if i == num else ' '}"
                f"M{i}={svs.get(i, 0)}"
                for i in range(1, 7)
            )
            print(
                f"\r  ⏱ {remaining:.1f}s  {sv_str}  ",
                end="", flush=True
            )
            time.sleep(0.1)

        print(f"\r  ✅ Run complete"
              f"                                          ")

        # ── Ramp down safely ──────────────────────────────
        print(f"  Ramping down...", end="", flush=True)
        ramp_down(x=x, y=y, z=z, r=r)
        print(f" stopped")

        # ── Analyse servo data ────────────────────────────
        print(f"\n  Servo analysis:")
        target_moved = False
        for i in range(1, 7):
            rdgs = servo_readings[i]
            if rdgs:
                avg   = sum(rdgs) // len(rdgs)
                delta = avg - 1500
                moved = abs(delta) >= 10
                if i == num:
                    target_moved = moved
                marker = " ◄ TARGET" if i == num else ""
                flag   = "✅" if (moved and i == num) else \
                         "⚠️ " if (moved and i != num) else \
                         "   "
                bar    = (
                    "█" * min(abs(delta) // 5, 15)
                )
                direction = "▲" if delta > 0 else \
                            "▼" if delta < 0 else " "
                print(f"    {flag} M{i}: "
                      f"{direction}{abs(delta):>3}µs  "
                      f"avg={avg}µs  "
                      f"[{bar:<15}]"
                      f"{marker}")

        # ── Ask user ──────────────────────────────────────
        neutral_hold(0.3)
        print()

        if target_moved:
            print(f"  ℹ️  Servo data shows M{num} responded")
        else:
            print(f"  ⚠️  Servo data shows M{num} did NOT move")

        response = input(
            f"  Did you HEAR/SEE motor {num} "
            f"({name}) spin? (y/n/s=skip): "
        ).strip().lower()

        results[num] = {
            "name":         name,
            "passed":       response == 'y',
            "skipped":      response == 's',
            "target_moved": target_moved,
            "note":         note,
        }
        print()

        # Keep armed for next test
        neutral_hold(0.5)

except KeyboardInterrupt:
    print("\n\n  ⚠️  Ctrl+C — Emergency stop!")

finally:
    # ── Always disarm safely ──────────────────────────────
    print("\n[6] Emergency stop and disarm...")
    emergency_stop()
    time.sleep(0.5)
    emergency_stop()   # Send twice to be sure
    time.sleep(2)

    msg = mav.recv_match(
        type='HEARTBEAT', blocking=True, timeout=3)
    if msg:
        still = bool(
            msg.base_mode &
            mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        )
        if still:
            print(f"    ⚠️  Still armed — "
                  f"disconnect battery if needed!")
        else:
            print(f"    ✅ Disarmed safely")

# ── Results ───────────────────────────────────────────────
if not results:
    print("\nNo results recorded.")
    exit(0)

print(f"\n{'='*62}")
print(f"  Motor Test Results")
print(f"  Speed: {TEST_SPEED}/1000  Duration: {TEST_DURATION}s")
print(f"{'='*62}")

passed = 0
failed = []

for num, d in results.items():
    if d["skipped"]:
        icon   = "⏭ "
        status = "SKIP"
    elif d["passed"]:
        icon   = "✅"
        status = "PASS"
        passed += 1
    else:
        icon   = "❌"
        status = "FAIL"
        failed.append(num)

    servo_note = (
        "servo confirmed moved" if d["target_moved"]
        else "servo showed no movement"
    )
    print(f"  {icon} M{num} {d['name']:<28} "
          f"{status}  {servo_note}")

tested = len([
    d for d in results.values() if not d["skipped"]
])
print(f"\n  Score: {passed}/{tested}")

if failed:
    print(f"\n  ❌ Motors to investigate: {failed}")
    print()
    print(f"  For each failed motor check in this order:")
    print()
    print(f"  1. QGroundControl → Vehicle Setup → Motors")
    print(f"     Does the slider spin that motor?")
    print(f"     If YES  → axis mixing issue in our code")
    print(f"     If NO   → hardware problem")
    print()
    print(f"  2. Hardware checks:")
    print(f"     — ESC signal wire firmly in Pixhawk")
    print(f"     — ESC power leads connected")
    print(f"     — Thruster cable into ESC")
    print(f"     — ESC LED blinking normally")
else:
    print(f"\n  ✅ All motors confirmed working!")
    print(f"  Next step: refit props and do wet test")
print(f"{'='*62}")