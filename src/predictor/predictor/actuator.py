from __future__ import annotations

import json
import paho.mqtt.publish as publish

from .entity_map import resolve_zone
from .schemas import ActuatorCommand

ARMED_MODES = ("armed_home", "armed_away")


def decide_action(slug: str, alarm_mode: str, event_type: str, entity_map: dict,
                  inhibitors: dict | None = None,
                  last_trigger_ts: float | None = None,
                  now_ts: float = 0.0, motivo: str = "") -> dict | None:
    entry = resolve_zone(slug, entity_map)
    if entry is None:
        return None
    if alarm_mode not in entry.get("modos_ativos", list(ARMED_MODES)):
        return None
    if entry.get("alarm_required") and alarm_mode not in ARMED_MODES:
        return None
    inhibitors = inhibitors or {}
    if inhibitors.get("chuva") or inhibitors.get("identidade_conhecida"):
        return None
    cooldown = int(entry.get("cooldown_sec", 900))
    if last_trigger_ts is not None and (now_ts - last_trigger_ts) < cooldown:
        return None
    return ActuatorCommand(
        action="turn_on",
        camera=slug,
        zone=slug,
        event_type=event_type,
        target_entity=entry["ha_actuator"],
        duration_sec=int(entry.get("default_duration_sec", 300)),
        alarm_mode=alarm_mode,
        motivo=motivo,
    ).to_dict()


def publish_actuator(broker: str, port: int, auth: dict | None, command: dict) -> None:
    publish.single("tucuxi/automation/actuator", json.dumps(command),
                   hostname=broker, port=port, auth=auth, retain=False, qos=0)
