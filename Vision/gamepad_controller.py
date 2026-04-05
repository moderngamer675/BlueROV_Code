"""
gamepad_controller.py — Xbox 360 controller input handler for BlueROV2.
Runs on a dedicated daemon thread. Reads controller state via pygame,
translates to ROV commands through MotionController → SharedState pipeline.
"""

import threading
import time
import os

try:
    os.environ.setdefault('SDL_VIDEO_ALLOW_SCREENSAVER', '1')
    os.environ.setdefault('SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', '1')
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

from rov_config import (
    GAMEPAD_POLL_MS, GAMEPAD_DEADZONE, GAMEPAD_TRIGGER_DEADZONE,
    GAMEPAD_AXIS_LEFT_X, GAMEPAD_AXIS_LEFT_Y,
    GAMEPAD_AXIS_RIGHT_X, GAMEPAD_AXIS_LT, GAMEPAD_AXIS_RT,
    GAMEPAD_BTN_A, GAMEPAD_BTN_B, GAMEPAD_BTN_X, GAMEPAD_BTN_Y,
    GAMEPAD_BTN_LB, GAMEPAD_BTN_RB, GAMEPAD_BTN_BACK, GAMEPAD_BTN_START,
    GAMEPAD_BTN_L3, GAMEPAD_BTN_R3,
    GAMEPAD_HAT_INDEX, GAMEPAD_SPEED_PROFILES
)
from shared_state import Command


def apply_deadzone(value, deadzone):
    """Apply deadzone and rescale remaining range to full 0-1."""
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    rescaled = (abs(value) - deadzone) / (1.0 - deadzone)
    return sign * min(rescaled, 1.0)


def normalize_trigger(raw_value):
    """
    Normalize trigger from pygame range to 0.0-1.0.
    Xbox 360 on pygame/Windows: rest = -1.0, full press = +1.0
    """
    return max(0.0, min(1.0, (raw_value + 1.0) / 2.0))


class GamepadThread(threading.Thread):
    """
    Background thread for Xbox 360 controller input.
    Reads at 20Hz, sends motion commands through MotionController.
    Thread-safe: only writes to SharedState, never touches tkinter.
    """

    def __init__(self, shared_state, motion_controller):
        super().__init__(daemon=True, name="GamepadThread")
        self._state = shared_state
        self._motion = motion_controller
        self._stop_event = threading.Event()

        # Connection state
        self._connected = False
        self._joystick = None
        self._pygame_inited = False

        # Button edge detection
        self._prev_buttons = {}
        self._prev_hat = (0, 0)

        # Smoothed axes
        self._smooth_lx = 0.0
        self._smooth_ly = 0.0
        self._smooth_rx = 0.0
        self._smooth_lt = 0.0
        self._smooth_rt = 0.0
        self._smoothing = 0.35  # exponential smoothing factor

        # Speed profile cycling
        self._speed_index = 0

        # Input active flag
        self._has_input = False

    @property
    def connected(self):
        return self._connected

    def stop(self):
        self._stop_event.set()

    def run(self):
        if not PYGAME_AVAILABLE:
            self._state.log("[GAMEPAD] ❌ pygame not installed — controller disabled")
            self._state.log("[GAMEPAD] Run: pip install pygame")
            return

        # Init pygame minimally — need display for event.pump()
        try:
            os.environ['SDL_VIDEO_WINDOW_POS'] = '-10000,-10000'
            pygame.init()
            pygame.display.set_mode((1, 1), pygame.NOFRAME)
            self._pygame_inited = True
            self._state.log("[GAMEPAD] Controller subsystem initialized")
        except Exception as e:
            self._state.log(f"[GAMEPAD] ❌ pygame init failed: {e}")
            return

        # Main loop
        reconnect_interval = 0
        while not self._stop_event.is_set():
            try:
                if not self._connected:
                    # Try to connect every 2 seconds
                    reconnect_interval += GAMEPAD_POLL_MS
                    if reconnect_interval >= 2000:
                        reconnect_interval = 0
                        self._try_connect()
                    if not self._connected:
                        time.sleep(GAMEPAD_POLL_MS / 1000.0)
                        continue

                # Connected — poll inputs
                self._poll()
                time.sleep(GAMEPAD_POLL_MS / 1000.0)

            except pygame.error as e:
                self._state.log(f"[GAMEPAD] ⚠ pygame error: {e}")
                self._connected = False
                self._joystick = None
                self._state.set_gamepad_state(connected=False)
                self._state.put_telemetry_update("GAMEPAD", "DISCONNECTED", "#FF4444")
                time.sleep(1.0)

            except Exception as e:
                self._state.log(f"[GAMEPAD] Error: {e}")
                time.sleep(1.0)

        # Cleanup
        self._cleanup()
        self._state.log("[GAMEPAD] Thread stopped")

    def _try_connect(self):
        """Scan for Xbox 360 controller."""
        try:
            pygame.joystick.quit()
            pygame.joystick.init()
        except Exception:
            return

        count = pygame.joystick.get_count()

        if count == 0:
            if self._connected:
                self._state.log("[GAMEPAD] ⚠ Controller disconnected")
                self._connected = False
                self._joystick = None
                self._state.set_gamepad_state(connected=False)
                self._state.put_telemetry_update("GAMEPAD", "DISCONNECTED", "#FF4444")
            return

        try:
            self._joystick = pygame.joystick.Joystick(0)
            self._joystick.init()

            name = self._joystick.get_name()
            axes = self._joystick.get_numaxes()
            buttons = self._joystick.get_numbuttons()
            hats = self._joystick.get_numhats()

            self._connected = True
            self._prev_buttons = {i: False for i in range(buttons)}
            self._prev_hat = (0, 0)

            # Reset smoothed values
            self._smooth_lx = self._smooth_ly = self._smooth_rx = 0.0
            self._smooth_lt = self._smooth_rt = 0.0

            self._state.set_gamepad_state(connected=True)
            self._state.put_telemetry_update("GAMEPAD", "CONNECTED", "#44FF44")
            self._state.log(
                f"[GAMEPAD] ✅ {name} — {axes} axes, {buttons} btn, {hats} hat"
            )

        except Exception as e:
            self._state.log(f"[GAMEPAD] ⚠ Connect failed: {e}")

    def _poll(self):
        """Read all controller inputs and generate commands."""

        # Required for pygame joystick state updates
        try:
            pygame.event.pump()
        except Exception:
            self._connected = False
            return

        # Check controller still valid
        if self._joystick is None:
            self._connected = False
            return

        # ── Read analog sticks ──
        try:
            raw_lx = self._joystick.get_axis(GAMEPAD_AXIS_LEFT_X)
            raw_ly = self._joystick.get_axis(GAMEPAD_AXIS_LEFT_Y)
            raw_rx = self._joystick.get_axis(GAMEPAD_AXIS_RIGHT_X)
        except Exception:
            self._connected = False
            return

        # Apply deadzone
        lx = apply_deadzone(raw_lx, GAMEPAD_DEADZONE)
        ly = apply_deadzone(raw_ly, GAMEPAD_DEADZONE)
        rx = apply_deadzone(raw_rx, GAMEPAD_DEADZONE)

        # Invert Y: pygame up = negative, we want up = positive = forward
        ly = -ly

        # ── Read triggers ──
        lt = rt = 0.0
        try:
            raw_lt = self._joystick.get_axis(GAMEPAD_AXIS_LT)
            raw_rt = self._joystick.get_axis(GAMEPAD_AXIS_RT)
            lt = normalize_trigger(raw_lt)
            rt = normalize_trigger(raw_rt)
            if lt < GAMEPAD_TRIGGER_DEADZONE: lt = 0.0
            if rt < GAMEPAD_TRIGGER_DEADZONE: rt = 0.0
        except (pygame.error, IndexError):
            pass  # controller may not have trigger axes at expected indices

        # ── Exponential smoothing ──
        a = self._smoothing
        self._smooth_lx += a * (lx - self._smooth_lx)
        self._smooth_ly += a * (ly - self._smooth_ly)
        self._smooth_rx += a * (rx - self._smooth_rx)
        self._smooth_lt += a * (lt - self._smooth_lt)
        self._smooth_rt += a * (rt - self._smooth_rt)

        # ── Check if any input active ──
        self._has_input = (
            abs(self._smooth_lx) > 0.02 or abs(self._smooth_ly) > 0.02 or
            abs(self._smooth_rx) > 0.02 or self._smooth_lt > 0.02 or
            self._smooth_rt > 0.02
        )

        self._state.set_gamepad_state(
            connected=True,
            input_active=self._has_input
        )

        # ── Send motion command if sticks active ──
        if self._has_input:
            self._motion.move_from_gamepad(
                left_x=self._smooth_lx,
                left_y=self._smooth_ly,
                right_x=self._smooth_rx,
                lt=self._smooth_lt,
                rt=self._smooth_rt
            )

        # ── Handle buttons ──
        self._handle_buttons()

        # ── Handle D-pad ──
        self._handle_dpad()

        # ── Update GUI status ──
        if self._has_input:
            self._state.put_telemetry_update(
                "GAMEPAD",
                f"X:{self._smooth_lx:+.1f} Y:{self._smooth_ly:+.1f} R:{self._smooth_rx:+.1f}",
                "#44FF44"
            )
        elif self._connected:
            self._state.put_telemetry_update("GAMEPAD", "IDLE", "#888888")

    def _handle_buttons(self):
        """Process buttons with edge detection (fire once per press)."""
        if self._joystick is None:
            return

        num_buttons = self._joystick.get_numbuttons()

        for btn_id in range(num_buttons):
            try:
                current = self._joystick.get_button(btn_id)
            except Exception:
                continue

            previous = self._prev_buttons.get(btn_id, False)

            # Rising edge only
            if current and not previous:
                self._on_button_press(btn_id)

            self._prev_buttons[btn_id] = current

    def _on_button_press(self, btn_id):
        """Handle a single button press."""

        if btn_id == GAMEPAD_BTN_A:
            self._state.send_command(Command(name="arm"))
            self._state.log("🎮 A → ARM")

        elif btn_id == GAMEPAD_BTN_B:
            self._state.send_command(Command(name="disarm"))
            self._state.log("🎮 B → DISARM")

        elif btn_id == GAMEPAD_BTN_Y:
            # Emergency stop — thrusters AND DC motors
            self._state.send_command(Command(name="stop_motors"))
            self._smooth_lx = self._smooth_ly = self._smooth_rx = 0.0
            self._smooth_lt = self._smooth_rt = 0.0
            # Also kill DC motors
            self._motion.all_motors_off()
            self._state.log("🎮 ⚠ Y → EMERGENCY STOP (thrusters + DC motors)")

        elif btn_id == GAMEPAD_BTN_X:
            # Cycle speed profile
            self._speed_index = (self._speed_index + 1) % len(GAMEPAD_SPEED_PROFILES)
            profile = GAMEPAD_SPEED_PROFILES[self._speed_index]
            self._motion.set_speed_profile(profile)
            self._state.log(f"🎮 X → Speed: {profile.upper()}")

        elif btn_id == GAMEPAD_BTN_LB:
            # Speed down
            self._speed_index = max(0, self._speed_index - 1)
            profile = GAMEPAD_SPEED_PROFILES[self._speed_index]
            self._motion.set_speed_profile(profile)
            self._state.log(f"🎮 LB → Speed: {profile.upper()}")

        elif btn_id == GAMEPAD_BTN_RB:
            # Speed up
            self._speed_index = min(len(GAMEPAD_SPEED_PROFILES) - 1, self._speed_index + 1)
            profile = GAMEPAD_SPEED_PROFILES[self._speed_index]
            self._motion.set_speed_profile(profile)
            self._state.log(f"🎮 RB → Speed: {profile.upper()}")

        elif btn_id == GAMEPAD_BTN_L3:
            # Left stick click → toggle Motor A
            self._motion.toggle_motor_a()
            self._state.log("🎮 L3 → Toggle Motor A")

        elif btn_id == GAMEPAD_BTN_R3:
            # Right stick click → toggle Motor B
            self._motion.toggle_motor_b()
            self._state.log("🎮 R3 → Toggle Motor B")

        elif btn_id == GAMEPAD_BTN_START:
            self._state.log("🎮 START pressed")

        elif btn_id == GAMEPAD_BTN_BACK:
            self._state.log("🎮 BACK pressed")

    def _handle_dpad(self):
        """Process D-pad (hat) input with edge detection."""
        if self._joystick is None:
            return
        if self._joystick.get_numhats() == 0:
            return

        try:
            hat = self._joystick.get_hat(GAMEPAD_HAT_INDEX)
        except Exception:
            return

        if hat == self._prev_hat:
            return

        self._prev_hat = hat
        hx, hy = hat

        if hy == 1:
            self._state.log("🎮 D-Up")
        elif hy == -1:
            self._state.log("🎮 D-Down")
        elif hx == -1:
            self._state.log("🎮 D-Left")
        elif hx == 1:
            self._state.log("🎮 D-Right")

    def _cleanup(self):
        """Clean shutdown of pygame."""
        try:
            if self._joystick:
                self._joystick.quit()
            if self._pygame_inited:
                pygame.quit()
        except Exception:
            pass