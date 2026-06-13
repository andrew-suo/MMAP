"""Structured records for LLM-backed orchestration steps.

The optimizer has several places where an LLM may produce output that needs to be
parsed or validated.  This module provides a small, dependency-free record type
and a context-local recorder so those low-level modules can emit audit records
without needing to know where the current round stores artifacts.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, MutableSequence, Sequence


@dataclass(slots=True)
class LLMStepRecord:
    """One auditable LLM step emitted during a round."""

    round_id: str | None
    step_type: str
    template_id: str | None
    prompt_hash: str | None
    input_refs: list[str] = field(default_factory=list)
    raw_output: str | None = None
    parse_success: bool = False
    fallback_used: bool = False
    error_type: str | None = None
    accepted_output_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""

        return asdict(self)

    def to_json(self) -> str:
        """Serialize the record as one JSONL-safe line."""

        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


_current_records: ContextVar[MutableSequence[LLMStepRecord] | None] = ContextVar(
    "mmap_llm_step_records", default=None
)
_current_round_id: ContextVar[str | None] = ContextVar("mmap_round_id", default=None)


def prompt_hash(prompt: str | bytes | None) -> str | None:
    """Compute a stable hash for prompt/input text."""

    if prompt is None:
        return None
    if isinstance(prompt, str):
        prompt = prompt.encode("utf-8")
    return hashlib.sha256(prompt).hexdigest()


def record_llm_step(record: LLMStepRecord) -> LLMStepRecord:
    """Append a record to the active round recorder, if one is installed."""

    if record.round_id is None:
        record.round_id = _current_round_id.get()
    records = _current_records.get()
    if records is not None:
        records.append(record)
    return record


@contextmanager
def capture_llm_steps(
    round_id: str | None = None,
    records: MutableSequence[LLMStepRecord] | None = None,
) -> Iterator[MutableSequence[LLMStepRecord]]:
    """Capture records emitted by nested optimizer calls."""

    bucket: MutableSequence[LLMStepRecord] = [] if records is None else records
    records_token = _current_records.set(bucket)
    round_token = _current_round_id.set(round_id)
    try:
        yield bucket
    finally:
        _current_round_id.reset(round_token)
        _current_records.reset(records_token)


def write_llm_steps_jsonl(path: str | Path, records: Sequence[LLMStepRecord]) -> None:
    """Write LLM step records to a JSONL artifact."""

    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.to_json())
            handle.write("\n")
