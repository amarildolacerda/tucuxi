"""Autotracking — auto-follow detected persons using PTZ.

When autotracking is enabled for a camera, the module analyzes
detections and sends PTZ commands to follow the most prominent
person/subject in the frame.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class Autotracker:
    """Tracks subjects by sending PTZ commands based on detection positions."""

    def __init__(self, ptz_manager, cooldown_seconds: float = 2.0):
        self.ptz_manager = ptz_manager
        self.cooldown_seconds = cooldown_seconds
        self._last_move_time: dict[int, float] = {}

    def process_detection(self, camera_id: int, detections: list[dict]) -> Optional[dict]:
        """Analyze detections and return PTZ command if tracking should move.

        Args:
            camera_id: Camera ID.
            detections: List of detection dicts with keys:
                - class: detection class (e.g. "person")
                - bbox: [x1, y1, x2, y2] normalized to 0-1
                - confidence: float 0-1

        Returns:
            Dict with pan, tilt, zoom or None if no move needed.
        """
        if not detections:
            return None

        # Rate limit: don't move too frequently
        now = time.time()
        last_move = self._last_move_time.get(camera_id, 0)
        if now - last_move < self.cooldown_seconds:
            return None

        # Find the most prominent person detection
        persons = [d for d in detections if d.get("class") == "person"]
        if not persons:
            return None

        # Pick highest confidence detection
        best = max(persons, key=lambda d: d.get("confidence", 0))
        bbox = best.get("bbox")
        if not bbox or len(bbox) != 4:
            return None

        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2.0  # center x (0-1)
        cy = (y1 + y2) / 2.0  # center y (0-1)

        # Convert center position to PTZ move command
        # Center of frame = (0.5, 0.5) = no movement needed
        # Map offset to pan/tilt values (-1 to 1 range, scaled)
        pan = (cx - 0.5) * 1.0
        tilt = -(cy - 0.5) * 0.5  # invert Y (screen Y is down, tilt Y is up)

        # Only move if offset is significant (deadzone of 10%)
        if abs(pan) < 0.1 and abs(tilt) < 0.1:
            return None

        # Clamp values
        pan = max(-1.0, min(1.0, pan))
        tilt = max(-1.0, min(1.0, tilt))

        self._last_move_time[camera_id] = now

        return {"pan": pan, "tilt": tilt, "zoom": 0.0}

    def execute_move(self, camera_id: int, pan: float, tilt: float, zoom: float = 0.0) -> bool:
        """Execute a PTZ move via the manager.

        Returns True if move was sent successfully.
        """
        try:
            self.ptz_manager.move(camera_id, pan, tilt, zoom)
            return True
        except Exception as e:
            logger.warning("Autotracking move failed for camera %d: %s", camera_id, e)
            return False
