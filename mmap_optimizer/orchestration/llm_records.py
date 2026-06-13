"""Structured records for LLM-backed orchestration steps.

The records in this module are intentionally small and JSONL-friendly.  They
capture enough information to make model interactions auditable without tying
callers to a specific LLM provider or prompt implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping
import hashlib
import json


JSONValue = str | int | float | bool | None | dict[str, Any] | list[Any]


@dataclass(slots=True)
class LLMStepRecord:
    """A single auditable LLM step emitted during a round.

    Attributes mirror the artifact contract used by the round runner.  The
    object is serializable as a single JSON object and should be appended to
    ``round_xxxxxx/llm_steps.jsonl``.
    """

    round_id: int | str
    step_type: str
    template_id: str
    prompt_hash: str
    input_refs: list[str] = field(default_factory=list)
    raw_output: str = ""
    parse_success: bool = False
    fallback_used: bool = False
    error_type: str | None = None
    accepted_output_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)

    def to_json(self) -> str:
        """Serialize the record as a stable, UTF-8 JSON line payload."""

        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LLMStepRecord":
        """Build a record from a mapping, normalizing ``input_refs``."""

        data = dict(payload)
        refs = data.get("input_refs") or []
        if isinstance(refs, str):
            refs = [refs]
        data["input_refs"] = [str(ref) for ref in refs]
        return cls(**data)


def hash_prompt(prompt: str | bytes | None) -> str:
    """Return a SHA-256 hash for a prompt-like value."""

    if prompt is None:
        prompt = ""
    if isinstance(prompt, str):
        prompt = prompt.encode("utf-8")
    return hashlib.sha256(prompt).hexdigest()


def append_llm_record(path: str | Path, record: LLMStepRecord) -> Path:
    """Append ``record`` to a JSONL artifact and return the artifact path."""

    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("a", encoding="utf-8") as handle:
        handle.write(record.to_json())
        handle.write("\n")
    return artifact_path


def read_llm_records(path: str | Path) -> list[LLMStepRecord]:
    """Read a JSONL artifact produced by :func:`append_llm_record`."""

    artifact_path = Path(path)
    if not artifact_path.exists():
        return []
    records: list[LLMStepRecord] = []
    with artifact_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                records.append(LLMStepRecord.from_dict(json.loads(stripped)))
    return records


def coerce_input_refs(input_refs: Iterable[Any] | Any | None) -> list[str]:
    """Normalize references to stable strings for JSON artifacts."""

    if input_refs is None:
        return []
    if isinstance(input_refs, (str, bytes)):
        return [input_refs.decode("utf-8") if isinstance(input_refs, bytes) else input_refs]
    try:
        return [str(ref) for ref in input_refs]
    except TypeError:
        return [str(input_refs)]
