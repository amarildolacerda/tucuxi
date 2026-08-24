import logging
import json
import sqlite3
import threading
import time
import sys
import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from .config import DB_PATH, IDENTITY_EMBEDDINGS_DIR

logger = logging.getLogger(__name__)


class EventStorage:
    def __init__(self, db_path: Path = DB_PATH):
        # When running under pytest, ensure a fresh DB to avoid cross-test pollution
        self.db_path = Path(db_path)
        try:
            running_pytest = "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules
        except Exception:
            running_pytest = False
        if running_pytest and self.db_path.exists():
            try:
                self.db_path.unlink()
            except Exception:
                pass
        self.connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._create_tables()

    def _create_tables(self):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    zone TEXT,
                    event_type TEXT NOT NULL,
                    details TEXT,
                    level INTEGER DEFAULT 0,
                    dropped INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'local',
                    disposition TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS cameras (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    zone TEXT,
                    alert_classes TEXT,
                    exclusion_zones TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS zones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    classification TEXT NOT NULL DEFAULT 'pública',
                    schedule TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS known_identities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    species TEXT NOT NULL DEFAULT 'person',
                    created_at TEXT NOT NULL,
                    embedding_path TEXT NOT NULL,
                    thumbnail_path TEXT
                )
                """
            )
            # Ensure thumbnail_path column exists for older DBs
            try:
                cursor.execute("PRAGMA table_info(known_identities)")
                cols = [r[1] for r in cursor.fetchall()]
                if 'thumbnail_path' not in cols:
                    cursor.execute("ALTER TABLE known_identities ADD COLUMN thumbnail_path TEXT")
            except Exception:
                pass
            # Ensure new camera columns exist for older DBs
            try:
                cursor.execute("PRAGMA table_info(cameras)")
                cols = [r[1] for r in cursor.fetchall()]
                if 'alert_classes' not in cols:
                    cursor.execute("ALTER TABLE cameras ADD COLUMN alert_classes TEXT")
                if 'exclusion_zones' not in cols:
                    cursor.execute("ALTER TABLE cameras ADD COLUMN exclusion_zones TEXT")
                if 'mask_polygons' not in cols:
                    cursor.execute("ALTER TABLE cameras ADD COLUMN mask_polygons TEXT")
            except Exception:
                pass
            # Ensure schedule column exists for older DBs
            try:
                cursor.execute("PRAGMA table_info(zones)")
                cols = [r[1] for r in cursor.fetchall()]
                if 'schedule' not in cols:
                    cursor.execute("ALTER TABLE zones ADD COLUMN schedule TEXT")
                if 'retention_policy' not in cols:
                    cursor.execute("ALTER TABLE zones ADD COLUMN retention_policy TEXT")
                if 'direction_line' not in cols:
                    cursor.execute("ALTER TABLE zones ADD COLUMN direction_line TEXT")
            except Exception:
                pass
            # Ensure clip_path column exists for older DBs
            try:
                cursor.execute("PRAGMA table_info(events)")
                cols = [r[1] for r in cursor.fetchall()]
                if 'clip_path' not in cols:
                    cursor.execute("ALTER TABLE events ADD COLUMN clip_path TEXT")
                for col, ddl in (("level", "INTEGER DEFAULT 0"), ("dropped", "INTEGER DEFAULT 0"), ("source", "TEXT DEFAULT 'local'"), ("disposition", "TEXT"), ("retained", "INTEGER DEFAULT 0")):
                    if col not in cols:
                        cursor.execute(f"ALTER TABLE events ADD COLUMN {col} {ddl}")
            except Exception:
                pass
            # Ensure event_id column exists in camera_thumbnails for older DBs
            try:
                cursor.execute("PRAGMA table_info(camera_thumbnails)")
                cols = [r[1] for r in cursor.fetchall()]
                if 'event_id' not in cols:
                    cursor.execute("ALTER TABLE camera_thumbnails ADD COLUMN event_id TEXT")
            except Exception:
                pass
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS camera_thumbnails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT,
                    path TEXT NOT NULL,
                    event_id TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS event_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id INTEGER NOT NULL,
                    event_id INTEGER,
                    timestamp TEXT NOT NULL,
                    path TEXT NOT NULL,
                    duration_s REAL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_routing (
                    channel TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (channel, event_type)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            # ── Auth tables ──
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','chefe_seguranca','vigilante','viewer')),
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    last_login TEXT,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    ip_address TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS role_permissions (
                    role TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (role, permission)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_hash TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    permissions TEXT,
                    created_by INTEGER REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    last_used TEXT,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id),
                    api_key_id INTEGER REFERENCES api_keys(id),
                    action TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    details TEXT,
                    ip_address TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_cameras (
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    camera_id INTEGER NOT NULL REFERENCES cameras(id),
                    PRIMARY KEY (user_id, camera_id)
                )
                """
            )
            self.connection.commit()

    def add_event(self, camera_id, zone, event_type, details=None, level=0, source="local", dropped=False):
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO events (timestamp, camera_id, zone, event_type, details, level, dropped, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (timestamp, camera_id, zone, event_type, details, level, 1 if dropped else 0, source),
            )
            self.connection.commit()
            return cursor.lastrowid

    def update_event_level(self, event_id, level, event_type=None, details=None, disposition=None):
        with self.lock:
            cursor = self.connection.cursor()
            sets, params = ["level = ?"], [level]
            if event_type is not None:
                sets.append("event_type = ?"); params.append(event_type)
            if details is not None:
                sets.append("details = ?"); params.append(details)
            if disposition is not None:
                sets.append("disposition = ?"); params.append(disposition)
            params.append(event_id)
            cursor.execute(f"UPDATE events SET {', '.join(sets)} WHERE id = ?", params)
            self.connection.commit()
            return cursor.rowcount > 0

    def list_events(self, limit=100, level=None, camera_id=None, source=None, retained=None,
                    start=None, end=None):
        with self.lock:
            cursor = self.connection.cursor()
            sql = ("SELECT id, timestamp, camera_id, zone, event_type, details, clip_path, level, dropped, source, retained "
                   "FROM events WHERE 1=1")
            params = []
            if level is not None:
                sql += " AND level = ?"; params.append(level)
            if camera_id is not None:
                sql += " AND camera_id = ?"; params.append(str(camera_id))
            if source is not None:
                sql += " AND source = ?"; params.append(source)
            if retained is not None:
                sql += " AND retained = ?"; params.append(1 if retained else 0)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            cursor.execute(sql, params)
            rows = [dict(row) for row in cursor.fetchall()]
        if start is not None or end is not None:
            filtered = []
            for row in rows:
                try:
                    ts = datetime.fromisoformat(row["timestamp"]).timestamp()
                except (ValueError, TypeError):
                    continue
                if start is not None and ts < float(start):
                    continue
                if end is not None and ts > float(end):
                    continue
                filtered.append(row)
            rows = filtered
        return rows

    def add_camera(self, name: str, source: str, zone: str = None, alert_classes=None, exclusion_zones=None, mask_polygons=None):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO cameras (name, source, zone, alert_classes, exclusion_zones, mask_polygons) VALUES (?, ?, ?, ?, ?, ?)",
                (name, source, zone,
                 json.dumps(alert_classes) if alert_classes else None,
                 json.dumps(exclusion_zones) if exclusion_zones else None,
                 json.dumps(mask_polygons) if mask_polygons else None),
            )
            self.connection.commit()
            return cursor.lastrowid

    def list_cameras(self):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT id, name, source, zone, alert_classes, exclusion_zones, mask_polygons FROM cameras ORDER BY id ASC")
            rows = [dict(row) for row in cursor.fetchall()]
        for row in rows:
            row["alert_classes"] = json.loads(row["alert_classes"]) if row.get("alert_classes") else None
            row["exclusion_zones"] = json.loads(row["exclusion_zones"]) if row.get("exclusion_zones") else None
            row["mask_polygons"] = json.loads(row["mask_polygons"]) if row.get("mask_polygons") else None
        return rows

    def get_camera(self, camera_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT id, name, source, zone, alert_classes, exclusion_zones, mask_polygons FROM cameras WHERE id = ?", (camera_id,))
            row = cursor.fetchone()
            if not row:
                return None
            camera = dict(row)
        camera["alert_classes"] = json.loads(camera["alert_classes"]) if camera.get("alert_classes") else None
        camera["exclusion_zones"] = json.loads(camera["exclusion_zones"]) if camera.get("exclusion_zones") else None
        camera["mask_polygons"] = json.loads(camera["mask_polygons"]) if camera.get("mask_polygons") else None
        return camera

    def update_camera(self, camera_id: int, name: str, source: str, zone: str = None, alert_classes=None, exclusion_zones=None, mask_polygons=None):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "UPDATE cameras SET name = ?, source = ?, zone = ?, alert_classes = ?, exclusion_zones = ?, mask_polygons = ? WHERE id = ?",
                (name, source, zone,
                 json.dumps(alert_classes) if alert_classes else None,
                 json.dumps(exclusion_zones) if exclusion_zones else None,
                 json.dumps(mask_polygons) if mask_polygons else None,
                 camera_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    def remove_camera(self, camera_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
            self.connection.commit()
            return cursor.rowcount > 0

    def seed_cameras(self, default_cameras):
        if self.list_cameras():
            return
        for camera in default_cameras:
            self.add_camera(camera["name"], camera["source"], camera.get("zone"))

    def add_zone(self, name: str, classification: str = 'pública', schedule=None, retention_policy=None, direction_line=None):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO zones (name, classification, schedule, retention_policy, direction_line) VALUES (?, ?, ?, ?, ?)",
                (name, classification, json.dumps(schedule) if schedule else None,
                 json.dumps(retention_policy) if retention_policy else None,
                 json.dumps(direction_line) if direction_line else None),
            )
            self.connection.commit()
            return cursor.lastrowid

    def list_zones(self):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT id, name, classification, schedule, retention_policy, direction_line FROM zones ORDER BY id ASC")
            rows = [dict(row) for row in cursor.fetchall()]
        for row in rows:
            row["schedule"] = json.loads(row["schedule"]) if row.get("schedule") else None
            row["retention_policy"] = json.loads(row["retention_policy"]) if row.get("retention_policy") else None
            row["direction_line"] = json.loads(row["direction_line"]) if row.get("direction_line") else None
        return rows

    def get_zone(self, zone_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT id, name, classification, schedule, retention_policy, direction_line FROM zones WHERE id = ?", (zone_id,))
            row = cursor.fetchone()
            if not row:
                return None
            zone = dict(row)
        zone["schedule"] = json.loads(zone["schedule"]) if zone.get("schedule") else None
        zone["retention_policy"] = json.loads(zone["retention_policy"]) if zone.get("retention_policy") else None
        zone["direction_line"] = json.loads(zone["direction_line"]) if zone.get("direction_line") else None
        return zone

    def update_zone(self, zone_id: int, name: str, classification: str, schedule=None, retention_policy=None, direction_line=None):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "UPDATE zones SET name = ?, classification = ?, schedule = ?, retention_policy = ?, direction_line = ? WHERE id = ?",
                (name, classification, json.dumps(schedule) if schedule else None,
                 json.dumps(retention_policy) if retention_policy else None,
                 json.dumps(direction_line) if direction_line else None, zone_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    def remove_zone(self, zone_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM zones WHERE id = ?", (zone_id,))
            self.connection.commit()
            return cursor.rowcount > 0

    def seed_zones(self, default_zones):
        if self.list_zones():
            return
        for zone in default_zones:
            self.add_zone(zone["name"], zone.get("classification", "pública"))

    def save_identity_embedding(self, name: str, embedding: np.ndarray) -> str:
        safe = "".join(c if c.isalnum() else "_" for c in name)
        filename = f"{safe}_{int(time.time() * 1000)}.npy"
        path = IDENTITY_EMBEDDINGS_DIR / filename
        np.save(str(path), np.asarray(embedding, dtype=np.float32))
        return str(path)

    def save_identity_thumbnail(self, name: str, b64data: str) -> str:
        """Save a base64-encoded JPEG thumbnail for an identity and return the path."""
        safe = "".join(c if c.isalnum() else "_" for c in name)
        thumbs_dir = IDENTITY_EMBEDDINGS_DIR / "thumbnails"
        thumbs_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{safe}_{int(time.time() * 1000)}.jpg"
        path = thumbs_dir / filename
        try:
            import base64

            raw = base64.b64decode(b64data)
            with open(path, "wb") as f:
                f.write(raw)
            return str(path)
        except Exception as e:
            logger.warning("Failed to save thumbnail: %s", e)
            return ""

    def update_identity_thumbnail(self, identity_id: int, thumbnail_path: str) -> bool:
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "UPDATE known_identities SET thumbnail_path = ? WHERE id = ?",
                (thumbnail_path, identity_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    def add_identity(self, name: str, species: str, embedding_path: str):
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO known_identities (name, species, created_at, embedding_path) VALUES (?, ?, ?, ?)",
                (name, species, timestamp, embedding_path),
            )
            self.connection.commit()
            return cursor.lastrowid

    def list_identities(self):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT id, name, species, created_at, thumbnail_path FROM known_identities ORDER BY id ASC")
            return [dict(row) for row in cursor.fetchall()]

    def get_identity(self, identity_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT id, name, species, created_at, embedding_path, thumbnail_path FROM known_identities WHERE id = ?", (identity_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def load_identity_embedding(self, identity_id: int):
        ident = self.get_identity(identity_id)
        if not ident:
            return None
        p = Path(ident["embedding_path"])
        if not p.exists():
            return None
        return np.load(str(p))

    def remove_identity(self, identity_id: int):
        ident = self.get_identity(identity_id)
        if not ident:
            return False
        try:
            Path(ident["embedding_path"]).unlink(missing_ok=True)
        except Exception:
            logger.warning("Falha ao remover arquivo de embedding para identidade %s", identity_id)
        thumb = ident.get("thumbnail_path")
        if thumb:
            try:
                Path(thumb).unlink(missing_ok=True)
            except Exception:
                logger.warning("Falha ao remover thumbnail para identidade %s", identity_id)
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM known_identities WHERE id = ?", (identity_id,))
            self.connection.commit()
            return cursor.rowcount > 0

    def add_camera_thumbnail(self, camera_id: int, path: str, event_type: str, event_id: str = None) -> int:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO camera_thumbnails (camera_id, timestamp, event_type, path, event_id) VALUES (?, ?, ?, ?, ?)",
                (camera_id, timestamp, event_type, path, event_id),
            )
            self.connection.commit()
            return cursor.lastrowid

    def list_camera_thumbnails(self, camera_id: int, limit: int = 20):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT t.id, t.timestamp, t.camera_id, t.event_type, t.path, t.event_id, "
                "       e.level AS event_level, e.disposition AS event_disposition, e.dropped AS event_dropped "
                "FROM camera_thumbnails t "
                "LEFT JOIN events e ON e.id = t.event_id "
                "WHERE t.camera_id = ? ORDER BY t.id DESC LIMIT ?",
                (camera_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def prune_camera_thumbnails(self, camera_id: int, keep: int = 20, max_age_days: int = None):
        with self.lock:
            cursor = self.connection.cursor()
            if max_age_days:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
                cursor.execute(
                    "SELECT id, path FROM camera_thumbnails WHERE camera_id = ? AND timestamp < ?",
                    (camera_id, cutoff),
                )
                for item in [dict(row) for row in cursor.fetchall()]:
                    try:
                        Path(item["path"]).unlink(missing_ok=True)
                    except Exception:
                        logger.warning("Falha ao remover thumbnail %s", item["path"])
                    cursor.execute("DELETE FROM camera_thumbnails WHERE id = ?", (item["id"],))
            cursor.execute(
                "SELECT id, path FROM camera_thumbnails WHERE camera_id = ? ORDER BY id DESC LIMIT -1 OFFSET ?",
                (camera_id, keep),
            )
            excess = [dict(row) for row in cursor.fetchall()]
            for item in excess:
                try:
                    Path(item["path"]).unlink(missing_ok=True)
                except Exception:
                    logger.warning("Falha ao remover thumbnail %s", item["path"])
                cursor.execute("DELETE FROM camera_thumbnails WHERE id = ?", (item["id"],))
            self.connection.commit()

    def remove_camera_thumbnails(self, camera_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT path FROM camera_thumbnails WHERE camera_id = ?", (camera_id,))
            rows = cursor.fetchall()
            for row in rows:
                try:
                    Path(row["path"]).unlink(missing_ok=True)
                except Exception:
                    logger.warning("Falha ao remover thumbnail %s", row["path"])
            cursor.execute("DELETE FROM camera_thumbnails WHERE camera_id = ?", (camera_id,))
            self.connection.commit()

    def get_camera_thumbnail(self, thumb_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT id, camera_id, timestamp, event_type, path FROM camera_thumbnails WHERE id = ?",
                (thumb_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def add_event_clip(self, camera_id: int, event_id, path: str, duration_s: float) -> int:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO event_clips (camera_id, event_id, timestamp, path, duration_s) VALUES (?, ?, ?, ?, ?)",
                (camera_id, event_id, timestamp, path, duration_s),
            )
            self.connection.commit()
            return cursor.lastrowid

    def list_event_clips(self, camera_id: int, limit: int = 20):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT id, camera_id, event_id, timestamp, path, duration_s FROM event_clips "
                "WHERE camera_id = ? ORDER BY id DESC LIMIT ?",
                (camera_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_event_clip(self, clip_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT id, camera_id, event_id, timestamp, path, duration_s FROM event_clips WHERE id = ?",
                (clip_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_event_thumbnail_path(self, event_id):
        """Retorna o path da thumbnail associada a um evento (camera_thumbnails.event_id)."""
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT path FROM camera_thumbnails WHERE event_id = ? ORDER BY id DESC LIMIT 1",
                (str(event_id),),
            )
            row = cursor.fetchone()
            return row["path"] if row else None

    def get_event_clip_path(self, event_id):
        """Retorna o path do clipe de um evento (events.clip_path ou event_clips)."""
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT clip_path FROM events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            if row and row["clip_path"]:
                return row["clip_path"]
            cursor.execute(
                "SELECT path FROM event_clips WHERE event_id = ? ORDER BY id DESC LIMIT 1",
                (str(event_id),),
            )
            row = cursor.fetchone()
            return row["path"] if row else None

    def prune_event_clips(self, camera_id: int, keep: int = 20, max_age_days: int = None):
        with self.lock:
            cursor = self.connection.cursor()
            if max_age_days:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
                cursor.execute(
                    "SELECT id, path FROM event_clips WHERE camera_id = ? AND timestamp < ?",
                    (camera_id, cutoff),
                )
                for item in [dict(row) for row in cursor.fetchall()]:
                    try:
                        Path(item["path"]).unlink(missing_ok=True)
                    except Exception:
                        logger.warning("Falha ao remover clipe %s", item["path"])
                    cursor.execute("DELETE FROM event_clips WHERE id = ?", (item["id"],))
            cursor.execute(
                "SELECT id, path FROM event_clips WHERE camera_id = ? ORDER BY id DESC LIMIT -1 OFFSET ?",
                (camera_id, keep),
            )
            excess = [dict(row) for row in cursor.fetchall()]
            for item in excess:
                try:
                    Path(item["path"]).unlink(missing_ok=True)
                except Exception:
                    logger.warning("Falha ao remover clipe %s", item["path"])
                cursor.execute("DELETE FROM event_clips WHERE id = ?", (item["id"],))
            self.connection.commit()

    def remove_event_clips(self, camera_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT path FROM event_clips WHERE camera_id = ?", (camera_id,))
            rows = cursor.fetchall()
            for row in rows:
                try:
                    Path(row["path"]).unlink(missing_ok=True)
                except Exception:
                    logger.warning("Falha ao remover clipe %s", row["path"])
            cursor.execute("DELETE FROM event_clips WHERE camera_id = ?", (camera_id,))
            self.connection.commit()

    def prune_events(self, type_days: dict = None, default_days: float = -1, max_age_days: float = -1):
        """Remove eventos antigos por TIPO de evento (ignora level), com Idade Máxima
        como rede de segurança final. Eventos retidos (retained=1) nunca são removidos.

        Garantia de análise: eventos ainda em voo (disposition IS NULL E dropped = 0)
        NUNCA são removidos, independente da idade. Isso assegura que a automação
        (Home Assistant/MQTT) seja notificada antes do prune — o AlertRuleEngine só
        define `disposition` após analisar e disparar os handlers. Eventos dropados
        (dropped = 1, triados como ruído na N1) e analisados (disposition definido)
        podem ser podados normalmente.

        Args:
            type_days: dict {event_type: dias}. 0 = remove todos imediatamente;
                       <0 = nunca podar por tipo (só Idade Máx.); omissão = usa config.
            default_days: retenção padrão (dias) para tipos não previstos em type_days.
                          -1 = usa EVENT_PRUNE_DEFAULT_DAYS.
            max_age_days: idade máxima (dias) de qualquer evento não retido, ao final.
                          -1 = usa EVENT_PRUNE_MAX_AGE_DAYS; 0 = remove todos os não retidos.
        """
        from src import config as cfg
        if type_days is None:
            type_days = cfg.EVENT_PRUNE_TYPE_DAYS
        default_days = default_days if default_days >= 0 else cfg.EVENT_PRUNE_DEFAULT_DAYS
        max_age_days = max_age_days if max_age_days >= 0 else cfg.EVENT_PRUNE_MAX_AGE_DAYS
        
        deleted = 0
        with self.lock:
            cursor = self.connection.cursor()
            now = datetime.now(timezone.utc)
            
            # Helper: get event IDs to be deleted, then remove associated thumbnails/clips
            def _collect_and_delete_event_ids(where_sql, params):
                """Retorna IDs que batem com a condição (exceto retidos) E que já
                foram analisados. Garantia: eventos em voo (disposition IS NULL E
                dropped = 0) NUNCA são podados — só após análise (disposition
                definido) ou triagem como ruído (dropped = 1)."""
                cursor.execute(
                    f"SELECT id FROM events WHERE {where_sql} AND retained = 0 "
                    f"AND (disposition IS NOT NULL OR dropped = 1)",
                    params,
                )
                return [row["id"] for row in cursor.fetchall()]
            
            def _delete_orphaned_media(event_ids):
                """Delete thumbnails and clips associated with given event IDs."""
                if not event_ids:
                    return
                placeholders = ",".join("?" * len(event_ids))
                # Delete thumbnails
                cursor.execute(
                    f"SELECT path FROM camera_thumbnails WHERE event_id IN ({placeholders})",
                    event_ids
                )
                for row in cursor.fetchall():
                    try:
                        Path(row["path"]).unlink(missing_ok=True)
                    except Exception:
                        logger.warning("Falha ao remover thumbnail órfão %s", row["path"])
                cursor.execute(
                    f"DELETE FROM camera_thumbnails WHERE event_id IN ({placeholders})",
                    event_ids
                )
                # Delete clips
                cursor.execute(
                    f"SELECT path FROM event_clips WHERE event_id IN ({placeholders})",
                    event_ids
                )
                for row in cursor.fetchall():
                    try:
                        Path(row["path"]).unlink(missing_ok=True)
                    except Exception:
                        logger.warning("Falha ao remover clipe órfão %s", row["path"])
                cursor.execute(
                    f"DELETE FROM event_clips WHERE event_id IN ({placeholders})",
                    event_ids
                )
            
            # 1) Por tipo de evento (ignorando level)
            cursor.execute("SELECT DISTINCT event_type FROM events")
            present_types = [r["event_type"] for r in cursor.fetchall()]
            for etype in present_types:
                days = type_days.get(etype, default_days)
                if days < 0:
                    continue  # tipo com -1: não podar por tipo (só Idade Máx.)
                if days == 0:
                    event_ids = _collect_and_delete_event_ids("event_type = ?", (etype,))
                else:
                    cutoff = (now - timedelta(days=days)).isoformat()
                    event_ids = _collect_and_delete_event_ids("event_type = ? AND timestamp < ?", (etype, cutoff))
                if event_ids:
                    _delete_orphaned_media(event_ids)
                    placeholders = ",".join("?" * len(event_ids))
                    cursor.execute(f"DELETE FROM events WHERE id IN ({placeholders})", event_ids)
                    deleted += len(event_ids)

            # 2) Idade Máxima — rede de segurança final para qualquer não retido
            if max_age_days >= 0:
                if max_age_days == 0:
                    event_ids = _collect_and_delete_event_ids("1=1", ())
                else:
                    cutoff = (now - timedelta(days=max_age_days)).isoformat()
                    event_ids = _collect_and_delete_event_ids("timestamp < ?", (cutoff,))
                if event_ids:
                    _delete_orphaned_media(event_ids)
                    placeholders = ",".join("?" * len(event_ids))
                    cursor.execute(f"DELETE FROM events WHERE id IN ({placeholders})", event_ids)
                    deleted += len(event_ids)
            
            self.connection.commit()
        return deleted

    def update_event_clip_path(self, event_id: int, clip_path: str) -> bool:
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "UPDATE events SET clip_path = ? WHERE id = ?",
                (clip_path, event_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    def get_routing(self, channel: str) -> dict:
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT event_type, enabled FROM notification_routing WHERE channel = ?",
                (channel,),
            )
            return {row["event_type"]: bool(row["enabled"]) for row in cursor.fetchall()}

    def set_routing(self, channel: str, event_type: str, enabled: bool):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO notification_routing (channel, event_type, enabled) VALUES (?, ?, ?) "
                "ON CONFLICT(channel, event_type) DO UPDATE SET enabled = excluded.enabled",
                (channel, event_type, int(enabled)),
            )
            self.connection.commit()

    def get_all_routing(self) -> dict:
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT channel, event_type, enabled FROM notification_routing")
            routing = {}
            for row in cursor.fetchall():
                routing.setdefault(row["channel"], {})[row["event_type"]] = bool(row["enabled"])
            return routing

    def seed_default_routing(self, defaults: dict):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM notification_routing")
            if cursor.fetchone()["c"] > 0:
                return
            for channel, events in defaults.items():
                for event_type, enabled in events.items():
                    cursor.execute(
                        "INSERT INTO notification_routing (channel, event_type, enabled) VALUES (?, ?, ?)",
                        (channel, event_type, int(enabled)),
                    )
            self.connection.commit()

    def ensure_default_routing(self, defaults: dict):
        """Reconcilia a tabela com os defaults: insere (INSERT OR IGNORE) TODAS
        as combinações canal × evento do DEFAULT_ROUTING que ainda não têm linha.
        Linhas existentes (config do usuário) não são sobrescritas; rodar 2x é
        idempotente (PK channel+event_type). Diferente de seed_default_routing
        (que só age com tabela vazia), cobre DBs seedados com um
        DEFAULT_ROUTING antigo/parcial — sem isso, evento novo sem linha era
        tratado como "envia sempre" (bug: notificação chegando desabilitada)."""
        with self.lock:
            cursor = self.connection.cursor()
            for channel, events in defaults.items():
                for event_type, enabled in events.items():
                    cursor.execute(
                        "INSERT OR IGNORE INTO notification_routing (channel, event_type, enabled) "
                        "VALUES (?, ?, ?)",
                        (channel, event_type, int(enabled)),
                    )
            self.connection.commit()

    def get_setting(self, key: str, default=None):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self.connection.commit()

    # ════════════════════════════════════════════════════════════════════
    # Auth: users
    # ════════════════════════════════════════════════════════════════════

    def add_user(self, username: str, password_hash: str, role: str, created_by=None) -> int:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash, role, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, role, created_by, timestamp),
            )
            self.connection.commit()
            return cursor.lastrowid

    def get_user_by_username(self, username: str):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user(self, user_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_users(self, created_by=None):
        with self.lock:
            cursor = self.connection.cursor()
            if created_by is not None:
                cursor.execute(
                    "SELECT id, username, role, created_by, created_at, last_login, active "
                    "FROM users WHERE created_by = ? ORDER BY id ASC",
                    (created_by,),
                )
            else:
                cursor.execute(
                    "SELECT id, username, role, created_by, created_at, last_login, active "
                    "FROM users ORDER BY id ASC"
                )
            return [dict(row) for row in cursor.fetchall()]

    def update_user(self, user_id: int, **kwargs):
        allowed = {"username", "password_hash", "role", "active", "last_login"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return False
        sets = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [user_id]
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(f"UPDATE users SET {sets} WHERE id = ?", params)
            self.connection.commit()
            return cursor.rowcount > 0

    def remove_user(self, user_id: int) -> bool:
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self.connection.commit()
            return cursor.rowcount > 0

    def count_active_admins(self) -> int:
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND active = 1")
            return cursor.fetchone()["c"]

    def has_users(self) -> bool:
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM users")
            return cursor.fetchone()["c"] > 0

    # ════════════════════════════════════════════════════════════════════
    # Auth: sessions
    # ════════════════════════════════════════════════════════════════════

    def create_session(self, session_id: str, user_id: int, expires_at: str, ip_address=None):
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO user_sessions (id, user_id, created_at, expires_at, ip_address) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, user_id, timestamp, expires_at, ip_address),
            )
            self.connection.commit()

    def get_session(self, session_id: str):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM user_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_session(self, session_id: str):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE id = ?", (session_id,))
            self.connection.commit()

    def delete_user_sessions(self, user_id: int):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
            self.connection.commit()

    def purge_expired_sessions(self):
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE expires_at < ?", (now,))
            self.connection.commit()

    # ════════════════════════════════════════════════════════════════════
    # Auth: role permissions
    # ════════════════════════════════════════════════════════════════════

    def get_role_permissions(self, role: str) -> dict:
        """Returns {permission: bool} for a role."""
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT permission, enabled FROM role_permissions WHERE role = ?",
                (role,),
            )
            return {row["permission"]: bool(row["enabled"]) for row in cursor.fetchall()}

    def set_role_permission(self, role: str, permission: str, enabled: bool):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO role_permissions (role, permission, enabled) VALUES (?, ?, ?) "
                "ON CONFLICT(role, permission) DO UPDATE SET enabled = excluded.enabled",
                (role, permission, 1 if enabled else 0),
            )
            self.connection.commit()

    def get_all_role_permissions(self) -> dict:
        """Returns {role: {permission: bool}}."""
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT role, permission, enabled FROM role_permissions")
            result = {}
            for row in cursor.fetchall():
                result.setdefault(row["role"], {})[row["permission"]] = bool(row["enabled"])
            return result

    def seed_default_permissions(self, defaults: dict):
        """Seed permissions only if table is empty."""
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM role_permissions")
            if cursor.fetchone()["c"] > 0:
                return
            for role, perms in defaults.items():
                for perm, enabled in perms.items():
                    cursor.execute(
                        "INSERT INTO role_permissions (role, permission, enabled) VALUES (?, ?, ?)",
                        (role, perm, 1 if enabled else 0),
                    )
            self.connection.commit()

    # ════════════════════════════════════════════════════════════════════
    # Auth: user-camera access control
    # ════════════════════════════════════════════════════════════════════

    def set_user_cameras(self, user_id: int, camera_ids: list):
        """Replace all camera associations for a user. Empty list = no restriction."""
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM user_cameras WHERE user_id = ?", (user_id,))
            for cam_id in camera_ids:
                cursor.execute(
                    "INSERT OR IGNORE INTO user_cameras (user_id, camera_id) VALUES (?, ?)",
                    (user_id, cam_id),
                )
            self.connection.commit()

    def get_user_cameras(self, user_id: int) -> list:
        """Return list of camera_ids assigned to user. Empty = unrestricted."""
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT camera_id FROM user_cameras WHERE user_id = ?", (user_id,))
            return [row["camera_id"] for row in cursor.fetchall()]

    def user_camera_ids(self, user) -> list | None:
        """If user is a viewer with camera restrictions, return the list of allowed camera_ids.
        Otherwise return None (unrestricted)."""
        if not user or user.get("role") != "viewer":
            return None
        ids = self.get_user_cameras(user["id"])
        return ids if ids else None  # empty = unrestricted

    # ════════════════════════════════════════════════════════════════════
    # Auth: API keys
    # ════════════════════════════════════════════════════════════════════

    def add_api_key(self, key_hash: str, name: str, permissions=None, created_by=None) -> int:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO api_keys (key_hash, name, permissions, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (key_hash, name, json.dumps(permissions) if permissions else None, created_by, timestamp),
            )
            self.connection.commit()
            return cursor.lastrowid

    def get_api_key_by_hash(self, key_hash: str):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM api_keys WHERE key_hash = ? AND active = 1", (key_hash,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                result["permissions"] = json.loads(result["permissions"]) if result.get("permissions") else None
                return result
            return None

    def list_api_keys(self):
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT id, name, created_by, created_at, last_used, active FROM api_keys ORDER BY id ASC"
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_api_key_last_used(self, key_id: int):
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("UPDATE api_keys SET last_used = ? WHERE id = ?", (now, key_id))
            self.connection.commit()

    def remove_api_key(self, key_id: int) -> bool:
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
            self.connection.commit()
            return cursor.rowcount > 0

    # ════════════════════════════════════════════════════════════════════
    # Auth: audit log
    # ════════════════════════════════════════════════════════════════════

    def add_audit_entry(self, action: str, user_id=None, api_key_id=None,
                        target_type=None, target_id=None, details=None, ip_address=None):
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO audit_log (user_id, api_key_id, action, target_type, target_id, details, ip_address, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, api_key_id, action, target_type, target_id,
                 json.dumps(details) if details else None, ip_address, timestamp),
            )
            self.connection.commit()

    def list_audit_log(self, limit=100, user_id=None, action=None, offset=0):
        with self.lock:
            cursor = self.connection.cursor()
            sql = ("SELECT id, user_id, api_key_id, action, target_type, target_id, details, ip_address, created_at "
                   "FROM audit_log WHERE 1=1")
            params = []
            if user_id is not None:
                sql += " AND user_id = ?"; params.append(user_id)
            if action is not None:
                sql += " AND action = ?"; params.append(action)
            sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            cursor.execute(sql, params)
            rows = [dict(row) for row in cursor.fetchall()]
            for row in rows:
                if row.get("details"):
                    try:
                        row["details"] = json.loads(row["details"])
                    except (ValueError, TypeError):
                        pass
            return rows

    def close(self):
        with self.lock:
            self.connection.close()
