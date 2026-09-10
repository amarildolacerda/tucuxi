import numpy as np
import cv2
from src.motion import MotionDetector


def _make_frame(base, offset=0, rect=(50, 50, 150, 150), intensity=255):
    frame = base.copy()
    x0, y0, x1, y1 = rect
    cv2.rectangle(frame, (x0 + offset, y0 + offset), (x1 + offset, y1 + offset),
                  (intensity, intensity, intensity), -1)
    return frame


def _prime_motion(detector, base, n=4):
    """Build up consecutive motion counter by providing n distinct motion frames."""
    for i in range(n):
        detector.detect(_make_frame(base, offset=i * 2, intensity=255 - i))


def test_motion_detector_no_motion():
    detector = MotionDetector(min_area=100)
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    assert detector.detect(frame) is False


def test_motion_detector_with_motion():
    detector = MotionDetector(min_area=100)
    base = np.zeros((200, 200, 3), dtype=np.uint8)
    for i in range(5):
        result = detector.detect(_make_frame(base, offset=i * 2))
    assert result is True


def test_motion_detector_persistence_filter():
    detector = MotionDetector(min_area=100)
    base = np.zeros((200, 200, 3), dtype=np.uint8)
    assert detector.detect(_make_frame(base, offset=0)) is False
    assert detector.detect(_make_frame(base, offset=2)) is False
    detector.detect(base)
    assert detector.detect(base) is False


def test_motion_detector_exclusion_zone():
    detector = MotionDetector(min_area=100)
    base = np.zeros((200, 200, 3), dtype=np.uint8)
    exclusion = [[{"x": 0, "y": 0}, {"x": 200, "y": 0}, {"x": 200, "y": 200}, {"x": 0, "y": 200}]]
    for i in range(5):
        assert detector.detect(_make_frame(base, offset=i * 2), exclusion_polygons=exclusion) is False


def test_motion_detector_exclusion_zone_other_region():
    detector = MotionDetector(min_area=100)
    base = np.zeros((200, 200, 3), dtype=np.uint8)
    exclusion = [[{"x": 0, "y": 0}, {"x": 50, "y": 0}, {"x": 50, "y": 50}, {"x": 0, "y": 50}]]
    _prime_motion(detector, base)
    assert detector.detect(_make_frame(base, offset=8)) is True
