import time
import matplotlib.pyplot as plt
import numpy as np
from RobotApp import SharedState
from RobotBackend import RobotLogic
from autonomous_controller import AutonomousController, AutonomousMode
from motor_controller import MotionController

# --- Configuration ---
TEST_DURATION = 30  # seconds

def main():
    print("=" * 50)
    print("  DRY-RUN: HARDWARE OBJECT TRACKING VERIFICATION")
    print("=" * 50)
    
    # 1. Initialize the actual system state
    state = SharedState()
    motion = MotionController(state)
    
    # 2. Initialize actual Camera and YOLO model
    # This will load the 'yolov8n.pt' model defined in your config [cite: 1357]
    video = RobotLogic(state)
    
    # 3. Initialize Autonomous Controller
    auto = AutonomousController(state, motion)
    
    # --- MOCKING THE TELEMETRY LINK ---
    # We replace the send_command function so it logs to our test instead of the ROV
    history_time = []
    history_yaw = []
    
    def mocked_send_command(cmd):
        if cmd.name == "set_motion":
            # Extract the yaw value (-1.0 to 1.0) calculated by the controller [cite: 1651]
            yaw_val = cmd.kwargs.get("yaw", 0.0)
            history_time.append(time.time() - start_time)
            history_yaw.append(1500 + (yaw_val * 400)) # Convert to PWM for the graph
            
    state.send_command = mocked_send_command
    # ----------------------------------

    print("🚀 Starting Camera and YOLO... Please point the camera at a target.")
    video.start()
    auto.start()
    
    # Set mode to Object Track [cite: 1432]
    auto.set_mode(AutonomousMode.OBJECT_TRACK)
    
    start_time = time.time()
    try:
        while time.time() - start_time < TEST_DURATION:
            # Check if YOLO has found anything
            dets = state.get_latest_detections()
            if dets:
                target = dets[0]
                print(f"[{time.time()-start_time:05.2f}s] Tracking: {target['label']} "
                      f"({target['conf']:.2f}) | PWM: {history_yaw[-1] if history_yaw else 1500:.0f}")
            else:
                print(f"[{time.time()-start_time:05.2f}s] Searching for targets...")
            
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        pass

    print("\n⏹️ Test Complete. Shutting down...")
    video.stop()
    auto.stop()
    
    generate_hardware_tracking_plot(history_time, history_yaw)

def generate_hardware_tracking_plot(t_data, yaw_data):
    plt.style.use('seaborn-v0_8-darkgrid')
    plt.figure(figsize=(10, 6), dpi=120)
    
    plt.plot(t_data, yaw_data, color='#00A8FF', linewidth=2, label='Mocked Yaw Output')
    plt.axhline(1500, color='red', linestyle='--', alpha=0.6, label='Neutral (1500µs)')
    
    plt.title('Hardware-in-the-Loop: YOLOv8 Tracking Kinematic Response (Dry-Run)', fontweight='bold')
    plt.xlabel('Time (seconds)')
    plt.ylabel('Commanded Yaw PWM (µs)')
    plt.ylim(1100, 1900)
    plt.legend()
    
    plt.savefig(f"hardware_tracking_test_{int(time.time())}.png")
    plt.show()

if __name__ == "__main__":
    main()