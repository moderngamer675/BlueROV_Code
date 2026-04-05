"""
motor_test.py — Test motor commands from topside to Arduino via Pi
Sends NAMED_VALUE_FLOAT messages on port 14554 to the Pi's sensor_bridge.py
which forwards them as serial commands to the Arduino.

Also listens on port 14553 for motor status feedback and 4-sensor data.

Usage: python rov_tests/motor_test.py
"""

from pymavlink import mavutil
import time
import threading

# ── Send connection (topside → Pi port 14554) ──
print("Connecting to Pi motor command port...")
mav_send = mavutil.mavlink_connection(
    "udpout:192.168.2.2:14554",
    source_system=255,
    source_component=0
)

# ── Receive connection (Pi port 14553 → topside) for feedback ──
print("Listening for sensor data + motor feedback on port 14553...")
mav_recv = mavutil.mavlink_connection(
    "udp:0.0.0.0:14553",
    source_system=255,
    source_component=0
)

def feedback_listener():
    """Background thread: print sensor data and motor status from Pi"""
    while True:
        try:
            msg = mav_recv.recv_match(type="NAMED_VALUE_FLOAT", blocking=True, timeout=2.0)
            if msg is None:
                continue
            name = msg.name
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            name = name.rstrip("\x00").strip()
            value = msg.value

            if name.startswith("mot_"):
                state = "ON" if value >= 1.0 else "OFF"
                print(f"  ← FEEDBACK: {name} = {state}")
            # Sensor data is silent here to avoid flooding — uncomment below to see it:
            # elif name.startswith("dst_"):
            #     print(f"  ← SENSOR: {name} = {int(value)}cm")
        except:
            pass

# Start feedback listener
t = threading.Thread(target=feedback_listener, daemon=True)
t.start()

def send_motor_command(name, value):
    """Send a motor command as NAMED_VALUE_FLOAT"""
    time_boot_ms = int(time.time() * 1000) & 0xFFFFFFFF
    mav_send.mav.named_value_float_send(
        time_boot_ms,
        name.encode("utf-8"),
        float(value)
    )
    state = "ON" if value == 1.0 else "OFF"
    print(f"  → Sent: {name} = {value} ({state})")

print("\n" + "=" * 50)
print("  DC MOTOR REMOTE TEST (with 4-sensor feedback)")
print("=" * 50)
print("  1 = Motor A ON        2 = Motor A OFF")
print("  3 = Motor B ON        4 = Motor B OFF")
print("  5 = Both ON           6 = Both OFF")
print("  s = Show sensors (one snapshot)")
print("  q = Quit (turns both off first)")
print("=" * 50 + "\n")

try:
    while True:
        choice = input("Command (1-6, s, q): ").strip().lower()
        
        if choice == "1":
            send_motor_command("mot_a", 1.0)
        elif choice == "2":
            send_motor_command("mot_a", 0.0)
        elif choice == "3":
            send_motor_command("mot_b", 1.0)
        elif choice == "4":
            send_motor_command("mot_b", 0.0)
        elif choice == "5":
            send_motor_command("mot_all", 1.0)
        elif choice == "6":
            send_motor_command("mot_all", 0.0)
        elif choice == "s":
            print("  Listening for sensor snapshot (2 seconds)...")
            end = time.time() + 2
            while time.time() < end:
                msg = mav_recv.recv_match(type="NAMED_VALUE_FLOAT", blocking=True, timeout=0.5)
                if msg:
                    name = msg.name
                    if isinstance(name, bytes):
                        name = name.decode("utf-8", errors="replace")
                    name = name.rstrip("\x00").strip()
                    if name.startswith("dst_"):
                        print(f"    {name}: {int(msg.value)}cm")
        elif choice == "q":
            print("Shutting down — turning off both motors...")
            send_motor_command("mot_all", 0.0)
            time.sleep(0.5)
            break
        else:
            print("  Invalid. Use 1-6, s, or q.")

except KeyboardInterrupt:
    print("\nCtrl+C — turning off both motors...")
    send_motor_command("mot_all", 0.0)
    time.sleep(0.5)

print("Done.")