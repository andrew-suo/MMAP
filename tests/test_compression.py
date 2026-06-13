import json

from mmap_optimizer.compression.engine import CompressionEngine
from mmap_optimizer.compression.semantic import semantic_compress_section


class RecordingLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("LLM called more often than expected")
        return self.responses.pop(0)


def prune(content, reason="ok"):
    return json.dumps({"content": content, "reason": reason})


def validation(valid, reason="ok"):
    return json.dumps({"valid": valid, "reason": reason})


def test_first_validation_false_second_true_uses_original_for_each_validation():
    original = "line 1\nline 2\nline 3"
    llm = RecordingLLM(
        [
            prune("line 1\nline 3", "attempt one"),
            validation(False, "missing line 2"),
            prune("line 1\nline 2", "attempt two"),
            validation(True, "equivalent"),
        ]
    )

    result = semantic_compress_section(original, llm, max_attempts=2)

    assert result.accepted is True
    assert result.content == "line 1\nline 2"
    assert result.attempt_count == 2
    validation_prompts = [prompt for prompt in llm.prompts if "Validate whether" in prompt]
    assert len(validation_prompts) == 2
    assert all(f"ORIGINAL_SECTION:\n{original}" in prompt for prompt in validation_prompts)


def test_validation_raw_output_non_json_is_explicit_parse_error():
    llm = RecordingLLM([prune("short"), "not json"])

    engine = CompressionEngine(llm=llm, max_attempts=3)
    output = engine.compress_section("long original")

    assert output == "long original"
    assert engine.report is not None
    assert engine.report.semantic_attempt_count == 1
    assert engine.report.semantic_validation_raw_output == "not json"
    assert engine.report.semantic_rejected_reason.startswith("validation_parse_error:")


def test_semantic_validation_true_but_behavior_gate_fails():
    llm = RecordingLLM([prune("short"), validation(True, "equivalent")])

    engine = CompressionEngine(
        llm=llm,
        behavior_gate=lambda candidate, original: (False, "lost required token"),
    )
    output = engine.compress_section("long original")

    assert output == "long original"
    assert engine.report is not None
    assert engine.report.semantic_attempt_count == 1
    assert engine.report.semantic_validation_reason == "equivalent"
    assert engine.report.semantic_rejected_reason == "behavior_gate_failed: lost required token"


def test_deterministic_compression_success_does_not_call_llm():
    def llm(_prompt):
        raise AssertionError("semantic LLM should not be called")

    engine = CompressionEngine(
        llm=llm,
        deterministic_compressor=lambda section: ("deterministic", "trimmed", True),
    )

    output = engine.compress_section("original")

    assert output == "deterministic"
    assert engine.report is not None
    assert engine.report.strategy == "deterministic"
    assert engine.report.semantic_attempt_count == 0
