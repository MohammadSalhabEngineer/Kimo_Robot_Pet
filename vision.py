"""
vision.py — Color tracking vision module for Kimo.

Detects a specified color in the webcam feed and steers the robot toward it.
Runs in a background thread. Call start_follow() / stop_follow() to control it.
"""

import threading
import time
import cv2
import numpy as np

# HSV color ranges: each color has (lower, upper) bounds
# Red wraps around in HSV so it has two ranges.
# Red S_min=120: brown/terracotta has S=40-100, vivid red has S=150+. Gap is the key.
# Blue V_min=60: dark shadow corners under indoor light appear blue — keep V high.
_COLOR_RANGES = {
    "red": [((0,   150, 50),  (8,   255, 255)),
            ((167, 150, 50),  (180, 255, 255))],
}

# Frame zone boundaries (fraction of width) — wide center reduces oscillation
_LEFT_ZONE  = 0.20
_RIGHT_ZONE = 0.80

# Minimum blob area to count as a valid target (filters tiny noise blobs)
_MIN_BLOB_AREA = 1500

# Delay between steering commands while tracking (seconds)
_STEER_INTERVAL = 0.6

# Search behaviour: look first, then rotate 90° at a time
_LOOK_SECS   = 2.0   # seconds to watch current view before rotating
_TURN_SECS   = 0.5   # duration of each RIGHT rotation (~90° — tune to your robot)
_SETTLE_SECS = 0.3   # pause after rotating so camera can settle


def _get_color_mask(hsv_frame: np.ndarray, color: str) -> np.ndarray:
    """Return a binary mask for the given color in the HSV frame."""
    ranges = _COLOR_RANGES.get(color, [])
    mask = np.zeros(hsv_frame.shape[:2], dtype=np.uint8)
    for (lower, upper) in ranges:
        mask |= cv2.inRange(hsv_frame, np.array(lower), np.array(upper))
    # Clean up noise and close gaps between fragments
    open_kernel  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,  5))
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (40, 40))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  open_kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)
    return mask


def _get_blob_center(mask: np.ndarray):
    """Return area-weighted centroid of all qualifying blobs, or None if nothing found."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    weighted_x = weighted_y = total_area = 0.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < _MIN_BLOB_AREA:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        weighted_x += (M["m10"] / M["m00"]) * area
        weighted_y += (M["m01"] / M["m00"]) * area
        total_area += area
    if total_area == 0:
        return None
    return int(weighted_x / total_area), int(weighted_y / total_area)


class ColorFollower:
    def __init__(self, motor_controller):
        self._motor = motor_controller
        self._thread = None
        self._stop_event = threading.Event()
        self._color = None

    def start(self, color: str) -> None:
        """Start following the given color."""
        if color not in _COLOR_RANGES:
            print(f"[Vision] Unknown color '{color}'. Supported: {list(_COLOR_RANGES)}")
            return
        self.stop()  # stop any existing follow
        self._color = color
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[Vision] Now following color: {color}")

    def stop(self) -> None:
        """Stop the follow thread."""
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=2)
            self._thread = None
            print("[Vision] Color follow stopped.")

    def is_active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[Vision] ERROR: Cannot open webcam.")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        frame_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)

        smoothed_rel = None
        EMA_ALPHA    = 0.1
        last_command = None
        look_start   = time.time()

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            frame  = cv2.flip(frame, 1)
            hsv    = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask   = _get_color_mask(hsv, self._color)
            center = _get_blob_center(mask)

            if center is not None:
                # ── TRACKING ─────────────────────────────────────────
                look_start = time.time()   # reset scan timer
                cx  = center[0]
                rel = cx / frame_width

                if smoothed_rel is None:
                    smoothed_rel = rel
                else:
                    smoothed_rel = EMA_ALPHA * rel + (1 - EMA_ALPHA) * smoothed_rel

                if smoothed_rel < _LEFT_ZONE:
                    new_command = "LEFT"
                elif smoothed_rel > _RIGHT_ZONE:
                    new_command = "RIGHT"
                else:
                    new_command = "FORWARD"

                if new_command != last_command:
                    self._motor.send_command(new_command)
                    print(f"[Vision] {self._color.upper()} → {new_command} (pos: {smoothed_rel*100:.0f}%)")
                    last_command = new_command

                time.sleep(_STEER_INTERVAL)

            else:
                # ── SCANNING ─────────────────────────────────────────
                smoothed_rel = None   # reset EMA when target lost

                if time.time() - look_start < _LOOK_SECS:
                    # Still within the look window — stay stopped and keep checking
                    if last_command != "STOP":
                        self._motor.send_command("STOP")
                        last_command = "STOP"
                        print(f"[Vision] Searching for {self._color}...")
                    time.sleep(0.1)

                else:
                    # Look window expired — rotate right ~90° then look again
                    print(f"[Vision] Not found — rotating right...")
                    self._motor.send_command("RIGHT")
                    last_command = "RIGHT"
                    elapsed = 0.0
                    while elapsed < _TURN_SECS and not self._stop_event.is_set():
                        time.sleep(0.05)
                        elapsed += 0.05

                    self._motor.send_command("STOP")
                    last_command = "STOP"
                    elapsed = 0.0
                    while elapsed < _SETTLE_SECS and not self._stop_event.is_set():
                        time.sleep(0.05)
                        elapsed += 0.05

                    look_start = time.time()
                    print(f"[Vision] Scanning new angle...")

        cap.release()
        self._motor.send_command("STOP")
