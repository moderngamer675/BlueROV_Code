# RobotTelemetry.py
# MAVLink communication handler for BlueROV2
# Background thread — all GUI communication via SharedState

import threading
import time
from pymavlink import mavutil

from rov_config import MAV_PORT, SOURCE_SYSTEM, THRUSTER_COUNT
from shared_state import SharedState, Command

RAD2DEG = 57.2958

# Battery voltage thresholds: (min_voltage, color)
BATTERY_THRESHOLDS = [
    (15.5, "#00E676"),  # Green — good
    (14.5, "#FFD600"),  # Yellow — OK
    (13.5, "#FF9100"),  # Orange — low
    (0.0,  "#FF1744"),  # Red — critical
]


class TelemetryHandler:
    """
    Threaded MAVLink handler.

    - Reads MAVLink messages and writes display updates to SharedState.
    - Reads Command objects from SharedState and executes them on self.mav.
    - Never touches tkinter directly.
    """

    def __init__(self, state: SharedState):
        self._state = state
        self._thread = None
        self._stop = threading.Event()
        self.running = False
        self.mav = None
        self.armed = False

        self._last_hb = 0.0
        self._last_ctrl = 0.0
        self._ctrl_hz = 10

        # ── Command dispatch (GUI → telemetry thread) ────────────────────
        self._cmd_dispatch = {
            "arm":          lambda a, kw: self._do_arm_disarm(True),
            "disarm":       lambda a, kw: self._do_arm_disarm(False),
            "set_motion":   lambda a, kw: self._do_set_motion(*a, **kw),
            "stop_motors":  lambda a, kw: self._send_neutral(),
            "set_mode":     lambda a, kw: self._do_set_mode(*a),
        }

    # =====================================================================
    #  START / STOP
    # =====================================================================

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="TelemetryThread")
        self._thread.start()
        self.running = True
        self._state.log("Telemetry thread started.")

    def stop(self):
        self._state.log("Stopping telemetry...")
        self._stop.set()
        self.running = False
        if self.mav:
            try:
                self._send_neutral()
                time.sleep(0.2)
                self._do_arm_disarm(False)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3)
        self._state.log("Telemetry stopped.")

    # =====================================================================
    #  MAIN LOOP
    # =====================================================================

    def _run(self):
        if not self._connect():
            return

        # Message dispatch table — maps MAVLink type → handler
        msg_dispatch = {
            'HEARTBEAT':         self._on_heartbeat,
            'SYS_STATUS':        self._on_sys_status,
            'VFR_HUD':           self._on_vfr_hud,
            'ATTITUDE':          self._on_attitude,
            'SCALED_PRESSURE':   self._on_pressure,
            'SERVO_OUTPUT_RAW':  self._on_servo,
            'NAMED_VALUE_FLOAT': self._on_named_value,
        }

        while not self._stop.is_set():
            now = time.time()

            # Periodic heartbeat to vehicle
            if now - self._last_hb >= 1.0:
                self._send_heartbeat()
                self._last_hb = now

            # Periodic neutral hold
            if now - self._last_ctrl >= (1.0 / self._ctrl_hz):
                self._send_neutral()
                self._last_ctrl = now

            # ── Process commands from GUI ────────────────────────────────
            self._process_commands()

            # ── Receive MAVLink messages ─────────────────────────────────
            msg = self.mav.recv_match(blocking=True, timeout=0.05)
            if msg is None:
                continue

            mt = msg.get_type()
            if mt != 'BAD_DATA' and mt in msg_dispatch:
                msg_dispatch[mt](msg)

        self._state.log("Telemetry loop ended.")

    def _process_commands(self):
        """Drain all pending commands from the GUI and execute them."""
        while True:
            cmd = self._state.poll_command()
            if cmd is None:
                break
            handler = self._cmd_dispatch.get(cmd.name)
            if handler:
                try:
                    handler(cmd.args, cmd.kwargs)
                except Exception as e:
                    self._state.log(f"Command error ({cmd.name}): {e}")
            else:
                self._state.log(f"Unknown command: {cmd.name}")

    def _connect(self) -> bool:
        self._state.log(f"Connecting to MAVLink on UDP:{MAV_PORT}...")
        try:
            self.mav = mavutil.mavlink_connection(
                f'udp:0.0.0.0:{MAV_PORT}', source_system=SOURCE_SYSTEM)
        except Exception as e:
            self._state.log(f"❌ MAVLink connection failed: {e}")
            self.running = False
            return False

        self._state.log("Waiting for heartbeat from Pixhawk...")
        hb = self.mav.wait_heartbeat(timeout=15)
        if hb is None:
            self._state.log("❌ No heartbeat — check MAVProxy on Pi")
            self.running = False
            return False

        self._state.log(
            f"✅ MAVLink connected — System {self.mav.target_system}")
        self._state.log(f"   Mode: {mavutil.mode_string_v10(hb)}")

        self._state.put_telemetry_update("STATUS", "ONLINE", "#00E676")
        self._state.put_telemetry_update("LINK", "ACTIVE", "#00E676")
        self._set_manual_mode()
        return True

    # =====================================================================
    #  MESSAGE HANDLERS — write to SharedState, never touch GUI
    # =====================================================================

    def _on_heartbeat(self, msg):
        mode = mavutil.mode_string_v10(msg)
        armed = bool(msg.base_mode &
                     mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        self._state.update_raw_telemetry(mode=mode, armed=armed)
        self.armed = armed

        self._state.put_telemetry_update("STATUS", mode)
        self._state.put_telemetry_update(
            "ARMED_STATE",
            "⚠ ARMED" if armed else "SAFE",
            "#FF1744" if armed else "#00E676")

    def _on_sys_status(self, msg):
        v = msg.voltage_battery / 1000.0
        a = msg.current_battery / 100.0 if msg.current_battery != -1 else 0.0
        self._state.update_raw_telemetry(battery_v=v, battery_a=a)

        bat_col = next(c for thresh, c in BATTERY_THRESHOLDS if v > thresh)
        self._state.put_telemetry_update("BATTERY", f"{v:.2f}", bat_col)
        self._state.put_telemetry_update("CURRENT", f"{a:.1f}")

    def _on_vfr_hud(self, msg):
        depth = abs(msg.alt)
        self._state.update_raw_telemetry(
            depth=depth, heading=msg.heading, throttle=msg.throttle)
        self._state.put_telemetry_update("DEPTH", f"{depth:.2f}")
        self._state.put_telemetry_update("HEADING", f"{msg.heading}")

    def _on_attitude(self, msg):
        roll  = msg.roll  * RAD2DEG
        pitch = msg.pitch * RAD2DEG
        yaw   = msg.yaw   * RAD2DEG
        self._state.update_raw_telemetry(roll=roll, pitch=pitch, yaw=yaw)
        self._state.put_telemetry_update("ROLL", f"{roll:+.1f}")
        self._state.put_telemetry_update("PITCH", f"{pitch:+.1f}")

    def _on_pressure(self, msg):
        self._state.update_raw_telemetry(
            pressure=msg.press_abs, temp=msg.temperature / 100.0)

    # In RobotTelemetry.py, replace the _on_servo method:

    def _on_servo(self, msg):
        servos = [getattr(msg, f'servo{i}_raw', 1500)
              for i in range(1, THRUSTER_COUNT + 1)]
        self._state.update_raw_telemetry(servo=servos)

        thrust = [max(-1.0, min(1.0, (pwm - 1500) / 400.0))
              for pwm in servos]
        self._state.put_telemetry_update("THRUSTERS", thrust)

    def _on_named_value(self, msg):
        name = msg.name.strip('\x00').strip()
        self._state.put_telemetry_update(
            f"SENSOR_{name}", f"{msg.value:.3f}")

    # =====================================================================
    #  COMMAND EXECUTORS — called on telemetry thread only
    # =====================================================================

    def _do_set_motion(self, forward=0.0, lateral=0.0,
                       throttle=0.0, yaw=0.0):
        """Send MANUAL_CONTROL. All values -1.0 to +1.0."""
        if not (self.mav and self.running):
            return
        x = max(-1000, min(1000, int(forward  * 1000)))
        y = max(-1000, min(1000, int(lateral  * 1000)))
        z = max(0,     min(1000, int(500 + throttle * 500)))
        r = max(-1000, min(1000, int(yaw      * 1000)))
        self.mav.mav.manual_control_send(
            self.mav.target_system, x, y, z, r, 0)

    def _do_arm_disarm(self, arm: bool):
        if not self.mav:
            return
        self.mav.mav.command_long_send(
            self.mav.target_system, self.mav.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, int(arm), 21196, 0, 0, 0, 0, 0)
        self._state.log(
            f"Sent {'ARM' if arm else 'DISARM'} command to vehicle.")
        if not arm:
            self._send_neutral()

    def _do_set_mode(self, mode_name: str):
        if not self.mav:
            return
        mode_id = self.mav.mode_mapping().get(mode_name)
        if mode_id is None:
            self._state.log(f"⚠️  {mode_name} mode not found in mode map")
            return
        self.mav.mav.set_mode_send(
            self.mav.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, mode_id)
        self._state.log(f"Mode → {mode_name}")

    # =====================================================================
    #  INTERNAL HELPERS — all run on telemetry thread
    # =====================================================================

    def _send_neutral(self):
        if self.mav and self.running:
            self.mav.mav.manual_control_send(
                self.mav.target_system, 0, 0, 500, 0, 0)

    def _set_manual_mode(self):
        self._do_set_mode("MANUAL")
        self._state.log("MANUAL mode set.")

    def _send_heartbeat(self):
        if self.mav:
            self.mav.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)

    def get_telemetry(self) -> dict:
        """Public accessor — returns a thread-safe snapshot."""
        return self._state.get_raw_telemetry()