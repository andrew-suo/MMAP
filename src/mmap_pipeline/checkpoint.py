"""Checkpoint persistence for optimizer state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CheckpointState:
    """Serializable optimizer state written after each completed round."""

    active_extraction_prompt_version_id: int
    active_analysis_prompt_version_id: int
    completed_round_ids: list[int] = field(default_factory=list)
    sample_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    fewshot_pool_path: str = "fewshot_pool.json"
    latest_metrics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def initial(
        cls,
        *,
        fewshot_pool_path: str,
        sample_ids: list[str] | None = None,
        initial_prompt_version_id: int = 1,
    ) -> "CheckpointState":
        """Create a fresh checkpoint state for a new optimization run."""

        samples = {
            sample_id: {"status": "pending", "last_completed_round_id": None}
            for sample_id in (sample_ids or [])
        }
        return cls(
            active_extraction_prompt_version_id=initial_prompt_version_id,
            active_analysis_prompt_version_id=initial_prompt_version_id,
            sample_states=samples,
            fewshot_pool_path=fewshot_pool_path,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CheckpointState":
        """Build state from checkpoint JSON, validating required fields."""

        required = {
            "active_extraction_prompt_version_id",
            "active_analysis_prompt_version_id",
            "completed_round_ids",
            "sample_states",
            "fewshot_pool_path",
            "latest_metrics",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ValueError(f"checkpoint is missing required fields: {', '.join(missing)}")

        return cls(
            active_extraction_prompt_version_id=int(payload["active_extraction_prompt_version_id"]),
            active_analysis_prompt_version_id=int(payload["active_analysis_prompt_version_id"]),
            completed_round_ids=[int(round_id) for round_id in payload["completed_round_ids"]],
            sample_states=dict(payload["sample_states"]),
            fewshot_pool_path=str(payload["fewshot_pool_path"]),
            latest_metrics=dict(payload["latest_metrics"]),
        )


class CheckpointStore:
    """Read and atomically write optimizer checkpoints."""

    def __init__(self, path: str | Path = "checkpoint.json") -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        """Return whether the checkpoint file exists."""

        return self.path.exists()

    def load(self) -> CheckpointState:
        """Load checkpoint state from disk."""

        with self.path.open("r", encoding="utf-8") as checkpoint_file:
            payload = json.load(checkpoint_file)
        return CheckpointState.from_dict(payload)

    def save(self, state: CheckpointState) -> None:
        """Atomically persist checkpoint state to disk."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as checkpoint_file:
            json.dump(state.to_dict(), checkpoint_file, indent=2, sort_keys=True)
            checkpoint_file.write("\n")
        temp_path.replace(self.path)
