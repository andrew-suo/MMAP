"""Checkpoint persistence for resumable runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import to_artifact_data


@dataclass
class RunCheckpoint:
    schema_version: int = 1
    run_status: str = "running"
    current_phase: str | None = None
    current_step_id: str | None = None
    current_iteration: int | None = None
    current_stage: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    structured_extraction_prompt_path: str | None = None
    structured_analysis_prompt_path: str | None = None
    current_extraction_prompt_path: str | None = None
    current_analysis_prompt_path: str | None = None
    sample_states_path: str | None = None
    sample_traces_path: str | None = None
    batch_size_controller_path: str | None = None
    fewshot_examples_path: str | None = None
    updated_at: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_status": self.run_status,
            "current_phase": self.current_phase,
            "current_step_id": self.current_step_id,
            "current_iteration": self.current_iteration,
            "current_stage": self.current_stage,
            "completed_steps": list(self.completed_steps),
            "structured_extraction_prompt_path": self.structured_extraction_prompt_path,
            "structured_analysis_prompt_path": self.structured_analysis_prompt_path,
            "current_extraction_prompt_path": self.current_extraction_prompt_path,
            "current_analysis_prompt_path": self.current_analysis_prompt_path,
            "sample_states_path": self.sample_states_path,
            "sample_traces_path": self.sample_traces_path,
            "batch_size_controller_path": self.batch_size_controller_path,
            "fewshot_examples_path": self.fewshot_examples_path,
            "updated_at": self.updated_at,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunCheckpoint":
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            run_status=data.get("run_status", "running"),
            current_phase=data.get("current_phase"),
            current_step_id=data.get("current_step_id"),
            current_iteration=data.get("current_iteration"),
            current_stage=data.get("current_stage"),
            completed_steps=list(data.get("completed_steps", [])),
            structured_extraction_prompt_path=data.get("structured_extraction_prompt_path"),
            structured_analysis_prompt_path=data.get("structured_analysis_prompt_path"),
            current_extraction_prompt_path=data.get("current_extraction_prompt_path"),
            current_analysis_prompt_path=data.get("current_analysis_prompt_path"),
            sample_states_path=data.get("sample_states_path"),
            sample_traces_path=data.get("sample_traces_path"),
            batch_size_controller_path=data.get("batch_size_controller_path"),
            fewshot_examples_path=data.get("fewshot_examples_path"),
            updated_at=data.get("updated_at"),
            last_error=data.get("last_error"),
        )


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(to_artifact_data(data), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(path)


class CheckpointStore:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.path = self.output_dir / "checkpoint.json"
        self.events_path = self.output_dir / "resume_events.jsonl"

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> RunCheckpoint:
        return RunCheckpoint.from_dict(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, checkpoint: RunCheckpoint, *, event: str | None = None) -> None:
        checkpoint.updated_at = datetime.now(timezone.utc).isoformat()
        atomic_write_json(self.path, checkpoint.to_dict())
        if event:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": checkpoint.updated_at,
                "event": event,
                "checkpoint": checkpoint.to_dict(),
            }
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(to_artifact_data(record), ensure_ascii=False) + "\n")


__all__ = ["CheckpointStore", "RunCheckpoint", "atomic_write_json"]
