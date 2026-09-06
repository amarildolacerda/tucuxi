from __future__ import annotations

import json
import paho.mqtt.publish as publish

from .schemas import Prediction


def build_prediction_payload(camera: str, zone: str, janela: str, evento_previsto: str,
                             probabilidade: float, confianca_modelo: float,
                             amostras: int, expira_em: str) -> dict:
    return Prediction(
        camera=camera, zone=zone, janela=janela, evento_previsto=evento_previsto,
        probabilidade=probabilidade, confianca_modelo=confianca_modelo,
        modelo="ewma-7d", amostras=amostras, expira_em=expira_em,
    ).to_dict()


def publish_prediction(broker: str, port: int, auth: dict | None, slug: str, payload: dict) -> None:
    publish.single(f"tucuxi/predictions/{slug}", json.dumps(payload),
                   hostname=broker, port=port, auth=auth, retain=True, qos=0)


def build_discovery_config(slug: str, expire_after_sec: int = 1800) -> dict:
    return {
        "name": f"Tucuxi {slug} Predicao",
        "state_topic": f"tucuxi/predictions/{slug}",
        "value_template": "{{ value_json.probabilidade }}",
        "unit_of_measurement": "%",
        "json_attributes_topic": f"tucuxi/predictions/{slug}",
        "expire_after": expire_after_sec,
        "unique_id": f"tucuxi_{slug}_prediction",
    }


def publish_discovery(broker: str, port: int, auth: dict | None, slug: str,
                      expire_after_sec: int = 1800) -> None:
    publish.single(f"homeassistant/sensor/tucuxi_{slug}_prediction/config",
                   json.dumps(build_discovery_config(slug, expire_after_sec)),
                   hostname=broker, port=port, auth=auth, retain=True, qos=0)
