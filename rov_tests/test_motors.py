#!/usr/bin/env python3
"""
thrust_direction_test.py

Your wiring is CONFIRMED CORRECT from QGC:
  Port 1 = BR, Port 2 = BL, Port 3 = FR, Port 4 = FL

This script tests what ACTUALLY HAPPENS when we send
FORWARD, BACKWARD, STRAFE, YAW commands.

Instead of comparing UP/DN to a table, we look at the
PHYSICS: which direction would the thrust go?

For each motor, we need to know:
  - Its position (BR/BL/FR/FL) — KNOWN from QGC
  - Its prop type (CW/CCW) — from your documentation
  - Its direction flag — read from params
  - Its PWM deviation — measured

Then we calculate whether the ROV would actually move correctly.
"""

from pymavlink import mavutil
import time
import threading

# ─── CONFIG ─────────────────────────────────────────────────────────
MAV_PORT      = 14550
SOURCE_SYSTEM = 255
THRUST        = 300
HOLD_SECS     = 2.0
SETTLE_SECS   = 2.0
PWM_NEUTRAL   = 1500
DEADBAND      = 25
# ────────────────────────────────────────────────────────────────────

# YOUR CONFIRMED WIRING (from QGC slider test):
# Port 1 = BR (Back-Right)   — CW prop
# Port 2 = BL (Back-Left)    — CW prop  
# Port 3 = FR (Front-Right)  — CCW prop
# Port 4 = FL (Front-Left)   — CCW prop

# FRAME_CONFIG=1 internal mixing matrix:
#              fwd   lat   yaw
# Port 1 (BR): -1    +1    +1
# Port 2 (BL): -1    -1    -1
# Port 3 (FR): +1    +1    -1
# Port 4 (FL): +1    -1    +1

AXIS_COMMANDS = [
    ("FORWARD  (+X)",  THRUST,  0,       500, 0),
    ("BACKWARD (-X)", -THRUST,  0,       500, 0),
    ("STRAFE_R (+Y)",  0,       THRUST,  500, 0),
    ("STRAFE_L (-Y)",  0,      -THRUST,  500, 0),
    ("YAW_CW   (+R)",  0,       0,       500, THRUST),
    ("YAW_CCW  (-R)",  0,       0,       500, -THRUST),
]


class NeutralHold:
    def __init__(self, mav):
        self._mav = mav
        self._lock = threading.Lock()
        self._x = 0; self._y = 0; self._z = 500; self._r = 0
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def set(self, x=0, y=0, z=500, r=0):
        with self._lock:
            self._x = max(-600, min(600, int(x)))
            self._y = max(-600, min(600, int(y)))
            self._z = max(0, min(1000, int(z)))
            self._r = max(-600, min(600, int(r)))

    def neutral(self):
        self.set()

    def _loop(self):
        while self._running:
            with self._lock:
                x, y, z, r = self._x, self._y, self._z, self._r
            self._mav.mav.manual_control_send(
                self._mav.target_system, x, y, z, r, 0)
            time.sleep(0.1)


def connect():
    print(f"\n[CONNECT] udp:0.0.0.0:{MAV_PORT}")
    mav = mavutil.mavlink_connection(
        f'udp:0.0.0.0:{MAV_PORT}', source_system=SOURCE_SYSTEM)
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

    print(f"  Locked: sys={mav.target_system}, comp={mav.target_component}")
    return mav


def read_param(mav, name, timeout=5):
    mav.mav.param_request_read_send(
        mav.target_system, mav.target_component, name.encode('utf-8'), -1)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = mav.recv_match(type='PARAM_VALUE', blocking=True, timeout=2)
        if msg and msg.param_id.replace('\x00', '') == name:
            return msg.param_value
    return None


def set_param(mav, name, value):
    mav.mav.param_set_send(
        mav.target_system, mav.target_component,
        name.encode('utf-8'), float(value),
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
    deadline = time.time() + 5
    while time.time() < deadline:
        msg = mav.recv_match(type='PARAM_VALUE', blocking=True, timeout=2)
        if msg and msg.param_id.replace('\x00', '') == name:
            if abs(msg.param_value - float(value)) < 0.01:
                return True
    return False


def arm(mav, retries=3):
    mode_id = mav.mode_mapping().get('MANUAL')
    for attempt in range(1, retries + 1):
        print(f"  ARM attempt {attempt}/{retries}...")
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
            time.sleep(2)
            continue
        time.sleep(2)
        for _ in range(5):
            hb = mav.recv_match(type='HEARTBEAT', blocking=True, timeout=2)
            if hb and bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
                print(f"  Armed on attempt {attempt}")
                return True
        time.sleep(2)
    print(f"  Failed to arm!")
    return False


def disarm(mav):
    mav.mav.command_long_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0, 0, 21196, 0, 0, 0, 0, 0)
    time.sleep(1)
    print(f"  Disarmed.")


def flush_servo(mav):
    while mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=False):
        pass


def capture_servos(mav, duration=2.0):
    flush_servo(mav)
    samples = []
    deadline = time.time() + duration
    while time.time() < deadline:
        msg = mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=True, timeout=0.3)
        if msg:
            samples.append([msg.servo1_raw, msg.servo2_raw,
                           msg.servo3_raw, msg.servo4_raw])
    return samples


def main():
    print(f"\n{'#'*65}")
    print(f"  THRUST DIRECTION TEST")
    print(f"  Wiring CONFIRMED from QGC:")
    print(f"    Port 1=BR  Port 2=BL  Port 3=FR  Port 4=FL")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*65}")

    mav = None
    nh = None

    try:
        mav = connect()

        # ── Read current directions ──
        print(f"\n{'='*65}")
        print(f"  CURRENT MOTOR DIRECTIONS")
        print(f"{'='*65}")

        dirs = {}
        for i in range(1, 5):
            val = read_param(mav, f'MOT_{i}_DIRECTION')
            dirs[i] = int(val) if val is not None else None
            d = dirs[i]
            if d is not None:
                print(f"  MOT_{i}_DIRECTION = {d:+d} ({'REVERSED' if d == -1 else 'NORMAL'})")
            else:
                print(f"  MOT_{i}_DIRECTION = could not read!")

        # ── Run mixing test ──
        print(f"\n{'='*65}")
        print(f"  MIXING MATRIX CAPTURE")
        print(f"{'='*65}")
        print(f"  ⚠️  NO PROPS!")

        confirm = input(f"\n  Type GO: ").strip().upper()
        if confirm != "GO":
            return

        nh = NeutralHold(mav)
        nh.start()
        time.sleep(1)

        if not arm(mav):
            nh.stop()
            return

        time.sleep(2)

        # Request servo stream
        mav.mav.request_data_stream_send(
            mav.target_system, mav.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS, 10, 1)
        mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=True, timeout=5)

        # Baseline
        nh.neutral()
        time.sleep(1.5)
        flush_servo(mav)
        time.sleep(0.3)
        bl_msg = mav.recv_match(type='SERVO_OUTPUT_RAW', blocking=True, timeout=2)
        if bl_msg:
            print(f"\n  Baseline: {bl_msg.servo1_raw} {bl_msg.servo2_raw} "
                  f"{bl_msg.servo3_raw} {bl_msg.servo4_raw}")

        # Capture all axes
        print(f"\n  {'Axis':<19s} | {'Port1':>7s} | {'Port2':>7s} | {'Port3':>7s} | {'Port4':>7s}")
        print(f"  {'':19s} | {'(BR)':>7s} | {'(BL)':>7s} | {'(FR)':>7s} | {'(FL)':>7s}")
        print(f"  {'-'*19}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}-+-{'-'*7}")

        all_devs = {}

        for name, x, y, z, r in AXIS_COMMANDS:
            nh.neutral()
            time.sleep(SETTLE_SECS)
            flush_servo(mav)

            nh.set(x=x, y=y, z=z, r=r)
            time.sleep(0.5)
            flush_servo(mav)
            samples = capture_servos(mav, HOLD_SECS)
            nh.neutral()

            if not samples:
                print(f"  {name:<19s} | NO DATA")
                continue

            devs = []
            for ch in range(4):
                vals = [s[ch] for s in samples]
                avg = sum(vals) / len(vals)
                devs.append(avg - PWM_NEUTRAL)

            all_devs[name] = devs

            parts = []
            for d in devs:
                if d > DEADBAND:
                    parts.append(f"{d:+5.0f} ↑")
                elif d < -DEADBAND:
                    parts.append(f"{d:+5.0f} ↓")
                else:
                    parts.append(f"   0  ·")

            print(f"  {name:<19s} | {parts[0]:>7s} | {parts[1]:>7s} | "
                  f"{parts[2]:>7s} | {parts[3]:>7s}")

        # Disarm
        nh.neutral()
        time.sleep(1)
        disarm(mav)
        nh.stop()
        nh = None

        # ── PHYSICS ANALYSIS ──
        print(f"\n{'='*65}")
        print(f"  PHYSICS ANALYSIS")
        print(f"{'='*65}")

        # The FRAME_CONFIG=1 mixing matrix:
        # mixing[port] = (fwd_coeff, lat_coeff, yaw_coeff)
        mixing = {
            1: (-1, +1, +1),  # BR
            2: (-1, -1, -1),  # BL
            3: (+1, +1, -1),  # FR
            4: (+1, -1, +1),  # FL
        }

        print(f"\n  FRAME_CONFIG=1 mixing matrix:")
        print(f"  {'Port':<8s} | {'Pos':<4s} | {'Fwd':>4s} | {'Lat':>4s} | {'Yaw':>4s} | {'DIR':>4s}")
        print(f"  {'-'*8}-+-{'-'*4}-+-{'-'*4}-+-{'-'*4}-+-{'-'*4}-+-{'-'*4}")
        pos_names = {1: 'BR', 2: 'BL', 3: 'FR', 4: 'FL'}
        for p in range(1, 5):
            f, l, y = mixing[p]
            d = dirs.get(p, '?')
            print(f"  Port {p}  | {pos_names[p]:<4s} | {f:+4d} | {l:+4d} | {y:+4d} | {d:+4d}" if isinstance(d, int) else
                  f"  Port {p}  | {pos_names[p]:<4s} | {f:+4d} | {l:+4d} | {y:+4d} |    ?")

        print(f"\n  How the firmware computes PWM for each port:")
        print(f"  PWM = 1500 + (command_value × mixing_coeff × direction_flag)")
        print(f"  If result < 1500 → motor can't go below idle → stays at 1500")

        # For FORWARD (x=+300):
        print(f"\n  ── FORWARD (x=+{THRUST}) breakdown ──")
        fwd_devs = all_devs.get("FORWARD  (+X)")
        if fwd_devs:
            for p in range(1, 5):
                fwd_coeff = mixing[p][0]
                d = dirs.get(p, 1)
                expected_raw = THRUST/1000.0 * fwd_coeff * d
                expected_pwm_delta = expected_raw * 400  # rough scaling
                actual = fwd_devs[p-1]
                
                sign_str = "speeds up" if expected_raw > 0 else "slows down" if expected_raw < 0 else "unchanged"
                print(f"    Port {p} ({pos_names[p]}): coeff={fwd_coeff:+d} × dir={d:+d} = {fwd_coeff*d:+d} → {sign_str}")
                print(f"      Expected effect: {'increase' if fwd_coeff*d > 0 else 'decrease'} from 1500")
                print(f"      Actual PWM dev:  {actual:+.1f} {'(motor responding)' if abs(actual) > DEADBAND else '(idle — clipped at neutral)'}")

        # Check if the pattern makes sense
        print(f"\n  ── INTERPRETATION ──")
        
        if fwd_devs:
            # With current dirs, what does forward produce?
            # Port 1 (BR): fwd=-1, dir=dirs[1] → effective = -1 * dirs[1]
            # Port 2 (BL): fwd=-1, dir=dirs[2] → effective = -1 * dirs[2]  
            # Port 3 (FR): fwd=+1, dir=dirs[3] → effective = +1 * dirs[3]
            # Port 4 (FL): fwd=+1, dir=dirs[4] → effective = +1 * dirs[4]
            
            effective = {}
            for p in range(1, 5):
                d = dirs.get(p, 1)
                effective[p] = {
                    'fwd': mixing[p][0] * d,
                    'lat': mixing[p][1] * d,
                    'yaw': mixing[p][2] * d,
                }
            
            print(f"\n  Effective mixing (after direction flags applied):")
            print(f"  {'Port':<8s} | {'Pos':<4s} | {'Fwd':>4s} | {'Lat':>4s} | {'Yaw':>4s}")
            print(f"  {'-'*8}-+-{'-'*4}-+-{'-'*4}-+-{'-'*4}-+-{'-'*4}")
            for p in range(1, 5):
                e = effective[p]
                print(f"  Port {p}  | {pos_names[p]:<4s} | {e['fwd']:+4d} | {e['lat']:+4d} | {e['yaw']:+4d}")
            
            # For a vectored X-frame to go FORWARD:
            # - Rear motors (BR, BL) should push forward → need positive effective fwd
            # - Front motors (FR, FL) should also contribute forward
            # Actually for differential thrust:
            # - ALL motors with positive effective fwd push forward
            # - The net force should be in the forward direction
            
            # Let's just check: do rear ports speed up or slow down?
            rear_fwd = [effective[1]['fwd'], effective[2]['fwd']]
            front_fwd = [effective[3]['fwd'], effective[4]['fwd']]
            
            print(f"\n  For FORWARD command:")
            print(f"    Rear  (BR,BL) effective fwd coefficients: {rear_fwd}")
            print(f"    Front (FR,FL) effective fwd coefficients: {front_fwd}")
            
            # In the vectored frame:
            # Thrusters point inward at 45°
            # For net FORWARD thrust:
            # All 4 thrusters should produce forward component
            # BR pushes forward-left, BL pushes forward-right (they're angled)
            # FR pushes forward-right, FL pushes forward-left
            # 
            # When PWM > 1500: thrust in the "positive" direction of the motor
            # When PWM < 1500: thrust in the "negative" direction
            #
            # The mixing matrix with positive fwd coefficient means:
            # positive command → increase PWM → more forward thrust from that motor
            
            rear_correct = all(r > 0 for r in rear_fwd)
            front_correct = all(f > 0 for f in front_fwd)

            if rear_correct and front_correct:
                print(f"    → All positive: all motors push forward ✓")
                print(f"    → But some show 0 deviation → they may be clipped")
                print(f"       (firmware can't go above max output at 30% input)")
            elif not rear_correct and not front_correct:
                print(f"    → All negative: all motors push BACKWARD for forward command!")
                print(f"    → Direction flags are ALL WRONG")
                print(f"    → Need to flip all 4 direction flags")
            else:
                print(f"    → Mixed: some motors forward, some backward")
                print(f"    → This would cause rotation instead of translation")

        # Try all 16 direction flag combinations
        print(f"\n{'='*65}")
        print(f"  BRUTE FORCE: Testing all direction flag combinations")
        print(f"{'='*65}")
        print(f"  Checking which combination of direction flags would")
        print(f"  make ALL 6 axes produce correct thrust patterns...")
        print(f"")

        # For each axis, we know the actual PWM deviations
        # The deviation should match: command × mixing_coeff × dir_flag
        # But we only see the SIGN (positive or zero/negative)
        
        # A deviation of 0 means the computed value was negative (clipped)
        # A positive deviation means the computed value was positive
        # A negative deviation means... shouldn't happen if neutral is 1500
        
        # Actually, deviation CAN be negative — it means PWM < 1500
        # Which means the motor is being commanded in reverse
        
        # For MANUAL_CONTROL, the firmware computes:
        # output[port] = sum(command[axis] * mixing[port][axis]) for all axes
        # Then applies direction flag
        # Then maps to PWM range
        
        # Let's just try all 16 combos and see which one makes
        # the predicted signs match the actual signs
        
        best_combo = None
        best_score = -1
        
        for d1 in [-1, 1]:
            for d2 in [-1, 1]:
                for d3 in [-1, 1]:
                    for d4 in [-1, 1]:
                        test_dirs = {1: d1, 2: d2, 3: d3, 4: d4}
                        score = 0
                        total_checks = 0
                        
                        for name, cmd_x, cmd_y, cmd_z, cmd_r in AXIS_COMMANDS:
                            if name not in all_devs:
                                continue
                            actual = all_devs[name]
                            
                            for p in range(1, 5):
                                # Compute expected sign
                                fwd_c, lat_c, yaw_c = mixing[p]
                                d = test_dirs[p]
                                
                                # The actual computation in firmware (simplified):
                                # output = (cmd_x/1000 * fwd_c + cmd_y/1000 * lat_c + cmd_r/1000 * yaw_c) * d
                                raw = (cmd_x/1000.0 * fwd_c + 
                                       cmd_y/1000.0 * lat_c + 
                                       cmd_r/1000.0 * yaw_c) * d
                                
                                # Predicted: positive raw → PWM above 1500
                                #            negative raw → PWM stays at 1500 (clipped) or goes below
                                #            zero raw → PWM at 1500
                                
                                actual_dev = actual[p-1]
                                
                                total_checks += 1
                                
                                # Match criteria:
                                if raw > 0.01 and actual_dev > DEADBAND:
                                    score += 1  # both positive
                                elif raw < -0.01 and actual_dev < -DEADBAND:
                                    score += 1  # both negative
                                elif raw < -0.01 and abs(actual_dev) <= DEADBAND:
                                    score += 1  # predicted negative, actual clipped to neutral
                                elif abs(raw) <= 0.01 and abs(actual_dev) <= DEADBAND:
                                    score += 1  # both zero
                                # else: mismatch
                        
                        if score > best_score:
                            best_score = score
                            best_combo = test_dirs.copy()
        
        print(f"  Best matching direction flags (score {best_score}/{total_checks}):")
        print(f"    MOT_1_DIRECTION = {best_combo[1]:+d} ({'REVERSED' if best_combo[1]==-1 else 'NORMAL'})")
        print(f"    MOT_2_DIRECTION = {best_combo[2]:+d} ({'REVERSED' if best_combo[2]==-1 else 'NORMAL'})")
        print(f"    MOT_3_DIRECTION = {best_combo[3]:+d} ({'REVERSED' if best_combo[3]==-1 else 'NORMAL'})")
        print(f"    MOT_4_DIRECTION = {best_combo[4]:+d} ({'REVERSED' if best_combo[4]==-1 else 'NORMAL'})")
        
        current_match = (best_combo[1] == dirs.get(1) and best_combo[2] == dirs.get(2) and
                        best_combo[3] == dirs.get(3) and best_combo[4] == dirs.get(4))
        
        if current_match:
            print(f"\n  These are your CURRENT flags — they're already optimal!")
            print(f"  The mixing matrix test comparison table was WRONG.")
            print(f"  Your ROV should actually work correctly as-is.")
        else:
            print(f"\n  Your current flags are DIFFERENT from optimal.")
            print(f"  Current:  {dirs.get(1,0):+d}  {dirs.get(2,0):+d}  {dirs.get(3,0):+d}  {dirs.get(4,0):+d}")
            print(f"  Optimal:  {best_combo[1]:+d}  {best_combo[2]:+d}  {best_combo[3]:+d}  {best_combo[4]:+d}")
            
            print(f"\n  Want to apply the optimal flags now?")
            apply = input(f"  Type APPLY to set them (or SKIP): ").strip().upper()
            
            if apply == "APPLY":
                for i in range(1, 5):
                    param = f'MOT_{i}_DIRECTION'
                    ok = set_param(mav, param, best_combo[i])
                    status = "✓" if ok else "✗"
                    print(f"    {param} → {best_combo[i]:+d}  {status}")
                
                print(f"\n  Applied! Now run the mixing matrix test again to verify.")
            else:
                print(f"  Skipped. Apply these manually if needed.")

        # Show all combos with high scores
        print(f"\n  All direction combos scoring >= {best_score - 2}:")
        print(f"  {'D1':>4s} {'D2':>4s} {'D3':>4s} {'D4':>4s} | {'Score':>5s}")
        print(f"  {'-'*4} {'-'*4} {'-'*4} {'-'*4}-+-{'-'*5}")
        
        for d1 in [-1, 1]:
            for d2 in [-1, 1]:
                for d3 in [-1, 1]:
                    for d4 in [-1, 1]:
                        test_dirs = {1: d1, 2: d2, 3: d3, 4: d4}
                        score = 0
                        total_checks = 0
                        
                        for name, cmd_x, cmd_y, cmd_z, cmd_r in AXIS_COMMANDS:
                            if name not in all_devs:
                                continue
                            actual = all_devs[name]
                            
                            for p in range(1, 5):
                                fwd_c, lat_c, yaw_c = mixing[p]
                                d = test_dirs[p]
                                raw = (cmd_x/1000.0 * fwd_c + 
                                       cmd_y/1000.0 * lat_c + 
                                       cmd_r/1000.0 * yaw_c) * d
                                
                                actual_dev = actual[p-1]
                                total_checks += 1
                                
                                if raw > 0.01 and actual_dev > DEADBAND:
                                    score += 1
                                elif raw < -0.01 and actual_dev < -DEADBAND:
                                    score += 1
                                elif raw < -0.01 and abs(actual_dev) <= DEADBAND:
                                    score += 1
                                elif abs(raw) <= 0.01 and abs(actual_dev) <= DEADBAND:
                                    score += 1
                        
                        if score >= best_score - 2:
                            marker = " ← BEST" if score == best_score else ""
                            current = " (current)" if (d1==dirs.get(1) and d2==dirs.get(2) and 
                                                        d3==dirs.get(3) and d4==dirs.get(4)) else ""
                            print(f"  {d1:+4d} {d2:+4d} {d3:+4d} {d4:+4d} | {score:>5d}{marker}{current}")

    except KeyboardInterrupt:
        print(f"\n  [E-STOP]")
        if nh:
            nh.neutral()
            time.sleep(0.3)
        if mav:
            disarm(mav)
        if nh:
            nh.stop()

    except Exception as e:
        print(f"\n  [ERROR] {e}")
        import traceback
        traceback.print_exc()
        if nh:
            nh.neutral()
            time.sleep(0.3)
        if mav:
            disarm(mav)
        if nh:
            nh.stop()


if __name__ == "__main__":
    main()