# RobotTelemetry.py
# Handles all MAVLink communication with the BlueROV2
# Uses MANUAL_CONTROL (proven working method)
# Runs in background thread — thread-safe callbacks

import threading
import time
from pymavlink import mavutil
from rov_config import MAV_PORT, SOURCE_SYSTEM


class TelemetryHandler:

    def __init__(self, update_callback, log_callback):
        """
        update_callback : fn(key, value, color=None)
                          Called on main thread via root.after
        log_callback    : fn(message)
        """
        self._update  = update_callback
        self._log     = log_callback
        self._thread  = None
        self._stop    = threading.Event()
        self.running  = False
        self.mav      = None
        self.armed    = False

        # Current thruster values (-1.0 to 1.0)
        self._thrust = [0.0] * 6

        # Telemetry store
        self._telem = {
            "mode":      "—",
            "armed":     False,
            "battery_v": 0.0,
            "battery_a": 0.0,
            "depth":     0.0,
            "heading":   0,
            "throttle":  0,
            "roll":      0.0,
            "pitch":     0.0,
            "yaw":       0.0,
            "pressure":  0.0,
            "temp":      0.0,
            "servo":     [1500] * 6,
        }

        # Heartbeat timing
        self._last_hb = 0.0

        # Control loop timing
        self._last_ctrl = 0.0
        self._ctrl_hz   = 10   # Send MANUAL_CONTROL at 10Hz

    # =========================================================================
    #  START / STOP
    # =========================================================================
    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="TelemetryThread"
        )
        self._thread.start()
        self.running = True
        self._log("Telemetry thread started.")

    def stop(self):
        self._log("Stopping telemetry...")
        self._stop.set()
        self.running = False
        if self.mav:
            try:
                self._send_neutral()
                time.sleep(0.2)
                self.arm_disarm(False)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3)
        self._log("Telemetry stopped.")

    # =========================================================================
    #  MAIN THREAD
    # =========================================================================
    def _run(self):
        # ── Connect ───────────────────────────────────────
        self._log(f"Connecting to MAVLink on UDP:{MAV_PORT}...")
        try:
            self.mav = mavutil.mavlink_connection(
                f'udp:0.0.0.0:{MAV_PORT}',
                source_system=SOURCE_SYSTEM
            )
        except Exception as e:
            self._log(f"❌ MAVLink connection failed: {e}")
            self.running = False
            return

        # ── Wait for heartbeat ────────────────────────────
        self._log("Waiting for heartbeat from Pixhawk...")
        hb = self.mav.wait_heartbeat(timeout=15)
        if hb is None:
            self._log("❌ No heartbeat — check MAVProxy on Pi")
            self.running = False
            return

        mode = mavutil.mode_string_v10(hb)
        self._log(f"✅ MAVLink connected — System {self.mav.target_system}")
        self._log(f"   Mode: {mode}")

        # Update UI connection status
        self._update("STATUS", "ONLINE",  "#00E676")
        self._update("LINK",   "ACTIVE",  "#00E676")

        # ── Set MANUAL mode ───────────────────────────────
        self._set_manual_mode()

        # ── Main receive loop ─────────────────────────────
        while not self._stop.is_set():
            now = time.time()

            # Send heartbeat every 1 second
            if now - self._last_hb >= 1.0:
                self._send_heartbeat()
                self._last_hb = now

            # Send MANUAL_CONTROL at 10Hz to keep armed
            if now - self._last_ctrl >= (1.0 / self._ctrl_hz):
                self._send_manual_control()
                self._last_ctrl = now

            # Receive message
            msg = self.mav.recv_match(
                blocking=True,
                timeout=0.05
            )
            if msg is None:
                continue

            mt = msg.get_type()
            if mt == 'BAD_DATA':
                continue

            self._parse_message(mt, msg)

        self._log("Telemetry loop ended.")

    # =========================================================================
    #  MESSAGE PARSING
    # =========================================================================
    def _parse_message(self, mt: str, msg):
        # ── HEARTBEAT ─────────────────────────────────────
        if mt == 'HEARTBEAT':
            mode  = mavutil.mode_string_v10(msg)
            armed = bool(
                msg.base_mode &
                mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
            )
            self._telem["mode"]  = mode
            self._telem["armed"] = armed
            self.armed = armed

            self._update("STATUS", mode)

            if armed:
                self._update("ARMED_STATE", "⚠ ARMED", "#FF1744")
            else:
                self._update("ARMED_STATE", "SAFE",    "#00E676")

        # ── BATTERY ───────────────────────────────────────
        elif mt == 'SYS_STATUS':
            v = msg.voltage_battery / 1000.0
            a = (msg.current_battery / 100.0
                 if msg.current_battery != -1 else 0.0)
            self._telem["battery_v"] = v
            self._telem["battery_a"] = a

            # Colour battery by voltage
            if v > 15.5:
                bat_col = "#00E676"   # Green — good
            elif v > 14.5:
                bat_col = "#FFD600"   # Yellow — OK
            elif v > 13.5:
                bat_col = "#FF9100"   # Orange — low
            else:
                bat_col = "#FF1744"   # Red — critical

            self._update("BATTERY", f"{v:.2f}", bat_col)
            self._update("CURRENT", f"{a:.1f}")

        # ── VFR HUD ───────────────────────────────────────
        elif mt == 'VFR_HUD':
            depth = abs(msg.alt)
            self._telem["depth"]    = depth
            self._telem["heading"]  = msg.heading
            self._telem["throttle"] = msg.throttle

            self._update("DEPTH",   f"{depth:.2f}")
            self._update("HEADING", f"{msg.heading}")

        # ── ATTITUDE ──────────────────────────────────────
        elif mt == 'ATTITUDE':
            roll  = msg.roll  * 57.2958
            pitch = msg.pitch * 57.2958
            yaw   = msg.yaw   * 57.2958
            self._telem["roll"]  = roll
            self._telem["pitch"] = pitch
            self._telem["yaw"]   = yaw

            self._update("ROLL",  f"{roll:+.1f}")
            self._update("PITCH", f"{pitch:+.1f}")

        # ── PRESSURE / TEMP ───────────────────────────────
        elif mt == 'SCALED_PRESSURE':
            self._telem["pressure"] = msg.press_abs
            self._telem["temp"]     = msg.temperature / 100.0

        # ── SERVO OUTPUTS ─────────────────────────────────
        elif mt == 'SERVO_OUTPUT_RAW':
            servos = []
            for i in range(1, 7):
                pwm = getattr(msg, f'servo{i}_raw', 1500)
                servos.append(pwm)
            self._telem["servo"] = servos

            # Convert PWM (1100-1900) to -1.0 to +1.0 for display
            thrust_values = []
            for pwm in servos:
                if pwm <= 1500:
                    val = (pwm - 1500) / 400.0   # 1100→-1.0  1500→0.0
                else:
                    val = (pwm - 1500) / 400.0   # 1500→0.0   1900→+1.0
                thrust_values.append(
                    max(-1.0, min(1.0, val))
                )

            # Send to thruster panel
            self._update("THRUSTERS", thrust_values)

        # ── NAMED VALUES (Arduino sensors) ────────────────
        elif mt == 'NAMED_VALUE_FLOAT':
            name = msg.name.strip('\x00').strip()
            self._update(f"SENSOR_{name}", f"{msg.value:.3f}")

    # =========================================================================
    #  MOTOR CONTROL  (MANUAL_CONTROL method — proven working)
    # =========================================================================
    def set_motion(self,
                   forward:  float = 0.0,
                   lateral:  float = 0.0,
                   throttle: float = 0.0,
                   yaw:      float = 0.0):
        """
        Set ROV motion using MANUAL_CONTROL.
        All values: -1.0 to +1.0
        forward  : +forward  / -reverse
        lateral  : +strafe right / -strafe left
        throttle : +ascend  / -descend
        yaw      : +yaw right / -yaw left
        """
        # Scale to MANUAL_CONTROL range (-1000 to +1000)
        # z is 0-1000 where 500 = neutral
        x = int(forward  * 1000)
        y = int(lateral  * 1000)
        z = int(500 + throttle * 500)
        r = int(yaw      * 1000)

        # Clamp all values
        x = max(-1000, min(1000, x))
        y = max(-1000, min(1000, y))
        z = max(0,     min(1000, z))
        r = max(-1000, min(1000, r))

        if self.mav and self.running:
            self.mav.mav.manual_control_send(
                self.mav.target_system,
                x, y, z, r, 0
            )

    def stop_motors(self):
        """Send neutral on all axes — safe stop"""
        self._send_neutral()

    def _send_neutral(self):
        if self.mav and self.running:
            self.mav.mav.manual_control_send(
                self.mav.target_system,
                0, 0, 500, 0, 0
            )

    def _send_manual_control(self):
        """
        Called at 10Hz.
        Sends current thrust values to keep Pixhawk happy.
        When idle sends neutral.
        """
        self._send_neutral()

    # =========================================================================
    #  ARM / DISARM
    # =========================================================================
    def arm_disarm(self, arm: bool):
        if not self.mav:
            return

        param = 1 if arm else 0
        self.mav.mav.command_long_send(
            self.mav.target_system,
            self.mav.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, param, 21196, 0, 0, 0, 0, 0
        )
        action = "ARM" if arm else "DISARM"
        self._log(f"Sent {action} command to vehicle.")

        if not arm:
            self._send_neutral()

    # =========================================================================
    #  MODE
    # =========================================================================
    def _set_manual_mode(self):
        if not self.mav:
            return
        mode_id = self.mav.mode_mapping().get('MANUAL')
        if mode_id is None:
            self._log("⚠️  MANUAL mode not found in mode map")
            return
        self.mav.mav.set_mode_send(
            self.mav.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_id
        )
        self._log("MANUAL mode set.")

    def set_mode(self, mode_name: str):
        if not self.mav:
            return
        mode_id = self.mav.mode_mapping().get(mode_name)
        if mode_id is None:
            self._log(f"❌ Mode {mode_name} not found")
            return
        self.mav.mav.set_mode_send(
            self.mav.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_id
        )
        self._log(f"Mode → {mode_name}")

    # =========================================================================
    #  HELPERS
    # =========================================================================
    def _send_heartbeat(self):
        if self.mav:
            self.mav.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0, 0, 0
            )

    def get_telemetry(self) -> dict:
        """Returns a snapshot of current telemetry."""
        return dict(self._telem)