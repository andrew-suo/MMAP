"""Checkpoint schema and persistence helpers for optimizer runs.

The checkpoint file captures the optimizer state needed to resume a run without
reusing round identifiers or resetting prompt versions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import json

CHECKPOINT_FILENAME = "checkpoint.json"


@dataclass(frozen=True)
class PromptSnapshot:
    """Serializable identity for the active rendered prompt."""

    prompt_id: str
    version: int
    rendered_hash: str

    @classmethod
    def from_rendered(cls, prompt_id: str, version: int, rendered: str) -> "PromptSnapshot":
        """Build a prompt snapshot by hashing the rendered prompt text."""

        return cls(
            prompt_id=prompt_id,
            version=version,
            rendered_hash=hash_rendered_prompt(rendered),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PromptSnapshot":
        return cls(
            prompt_id=str(value["prompt_id"]),
            version=int(value["version"]),
            rendered_hash=str(value["rendered_hash"]),
        )


@dataclass(frozen=True)
class Checkpoint:
    """State persisted after every optimizer round."""

    active_extraction_prompt: PromptSnapshot
    active_analysis_prompt: PromptSnapshot
    completed_round_ids: list[str] = field(default_factory=list)
    sample_states: dict[str, Any] = field(default_factory=dict)
    fewshot_pool_path: str = ""
    latest_metrics_summary: dict[str, Any] = field(default_factory=dict)
    next_round_index: int = 1

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Checkpoint":
        return cls(
            active_extraction_prompt=PromptSnapshot.from_mapping(
                value["active_extraction_prompt"]
            ),
            active_analysis_prompt=PromptSnapshot.from_mapping(
                value["active_analysis_prompt"]
            ),
            completed_round_ids=[str(round_id) for round_id in value.get("completed_round_ids", [])],
            sample_states=dict(value.get("sample_states", {})),
            fewshot_pool_path=str(value.get("fewshot_pool_path", "")),
            latest_metrics_summary=dict(value.get("latest_metrics_summary", {})),
            next_round_index=int(value.get("next_round_index", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def hash_rendered_prompt(rendered: str) -> str:
    """Return a stable SHA-256 hash for rendered prompt content."""

    return sha256(rendered.encode("utf-8")).hexdigest()


def checkpoint_path(run_dir: str | Path) -> Path:
    """Return the checkpoint path for an optimizer run directory."""

    return Path(run_dir) / CHECKPOINT_FILENAME


def load_checkpoint(run_dir: str | Path) -> Checkpoint:
    """Load a checkpoint from ``run_dir``."""

    path = checkpoint_path(run_dir)
    with path.open("r", encoding="utf-8") as checkpoint_file:
        return Checkpoint.from_mapping(json.load(checkpoint_file))


def write_checkpoint(run_dir: str | Path, checkpoint: Checkpoint) -> Path:
    """Atomically write ``checkpoint.json`` for ``run_dir``."""

    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    path = checkpoint_path(run_path)
    temp_path = path.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as checkpoint_file:
        json.dump(checkpoint.to_dict(), checkpoint_file, indent=2, sort_keys=True)
        checkpoint_file.write("\n")
    temp_path.replace(path)
    return path
