import threading, time, os

try:
    os.environ.setdefault('SDL_VIDEO_ALLOW_SCREENSAVER', '1')
    os.environ.setdefault('SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', '1')
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

from rov_config import (
    GAMEPAD_POLL_MS, GAMEPAD_DEADZONE, GAMEPAD_TRIGGER_DEADZONE,
    GAMEPAD_AXIS_LEFT_X, GAMEPAD_AXIS_LEFT_Y, GAMEPAD_AXIS_RIGHT_X,
    GAMEPAD_AXIS_LT, GAMEPAD_AXIS_RT,
    GAMEPAD_BTN_A, GAMEPAD_BTN_B, GAMEPAD_BTN_X, GAMEPAD_BTN_Y,
    GAMEPAD_BTN_LB, GAMEPAD_BTN_RB, GAMEPAD_BTN_BACK, GAMEPAD_BTN_START,
    GAMEPAD_BTN_L3, GAMEPAD_BTN_R3, GAMEPAD_HAT_INDEX, GAMEPAD_SPEED_PROFILES,
)
from shared_state import Command


def apply_deadzone(value, deadzone):
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * min((abs(value) - deadzone) / (1.0 - deadzone), 1.0)


def normalize_trigger(raw):
    return max(0.0, min(1.0, (raw + 1.0) / 2.0))


class GamepadThread(threading.Thread):
    def __init__(self, shared_state, motion_controller):
        super().__init__(daemon=True, name="GamepadThread")
        self._state      = shared_state
        self._motion     = motion_controller
        self._stop_event = threading.Event()
        self._connected  = False
        self._joystick   = None
        self._pygame_inited = False
        self._prev_buttons: dict = {}
        self._prev_hat = (0, 0)
        self._smooth_lx = self._smooth_ly = self._smooth_rx = 0.0
        self._smooth_lt = self._smooth_rt = 0.0
        self._smoothing  = 0.35
        self._speed_index = 0
        self._has_input   = False

    @property
    def connected(self):
        return self._connected

    def stop(self):
        self._stop_event.set()

    def run(self):
        if not PYGAME_AVAILABLE:
            self._state.log("[GAMEPAD] ❌ pygame not installed")
            return
        try:
            os.environ['SDL_VIDEO_WINDOW_POS'] = '-10000,-10000'
            pygame.init()
            pygame.display.set_mode((1, 1), pygame.NOFRAME)
            self._pygame_inited = True
        except Exception as e:
            self._state.log(f"[GAMEPAD] ❌ pygame init failed: {e}")
            return

        reconnect_interval = 0
        while not self._stop_event.is_set():
            try:
                if not self._connected:
                    reconnect_interval += GAMEPAD_POLL_MS
                    if reconnect_interval >= 2000:
                        reconnect_interval = 0
                        self._try_connect()
                    if not self._connected:
                        time.sleep(GAMEPAD_POLL_MS / 1000.0)
                        continue
                self._poll()
                time.sleep(GAMEPAD_POLL_MS / 1000.0)
            except pygame.error as e:
                self._state.log(f"[GAMEPAD] ⚠ pygame error: {e}")
                self._connected = False
                self._joystick  = None
                self._state.set_gamepad_state(connected=False)
                self._state.put_telemetry_update("GAMEPAD", "DISCONNECTED", "#FF4444")
                time.sleep(1.0)
            except Exception as e:
                self._state.log(f"[GAMEPAD] Error: {e}")
                time.sleep(1.0)

        self._cleanup()

    def _try_connect(self):
        try:
            pygame.joystick.quit()
            pygame.joystick.init()
        except Exception:
            return

        if pygame.joystick.get_count() == 0:
            if self._connected:
                self._connected = False
                self._joystick  = None
                self._state.set_gamepad_state(connected=False)
                self._state.put_telemetry_update("GAMEPAD", "DISCONNECTED", "#FF4444")
            return

        try:
            self._joystick = pygame.joystick.Joystick(0)
            self._joystick.init()
            self._connected    = True
            self._prev_buttons = {i: False for i in range(self._joystick.get_numbuttons())}
            self._prev_hat     = (0, 0)
            self._smooth_lx = self._smooth_ly = self._smooth_rx = 0.0
            self._smooth_lt = self._smooth_rt = 0.0
            self._state.set_gamepad_state(connected=True)
            self._state.put_telemetry_update("GAMEPAD", "CONNECTED", "#44FF44")
            self._state.log(f"[GAMEPAD] ✅ {self._joystick.get_name()}")
        except Exception as e:
            self._state.log(f"[GAMEPAD] ⚠ Connect failed: {e}")

    def _poll(self):
        try:
            pygame.event.pump()
        except Exception:
            self._connected = False
            return

        if self._joystick is None:
            self._connected = False
            return

        try:
            raw_lx = self._joystick.get_axis(GAMEPAD_AXIS_LEFT_X)
            raw_ly = self._joystick.get_axis(GAMEPAD_AXIS_LEFT_Y)
            raw_rx = self._joystick.get_axis(GAMEPAD_AXIS_RIGHT_X)
        except Exception:
            self._connected = False
            return

        lx = apply_deadzone(raw_lx, GAMEPAD_DEADZONE)
        ly = -apply_deadzone(raw_ly, GAMEPAD_DEADZONE)
        rx = apply_deadzone(raw_rx, GAMEPAD_DEADZONE)

        lt = rt = 0.0
        try:
            lt = normalize_trigger(self._joystick.get_axis(GAMEPAD_AXIS_LT))
            rt = normalize_trigger(self._joystick.get_axis(GAMEPAD_AXIS_RT))
            if lt < GAMEPAD_TRIGGER_DEADZONE: lt = 0.0
            if rt < GAMEPAD_TRIGGER_DEADZONE: rt = 0.0
        except (pygame.error, IndexError):
            pass

        a = self._smoothing
        self._smooth_lx += a * (lx - self._smooth_lx)
        self._smooth_ly += a * (ly - self._smooth_ly)
        self._smooth_rx += a * (rx - self._smooth_rx)
        self._smooth_lt += a * (lt - self._smooth_lt)
        self._smooth_rt += a * (rt - self._smooth_rt)

        self._has_input = (
            abs(self._smooth_lx) > 0.02 or abs(self._smooth_ly) > 0.02 or
            abs(self._smooth_rx) > 0.02 or self._smooth_lt > 0.02 or self._smooth_rt > 0.02
        )
        self._state.set_gamepad_state(connected=True, input_active=self._has_input)

        if self._has_input:
            auto_ctrl = getattr(self._motion, "_auto_ctrl", None)
            if auto_ctrl:
                auto_ctrl.notify_user_override()
            self._motion.move_from_gamepad(
                self._smooth_lx, self._smooth_ly, self._smooth_rx,
                self._smooth_lt, self._smooth_rt
            )

        self._handle_buttons()
        self._handle_dpad()

        if self._has_input:
            self._state.put_telemetry_update(
                "GAMEPAD",
                f"X:{self._smooth_lx:+.1f} Y:{self._smooth_ly:+.1f} R:{self._smooth_rx:+.1f}",
                "#44FF44"
            )
        else:
            self._state.put_telemetry_update("GAMEPAD", "IDLE", "#888888")

    def _handle_buttons(self):
        if not self._joystick:
            return
        for btn_id in range(self._joystick.get_numbuttons()):
            try:
                cur = self._joystick.get_button(btn_id)
            except Exception:
                continue
            if cur and not self._prev_buttons.get(btn_id, False):
                self._on_button_press(btn_id)
            self._prev_buttons[btn_id] = cur

    def _on_button_press(self, btn_id):
        auto_ctrl = getattr(self._motion, "_auto_ctrl", None)

        if btn_id == GAMEPAD_BTN_A:
            self._state.send_command(Command(name="arm"))
            self._state.log("🎮 A → ARM")

        elif btn_id == GAMEPAD_BTN_B:
            self._state.send_command(Command(name="disarm"))
            self._state.log("🎮 B → DISARM")

        elif btn_id == GAMEPAD_BTN_Y:
            if auto_ctrl:
                from autonomous_controller import AutonomousMode
                auto_ctrl.set_mode(AutonomousMode.OFF)
            self._state.send_command(Command(name="stop_motors"))
            self._smooth_lx = self._smooth_ly = self._smooth_rx = 0.0
            self._smooth_lt = self._smooth_rt = 0.0
            self._motion.all_motors_off()
            self._state.log("🎮 ⚠ Y → EMERGENCY STOP")

        elif btn_id == GAMEPAD_BTN_X:
            self._speed_index = (self._speed_index + 1) % len(GAMEPAD_SPEED_PROFILES)
            profile = GAMEPAD_SPEED_PROFILES[self._speed_index]
            self._motion.set_speed_profile(profile)
            self._state.log(f"🎮 X → Speed: {profile.upper()}")

        elif btn_id == GAMEPAD_BTN_LB:
            self._speed_index = max(0, self._speed_index - 1)
            profile = GAMEPAD_SPEED_PROFILES[self._speed_index]
            self._motion.set_speed_profile(profile)
            self._state.log(f"🎮 LB → Speed: {profile.upper()}")

        elif btn_id == GAMEPAD_BTN_RB:
            self._speed_index = min(len(GAMEPAD_SPEED_PROFILES) - 1, self._speed_index + 1)
            profile = GAMEPAD_SPEED_PROFILES[self._speed_index]
            self._motion.set_speed_profile(profile)
            self._state.log(f"🎮 RB → Speed: {profile.upper()}")

        elif btn_id == GAMEPAD_BTN_BACK:
            if auto_ctrl:
                from autonomous_controller import AutonomousMode
                auto_ctrl.set_mode(AutonomousMode.OFF)
                self._state.log("🎮 BACK → AUTO OFF")

        elif btn_id == GAMEPAD_BTN_START:
            if auto_ctrl:
                from autonomous_controller import AutonomousMode
                last = getattr(auto_ctrl, "_last_active_mode", None)
                if last and last != AutonomousMode.OFF:
                    auto_ctrl.set_mode(last)
                    self._state.log(f"🎮 START → AUTO: {last.value}")

        elif btn_id == GAMEPAD_BTN_L3:
            self._motion.toggle_motor_a()
            self._state.log("🎮 L3 → Toggle Motor A")

        elif btn_id == GAMEPAD_BTN_R3:
            self._motion.toggle_motor_b()
            self._state.log("🎮 R3 → Toggle Motor B")

    def _handle_dpad(self):
        if not self._joystick or self._joystick.get_numhats() == 0:
            return
        try:
            hat = self._joystick.get_hat(GAMEPAD_HAT_INDEX)
        except Exception:
            return
        if hat == self._prev_hat:
            return
        self._prev_hat = hat

        auto_ctrl = getattr(self._motion, "_auto_ctrl", None)
        if not auto_ctrl:
            return

        from autonomous_controller import AutonomousMode
        hx, hy = hat
        mapping = {
            (0,  1): (AutonomousMode.WANDER,            "D-Up → WANDER"),
            (0, -1): (AutonomousMode.CORRIDOR,           "D-Down → CORRIDOR"),
            (-1, 0): (AutonomousMode.WALL_FOLLOW_LEFT,   "D-Left → WALL LEFT"),
            (1,  0): (AutonomousMode.WALL_FOLLOW_RIGHT,  "D-Right → WALL RIGHT"),
        }
        if (hx, hy) in mapping:
            mode, log_msg = mapping[(hx, hy)]
            auto_ctrl.set_mode(mode)
            auto_ctrl._last_active_mode = mode
            self._state.log(f"🎮 {log_msg}")

    def _cleanup(self):
        try:
            if self._joystick:
                self._joystick.quit()
            if self._pygame_inited:
                pygame.quit()
        except Exception:
            pass