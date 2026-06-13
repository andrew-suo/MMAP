from mmap_optimizer.compression.engine import _compression_candidate_content
from mmap_optimizer.compression.report import CompressionReport
from mmap_optimizer.compression.semantic import semantic_prune_section


def test_validation_false_then_retry_success_keeps_original_baseline():
    original = "line 1\nline 2\nline 3"
    candidates = iter(["line 1", "line 1\nline 2"])
    validation_originals = []

    def prune(section):
        assert section == original
        return next(candidates)

    def validate(original_section, candidate_section):
        validation_originals.append(original_section)
        return {
            "valid": candidate_section == "line 1\nline 2",
            "reason": "candidate keeps required lines",
        }

    result = semantic_prune_section(original, prune, validate, max_attempts=2)

    assert result.accepted is True
    assert result.content == "line 1\nline 2"
    assert result.attempt_count == 2
    assert result.candidate_lines == [["line 1"], ["line 1", "line 2"]]
    assert validation_originals == [original, original]


def test_validation_parse_error_is_reported_and_not_accepted():
    result = semantic_prune_section(
        "original",
        lambda section: "candidate",
        lambda original, candidate: {"valid": "yes"},
        max_attempts=3,
    )

    assert result.accepted is False
    assert result.content == "original"
    assert result.attempt_count == 1
    assert result.rejected_reason.startswith("validation_parse_error:")
    assert result.candidate_lines == [["candidate"]]


def test_semantic_success_but_behavior_gate_failure_rejects_candidate():
    report = CompressionReport()

    candidate = _compression_candidate_content(
        "original\nrequired",
        prune=lambda section: "original",
        validate=lambda original, compressed: {"valid": True, "reason": "semantically ok"},
        max_attempts=1,
        behavior_gate=lambda original, compressed: False,
        report=report,
    )

    assert candidate.accepted is False
    assert candidate.content == "original\nrequired"
    assert candidate.semantic.accepted is True
    assert candidate.behavior_preservation_passed is False
    assert candidate.rejected_reason == "behavior_preservation_failed"
    assert report.accepted is False
    assert report.rejected_reason == "behavior_preservation_failed"
    assert report.behavior_preservation_passed is False
    assert report.semantic_validation_reason == "semantically ok"
    assert report.semantic_attempt_count == 1
    assert report.semantic_candidate_lines == [["original"]]
    assert report.semantic_rejected_reason is None
