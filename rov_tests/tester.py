#!/usr/bin/env python3
"""
mixing_matrix_diagnostic.py  (v2 — fixed ESC deadband issue)

Sends single-axis MANUAL_CONTROL commands and captures SERVO_OUTPUT_RAW
to verify the mixing matrix AND confirm physical motor spin.

v2 changes:
  - Thrust increased to 250/1000 to overcome ESC deadband
  - Pre-flight check confirms motors actually spin before full suite
  - Pulse reduced to 1.5s for bench safety at higher thrust
  - Reports actual PWM values so you can see deadband clearance

Uses proven connection/arm/neutral-hold patterns from motor_identify.py.
"""

from pymavlink import mavutil
import time
import threading
import sys

try:
    from rov_config import MAV_PORT
except ImportError:
    MAV_PORT = 14551

# ─── CONFIGURATION ──────────────────────────────────────────────────────────
THRUST_VALUE    = 250       # 25% — enough to clear ESC deadband on single axis
PULSE_DURATION  = 1.5       # seconds per test (shorter due to higher thrust)
SETTLE_SECS     = 2.0       # seconds of neutral between tests
PWM_NEUTRAL     = 1500
PWM_DEADBAND    = 25        # ESC won't spin below this deviation from 1500
# ────────────────────────────────────────────────────────────────────────────

# Motor layout reference (from verified memo)
MOTOR_MAP = {
    1: "BR (CCW)",
    2: "BL (CW)",
    3: "FR (CW)",
    4: "FL (CCW)",
}

# Test sequence: (name, x, y, z, r)
TEST_SEQUENCE = [
    ("FORWARD",       +THRUST_VALUE,  0,              500,  0),
    ("BACKWARD",      -THRUST_VALUE,  0,              500,  0),
    ("STRAFE RIGHT",  0,              +THRUST_VALUE,  500,  0),
    ("STRAFE LEFT",   0,              -THRUST_VALUE,  500,  0),
    ("YAW CW",        0,              0,              500,  +THRUST_VALUE),
    ("YAW CCW",       0,              0,              500,  -THRUST_VALUE),
]

# Known mixing matrix from FRAME_CONFIG=1 (verified)
MIXING_MATRIX = {
    1: {"fwd": -1, "lat": +1, "yaw": +1},  # BR CCW
    2: {"fwd": -1, "lat": -1, "yaw": -1},  # BL CW
    3: {"fwd": +1, "lat": +1, "yaw": -1},  # FR CW
    4: {"fwd": +1, "lat": -1, "yaw": +1},  # FL CCW
}

# Expected channel behavior for each test (UP or DN)
EXPECTED_DIRS = {
    "FORWARD":      {"ch1": "DN", "ch2": "DN", "ch3": "UP", "ch4": "UP"},
    "BACKWARD":     {"ch1": "UP", "ch2": "UP", "ch3": "DN", "ch4": "DN"},
    "STRAFE RIGHT": {"ch1": "UP", "ch2": "DN", "ch3": "UP", "ch4": "DN"},
    "STRAFE LEFT":  {"ch1": "DN", "ch2": "UP", "ch3": "DN", "ch4": "UP"},
    "YAW CW":       {"ch1": "UP", "ch2": "DN", "ch3": "DN", "ch4": "UP"},
    "YAW CCW":      {"ch1": "DN", "ch2": "UP", "ch3": "UP", "ch4": "DN"},
}


# ═════════════════════════════════════════════════════════════════════
#  CONNECTION (proven working)
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
#  NEUTRAL HOLD (proven working)
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
            # Allow up to 400 for diagnostic tests
            T = 400
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
#  ARM / DISARM (proven working)
# ═════════════════════════════════════════════════════════════════════

def arm_vehicle(mav, max_retries=3):
    for attempt in range(1, max_retries + 1):
        print(f"\n  -- ARM ATTEMPT {attempt}/{max_retries} --")
        mode_id = mav.mode_mapping().get('MANUAL')
        if mode_id is None:
            print("  ERROR: MANUAL mode not found in mode mapping!")
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
        if ack and ack.result != 0:
            print(f"  ARM rejected (result={ack.result}), retrying...")
            time.sleep(2)
            continue

        time.sleep(2)
        for _ in range(5):
            hb = mav.recv_match(type='HEARTBEAT', blocking=True, timeout=2)
            if hb and bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
                print(f"  Armed on attempt {attempt}")
                return True

        time.sleep(2)
    return False


def disarm_vehicle(mav):
    mav.mav.command_long_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 0, 21196, 0, 0, 0, 0, 0)
    time.sleep(1)


# ═════════════════════════════════════════════════════════════════════
#  SERVO DATA HELPERS
# ═════════════════════════════════════════════════════════════════════

def request_servo_stream(mav):
    """Request SERVO_OUTPUT_RAW at 10Hz."""
    print("  Requesting SERVO_OUTPUT_RAW stream at 10Hz...")
    mav.mav.request_data_stream_send(
        mav.target_system,
        mav.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS,
        10, 1)
    msg = mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=True, timeout=5)
    if msg:
        print(f"  Stream active: Ch1={msg.servo1_raw} Ch2={msg.servo2_raw} "
              f"Ch3={msg.servo3_raw} Ch4={msg.servo4_raw}")
    else:
        print("  WARNING: No SERVO_OUTPUT_RAW received!")


def flush_servo_messages(mav):
    """Drain any queued SERVO_OUTPUT_RAW messages."""
    count = 0
    while mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=False):
        count += 1
    return count


def capture_servo_during_command(mav, nh, x, y, z, r, duration):
    """
    Send a command via NeutralHold and capture SERVO_OUTPUT_RAW.
    Returns list of sample dicts.
    """
    flush_servo_messages(mav)
    nh.cmd(x=x, y=y, z=z, r=r)

    samples = []
    deadline = time.time() + duration
    while time.time() < deadline:
        msg = mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=True, timeout=0.2)
        if msg:
            samples.append({
                'time': time.time(),
                'ch1': msg.servo1_raw,
                'ch2': msg.servo2_raw,
                'ch3': msg.servo3_raw,
                'ch4': msg.servo4_raw,
            })

    nh.neutral()
    return samples


# ═════════════════════════════════════════════════════════════════════
#  PRE-FLIGHT MOTOR CHECK
# ═════════════════════════════════════════════════════════════════════

def preflight_motor_check(mav, nh):
    """
    Send a brief forward command and verify PWM deviations exceed
    the ESC deadband. Returns True if motors should spin.
    """
    print("\n  ┌────────────────────────────────────────────────┐")
    print("  │ PRE-FLIGHT CHECK: Verifying ESC deadband       │")
    print("  │ Sending FORWARD at thrust=250 for 1 second...  │")
    print("  └────────────────────────────────────────────────┘")

    # Capture neutral baseline first
    flush_servo_messages(mav)
    nh.neutral()
    time.sleep(0.5)
    baseline = mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=True, timeout=2)
    if baseline:
        print(f"  Neutral baseline: Ch1={baseline.servo1_raw} Ch2={baseline.servo2_raw} "
              f"Ch3={baseline.servo3_raw} Ch4={baseline.servo4_raw}")
    else:
        print(f"  WARNING: No baseline — continuing anyway")

    # Send forward pulse
    samples = capture_servo_during_command(
        mav, nh, x=THRUST_VALUE, y=0, z=500, r=0, duration=1.0)

    if not samples:
        print("  ERROR: No servo samples captured during pre-flight!")
        return False

    # Check deviations
    max_dev = 0
    print(f"\n  Pre-flight results ({len(samples)} samples):")
    for i in range(1, 5):
        ch_key = f'ch{i}'
        values = [s[ch_key] for s in samples]
        avg = sum(values) / len(values)
        dev = abs(avg - PWM_NEUTRAL)
        max_dev = max(max_dev, dev)
        above_db = "YES - WILL SPIN" if dev > PWM_DEADBAND else "NO  - IN DEADBAND"
        print(f"    Ch{i} {MOTOR_MAP[i]:<12s}: avg={avg:7.1f}  dev={dev:+6.1f}  "
              f"above deadband({PWM_DEADBAND}): {above_db}")

    if max_dev > PWM_DEADBAND:
        print(f"\n  PRE-FLIGHT PASSED: Max deviation = {max_dev:.1f} "
              f"(deadband = {PWM_DEADBAND})")
        print(f"  Motors SHOULD physically spin during tests.")
        return True
    else:
        print(f"\n  PRE-FLIGHT FAILED: Max deviation = {max_dev:.1f} "
              f"(deadband = {PWM_DEADBAND})")
        print(f"  Motors will NOT spin! Thrust value needs to be higher.")
        print(f"  Current THRUST_VALUE = {THRUST_VALUE}")
        print(f"  Try increasing to {THRUST_VALUE * 2} and re-run.")
        return False


# ═════════════════════════════════════════════════════════════════════
#  ANALYSIS
# ═════════════════════════════════════════════════════════════════════

def analyze_samples(test_name, x, y, z, r, samples):
    """Analyze captured servo data and produce a diagnostic block."""
    if not samples:
        print(f"  WARNING: No SERVO_OUTPUT_RAW samples for {test_name}!")
        return None

    avg = {}
    for ch in ['ch1', 'ch2', 'ch3', 'ch4']:
        values = [s[ch] for s in samples]
        avg[ch] = sum(values) / len(values)

    dev = {}
    for ch in ['ch1', 'ch2', 'ch3', 'ch4']:
        dev[ch] = avg[ch] - PWM_NEUTRAL

    def dir_label(d):
        if d > 5:
            return f"UP   (+{d:5.1f})"
        elif d < -5:
            return f"DOWN ({d:6.1f})"
        else:
            return f"IDLE ({d:+5.1f})"

    def dir_code(d):
        if d > 5:
            return "UP"
        elif d < -5:
            return "DN"
        else:
            return "--"

    def spin_status(d):
        """Will the ESC actually spin at this deviation?"""
        if abs(d) > PWM_DEADBAND:
            return "SPINNING"
        elif abs(d) > 5:
            return "DEADBAND"
        else:
            return "IDLE"

    result = {
        'test': test_name,
        'command': f"x={x:+5d}, y={y:+5d}, z={z:4d}, r={r:+5d}",
        'samples': len(samples),
        'channels': {},
    }

    print(f"\n  +{'='*71}+")
    print(f"  | TEST: {test_name:<64s}|")
    print(f"  | Command: x={x:+5d}, y={y:+5d}, z={z:4d}, r={r:+5d}"
          f"{'':>30s}|")
    print(f"  | Samples: {len(samples):<61d}|")
    print(f"  +{'-'*71}+")
    print(f"  | {'Channel':<15s} | {'PWM':>7s} | {'Delta':>7s} | "
          f"{'Direction':<10s} | {'ESC Status':<12s} |")
    print(f"  +{'-'*71}+")

    for i in range(1, 5):
        ch_key = f'ch{i}'
        a = avg[ch_key]
        d = dev[ch_key]
        dl = dir_label(d)
        dc = dir_code(d)
        ss = spin_status(d)
        motor_label = MOTOR_MAP[i]
        print(f"  | Ch{i} {motor_label:<10s} | {a:7.1f} | {d:+7.1f} | "
              f"{dc:<10s} | {ss:<12s} |")
        result['channels'][ch_key] = {
            'motor': motor_label,
            'avg_pwm': round(a, 1),
            'deviation': round(d, 1),
            'dir_code': dc,
            'spinning': ss == "SPINNING",
        }

    print(f"  +{'='*71}+")
    return result


# ═════════════════════════════════════════════════════════════════════
#  RUN SINGLE TEST
# ═════════════════════════════════════════════════════════════════════

def run_single_test(mav, nh, test_name, x, y, z, r):
    """Run one axis test: settle, command, capture, analyze."""
    print(f"\n{'='*65}")
    print(f"  PREPARING: {test_name}")
    print(f"  Command: x={x:+5d}, y={y:+5d}, z={z:4d}, r={r:+5d}")
    thrust_pct = abs(max(abs(x), abs(y), abs(r))) / 10
    print(f"  Thrust: {thrust_pct:.1f}% for {PULSE_DURATION}s")
    print(f"{'='*65}")

    # Settle at neutral
    print(f"  Settling at neutral for {SETTLE_SECS}s...")
    nh.neutral()
    time.sleep(SETTLE_SECS)

    # Capture neutral baseline
    flush_servo_messages(mav)
    time.sleep(0.3)
    baseline_msg = mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=True, timeout=2)
    if baseline_msg:
        print(f"  Baseline: Ch1={baseline_msg.servo1_raw} Ch2={baseline_msg.servo2_raw} "
              f"Ch3={baseline_msg.servo3_raw} Ch4={baseline_msg.servo4_raw}")

    # Run command and capture
    print(f"  SENDING {test_name} for {PULSE_DURATION}s...")
    samples = capture_servo_during_command(mav, nh, x, y, z, r, PULSE_DURATION)
    print(f"  Done. Captured {len(samples)} samples.")

    # Analyze
    result = analyze_samples(test_name, x, y, z, r, samples)
    return result


# ═════════════════════════════════════════════════════════════════════
#  FINAL SUMMARY
# ═════════════════════════════════════════════════════════════════════

def print_final_summary(results):
    """Print a complete, copy-paste-friendly diagnostic summary."""
    valid = [r for r in results if r is not None]
    if not valid:
        print("\n  ERROR: No valid test results to summarize!")
        return

    # Count how many motors actually spun
    total_spins = 0
    total_expected = 0
    for r in valid:
        for ch_key in ['ch1', 'ch2', 'ch3', 'ch4']:
            ch = r['channels'][ch_key]
            if abs(ch['deviation']) > 5:  # was supposed to move
                total_expected += 1
                if ch['spinning']:
                    total_spins += 1

    print("\n")
    print("=" * 75)
    print("  MIXING MATRIX DIAGNOSTIC SUMMARY")
    print("  Frame Config: 1 (SimpleROV-3/Vectored)")
    print(f"  Thrust level: {THRUST_VALUE}/1000 ({THRUST_VALUE/10:.1f}%)")
    print(f"  Pulse duration: {PULSE_DURATION}s per test")
    print(f"  ESC deadband threshold: ±{PWM_DEADBAND} from {PWM_NEUTRAL}")
    print(f"  Motor layout: Ch1=BR(CCW) Ch2=BL(CW) Ch3=FR(CW) Ch4=FL(CCW)")
    print(f"  Motors physically spinning: {total_spins}/{total_expected} expected responses")
    print("=" * 75)

    # ── RAW RESULTS TABLE ──
    print(f"\n  {'Test':<16s} | {'Ch1 BR':>11s} | {'Ch2 BL':>11s} | "
          f"{'Ch3 FR':>11s} | {'Ch4 FL':>11s} | {'N':>3s} | Spinning?")
    print(f"  {'-'*16}-+-{'-'*11}-+-{'-'*11}-+-{'-'*11}-+-{'-'*11}-+-"
          f"{'-'*3}-+-{'-'*10}")

    for r in valid:
        ch = r['channels']

        def fmt(ch_key):
            d = ch[ch_key]['deviation']
            if d > 5:
                return f"+{d:5.1f} UP"
            elif d < -5:
                return f"{d:6.1f} DN"
            else:
                return f"{d:+5.1f} --"

        spinning_count = sum(1 for k in ['ch1','ch2','ch3','ch4']
                           if ch[k]['spinning'])

        print(f"  {r['test']:<16s} | {fmt('ch1'):>11s} | {fmt('ch2'):>11s} | "
              f"{fmt('ch3'):>11s} | {fmt('ch4'):>11s} | {r['samples']:>3d} | "
              f"{spinning_count}/4 motors")

    # ── EXPECTED TABLE ──
    print(f"\n  EXPECTED (from firmware mixing matrix):")
    print(f"  {'Test':<16s} | {'Ch1 BR':>8s} | {'Ch2 BL':>8s} | "
          f"{'Ch3 FR':>8s} | {'Ch4 FL':>8s}")
    print(f"  {'-'*16}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}-+-{'-'*8}")
    expected_display = [
        ("FORWARD",      "DOWN", "DOWN", "UP",   "UP"),
        ("BACKWARD",     "UP",   "UP",   "DOWN", "DOWN"),
        ("STRAFE RIGHT", "UP",   "DOWN", "UP",   "DOWN"),
        ("STRAFE LEFT",  "DOWN", "UP",   "DOWN", "UP"),
        ("YAW CW",       "UP",   "DOWN", "DOWN", "UP"),
        ("YAW CCW",      "DOWN", "UP",   "UP",   "DOWN"),
    ]
    for name, e1, e2, e3, e4 in expected_display:
        print(f"  {name:<16s} | {e1:>8s} | {e2:>8s} | {e3:>8s} | {e4:>8s}")

    # ── MATCH ANALYSIS ──
    print(f"\n  ACTUAL vs EXPECTED DIRECTION MATCH:")
    print(f"  {'Test':<16s} | {'Ch1':>5s} | {'Ch2':>5s} | {'Ch3':>5s} | "
          f"{'Ch4':>5s} | {'Verdict':<10s}")
    print(f"  {'-'*16}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*10}")

    all_match = True
    for r in valid:
        test = r['test']
        if test not in EXPECTED_DIRS:
            continue
        exp = EXPECTED_DIRS[test]
        ch = r['channels']

        matches = {}
        for ch_key in ['ch1', 'ch2', 'ch3', 'ch4']:
            actual_dc = ch[ch_key]['dir_code']
            expected_dc = exp[ch_key]
            if actual_dc == '--':
                matches[ch_key] = '?'
            elif actual_dc == expected_dc:
                matches[ch_key] = 'YES'
            else:
                matches[ch_key] = 'NO'
                all_match = False

        all_yes = all(v == 'YES' for v in matches.values())
        verdict = "MATCH" if all_yes else "MISMATCH"
        if any(v == '?' for v in matches.values()):
            verdict = "PARTIAL"

        print(f"  {test:<16s} | {matches['ch1']:>5s} | {matches['ch2']:>5s} | "
              f"{matches['ch3']:>5s} | {matches['ch4']:>5s} | {verdict:<10s}")

    print(f"  {'-'*16}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*5}-+-{'-'*10}")

    # ── PHYSICAL OBSERVATION SECTION ──
    print(f"""
  PHYSICAL OBSERVATION CHECKLIST:
  ═══════════════════════════════════════════════════════════════════
  For each test, answer these questions:

  FORWARD test:
    [ ] Did motors spin?  YES / NO
    [ ] Front motors (Ch3 FR, Ch4 FL): air blew _______ (inward/outward)
    [ ] Rear motors  (Ch1 BR, Ch2 BL): air blew _______ (inward/outward)
    [ ] If free to move, ROV would go: FORWARD / BACKWARD / UNSURE

  STRAFE RIGHT test:
    [ ] Did motors spin?  YES / NO
    [ ] Right motors (Ch1 BR, Ch3 FR): air blew _______ (inward/outward)
    [ ] Left motors  (Ch2 BL, Ch4 FL): air blew _______ (inward/outward)
    [ ] If free to move, ROV would go: RIGHT / LEFT / UNSURE

  YAW CW test:
    [ ] Did motors spin?  YES / NO
    [ ] ROV body would rotate: CW / CCW / UNSURE
  ═══════════════════════════════════════════════════════════════════""")

    # ── VERDICT ──
    if total_spins == 0:
        print(f"""
  >>> WARNING: NO MOTORS PHYSICALLY SPUN <<<
  PWM deviations did not exceed ESC deadband ({PWM_DEADBAND}).
  Current max deviation: check table above.
  
  FIX: Increase THRUST_VALUE in the script.
  Current value: {THRUST_VALUE} → Try: {min(THRUST_VALUE * 2, 500)}
  Then re-run this test.""")
    elif all_match and total_spins == total_expected:
        print(f"""
  >>> ALL ELECTRONIC MATCHES + ALL MOTORS SPINNING <<<
  The mixing matrix is electronically correct AND motors are responding.
  
  NOW: Use your physical observations above to determine if
  the thrust DIRECTION is correct for mesh-inward mounting.
  
  Paste this entire summary + observations into your chat.""")
    elif all_match:
        print(f"""
  >>> ELECTRONIC MATCH but only {total_spins}/{total_expected} motor responses <<<
  Mixing directions are correct but some motors may be in deadband.
  Physical observations for spinning motors are still valid.
  
  Paste this entire summary + observations into your chat.""")
    else:
        print(f"""
  >>> MISMATCHES DETECTED <<<
  Some channels responded in unexpected directions.
  Paste this entire summary into your chat for diagnosis.""")

    print("\n" + "=" * 75)
    print("  END OF DIAGNOSTIC REPORT")
    print("  Copy from 'MIXING MATRIX DIAGNOSTIC SUMMARY' to here.")
    print("=" * 75)


# ═════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 65)
    print("  BLUEROV2 MIXING MATRIX DIAGNOSTIC TEST (v2)")
    print("=" * 65)
    print(f"""
  This script tests each movement axis one at a time and
  captures the actual PWM output to each motor channel.

  Tests:  FORWARD, BACKWARD, STRAFE L/R, YAW CW/CCW
  Thrust: {THRUST_VALUE}/1000 ({THRUST_VALUE/10:.1f}%)
  Pulse:  {PULSE_DURATION}s per test, {SETTLE_SECS}s settle between
  Total:  ~{len(TEST_SEQUENCE) * (PULSE_DURATION + SETTLE_SECS):.0f}s of motor activity

  v2 FIX: Thrust increased from 70 to {THRUST_VALUE} to clear ESC deadband.
  Previous run showed ±14 PWM deviation — not enough to spin.
  At {THRUST_VALUE}/1000 we expect ~±{THRUST_VALUE * 400 // 1000} PWM deviation.

  Motor layout (verified):
       FRONT
    Ch4(FL,CCW)   Ch3(FR,CW)
          [ROV]
    Ch2(BL,CW)    Ch1(BR,CCW)
       BACK

  IMPORTANT: Watch/feel each test carefully!
  Note which direction air moves for each command.
  PROPS MUST BE REMOVED FOR BENCH TESTING!
""")

    confirm = input("  Type YES to proceed: ").strip().upper()
    if confirm != "YES":
        print("  Aborted.")
        sys.exit(0)

    mav = None
    nh = None

    try:
        # Phase 1: Connect
        mav = connect()

        # Phase 2: Start neutral hold
        nh = NeutralHold(mav)
        nh.start()
        print("  Neutral hold thread started (10Hz).")
        time.sleep(1)

        # Phase 3: Request servo stream
        request_servo_stream(mav)

        # Phase 4: Arm
        print("\n  Arming vehicle...")
        if not arm_vehicle(mav):
            print("  FAILED to arm! Exiting.")
            nh.stop()
            sys.exit(1)

        time.sleep(2)
        print("  Armed and ready.\n")

        # Phase 5: Pre-flight motor check
        preflight_ok = preflight_motor_check(mav, nh)

        if not preflight_ok:
            print("\n  Pre-flight check FAILED — motors won't spin at this thrust.")
            choice = input("  Continue anyway for data? (YES/NO): ").strip().upper()
            if choice != "YES":
                print("  Aborting. Disarming...")
                disarm_vehicle(mav)
                nh.stop()
                sys.exit(0)
            print("  Continuing with data capture only...")
        else:
            print("\n  Pre-flight PASSED — motors should spin!")

        # Phase 6: Safety confirmation
        print("\n  " + "!" * 52)
        print("  ! MOTORS WILL SPIN DURING THE NEXT PHASE          !")
        print("  ! Ensure props are removed and area is clear       !")
        print("  " + "!" * 52)
        confirm2 = input("\n  Type GO to begin tests (Ctrl+C to abort): ").strip().upper()
        if confirm2 != "GO":
            print("  Aborted. Disarming...")
            disarm_vehicle(mav)
            nh.stop()
            sys.exit(0)

        # Phase 7: Run all tests
        print(f"\n  Running {len(TEST_SEQUENCE)} tests...\n")
        results = []
        for i, (test_name, x, y, z, r) in enumerate(TEST_SEQUENCE, 1):
            print(f"\n  --- Test {i}/{len(TEST_SEQUENCE)} ---")
            result = run_single_test(mav, nh, test_name, x, y, z, r)
            results.append(result)

        # Phase 8: Settle and disarm
        print(f"\n  All tests complete. Settling at neutral...")
        nh.neutral()
        time.sleep(2)

        print("  Disarming...")
        disarm_vehicle(mav)
        nh.stop()
        print("  Disarmed.\n")

        # Phase 9: Print summary
        print_final_summary(results)

    except KeyboardInterrupt:
        print("\n\n  [E-STOP] Ctrl+C detected!")
        print("  Sending neutral and disarming...")
        try:
            if nh:
                nh.neutral()
                time.sleep(0.5)
            if mav:
                disarm_vehicle(mav)
            if nh:
                nh.stop()
        except Exception:
            pass
        print("  Emergency stop complete.")

    except Exception as e:
        print(f"\n  [ERROR] {e}")
        import traceback
        traceback.print_exc()
        try:
            if nh:
                nh.neutral()
                time.sleep(0.5)
            if mav:
                disarm_vehicle(mav)
            if nh:
                nh.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()