from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


class PredictorStore:
    """Read-only aggregates over the Tucuxi `events` table."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _since_iso(self, days: int) -> str:
        since = datetime.now().astimezone() - timedelta(days=days)
        return since.isoformat(timespec="seconds")

    def count_by_bucket(self, camera_slug: str, days: int = 7) -> dict[int, int]:
        con = sqlite3.connect(str(self.db_path))
        try:
            cur = con.execute(
                "SELECT timestamp FROM events WHERE camera_id = ? AND timestamp >= ?",
                (camera_slug, self._since_iso(days)),
            )
            buckets: dict[int, int] = {}
            for (ts,) in cur.fetchall():
                try:
                    hour = datetime.fromisoformat(ts).hour
                except ValueError:
                    continue
                buckets[hour] = buckets.get(hour, 0) + 1
            return buckets
        finally:
            con.close()

    def total_events(self, camera_slug: str, days: int = 7) -> int:
        return sum(self.count_by_bucket(camera_slug, days).values())
