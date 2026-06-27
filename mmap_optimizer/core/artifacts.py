"""Artifact serialization helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def to_artifact_data(value: Any) -> Any:
    """Convert runtime objects into compact JSON artifact data.

    Artifact files are for inspection and resume/debug workflows. Optional
    values that carry no information are omitted, while falsey metrics such as
    ``0`` and ``False`` are preserved.
    """
    if hasattr(value, "to_dict"):
        value = value.to_dict()

    if isinstance(value, dict):
        data: dict[str, Any] = {}
        for key, item in value.items():
            converted = to_artifact_data(item)
            if converted is None:
                continue
            if isinstance(converted, dict) and not converted:
                continue
            data[str(key)] = converted
        return data

    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            converted = to_artifact_data(item)
            if converted is not None:
                items.append(converted)
        return items

    return value


def write_json_artifact(path: Path, data: Any) -> None:
    """Write a JSON artifact with normalized optional fields."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_artifact_data(data), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_jsonl_artifact(path: Path, items: list[Any]) -> None:
    """Write a JSONL artifact with normalized optional fields per record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(to_artifact_data(item), ensure_ascii=False) + "\n")


__all__ = ["to_artifact_data", "write_json_artifact", "write_jsonl_artifact"]
