# rov_tests/post_reboot_test.py
# ═══════════════════════════════════════════════════════════════════════
# POST-REBOOT FRAME CONFIG VERIFICATION & MOTOR TEST
# ═══════════════════════════════════════════════════════════════════════
# Run this AFTER you have:
#   1. Changed FRAME_CONFIG to your desired value
#   2. Power cycled the Pixhawk (disconnected/reconnected LiPo)
#   3. Waited 30 seconds for full boot
#
# This script will:
#   1. Connect fresh
#   2. Verify FRAME_CONFIG and servo assignments
#   3. Check servo baselines (are all 4 channels alive?)
#   4. Arm the vehicle
#   5. Test every MANUAL_CONTROL axis
#   6. Report which channels respond to what
# ═══════════════════════════════════════════════════════════════════════

from pymavlink import mavutil
import time
import threading
import sys

try:
    from rov_config import MAV_PORT
except ImportError:
    MAV_PORT = 14551

THRUST = 100
SPIN_SECS = 3.0
SETTLE_SECS = 2.0
NOISE_FLOOR = 15


# ═════════════════════════════════════════════════════════════════════
#  CONNECTION
# ═════════════════════════════════════════════════════════════════════

def connect():
    print(f"\n  Connecting on UDP port {MAV_PORT}...")
    mav = mavutil.mavlink_connection(
        f'udp:0.0.0.0:{MAV_PORT}', source_system=255)
    mav.wait_heartbeat()

    if mav.target_component == 0:
        for _ in range(20):
            hb = mav.recv_match(type='HEARTBEAT', blocking=True, timeout=2)
            if hb and hb.get_srcComponent() != 0:
                mav.target_system = hb.get_srcSystem()
                mav.target_component = hb.get_srcComponent()
                break
        else:
            mav.target_component = 1

    print(f"  Connected: system={mav.target_system}, "
          f"component={mav.target_component}")
    return mav


# ═════════════════════════════════════════════════════════════════════
#  NEUTRAL HOLD
# ═════════════════════════════════════════════════════════════════════

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
            T = 150
            self._x = max(-T, min(T, int(x)))
            self._y = max(-T, min(T, int(y)))
            self._z = max(0, min(1000, int(z)))
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


# ═════════════════════════════════════════════════════════════════════
#  ARM / DISARM
# ═════════════════════════════════════════════════════════════════════

def arm_vehicle(mav, max_retries=3):
    for attempt in range(1, max_retries + 1):
        print(f"\n  -- ARM ATTEMPT {attempt}/{max_retries} --")
        mode_id = mav.mode_mapping().get('MANUAL')
        if mode_id is None:
            print(f"  MANUAL not in mode mapping!")
            return False

        mav.mav.set_mode_send(
            mav.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_id)
        time.sleep(1)

        mav.mav.command_long_send(
            mav.target_system, mav.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, 1, 21196, 0, 0, 0, 0, 0)

        ack = mav.recv_match(type='COMMAND_ACK', blocking=True, timeout=5)
        if ack:
            if ack.result != 0:
                print(f"  ACK result={ack.result} -- retrying...")
                time.sleep(2)
                continue
            else:
                print(f"  ACK: ACCEPTED")

        time.sleep(2)
        for _ in range(5):
            hb = mav.recv_match(type='HEARTBEAT', blocking=True, timeout=2)
            if hb and bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
                print(f"  Armed on attempt {attempt}")
                return True

        print(f"  Not armed on attempt {attempt}")
        time.sleep(2)
    return False


def disarm_vehicle(mav):
    mav.mav.command_long_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 0, 21196, 0, 0, 0, 0, 0)
    time.sleep(1)


# ═════════════════════════════════════════════════════════════════════
#  PARAMETER READ
# ═════════════════════════════════════════════════════════════════════

def read_param(mav, name, timeout=3):
    mav.mav.param_request_read_send(
        mav.target_system, mav.target_component,
        name.encode('utf-8'), -1)
    msg = mav.recv_match(type='PARAM_VALUE', blocking=True, timeout=timeout)
    if msg:
        return msg.param_value
    return None


# ═════════════════════════════════════════════════════════════════════
#  SERVO MONITORING
# ═════════════════════════════════════════════════════════════════════

def drain_messages(mav, duration=0.3):
    end = time.time() + duration
    while time.time() < end:
        mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=False)
        time.sleep(0.01)


def read_baseline(mav, duration=1.0):
    readings = {i: [] for i in range(1, 9)}
    end = time.time() + duration
    while time.time() < end:
        msg = mav.recv_match(type='SERVO_OUTPUT_RAW',
                             blocking=True, timeout=0.2)
        if msg:
            for i in range(1, 9):
                readings[i].append(getattr(msg, f'servo{i}_raw'))
        time.sleep(0.05)
    return {i: (sum(v) / len(v) if v else 0) for i, v in readings.items()}


def monitor_deltas(mav, baseline, duration):
    peaks = {i: 0.0 for i in range(1, 9)}
    count = 0
    end = time.time() + duration
    while time.time() < end:
        msg = mav.recv_match(type='SERVO_OUTPUT_RAW',
                             blocking=True, timeout=0.2)
        if msg:
            count += 1
            for i in range(1, 9):
                pwm = getattr(msg, f'servo{i}_raw')
                delta = pwm - baseline[i]
                if abs(delta) > abs(peaks[i]):
                    peaks[i] = delta
    return peaks, count


# ═════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 60)
    print("  POST-REBOOT FRAME VERIFICATION & MOTOR TEST")
    print("=" * 60)
    print(f"""
  Run this AFTER:
    1. FRAME_CONFIG has been changed
    2. LiPo disconnected and reconnected
    3. Waited 30 seconds for boot

  Port: UDP {MAV_PORT}
  Props must be REMOVED
""")

    confirm = input("  Type YES to proceed: ").strip().upper()
    if confirm != "YES":
        sys.exit(0)

    # ── STEP 1: Connect ──
    mav = connect()

    # ── STEP 2: Verify parameters ──
    print("\n" + "=" * 60)
    print("  STEP 1 -- PARAMETER VERIFICATION")
    print("=" * 60)

    frame_names = {
        0: "BlueROV1 (6-thruster vectored)",
        1: "SimpleROV-3 (3 thrusters)",
        2: "SimpleROV-4 (4 thrusters vectored)",
        3: "SimpleROV-5 (5 thrusters)",
        4: "BlueROV2 (6-thruster standard)",
        5: "BlueROV2 Heavy (8-thruster)",
        6: "Vectored-6DOF (6 thrusters)",
        7: "Custom (no param matrix)",
    }

    fc = read_param(mav, "FRAME_CONFIG")
    if fc is not None:
        fc_int = int(fc)
        name = frame_names.get(fc_int, f"Unknown({fc_int})")
        print(f"\n  FRAME_CONFIG = {fc_int}  ({name})")
    else:
        print(f"\n  Could not read FRAME_CONFIG!")
        fc_int = -1

    ac = read_param(mav, "ARMING_CHECK")
    if ac is not None:
        print(f"  ARMING_CHECK = {int(ac)}  "
              f"{'(disabled)' if int(ac) == 0 else 'WARNING: should be 0'}")

    print(f"\n  Servo assignments:")
    func_names = {
        0: "Disabled", 33: "Motor1", 34: "Motor2",
        35: "Motor3", 36: "Motor4", 37: "Motor5",
        38: "Motor6", 39: "Motor7", 40: "Motor8",
        7: "RCPassThru", 181: "ProGripperOpen"
    }
    for i in range(1, 9):
        val = read_param(mav, f"SERVO{i}_FUNCTION")
        if val is not None:
            iv = int(val)
            fname = func_names.get(iv, f"Function_{iv}")
            expected = ""
            if i <= 4:
                exp = 32 + i
                expected = " OK" if iv == exp else f" WARNING: expected {exp}"
            else:
                expected = " OK" if iv == 0 else " WARNING: should be 0"
            print(f"    SERVO{i}_FUNCTION = {iv:>3} ({fname}){expected}")

    # ── STEP 3: Check servo baselines BEFORE arming ──
    print("\n" + "=" * 60)
    print("  STEP 2 -- SERVO BASELINE CHECK (before arming)")
    print("=" * 60)

    drain_messages(mav)
    base_pre = read_baseline(mav, 1.5)
    print(f"\n  Pre-arm servo baselines:")
    for i in range(1, 9):
        b = base_pre[i]
        if b == 0:
            status = "OFF/uninitialized"
        elif 1450 <= b <= 1550:
            status = "neutral (good)"
        else:
            status = f"unexpected"
        print(f"    Ch{i}: {b:6.0f}us  ({status})")

    alive_pre = [i for i in range(1, 5) if 1450 <= base_pre[i] <= 1550]
    dead_pre = [i for i in range(1, 5) if base_pre[i] == 0]

    if dead_pre:
        print(f"\n  WARNING: Channels {dead_pre} show 0us before arming")
        print(f"  These channels may not be initialized by this frame type")

    # ── STEP 4: Arm ──
    print("\n" + "=" * 60)
    print("  STEP 3 -- ARMING")
    print("=" * 60)

    nh = NeutralHold(mav)
    nh.start()

    if not arm_vehicle(mav):
        print("\n  Could not arm the vehicle!")
        print("  Possible causes:")
        print("    - ARMING_CHECK may have reset (set to 0 again)")
        print("    - New frame type may have different arm requirements")
        print("    - Try power cycling and running again")
        nh.stop()
        sys.exit(1)

    time.sleep(2)

    # ── STEP 5: Check servo baselines AFTER arming ──
    print("\n" + "=" * 60)
    print("  STEP 4 -- SERVO BASELINE CHECK (after arming)")
    print("=" * 60)

    drain_messages(mav)
    base_armed = read_baseline(mav, 1.5)
    print(f"\n  Armed servo baselines:")
    for i in range(1, 9):
        b = base_armed[i]
        pre = base_pre[i]
        changed = "CHANGED" if abs(b - pre) > 10 else ""
        if b == 0:
            status = "OFF"
        elif 1450 <= b <= 1550:
            status = "neutral"
        else:
            status = "active"
        print(f"    Ch{i}: {b:6.0f}us  ({status})  {changed}")

    alive_armed = [i for i in range(1, 5)
                   if 1450 <= base_armed[i] <= 1550]
    dead_armed = [i for i in range(1, 5) if base_armed[i] == 0]

    if dead_armed:
        print(f"\n  WARNING: Channels {dead_armed} still 0us after arming!")
    if alive_armed:
        print(f"\n  Active motor channels: {alive_armed}")

    # ── STEP 6: Axis tests ──
    print("\n" + "=" * 60)
    print("  STEP 5 -- MANUAL_CONTROL AXIS TESTS")
    print(f"  Thrust: {THRUST}/1000 ({THRUST/10:.0f}%)")
    print(f"  Duration: {SPIN_SECS}s per test")
    print("=" * 60)

    T = THRUST
    tests = [
        ("FORWARD      x=+T",    T,   0, 500,   0),
        ("BACKWARD     x=-T",   -T,   0, 500,   0),
        ("STRAFE RIGHT y=+T",    0,   T, 500,   0),
        ("STRAFE LEFT  y=-T",    0,  -T, 500,   0),
        ("YAW CW      r=+T",    0,   0, 500,   T),
        ("YAW CCW     r=-T",    0,   0, 500,  -T),
        ("ASCEND      z=700",    0,   0, 700,   0),
        ("DESCEND     z=300",    0,   0, 300,   0),
    ]

    results = {}
    for label, x, y, z, r in tests:
        print(f"\n  >> {label}")
        print(f"     x={x:+4d}  y={y:+4d}  z={z:4d}  r={r:+4d}")

        drain_messages(mav)
        base = read_baseline(mav, 0.5)

        nh.cmd(x=x, y=y, z=z, r=r)
        peaks, count = monitor_deltas(mav, base, SPIN_SECS)
        nh.neutral()

        moved = []
        print(f"     Servo messages captured: {count}")
        for i in range(1, 5):
            d = peaks[i]
            bar = "#" * min(int(abs(d) / 3), 30)
            direction = "UP  " if d > 0 else "DOWN" if d < 0 else "    "
            tag = " <-- MOVED" if abs(d) > NOISE_FLOOR else ""
            print(f"     Ch{i}: {d:+7.0f}us  {direction}  {bar}{tag}")
            if abs(d) > NOISE_FLOOR:
                moved.append((i, "UP" if d > 0 else "DOWN"))

        # Also check channels 5-8 just in case
        extra_moved = []
        for i in range(5, 9):
            d = peaks[i]
            if abs(d) > NOISE_FLOOR:
                extra_moved.append((i, d))

        if extra_moved:
            print(f"     Also moved on Ch5-8: {extra_moved}")

        if moved:
            print(f"     RESPONDED: {moved}")
        else:
            print(f"     NO RESPONSE")

        results[label] = {
            "moved": moved,
            "peaks": {i: peaks[i] for i in range(1, 9)},
            "x": x, "y": y, "z": z, "r": r
        }

        time.sleep(SETTLE_SECS)

    # ── SUMMARY ──
    print("\n" + "=" * 60)
    print("  COMPLETE TEST SUMMARY")
    print("=" * 60)

    print(f"\n  FRAME_CONFIG = {fc_int}  "
          f"({frame_names.get(fc_int, 'Unknown')})")
    print(f"  Active servo channels at baseline: {alive_armed}")
    print(f"  Dead servo channels: {dead_armed}")

    print(f"\n  {'Axis Test':<25} {'Channels Moved':<30}")
    print(f"  {'-'*25} {'-'*30}")

    any_worked = False
    for label, info in results.items():
        moved_str = str(info['moved']) if info['moved'] else "NONE"
        sym = "OK  " if info['moved'] else "FAIL"
        print(f"  [{sym}] {label:<23} {moved_str}")
        if info['moved']:
            any_worked = True

    # ── Analysis ──
    if any_worked:
        print(f"""
  ============================================================
  MOTORS ARE RESPONDING!

  FRAME_CONFIG = {fc_int} is producing servo output.

  Next steps:
  1. Look at which channels respond to FORWARD vs YAW etc
  2. Physically identify each motor position (FR/FL/BR/BL)
  3. If any direction is backward:
     - Change MOT_X_DIRECTION from 1 to -1
     - OR swap two motor phase wires
  4. Your GUI MANUAL_CONTROL commands will now work!
  ============================================================
""")

        # Build motor map from results
        print("  MOTOR BEHAVIOR MAP:")
        print("  (Which channels go UP/DOWN for each command)\n")

        for label, info in results.items():
            if info['moved']:
                parts = []
                for ch, direction in info['moved']:
                    parts.append(f"Ch{ch}={direction}")
                print(f"    {label:<25} {', '.join(parts)}")

    elif alive_armed and not any_worked:
        print(f"""
  ============================================================
  CHANNELS ARE ALIVE BUT NO AXIS RESPONSE

  Channels {alive_armed} show 1500us (initialized) but
  MANUAL_CONTROL commands produce zero output.

  This means the mixing matrix for FRAME_CONFIG={fc_int}
  does not map to your physical motor arrangement.

  Try a different frame:
    - Re-run frame_fix_and_test.py with a different number
    - Frame 0 (BlueROV1) has a vectored 6-thruster matrix
    - Frame 4 (BlueROV2) has a different layout
  ============================================================
""")

    elif dead_armed:
        print(f"""
  ============================================================
  SERVO CHANNELS NOT INITIALIZED

  Channels {dead_armed} show 0us even after arming.
  This frame type may not initialize all 4 motor outputs.

  Possible fixes:
    1. Try a different FRAME_CONFIG value
    2. Check SERVO{dead_armed[0]}_FUNCTION is set correctly
    3. Check physical wiring on Pixhawk MAIN OUT pins
  ============================================================
""")

    else:
        print(f"""
  ============================================================
  NO RESPONSE AT ALL

  No servo channels responded to any command.
  Try a different FRAME_CONFIG value.
  ============================================================
""")

    print("\n  Disarming...")
    disarm_vehicle(mav)
    nh.stop()
    print("  Done\n")


if __name__ == "__main__":
    main()