"""Sensitivity presets for camera detection tuning."""

import logging
from enum import Enum
from typing import Optional

from .config import (
    DETECTOR_CONFIDENCE,
    DETECTOR_IOU,
    MOTION_MIN_AREA,
    MOTION_PERSIST_FRAMES,
    TRACK_IOU_THRESHOLD,
)

logger = logging.getLogger(__name__)

# Parâmetros efetivos de câmera sem registro em camera_sensitivity.
# Seguem a prioridade do SPEC §8.1/§8.2: DB > env vars (config) > defaults.
CONFIG_DEFAULT_PARAMS = {
    "motion_min_area": MOTION_MIN_AREA,
    "motion_persist_frames": MOTION_PERSIST_FRAMES,
    "detector_confidence": DETECTOR_CONFIDENCE,
    "detector_iou": DETECTOR_IOU,
    "track_iou_threshold": TRACK_IOU_THRESHOLD,
}


class SensitivityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CUSTOM = "custom"


SENSITIVITY_PRESETS = {
    SensitivityLevel.LOW: {
        "motion_min_area": 8000,
        "motion_persist_frames": 4,
        "detector_confidence": 0.55,
        "detector_iou": 0.50,
        "track_iou_threshold": 0.4,
    },
    SensitivityLevel.MEDIUM: {
        "motion_min_area": 5000,
        "motion_persist_frames": 3,
        "detector_confidence": 0.40,
        "detector_iou": 0.45,
        "track_iou_threshold": 0.3,
    },
    SensitivityLevel.HIGH: {
        "motion_min_area": 3000,
        "motion_persist_frames": 2,
        "detector_confidence": 0.30,
        "detector_iou": 0.40,
        "track_iou_threshold": 0.25,
    },
}

# Valid ranges for custom mode
PARAM_RANGES = {
    "motion_min_area": (1000, 15000),
    "motion_persist_frames": (1, 8),
    "detector_confidence": (0.10, 0.80),
    "detector_iou": (0.20, 0.70),
    "track_iou_threshold": (0.10, 0.60),
}


def validate_custom_params(params: dict) -> Optional[str]:
    """Validate custom parameters. Returns error message or None."""
    required = {"motion_min_area", "motion_persist_frames", "detector_confidence", "detector_iou", "track_iou_threshold"}
    if not required.issubset(params.keys()):
        missing = required - params.keys()
        return f"Parâmetros faltando: {', '.join(missing)}"
    for key, value in params.items():
        if key not in PARAM_RANGES:
            continue
        min_val, max_val = PARAM_RANGES[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return f"{key} deve ser numérico"
        if value < min_val or value > max_val:
            return f"{key} deve estar entre {min_val} e {max_val}"
    return None


class SensitivityManager:
    """Manages sensitivity presets per camera."""

    def __init__(self, storage):
        self.storage = storage
        self._workers = {}  # camera_id -> worker (set by CameraManager)

    def register_worker(self, camera_id, worker):
        """Register a worker for a camera (called by CameraManager)."""
        self._workers[camera_id] = worker

    def unregister_worker(self, camera_id):
        """Unregister a worker for a camera."""
        self._workers.pop(camera_id, None)

    def get_effective_params(self, camera_id: int) -> dict:
        """Return effective parameters (env fallback, preset or custom) for a camera.

        Sem registro em ``camera_sensitivity`` a câmera usa os valores do
        ambiente (config.py), preservando o comportamento atual (SPEC §8.2).
        """
        config = self.storage.get_camera_sensitivity(camera_id)
        if not config.get("configured", True):
            return dict(CONFIG_DEFAULT_PARAMS)
        level = config["level"]
        if level == SensitivityLevel.CUSTOM and config["custom_params"]:
            return config["custom_params"]
        preset_level = SensitivityLevel(level)
        return dict(SENSITIVITY_PRESETS[preset_level])

    def set_level(self, camera_id: int, level: str, custom_params: dict = None):
        """Set sensitivity level. Persists to DB and applies to workers.

        Returns error string on failure, None on success.
        """
        level_enum = SensitivityLevel(level)
        if level_enum == SensitivityLevel.CUSTOM:
            if custom_params is None:
                return "custom_params é obrigatório para nível custom"
            error = validate_custom_params(custom_params)
            if error:
                return error
        self.storage.set_camera_sensitivity(camera_id, level, custom_params)
        params = self.get_effective_params(camera_id)
        self.apply_to_workers(camera_id, params)
        logger.info("Sensitivity for camera %s set to %s", camera_id, level)
        return None

    def apply_to_workers(self, camera_id: int, params: dict):
        """Apply parameters to the worker for a camera (real-time)."""
        worker = self._workers.get(camera_id)
        if worker is None:
            return
        # Update motion detector (may not be initialized yet if run() hasn't started)
        md = getattr(worker, '_motion_detector_ref', None)
        if md is not None:
            md.min_area = params["motion_min_area"]
            md.persist_frames = params["motion_persist_frames"]
        # Update object detector (always exists on worker)
        od = getattr(worker, 'object_detector', None)
        if od is not None:
            od.confidence_threshold = params["detector_confidence"]
            od.iou_threshold = params["detector_iou"]
        # Update tracker (may not be initialized yet)
        tr = getattr(worker, '_tracker_ref', None)
        if tr is not None:
            tr.iou_threshold = params["track_iou_threshold"]
        # If any ref wasn't ready, store as pending so run() can apply it
        if md is None or tr is None:
            worker._pending_sensitivity = params
