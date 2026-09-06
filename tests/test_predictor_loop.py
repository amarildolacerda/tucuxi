from src.predictor.predictor.loop import PredictorLoop


def test_on_event_armed_rosa_fires_actuator():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.set_alarm_mode("armed_home", "2026-09-06T19:00:00-03:00")

    class E:
        camera_id = "rosa"
        zone = "rosa"
        event_type = "motion_detected"
    cmd = loop.on_event(E(), now_ts=1000.0)
    assert cmd["target_entity"] == "switch.aspersor_rosa"
    assert "rosa" in cmd["motivo"] and "armed_home" in cmd["motivo"]


def test_on_event_disarmed_returns_none():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.set_alarm_mode("disarmed", "2026-09-06T19:00:00-03:00")

    class E:
        camera_id = "rosa"
        zone = "rosa"
        event_type = "motion_detected"
    assert loop.on_event(E(), now_ts=1000.0) is None


def test_tick_returns_prediction_per_slug():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.ingest_count("rosa", 19, 6)
    payloads = loop.tick(now_hour=19)
    assert len(payloads) == 1
    assert payloads[0]["camera"] == "rosa"
    assert payloads[0]["janela"] == "19:00-20:00"
    assert payloads[0]["modelo"] == "ewma-7d"


def test_stale_alarm_mode_falls_back_to_armed():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.set_alarm_mode("disarmed", "2020-01-01T00:00:00-03:00")
    assert loop.effective_mode(now_ts=9999999999.0) == "armed_home"
