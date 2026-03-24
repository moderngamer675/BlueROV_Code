# rov_tests/test_camera.py
# Run with: python rov_tests/test_camera.py

import socket
import numpy as np
import cv2
import time
import paramiko
from rov_config import (PI_IP, LAPTOP_IP, PI_USERNAME,
                        PI_PASSWORD, VIDEO_PORT)

print("=" * 55)
print("  BlueROV2 Camera Stream Test")
print("=" * 55)

# ── Step 1: Start camera on Pi via SSH ────────────────────
print(f"\n[1] Starting camera stream on Pi...")
try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        PI_IP,
        username=PI_USERNAME,
        password=PI_PASSWORD,
        timeout=10
    )

    # Kill any existing camera process
    ssh.exec_command("pkill -f camera_stream.py 2>/dev/null")
    time.sleep(1.5)

    # Start fresh
    cmd = (
        "nohup /home/pi/rov-env/bin/python3 "
        "/home/pi/camera_stream.py "
        "> /home/pi/logs/camera.log 2>&1 &"
    )
    ssh.exec_command(cmd)
    time.sleep(2)

    # Check it started
    _, stdout, _ = ssh.exec_command(
        "ps aux | grep camera_stream | grep -v grep"
    )
    proc = stdout.read().decode().strip()

    if proc:
        pid = proc.split()[1]
        print(f"    ✅ Camera stream running (PID {pid})")
    else:
        print(f"    ⚠️  Process not visible yet")

    # Read the log to confirm camera opened
    time.sleep(1)
    _, stdout, _ = ssh.exec_command(
        "tail -5 /home/pi/logs/camera.log"
    )
    log_output = stdout.read().decode().strip()
    if log_output:
        print(f"    Pi log:")
        for line in log_output.split('\n'):
            print(f"      {line}")

    ssh.close()

except Exception as e:
    print(f"    ❌ SSH error: {e}")
    print(f"    Start camera manually on Pi:")
    print(f"    python3 /home/pi/camera_stream.py &")

# ── Step 2: Receive video on laptop ──────────────────────
print(f"\n[2] Opening UDP socket on port {VIDEO_PORT}...")
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 131072)

try:
    sock.bind(('0.0.0.0', VIDEO_PORT))
    print(f"    ✅ Socket bound")
except OSError as e:
    print(f"    ❌ Cannot bind: {e}")
    print(f"    Is another script using port {VIDEO_PORT}?")
    exit(1)

sock.settimeout(8.0)

print(f"\n[3] Waiting for first frame (8s timeout)...")
print(f"    Camera streams to {LAPTOP_IP}:{VIDEO_PORT}")

# ── Step 3: Receive and display frames ───────────────────
frame_count  = 0
start        = time.time()
last_fps_t   = time.time()
last_fps_cnt = 0
fps          = 0.0

try:
    while True:
        try:
            data, addr = sock.recvfrom(131072)
        except socket.timeout:
            if frame_count == 0:
                print(f"\n    ❌ No frames received after 8s")
                print(f"\n    Checklist:")
                print(f"    [ ] camera_stream.py running on Pi?")
                print(f"        ssh pi@{PI_IP}")
                print(f"        ps aux | grep camera")
                print(f"    [ ] Pi log shows correct IP?")
                print(f"        cat /home/pi/logs/camera.log")
                print(f"    [ ] Firewall blocking port {VIDEO_PORT}?")
                print(f"        Run fix_firewall.py as Admin")
            else:
                print(f"\n    Stream ended after {frame_count} frames")
            break

        if frame_count == 0:
            print(f"    ✅ First frame from {addr[0]}:{addr[1]}")
            print(f"    Packet size: {len(data)} bytes")
            print(f"    Opening video window...")
            print(f"    Press Q to quit\n")

        frame = cv2.imdecode(
            np.frombuffer(data, np.uint8),
            cv2.IMREAD_COLOR
        )

        if frame is None:
            print(f"    WARNING: Corrupt frame — skipping")
            continue

        frame_count += 1

        # Calculate FPS
        now = time.time()
        if now - last_fps_t >= 1.0:
            fps          = (frame_count - last_fps_cnt) / \
                           (now - last_fps_t)
            last_fps_cnt = frame_count
            last_fps_t   = now

        # Draw overlay
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, 40), (0, 0, 0), -1)
        cv2.putText(
            frame,
            f"BlueROV2 | {w}x{h} | {fps:.1f} FPS | "
            f"Frame {frame_count}",
            (8, 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6, (0, 255, 0), 1
        )
        cv2.putText(
            frame,
            "Q = quit",
            (w - 80, h - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45, (200, 200, 200), 1
        )

        cv2.imshow("BlueROV2 Camera", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("\n    Quit by user")
            break

except KeyboardInterrupt:
    print("\n    Stopped by Ctrl+C")

finally:
    sock.close()
    cv2.destroyAllWindows()

    elapsed = time.time() - start
    avg_fps = frame_count / elapsed if elapsed > 0 else 0

    print(f"\n{'='*55}")
    if frame_count > 0:
        print(f"  ✅ Camera test PASSED")
        print(f"  Frames received  : {frame_count}")
        print(f"  Average FPS      : {avg_fps:.1f}")
        print(f"  Duration         : {elapsed:.1f}s")
    else:
        print(f"  ❌ Camera test FAILED — no frames received")
    print(f"{'='*55}")