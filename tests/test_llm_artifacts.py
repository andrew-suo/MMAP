import json

from mmap_optimizer.analysis.llm_repair import repair_json_output
from mmap_optimizer.compression.semantic import semantic_compress
from mmap_optimizer.orchestration.round_runner import RoundRunner
from mmap_optimizer.patch.semantic import semantic_merge


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_json_repair_writes_artifact(tmp_path):
    runner = RoundRunner(tmp_path)

    result = runner.run_round(1, lambda: repair_json_output("```json\n{'ok': true,}\n```"))

    assert result.llm_steps_path.exists()
    records = _read_jsonl(result.llm_steps_path)
    assert records
    assert records[-1]["step_type"] == "json_repair"
    assert records[-1]["parse_success"] is True
    assert records[-1]["fallback_used"] is True


def test_semantic_merge_writes_patch_ids_and_raw_output(tmp_path):
    runner = RoundRunner(tmp_path)

    result = runner.run_round(
        "round_000002",
        lambda: semantic_merge(
            [{"id": "p1", "text": "one"}, {"id": "p2", "text": "two"}],
            llm=lambda _prompt: '{"merged_text": "one two"}',
        ),
    )

    records = _read_jsonl(result.llm_steps_path)
    merge = [record for record in records if record["step_type"] == "semantic_merge"][-1]
    assert merge["input_refs"] == ["p1", "p2"]
    assert merge["raw_output"] == '{"merged_text": "one two"}'
    assert merge["parse_success"] is True
    assert merge["fallback_used"] is False


def test_semantic_compression_writes_prune_validation_and_reason(tmp_path):
    runner = RoundRunner(tmp_path)

    round_result = runner.run_round(
        3,
        lambda: semantic_compress(
            ["alpha", "beta"],
            llm=lambda _prompt: "alpha",
            validator=lambda _prompt: '{"valid": true, "reason": "covers key facts"}',
        ),
    )

    assert round_result.result["prune_output"] == "alpha"
    assert round_result.result["validation_output"] == '{"valid": true, "reason": "covers key facts"}'
    assert round_result.result["validation_reason"] == "covers key facts"
    records = _read_jsonl(round_result.llm_steps_path)
    compression = [record for record in records if record["step_type"] == "semantic_compression"][-1]
    assert compression["raw_output"] == "alpha"
    assert compression["accepted_output_summary"] == "covers key facts"


def test_invalid_llm_json_records_fallback(tmp_path):
    runner = RoundRunner(tmp_path)

    runner.run_round(4, lambda: semantic_merge([{"id": "bad", "text": "x"}], llm=lambda _prompt: "not json"))

    records = _read_jsonl(tmp_path / "round_000004" / "llm_steps.jsonl")
    assert any(record["fallback_used"] and not record["parse_success"] for record in records)
