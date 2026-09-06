import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from src.predictor.predictor.store import PredictorStore


def _seed(tmp_path: Path) -> Path:
    db = tmp_path / "events.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, camera_id TEXT NOT NULL, zone TEXT, event_type TEXT NOT NULL, details TEXT, level INTEGER DEFAULT 0, dropped INTEGER DEFAULT 0, source TEXT DEFAULT 'local', disposition TEXT)")
    now = datetime.now().astimezone()
    for i in range(3):
        ts = (now.replace(hour=19, minute=5) - timedelta(days=i)).isoformat(timespec="seconds")
        con.execute("INSERT INTO events (timestamp, camera_id, event_type) VALUES (?, ?, ?)", (ts, "rosa", "motion_detected"))
    old = (now - timedelta(days=30)).isoformat(timespec="seconds")
    con.execute("INSERT INTO events (timestamp, camera_id, event_type) VALUES (?, ?, ?)", (old, "rosa", "motion_detected"))
    con.execute("INSERT INTO events (timestamp, camera_id, event_type) VALUES (?, ?, ?)", (now.isoformat(timespec="seconds"), "portao", "motion_detected"))
    con.commit()
    con.close()
    return db


def test_count_by_bucket_filters_camera_and_window(tmp_path):
    store = PredictorStore(_seed(tmp_path))
    buckets = store.count_by_bucket("rosa", days=7)
    assert buckets == {19: 3}
    assert store.total_events("rosa", days=7) == 3


def test_unknown_camera_returns_empty(tmp_path):
    store = PredictorStore(_seed(tmp_path))
    assert store.count_by_bucket("inexistente", days=7) == {}
    assert store.total_events("inexistente", days=7) == 0
