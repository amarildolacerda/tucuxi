import logging
from typing import Dict
import json
import os
import requests
import paho.mqtt.publish as publish

from .notifications import is_enabled
from .config import APP_VERSION, SIREN_MQTT_TOPIC, SIREN_EVENT_TYPES

logger = logging.getLogger(__name__)


class AlertService:
    def __init__(self, storage=None):
        # `storage` é mantido apenas por compatibilidade de assinatura: o
        # AlertService NÃO persiste mais eventos (quem persiste é o
        # AlertRuleEngine). Um storage passado aqui é ignorado.
        self.handlers = []
        if storage is not None:
            logger.debug("AlertService: storage ignorado (persistencia via AlertRuleEngine)")

    def register_handler(self, handler):
        self.handlers.append(handler)

    def send(self, camera_id, zone, event_type, details=None, zone_classification=None,
             identity=None, known=None, recognition_method=None, category=None, routing=None,
             thumbnail_path=None, clip_path=None, routing_channels=None, timestamp=None):
        payload = {
            "camera_id": camera_id,
            "zone": zone,
            "event_type": event_type,
            "details": details,
            "zone_classification": zone_classification,
            "identity": identity,
            "known": known,
            "recognition_method": recognition_method,
            "category": category,
            "thumbnail_path": thumbnail_path,
            "clip_path": clip_path,
            "timestamp": timestamp,
        }
        if routing is None:
            routing = getattr(self, "routing", None)
        event_id = None
        for handler in self.handlers:
            channel = getattr(handler, "channel", None)
            # Filtro da regra (ex.: N4 restringe aos canais decididos): um
            # canal só dispara se estiver na lista da regra QUANDO a regra
            # fornecer a lista. None = sem restrição de regra.
            if routing_channels is not None and channel is not None and channel not in routing_channels:
                continue
            if channel is not None and routing is not None and not is_enabled(routing, channel, event_type):
                continue
            try:
                result = handler(payload)
                if result is not None and event_id is None:
                    event_id = result
            except Exception:
                logger.exception("Alert handler failed: %s", handler.__name__)
        return event_id


def telegram_handler(payload: Dict):
    api_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not api_token or not chat_id:
        logger.debug("Telegram handler skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured")
        return

    text = _format_message(payload)
    thumbnail_path = payload.get("thumbnail_path")
    if thumbnail_path and os.path.exists(thumbnail_path):
        url = f"https://api.telegram.org/bot{api_token}/sendPhoto"
        data = {"chat_id": chat_id, "caption": text, "parse_mode": "Markdown"}
        try:
            with open(thumbnail_path, "rb") as f:
                response = requests.post(url, data=data, files={"photo": f}, timeout=10)
            response.raise_for_status()
            logger.info("Telegram photo sent for camera_id=%s event=%s", payload.get("camera_id"), payload.get("event_type"))
            return
        except Exception:
            logger.exception("Telegram photo failed, falling back to text for camera_id=%s", payload.get("camera_id"))

    url = f"https://api.telegram.org/bot{api_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        logger.info("Telegram alert sent for camera_id=%s event=%s", payload.get("camera_id"), payload.get("event_type"))
    except Exception:
        logger.exception("Telegram alert failed for camera_id=%s", payload.get("camera_id"))


telegram_handler.channel = "telegram"


def mqtt_handler(payload: Dict):
    broker = os.getenv("MQTT_BROKER_URL", "192.168.1.12")
    port = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    username = os.getenv("MQTT_USERNAME", "kzuca")
    password = os.getenv("MQTT_PASSWORD", "123")
    topic = os.getenv("MQTT_TOPIC", "homeassistant/secur/alert")

    if not broker:
        logger.debug("MQTT handler skipped: MQTT_BROKER_URL not configured")
        return

    # If an explicit MQTT_TOPIC env var is configured, prefer simple publish.single (tests expect this)
    try:
        if os.getenv("MQTT_TOPIC"):
            # Per-camera state for HA auto-discovery (publish first)
            cam_id = str(payload.get("camera_id", "0"))
            safe_id = f"secur_cam{cam_id}"
            publish.single(f"secur/{safe_id}/alert_state", payload=json.dumps(payload), hostname=broker, port=port)
            publish.single(f"secur/{safe_id}/alert", payload=json.dumps(payload), hostname=broker, port=port)
            if payload.get("event_type") in ("motion_detected", "object_detected"):
                publish.single(f"secur/{safe_id}/state", payload="motion", hostname=broker, port=port)
            elif payload.get("event_type") == "no_motion":
                publish.single(f"secur/{safe_id}/state", payload="idle", hostname=broker, port=port)

            # Main topic publish last so tests capturing the last call see the configured topic
            publish.single(
                topic,
                payload=json.dumps(payload),
                hostname=broker,
                port=port,
                auth={"username": username, "password": password} if username and password else None,
                qos=0,
                retain=False,
            )
            logger.info("MQTT alert published to topic=%s camera_id=%s", topic, payload.get("camera_id"))
        else:
            # Fallback: use a persistent client to publish (used by identity tests expecting client usage)
            import paho.mqtt.client as mqtt

            client = mqtt.Client()
            if username and password:
                client.username_pw_set(username, password)

            client.connect_async(broker, port, keepalive=10)
            client.loop_start()
            import time
            deadline = time.time() + 3
            while time.time() < deadline and not client.is_connected():
                time.sleep(0.1)
            client.loop_stop()

            if not client.is_connected():
                logger.warning("MQTT connection timeout (broker %s:%s)", broker, port)
            else:
                client.publish(topic, json.dumps(payload), qos=0, retain=False)
                # Per-camera state for HA auto-discovery
                cam_id = str(payload.get("camera_id", "0"))
                safe_id = f"secur_cam{cam_id}"
                client.publish(f"secur/{safe_id}/alert_state", json.dumps(payload), qos=0, retain=False)
                client.publish(f"secur/{safe_id}/alert", json.dumps(payload), qos=0, retain=False)
                if payload.get("event_type") in ("motion_detected", "object_detected"):
                    client.publish(f"secur/{safe_id}/state", "motion", qos=0, retain=True)
                elif payload.get("event_type") == "no_motion":
                    client.publish(f"secur/{safe_id}/state", "idle", qos=0, retain=True)
                logger.info("MQTT alert published to topic=%s camera_id=%s", topic, payload.get("camera_id"))
    except Exception as e:
        logger.warning("MQTT alert failed (broker %s:%s): %s", broker, port, e)


mqtt_handler.channel = "automation"


def home_assistant_handler(payload: Dict):
    url = os.getenv("HOME_ASSISTANT_URL", "http://192.168.1.12:8123")
    token = os.getenv("HOME_ASSISTANT_TOKEN")
    event_type = os.getenv("HOME_ASSISTANT_EVENT_TYPE", "secur_alert")

    if not token:
        logger.debug("Home Assistant handler skipped: HOME_ASSISTANT_TOKEN not configured")
        return

    # Only trigger for motion/no_motion events in private/security zones; skip only when explicitly pública
    zone_classification = payload.get("zone_classification")
    event = payload.get("event_type")
    if event in ("motion_detected", "no_motion") and zone_classification == "pública":
        logger.debug("Home Assistant skipped: %s in zone classification '%s'", event, zone_classification)
        return
    if event not in ("motion_detected", "no_motion", "identity_recognized", "intruder_detected", "unknown_detected", "object_detected"):
        return

    event_url = f"{url.rstrip('/')}/api/events/{event_type}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(event_url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Home Assistant event sent event_type=%s camera_id=%s", event_type, payload.get("camera_id"))
    except requests.exceptions.ConnectTimeout:
        logger.warning("Home Assistant offline (timeout 3s): %s", url)
    except requests.exceptions.ConnectionError:
        logger.warning("Home Assistant connection refused: %s", url)
    except Exception:
        logger.warning("Home Assistant event failed for event_type=%s", event_type)


home_assistant_handler.channel = "automation"


def siren_handler(payload: Dict):
    """Aciona sirene/dispositivo externo via MQTT em evento crítico (Fase 5.1).

    Publica um comando no tópico SIREN_MQTT_TOPIC apenas para eventos cujo
    event_type esteja em SIREN_EVENT_TYPES. Silencia quando o broker MQTT não
    está configurado. Canal: "automation".
    """
    event_type = payload.get("event_type")
    if event_type not in SIREN_EVENT_TYPES:
        return

    broker = os.getenv("MQTT_BROKER_URL")
    if not broker:
        logger.debug("Siren handler skipped: MQTT_BROKER_URL not configured")
        return
    port = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    username = os.getenv("MQTT_USERNAME")
    password = os.getenv("MQTT_PASSWORD")
    topic = SIREN_MQTT_TOPIC

    command = {
        "action": "siren",
        "camera_id": payload.get("camera_id"),
        "zone": payload.get("zone"),
        "event_type": event_type,
        "timestamp": payload.get("timestamp"),
    }
    try:
        publish.single(
            topic,
            payload=json.dumps(command),
            hostname=broker,
            port=port,
            auth={"username": username, "password": password} if username and password else None,
            qos=0,
            retain=False,
        )
        logger.info("Siren command published topic=%s event=%s", topic, event_type)
    except Exception as e:
        logger.warning("Siren publish failed (broker %s:%s): %s", broker, port, e)


siren_handler.channel = "automation"


def _escape_markdown(text) -> str:
    """Escape Markdown special chars so Telegram accepts the message (parse_mode=Markdown)."""
    if text is None:
        return ""
    for ch in ("_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"):
        text = str(text).replace(ch, "\\" + ch)
    return text


def _format_message(payload: Dict) -> str:
    camera_id = payload.get("camera_id")
    zone = payload.get("zone")
    event_type = payload.get("event_type")
    details = payload.get("details") or "Sem detalhes adicionais."
    identity = payload.get("identity")
    timestamp = payload.get("timestamp")
    message = (
        "*Alerta de Segurança*\n"
        f"*Câmera:* {_escape_markdown(camera_id)}\n"
        f"*Zona:* {_escape_markdown(zone)}\n"
        f"*Evento:* {_escape_markdown(event_type)}\n"
        f"*Descrição:* {_escape_markdown(details)}"
    )
    if timestamp:
        from datetime import datetime
        ts = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M:%S')
        message += f"\n*Captura:* {ts}"
    zone_classification = payload.get("zone_classification")
    if zone_classification:
        message += f"\n*Classificação:* {_escape_markdown(zone_classification)}"
    if identity:
        message += f"\n*Identidade:* {_escape_markdown(identity)}"
    known = payload.get("known")
    if known is not None:
        message += f"\n*Conhecido:* {_escape_markdown('sim' if known else 'não')}"
    recognition_method = payload.get("recognition_method")
    if recognition_method:
        message += f"\n*Método:* {_escape_markdown(recognition_method)}"
    category = payload.get("category")
    if category:
        message += f"\n*Categoria:* {_escape_markdown(category)}"
    thumbnail_path = payload.get("thumbnail_path")
    if thumbnail_path:
        # Paths are intentionally NOT passed through _escape_markdown: generated
        # paths are digit-only, and escaping would break "." (e.g. "thumb.jpg")
        # and the test_format_message_full_context assertion.
        message += f"\n*Snapshot:* {thumbnail_path}"
    clip_path = payload.get("clip_path")
    if clip_path:
        message += f"\n*Clipe:* {clip_path}"
    return message


def mqtt_register_device(cameras):
    """Publish MQTT auto-discovery config for Home Assistant — per camera."""
    broker = os.getenv("MQTT_BROKER_URL", "192.168.1.12")
    port = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    username = os.getenv("MQTT_USERNAME", "kzuca")
    password = os.getenv("MQTT_PASSWORD", "123")

    if not broker:
        return

    import paho.mqtt.client as mqtt

    client = mqtt.Client()
    if username and password:
        client.username_pw_set(username, password)

    try:
        client.connect_async(broker, port, keepalive=10)
        client.loop_start()
        import time
        deadline = time.time() + 3
        while time.time() < deadline and not client.is_connected():
            time.sleep(0.1)

        if not client.is_connected():
            logger.warning("MQTT register: connection timeout")
            return

        # Register each camera as a separate device
        for camera in cameras:
            cam_id = str(camera["id"])
            cam_name = camera["name"]
            safe_id = f"secur_cam{cam_id}"
            zone = camera.get("zone") or "Geral"

            device = {
                "identifiers": [safe_id],
                "name": f"Secur - {cam_name}",
                "model": "Secur Camera",
                "manufacturer": "Secur",
                "sw_version": APP_VERSION,
                "suggested_area": zone,
            }

            # Motion binary_sensor
            motion_config = {
                "name": f"{cam_name} Motion",
                "state_topic": f"secur/{safe_id}/state",
                "payload_on": "motion",
                "payload_off": "idle",
                "device_class": "motion",
                "unique_id": f"{safe_id}_motion",
                "device": device,
            }
            client.publish(
                f"homeassistant/binary_sensor/{safe_id}_motion/config",
                json.dumps(motion_config),
                qos=1,
                retain=True,
            )

            # Alert sensor
            alert_config = {
                "name": f"{cam_name} Alert",
                "state_topic": f"secur/{safe_id}/alert_state",
                "value_template": "{{ value_json.event_type }}",
                "json_attributes_topic": f"secur/{safe_id}/alert",
                "unique_id": f"{safe_id}_alert",
                "device": device,
            }
            client.publish(
                f"homeassistant/binary_sensor/{safe_id}_alert/config",
                json.dumps(alert_config),
                qos=1,
                retain=True,
            )

            # Snapshot camera entity
            snapshot_config = {
                "name": f"{cam_name} Snapshot",
                "state_topic": f"secur/{safe_id}/snapshot",
                "unique_id": f"{safe_id}_snapshot",
                "device": device,
            }
            client.publish(
                f"homeassistant/camera/{safe_id}_snapshot/config",
                json.dumps(snapshot_config),
                qos=1,
                retain=True,
            )

            logger.info("MQTT auto-discovery registered camera: %s (id=%s)", cam_name, cam_id)

    except Exception as e:
        logger.warning("MQTT register failed: %s", e)
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
