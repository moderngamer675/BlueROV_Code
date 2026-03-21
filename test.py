import time
from pymavlink import mavutil

# --- CONFIGURATION ---
# We use 14551 because your RobotLogic starts MAVProxy with this output
LAPTOP_IP = '0.0.0.0' 
MAV_PORT = 14551

def run_motor_test():
    print(f"Connecting to ROV Telemetry on port {MAV_PORT}...")
    # Create the connection
    master = mavutil.mavlink_connection(f'udpin:{LAPTOP_IP}:{MAV_PORT}')

    # Wait for the heartbeat so we know the Pixhawk is awake
    print("Waiting for heartbeat from Pixhawk...")
    master.wait_heartbeat()
    print("Heartbeat received! System ID: %u, Component ID: %u" % (master.target_system, master.target_component))

    # Motor Test Function
    def test_single_motor(motor_num):
        """
        motor_num: 1-8
        throttle: 1550 (approx 15% power)
        duration: 2 seconds
        """
        print(f"TESTING MOTOR #{motor_num}...")
        
        # MAV_CMD_DO_MOTOR_TEST
        master.mav.command_long_send(
            master.target_system,
            master.target_component,
            mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST,
            0,            # Confirmation
            motor_num,    # Motor index
            1,            # Test type (1=PWM)
            1550,         # PWM value (1500 is stop, 1550 is slow forward)
            2,            # Duration in seconds
            1,            # Motor count
            0, 0          # Unused
        )
        time.sleep(3) # Wait for motor to finish and stop

    # Cycle through all 8 motors
    for i in range(1, 9):
        test_single_motor(i)

    print("--- ALL MOTOR TESTS COMPLETE ---")

if __name__ == "__main__":
    run_motor_test()