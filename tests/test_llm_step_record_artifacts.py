from __future__ import annotations

import json
from pathlib import Path

from mmap_optimizer.orchestration.llm_records import (
    LLMStepRecord,
    LLMStepRecorder,
    LLMStepResult,
    append_llm_record,
    coerce_input_refs,
    hash_prompt,
    read_llm_records,
)


def test_record_serializes_to_json_round_trip():
    record = LLMStepRecord(
        round_id="round_000001",
        step_type="json_repair",
        template_id="prompting.repair.v1",
        prompt_hash=hash_prompt("fix this json"),
        input_refs=["patch-1", "patch-2"],
        raw_output='{"fixed": true}',
        parse_success=True,
        fallback_used=False,
        accepted_output_summary="fixed output",
        metadata={"model": "test-model", "attempts": 2},
    )
    payload = record.to_json()
    parsed = LLMStepRecord.from_dict(json.loads(payload))
    assert parsed.round_id == "round_000001"
    assert parsed.step_type == "json_repair"
    assert parsed.parse_success is True
    assert parsed.fallback_used is False
    assert parsed.metadata == {"model": "test-model", "attempts": 2}
    assert parsed.created_at  # auto-populated


def test_record_from_dict_handles_missing_optional_fields():
    payload = {
        "round_id": "round_000042",
        "step_type": "semantic_merge",
        "template_id": "prompting.merge.v1",
        "prompt_hash": hash_prompt("merge"),
        # input_refs omitted → should default to []
        "raw_output": '{"ok": 1}',
        # parse_success omitted → default False
        # fallback_used omitted → default False
        # accepted_output_summary omitted → default ""
        # metadata omitted → default {}
        # created_at omitted → auto-populated
    }
    record = LLMStepRecord.from_dict(payload)
    assert record.input_refs == []
    assert record.parse_success is False
    assert record.fallback_used is False
    assert record.accepted_output_summary == ""
    assert record.metadata == {}
    assert record.created_at


def test_coerce_input_refs_normalises_list_and_scalars():
    assert coerce_input_refs(None) == []
    assert coerce_input_refs("single-ref") == ["single-ref"]
    assert coerce_input_refs(["a", 1, None]) == ["a", "1", "None"]
    assert coerce_input_refs(b"bytes") == ["bytes"]


def test_jsonl_artifact_appends_multiple_records(tmp_path: Path):
    artifact = tmp_path / "round_000001" / "llm_steps.jsonl"
    first = LLMStepRecord(
        round_id="round_000001",
        step_type="json_repair",
        template_id="prompting.repair.v1",
        prompt_hash=hash_prompt("p1"),
        raw_output='{"ok": true}',
        parse_success=True,
    )
    second = LLMStepRecord(
        round_id="round_000001",
        step_type="semantic_validation",
        template_id="prompting.validate.v1",
        prompt_hash=hash_prompt("p2"),
        raw_output="invalid json",
        parse_success=False,
        fallback_used=True,
        error_type="JSONDecodeError",
    )
    append_llm_record(artifact, first)
    append_llm_record(artifact, second)

    records = read_llm_records(artifact)
    assert len(records) == 2
    assert records[0].step_type == "json_repair"
    assert records[1].step_type == "semantic_validation"
    assert records[1].fallback_used is True
    assert records[1].error_type == "JSONDecodeError"
    # Raw lines are newline terminated.
    text = artifact.read_text(encoding="utf-8").rstrip("\n")
    assert text.count("\n") == 1


def test_read_llm_records_handles_missing_file(tmp_path: Path):
    assert read_llm_records(tmp_path / "does-not-exist" / "llm_steps.jsonl") == []


def test_llm_step_result_wraps_parsed_value_without_modifying_it():
    result = LLMStepResult(
        output={"merged": ["p1", "p2"]},
        parse_success=True,
        fallback_used=False,
        metadata={"attempts": 1},
    )
    assert result.output == {"merged": ["p1", "p2"]}
    assert result.parse_success is True
    payload = result.to_dict()
    assert payload["parse_success"] is True
    assert payload["output"] == {"merged": ["p1", "p2"]}


def test_llm_step_result_handles_empty_metadata_and_no_output():
    result = LLMStepResult(output=None, parse_success=False, fallback_used=True, error_type="JSONDecodeError")
    assert result.parse_success is False
    assert result.fallback_used is True
    assert result.error_type == "JSONDecodeError"
    assert result.metadata == {}


def test_recorder_appends_to_expected_path(tmp_path: Path):
    round_dir = tmp_path / "round_000007"
    recorder = LLMStepRecorder(round_dir, "round_000007")
    recorded = recorder.record_step(
        step_type="json_repair",
        template_id="prompting.repair.v1",
        prompt="fix json",
        input_refs=["p1", "p2"],
        raw_output='{"ok": true}',
        parse_success=True,
        accepted_output_summary="repaired json",
        metadata={"model": "m"},
    )
    assert (round_dir / "llm_steps.jsonl").exists()
    assert recorded.round_id == "round_000007"
    assert recorded.step_type == "json_repair"
    assert recorded.parse_success is True
    assert recorded.input_refs == ["p1", "p2"]

    # Multiple calls append (do not overwrite).
    second = recorder.record_step(
        step_type="semantic_validation",
        template_id="prompting.validate.v1",
        prompt="validate",
        raw_output="not valid json",
        parse_success=False,
        fallback_used=True,
        error_type="JSONDecodeError",
    )
    assert len(read_llm_records(round_dir / "llm_steps.jsonl")) == 2
    assert second.fallback_used is True


def test_recorder_make_record_does_not_write(tmp_path: Path):
    recorder = LLMStepRecorder(tmp_path, "round_000009")
    record = recorder.make_record(
        step_type="semantic_merge",
        template_id="prompting.merge.v1",
        prompt="merge",
        raw_output='{"merged": []}',
        parse_success=True,
    )
    # make_record alone should not touch disk.
    assert not (tmp_path / "llm_steps.jsonl").exists()
    assert record.round_id == "round_000009"


def test_hash_prompt_is_stable_and_deterministic():
    assert hash_prompt("abc") == hash_prompt("abc")
    assert hash_prompt("abc") != hash_prompt("abd")
    assert hash_prompt(b"abc") == hash_prompt("abc")
    assert hash_prompt(None) == hash_prompt("")
    assert len(hash_prompt("x")) == 64  # SHA-256 hex


def test_checkpoint_and_scenario_paths_not_touched_by_recorder(tmp_path: Path):
    """The recorder only writes its configured JSONL path."""
    round_dir = tmp_path / "round_000010"
    recorder = LLMStepRecorder(round_dir, "round_000010")
    recorder.record_step(step_type="json_repair", template_id="t", prompt="x", parse_success=True)
    assert not (tmp_path / "checkpoint.json").exists()
    assert not (tmp_path / "scenario.yaml").exists()


def test_record_has_stable_key_set_after_round_trip(tmp_path: Path):
    """Each JSONL record always has at least these keys: round_id, step_type,
    template_id, prompt_hash, input_refs, raw_output, parse_success,
    fallback_used, error_type, accepted_output_summary, metadata, created_at."""
    record = LLMStepRecord(
        round_id="round_000011", step_type="x", template_id="y", prompt_hash=hash_prompt("z"),
    )
    payload = json.loads(record.to_json())
    required = {
        "round_id", "step_type", "template_id", "prompt_hash", "input_refs",
        "raw_output", "parse_success", "fallback_used", "error_type",
        "accepted_output_summary", "metadata", "created_at",
    }
    assert required.issubset(set(payload.keys()))
