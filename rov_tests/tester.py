#!/usr/bin/env python3
"""
sensor_listen_test.py — Run on TOPSIDE (Windows, VS Code)
Listens directly for ultrasonic sensor data on port 14553.
Displays a clean, updating dashboard until Ctrl+C is pressed.

Usage:
  python rov_tests/sensor_listen_test.py
"""

from pymavlink import mavutil
import time
import os

SENSOR_PORT = "udp:0.0.0.0:14553"

# Proximity thresholds (cm)
DANGER  = 30
CAUTION = 100

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def proximity_bar(value, max_cm=300, bar_width=30):
    """Create a visual bar showing distance."""
    if value == 0:
        return "[" + "?" * bar_width + "]  NO ECHO"
    fill = min(int((value / max_cm) * bar_width), bar_width)
    empty = bar_width - fill
    if value < DANGER:
        symbol = "!"
        status = "DANGER"
    elif value < CAUTION:
        symbol = "#"
        status = "CAUTION"
    else:
        symbol = "="
        status = "CLEAR"
    return f"[{symbol * fill}{'.' * empty}]  {status}"

def main():
    clear_screen()
    print("=" * 56)
    print("   ROV ULTRASONIC SENSOR MONITOR")
    print("=" * 56)
    print(f"   Port: {SENSOR_PORT}")
    print("   Press Ctrl+C to stop")
    print("-" * 56)
    print("   Waiting for sensor data...\n")

    mav = mavutil.mavlink_connection(SENSOR_PORT, source_system=255)

    latest = {"dst_front": None, "dst_left": None, "dst_right": None}
    labels = {"dst_front": "FRONT", "dst_left": " LEFT", "dst_right": "RIGHT"}
    count = 0
    cycles = 0
    start = time.time()

    try:
        while True:
            msg = mav.recv_match(type='NAMED_VALUE_FLOAT', blocking=True, timeout=0.5)
            if msg is None:
                continue

            name = msg.name.strip('\x00')
            if name not in latest:
                continue

            latest[name] = msg.value
            count += 1

            if count % 3 == 0:
                cycles += 1
                elapsed = time.time() - start

                clear_screen()
                print("=" * 56)
                print("   ROV ULTRASONIC SENSOR MONITOR")
                print("=" * 56)
                now = time.strftime("%H:%M:%S")
                print(f"   Cycle: {cycles:<6}  Elapsed: {elapsed:>5.1f}s  Time: {now}")
                print(f"   Press Ctrl+C to stop")
                print("-" * 56)

                for key in ["dst_front", "dst_left", "dst_right"]:
                    val = latest[key]
                    label = labels[key]
                    if val is None:
                        print(f"   {label}:    ---")
                    else:
                        bar = proximity_bar(val)
                        print(f"   {label}:  {val:>6.0f} cm  {bar}")

                print("-" * 56)
                print(f"   Total readings: {count}  ({count/max(elapsed,0.1):.0f}/sec)")
                print("=" * 56)

    except KeyboardInterrupt:
        elapsed = time.time() - start
        clear_screen()
        print("=" * 56)
        print("   ROV ULTRASONIC SENSOR MONITOR — STOPPED")
        print("=" * 56)

        if count == 0:
            print("\n   ⚠️  No ultrasonic sensor data received.\n")
        else:
            print(f"\n   Ran for:     {elapsed:.1f}s")
            print(f"   Readings:    {count} ({count/max(elapsed,0.1):.0f}/sec)")
            print(f"   Cycles:      {cycles}")
            print(f"\n   Last readings:")
            print(f"   {'-' * 48}")
            for key in ["dst_front", "dst_left", "dst_right"]:
                val = latest[key]
                label = labels[key]
                if val is not None:
                    bar = proximity_bar(val)
                    print(f"   {label}:  {val:>6.0f} cm  {bar}")
            print(f"   {'-' * 48}")
            print(f"\n   ✅ Sensor pipeline verified.")

        print("=" * 56)

if __name__ == "__main__":
    main()