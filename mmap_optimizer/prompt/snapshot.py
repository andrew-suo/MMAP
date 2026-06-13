"""Prompt snapshot persistence helpers.

Snapshots are stored under a run directory using the following layout::

    <run-dir>/prompt_snapshots/<prompt-type>/<snapshot-id>.json

Each snapshot file serializes a :class:`PromptVersion` so that prompt content can
be restored exactly during rollback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping

VALID_PROMPT_TYPES = {"extraction", "analysis"}


@dataclass(frozen=True)
class PromptVersion:
    """Versioned prompt payload captured in a snapshot."""

    id: str
    version: int
    content: str
    prompt_type: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PromptVersion":
        """Build a prompt version from JSON data with basic validation."""

        missing = {"id", "version", "content"} - set(payload)
        if missing:
            missing_fields = ", ".join(sorted(missing))
            raise ValueError(f"Prompt snapshot is missing required fields: {missing_fields}")

        return cls(
            id=str(payload["id"]),
            version=int(payload["version"]),
            content=str(payload["content"]),
            prompt_type=(
                str(payload["prompt_type"])
                if payload.get("prompt_type") is not None
                else None
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Serialize this prompt version to a JSON-compatible mapping."""

        payload = asdict(self)
        if payload["prompt_type"] is None:
            del payload["prompt_type"]
        return payload


def _validate_prompt_type(prompt_type: str) -> None:
    if prompt_type not in VALID_PROMPT_TYPES:
        valid_values = ", ".join(sorted(VALID_PROMPT_TYPES))
        raise ValueError(f"prompt_type must be one of: {valid_values}")


def snapshot_path(run_dir: str | Path, snapshot_id: str, prompt_type: str) -> Path:
    """Return the canonical path for a prompt snapshot."""

    _validate_prompt_type(prompt_type)
    return Path(run_dir) / "prompt_snapshots" / prompt_type / f"{snapshot_id}.json"


def load_prompt_snapshot(
    run_dir: str | Path, snapshot_id: str, prompt_type: str
) -> PromptVersion:
    """Load a prompt snapshot from ``run_dir``.

    Args:
        run_dir: Run directory containing prompt snapshots.
        snapshot_id: Snapshot identifier to restore.
        prompt_type: Prompt family, either ``extraction`` or ``analysis``.

    Returns:
        The versioned prompt captured by the snapshot.
    """

    path = snapshot_path(run_dir, snapshot_id, prompt_type)
    with path.open("r", encoding="utf-8") as snapshot_file:
        payload = json.load(snapshot_file)

    prompt_version = PromptVersion.from_mapping(payload)
    if prompt_version.prompt_type not in (None, prompt_type):
        raise ValueError(
            "Prompt snapshot type does not match requested prompt_type: "
            f"{prompt_version.prompt_type!r} != {prompt_type!r}"
        )
    return prompt_version


def save_prompt_snapshot(
    run_dir: str | Path,
    snapshot_id: str,
    prompt_type: str,
    prompt_version: PromptVersion,
) -> Path:
    """Save a prompt snapshot and return its path.

    This helper is intentionally small and is used by tests and callers that need
    to create rollback points.
    """

    path = snapshot_path(run_dir, snapshot_id, prompt_type)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = prompt_version.to_mapping()
    payload.setdefault("prompt_type", prompt_type)
    with path.open("w", encoding="utf-8") as snapshot_file:
        json.dump(payload, snapshot_file, ensure_ascii=False, indent=2)
        snapshot_file.write("\n")
    return path
