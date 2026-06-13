from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mmap_optimizer.storage.json_store import JsonStore


@dataclass
class RunState:
    run_id: str
    iteration: int = 0
    stage: str = "initialized"
    active_extraction_prompt_id: str | None = None
    active_analysis_prompt_id: str | None = None
    completed_round_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RunStateStore:
    def __init__(self, store: JsonStore, path: str = "run_state.json"):
        self.store = store
        self.path = path

    def save(self, state: RunState) -> None:
        self.store.write_json(self.path, state)

    def load(self) -> RunState | None:
        try:
            data = self.store.read_json(self.path)
        except FileNotFoundError:
            return None
        return RunState(**data)
