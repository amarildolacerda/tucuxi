from src import alerts


def test_to_enriched_event_maps_payload():
    payload = {"camera_id": "2", "zone": "rosa", "event_type": "motion_detected",
               "zone_classification": "seguranca", "details": "pessoa",
               "thumbnail_path": "data/thumbnails/x.jpg"}
    d = alerts.to_enriched_event(payload, camera_slug="rosa")
    assert d["schema_version"] == 1
    assert d["camera"] == "rosa"
    assert d["camera_id"] == "2"
    assert d["event_type"] == "motion_detected"
    assert "thumbnail_path" not in d


def test_publish_enriched_event_uses_slug_topic(monkeypatch):
    calls = {}
    monkeypatch.setattr(alerts.publish, "single",
                        lambda topic, payload, **kw: calls.setdefault("t", []).append((topic, payload, kw)))
    alerts.publish_enriched_event({"schema_version": 1, "camera": "rosa"})
    topic, payload, kw = calls["t"][0]
    assert topic == "tucuxi/camera/rosa/event"
    assert kw.get("retain") is False
