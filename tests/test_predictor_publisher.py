from src.predictor.predictor.publisher import (
    build_prediction_payload, build_discovery_config, publish_prediction,
)


def test_build_prediction_payload_shape():
    d = build_prediction_payload("rosa", "rosa", "19:00-20:00", "pessoa", 0.82, 0.71, 142, "2026-09-06T20:00:00-03:00")
    assert d["schema_version"] == 1
    assert d["modelo"] == "ewma-7d"
    assert d["threshold_sugestao"] == 0.75
    assert "thumbnail" not in str(d)


def test_build_discovery_config_points_to_state_topic():
    cfg = build_discovery_config("rosa")
    assert cfg["state_topic"] == "tucuxi/predictions/rosa"
    assert cfg["value_template"] == "{{ value_json.probabilidade }}"
    assert cfg["expire_after"] == 1800
    assert cfg["unique_id"] == "tucuxi_rosa_prediction"


def test_publish_prediction_retain_true(monkeypatch):
    calls = []
    import src.predictor.predictor.publisher as pub
    monkeypatch.setattr(pub.publish, "single",
                        lambda topic, payload, **kw: calls.append((topic, kw)))
    pub.publish_prediction("127.0.0.1", 1883, None, "rosa", {"schema_version": 1})
    assert calls[0][0] == "tucuxi/predictions/rosa"
    assert calls[0][1].get("retain") is True
