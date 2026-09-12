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


def test_default_initial_mode_is_armed_home():
    """First boot (no saved state): fail-secure default stays armed_home."""
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    assert loop.alarm_mode == "armed_home"
    assert loop._alarme_on is True
    assert loop._viagem_on is False


def test_initial_mode_restored_from_saved_state():
    """Restart: loop must start with the last saved mode, not armed."""
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False,
                         initial_mode="disarmed")
    assert loop.alarm_mode == "disarmed"
    assert loop._alarme_on is False
    assert loop._viagem_on is False

    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False,
                         initial_mode="armed_away")
    assert loop.alarm_mode == "armed_away"
    assert loop._viagem_on is True


def test_set_alarm_mode_persists_via_callback():
    """Every mode change must notify persistence so restart restores it."""
    saved = []
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False,
                         on_mode_change=saved.append)
    loop.set_alarm_mode("disarmed", "")
    assert saved == ["disarmed"]
    loop.set_alarm_mode("armed_away", "")
    assert saved == ["disarmed", "armed_away"]
    # Invalid mode: must not persist
    loop.set_alarm_mode("invalid", "")
    assert saved == ["disarmed", "armed_away"]
