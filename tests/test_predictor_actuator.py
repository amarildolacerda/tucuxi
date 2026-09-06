from src.predictor.predictor import actuator, ha_client
from src.predictor.predictor.entity_map import DEFAULT_ENTITY_MAP


def test_armed_rosa_motion_returns_aspersor_command():
    cmd = actuator.decide_action("rosa", "armed_home", "motion_detected",
                                 DEFAULT_ENTITY_MAP, {}, None, 1000.0,
                                 motivo="pessoa na rosa + alarme armado")
    assert cmd is not None
    assert cmd["target_entity"] == "switch.aspersor_rosa"
    assert cmd["duration_sec"] == 300
    assert cmd["condition"] == {"alarm_mode": "armed_home"}
    assert cmd["motivo"] == "pessoa na rosa + alarme armado"


def test_disarmed_suppresses_alarm_required():
    cmd = actuator.decide_action("rosa", "disarmed", "motion_detected",
                                 DEFAULT_ENTITY_MAP, {}, None, 1000.0)
    assert cmd is None


def test_l1_portao_fires_without_alarm_but_still_needs_armed_or_away():
    assert actuator.decide_action("portao_entrada", "armed_home", "motion_detected",
                                  DEFAULT_ENTITY_MAP, {}, None, 1000.0) is not None
    assert actuator.decide_action("portao_entrada", "disarmed", "motion_detected",
                                  DEFAULT_ENTITY_MAP, {}, None, 1000.0) is None


def test_inhibitors_block_action():
    cmd = actuator.decide_action("rosa", "armed_home", "motion_detected",
                                 DEFAULT_ENTITY_MAP,
                                 {"chuva": True}, None, 1000.0)
    assert cmd is None
    cmd2 = actuator.decide_action("rosa", "armed_home", "motion_detected",
                                  DEFAULT_ENTITY_MAP,
                                  {"identidade_conhecida": True}, None, 1000.0)
    assert cmd2 is None


def test_cooldown_blocks_repeat():
    cmd = actuator.decide_action("rosa", "armed_home", "motion_detected",
                                 DEFAULT_ENTITY_MAP, {}, 500.0, 1000.0)
    assert cmd is None


def test_fail_secure_parsing_and_stale():
    assert ha_client.parse_alarm_mode({"alarm_mode": "armed_away"}) == "armed_away"
    assert ha_client.parse_alarm_mode({"alarm_mode": "invalido"}) is None
    assert ha_client.parse_alarm_mode({"schema_version": 999, "alarm_mode": "armed_home"}) is None
    assert ha_client.FAIL_SECURE_MODE == "armed_home"
    assert ha_client.is_stale("2026-09-06T18:00:00-03:00", 9999999999.0) is True


def test_publish_actuator_topic(monkeypatch):
    calls = []
    import src.predictor.predictor.actuator as act
    monkeypatch.setattr(act.publish, "single",
                        lambda topic, payload, **kw: calls.append((topic, kw)))
    act.publish_actuator("127.0.0.1", 1883, None, {"schema_version": 1})
    assert calls[0][0] == "tucuxi/automation/actuator"
    assert calls[0][1].get("retain") is False
