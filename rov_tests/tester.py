"""
gamepad_test.py — Xbox 360 controller axis/button identification tool.
Run this FIRST to verify your controller mapping before using with ROV.

Displays live values for all axes, buttons, and hats.
Press Ctrl+C to exit.
"""

import pygame
import time
import os

def main():
    # Must init display subsystem for event.pump() to work
    # We use a tiny hidden window — no visible pygame window needed
    os.environ['SDL_VIDEO_WINDOW_POS'] = '-1000,-1000'  # off-screen
    pygame.init()
    pygame.display.set_mode((1, 1))  # minimal hidden window

    print("=" * 60)
    print("XBOX 360 CONTROLLER TEST")
    print("=" * 60)
    print(f"Controllers found: {pygame.joystick.get_count()}")

    if pygame.joystick.get_count() == 0:
        print("\n❌ No controller detected!")
        print("   1. Plug in Xbox 360 controller")
        print("   2. Wait for Windows to install drivers")
        print("   3. Run this script again")
        pygame.quit()
        return

    js = pygame.joystick.Joystick(0)
    js.init()

    print(f"\nController: {js.get_name()}")
    print(f"Axes: {js.get_numaxes()}")
    print(f"Buttons: {js.get_numbuttons()}")
    print(f"Hats: {js.get_numhats()}")
    print()
    print("Move sticks, press buttons, and press triggers.")
    print("Note which axis/button numbers correspond to each input.")
    print("Press Ctrl+C to exit.")
    print()
    time.sleep(2)  # give user time to read before screen clears

    try:
        while True:
            pygame.event.pump()

            # Clear screen (Windows)
            os.system('cls' if os.name == 'nt' else 'clear')

            print(f"Controller: {js.get_name()}")
            print(f"Axes: {js.get_numaxes()} | Buttons: {js.get_numbuttons()} | Hats: {js.get_numhats()}")
            print(f"{'=' * 60}")

            # Axes
            print("\nAXES:")
            for i in range(js.get_numaxes()):
                value = js.get_axis(i)
                # Build visual bar
                bar_width = 20
                bar_pos = int((value + 1.0) / 2.0 * bar_width)
                bar_pos = max(0, min(bar_width, bar_pos))
                bar = "░" * bar_pos + "█" + "░" * (bar_width - bar_pos)
                
                # Highlight if significantly deflected
                if abs(value) > 0.15:
                    marker = " ◄◄◄ ACTIVE"
                else:
                    marker = ""
                    
                print(f"  Axis {i}: {value:+.3f}  [{bar}]{marker}")

            # Buttons
            print("\nBUTTONS:")
            btn_line = "  "
            for i in range(js.get_numbuttons()):
                state = js.get_button(i)
                if state:
                    btn_line += f"[{i}:■] "  # pressed
                else:
                    btn_line += f"[{i}:□] "  # released
                if (i + 1) % 6 == 0:
                    print(btn_line)
                    btn_line = "  "
            if btn_line.strip():
                print(btn_line)

            # Hats
            print("\nHATS (D-PAD):")
            for i in range(js.get_numhats()):
                hat = js.get_hat(i)
                hx, hy = hat
                direction = ""
                if hy == 1:  direction += "UP "
                if hy == -1: direction += "DOWN "
                if hx == -1: direction += "LEFT "
                if hx == 1:  direction += "RIGHT "
                if not direction: direction = "CENTER"
                print(f"  Hat {i}: ({hx:+d}, {hy:+d})  →  {direction}")

            print(f"\n{'=' * 60}")
            print("IDENTIFICATION GUIDE:")
            print("  1. Push LEFT stick UP      → which axis goes NEGATIVE?  = LEFT_Y")
            print("  2. Push LEFT stick RIGHT   → which axis goes POSITIVE?  = LEFT_X")
            print("  3. Push RIGHT stick RIGHT  → which axis goes POSITIVE?  = RIGHT_X")
            print("  4. Push RIGHT stick UP     → which axis goes NEGATIVE?  = RIGHT_Y")
            print("  5. Pull LEFT trigger (LT)  → which axis changes?        = LT")
            print("  6. Pull RIGHT trigger (RT) → which axis changes?        = RT")
            print()
            print("  7. Press A → note button number")
            print("  8. Press B → note button number")
            print("  9. Press X → note button number")
            print(" 10. Press Y → note button number")
            print(" 11. Press LB → note button number")
            print(" 12. Press RB → note button number")
            print(" 13. Press BACK → note button number")
            print(" 14. Press START → note button number")
            print()
            print("Press Ctrl+C when done")

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n\nDone!")
        js.quit()
        pygame.quit()


if __name__ == "__main__":
    main()