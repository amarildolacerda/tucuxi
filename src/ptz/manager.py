"""PTZ manager — state and connection cache per camera."""
import logging
from typing import Dict, Optional
from .onvif_client import PTZClient

logger = logging.getLogger(__name__)


class PTZManager:
    """Manages PTZ clients for all cameras."""

    def __init__(self, storage):
        self.storage = storage
        self._clients: Dict[int, PTZClient] = {}

    def init_camera(self, camera_id: int):
        """Initialize PTZ client for a camera from storage config."""
        ptz_config = self.storage.get_camera_ptz(camera_id)
        if not ptz_config:
            logger.debug(f"No PTZ config for camera {camera_id}")
            return
        client = PTZClient(
            camera_id=camera_id,
            host=ptz_config["onvif_host"],
            port=ptz_config["onvif_port"],
            user=ptz_config.get("onvif_user", ""),
            password=ptz_config.get("onvif_pass", ""),
        )
        self._clients[camera_id] = client
        logger.info(f"PTZ client initialized for camera {camera_id}")

    def get_client(self, camera_id: int) -> Optional[PTZClient]:
        """Get PTZ client for a camera."""
        return self._clients.get(camera_id)

    def move(self, camera_id: int, pan: float, tilt: float, zoom: float) -> bool:
        """Move camera."""
        client = self._clients.get(camera_id)
        if not client:
            raise ValueError(f"PTZ not configured for camera {camera_id}")
        return client.move(pan, tilt, zoom)

    def stop(self, camera_id: int) -> bool:
        """Stop camera movement."""
        client = self._clients.get(camera_id)
        if not client:
            raise ValueError(f"PTZ not configured for camera {camera_id}")
        return client.stop()

    def goto_preset(self, camera_id: int, preset_token: str) -> bool:
        """Move to preset position."""
        client = self._clients.get(camera_id)
        if not client:
            raise ValueError(f"PTZ not configured for camera {camera_id}")
        return client.goto_preset(preset_token)

    def shutdown(self):
        """Disconnect all clients."""
        self._clients.clear()
        logger.info("PTZ manager shut down")
