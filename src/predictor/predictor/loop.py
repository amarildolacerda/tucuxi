from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

from . import ha_client
from .actuator import decide_action, publish_actuator
from .entity_map import DEFAULT_ENTITY_MAP, load_entity_map
from .ewma import EWMAModel
from .publisher import build_prediction_payload, publish_prediction


class PredictorLoop:
    """Embalagem A: in-process, fed by LocalEventQueue + periodic tick."""

    def __init__(self, broker: str, port: int, auth: dict | None,
                 entity_map: dict | None = None, publish: bool = True):
        raw = os.getenv("PREDICTOR_ENTITY_MAP", "")
        self.entity_map = entity_map if entity_map is not None else load_entity_map(raw)
        self.models: dict[str, EWMAModel] = {s: EWMAModel() for s in self.entity_map}
        self.samples: dict[str, int] = {s: 0 for s in self.entity_map}
        self.last_trigger: dict[str, float] = {}
        self.broker = broker
        self.port = port
        self.auth = auth
        self.publish = publish
        self.alarm_mode = ha_client.FAIL_SECURE_MODE
        self.alarm_ts = ""

    def set_alarm_mode(self, mode: str, timestamp_iso: str) -> None:
        if mode in ha_client.VALID_MODES:
            self.alarm_mode = mode
            self.alarm_ts = timestamp_iso
            if self.publish:
                self._publish_switch_states(mode)

    def _publish_switch_states(self, mode: str) -> None:
        """Publish switch states so HA reflects the current alarm mode."""
        import paho.mqtt.client as mqtt
        client = mqtt.Client()
        if self.auth and self.auth.get("username"):
            client.username_pw_set(self.auth["username"], self.auth.get("password", ""))
        try:
            client.connect_async(self.broker, self.port, keepalive=10)
            client.loop_start()
            import time
            deadline = time.time() + 3
            while time.time() < deadline and not client.is_connected():
                time.sleep(0.1)
            if not client.is_connected():
                return
            # Alarme switch: ON if armed_home, OFF if disarmed
            alarme_state = "ON" if mode == "armed_home" else "OFF"
            client.publish("tucuxi/mode/alarme/state", alarme_state, retain=True)
            # Viagem switch: ON if armed_away, OFF otherwise
            viagem_state = "ON" if mode == "armed_away" else "OFF"
            client.publish("tucuxi/mode/viagem/state", viagem_state, retain=True)
        except Exception:
            pass
        finally:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass

    def effective_mode(self, now_ts: float | None = None) -> str:
        now = time.time() if now_ts is None else now_ts
        if self.alarm_ts and ha_client.is_stale(self.alarm_ts, now):
            return ha_client.FAIL_SECURE_MODE
        return self.alarm_mode

    def ingest_count(self, slug: str, hour: int, count: int) -> None:
        if slug in self.models:
            self.models[slug].update(hour, count)
            self.samples[slug] += count

    def on_event(self, event, now_ts: float | None = None) -> dict | None:
        now = time.time() if now_ts is None else now_ts
        slug = str(getattr(event, "zone", None) or getattr(event, "camera_id", ""))
        if slug in self.models:
            try:
                hour = datetime.now().astimezone().hour
                self.models[slug].update(hour, 1)
                self.samples[slug] += 1
            except Exception:
                pass
        mode = self.effective_mode(now)
        event_label = str(getattr(event, "event_type", "motion_detected"))
        history_days = os.getenv("PREDICTOR_HISTORY_DAYS", "7")
        motivo = (f"{event_label} em {slug} + modo {mode} "
                  f"({self.samples.get(slug, 0)} eventos em {history_days} dias)")
        cmd = decide_action(slug, mode, event_label,
                            self.entity_map, {}, self.last_trigger.get(slug), now,
                            motivo=motivo)
        if cmd is None:
            return None
        self.last_trigger[slug] = now
        if self.publish:
            publish_actuator(self.broker, self.port, self.auth, cmd)
        return cmd

    def tick(self, now_hour: int) -> list[dict]:
        payloads = []
        for slug, model in self.models.items():
            if self.samples.get(slug, 0) == 0:
                continue
            prob = round(min(1.0, model.predict(now_hour) / 10.0), 3)
            janela = f"{now_hour:02d}:00-{(now_hour + 1) % 24:02d}:00"
            expira = (datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
                      + timedelta(hours=1)).isoformat(timespec="seconds")
            payload = build_prediction_payload(slug, slug, janela, "pessoa", prob, 0.5,
                                               self.samples.get(slug, 0), expira)
            payloads.append(payload)
            if self.publish:
                publish_prediction(self.broker, self.port, self.auth, slug, payload)
        return payloads
