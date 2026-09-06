from src import alerts
from src.predictor.predictor.loop import PredictorLoop
from src.predictor.predictor.schemas import validate_schema_version


def test_e2e_rosa_armed_fires_aspersor():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.set_alarm_mode("armed_home", "2026-09-06T19:00:00-03:00")
    payload = {"camera_id": "2", "zone": "rosa", "event_type": "motion_detected",
               "zone_classification": "seguranca", "details": "pessoa"}

    class E:
        camera_id = "rosa"
        zone = "rosa"
        event_type = "motion_detected"

    enriched = alerts.to_enriched_event(payload)
    assert validate_schema_version(enriched)
    cmd = loop.on_event(E(), now_ts=2000.0)
    assert validate_schema_version(cmd)
    assert cmd["target_entity"] == "switch.aspersor_rosa"
    assert cmd["duration_sec"] == 300
    assert "rosa" in cmd["motivo"]


def test_e2e_disarmed_silence_and_tick_shape():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.set_alarm_mode("disarmed", "2026-09-06T19:00:00-03:00")

    class E:
        camera_id = "rosa"
        zone = "rosa"
        event_type = "motion_detected"

    assert loop.on_event(E(), now_ts=2000.0) is None
    payloads = loop.tick(now_hour=19)
    assert len(payloads) >= 1
    assert all(validate_schema_version(p) for p in payloads)
    assert all("thumbnail" not in str(p) for p in payloads)
