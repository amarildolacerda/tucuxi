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

    def set_preset(self, name: str) -> Optional[str]:
        """Create/update an ONVIF preset at current position. Returns token."""
        self._connect()
        try:
            result = self._ptz_service.SetPreset({
                "ProfileToken": self._profile_token,
                "PresetName": name,
            })
            token = getattr(result, "PresetToken", None)
            if token:
                logger.info(f"ONVIF preset '{name}' created, token={token}")
            return token
        except Exception as e:
            logger.warning(f"SetPreset failed: {e}")
            return None

    def remove_preset(self, preset_token: str) -> bool:
        """Remove an ONVIF preset."""
        self._connect()
        try:
            self._ptz_service.RemovePreset({
                "ProfileToken": self._profile_token,
                "PresetToken": preset_token
            })
            return True
        except Exception as e:
            logger.warning(f"RemovePreset failed: {e}")
            return False

    def get_capabilities(self) -> dict:
        """Check PTZ capabilities."""
        self._connect()
        try:
            caps = self._ptz_service.GetServiceCapabilities()
            return {
                "continuous_move": getattr(caps, "ContinuousMove", None),
                "relative_move": getattr(caps, "RelativeMove", None),
                "absolute_move": getattr(caps, "AbsoluteMove", None),
                "move_status": getattr(caps, "MoveStatus", None),
            }
        except Exception as e:
            logger.warning(f"GetServiceCapabilities failed: {e}")
            return {}

    def get_status(self) -> dict:
        """Get current PTZ status (position + move state)."""
        self._connect()
        try:
            status = self._ptz_service.GetStatus({"ProfileToken": self._profile_token})
            move_status = getattr(status, "MoveStatus", None)
            pan_tilt_idle = True
            zoom_idle = True
            if move_status:
                pan_tilt_idle = getattr(move_status, "PanTilt", "IDLE") == "IDLE"
                zoom_idle = getattr(move_status, "Zoom", "IDLE") == "IDLE"
            return {
                "pan_tilt_idle": pan_tilt_idle,
                "zoom_idle": zoom_idle,
                "idle": pan_tilt_idle and zoom_idle,
            }
        except Exception as e:
            logger.warning(f"GetStatus failed: {e}")
            return {"pan_tilt_idle": True, "zoom_idle": True, "idle": True}
