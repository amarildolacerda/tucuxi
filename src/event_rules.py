import json

from .identity import decide_event

# Cooldown do motor de fila (queue engine), distinto de qualquer
# config-driven em main (ex.: ALERT_COOLDOWN_BY_EVENT).
COOLDOWNS = {
    "motion_detected": 30,
    "snapshot_info": 30,
    "loitering": 60,
    "direction_change": 60,
    "fall_detected": 20,
    "intruder_detected": 30,
    "identity_recognized": 30,
    "unknown_detected": 30,
    "no_motion": 120,
}


def get_cooldown_for_event(event_type):
    return COOLDOWNS.get(event_type, 30)


def decide_worker_event(detections, identity_info, zone_classification, camera_name, label=None,
                        in_schedule=True, fall=False, loitering=None, direction=None, now=None):
    """Decide o evento do frame (Fase 3: comportamento/anomalia).

    Prioridade: identidade (intruder_detected/identity_recognized) > queda >
    loitering > direção > snapshot > movimento. Fora do horário
    (in_schedule=False), apenas eventos de identidade válidos passam:
    intruder_detected (desconhecido em zona privativa/segurança, prioridade)
    e identity_recognized (conhecido); os demais retornam None (suprimido).
    """
    if identity_info is not None:
        decision = decide_event(identity_info, zone_classification, camera_name, label)
        if decision is not None:
            if not in_schedule and decision[0] == "unknown_detected":
                return None
            return decision
    if not in_schedule:
        return None
    if fall:
        return ("fall_detected", f"Possível queda de pessoa na câmera {camera_name}", None, None, None, None)
    if loitering is not None:
        seconds = int(now - loitering["first_seen"]) if now is not None else 0
        track_label = loitering.get("label", "Objeto")
        return ("loitering", f"{track_label} na mesma região há {seconds}s (câmera {camera_name})",
                None, None, track_label, None)
    if direction is not None:
        return ("direction_change", f"Movimento {direction} detectado na câmera {camera_name}",
                None, None, None, None)
    if detections:
        return ("snapshot_info", format_detections(detections), None, None, None, None)
    return ("motion_detected", f"Movimento detectado na câmera {camera_name}", None, None, None, None)


def _unpack_worker_decision(decision):
    """Desempacota a decisão de evento de forma segura no worker.

    decide_worker_event retorna None (supressão: fora do horário sem
    identidade válida). Desempacotar None direto lançaria TypeError por
    frame — log spam, thumbnails congeladas e cadência degradada (regressão
    Fase 3). None vira tupla de None; decisão real passa intacta.
    """
    if decision is None:
        return (None, None, None, None, None, None)
    return decision


def format_detections(detections):
    if not detections:
        return None

    labels = [d["label"] for d in detections]
    details = json.dumps(
        [
            {
                "label": d["label"],
                "confidence": round(d.get("confidence", 0.0), 2),
                "bbox": d.get("bbox"),
            }
            for d in detections
        ]
    )
    return f"Objetos detectados: {', '.join(labels)} | detalhes: {details}"


RULES = [
    {"when": {"event_type": ["intruder_detected", "fall_detected"]},
     "then": {"alert": ["telegram", "automation"], "disposition": "alert"}},
    {"when": {"event_type": ["identity_recognized"]},
     "then": {"alert": ["telegram", "automation"], "disposition": "alert"}},
    {"when": {"event_type": ["loitering", "direction_change"], "zone_classification": ["private", "security"]},
     "then": {"alert": ["telegram", "automation"], "disposition": "alert"}},
    {"when": {"event_type": ["motion_detected", "snapshot_info"]},
     "then": {"alert": ["telegram", "automation"], "disposition": "alert"}},
    {"when": {"no_motion": True},
     "then": {"alert": ["telegram", "automation"], "disposition": "alert"}},
    {"when": {"event_type": ["flood", "water_leak", "sensor_alert"]},
     "then": {"alert": ["telegram", "automation"], "disposition": "alert"}},
]


def match_rule(rule, ctx):
    for key, val in rule["when"].items():
        actual = ctx.get(key)
        if isinstance(val, list):
            if actual not in val:
                return False
        elif actual != val:
            return False
    return True


def evaluate_rules(event_type, zone_classification, no_motion):
    ctx = {"event_type": event_type, "zone_classification": zone_classification, "no_motion": no_motion}
    for rule in RULES:
        if match_rule(rule, ctx):
            return rule["then"]
    return {"alert": ["telegram"], "disposition": "alert"}
