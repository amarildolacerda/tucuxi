import logging
from enum import Enum

from .config import (
    DETECTOR_CONFIDENCE,
    DETECTOR_IOU,
    MOTION_MIN_AREA,
    MOTION_PERSIST_FRAMES,
    TRACK_IOU_THRESHOLD,
)

logger = logging.getLogger(__name__)

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
    DEFAULT = "default"


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


class SensitivityManager:
    """Gerencia perfis de sensibilidade per câmera."""

    def __init__(self, storage):
        self.storage = storage
        self._workers = {}

    def register_worker(self, camera_id, worker):
        self._workers[camera_id] = worker

    def unregister_worker(self, camera_id):
        self._workers.pop(camera_id, None)

    def get_effective_params(self, camera_id: int) -> dict:
        """Retorna parâmetros efetivos da câmera.

        Sem registro (ou nível ``default``) a câmera usa os valores do
        ambiente (config.py/.env) — preserva o comportamento atual.
        """
        config = self.storage.get_camera_sensitivity(camera_id)
        if not config.get("configured", True) or config["level"] == SensitivityLevel.DEFAULT:
            return dict(CONFIG_DEFAULT_PARAMS)
        preset_level = SensitivityLevel(config["level"])
        return dict(SENSITIVITY_PRESETS[preset_level])

    def set_level(self, camera_id: int, level: str):
        """Define o perfil da câmera. Persiste e aplica nos workers.

        ``default`` remove o registro; a câmera passa a usar config.py/.env.
        """
        level_enum = SensitivityLevel(level)
        self.storage.set_camera_sensitivity(camera_id, level_enum.value)
        params = self.get_effective_params(camera_id)
        self.apply_to_workers(camera_id, params)
        logger.info("Sensitivity for camera %s set to %s", camera_id, level)
        return None

    def apply_to_workers(self, camera_id: int, params: dict):
        worker = self._workers.get(camera_id)
        if worker is None:
            return
        md = getattr(worker, "_motion_detector_ref", None)
        if md is not None:
            md.min_area = params["motion_min_area"]
            md.persist_frames = params["motion_persist_frames"]
        od = getattr(worker, "object_detector", None)
        if od is not None:
            od.confidence_threshold = params["detector_confidence"]
            od.iou_threshold = params["detector_iou"]
        tr = getattr(worker, "_tracker_ref", None)
        if tr is not None:
            tr.iou_threshold = params["track_iou_threshold"]
        if md is None or tr is None:
            worker._pending_sensitivity = params