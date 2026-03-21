import time
import paramiko
from pymavlink import mavutil

# --- CONFIG ---
PI_IP = '192.168.2.2'
PI_USER = 'pi'
PI_PASS = 'raspberry'
LAPTOP_IP = '192.168.4.60'
PORT = 14550

class AuxSweep:
    def __init__(self):
        self.master = None

    def start_bridge(self):
        print(">> Resetting Pi Bridge...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(PI_IP, username=PI_USER, password=PI_PASS)
        ssh.exec_command("sudo pkill -9 -f mavproxy")
        time.sleep(1)
        
        cmd = (f"nohup /home/pi/rov-env/bin/python3 /home/pi/rov-env/bin/mavproxy.py "
               f"--master=/dev/ttyACM0 --baudrate=115200 "
               f"--out=udp:{LAPTOP_IP}:{PORT} --daemon > /dev/null 2>&1 &")
        ssh.exec_command(cmd)
        ssh.close()

    def connect(self):
        self.master = mavutil.mavlink_connection(f'udp:0.0.0.0:{PORT}')
        self.master.wait_heartbeat()
        print(">> Connected. Setting MANUAL mode and ARMING...")
        # Some Pixhawks disable AUX outputs until the system is ARMED
        self.master.set_mode('MANUAL')
        self.master.arducopter_arm()
        time.sleep(1)

    def sweep(self):
        # Targets: Ch 12 (AUX 4), Ch 13 (AUX 5), Ch 14 (AUX 6)
        channels = [11, 12, 13] # Indices for 0-based list
        
        print(">> Moving AUX 4, 5, 6 to 1900 PWM...")
        overrides = [65535] * 18
        for c in channels:
            overrides[c] = 1900
        self.master.mav.rc_channels_override_send(self.master.target_system, self.master.target_component, *overrides)
        time.sleep(2)

        print(">> Moving AUX 4, 5, 6 to 1100 PWM...")
        for c in channels:
            overrides[c] = 1100
        self.master.mav.rc_channels_override_send(self.master.target_system, self.master.target_component, *overrides)
        time.sleep(2)

        print(">> Returning to Neutral (1500)...")
        for c in channels:
            overrides[c] = 1500
        self.master.mav.rc_channels_override_send(self.master.target_system, self.master.target_component, *overrides)
        
        self.master.arducopter_disarm()
        print(">> Sweep Complete.")

if __name__ == "__main__":
    test = AuxSweep()
    test.start_bridge()
    test.connect()
    test.sweep()