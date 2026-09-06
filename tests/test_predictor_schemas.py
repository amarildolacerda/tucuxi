from src.predictor.predictor.schemas import (
    EnrichedEvent, Prediction, ActuatorCommand, validate_schema_version,
)


def test_enriched_event_to_dict_has_schema_version_1():
    e = EnrichedEvent(camera="rosa", camera_id="2", zone="rosa",
                      zone_classification="seguranca", event_type="motion_detected")
    d = e.to_dict()
    assert d["schema_version"] == 1
    assert d["camera"] == "rosa"
    assert "thumbnail_path" not in d


def test_prediction_to_dict_never_has_thumbnail():
    p = Prediction(camera="rosa", zone="rosa", janela="19:00-20:00",
                   evento_previsto="pessoa", probabilidade=0.82,
                   confianca_modelo=0.71, modelo="ewma-7d", amostras=142)
    d = p.to_dict()
    assert d["schema_version"] == 1
    assert d["probabilidade"] == 0.82
    assert "thumbnail" not in str(d)


def test_actuator_command_to_dict():
    c = ActuatorCommand(action="turn_on", camera="rosa", zone="rosa",
                        event_type="motion_detected",
                        target_entity="switch.aspersor_rosa", duration_sec=300,
                        alarm_mode="armed_home",
                        motivo="pessoa na rosa + alarme armado (base 7 dias, 142 amostras)")
    d = c.to_dict()
    assert d["target_entity"] == "switch.aspersor_rosa"
    assert d["duration_sec"] == 300
    assert d["motivo"] == "pessoa na rosa + alarme armado (base 7 dias, 142 amostras)"


def test_validate_schema_version_rejects_unknown():
    assert validate_schema_version({"schema_version": 1}) is True
    assert validate_schema_version({"schema_version": 999}) is False
    assert validate_schema_version({}) is False
