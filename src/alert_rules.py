import time
import logging
from .event_rules import decide_worker_event, _unpack_worker_decision, get_cooldown_for_event, evaluate_rules

logger = logging.getLogger("alert_rules")


class AlertRuleEngine:
    def __init__(self, storage, alerts, camera_manager):
        self.storage = storage
        self.alerts = alerts
        self.camera_manager = camera_manager
        self._last_alert_time = {}

    def handle(self, event):
        try:
            self._handle(event)
        except Exception:
            logger.exception("Erro no AlertRuleEngine ao processar evento %s", getattr(event, "event_id", "?"))

    def _handle(self, event):
        stored_type = event.event_type or ("no_motion" if event.no_motion else "capture")
        event_id = self.storage.add_event(
            event.camera_id, event.zone, stored_type, event.details,
            level=event.level, source=event.source, dropped=event.dropped,
        )
        event.db_event_id = event_id
        if event.dropped:
            return

        event_type, details, identity_name, known, _label, category = (None, None, None, None, None, None)
        if event.no_motion:
            event_type, details = "no_motion", f"Sem movimento na câmera {event.camera_name or event.camera_id}"
        else:
            decision = decide_worker_event(
                event.detections, event.identity_info, event.zone_classification, event.camera_name,
                event.identity_label, in_schedule=event.in_schedule, fall=event.fall,
                loitering=event.loitering, direction=event.direction, now=time.time(),
            )
            event_type, details, identity_name, known, _label, category = _unpack_worker_decision(decision)

        if event_type is None:
            self.storage.update_event_level(event_id, 3, event_type="suppressed", disposition="suppressed")
            return

        now = time.time()
        last = self._last_alert_time.get(event_type, 0.0)
        if now - last < get_cooldown_for_event(event_type):
            self.storage.update_event_level(event_id, 3, event_type=event_type, details=details, disposition="cooldown")
            return

        self._last_alert_time[event_type] = now
        action = evaluate_rules(event_type, event.zone_classification, event.no_motion)
        channels = action.get("alert", ["telegram"])
        disposition = action.get("disposition", "alert")
        logger.info("Alert routing: event_type=%s channels=%s routing=%s", event_type, channels, getattr(self.alerts, 'routing', None))
        self.alerts.send(
            event.camera_id, event.zone, event_type, details, event.zone_classification,
            identity=identity_name, known=known, category=category,
            recognition_method=event.recognition_method, thumbnail_path=event.thumbnail_path,
            routing_channels=channels,
            timestamp=event.timestamp,
        )
        self.camera_manager.request_clip(event.camera_id, event_id)
        self.storage.update_event_level(event_id, 4, event_type=event_type, details=details, disposition=disposition)
