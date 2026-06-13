"""Structured records for LLM-backed orchestration steps.

Two layers are provided:

* :class:`LLMStepRecord` captures a single LLM interaction with enough
  metadata to reproduce or audit the call.  It is written as one JSON line
  to a ``round_xxxxxx/llm_steps.jsonl`` artifact inside the run directory.
* :class:`LLMStepResult` is a lightweight, algorithm-agnostic container used
  by repair / semantic merge / compression helpers to return both a parsed
  output and recording metadata.
* :class:`LLMStepRecorder` is a thin helper that records to
  ``{round_dir}/llm_steps.jsonl`` using the existing storage path conventions
  so callers don't need a parallel storage system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
import hashlib
import json


JSONValue = str | int | float | bool | None | dict[str, Any] | list[Any]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class LLMStepRecord:
    """A single auditable LLM step emitted during a round.

    The schema is additive: ``metadata`` and ``created_at`` are new fields
    but all prior fields are kept unchanged so existing JSONL artifacts can
    still be read.
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
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "step_type": self.step_type,
            "template_id": self.template_id,
            "prompt_hash": self.prompt_hash,
            "input_refs": list(self.input_refs),
            "raw_output": self.raw_output,
            "parse_success": self.parse_success,
            "fallback_used": self.fallback_used,
            "error_type": self.error_type,
            "accepted_output_summary": self.accepted_output_summary,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LLMStepRecord":
        data: dict[str, Any] = dict(payload)
        refs = data.get("input_refs") or []
        if isinstance(refs, str):
            refs = [refs]
        data["input_refs"] = [str(ref) for ref in refs]
        if "metadata" not in data or data["metadata"] is None:
            data["metadata"] = {}
        else:
            data["metadata"] = dict(data["metadata"])
        if "created_at" not in data or not data["created_at"]:
            data["created_at"] = _utc_now_iso()
        return cls(**data)


@dataclass(slots=True)
class LLMStepResult:
    """Lightweight algorithm-agnostic wrapper for LLM-backed step outputs.

    Callers use this to surface both the parsed/cooked value that drives
    downstream logic and the recording metadata (parse success, fallback
    usage, error type).  The class intentionally does not make decisions for
    the caller; it only packages information so it can be traced.
    """

    output: Any = None
    parse_success: bool = False
    fallback_used: bool = False
    error_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, dict):
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "parse_success": self.parse_success,
            "fallback_used": self.fallback_used,
            "error_type": self.error_type,
            "metadata": dict(self.metadata),
        }


def hash_prompt(prompt: str | bytes | None) -> str:
    if prompt is None:
        prompt = ""
    if isinstance(prompt, str):
        prompt = prompt.encode("utf-8")
    return hashlib.sha256(prompt).hexdigest()


def append_llm_record(path: str | Path, record: LLMStepRecord) -> Path:
    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("a", encoding="utf-8") as handle:
        handle.write(record.to_json())
        handle.write("\n")
    return artifact_path


def read_llm_records(path: str | Path) -> list[LLMStepRecord]:
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
    if input_refs is None:
        return []
    if isinstance(input_refs, (str, bytes)):
        return [input_refs.decode("utf-8") if isinstance(input_refs, bytes) else input_refs]
    try:
        return [str(ref) for ref in input_refs]
    except TypeError:
        return [str(input_refs)]


class LLMStepRecorder:
    """Append-only JSONL writer for round-scoped LLM step records.

    Uses the existing :func:`append_llm_record` / :func:`read_llm_records`
    path so artifact files are interchangeable regardless of which helper
    produced them.  No feature flags, no thread-local state.
    """

    def __init__(self, round_dir: str | Path, round_id: str | int) -> None:
        self.round_dir = Path(round_dir)
        self.round_id = round_id
        self.path = self.round_dir / "llm_steps.jsonl"

    def make_record(
        self,
        *,
        step_type: str,
        template_id: str,
        prompt: str | bytes | None = None,
        prompt_hash: str | None = None,
        input_refs: Iterable[Any] | Any | None = None,
        raw_output: str = "",
        parse_success: bool = False,
        fallback_used: bool = False,
        error_type: str | None = None,
        accepted_output_summary: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMStepRecord:
        return LLMStepRecord(
            round_id=self.round_id,
            step_type=step_type,
            template_id=template_id,
            prompt_hash=prompt_hash or hash_prompt(prompt),
            input_refs=coerce_input_refs(input_refs),
            raw_output=raw_output,
            parse_success=parse_success,
            fallback_used=fallback_used,
            error_type=error_type,
            accepted_output_summary=accepted_output_summary,
            metadata=dict(metadata or {}),
        )

    def record(self, record: LLMStepRecord) -> Path:
        return append_llm_record(self.path, record)

    def record_step(self, **kwargs: Any) -> LLMStepRecord:
        record = self.make_record(**kwargs)
        self.record(record)
        return record

    def __repr__(self) -> str:
        return f"LLMStepRecorder(round_dir={self.round_dir!r}, round_id={self.round_id!r})"
