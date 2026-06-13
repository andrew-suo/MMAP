import json

from mmap_optimizer.analysis.llm_repair import repair_text
from mmap_optimizer.compression.semantic import semantic_prune_and_validate
from mmap_optimizer.orchestration.round_runner import RoundRunner
from mmap_optimizer.patch.semantic import semantic_merge


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_feature_flagged_round_artifacts_are_written(tmp_path):
    runner = RoundRunner(tmp_path, 7, record_llm_steps=True)

    def work():
        result = semantic_merge(
            [{"id": "p1", "body": "old"}],
            lambda _prompt: '{"patches": [{"id": "p2", "body": "merged"}]}',
            template_id="test.merge",
        )
        assert result.parse_success is True
        return result

    runner.run(work)

    records = _jsonl(tmp_path / "round_000007" / "llm_steps.jsonl")
    assert len(records) == 1
    assert records[0]["round_id"] == "round_000007"
    assert records[0]["step_type"] == "semantic_merge"
    assert records[0]["template_id"] == "test.merge"
    assert records[0]["input_summary"]["input_patch_ids"] == ["p1"]
    assert records[0]["raw_output"] == '{"patches": [{"id": "p2", "body": "merged"}]}'
    assert records[0]["parse_success"] is True
    assert records[0]["fallback_used"] is False


def test_invalid_json_fallback_is_recorded(tmp_path):
    runner = RoundRunner(tmp_path, 8, record_llm_steps=True)

    def work():
        result = semantic_merge(
            [{"id": "original", "body": "keep"}],
            lambda _prompt: "not json",
            template_id="test.invalid",
        )
        assert result.patches == [{"id": "original", "body": "keep"}]
        assert result.parse_success is False
        assert result.fallback_used is True
        return result

    runner.run(work)

    records = _jsonl(tmp_path / "round_000008" / "llm_steps.jsonl")
    assert len(records) == 1
    assert records[0]["step_type"] == "semantic_merge"
    assert records[0]["raw_output"] == "not json"
    assert records[0]["parse_success"] is False
    assert records[0]["fallback_used"] is True
    assert records[0]["error_type"] == "json_decode_error"


def test_repair_and_compression_record_metadata(tmp_path):
    runner = RoundRunner(tmp_path, 9, record_llm_steps=True)

    def work():
        repair = repair_text("orig", lambda _prompt: '{"repaired_text": "fixed"}')
        compression = semantic_prune_and_validate(
            ["a", "b"],
            lambda _prompt: '{"items": ["a"]}',
            lambda _prompt: '{"valid": false, "reason": "lost required item"}',
        )
        assert str(repair) == "fixed"
        assert compression.validation_reason == "lost required item"

    runner.run(work)

    records = _jsonl(tmp_path / "round_000009" / "llm_steps.jsonl")
    assert [record["step_type"] for record in records] == [
        "llm_repair",
        "semantic_prune",
        "semantic_validation",
    ]
    assert records[2]["raw_output"] == '{"valid": false, "reason": "lost required item"}'
    assert records[2]["metadata"]["validation_reason"] == "lost required item"
