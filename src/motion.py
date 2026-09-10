import cv2

from .config import MOTION_PERSIST_FRAMES, RAIN_SPATIAL_RATIO
from .geometry import point_in_polygon


class MotionDetector:
    def __init__(self, min_area: int = 5000):
        self.min_area = min_area
        self.previous_frame = None
        self._consecutive_motion = 0

    def detect(self, frame, exclusion_polygons=None):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self.previous_frame is None:
            self.previous_frame = gray
            return False

        delta = cv2.absdiff(self.previous_frame, gray)
        self.previous_frame = gray

        thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        raw_motion = False
        for contour in contours:
            if cv2.contourArea(contour) < self.min_area:
                continue
            if exclusion_polygons:
                moments = cv2.moments(contour)
                if moments["m00"] != 0:
                    cx = moments["m10"] / moments["m00"]
                    cy = moments["m01"] / moments["m00"]
                    if any(point_in_polygon(cx, cy, poly) for poly in exclusion_polygons):
                        continue
            raw_motion = True
            break

        if not raw_motion:
            self._consecutive_motion = 0
            return False

        if self._is_rain_pattern(contours, frame):
            self._consecutive_motion = 0
            return False

        self._consecutive_motion += 1
        if self._consecutive_motion < MOTION_PERSIST_FRAMES:
            return False

        return True

    def _is_rain_pattern(self, contours, frame):
        h, w = frame.shape[:2]
        frame_area = h * w
        if frame_area == 0:
            return False
        total_motion_area = sum(cv2.contourArea(c) for c in contours if cv2.contourArea(c) >= self.min_area)
        if total_motion_area / frame_area > RAIN_SPATIAL_RATIO:
            return True
        if len(contours) >= 20:
            xs, ys = [], []
            for c in contours:
                if cv2.contourArea(c) < self.min_area:
                    continue
                M = cv2.moments(c)
                if M["m00"] != 0:
                    xs.append(M["m10"] / M["m00"])
                    ys.append(M["m01"] / M["m00"])
            if len(xs) >= 20:
                spread_x = (max(xs) - min(xs)) / w
                spread_y = (max(ys) - min(ys)) / h
                if spread_x > 0.6 and spread_y > 0.6:
                    return True
        return False
