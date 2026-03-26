# rov_tests/check_battery.py
# Check battery monitor configuration
# Run with: python rov_tests/check_battery.py

from pymavlink import mavutil
from rov_config import MAV_PORT
import time

print("Checking battery configuration...")

mav = mavutil.mavlink_connection(f'udp:0.0.0.0:{MAV_PORT}')
mav.wait_heartbeat(timeout=10)
print("Connected.\n")

# Request specific parameters related to battery
params_to_check = [
    'BATT_MONITOR',
    'BATT_VOLT_PIN',
    'BATT_CURR_PIN',
    'BATT_VOLT_MULT',
    'BATT_AMP_PERVLT',
    'BATT_CAPACITY',
]

print("Battery Parameters:")
print(f"{'Parameter':<20} {'Value'}")
print("─" * 35)

for param in params_to_check:
    mav.mav.param_request_read_send(
        mav.target_system,
        mav.target_component,
        param.encode('utf-8'),
        -1
    )
    msg = mav.recv_match(
        type='PARAM_VALUE',
        blocking=True,
        timeout=3
    )
    if msg:
        print(f"  {msg.param_id:<18} {msg.param_value}")
    else:
        print(f"  {param:<18} (no response)")
    time.sleep(0.2)

print("\nIf BATT_MONITOR = 0 → battery not configured")
print("Set to 4 in QGroundControl for analog sensor")