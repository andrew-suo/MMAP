"""Round artifact management for optimizer orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .llm_records import LLMStepRecord, append_llm_record


@dataclass(slots=True)
class RoundRunner:
    """Small utility that owns per-round artifact paths."""

    artifact_root: str | Path
    round_id: int | str

    @property
    def round_dir(self) -> Path:
        return round_artifact_dir(self.artifact_root, self.round_id)

    @property
    def llm_steps_path(self) -> Path:
        return self.round_dir / "llm_steps.jsonl"

    def record_llm_step(self, record: LLMStepRecord | dict[str, Any]) -> Path:
        """Append an LLM step to this round's canonical JSONL artifact."""

        if isinstance(record, dict):
            record = LLMStepRecord.from_dict(record)
        return append_llm_record(self.llm_steps_path, record)


def format_round_id(round_id: int | str) -> str:
    """Format a round identifier as ``round_xxxxxx``."""

    if isinstance(round_id, int) or (isinstance(round_id, str) and round_id.isdigit()):
        return f"round_{int(round_id):06d}"
    text = str(round_id)
    return text if text.startswith("round_") else f"round_{text}"


def round_artifact_dir(artifact_root: str | Path, round_id: int | str) -> Path:
    return Path(artifact_root) / format_round_id(round_id)


def llm_steps_path(artifact_root: str | Path, round_id: int | str) -> Path:
    return round_artifact_dir(artifact_root, round_id) / "llm_steps.jsonl"


def write_llm_step(artifact_root: str | Path, round_id: int | str, record: LLMStepRecord | dict[str, Any]) -> Path:
    """Unified entry point for writing ``round_xxxxxx/llm_steps.jsonl``."""

    return RoundRunner(artifact_root=artifact_root, round_id=round_id).record_llm_step(record)
