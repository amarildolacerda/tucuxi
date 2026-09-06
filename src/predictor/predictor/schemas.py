from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import uuid

SCHEMA_VERSION = 1


def validate_schema_version(payload: dict) -> bool:
    return isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION


def _now_local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class EnrichedEvent:
    camera: str
    camera_id: str
    zone: str
    zone_classification: str
    event_type: str
    evento: str = "pessoa"
    probabilidade: float = 0.0
    timestamp: str = field(default_factory=_now_local_iso)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "camera": self.camera,
            "camera_id": self.camera_id,
            "zone": self.zone,
            "zone_classification": self.zone_classification,
            "evento": self.evento,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "probabilidade": self.probabilidade,
            "event_id": self.event_id,
        }


@dataclass
class Prediction:
    camera: str
    zone: str
    janela: str
    evento_previsto: str
    probabilidade: float
    confianca_modelo: float
    modelo: str
    amostras: int
    threshold_sugestao: float = 0.75
    gerado_em: str = field(default_factory=_now_local_iso)
    expira_em: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "camera": self.camera,
            "zone": self.zone,
            "janela": self.janela,
            "evento_previsto": self.evento_previsto,
            "probabilidade": self.probabilidade,
            "confianca_modelo": self.confianca_modelo,
            "modelo": self.modelo,
            "gerado_em": self.gerado_em,
            "expira_em": self.expira_em,
            "amostras": self.amostras,
            "threshold_sugestao": self.threshold_sugestao,
        }


@dataclass
class ActuatorCommand:
    action: str
    camera: str
    zone: str
    event_type: str
    target_entity: str
    duration_sec: int
    alarm_mode: str
    motivo: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_now_local_iso)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "action": self.action,
            "camera": self.camera,
            "zone": self.zone,
            "event_type": self.event_type,
            "target_entity": self.target_entity,
            "duration_sec": self.duration_sec,
            "condition": {"alarm_mode": self.alarm_mode},
            "motivo": self.motivo,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
        }
