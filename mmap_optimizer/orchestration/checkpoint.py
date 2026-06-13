"""Checkpoint and prompt snapshot persistence for optimizer runs.

The optimizer writes two kinds of durable state:

* :class:`PromptSnapshot` captures the exact rendered prompt that was active
  immediately before or immediately after a promotion event.
* :class:`OptimizerCheckpoint` captures the resumable end-of-round state in the
  run root's ``checkpoint.json``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp suitable for checkpoint metadata."""

    return datetime.now(timezone.utc).isoformat()


def rendered_hash(rendered: str) -> str:
    """Return the stable SHA-256 hash used to identify rendered prompt content."""

    return sha256(rendered.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically by replacing the destination from a temp file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temp_path.replace(path)


@dataclass(slots=True)
class PromptSnapshot:
    """A point-in-time copy of an optimizer prompt.

    ``snapshot_id`` is intentionally caller-provided so callers can make it
    human-readable and easy to pass back to ``--rollback-to``.
    """

    snapshot_id: str
    prompt_name: str
    version: int
    rendered: str
    rendered_hash: str
    round_index: int
    stage: str
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        snapshot_id: str,
        prompt_name: str,
        version: int,
        rendered: str,
        round_index: int,
        stage: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "PromptSnapshot":
        """Build a snapshot and compute the rendered prompt hash."""

        return cls(
            snapshot_id=snapshot_id,
            prompt_name=prompt_name,
            version=version,
            rendered=rendered,
            rendered_hash=rendered_hash(rendered),
            round_index=round_index,
            stage=stage,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the snapshot to a JSON-compatible dictionary."""

        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PromptSnapshot":
        """Deserialize a snapshot from JSON-compatible data."""

        return cls(
            snapshot_id=str(payload["snapshot_id"]),
            prompt_name=str(payload["prompt_name"]),
            version=int(payload["version"]),
            rendered=str(payload["rendered"]),
            rendered_hash=str(payload["rendered_hash"]),
            round_index=int(payload["round_index"]),
            stage=str(payload["stage"]),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            metadata=dict(payload.get("metadata") or {}),
        )

    def save(self, path: str | Path) -> Path:
        """Persist the snapshot as JSON and return the resolved path."""

        destination = Path(path)
        _write_json_atomic(destination, self.to_dict())
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "PromptSnapshot":
        """Load a prompt snapshot JSON file."""

        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))


@dataclass(slots=True)
class OptimizerCheckpoint:
    """Durable optimizer state written at the end of every round."""

    round_index: int
    active_prompts: dict[str, dict[str, Any]]
    sample_states: list[dict[str, Any]]
    fewshot_pool_path: str | None
    metrics_summary: dict[str, Any]
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the checkpoint to a JSON-compatible dictionary."""

        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OptimizerCheckpoint":
        """Deserialize checkpoint JSON data."""

        return cls(
            round_index=int(payload["round_index"]),
            active_prompts={k: dict(v) for k, v in dict(payload["active_prompts"]).items()},
            sample_states=[dict(item) for item in payload.get("sample_states", [])],
            fewshot_pool_path=(
                None if payload.get("fewshot_pool_path") is None else str(payload.get("fewshot_pool_path"))
            ),
            metrics_summary=dict(payload.get("metrics_summary") or {}),
            created_at=str(payload.get("created_at") or utc_now_iso()),
        )

    def save(self, path: str | Path) -> Path:
        """Persist the checkpoint as JSON and return the destination path."""

        destination = Path(path)
        _write_json_atomic(destination, self.to_dict())
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "OptimizerCheckpoint":
        """Load an optimizer checkpoint JSON file."""

        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))
