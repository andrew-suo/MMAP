from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from mmap_optimizer.storage.json_store import JsonStore


@dataclass
class DebugEvent:
    event_type: str
    message: str
    stage: str | None = None
    round_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DebugEventLogger:
    def __init__(self, store: JsonStore, path: str = "debug_events.jsonl"):
        self.store = store
        self.path = path

    def log(self, event_type: str, message: str, *, stage: str | None = None, round_id: str | None = None, payload: dict[str, Any] | None = None) -> DebugEvent:
        event = DebugEvent(event_type=event_type, message=message, stage=stage, round_id=round_id, payload=payload or {})
        self.store.append_jsonl(self.path, [event])
        return event
