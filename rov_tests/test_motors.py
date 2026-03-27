# rov_tests/motor_identify.py
# ═══════════════════════════════════════════════════════════════════════
# MOTOR PHYSICAL IDENTIFICATION
# ═══════════════════════════════════════════════════════════════════════
# Now that FRAME_CONFIG=1 is working with all 4 channels responding,
# this script isolates each motor one at a time using combined-axis
# MANUAL_CONTROL vectors so you can identify:
#   1. Which physical position each channel is in (FR/FL/BR/BL)
#   2. Which direction each motor spins (CW/CCW from above)
#
# The known mixing matrix from your test results:
#   Ch1: fwd=-1  lat=+1  yaw=+1
#   Ch2: fwd=-1  lat=-1  yaw=-1
#   Ch3: fwd=+1  lat=+1  yaw=-1
#   Ch4: fwd=+1  lat=-1  yaw=+1
#
# To isolate ONE channel, we combine axes so all others cancel:
#   Isolate Ch1: fwd=-1, lat=+1, yaw=+1 → x=-T, y=+T, r=+T
#   Isolate Ch2: fwd=-1, lat=-1, yaw=-1 → x=-T, y=-T, r=-T
#   Isolate Ch3: fwd=+1, lat=+1, yaw=-1 → x=+T, y=+T, r=-T
#   Isolate Ch4: fwd=+1, lat=-1, yaw=+1 → x=+T, y=-T, r=+T
# ═══════════════════════════════════════════════════════════════════════

from pymavlink import mavutil
import time
import threading
import sys

try:
    from rov_config import MAV_PORT
except ImportError:
    MAV_PORT = 14551

THRUST = 80       # slightly lower for single-motor isolation
SPIN_SECS = 4.0   # longer so you have time to look
SETTLE_SECS = 3.0


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
#  MAIN
# ═════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 60)
    print("  MOTOR PHYSICAL IDENTIFICATION")
    print("  Spins each motor ONE AT A TIME")
    print("=" * 60)
    print(f"""
  This will spin each of your 4 motors individually.
  For each motor you tell me:

  1. POSITION - looking DOWN at the ROV from above:

         FRONT
      FL \\     / FR
          [ROV]
      BL /     \\ BR
         BACK

  2. DIRECTION - viewed from above:
     CW  = Clockwise
     CCW = Counter-Clockwise

  Thrust: {THRUST}/1000 ({THRUST/10:.0f}%)
  Spin time: {SPIN_SECS}s per motor

  PROPS MUST BE REMOVED!
""")

    confirm = input("  Type YES to proceed: ").strip().upper()
    if confirm != "YES":
        sys.exit(0)

    mav = connect()
    nh = NeutralHold(mav)
    nh.start()

    print("\n  Arming...")
    if not arm_vehicle(mav):
        print("  Could not arm!")
        nh.stop()
        sys.exit(1)

    time.sleep(2)
    print("  Armed!\n")

    # Isolation vectors derived from the mixing matrix:
    #   Ch1: fwd=-1  lat=+1  yaw=+1
    #   Ch2: fwd=-1  lat=-1  yaw=-1
    #   Ch3: fwd=+1  lat=+1  yaw=-1
    #   Ch4: fwd=+1  lat=-1  yaw=+1
    T = THRUST
    isolations = [
        (1, "Channel 1", -T,  T, 500,  T),
        (2, "Channel 2", -T, -T, 500, -T),
        (3, "Channel 3",  T,  T, 500, -T),
        (4, "Channel 4",  T, -T, 500,  T),
    ]

    positions = ["FR", "FL", "BR", "BL"]
    directions = ["CW", "CCW"]
    motor_map = {}

    for ch, label, x, y, z, r in isolations:
        while True:
            print(f"\n  {'=' * 50}")
            print(f"  SPINNING {label}")
            print(f"  (x={x:+d}  y={y:+d}  z={z}  r={r:+d})")
            print(f"  Watch which motor spins...")
            print(f"  {'=' * 50}")

            nh.cmd(x=x, y=y, z=z, r=r)
            time.sleep(SPIN_SECS)
            nh.neutral()
            time.sleep(1)

            # Ask position
            while True:
                pos = input(f"\n  Which position is {label}? "
                           f"(FR/FL/BR/BL): ").strip().upper()
                if pos in positions:
                    break
                print(f"  Invalid! Enter one of: {positions}")

            # Ask direction
            while True:
                dir_ = input(f"  Spin direction of {label}? "
                            f"(CW/CCW): ").strip().upper()
                if dir_ in directions:
                    break
                print(f"  Invalid! Enter CW or CCW")

            print(f"\n  {label} = {pos}, {dir_}")
            choice = input(f"  Correct? (Y/N/RESPIN): ").strip().upper()

            if choice == "Y":
                motor_map[ch] = {"position": pos, "direction": dir_}
                break
            elif choice == "RESPIN":
                print(f"  Re-spinning {label}...")
                continue
            else:
                continue

        time.sleep(SETTLE_SECS)

    # ── RESULTS ──
    print("\n" + "=" * 60)
    print("  MOTOR MAP COMPLETE")
    print("=" * 60)

    print(f"\n  {'Channel':<10} {'Position':<10} {'Direction':<10}")
    print(f"  {'-'*10} {'-'*10} {'-'*10}")
    for ch in range(1, 5):
        info = motor_map[ch]
        print(f"  Ch{ch:<7} {info['position']:<10} {info['direction']:<10}")

    # ── Build the visual layout ──
    layout = {}
    for ch in range(1, 5):
        pos = motor_map[ch]["position"]
        dir_ = motor_map[ch]["direction"]
        layout[pos] = f"Ch{ch}({dir_})"

    print(f"""
  Physical Layout (viewed from above):

              FRONT
    {layout.get('FL', '---'):>12}     {layout.get('FR', '---'):<12}
                  [ROV]
    {layout.get('BL', '---'):>12}     {layout.get('BR', '---'):<12}
              BACK
""")

    # ── Mixing matrix with physical labels ──
    print("  Mixing Matrix (from test results):")
    print(f"  {'Channel':<8} {'Position':<6} {'Dir':<5} "
          f"{'Fwd':>5} {'Lat':>5} {'Yaw':>5}")
    print(f"  {'-'*8} {'-'*6} {'-'*5} {'-'*5} {'-'*5} {'-'*5}")

    # Known coefficients from your test
    coefficients = {
        1: {"fwd": -1, "lat": +1, "yaw": +1},
        2: {"fwd": -1, "lat": -1, "yaw": -1},
        3: {"fwd": +1, "lat": +1, "yaw": -1},
        4: {"fwd": +1, "lat": -1, "yaw": +1},
    }

    for ch in range(1, 5):
        info = motor_map[ch]
        c = coefficients[ch]
        print(f"  Ch{ch:<5} {info['position']:<6} {info['direction']:<5} "
              f"{c['fwd']:+5d} {c['lat']:+5d} {c['yaw']:+5d}")

    # ── Direction check ──
    print("\n" + "=" * 60)
    print("  DIRECTION VERIFICATION")
    print("=" * 60)
    print("""
  For a vectored X-frame to work correctly:
  - Diagonal pairs should spin OPPOSITE directions
  - FR and BL should be one direction (e.g., CW)
  - FL and BR should be the other direction (e.g., CCW)

  Your configuration:""")

    for pos_pair in [("FR", "BL"), ("FL", "BR")]:
        motors_in_pair = []
        for ch, info in motor_map.items():
            if info["position"] in pos_pair:
                motors_in_pair.append(
                    (info["position"], info["direction"], ch))

        if len(motors_in_pair) == 2:
            p1, d1, c1 = motors_in_pair[0]
            p2, d2, c2 = motors_in_pair[1]
            match = "SAME" if d1 == d2 else "OPPOSITE"
            ok = "OK" if d1 == d2 else "CHECK"
            print(f"    {p1}(Ch{c1})={d1}  {p2}(Ch{c2})={d2}  "
                  f"-> {match} ({ok})")

    # ── Save results ──
    print("\n" + "=" * 60)
    print("  WHAT TO TELL ME")
    print("=" * 60)
    print("""
  Copy and paste the MOTOR MAP and MIXING MATRIX sections
  above into the chat. With this information I can:

  1. Verify the matrix matches your physical layout
  2. Determine if any MOT_X_DIRECTION needs to be -1
  3. Update your GUI code (RobotTelemetry.py) so
     WASD/QE controls move the ROV correctly
  4. Build the final production motor test script
""")

    print("  Disarming...")
    disarm_vehicle(mav)
    nh.stop()
    print("  Done!\n")


if __name__ == "__main__":
    main()