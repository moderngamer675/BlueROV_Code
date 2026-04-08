"""
Object Tracking Logic Verification Test
Real hardware test with actual camera and water bottle
"""

import cv2
import numpy as np
import matplotlib.pyplot as plt
from collections import deque
import time

# ============================================================================
# CONFIGURATION
# ============================================================================

FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
FRAME_CENTER_X = FRAME_WIDTH / 2
PWM_NEUTRAL = 1500.0
PROPORTIONAL_GAIN = 200.0
DEADZONE_PIXELS = 20.0

# ============================================================================
# DATA STORAGE
# ============================================================================

class TestData:
    def __init__(self):
        self.timestamps = []
        self.target_x = []
        self.pixel_offset = []
        self.pwm_commands = []

data = TestData()

# ============================================================================
# YOLO DETECTION AND CONTROL
# ============================================================================

def detect_bottle(frame):
    """Detect water bottle using color-based detection (blue/white)"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    
    # Blue range for typical water bottles
    lower_blue = np.array([100, 50, 50])
    upper_blue = np.array([130, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    
    # White range as fallback
    lower_white = np.array([0, 0, 200])
    upper_white = np.array([180, 50, 255])
    mask_white = cv2.inRange(hsv, lower_white, upper_white)
    mask = cv2.bitwise_or(mask, mask_white)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    if contours:
        # Get largest contour
        largest = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest)
        center_x = x + w // 2
        return center_x, x, y, w, h
    
    return None, None, None, None, None

def compute_pwm(target_x_px):
    """Compute PWM command from target pixel position"""
    if target_x_px is None:
        return PWM_NEUTRAL
    
    # Pixel offset from center
    pixel_offset = target_x_px - FRAME_CENTER_X
    
    # Apply deadzone
    if abs(pixel_offset) <= DEADZONE_PIXELS:
        return PWM_NEUTRAL
    
    # Proportional control law
    normalized_offset = pixel_offset / (FRAME_WIDTH / 2)
    pwm = PWM_NEUTRAL + (normalized_offset * PROPORTIONAL_GAIN)
    
    # Saturate
    pwm = np.clip(pwm, 1300, 1700)
    
    return pwm, pixel_offset

# ============================================================================
# MAIN TEST
# ============================================================================

def run_test():
    """Run the object tracking test"""
    
    # Open camera
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    
    print("\n" + "="*70)
    print(" OBJECT TRACKING TEST - REAL HARDWARE")
    print("="*70)
    print("\nInstructions:")
    print("1. Position camera on floor pointing horizontally")
    print("2. Place water bottle in front of camera")
    print("3. Slowly move bottle from LEFT to RIGHT across camera view")
    print("4. Press 'q' to finish and generate plots")
    print("\n" + "="*70 + "\n")
    
    start_time = time.time()
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_count += 1
        elapsed = time.time() - start_time
        
        # Detect bottle
        target_x, box_x, box_y, box_w, box_h = detect_bottle(frame)
        
        if target_x is not None:
            # Compute PWM
            pwm, pixel_offset = compute_pwm(target_x)
            
            # Store data
            data.timestamps.append(elapsed)
            data.target_x.append(target_x)
            data.pixel_offset.append(pixel_offset)
            data.pwm_commands.append(pwm)
            
            # Draw bounding box
            cv2.rectangle(frame, (box_x, box_y), (box_x + box_w, box_y + box_h), (0, 255, 0), 2)
            cv2.circle(frame, (int(target_x), box_y + box_h // 2), 5, (0, 255, 0), -1)
            
            # Draw frame center line
            cv2.line(frame, (int(FRAME_CENTER_X), 0), (int(FRAME_CENTER_X), FRAME_HEIGHT), (255, 0, 0), 2)
            
            # Display info
            info_text = f"X: {target_x:.0f}px | Offset: {pixel_offset:.0f}px | PWM: {pwm:.0f}µs"
            cv2.putText(frame, info_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        else:
            cv2.putText(frame, "No bottle detected - move into view", (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        # Display frame count and time
        cv2.putText(frame, f"Time: {elapsed:.1f}s | Samples: {len(data.timestamps)}", (10, FRAME_HEIGHT - 20),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        cv2.imshow('Object Tracking Test', frame)
        
        # Press 'q' to quit
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()
    
    print(f"\n✓ Test completed - {len(data.timestamps)} samples collected\n")
    
    return data

# ============================================================================
# PLOTTING
# ============================================================================

def plot_results(data):
    """Create 2-subplot figure: target position and PWM output"""
    
    if not data.timestamps:
        print("No data collected!")
        return
    
    timestamps = np.array(data.timestamps)
    target_x = np.array(data.target_x)
    pixel_offset = np.array(data.pixel_offset)
    pwm = np.array(data.pwm_commands)
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9))
    
    # ---- TOP PLOT: TARGET POSITION ----
    ax1.plot(timestamps, target_x, linewidth=2.5, color='black', label='Target Position')
    ax1.axhline(FRAME_CENTER_X, color='green', linestyle='--', linewidth=2, label='Frame Center')
    ax1.fill_between(timestamps, FRAME_CENTER_X - DEADZONE_PIXELS, FRAME_CENTER_X + DEADZONE_PIXELS,
                     alpha=0.2, color='red', label='Deadzone')
    
    # Color regions by steering direction
    left_mask = pixel_offset < -DEADZONE_PIXELS
    right_mask = pixel_offset > DEADZONE_PIXELS
    center_mask = np.abs(pixel_offset) <= DEADZONE_PIXELS
    
    ax1.scatter(timestamps[left_mask], target_x[left_mask], s=30, color='#1f77b4', alpha=0.6, label='Steer LEFT')
    ax1.scatter(timestamps[center_mask], target_x[center_mask], s=50, color='green', alpha=0.8, label='Neutral')
    ax1.scatter(timestamps[right_mask], target_x[right_mask], s=30, color='#d62728', alpha=0.6, label='Steer RIGHT')
    
    ax1.set_ylabel('Target Position (pixels)', fontsize=12, fontweight='bold')
    ax1.set_title('Left/Right Steering Test - Target Sweep Trajectory', fontsize=13, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper right', fontsize=10)
    ax1.set_ylim([0, FRAME_WIDTH])
    
    # ---- BOTTOM PLOT: PWM OUTPUT ----
    ax2.plot(timestamps, pwm, linewidth=2.5, color='black', label='PWM Command')
    ax2.axhline(PWM_NEUTRAL, color='green', linestyle='--', linewidth=2, label='Neutral (1500µs)')
    ax2.axhline(1300, color='#1f77b4', linestyle=':', linewidth=2, label='Max Left')
    ax2.axhline(1700, color='#d62728', linestyle=':', linewidth=2, label='Max Right')
    
    # Color code by steering direction
    ax2.scatter(timestamps[left_mask], pwm[left_mask], s=30, color='#1f77b4', alpha=0.6)
    ax2.scatter(timestamps[center_mask], pwm[center_mask], s=50, color='green', alpha=0.8)
    ax2.scatter(timestamps[right_mask], pwm[right_mask], s=30, color='#d62728', alpha=0.6)
    
    ax2.fill_between(timestamps, 1300, PWM_NEUTRAL, alpha=0.1, color='#1f77b4')
    ax2.fill_between(timestamps, PWM_NEUTRAL, 1700, alpha=0.1, color='#d62728')
    
    ax2.set_xlabel('Time (seconds)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('PWM Command (microseconds)', fontsize=12, fontweight='bold')
    ax2.set_title('Yaw Control Output - Proportional Response to Target Motion', fontsize=13, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper right', fontsize=10)
    ax2.set_ylim([1250, 1750])
    
    plt.tight_layout()
    
    # Save figure
    plt.savefig('object_tracking_left_right_steering.png', dpi=300, bbox_inches='tight')
    print("✓ Figure saved: object_tracking_left_right_steering.png\n")
    
    plt.show()

def plot_linearity(data):
    """Create control law linearity plot"""
    
    pixel_offset = np.array(data.pixel_offset)
    pwm = np.array(data.pwm_commands)
    
    # Filter deadzone
    mask = np.abs(pixel_offset) > DEADZONE_PIXELS
    
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Active region
    ax.scatter(pixel_offset[mask], pwm[mask], s=80, alpha=0.7, 
              color='#1f77b4', edgecolor='black', linewidth=1, label='Active Control')
    
    # Deadzone region
    mask_deadzone = np.abs(pixel_offset) <= DEADZONE_PIXELS
    ax.scatter(pixel_offset[mask_deadzone], pwm[mask_deadzone], s=80, alpha=0.5, 
              color='green', edgecolor='black', linewidth=1, marker='s', label='Deadzone')
    
    # Ideal control line
    offset_range = np.linspace(-650, 650, 100)
    ideal_pwm = PWM_NEUTRAL + (offset_range / (FRAME_WIDTH / 2)) * PROPORTIONAL_GAIN
    ideal_pwm = np.clip(ideal_pwm, 1300, 1700)
    ax.plot(offset_range, ideal_pwm, linewidth=3, color='#d62728', linestyle='--', 
           alpha=0.8, label='Ideal Control Law')
    
    # Linear fit
    if np.sum(mask) > 2:
        z = np.polyfit(pixel_offset[mask], pwm[mask], 1)
        p = np.poly1d(z)
        ax.plot(offset_range, p(offset_range), linewidth=2.5, color='orange', 
               linestyle=':', alpha=0.9, label='Linear Fit')
        
        # Calculate R²
        residuals = pwm[mask] - p(pixel_offset[mask])
        ss_res = np.sum(residuals**2)
        ss_tot = np.sum((pwm[mask] - np.mean(pwm[mask]))**2)
        r_squared = 1 - (ss_res / ss_tot)
        
        textstr = f'R² = {r_squared:.5f}\n(Linearity Test)'
        ax.text(0.05, 0.95, textstr, transform=ax.transAxes, fontsize=11, 
               fontweight='bold', verticalalignment='top',
               bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    # Deadzone shading
    ax.axvspan(-DEADZONE_PIXELS, DEADZONE_PIXELS, alpha=0.15, color='green')
    ax.axhline(PWM_NEUTRAL, color='gray', linestyle=':', linewidth=1, alpha=0.5)
    ax.axvline(0, color='gray', linestyle=':', linewidth=1, alpha=0.5)
    
    ax.set_xlabel('Pixel Offset from Frame Center (pixels)', fontsize=12, fontweight='bold')
    ax.set_ylabel('PWM Command (microseconds)', fontsize=12, fontweight='bold')
    ax.set_title('Control Law Linearity Verification', fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=10)
    ax.set_xlim([-650, 650])
    ax.set_ylim([1250, 1750])
    
    plt.tight_layout()
    
    plt.savefig('object_tracking_control_linearity.png', dpi=300, bbox_inches='tight')
    print("✓ Figure saved: object_tracking_control_linearity.png\n")
    
    plt.show()

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # Run test
    data = run_test()
    
    # Generate plots
    if data.timestamps:
        print("Generating plots...\n")
        plot_results(data)
        plot_linearity(data)
        
        # Print summary
        print("\n" + "="*70)
        print(" TEST SUMMARY")
        print("="*70)
        print(f"Total samples: {len(data.timestamps)}")
        print(f"Test duration: {data.timestamps[-1]:.1f} seconds")
        print(f"Min target X: {min(data.target_x):.0f} pixels")
        print(f"Max target X: {max(data.target_x):.0f} pixels")
        print(f"Min PWM: {min(data.pwm_commands):.0f} µs")
        print(f"Max PWM: {max(data.pwm_commands):.0f} µs")
        print("="*70 + "\n")
    else:
        print("No data collected!")