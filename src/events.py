import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class CameraEvent:
    camera_id: str
    device_type: str = "camera"   # 'camera' | 'sensor' | 'device' (origem heterogênea)
    zone: str = None
    zone_classification: str = None
    timestamp: float = field(default_factory=time.time)
    level: int = 0
    source: str = "local"          # 'local' | 'edge'
    event_type: str = None
    details: str = None
    identity_name: str = None
    known: bool = None
    category: str = None
    recognition_method: str = None
    thumbnail_path: str = None
    no_motion: bool = False
    dropped: bool = False
    # Entradas para decide_worker_event (N2-N3), preenchidas na borda:
    detections: list = field(default_factory=list)
    identity_info: dict = None
    identity_label: str = None
    in_schedule: bool = True
    fall: bool = False
    loitering: dict = None
    direction: str = None
    camera_name: str = None
    alert_classes: list = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    db_event_id: int = None  # ID integer no banco (preenchido pelo AlertRuleEngine)


class EventQueue(Protocol):
    def enqueue(self, event: "CameraEvent"): ...
    def subscribe(self, handler): ...
    def start(self): ...


class LocalEventQueue:
    def __init__(self):
        self._q = queue.Queue()
        self._handlers = []
        self._thread = None

    def enqueue(self, event):
        self._q.put(event)

    def subscribe(self, handler):
        self._handlers.append(handler)

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            event = self._q.get()
            if event is None:
                self._q.task_done()
                break
            for h in self._handlers:
                try:
                    h(event)
                except Exception:
                    logging.getLogger("events").exception("Handler falhou ao processar evento")
            self._q.task_done()
