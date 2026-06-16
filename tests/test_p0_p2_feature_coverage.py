from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import pytest

from mmap_optimizer.compression.engine import CompressionEngine
from mmap_optimizer.compression.report import CompressionReport
from mmap_optimizer.core.config import (
    OptimizerConfig,
    _float_safe,
    _int_safe,
    optimizer_config_from_mapping,
    validate_optimizer_config_mapping,
)
from mmap_optimizer.core.enums import PromptType, PromptVersionType
from mmap_optimizer.debug.logger import DebugEventLogger
from mmap_optimizer.orchestration.records import OptimizationRound, RoundStage
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.validator import PatchValidationResult, PatchValidator
from mmap_optimizer.prompt.ir import PromptIR, PromptSection
from mmap_optimizer.prompt.snapshot import rollback_to_snapshot, save_prompt_snapshot
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.storage.json_store import JsonStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_prompt_ir(section_contents: list[tuple[str, str]]) -> PromptIR:
    sections = [
        PromptSection(id=sid, type="instruction", content=content, name=sid, priority="medium", compressibility="high")
        for sid, content in section_contents
    ]
    return PromptIR(
        id="ir-1",
        prompt_type="extraction",
        version=1,
        output_schema_contract_id="contract-1",
        sections=sections,
    )


def _build_prompt_version(
    *, prompt_id: str = "pv-1", created_by_round_id: str | None = None, created_by_run_id: str | None = None
) -> PromptVersion:
    return PromptVersion(
        id=prompt_id,
        prompt_type=PromptType.EXTRACTION,
        version=1,
        prompt_ir=_build_prompt_ir([("task", "Answer the following question.")]),
        output_schema_contract_id="contract-1",
        version_type=PromptVersionType.INITIAL,
        created_by_round_id=created_by_round_id,
        created_by_run_id=created_by_run_id,
    )


class _MockModelClient:
    def __init__(self, raw_output: str = "{}") -> None:
        self.raw_output = raw_output

    def complete(self, messages, *, model_config=None):
        class _Resp:
            def __init__(self, raw):
                self.raw_output = raw

        return _Resp(self.raw_output)


class _MockEvaluator:
    def evaluate(self, *args, **kwargs):
        return None


# ---------------------------------------------------------------------------
# P0 - PromptVersion serialization & tracing
# ---------------------------------------------------------------------------


def test_prompt_version_from_dict_preserves_round_and_run_id() -> None:
    original = _build_prompt_version(created_by_round_id="round-1", created_by_run_id="run-1")
    data = asdict(original)
    reconstructed = PromptVersion.from_dict(data)
    assert reconstructed.created_by_round_id == "round-1"
    assert reconstructed.created_by_run_id == "run-1"


def test_prompt_version_from_dict_renders_after_reconstruction() -> None:
    original = _build_prompt_version(created_by_round_id="round-2")
    data = asdict(original)
    reconstructed = PromptVersion.from_dict(data)
    assert reconstructed.rendered_prompt is not None
    assert "task" in reconstructed.rendered_prompt.text


def test_prompt_version_from_dict_handles_missing_round_and_run_id() -> None:
    ir = _build_prompt_ir([("task", "Be concise.")])
    # Minimal payload: no round/run id fields provided
    minimal = {
        "id": "pv-minimal",
        "prompt_type": "extraction",
        "version": 1,
        "output_schema_contract_id": "contract-1",
        "prompt_ir": asdict(ir),
    }
    pv = PromptVersion.from_dict(minimal)
    assert pv.created_by_round_id is None
    assert pv.created_by_run_id is None


# ---------------------------------------------------------------------------
# P0 - Patch constraints
# ---------------------------------------------------------------------------


def test_patch_constraints_serialize_via_from_mapping_and_to_dict() -> None:
    raw = {
        "id": "patch-1",
        "type": "text_patch",
        "status": "candidate",
        "target_prompt_type": "extraction",
        "base_version_id": "pv-1",
        "section_id": "task",
        "operation_type": "ADD_RULE",
        "operation_mode": "replace_section",
        "intent_name": "strengthen",
        "intent_description": "strengthen rule",
        "patch_text": "Please be clear.",
        "rationale": "clarification",
        "constraints": {
            "allowed_operation_types": ["ADD_RULE", "REFINE_RULE"],
            "forbidden_keywords": ["delete"],
            "must_mention_section_ids": ["task"],
        },
    }
    patch = Patch.from_mapping(raw)
    assert patch.constraints["allowed_operation_types"] == ["ADD_RULE", "REFINE_RULE"]
    assert patch.constraints["forbidden_keywords"] == ["delete"]
    snapshot = patch.to_dict()
    assert snapshot["constraints"]["allowed_operation_types"] == ["ADD_RULE", "REFINE_RULE"]
    assert snapshot["constraints"]["forbidden_keywords"] == ["delete"]


def test_patch_validator_honors_allowed_operation_types() -> None:
    ir = _build_prompt_ir([("task", "Original task text.")])
    patch = Patch(
        id="patch-2",
        type="text_patch",
        status="candidate",
        target_prompt_type="extraction",
        base_version_id="pv-1",
        section_id="task",
        operation_type="ADD_RULE",
        operation_mode="replace_section",
        intent_name="intent",
        intent_description="intent",
        patch_text="Refined content that must match in the section.",
        rationale="rationale",
        constraints={"allowed_operation_types": ["REFINE_RULE"]},
    )
    validator = PatchValidator()
    result = validator.validate(patch, ir)
    assert result.valid is False
    assert result.reason is not None


def test_patch_validator_honors_forbidden_keywords() -> None:
    ir = _build_prompt_ir([("task", "Original task text.")])
    patch = Patch(
        id="patch-3",
        type="text_patch",
        status="candidate",
        target_prompt_type="extraction",
        base_version_id="pv-1",
        section_id="task",
        operation_type="REFINE_RULE",
        operation_mode="replace_section",
        intent_name="intent",
        intent_description="intent",
        patch_text="delete some instructions",
        rationale="rationale",
        constraints={
            "allowed_operation_types": ["REFINE_RULE"],
            "forbidden_keywords": ["delete"],
            "must_mention_section_ids": ["task"],
        },
    )
    validator = PatchValidator()
    result = validator.validate(patch, ir)
    assert result.valid is False
    assert result.reason is not None


def test_patch_validator_honors_must_mention_section_ids() -> None:
    ir = _build_prompt_ir([("task", "Original task text.")])
    patch = Patch(
        id="patch-4",
        type="text_patch",
        status="candidate",
        target_prompt_type="extraction",
        base_version_id="pv-1",
        section_id="task",
        operation_type="REFINE_RULE",
        operation_mode="replace_section",
        intent_name="intent",
        intent_description="intent",
        patch_text="Refined content.",
        rationale="rationale",
        constraints={
            "allowed_operation_types": ["REFINE_RULE"],
            "forbidden_keywords": ["delete"],
            "must_mention_section_ids": ["nonexistent_section"],
        },
    )
    validator = PatchValidator()
    result = validator.validate(patch, ir)
    assert result.valid is False
    assert result.reason is not None


def test_patch_compact_dict_produces_minimal_public_view() -> None:
    patch = Patch(
        id="patch-5",
        type="text_patch",
        status="accepted",
        target_prompt_type="extraction",
        base_version_id="pv-1",
        section_id="task",
        operation_type="ADD_RULE",
        operation_mode="replace_section",
        intent_name="intent",
        intent_description="intent",
        patch_text="content",
        rationale="rationale",
        risk_level="low",
        rejection_reason=None,
        fixed_sample_ids=["s1", "s2"],
        broken_sample_ids=[],
    )
    compact = patch.compact_dict()
    assert compact["id"] == "patch-5"
    assert compact["status"] == "accepted"
    assert compact["risk_level"] == "low"
    assert compact["section_id"] == "task"
    # Verify compact view intentionally omits the full payload
    for omitted_key in ("patch_text", "rationale", "intent_description", "target_prompt_type"):
        assert omitted_key not in compact


# ---------------------------------------------------------------------------
# P1 - RoundStage enum & OptimizationRound
# ---------------------------------------------------------------------------


def test_round_stage_has_distinct_enum_values_and_is_json_serializable() -> None:
    values = list(RoundStage)
    assert len(values) >= 15
    # JSON serializable: verify each value is a string that can be dumped
    for stage in values:
        assert json.dumps(stage.value)
    # Make sure values are unique
    assert len({stage.value for stage in values}) == len(values)


def test_optimization_round_default_stage_is_init() -> None:
    round_ = OptimizationRound(
        id="round-1",
        index=0,
        status="in_progress",
        base_extraction_prompt_version_id="pv-1",
        base_analysis_prompt_version_id="pv-2",
    )
    assert round_.current_stage == RoundStage.INIT.value


# ---------------------------------------------------------------------------
# P1 - Snapshot / rollback
# ---------------------------------------------------------------------------


def test_prompt_version_round_and_run_id_survives_save_and_reload() -> None:
    prompt = _build_prompt_version(created_by_round_id="round-42", created_by_run_id="run-7")
    # Simulate a save → dict → from_dict cycle
    data = asdict(prompt)
    reloaded = PromptVersion.from_dict(data)
    assert reloaded.created_by_round_id == "round-42"
    assert reloaded.created_by_run_id == "run-7"


def test_rollback_to_snapshot_with_prompt_payload_reconstructs_prompt() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = JsonStore(tmpdir)
        prompt = _build_prompt_version(
            prompt_id="pv-snap", created_by_round_id="round-10", created_by_run_id="run-10"
        )
        save_prompt_snapshot(store, prompt, "ss-1")
        restored = rollback_to_snapshot(store, "ss-1")
        assert restored.id == "pv-snap"
        assert restored.created_by_round_id == "round-10"
        assert restored.created_by_run_id == "run-10"
        # And rendering was redone during reconstruction
        assert restored.rendered_prompt is not None


# ---------------------------------------------------------------------------
# P1 - Compression token budget
# ---------------------------------------------------------------------------


def test_compression_report_has_token_count_before_and_token_budget() -> None:
    report = CompressionReport(
        id="cr-1",
        round_id="round-1",
        prompt_type="extraction",
        prompt_version_before_id="pv-1",
        triggered=False,
        reason="WITHIN_BUDGET",
        token_count_before=400,
        token_budget=200,
    )
    assert report.token_count_before == 400
    assert report.token_budget == 200


def test_compression_engine_token_budget_triggers_when_exceeded() -> None:
    engine = CompressionEngine(model_client=_MockModelClient(), evaluator=_MockEvaluator())
    # Use a prompt IR whose rendered text is large enough to exceed token budget.
    long_content = "line " * 800  # 800 * 5 chars ≈ 4000 chars → ~1000 tokens
    ir = PromptIR(
        id="ir-big",
        prompt_type="extraction",
        version=1,
        output_schema_contract_id="contract-1",
        sections=[
            PromptSection(
                id="task",
                type="instruction",
                content=long_content,
                name="task",
                priority="medium",
                compressibility="high",
                mutability="normal",
                rendering_enabled=True,
            )
        ],
    )
    prompt = PromptVersion(
        id="pv-big",
        prompt_type=PromptType.EXTRACTION,
        version=1,
        prompt_ir=ir,
        output_schema_contract_id="contract-1",
        created_by_round_id="round-big",
    )
    rendered = prompt.render()
    # Verify the internal token counter produces a meaningful number
    assert engine._token_count(rendered.text) > 100

    # Run with no token budget (so compression won't trigger based on tokens)
    _, report_no_budget, _, _ = engine.compress_if_needed(
        round_id="round-big",
        prompt=prompt,
        line_budget=None,
        samples=[],
        assets={},
        ground_truths={},
        contract=object(),
        base_evaluations=[],
        token_budget=None,
    )
    assert report_no_budget.triggered is False

    # Run with a tiny token budget that is certainly exceeded
    _, report_small_budget, _, _ = engine.compress_if_needed(
        round_id="round-big",
        prompt=prompt,
        line_budget=None,
        samples=[],
        assets={},
        ground_truths={},
        contract=object(),
        base_evaluations=[],
        token_budget=1,
    )
    assert report_small_budget.triggered is True


# ---------------------------------------------------------------------------
# P2 - Config safe parsing & validate
# ---------------------------------------------------------------------------


def test_int_safe_returns_default_for_none() -> None:
    assert _int_safe(None, 42) == 42


def test_int_safe_returns_default_for_bad_string_and_dict() -> None:
    assert _int_safe("not-a-number", 7) == 7
    assert _int_safe({"key": "value"}, 7) == 7


def test_int_safe_converts_valid_strings_to_int() -> None:
    assert _int_safe("12", 0) == 12
    assert _int_safe("0", 99) == 0


def test_float_safe_returns_default_for_bad_inputs() -> None:
    assert _float_safe(None, 1.5) == 1.5
    assert _float_safe("not-a-float", 1.5) == 1.5
    assert _float_safe({"a": 1}, 2.0) == 2.0


def test_optimizer_config_validate_reports_multiple_issues_for_bad_values() -> None:
    config = OptimizerConfig(
        batch_size=-1,
        dynamic_validation_batch_size=0,
        dynamic_validation_min_label_count=0,
        max_text_rounds=-1,
        execution_max_workers=0,
        eval_vote_rounds=-1,
        extraction_token_budget=0,
        fewshot_min_accuracy_delta=2.0,
    )
    issues = config.validate()
    assert len(issues) >= 2


def test_optimizer_config_validate_returns_empty_list_for_defaults() -> None:
    assert OptimizerConfig().validate() == []


def test_validate_optimizer_config_mapping_works() -> None:
    good = {"text_optimization": {"batch_size": 10}}
    assert validate_optimizer_config_mapping(good) == []
    bad = {"text_optimization": {"batch_size": -1}}
    issues = validate_optimizer_config_mapping(bad)
    assert any("batch_size" in issue for issue in issues)


def test_optimizer_config_from_mapping_handles_bad_values_gracefully() -> None:
    mapping = {
        "text_optimization": {"batch_size": "not-a-number"},
        "compression": {"extraction_line_budget": 100},
    }
    config = optimizer_config_from_mapping(mapping)
    # batch_size falls back to the default, extraction_line_budget is set
    assert config.batch_size == 24
    assert config.extraction_line_budget == 100


# ---------------------------------------------------------------------------
# P2 - DebugEventLogger
# ---------------------------------------------------------------------------


def test_debug_event_logger_log_increments_counters_and_exposes_summary() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = DebugEventLogger(JsonStore(tmpdir), "events.jsonl")
        logger.log("patch_validated", "ok")
        logger.log("patch_validated", "ok-2")
        logger.log("patch_applied", "applied patch")
        summary = logger.summary()
        assert summary["total_in_memory"] == 3
        assert summary["counts_in_memory"]["patch_validated"] == 2
        assert summary["counts_in_memory"]["patch_applied"] == 1
        assert (Path(tmpdir) / "events.jsonl").exists()


def test_debug_event_logger_clear_resets_counters_and_removes_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = DebugEventLogger(JsonStore(tmpdir), "events.jsonl")
        logger.log("a", "1")
        logger.log("b", "2")
        assert logger.summary()["total_in_memory"] == 2
        logger.clear()
        assert logger.summary()["total_in_memory"] == 0
        assert logger.summary()["counts_in_memory"] == {}
        assert not (Path(tmpdir) / "events.jsonl").exists()


def test_debug_event_logger_reset_counters_resets_only_memory() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = DebugEventLogger(JsonStore(tmpdir), "events.jsonl")
        logger.log("a", "1")
        logger.reset_counters()
        assert logger.summary()["total_in_memory"] == 0
        # backing file still present
        assert (Path(tmpdir) / "events.jsonl").exists()


# ---------------------------------------------------------------------------
# P2 - Patch.to_dict & PatchValidationResult.to_dict
# ---------------------------------------------------------------------------


def test_patch_to_dict_includes_constraints_and_main_fields() -> None:
    patch = Patch(
        id="patch-6",
        type="text_patch",
        status="candidate",
        target_prompt_type="extraction",
        base_version_id="pv-1",
        section_id="task",
        operation_type="REFINE_RULE",
        operation_mode="replace_section",
        intent_name="intent",
        intent_description="intent",
        patch_text="content",
        rationale="rationale",
        constraints={"allowed_operation_types": ["REFINE_RULE"], "forbidden_keywords": []},
    )
    data = patch.to_dict()
    assert data["id"] == "patch-6"
    assert data["section_id"] == "task"
    assert data["constraints"]["allowed_operation_types"] == ["REFINE_RULE"]
    assert data["operation_type"] == "REFINE_RULE"
    # Round-trippable
    round_tripped = Patch.from_mapping(data)
    assert round_tripped.id == patch.id
    assert round_tripped.constraints == patch.constraints


def test_patch_validation_result_to_dict_serializes_correctly() -> None:
    valid = PatchValidationResult(valid=True)
    invalid = PatchValidationResult(valid=False, reason="BAD_PATCH")
    assert valid.to_dict() == {"valid": True, "reason": None}
    assert invalid.to_dict() == {"valid": False, "reason": "BAD_PATCH"}
