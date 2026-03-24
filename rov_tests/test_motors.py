# rov_tests/check_disarm.py
# Checks if ArduSub is disarming between motor tests

from pymavlink import mavutil
from Vision.rov_config import MAV_PORT
import time

mav = mavutil.mavlink_connection(
    f'udp:0.0.0.0:{MAV_PORT}',
    source_system=255
)
mav.wait_heartbeat()

def send_hb():
    mav.mav.heartbeat_send(
        mavutil.mavlink.MAV_TYPE_GCS,
        mavutil.mavlink.MAV_AUTOPILOT_INVALID,
        0, 0, 0
    )

def send_neutral():
    mav.mav.manual_control_send(
        mav.target_system, 0, 0, 500, 0, 0
    )

def is_armed():
    msg = mav.recv_match(
        type='HEARTBEAT', blocking=True, timeout=1)
    if msg:
        return bool(
            msg.base_mode &
            mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        )
    return False

# Set MANUAL and arm
mode_id = mav.mode_mapping().get('MANUAL')
mav.mav.set_mode_send(
    mav.target_system,
    mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
    mode_id
)
time.sleep(1.5)

mav.mav.command_long_send(
    mav.target_system,
    mav.target_component,
    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
    0, 1, 21196, 0, 0, 0, 0, 0
)
time.sleep(2)
print(f"Armed at start: {is_armed()}")

# Simulate what happens between motor tests
print("\nSimulating gap between motor tests...")
print("Sending neutral but NO manual_control for 3 seconds")
print("Watching arm state every 0.5s:\n")

for i in range(12):
    send_hb()
    # Deliberately NOT sending manual_control
    armed = is_armed()
    print(f"  t={i*0.5:.1f}s  Armed: "
          f"{'✅ YES' if armed else '❌ DISARMED ← here'}")
    time.sleep(0.5)
    if not armed:
        print("\n  ⚠️  ArduSub auto-disarmed!")
        print("  This is why motors 2-6 always fail")
        break