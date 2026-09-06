from __future__ import annotations

import copy
import json

DEFAULT_ENTITY_MAP: dict = {
    "rosa": {
        "camera_id": 2,
        "alias_of": None,
        "layer": "L2_seguranca",
        "ha_sensor": "binary_sensor.presenca_rosa",
        "ha_actuator": "switch.aspersor_rosa",
        "default_duration_sec": 300,
        "alarm_required": True,
        "modos_ativos": ["armed_home", "armed_away"],
        "cooldown_sec": 900,
    },
    "acesso_jardim": {
        "camera_id": 2,
        "alias_of": "rosa",
        "layer": "L2_seguranca",
        "ha_sensor": "binary_sensor.presenca_rosa",
        "ha_actuator": "switch.aspersor_rosa",
        "default_duration_sec": 300,
        "alarm_required": True,
        "modos_ativos": ["armed_home", "armed_away"],
        "cooldown_sec": 900,
    },
    "portao_entrada": {
        "camera_id": 1,
        "alias_of": None,
        "layer": "L1_perimetro",
        "ha_sensor": "binary_sensor.pir_portao",
        "ha_actuator": "light.perimetral",
        "default_duration_sec": 600,
        "alarm_required": False,
        "modos_ativos": ["armed_home", "armed_away"],
        "cooldown_sec": 600,
    },
}


def load_entity_map(raw_json: str = "") -> dict:
    merged = copy.deepcopy(DEFAULT_ENTITY_MAP)
    if raw_json:
        override = json.loads(raw_json)
        for slug, entry in override.items():
            merged.setdefault(slug, {}).update(entry)
    return merged


def resolve_zone(slug: str, entity_map: dict) -> dict | None:
    entry = entity_map.get(slug)
    if entry is None:
        return None
    if entry.get("alias_of"):
        return entity_map.get(entry["alias_of"])
    return entry
