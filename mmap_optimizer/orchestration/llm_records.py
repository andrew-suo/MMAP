"""Structured records for LLM calls made during optimization rounds."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping
import hashlib
import json
import os


FEATURE_FLAG_ENV = "MMAP_ENABLE_LLM_STEP_RECORDS"
LEGACY_FEATURE_FLAG_ENV = "MMAP_LLM_STEPS_ENABLED"


@dataclass(slots=True)
class LLMStepRecord:
    """Audit record for one LLM-backed orchestration step."""

    round_id: str
    step_type: str
    template_id: str
    prompt_hash: str
    input_summary: Mapping[str, Any] | str
    raw_output: str
    parse_success: bool
    fallback_used: bool
    error_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def llm_recording_enabled() -> bool:
    """Return whether LLM step artifact recording is enabled."""

    value = os.getenv(FEATURE_FLAG_ENV, os.getenv(LEGACY_FEATURE_FLAG_ENV, ""))
    return value.strip().lower() in {"1", "true", "yes", "on"}


def hash_prompt(prompt: str | bytes | None) -> str:
    """Return a stable SHA-256 hash for a prompt-like value."""

    if prompt is None:
        prompt = ""
    if isinstance(prompt, str):
        prompt = prompt.encode("utf-8")
    return hashlib.sha256(prompt).hexdigest()


class LLMStepRecorder:
    """Append-only JSONL writer for round-scoped LLM step records."""

    def __init__(self, round_dir: str | Path, round_id: str, *, enabled: bool | None = None) -> None:
        self.round_dir = Path(round_dir)
        self.round_id = round_id
        self.enabled = llm_recording_enabled() if enabled is None else enabled
        self.path = self.round_dir / "llm_steps.jsonl"

    def record(self, record: LLMStepRecord) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.to_json())
            handle.write("\n")

    def make_record(
        self,
        *,
        step_type: str,
        template_id: str,
        prompt: str | bytes | None = None,
        prompt_hash: str | None = None,
        input_summary: Mapping[str, Any] | str = "",
        raw_output: str = "",
        parse_success: bool = False,
        fallback_used: bool = False,
        error_type: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> LLMStepRecord:
        return LLMStepRecord(
            round_id=self.round_id,
            step_type=step_type,
            template_id=template_id,
            prompt_hash=prompt_hash or hash_prompt(prompt),
            input_summary=input_summary,
            raw_output=raw_output,
            parse_success=parse_success,
            fallback_used=fallback_used,
            error_type=error_type,
            metadata=metadata or {},
        )

    def record_step(self, **kwargs: Any) -> LLMStepRecord:
        record = self.make_record(**kwargs)
        self.record(record)
        return record


_CURRENT_RECORDER: ContextVar[LLMStepRecorder | None] = ContextVar("mmap_llm_step_recorder", default=None)


def get_current_recorder() -> LLMStepRecorder | None:
    return _CURRENT_RECORDER.get()


@contextmanager
def use_llm_step_recorder(recorder: LLMStepRecorder | None) -> Iterator[LLMStepRecorder | None]:
    token = _CURRENT_RECORDER.set(recorder)
    try:
        yield recorder
    finally:
        _CURRENT_RECORDER.reset(token)
