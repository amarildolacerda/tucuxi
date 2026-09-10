#!/usr/bin/env python3
"""Verify all fixes are in place."""

import inspect
import sys

print("=== Verifying Fixes ===")

# 1. Check alarm_mode_telegram_handler
try:
    from src.alerts import alarm_mode_telegram_handler
    print("1. alarm_mode_telegram_handler: OK")
except ImportError as e:
    print(f"1. alarm_mode_telegram_handler: FAIL - {e}")

# 2. Check _on_alarme_set_msg in main.py
try:
    from src.main import main
    source = inspect.getsource(main)
    has_alarme = '_on_alarme_set_msg' in source
    has_publish = 'client.publish("tucuxi/ha/alarm_mode"' in source
    print(f"2. _on_alarme_set_msg: {'OK' if has_alarme else 'MISSING'}")
    print(f"3. Publishes to tucuxi/ha/alarm_mode: {'OK' if has_publish else 'MISSING'}")
except ImportError as e:
    print(f"2-3. main import: FAIL - {e}")

# 4. Check _publish_switch_states in loop.py __init__
try:
    from src.predictor.predictor.loop import PredictorLoop
    loop_source = inspect.getsource(PredictorLoop.__init__)
    has_publish_init = '_publish_switch_states' in loop_source
    print(f"4. _publish_switch_states in __init__: {'OK' if has_publish_init else 'MISSING'}")
except ImportError as e:
    print(f"4. loop import: FAIL - {e}")

# 5. Check initial state publish in alerts.py
try:
    with open('src/alerts.py') as f:
        alerts_source = f.read()
    has_initial = 'probabilidade": 0' in alerts_source and 'alarm_mode": "disarmed"' in alerts_source
    print(f"5. Initial states published: {'OK' if has_initial else 'CHECK'}")
except Exception as e:
    print(f"5. alerts.py read: FAIL - {e}")

print("\n=== All checks complete ===")