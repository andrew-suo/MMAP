from __future__ import annotations

import json

from mmap_optimizer.analysis.llm_repair import repair_json_with_model
from mmap_optimizer.compression.semantic import semantic_compress
from mmap_optimizer.orchestration.llm_records import read_llm_records
from mmap_optimizer.patch.semantic import root_audit, semantic_merge


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_json_repair_writes_readable_artifact(tmp_path):
    result = repair_json_with_model(
        "{'bad': true}",
        lambda prompt: '{"bad": true}',
        round_id=3,
        artifact_root=tmp_path,
        input_refs=["candidate.json"],
    )

    assert result.parse_success is True
    artifact = tmp_path / "round_000003" / "llm_steps.jsonl"
    payloads = _lines(artifact)
    assert payloads[0]["step_type"] == "json_repair"
    assert payloads[0]["input_refs"] == ["candidate.json"]
    assert payloads[0]["raw_output"] == '{"bad": true}'
    assert read_llm_records(artifact)[0].parse_success is True


def test_invalid_json_fallback_is_persisted(tmp_path):
    result = repair_json_with_model(
        "{bad",
        lambda prompt: "not json",
        round_id=4,
        artifact_root=tmp_path,
        input_refs=["broken.json"],
    )

    assert result.fallback_used is True
    artifact = tmp_path / "round_000004" / "llm_steps.jsonl"
    payload = _lines(artifact)[0]
    assert payload["fallback_used"] is True
    assert payload["parse_success"] is False
    assert payload["raw_output"] == "not json"
    assert payload["error_type"] == "JSONDecodeError"


def test_semantic_merge_and_root_audit_write_patch_ids_and_raw_output(tmp_path):
    patches = [{"id": "p1", "op": "add"}, {"id": "p2", "op": "replace"}]
    semantic_merge(patches, lambda prompt: '{"merged": ["p1", "p2"]}', round_id=5, artifact_root=tmp_path)
    root_audit(patches, lambda prompt: "invalid json", round_id=5, artifact_root=tmp_path)

    payloads = _lines(tmp_path / "round_000005" / "llm_steps.jsonl")
    assert payloads[0]["step_type"] == "semantic_merge"
    assert payloads[0]["input_refs"] == ["p1", "p2"]
    assert payloads[0]["raw_output"] == '{"merged": ["p1", "p2"]}'
    assert payloads[0]["parse_success"] is True
    assert payloads[1]["step_type"] == "root_audit"
    assert payloads[1]["fallback_used"] is True
    assert payloads[1]["input_refs"] == ["p1", "p2"]


def test_semantic_compression_records_prune_and_validation_outputs(tmp_path):
    result = semantic_compress(
        ["keep", "drop"],
        prune_model=lambda prompt: '["keep"]',
        validation_model=lambda prompt: '{"valid": true, "reason": "meaning preserved"}',
        round_id=6,
        artifact_root=tmp_path,
        input_refs=["item-1", "item-2"],
    )

    assert result["output"] == ["keep"]
    assert result["validation_reason"] == "meaning preserved"
    payloads = _lines(tmp_path / "round_000006" / "llm_steps.jsonl")
    assert [payload["step_type"] for payload in payloads] == ["semantic_prune", "semantic_validation"]
    assert payloads[0]["raw_output"] == '["keep"]'
    assert "prune output" in payloads[0]["accepted_output_summary"]
    assert payloads[1]["raw_output"] == '{"valid": true, "reason": "meaning preserved"}'
    assert "validation reason: meaning preserved" in payloads[1]["accepted_output_summary"]
