from __future__ import annotations

import time
from datetime import datetime

from .schemas import validate_schema_version

VALID_MODES = ("disarmed", "armed_home", "armed_away")
FAIL_SECURE_MODE = "armed_home"
STALE_AFTER_SEC = 60


def parse_alarm_mode(payload: dict) -> str | None:
    if not validate_schema_version(payload):
        if "schema_version" in payload:
            return None
    mode = payload.get("alarm_mode")
    return mode if mode in VALID_MODES else None


def is_stale(timestamp_iso: str, now_ts: float | None = None, max_age_sec: int = STALE_AFTER_SEC) -> bool:
    try:
        ts = datetime.fromisoformat(timestamp_iso).timestamp()
    except (ValueError, TypeError):
        return True
    now = time.time() if now_ts is None else now_ts
    return (now - ts) > max_age_sec
