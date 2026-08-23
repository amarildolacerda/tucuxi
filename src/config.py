import os
from pathlib import Path

# Carrega .env ANTES de qualquer leitura de os.getenv(), para que tanto o
# módulo main quanto o app (create_app) e o status vejam as mesmas variáveis.
# Antes, só main.py chamava load_dotenv() — chamar /api/system-status via
# flask run ou testes mostrava Telegram como "nao configurado" mesmo com
# TELEGRAM_BOT_TOKEN no .env.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "events.db"

# Versão da release. Bump a cada release (formato vX.Y.Z, ver AGENTS.md).
# Fonte única: exibida no footer do dashboard e usada como sw_version no HA
# (antes era hardcoded "0.2.0" e ficava defasada em relação às tags).
APP_VERSION = "0.6.0"

DEFAULT_CAMERAS = [
    {
        "name": "Camera 1",
        "source": "rtsp://admin:123456@192.168.1.104:554/stream",
        "zone": "entrada",
    }
]

MOTION_MIN_AREA = int(os.getenv("MOTION_MIN_AREA", "5000"))
FRAME_WAIT_SECONDS = float(os.getenv("FRAME_WAIT_SECONDS", "0.1"))
# Tempo sem frame válido para considerar a câmera não-saudável (FRAME_WAIT_SECONDS=0.1
# -> 15s = ~150 frames perdidos, generoso para câmeras lentas).
WORKER_HEALTHY_TIMEOUT_SECONDS = float(os.getenv("WORKER_HEALTHY_TIMEOUT", "15"))
# Send a "sem movimento" alert after this many seconds without any occurrence (per camera)
NO_MOTION_ALERT_SECONDS = float(os.getenv("NO_MOTION_ALERT_SECONDS", "60"))
# Suppress repeated events of the same type within this window (per camera)
ALERT_COOLDOWN_SECONDS = float(os.getenv("ALERT_COOLDOWN_SECONDS", "60"))
# Cooldown específico por tipo de evento (fallback: ALERT_COOLDOWN_SECONDS)
ALERT_COOLDOWN_BY_EVENT = {
    "intruder_detected": float(os.getenv("ALERT_COOLDOWN_INTRUDER", "30")),
    "unknown_detected": float(os.getenv("ALERT_COOLDOWN_UNKNOWN", "30")),
    "loitering": float(os.getenv("ALERT_COOLDOWN_LOITERING", "300")),
    "direction_change": float(os.getenv("ALERT_COOLDOWN_DIRECTION", "60")),
    "fall_detected": float(os.getenv("ALERT_COOLDOWN_FALL", "30")),
}
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
DETECTOR_MODEL_PATH = os.getenv("DETECTOR_MODEL_PATH", "")
DETECTOR_CONFIDENCE = float(os.getenv("DETECTOR_CONFIDENCE", "0.25"))
DETECTOR_IOU = float(os.getenv("DETECTOR_IOU", "0.45"))
DETECTOR_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
]
IDENTITY_ENABLED = os.getenv("IDENTITY_ENABLED", "false").lower() in ("1", "true", "yes", "on")
IDENTITY_FACE_MODEL_PATH = os.getenv("IDENTITY_FACE_MODEL_PATH", "")
IDENTITY_REID_MODEL_PATH = os.getenv("IDENTITY_REID_MODEL_PATH", "")
IDENTITY_MATCH_THRESHOLD = float(os.getenv("IDENTITY_MATCH_THRESHOLD", "0.6"))

PRIVACY_MODE = os.getenv("PRIVACY_MODE", "false").lower() in ("1", "true", "yes", "on")


def is_privacy_mode_on(value):
    """True se o valor da settings/environment representa modo privacidade ativo."""
    return str(value).lower() == "true"
IDENTITY_EMBEDDINGS_DIR = DATA_DIR / "identities"
IDENTITY_EMBEDDINGS_DIR.mkdir(exist_ok=True)
HOME_ASSISTANT_URL = os.getenv("HOME_ASSISTANT_URL", "http://192.168.1.12:8123")
HOME_ASSISTANT_TOKEN = os.getenv("HOME_ASSISTANT_TOKEN", "")
HOME_ASSISTANT_EVENT_TYPE = os.getenv("HOME_ASSISTANT_EVENT_TYPE", "secur_alert")
MQTT_BROKER_URL = os.getenv("MQTT_BROKER_URL", "192.168.1.12")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "kzuca")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "123")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "homeassistant/secur/alert")

THUMBNAILS_DIR = DATA_DIR / "thumbnails"
THUMBNAILS_DIR.mkdir(exist_ok=True)
THUMBNAIL_INTERVAL_SECONDS = float(os.getenv("THUMBNAIL_INTERVAL_SECONDS", "20"))
# Dedup de thumbnails: diferença média por pixel (grayscale 64x64) acima deste
# limiar = frame diferente do último salvo -> gravar. Calibrado (480x640):
# idêntico/jpeg roundtrip = 0.0, ruído de sensor sigma3 = ~0.97, objeto forte
# 2.5% do frame = ~9.1. 3.0 cobre ruído leve e separa mudança real de cena.
THUMBNAIL_DIFF_THRESHOLD = float(os.getenv("THUMBNAIL_DIFF_THRESHOLD", "3.0"))
THUMBNAIL_HISTORY_SIZE = int(os.getenv("THUMBNAIL_HISTORY_SIZE", "30"))
# Janela de deduplicação por cena estável: uma cena estável é representada
# por no máximo 1 thumbnail/evento por este período (5–10 min). Após a janela,
# um refresh é salvo mesmo sem mudança de cena.
EVENT_DEDUP_WINDOW_SECONDS = float(os.getenv("EVENT_DEDUP_WINDOW_SECONDS", "300"))

CLIP_PRE_SECONDS = float(os.getenv("CLIP_PRE_SECONDS", "10"))
CLIP_POST_SECONDS = float(os.getenv("CLIP_POST_SECONDS", "10"))
CLIP_FPS = int(os.getenv("CLIP_FPS", "5"))
CLIPS_DIR = DATA_DIR / "clips"
CLIPS_DIR.mkdir(exist_ok=True)
CLIP_HISTORY_SIZE = int(os.getenv("CLIP_HISTORY_SIZE", "20"))

# Event pruning — por TIPO de evento (ignora level). 0 = remove todos imediatamente;
# aceita fração (ex: 0.5 = 12h). -1 num tipo = nunca podar por tipo (só Idade Máx.).
EVENT_PRUNE_ENABLED = os.getenv("EVENT_PRUNE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
EVENT_PRUNE_TYPE_DAYS = {
    "motion_detected": float(os.getenv("EVENT_PRUNE_MOTION_DETECTED_DAYS", "1")),
    "capture": float(os.getenv("EVENT_PRUNE_CAPTURE_DAYS", "7")),
    "snapshot_info": float(os.getenv("EVENT_PRUNE_SNAPSHOT_INFO_DAYS", "7")),
    "no_motion": float(os.getenv("EVENT_PRUNE_NO_MOTION_DAYS", "0")),
    "loitering": float(os.getenv("EVENT_PRUNE_LOITERING_DAYS", "7")),
    "suppressed": float(os.getenv("EVENT_PRUNE_SUPPRESSED_DAYS", "1")),
    "cooldown": float(os.getenv("EVENT_PRUNE_COOLDOWN_DAYS", "1")),
}
# Retenção padrão (dias) para tipos não previstos acima. -1 = nunca podar por tipo.
EVENT_PRUNE_DEFAULT_DAYS = float(os.getenv("EVENT_PRUNE_DEFAULT_DAYS", "7"))
# Idade máxima (dias) de qualquer evento NÃO retido — rede de segurança final.
# 0 = remove todos os não retidos; -1 (no param) usa este valor.
EVENT_PRUNE_MAX_AGE_DAYS = float(os.getenv("EVENT_PRUNE_MAX_AGE_DAYS", "30"))
# Intervalo de execução do prune (segundos)
EVENT_PRUNE_INTERVAL_SECONDS = int(os.getenv("EVENT_PRUNE_INTERVAL_SECONDS", "3600"))

# Fase 3 — comportamento/anomalia (tracking)
TRACK_IOU_THRESHOLD = float(os.getenv("TRACK_IOU_THRESHOLD", "0.3"))
TRACK_MAX_AGE_SECONDS = float(os.getenv("TRACK_MAX_AGE_SECONDS", "2.0"))

LOITERING_SECONDS = float(os.getenv("LOITERING_SECONDS", "30"))
LOITERING_MAX_DISTANCE = float(os.getenv("LOITERING_MAX_DISTANCE", "80"))
LOITERING_LABELS = ["person", "car", "truck", "bus", "motorcycle", "bicycle"]

FALL_ASPECT_RATIO = float(os.getenv("FALL_ASPECT_RATIO", "1.2"))

# Auth settings
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", "5"))
