# rov_tests/diagnose_commands.py
# ═══════════════════════════════════════════════════════════════════════
# Systematically tests every possible MANUAL_CONTROL combination
# and reports exactly which servo channels respond and by how much.
# Answers the question: which commands actually work on THIS vehicle?
# ═══════════════════════════════════════════════════════════════════════

from pymavlink import mavutil
import time
import threading
import sys

try:
    from rov_config import MAV_PORT
except ImportError:
    MAV_PORT = 14551

THRUST       = 100    # 10% — slightly higher than before to clear deadzone
SPIN_SECS    = 2.5
SETTLE_SECS  = 1.5
NOISE_FLOOR  = 10     # µs — ignore below this


# =============================================================================
#  CONNECTION & ARM (same as before)
# =============================================================================

def connect():
    print(f"\n  Connecting on UDP port {MAV_PORT}...")
    mav = mavutil.mavlink_connection(
        f'udp:0.0.0.0:{MAV_PORT}', source_system=255)
    mav.wait_heartbeat()
    print(f"  ✅ Connected — system {mav.target_system}")
    return mav


class NeutralHold:
    def __init__(self, mav):
        self._mav = mav
        self._lock = threading.Lock()
        self._x = 0; self._y = 0
        self._z = 500; self._r = 0
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def cmd(self, x=0, y=0, z=500, r=0):
        with self._lock:
            T = 150  # hard cap
            self._x = max(-T, min(T, int(x)))
            self._y = max(-T, min(T, int(y)))
            self._z = max(0,  min(1000, int(z)))
            self._r = max(-T, min(T, int(r)))

    def neutral(self):
        self.cmd()

    def _loop(self):
        while self._running:
            with self._lock:
                x, y, z, r = self._x, self._y, self._z, self._r
            self._mav.mav.manual_control_send(
                self._mav.target_system, x, y, z, r, 0)
            time.sleep(0.1)


def arm_vehicle(mav):
    mode_id = mav.mode_mapping().get('MANUAL')
    mav.mav.set_mode_send(
        mav.target_system,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        mode_id)
    time.sleep(1)

    mav.mav.command_long_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 1, 21196, 0, 0, 0, 0, 0)
    time.sleep(3)

    hb = mav.recv_match(type='HEARTBEAT', blocking=True, timeout=3)
    armed = hb and bool(
        hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
    print(f"  Armed: {'✅ YES' if armed else '❌ NO'}")
    return armed


def disarm_vehicle(mav):
    mav.mav.command_long_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 0, 21196, 0, 0, 0, 0, 0)
    time.sleep(1)


# =============================================================================
#  SERVO READING
# =============================================================================

def baseline(mav, n=8):
    b = {i: [] for i in range(1, 5)}
    for _ in range(n):
        msg = mav.recv_match(
            type='SERVO_OUTPUT_RAW', blocking=True, timeout=1)
        if msg:
            for i in range(1, 5):
                b[i].append(getattr(msg, f'servo{i}_raw'))
        time.sleep(0.05)
    return {i: (sum(v)/len(v) if v else 1500) for i, v in b.items()}


def peak_delta(mav, base, secs):
    peaks = {i: 0 for i in range(1, 5)}
    end   = time.time() + secs
    while time.time() < end:
        msg = mav.recv_match(
            type='SERVO_OUTPUT_RAW', blocking=True, timeout=0.15)
        if msg:
            for i in range(1, 5):
                d = abs(getattr(msg, f'servo{i}_raw') - base[i])
                if d > NOISE_FLOOR and d > peaks[i]:
                    peaks[i] = d
    return peaks


def run_test(mav, nh, label, x, y, z, r):
    """Runs one command and returns {ch: delta}."""
    # Drain old messages
    end = time.time() + 0.3
    while time.time() < end:
        mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=False)

    base = baseline(mav)
    nh.cmd(x=x, y=y, z=z, r=r)
    deltas = peak_delta(mav, base, SPIN_SECS)
    nh.neutral()
    time.sleep(SETTLE_SECS)
    return deltas


def print_result(label, deltas, x, y, z, r):
    moved = [ch for ch, d in deltas.items() if d >= 30]
    sym   = "✅" if moved else "❌"
    print(f"\n  {sym} {label}")
    print(f"     x={x:4d}  y={y:4d}  z={z:4d}  r={r:4d}")
    for ch in range(1, 5):
        d   = deltas.get(ch, 0)
        bar = "█" * min(int(d / 5), 30)
        tag = "  ← MOVED" if d >= 30 else ""
        print(f"     Ch{ch}: {d:4.0f}µs  {bar}{tag}")
    if not moved:
        print(f"     ⚠️  NO channels responded")
    return moved


# =============================================================================
#  TEST BATTERY
# =============================================================================

def main():
    print("\n" + "═" * 65)
    print("  ARDUSUB COMMAND DIAGNOSTIC")
    print("  Finds which MANUAL_CONTROL values produce servo output")
    print("═" * 65)
    print(f"\n  Thrust level: {THRUST}/1000  ({THRUST/10:.0f}%)")
    print(f"  Spin time:    {SPIN_SECS}s per test")
    print("\n  ⚠️  Propellers must be REMOVED")
    ans = input("  Type YES to proceed: ")
    if ans.strip().upper() != "YES":
        sys.exit(0)

    mav = connect()
    nh  = NeutralHold(mav)
    nh.start()

    print("\n  Setting MANUAL mode and arming...")
    if not arm_vehicle(mav):
        print("  ❌ Could not arm — check ARMING_CHECK=0 in QGC")
        nh.stop()
        sys.exit(1)

    time.sleep(2)
    print("  ✅ Armed — starting diagnostic\n")

    results = {}
    T = THRUST

    # ─────────────────────────────────────────────────────────────────────────
    # BLOCK 1 — Single axis tests
    # These SHOULD work if the frame config and mixing matrix are correct.
    # If they all show 0, the frame type or SERVO_FUNCTION params are wrong.
    # ─────────────────────────────────────────────────────────────────────────
    print("═" * 65)
    print("  BLOCK 1 — SINGLE AXIS COMMANDS")
    print("  Expected: all 4 channels respond to each command")
    print("═" * 65)

    single_axis = [
        ("SURGE FWD    x=+T",  T,  0, 500,  0),
        ("SURGE REV    x=-T", -T,  0, 500,  0),
        ("SWAY PORT    y=-T",  0, -T, 500,  0),
        ("SWAY STBD    y=+T",  0,  T, 500,  0),
        ("YAW LEFT     r=-T",  0,  0, 500, -T),
        ("YAW RIGHT    r=+T",  0,  0, 500,  T),
        ("THROTTLE UP  z=600", 0,  0, 600,  0),
    ]

    for label, x, y, z, r in single_axis:
        d = run_test(mav, nh, label, x, y, z, r)
        results[label] = print_result(label, d, x, y, z, r)

    # ─────────────────────────────────────────────────────────────────────────
    # BLOCK 2 — Isolation vector tests
    # These are the combined-axis commands that isolated motors in Phase 0.
    # We know these work — this block confirms that and reads the channel map.
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "═" * 65)
    print("  BLOCK 2 — ISOLATION VECTORS (known to work from Phase 0)")
    print("  Each should move exactly ONE channel")
    print("═" * 65)

    isolation = [
        ("ISO Ch1 expected  x=+T y=-T r=+T",  T, -T, 500,  T),
        ("ISO Ch2 expected  x=+T y=+T r=-T",  T,  T, 500, -T),
        ("ISO Ch3 expected  x=-T y=-T r=-T", -T, -T, 500, -T),
        ("ISO Ch4 expected  x=-T y=+T r=+T", -T,  T, 500,  T),
    ]

    for label, x, y, z, r in isolation:
        d = run_test(mav, nh, label, x, y, z, r)
        results[label] = print_result(label, d, x, y, z, r)

    # ─────────────────────────────────────────────────────────────────────────
    # BLOCK 3 — Thrust scaling tests
    # Tests if lower thrust values are below the ArduSub deadzone.
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "═" * 65)
    print("  BLOCK 3 — THRUST SCALING (surge forward only)")
    print("  Finds the minimum thrust value that produces servo output")
    print("═" * 65)

    for thrust_val in (20, 50, 75, 100, 150, 200, 300):
        label = f"SURGE FWD  x={thrust_val}"
        d = run_test(mav, nh, label, thrust_val, 0, 500, 0)
        moved = print_result(label, d, thrust_val, 0, 500, 0)
        if moved:
            print(f"     ✅ First working threshold: {thrust_val}/1000 "
                  f"({thrust_val/10:.0f}%)")
            break

    # ─────────────────────────────────────────────────────────────────────────
    # BLOCK 4 — Frame config verification
    # Reads FRAME_CONFIG and SERVO_FUNCTION parameters directly
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "═" * 65)
    print("  BLOCK 4 — PARAMETER VERIFICATION")
    print("═" * 65)

    params_to_check = [
        "FRAME_CONFIG",
        "SERVO1_FUNCTION",
        "SERVO2_FUNCTION",
        "SERVO3_FUNCTION",
        "SERVO4_FUNCTION",
        "SERVO5_FUNCTION",
        "SERVO6_FUNCTION",
        "MOT_PWM_MIN",
        "MOT_PWM_MAX",
        "MOT_SPIN_MIN",
        "MOT_SPIN_ARM",
    ]

    print(f"\n  {'Parameter':<22}  {'Value':>8}  Notes")
    print(f"  {'─'*22}  {'─'*8}  {'─'*25}")

    frame_config_vals = {
        0: "BlueROV2 Original (4 thruster)",
        1: "BlueROV2 Heavy (6+2 thruster)",
        2: "Vectored 6DOF",
        3: "SimpleROV-3",
        4: "SimpleROV-4",
        5: "SimpleROV-5",
        6: "Custom — check mixing matrix",
    }

    servo_function_vals = {
        0:  "Disabled",
        33: "Motor 1",
        34: "Motor 2",
        35: "Motor 3",
        36: "Motor 4",
        37: "Motor 5",
        38: "Motor 6",
    }

    for param_name in params_to_check:
        mav.mav.param_request_read_send(
            mav.target_system, mav.target_component,
            param_name.encode('utf-8'), -1)
        msg = mav.recv_match(
            type='PARAM_VALUE', blocking=True, timeout=2)
        if msg:
            val = msg.param_value
            int_val = int(val)

            note = ""
            if param_name == "FRAME_CONFIG":
                note = frame_config_vals.get(int_val, "Unknown")
                if int_val != 0:
                    note += "  ⚠️  Should be 0"
            elif "SERVO" in param_name and "FUNCTION" in param_name:
                note = servo_function_vals.get(int_val, f"Value {int_val}")
                ch   = int(param_name[5])
                expected = 32 + ch
                if int_val == 0:
                    note += "  ❌ DISABLED — must be enabled"
                elif int_val != expected:
                    note += f"  ⚠️  Expected {expected} (Motor {ch})"
                else:
                    note += "  ✅"
            elif param_name == "MOT_SPIN_ARM":
                note = f"Spin-on-arm PWM offset"
            elif param_name == "MOT_SPIN_MIN":
                note = f"Minimum spin threshold"

            print(f"  {param_name:<22}  {int_val:>8}  {note}")
        else:
            print(f"  {param_name:<22}  {'N/A':>8}  ⚠️  Could not read")

    # ─────────────────────────────────────────────────────────────────────────
    # FINAL SUMMARY
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "═" * 65)
    print("  DIAGNOSTIC SUMMARY")
    print("═" * 65)

    single_axis_labels = [l for l, _, _, _, _ in single_axis]
    single_work = [l for l in single_axis_labels
                   if l in results and results[l]]
    iso_work    = [l for l, _, _, _, _ in isolation
                   if l in results and results[l]]

    print(f"\n  Single-axis commands that produced output: "
          f"{len(single_work)}/{len(single_axis_labels)}")
    print(f"  Isolation vectors that produced output:    "
          f"{len(iso_work)}/{len(isolation)}")

    if not single_work and iso_work:
        print("""
  ╔══════════════════════════════════════════════════════════╗
  ║  ROOT CAUSE IDENTIFIED                                   ║
  ╠══════════════════════════════════════════════════════════╣
  ║  Isolation vectors work (combined axes) but single-axis  ║
  ║  commands produce zero output.                           ║
  ║                                                          ║
  ║  This means the mixing matrix in ArduSub is computing   ║
  ║  very small (near-zero) values for pure single-axis      ║
  ║  inputs which fall below the motor deadzone.             ║
  ║                                                          ║
  ║  MOST LIKELY CAUSE:                                      ║
  ║  FRAME_CONFIG is set to the wrong frame type.            ║
  ║  The mixing coefficients for your 4-thruster frame       ║
  ║  do not match the frame type selected in ArduSub.        ║
  ║                                                          ║
  ║  FIX — In QGroundControl:                               ║
  ║  1. Vehicle Setup → Parameters                          ║
  ║  2. FRAME_CONFIG → set to 0 (BlueROV2 Original)         ║
  ║  3. Reboot Pixhawk                                       ║
  ║  4. Re-run this diagnostic                               ║
  ╚══════════════════════════════════════════════════════════╝
""")
    elif not single_work and not iso_work:
        print("""
  ╔══════════════════════════════════════════════════════════╗
  ║  NOTHING IS WORKING                                      ║
  ╠══════════════════════════════════════════════════════════╣
  ║  Neither single-axis nor isolation vectors produce       ║
  ║  any servo output. Most likely causes:                   ║
  ║                                                          ║
  ║  1. SERVO1-4_FUNCTION parameters not set to 33-36       ║
  ║     Fix: QGC → Parameters → set each SERVO_FUNCTION     ║
  ║                                                          ║
  ║  2. Vehicle not actually staying armed                   ║
  ║     Fix: Check neutral_hold is running                   ║
  ║                                                          ║
  ║  3. MAVProxy not routing commands to Pixhawk            ║
  ║     Fix: Check udpout flag in mavproxy service           ║
  ╚══════════════════════════════════════════════════════════╝
""")
    elif single_work:
        print("""
  ✅ Single-axis commands work.
  The main motor test suite should now function correctly.
  Re-run test_motors.py.
""")

    print("  Disarming...")
    disarm_vehicle(mav)
    nh.stop()
    print("  ✅ Done\n")


if __name__ == "__main__":
    main()