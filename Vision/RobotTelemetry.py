import threading, time
from pymavlink import mavutil
from rov_config import (
    MAV_PORT, SOURCE_SYSTEM, THRUSTER_COUNT, SENSOR_PORT,
    MOTOR_CMD_PORT, PI_IP, SENSOR_NAMES, MOTOR_STATUS_NAMES,
    MOTOR_ON_VALUE, MOTOR_OFF_VALUE
)
from shared_state import SharedState, Command

RAD2DEG = 57.2958
BATTERY_THRESHOLDS = [(15.5, "#00E676"), (14.5, "#FFD600"), (13.5, "#FF9100"), (0.0, "#FF3366")]


class TelemetryHandler:
    def __init__(self, state: SharedState):
        self._state = state
        self._thread = None
        self.running = False
        self.mav     = None
        self.armed   = False
        self._stop   = threading.Event()
        self._last_hb = self._last_ctrl = 0.0
        self._cmd_dispatch = {
            "arm":         lambda a, kw: self._do_arm_disarm(True),
            "disarm":      lambda a, kw: self._do_arm_disarm(False),
            "set_motion":  lambda a, kw: self._do_set_motion(*a, **kw),
            "stop_motors": lambda a, kw: self._send_neutral(),
            "set_mode":    lambda a, kw: self._do_set_mode(*a),
        }

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.running = True
        self._state.log("Telemetry thread started.")

    def stop(self):
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

    def _run(self):
        if not self._connect():
            return
        dispatch = {
            'HEARTBEAT':        self._on_heartbeat,
            'SYS_STATUS':       self._on_sys_status,
            'VFR_HUD':          self._on_vfr_hud,
            'ATTITUDE':         self._on_attitude,
            'SCALED_PRESSURE':  self._on_pressure,
            'SERVO_OUTPUT_RAW': self._on_servo,
            'NAMED_VALUE_FLOAT':self._on_named_value,
        }
        while not self._stop.is_set():
            now = time.time()
            if now - self._last_hb   >= 1.0:  self._send_heartbeat(); self._last_hb   = now
            if now - self._last_ctrl >= 0.1:  self._send_neutral();   self._last_ctrl = now
            while cmd := self._state.poll_command():
                if handler := self._cmd_dispatch.get(cmd.name):
                    handler(cmd.args, cmd.kwargs)
            if msg := self.mav.recv_match(blocking=True, timeout=0.05):
                mt = msg.get_type()
                if mt != 'BAD_DATA' and mt in dispatch:
                    dispatch[mt](msg)

    def _connect(self):
        try:
            self.mav = mavutil.mavlink_connection(f'udp:0.0.0.0:{MAV_PORT}', source_system=SOURCE_SYSTEM)
        except Exception as e:
            self._state.log(f"❌ MAVLink connection failed: {e}")
            return False
        if not self.mav.wait_heartbeat(timeout=15):
            self._state.log("❌ No heartbeat")
            return False
        self._state.log(f"✅ MAVLink connected — System {self.mav.target_system}")
        self._state.put_telemetry_update("STATUS", "ONLINE", "#00E676")
        self._state.put_telemetry_update("LINK",   "ACTIVE", "#00E676")
        self._do_set_mode("MANUAL")
        return True

    def _on_heartbeat(self, msg):
        mode  = mavutil.mode_string_v10(msg)
        armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        self._state.update_raw_telemetry(mode=mode, armed=armed)
        self.armed = armed
        self._state.put_telemetry_update("STATUS", mode)
        self._state.put_telemetry_update("ARMED_STATE", " ⚠ ARMED" if armed else "SAFE",
                                          "#FF3366" if armed else "#00E676")

    def _on_sys_status(self, msg):
        v = msg.voltage_battery / 1000.0
        a = msg.current_battery / 100.0 if msg.current_battery != -1 else 0.0
        self._state.update_raw_telemetry(battery_v=v, battery_a=a)
        bat_col = next(c for thresh, c in BATTERY_THRESHOLDS if v > thresh)
        self._state.put_telemetry_update("BATTERY", f"{v:.2f}", bat_col)
        self._state.put_telemetry_update("CURRENT", f"{a:.1f}")

    def _on_vfr_hud(self, msg):
        self._state.update_raw_telemetry(heading=msg.heading, throttle=msg.throttle)
        self._state.put_telemetry_update("HEADING", f"{msg.heading}")

    def _on_attitude(self, msg):
        r, p, y = msg.roll * RAD2DEG, msg.pitch * RAD2DEG, msg.yaw * RAD2DEG
        self._state.update_raw_telemetry(roll=r, pitch=p, yaw=y)
        self._state.put_telemetry_update("ROLL",  f"{r:+.1f}")
        self._state.put_telemetry_update("PITCH", f"{p:+.1f}")

    def _on_pressure(self, msg):
        self._state.update_raw_telemetry(pressure=msg.press_abs, temp=msg.temperature / 100.0)

    def _on_servo(self, msg):
        servos = [getattr(msg, f'servo{i}_raw', 1500) for i in range(1, THRUSTER_COUNT + 1)]
        self._state.update_raw_telemetry(servo=servos)
        self._state.put_telemetry_update(
            "THRUSTERS",
            [max(-1.0, min(1.0, (pwm - 1500) / 400.0)) for pwm in servos]
        )

    def _on_named_value(self, msg):
        self._state.put_telemetry_update(f"SENSOR_{msg.name.strip(chr(0)).strip()}", f"{msg.value:.3f}")

    def _do_set_motion(self, forward=0.0, lateral=0.0, throttle=0.0, yaw=0.0):
        if self.mav and self.running:
            self.mav.mav.manual_control_send(
                self.mav.target_system,
                max(-1000, min(1000, int(forward  * 1000))),
                max(-1000, min(1000, int(lateral  * 1000))),
                max(0,     min(1000, int(500 + throttle * 500))),
                max(-1000, min(1000, int(yaw * 1000))), 0
            )

    def _do_arm_disarm(self, arm):
        if self.mav:
            self.mav.mav.command_long_send(
                self.mav.target_system, self.mav.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
                int(arm), 21196, 0, 0, 0, 0, 0
            )
            if not arm:
                self._send_neutral()

    def _do_set_mode(self, mode_name):
        if self.mav and (mode_id := self.mav.mode_mapping().get(mode_name)) is not None:
            self.mav.mav.set_mode_send(
                self.mav.target_system,
                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                mode_id
            )

    def _send_neutral(self):
        if self.mav and self.running:
            self.mav.mav.manual_control_send(self.mav.target_system, 0, 0, 500, 0, 0)

    def _send_heartbeat(self):
        if self.mav:
            self.mav.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0
            )


class SensorListenerThread(threading.Thread):
    SENSOR_CARD_MAP = {
        "dst_front": "FRONT_DIST", "dst_left": "LEFT_DIST",
        "dst_right": "RIGHT_DIST", "dst_back": "BACK_DIST",
    }

    def __init__(self, shared_state: SharedState):
        super().__init__(daemon=True, name="SensorListener")
        self._state      = shared_state
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        self._state.log(f"[SENSORS] Starting on udp:0.0.0.0:{SENSOR_PORT}")
        try:
            conn = mavutil.mavlink_connection(f"udp:0.0.0.0:{SENSOR_PORT}",
                                               source_system=255, source_component=0)
        except Exception as e:
            self._state.log(f"[SENSORS] ❌ Cannot bind: {e}")
            return

        while not self._stop_event.is_set():
            try:
                msg = conn.recv_match(type="NAMED_VALUE_FLOAT", blocking=True, timeout=2.0)
                if msg is None:
                    continue
                name = msg.name
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                name  = name.strip().rstrip("\x00")
                value = msg.value

                if name in SENSOR_NAMES:
                    self._state.update_sensor(name, value)
                    color   = self._proximity_color(value)
                    display = f"{int(value)}" if value > 0 else "—"
                    self._state.put_telemetry_update(
                        self.SENSOR_CARD_MAP.get(name, name),
                        display,
                        "#666666" if value <= 0 else color
                    )
                elif name in MOTOR_STATUS_NAMES:
                    is_on = value > 0.5
                    self._state.update_motor_state(name, is_on)
                    self._state.put_telemetry_update(
                        f"MOT_{name[-1].upper()}_STATUS",
                        "ON" if is_on else "OFF",
                        "#00E676" if is_on else "#666666"
                    )
            except Exception as e:
                if not self._stop_event.is_set():
                    self._state.log(f"[SENSORS] Error: {e}")

    @staticmethod
    def _proximity_color(dist_cm):
        if dist_cm <= 0:    return "#666666"
        if dist_cm < 20:    return "#FF4444"
        if dist_cm < 50:    return "#FFA500"
        if dist_cm < 100:   return "#FFFF44"
        return "#44FF44"


class MotorCommandThread(threading.Thread):
    def __init__(self, shared_state: SharedState):
        super().__init__(daemon=True, name="MotorCommandSender")
        self._state      = shared_state
        self._stop_event = threading.Event()
        self._conn       = None

    def stop(self):
        self._stop_event.set()

    def run(self):
        self._state.log(f"[MOTORS] Starting → {PI_IP}:{MOTOR_CMD_PORT}")
        try:
            self._conn = mavutil.mavlink_connection(
                f"udpout:{PI_IP}:{MOTOR_CMD_PORT}",
                source_system=255, source_component=0
            )
        except Exception as e:
            self._state.log(f"[MOTORS] ❌ Cannot create UDP connection: {e}")
            return

        self._state.log("[MOTORS] ✅ Motor command channel ready")
        while not self._stop_event.is_set():
            try:
                cmd = self._state.poll_motor_command(timeout=0.2)
                if cmd is None:
                    continue
                motor_name, turn_on = cmd
                name_bytes = motor_name.encode('utf-8')[:10].ljust(10, b'\x00')
                self._conn.mav.named_value_float_send(
                    int(time.time() * 1000) & 0xFFFFFFFF,
                    name_bytes,
                    MOTOR_ON_VALUE if turn_on else MOTOR_OFF_VALUE
                )
                self._state.log(f"[MOTORS] Sent: {motor_name} → {'ON' if turn_on else 'OFF'}")
            except Exception as e:
                if not self._stop_event.is_set():
                    self._state.log(f"[MOTORS] Send error: {e}")

        try:
            if self._conn:
                self._conn.mav.named_value_float_send(
                    int(time.time() * 1000) & 0xFFFFFFFF,
                    b'mot_all\x00\x00\x00',
                    MOTOR_OFF_VALUE
                )
        except Exception:
            pass