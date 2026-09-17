"""ONVIF PTZ client wrapper."""
import logging
from typing import Optional

try:
    from onvif import ONVIFCamera
except ImportError:
    ONVIFCamera = None

logger = logging.getLogger(__name__)


class PTZClient:
    """Wraps onvif-zeep for PTZ operations."""

    def __init__(self, camera_id: int, host: str, port: int = 80,
                 user: str = "", password: str = ""):
        if ONVIFCamera is None:
            raise ImportError("onvif-zeep not installed: pip install onvif-zeep")
        self.camera_id = camera_id
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self._cam: Optional[ONVIFCamera] = None
        self._ptz_service = None
        self._profile_token = None

    def _connect(self):
        """Lazy connection to ONVIF service."""
        if self._cam is not None:
            return
        logger.info(f"Connecting ONVIF {self.host}:{self.port}")
        self._cam = ONVIFCamera(self.host, self.port, self.user, self.password)
        media_service = self._cam.create_media_service()
        profiles = media_service.GetProfiles()
        if profiles:
            self._profile_token = profiles[0].token
        self._ptz_service = self._cam.create_ptz_service()

    def move(self, pan: float, tilt: float, zoom: float) -> bool:
        """Continuous move with velocity values (-1.0 to 1.0)."""
        self._connect()
        req = {
            "ProfileToken": self._profile_token,
            "Velocity": {
                "PanTilt": {"x": pan, "y": tilt},
                "Zoom": {"x": zoom}
            }
        }
        self._ptz_service.ContinuousMove(req)
        return True

    def stop(self) -> bool:
        """Stop all PTZ movement."""
        self._connect()
        self._ptz_service.Stop({"ProfileToken": self._profile_token})
        return True

    def get_presets(self) -> list:
        """Get list of configured presets."""
        self._connect()
        try:
            presets = self._ptz_service.GetPresets({"ProfileToken": self._profile_token})
            return [{"name": p.Name, "token": p.token} for p in presets]
        except Exception as e:
            logger.warning(f"GetPresets failed: {e}")
            return []

    def goto_preset(self, preset_token: str) -> bool:
        """Move to a preset position."""
        self._connect()
        self._ptz_service.GotoPreset({
            "ProfileToken": self._profile_token,
            "PresetToken": preset_token
        })
        return True

    def get_capabilities(self) -> dict:
        """Check PTZ capabilities."""
        self._connect()
        try:
            caps = self._ptz_service.GetServiceCapabilities()
            return {
                "continuous_move": getattr(caps, "ContinuousMove", None),
                "relative_move": getattr(caps, "RelativeMove", None),
                "absolute_move": getattr(caps, "AbsoluteMove", None),
            }
        except Exception as e:
            logger.warning(f"GetServiceCapabilities failed: {e}")
            return {}
