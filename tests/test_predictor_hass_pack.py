from pathlib import Path
import yaml


def test_hass_pack_has_sensors_switches_automations():
    text = Path("hass/tucuxi_mvp.yaml").read_text(encoding="utf-8")
    pack = yaml.safe_load(text)
    sensor_topics = [s["state_topic"] for s in pack["mqtt"]["sensor"]]
    assert "tucuxi/predictions/rosa" in sensor_topics
    switch_topics = [s["command_topic"] for s in pack["mqtt"]["switch"]]
    assert "tucuxi/mode/alarme/set" in switch_topics
    assert "tucuxi/mode/viagem/set" in switch_topics
    aliases = [a["alias"] for a in pack["automation"]]
    assert any("aspersor" in a for a in aliases)
    rosa_auto = next(a for a in pack["automation"] if "aspersor" in a["alias"])
    assert rosa_auto["mode"] == "single"
    assert "tucuxi/automation/actuator" in str(rosa_auto["trigger"])
    assert "motivo" in str(rosa_auto["action"])
