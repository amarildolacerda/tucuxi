from src.predictor.predictor import entity_map as em


def test_default_map_has_rosa_and_alias():
    assert em.DEFAULT_ENTITY_MAP["rosa"]["ha_actuator"] == "switch.aspersor_rosa"
    assert em.DEFAULT_ENTITY_MAP["rosa"]["default_duration_sec"] == 300
    assert em.resolve_zone("acesso_jardim", em.DEFAULT_ENTITY_MAP)["ha_actuator"] == "switch.aspersor_rosa"


def test_l1_portao_needs_no_alarm():
    entry = em.resolve_zone("portao_entrada", em.DEFAULT_ENTITY_MAP)
    assert entry["alarm_required"] is False
    assert entry["ha_actuator"] == "light.perimetral"


def test_load_entity_map_overrides_default():
    raw = '{"rosa": {"ha_actuator": "switch.outro", "default_duration_sec": 60, "alarm_required": true, "modos_ativos": ["viagem"]}}'
    merged = em.load_entity_map(raw)
    assert merged["rosa"]["ha_actuator"] == "switch.outro"
    assert merged["portao_entrada"]["ha_actuator"] == "light.perimetral"


def test_config_defaults(monkeypatch):
    import importlib, src.config as cfg
    monkeypatch.delenv("PREDICTOR_ENABLED", raising=False)
    importlib.reload(cfg)
    assert cfg.PREDICTOR_ENABLED is False
    assert cfg.PREDICTOR_HISTORY_DAYS == 7
    assert cfg.PREDICTOR_INTERVAL_SECONDS == 900
    assert cfg.PREDICTION_THRESHOLD == 0.75
    assert cfg.PREDICTOR_DETER_COOLDOWN_SEC == 900
