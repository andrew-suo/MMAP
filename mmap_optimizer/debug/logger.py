from __future__ import annotations

from collections import Counter
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
        self._counter: Counter[str] = Counter()
        self._total: int = 0

    @property
    def total(self) -> int:
        return self._total

    @property
    def event_counts(self) -> dict[str, int]:
        return dict(self._counter)

    def log(self, event_type: str, message: str, *, stage: str | None = None, round_id: str | None = None, payload: dict[str, Any] | None = None) -> DebugEvent:
        event = DebugEvent(event_type=event_type, message=message, stage=stage, round_id=round_id, payload=payload or {})
        self.store.append_jsonl(self.path, [event])
        self._counter[event_type] += 1
        self._total += 1
        return event

    def counts_by_stage(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        records = self._load_records()
        for record in records:
            stage = record.get("stage") if isinstance(record, dict) else getattr(record, "stage", None)
            counts[str(stage or "unknown")] += 1
        return dict(counts)

    def counts_by_round(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for record in self._load_records():
            round_id = record.get("round_id") if isinstance(record, dict) else getattr(record, "round_id", None)
            counts[str(round_id or "unknown")] += 1
        return dict(counts)

    def summary(self) -> dict[str, Any]:
        return {
            "total_in_memory": self._total,
            "counts_in_memory": dict(self._counter),
            "path": self.path,
        }

    def clear(self) -> None:
        self._counter.clear()
        self._total = 0
        target = self.store.root / self.path
        if target.exists():
            target.unlink()

    def reset_counters(self) -> None:
        self._counter.clear()
        self._total = 0

    def _load_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        try:
            raw = self.store.read_json(self.path)
        except (FileNotFoundError, OSError):
            return records
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    records.append(item)
        return records
