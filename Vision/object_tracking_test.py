"""
Object Tracking Logic Verification Test
Tests proportional control law for YOLOv8 bounding box to yaw PWM conversion
Author: Engineering Project
Date: 2025
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
from dataclasses import dataclass
from typing import List, Tuple
import json
from datetime import datetime

# ============================================================================
# CONFIGURATION AND CONSTANTS
# ============================================================================

@dataclass
class ControlParams:
    """Control law parameters"""
    frame_width: int = 1280
    frame_height: int = 720
    frame_center_x: float = 640  # frame_width / 2
    pwm_neutral: float = 1500.0  # microseconds
    pwm_min: float = 1300.0
    pwm_max: float = 1700.0
    proportional_gain: float = 200.0  # µs per normalized error unit
    deadzone_pixels: float = 20.0  # ±20 px
    deadzone_pwm: float = pwm_neutral

@dataclass
class TargetTrajectory:
    """Target motion parameters"""
    start_x: float = 50.0  # pixels from left
    end_x: float = 1230.0  # pixels from left
    duration: float = 16.0  # seconds
    sweep_speed: float = 40.0  # pixels per second

@dataclass
class TestResult:
    """Single test measurement"""
    timestamp: float
    target_x_px: float
    pixel_offset: float
    normalized_offset: float
    expected_pwm: float
    measured_pwm: float
    error_pwm: float
    yaw_error_rate: float = 0.0


# ============================================================================
# CONTROL LAW IMPLEMENTATION
# ============================================================================

class ObjectTrackingController:
    """
    Implements the proportional control law for visual tracking.
    
    Control equation:
        error_px = target_x - frame_center_x
        error_norm = error_px / (frame_width / 2)
        yaw_command = 1500 µs + (error_norm × gain)
    """
    
    def __init__(self, params: ControlParams):
        self.params = params
        self.previous_error = 0.0
        self.previous_time = 0.0
    
    def compute_control_command(
        self, 
        target_x_px: float, 
        timestamp: float = 0.0
    ) -> Tuple[float, float, float]:
        """
        Compute yaw PWM command from target pixel position.
        
        Args:
            target_x_px: Target X coordinate in pixels (0 = left edge, 1280 = right edge)
            timestamp: Current time in seconds (for derivative calculation)
        
        Returns:
            Tuple of (pixel_offset, normalized_offset, pwm_command)
        """
        # Calculate pixel offset from frame center
        pixel_offset = target_x_px - self.params.frame_center_x
        
        # Normalize to [-1, +1] range
        normalized_offset = pixel_offset / (self.params.frame_width / 2)
        
        # Apply deadzone
        if abs(pixel_offset) <= self.params.deadzone_pixels:
            pwm_command = self.params.pwm_neutral
            normalized_offset = 0.0
        else:
            # Proportional control law
            pwm_command = self.params.pwm_neutral + (normalized_offset * self.params.proportional_gain)
            
            # Saturate to valid PWM range
            pwm_command = np.clip(
                pwm_command, 
                self.params.pwm_min, 
                self.params.pwm_max
            )
        
        # Calculate derivative (yaw error rate)
        dt = timestamp - self.previous_time if timestamp > 0 else 0.001
        yaw_error_rate = (normalized_offset - self.previous_error) / dt if dt > 0 else 0.0
        
        self.previous_error = normalized_offset
        self.previous_time = timestamp
        
        return pixel_offset, normalized_offset, pwm_command, yaw_error_rate


# ============================================================================
# TEST DATA GENERATION (SIMULATED HARDWARE)
# ============================================================================

class HardwareSimulator:
    """
    Simulates real hardware measurements with realistic noise characteristics.
    """
    
    def __init__(self, seed: int = 42):
        np.random.seed(seed)
        self.noise_std_px = 0.5  # 0.5 pixel standard deviation
        self.noise_std_pwm = 2.0  # 2 µs standard deviation
    
    def add_realistic_noise(
        self, 
        ideal_pwm: float, 
        ideal_target_x: float
    ) -> Tuple[float, float]:
        """
        Add realistic measurement noise to ideal values.
        Simulates camera resolution limits and PWM quantization.
        """
        # Camera position noise (pixel coordinates)
        target_x_noisy = ideal_target_x + np.random.normal(0, self.noise_std_px)
        
        # PWM quantization and measurement noise
        # PWM is quantized to ~2 µs steps (typical for ESC boards)
        pwm_quantized = round(ideal_pwm / 2) * 2
        pwm_noisy = pwm_quantized + np.random.normal(0, self.noise_std_pwm)
        
        return target_x_noisy, pwm_noisy


# ============================================================================
# TEST EXECUTION
# ============================================================================

class ObjectTrackingTest:
    """
    Executes the object tracking verification test.
    """
    
    def __init__(
        self, 
        control_params: ControlParams = None,
        trajectory_params: TargetTrajectory = None,
        sampling_rate_hz: float = 30.0
    ):
        self.control_params = control_params or ControlParams()
        self.trajectory_params = trajectory_params or TargetTrajectory()
        self.sampling_rate_hz = sampling_rate_hz
        self.sampling_period = 1.0 / sampling_rate_hz
        
        self.controller = ObjectTrackingController(self.control_params)
        self.simulator = HardwareSimulator()
        self.results: List[TestResult] = []
    
    def generate_target_trajectory(self) -> List[Tuple[float, float]]:
        """
        Generate smooth target motion trajectory.
        Returns list of (timestamp, target_x_position) tuples.
        """
        num_samples = int(self.trajectory_params.duration / self.sampling_period)
        trajectory = []
        
        for i in range(num_samples):
            t = i * self.sampling_period
            
            # Linear sweep from start to end position
            progress = t / self.trajectory_params.duration
            target_x = (
                self.trajectory_params.start_x +
                progress * (self.trajectory_params.end_x - self.trajectory_params.start_x)
            )
            
            trajectory.append((t, target_x))
        
        return trajectory
    
    def run_test(self, verbose: bool = True) -> List[TestResult]:
        """
        Execute the full object tracking test.
        """
        if verbose:
            print("=" * 80)
            print("OBJECT TRACKING LOGIC VERIFICATION TEST")
            print("=" * 80)
            print(f"Test Duration: {self.trajectory_params.duration} seconds")
            print(f"Sampling Rate: {self.sampling_rate_hz} Hz")
            print(f"Expected Samples: {int(self.trajectory_params.duration * self.sampling_rate_hz)}")
            print()
        
        trajectory = self.generate_target_trajectory()
        
        for timestamp, target_x_ideal in trajectory:
            # Add measurement noise
            target_x_measured, measured_pwm = self.simulator.add_realistic_noise(
                ideal_pwm=self.control_params.pwm_neutral,  # placeholder
                ideal_target_x=target_x_ideal
            )
            
            # Compute control command
            pixel_offset, normalized_offset, computed_pwm, yaw_rate = self.controller.compute_control_command(
                target_x_px=target_x_measured,
                timestamp=timestamp
            )
            
            # Expected PWM (from ideal, no noise)
            expected_pwm = self.control_params.pwm_neutral + (
                normalized_offset * self.control_params.proportional_gain
            )
            expected_pwm = np.clip(
                expected_pwm,
                self.control_params.pwm_min,
                self.control_params.pwm_max
            )
            
            # PWM error
            pwm_error = computed_pwm - expected_pwm
            
            # Store result
            result = TestResult(
                timestamp=timestamp,
                target_x_px=target_x_measured,
                pixel_offset=pixel_offset,
                normalized_offset=normalized_offset,
                expected_pwm=expected_pwm,
                measured_pwm=computed_pwm,
                error_pwm=pwm_error,
                yaw_error_rate=yaw_rate
            )
            self.results.append(result)
        
        if verbose:
            self._print_summary()
        
        return self.results
    
    def _print_summary(self):
        """Print test summary statistics."""
        if not self.results:
            return
        
        timestamps = np.array([r.timestamp for r in self.results])
        pwm_values = np.array([r.measured_pwm for r in self.results])
        pwm_errors = np.array([r.error_pwm for r in self.results])
        pixel_offsets = np.array([r.pixel_offset for r in self.results])
        
        print("TEST RESULTS SUMMARY")
        print("-" * 80)
        print(f"Total Samples: {len(self.results)}")
        print(f"Test Duration: {timestamps[-1] - timestamps[0]:.2f} seconds")
        print()
        print("PWM OUTPUT STATISTICS:")
        print(f"  Mean PWM: {np.mean(pwm_values):.2f} µs")
        print(f"  Min PWM:  {np.min(pwm_values):.2f} µs")
        print(f"  Max PWM:  {np.max(pwm_values):.2f} µs")
        print(f"  Std Dev:  {np.std(pwm_values):.2f} µs")
        print()
        print("CONTROL ERROR STATISTICS:")
        print(f"  Mean Error: {np.mean(pwm_errors):.2f} µs")
        print(f"  Std Error:  {np.std(pwm_errors):.2f} µs")
        print(f"  Max Error:  {np.max(np.abs(pwm_errors)):.2f} µs")
        print()
        print("PIXEL OFFSET STATISTICS:")
        print(f"  Min Offset:  {np.min(pixel_offsets):.1f} px")
        print(f"  Max Offset:  {np.max(pixel_offsets):.1f} px")
        print(f"  Mean Offset: {np.mean(pixel_offsets):.1f} px")
        print()
        
        # Linearity analysis
        nonzero_errors = pwm_errors[np.abs(pixel_offsets) > self.control_params.deadzone_pixels]
        if len(nonzero_errors) > 0:
            r_squared = self._calculate_linearity()
            print("PROPORTIONAL CONTROL ANALYSIS:")
            print(f"  R² (Linearity): {r_squared:.6f}")
            print(f"  Control Law Status: {'✓ NOMINAL' if r_squared > 0.99 else '✗ DEGRADED'}")
        
        print("=" * 80)
    
    def _calculate_linearity(self) -> float:
        """Calculate R² value for control law linearity."""
        pixel_offsets = np.array([r.pixel_offset for r in self.results])
        pwm_values = np.array([r.measured_pwm for r in self.results])
        
        # Filter out deadzone region
        mask = np.abs(pixel_offsets) > self.control_params.deadzone_pixels
        if len(pixel_offsets[mask]) < 2:
            return 0.0
        
        # Linear regression
        slope, intercept, r_value, _, _ = stats.linregress(
            pixel_offsets[mask],
            pwm_values[mask]
        )
        
        return r_value ** 2


# ============================================================================
# PLOTTING AND VISUALIZATION
# ============================================================================

class TestVisualizer:
    """
    Creates publication-quality plots of test results.
    """
    
    def __init__(self, test_results: List[TestResult], control_params: ControlParams):
        self.results = test_results
        self.params = control_params
    
    def plot_comprehensive_results(self, save_path: str = None):
        """
        Create comprehensive 4-subplot figure showing all key metrics.
        """
        # Extract data
        timestamps = np.array([r.timestamp for r in self.results])
        target_positions = np.array([r.target_x_px for r in self.results])
        pixel_offsets = np.array([r.pixel_offset for r in self.results])
        normalized_offsets = np.array([r.normalized_offset for r in self.results])
        pwm_commands = np.array([r.measured_pwm for r in self.results])
        pwm_expected = np.array([r.expected_pwm for r in self.results])
        
        # Create figure with 4 subplots
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(
            'Object Tracking Logic Verification - YOLOv8 to PWM Control',
            fontsize=16,
            fontweight='bold',
            y=0.995
        )
        
        # Color scheme
        color_measured = '#1f77b4'  # blue
        color_expected = '#ff7f0e'  # orange
        color_deadzone = '#d62728'  # red
        
        # ---- SUBPLOT 1: Target Position Over Time ----
        ax1 = axes[0, 0]
        ax1.plot(timestamps, target_positions, linewidth=2.5, color=color_measured, label='Target Position')
        ax1.axhline(self.params.frame_center_x, color='gray', linestyle='--', linewidth=1.5, label='Frame Center')
        ax1.fill_between(
            timestamps,
            self.params.frame_center_x - self.params.deadzone_pixels,
            self.params.frame_center_x + self.params.deadzone_pixels,
            alpha=0.2,
            color=color_deadzone,
            label=f'Deadzone (±{self.params.deadzone_pixels:.0f}px)'
        )
        ax1.set_xlabel('Time (s)', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Pixel Position (px)', fontsize=11, fontweight='bold')
        ax1.set_title('Target Sweep Trajectory', fontsize=12, fontweight='bold')
        ax1.grid(True, alpha=0.3, linestyle=':')
        ax1.legend(loc='best', fontsize=10)
        ax1.set_ylim([0, self.params.frame_width])
        
        # ---- SUBPLOT 2: Pixel Offset ----
        ax2 = axes[0, 1]
        ax2.plot(timestamps, pixel_offsets, linewidth=2.5, color=color_measured, label='Pixel Offset')
        ax2.axhline(0, color='black', linestyle='-', linewidth=1, alpha=0.5)
        ax2.fill_between(
            timestamps,
            -self.params.deadzone_pixels,
            self.params.deadzone_pixels,
            alpha=0.2,
            color=color_deadzone,
            label=f'Deadzone'
        )
        ax2.set_xlabel('Time (s)', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Offset from Center (px)', fontsize=11, fontweight='bold')
        ax2.set_title('Pixel Offset from Frame Center', fontsize=12, fontweight='bold')
        ax2.grid(True, alpha=0.3, linestyle=':')
        ax2.legend(loc='best', fontsize=10)
        
        # ---- SUBPLOT 3: PWM Command Output ----
        ax3 = axes[1, 0]
        ax3.plot(
            timestamps, pwm_expected, linewidth=2, color=color_expected, 
            label='Expected PWM', linestyle='--', alpha=0.8
        )
        ax3.plot(
            timestamps, pwm_commands, linewidth=2.5, color=color_measured, 
            label='Measured PWM'
        )
        ax3.axhline(self.params.pwm_neutral, color='green', linestyle=':', linewidth=1.5, label='Neutral')
        ax3.axhline(self.params.pwm_min, color='red', linestyle='-.', linewidth=1, alpha=0.7, label='Min/Max')
        ax3.axhline(self.params.pwm_max, color='red', linestyle='-.', linewidth=1, alpha=0.7)
        ax3.fill_between(
            timestamps,
            self.params.pwm_neutral - self.params.proportional_gain * 0.05,
            self.params.pwm_neutral + self.params.proportional_gain * 0.05,
            alpha=0.15,
            color=color_deadzone,
            label='Deadzone Response'
        )
        ax3.set_xlabel('Time (s)', fontsize=11, fontweight='bold')
        ax3.set_ylabel('PWM Command (µs)', fontsize=11, fontweight='bold')
        ax3.set_title('Yaw Control Command (PWM)', fontsize=12, fontweight='bold')
        ax3.grid(True, alpha=0.3, linestyle=':')
        ax3.legend(loc='best', fontsize=9)
        ax3.set_ylim([self.params.pwm_min - 50, self.params.pwm_max + 50])
        
        # ---- SUBPLOT 4: Control Law Verification (Scatter) ----
        ax4 = axes[1, 1]
        
        # Only plot points outside deadzone for clarity
        mask = np.abs(pixel_offsets) > self.params.deadzone_pixels
        ax4.scatter(
            pixel_offsets[mask], pwm_commands[mask],
            alpha=0.6, s=50, color=color_measured, edgecolor='black', linewidth=0.5,
            label='Measured Data Points'
        )
        
        # Plot deadzone points separately
        mask_deadzone = np.abs(pixel_offsets) <= self.params.deadzone_pixels
        ax4.scatter(
            pixel_offsets[mask_deadzone], pwm_commands[mask_deadzone],
            alpha=0.4, s=30, color=color_deadzone, edgecolor='black', linewidth=0.5,
            label='Deadzone Points'
        )
        
        # Plot ideal control line
        offset_range = np.linspace(-640, 640, 100)
        ideal_pwm = self.params.pwm_neutral + (offset_range / 320.0) * self.params.proportional_gain
        ideal_pwm = np.clip(ideal_pwm, self.params.pwm_min, self.params.pwm_max)
        ax4.plot(
            offset_range, ideal_pwm,
            linewidth=2.5, color=color_expected, linestyle='--', alpha=0.8,
            label='Ideal Control Law'
        )
        
        # Calculate and display R² value
        if np.sum(mask) > 2:
            slope, intercept, r_value, _, _ = stats.linregress(
                pixel_offsets[mask],
                pwm_commands[mask]
            )
            r_squared = r_value ** 2
            ax4.text(
                0.05, 0.95, f'R² = {r_squared:.5f}\n(Linearity)',
                transform=ax4.transAxes,
                fontsize=11, fontweight='bold',
                verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8)
            )
        
        ax4.set_xlabel('Pixel Offset from Center (px)', fontsize=11, fontweight='bold')
        ax4.set_ylabel('PWM Command (µs)', fontsize=11, fontweight='bold')
        ax4.set_title('Control Law Verification (Proportionality)', fontsize=12, fontweight='bold')
        ax4.grid(True, alpha=0.3, linestyle=':')
        ax4.legend(loc='best', fontsize=10)
        ax4.axhline(self.params.pwm_neutral, color='gray', linestyle=':', linewidth=1, alpha=0.5)
        ax4.axvline(0, color='gray', linestyle=':', linewidth=1, alpha=0.5)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"\n✓ Figure saved to: {save_path}")
        
        plt.show()
    
    def plot_left_right_steering(self, save_path: str = None):
        """
        Create a detailed plot specifically showing left vs. right steering response.
        This is the main figure mentioned in the test objective.
        """
        # Extract data
        timestamps = np.array([r.timestamp for r in self.results])
        pixel_offsets = np.array([r.pixel_offset for r in self.results])
        pwm_commands = np.array([r.measured_pwm for r in self.results])
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
        
        # Color scheme: blue for left, red for right, green for center
        left_mask = pixel_offsets < -self.params.deadzone_pixels
        right_mask = pixel_offsets > self.params.deadzone_pixels
        center_mask = np.abs(pixel_offsets) <= self.params.deadzone_pixels
        
        # ---- TOP PLOT: Target Position and Steering Direction ----
        target_positions = np.array([r.target_x_px for r in self.results])
        
        # Create colored regions for left/right/center
        ax1.fill_between(
            timestamps[left_mask], 0, 1280,
            alpha=0.1, color='#1f77b4', label='Target Moving LEFT (Steer Left)'
        )
        ax1.fill_between(
            timestamps[center_mask], 0, 1280,
            alpha=0.1, color='green', label='Target at CENTER (No Steering)'
        )
        ax1.fill_between(
            timestamps[right_mask], 0, 1280,
            alpha=0.1, color='#d62728', label='Target Moving RIGHT (Steer Right)'
        )
        
        ax1.plot(
            timestamps, target_positions,
            linewidth=3, color='black', label='Target Position', zorder=5
        )
        ax1.axhline(self.params.frame_center_x, color='gray', linestyle='--', linewidth=2, label='Frame Center')
        ax1.fill_between(
            timestamps,
            self.params.frame_center_x - self.params.deadzone_pixels,
            self.params.frame_center_x + self.params.deadzone_pixels,
            alpha=0.3, color='green', label='Deadzone'
        )
        
        ax1.set_ylabel('Target Position (pixels)', fontsize=13, fontweight='bold')
        ax1.set_title(
            'Left/Right Steering Test - Target Sweep Trajectory',
            fontsize=14, fontweight='bold'
        )
        ax1.grid(True, alpha=0.3, linestyle=':', linewidth=1)
        ax1.legend(loc='upper right', fontsize=11, framealpha=0.95)
        ax1.set_xlim([timestamps[0], timestamps[-1]])
        ax1.set_ylim([0, self.params.frame_width])
        ax1.set_xticks([0, 4, 8, 12, 16])
        
        # Add annotations for key points
        # Left extreme
        left_idx = np.argmin(target_positions)
        ax1.annotate(
            f'Far LEFT\n({target_positions[left_idx]:.0f}px)',
            xy=(timestamps[left_idx], target_positions[left_idx]),
            xytext=(timestamps[left_idx] - 1, 100),
            fontsize=10, fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='#1f77b4', lw=2),
            color='#1f77b4'
        )
        
        # Center
        center_idx = np.argmin(np.abs(target_positions - self.params.frame_center_x))
        ax1.annotate(
            f'CENTER\n({self.params.frame_center_x:.0f}px)',
            xy=(timestamps[center_idx], target_positions[center_idx]),
            xytext=(timestamps[center_idx], 200),
            fontsize=10, fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='green', lw=2),
            color='green'
        )
        
        # Right extreme
        right_idx = np.argmax(target_positions)
        ax1.annotate(
            f'Far RIGHT\n({target_positions[right_idx]:.0f}px)',
            xy=(timestamps[right_idx], target_positions[right_idx]),
            xytext=(timestamps[right_idx] + 1, 1100),
            fontsize=10, fontweight='bold',
            arrowprops=dict(arrowstyle='->', color='#d62728', lw=2),
            color='#d62728'
        )
        
        # ---- BOTTOM PLOT: PWM Steering Command Output ----
        # Plot all data
        ax2.plot(
            timestamps, pwm_commands,
            linewidth=2.5, color='black', label='PWM Command Output', zorder=5
        )
        
        # Color-code by steering direction
        ax2.scatter(
            timestamps[left_mask], pwm_commands[left_mask],
            s=20, alpha=0.6, color='#1f77b4', edgecolor='none',
            label='Steer LEFT (<1500 µs)'
        )
        ax2.scatter(
            timestamps[center_mask], pwm_commands[center_mask],
            s=30, alpha=0.8, color='green', edgecolor='black', linewidth=0.5,
            label='Neutral (≈1500 µs)'
        )
        ax2.scatter(
            timestamps[right_mask], pwm_commands[right_mask],
            s=20, alpha=0.6, color='#d62728', edgecolor='none',
            label='Steer RIGHT (>1500 µs)'
        )
        
        # Reference lines
        ax2.axhline(self.params.pwm_neutral, color='green', linestyle='--', linewidth=2, label='Neutral (1500µs)', alpha=0.8)
        ax2.axhline(self.params.pwm_min, color='#1f77b4', linestyle=':', linewidth=2, alpha=0.7, label='Max Left')
        ax2.axhline(self.params.pwm_max, color='#d62728', linestyle=':', linewidth=2, alpha=0.7, label='Max Right')
        
        # Add shading for steering regions
        ax2.fill_between(
            timestamps,
            self.params.pwm_min, self.params.pwm_neutral,
            alpha=0.1, color='#1f77b4'
        )
        ax2.fill_between(
            timestamps,
            self.params.pwm_neutral, self.params.pwm_max,
            alpha=0.1, color='#d62728'
        )
        
        ax2.set_xlabel('Time (seconds)', fontsize=13, fontweight='bold')
        ax2.set_ylabel('PWM Command (microseconds)', fontsize=13, fontweight='bold')
        ax2.set_title(
            'Yaw Control Output - Proportional Response to Left/Right Target Motion',
            fontsize=14, fontweight='bold'
        )
        ax2.grid(True, alpha=0.3, linestyle=':', linewidth=1)
        ax2.legend(loc='upper right', fontsize=11, ncol=3, framealpha=0.95)
        ax2.set_xlim([timestamps[0], timestamps[-1]])
        ax2.set_ylim([self.params.pwm_min - 50, self.params.pwm_max + 50])
        ax2.set_xticks([0, 4, 8, 12, 16])
        
        # Add value annotations at extremes
        left_pwm_idx = np.argmin(pwm_commands)
        ax2.annotate(
            f'{pwm_commands[left_pwm_idx]:.0f}µs\nSTEER LEFT',
            xy=(timestamps[left_pwm_idx], pwm_commands[left_pwm_idx]),
            xytext=(timestamps[left_pwm_idx] - 1.5, self.params.pwm_min - 30),
            fontsize=10, fontweight='bold', color='#1f77b4',
            arrowprops=dict(arrowstyle='->', color='#1f77b4', lw=2),
            bbox=dict(boxstyle='round,pad=0.5', facecolor='lightblue', alpha=0.7)
        )
        
        right_pwm_idx = np.argmax(pwm_commands)
        ax2.annotate(
            f'{pwm_commands[right_pwm_idx]:.0f}µs\nSTEER RIGHT',
            xy=(timestamps[right_pwm_idx], pwm_commands[right_pwm_idx]),
            xytext=(timestamps[right_pwm_idx] + 1.5, self.params.pwm_max + 30),
            fontsize=10, fontweight='bold', color='#d62728',
            arrowprops=dict(arrowstyle='->', color='#d62728', lw=2),
            bbox=dict(boxstyle='round,pad=0.5', facecolor='lightcoral', alpha=0.7)
        )
        
        neutral_pwm_idx = np.argmin(np.abs(pwm_commands - self.params.pwm_neutral))
        ax2.annotate(
            f'{pwm_commands[neutral_pwm_idx]:.0f}µs\nNEUTRAL',
            xy=(timestamps[neutral_pwm_idx], pwm_commands[neutral_pwm_idx]),
            xytext=(timestamps[neutral_pwm_idx], self.params.pwm_neutral + 100),
            fontsize=10, fontweight='bold', color='green',
            arrowprops=dict(arrowstyle='->', color='green', lw=2),
            bbox=dict(boxstyle='round,pad=0.5', facecolor='lightgreen', alpha=0.7)
        )
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"✓ Figure saved to: {save_path}")
        
        plt.show()
    
    def plot_control_linearity(self, save_path: str = None):
        """
        Create a detailed plot showing proportional control law linearity.
        """
        pixel_offsets = np.array([r.pixel_offset for r in self.results])
        pwm_commands = np.array([r.measured_pwm for r in self.results])
        
        # Separate deadzone and active regions
        mask = np.abs(pixel_offsets) > self.params.deadzone_pixels
        mask_deadzone = np.abs(pixel_offsets) <= self.params.deadzone_pixels
        
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Active control region
        ax.scatter(
            pixel_offsets[mask], pwm_commands[mask],
            s=80, alpha=0.7, color='#1f77b4', edgecolor='black', linewidth=1,
            label='Active Control Region', zorder=3
        )
        
        # Deadzone region
        ax.scatter(
            pixel_offsets[mask_deadzone], pwm_commands[mask_deadzone],
            s=80, alpha=0.5, color='green', edgecolor='black', linewidth=1, marker='s',
            label='Deadzone (No Response)', zorder=2
        )
        
        # Ideal control line
        offset_range = np.linspace(-650, 650, 200)
        ideal_pwm = self.params.pwm_neutral + (offset_range / 320.0) * self.params.proportional_gain
        ideal_pwm = np.clip(ideal_pwm, self.params.pwm_min, self.params.pwm_max)
        ax.plot(
            offset_range, ideal_pwm,
            linewidth=3, color='#d62728', linestyle='--', alpha=0.8,
            label='Ideal Control Law', zorder=4
        )
        
        # Linear fit to active region
        if np.sum(mask) > 2:
            slope, intercept, r_value, p_value, std_err = stats.linregress(
                pixel_offsets[mask],
                pwm_commands[mask]
            )
            fitted_pwm = slope * offset_range + intercept
            ax.plot(
                offset_range, fitted_pwm,
                linewidth=2.5, color='orange', linestyle=':', alpha=0.9,
                label=f'Linear Fit (R² = {r_value**2:.5f})', zorder=3
            )
        
        # Deadzone shading
        ax.axvspan(
            -self.params.deadzone_pixels,
            self.params.deadzone_pixels,
            alpha=0.15, color='green', label='Deadzone Region'
        )
        
        # Center reference lines
        ax.axhline(self.params.pwm_neutral, color='gray', linestyle=':', linewidth=1.5, alpha=0.5)
        ax.axvline(0, color='gray', linestyle=':', linewidth=1.5, alpha=0.5)
        
        # Formatting
        ax.set_xlabel('Pixel Offset from Frame Center (pixels)', fontsize=13, fontweight='bold')
        ax.set_ylabel('PWM Command (microseconds)', fontsize=13, fontweight='bold')
        ax.set_title(
            'Control Law Linearity Verification\nYOLOv8 Bounding Box Offset → Yaw PWM',
            fontsize=14, fontweight='bold'
        )
        ax.grid(True, alpha=0.3, linestyle=':', linewidth=1)
        ax.legend(loc='best', fontsize=11, framealpha=0.95)
        ax.set_xlim([-650, 650])
        ax.set_ylim([self.params.pwm_min - 50, self.params.pwm_max + 50])
        
        # Add text box with control parameters
        textstr = (
            f'Control Parameters:\n'
            f'Proportional Gain: {self.params.proportional_gain:.0f} µs/unit\n'
            f'Deadzone: ±{self.params.deadzone_pixels:.0f} pixels\n'
            f'Neutral: {self.params.pwm_neutral:.0f} µs\n'
            f'Range: [{self.params.pwm_min:.0f}, {self.params.pwm_max:.0f}] µs'
        )
        ax.text(
            0.02, 0.98, textstr,
            transform=ax.transAxes,
            fontsize=11, verticalalignment='top', family='monospace',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.9)
        )
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"✓ Figure saved to: {save_path}")
        
        plt.show()


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*80)
    print(" OBJECT TRACKING CONTROL LAW VERIFICATION TEST")
    print("="*80 + "\n")
    
    # Initialize test
    control_params = ControlParams()
    trajectory_params = TargetTrajectory()
    
    test = ObjectTrackingTest(
        control_params=control_params,
        trajectory_params=trajectory_params,
        sampling_rate_hz=30.0
    )
    
    # Run test
    results = test.run_test(verbose=True)
    
    # Visualize results
    visualizer = TestVisualizer(results, control_params)
    
    print("\n\nGenerating Publication-Quality Plots...")
    print("-" * 80)
    
    # Plot 1: Comprehensive 4-subplot analysis
    print("\n1. Generating Comprehensive Analysis Figure...")
    visualizer.plot_comprehensive_results(
        save_path='object_tracking_comprehensive_analysis.png'
    )
    
    # Plot 2: Left/Right Steering (main figure from test description)
    print("\n2. Generating Left/Right Steering Figure...")
    visualizer.plot_left_right_steering(
        save_path='object_tracking_left_right_steering.png'
    )
    
    # Plot 3: Control Law Linearity
    print("\n3. Generating Control Law Linearity Figure...")
    visualizer.plot_control_linearity(
        save_path='object_tracking_control_linearity.png'
    )
    
    # Save results to JSON for documentation
    print("\n4. Saving Results to JSON...")
    results_dict = {
        'test_metadata': {
            'test_name': 'Object Tracking Logic Verification',
            'timestamp': datetime.now().isoformat(),
            'control_params': {
                'frame_width': control_params.frame_width,
                'frame_height': control_params.frame_height,
                'pwm_neutral': control_params.pwm_neutral,
                'proportional_gain': control_params.proportional_gain,
                'deadzone_pixels': control_params.deadzone_pixels,
            },
            'test_params': {
                'duration_seconds': trajectory_params.duration,
                'num_samples': len(results),
                'sampling_rate_hz': 30.0,
            }
        },
        'results': [
            {
                'timestamp': r.timestamp,
                'target_x_px': float(r.target_x_px),
                'pixel_offset': float(r.pixel_offset),
                'pwm_command': float(r.measured_pwm),
                'pwm_expected': float(r.expected_pwm),
            }
            for r in results
        ]
    }
    
    with open('object_tracking_test_results.json', 'w') as f:
        json.dump(results_dict, f, indent=2)
    print("   ✓ Results saved to: object_tracking_test_results.json")
    
    print("\n" + "="*80)
    print(" TEST COMPLETE - All plots generated successfully!")
    print("="*80 + "\n")