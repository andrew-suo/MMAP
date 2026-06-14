"""Contract tests extracted and adapted from PR #7.

PR #7 proposed a wide set of contract tests for MMAP.  This file keeps the
ideas that map cleanly onto the current ``main`` module layout and drops
those that referenced API surfaces no longer present, e.g. ``checkpoint``
style ``save(run_id, step, state)`` or a hypothetical ``run_patch_and_round``
pipeline that has not landed.

Scope of this file:

* Prompt health contract (H1–H6 issue codes and safe autofix).
* Import stability for every module introduced in #33–#44.
* Section contribution JSON round-trip (from #41).
* Scenario contract (from #36).
* Checkpoint/resume contract (from #37).
* LLM step record contract (from #38).
* Exact text patch contract (from #39).
* Patch repair contract (from #40).
* Merge ranking / compression helper contracts (#42–#44).
* CLI smoke contract (help / run-smoke / resume don't crash).

The file intentionally avoids exercising model clients, external network
calls, or semantic compression — those are out of scope for contract tests
of the lightweight helpers.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from mmap_optimizer.metrics.section_deltas import (
    SectionContributionDelta,
    compute_section_deltas,
    rank_section_deltas,
    section_contributions_to_dict,
)
from mmap_optimizer.prompt.health import (
    PromptHealthIssue,
    PromptHealthReport,
    check_prompt_health,
    safe_autofix_prompt_ir,
)
from mmap_optimizer.prompt.ir import PromptIR, PromptSection
from mmap_optimizer.core.enums import PromptType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_prompt_ir(sections: list[PromptSection]) -> PromptIR:
    return PromptIR(
        id="contract-test-ir",
        prompt_type=PromptType.EXTRACTION,
        version=1,
        output_schema_contract_id="schema-v1",
        sections=sections,
        rendering_order=[section.id for section in sections],
    )


@pytest.fixture
def clean_prompt_ir() -> PromptIR:
    return _minimal_prompt_ir(
        [
            PromptSection(
                id="task", type="instruction", content="Follow the task below."
            ),
            PromptSection(
                id="examples",
                type="example",
                content="Example: 2 + 2 → 4.",
            ),
            PromptSection(
                id="output_schema",
                type="schema",
                content='{"value": 42}',
                mutability="frozen",
                compressibility="none",
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Import stability
# ---------------------------------------------------------------------------


class TestImportStability:
    """Every module introduced in #33–#44 must remain importable by name."""

    @pytest.mark.parametrize(
        "module_name",
        [
            # #33 – safety/safety infrastructure
            "mmap_optimizer.prompt.health",
            # #36 – scenario support
            "mmap_optimizer.core.scenario",
            # #37 – checkpoint/resume
            "mmap_optimizer.orchestration.checkpoint",
            # #38 – LLM step record artifacts
            "mmap_optimizer.orchestration.llm_records",
            # #39 – exact text patch operations
            "mmap_optimizer.patch.validator",
            "mmap_optimizer.patch.applier",
            # #40 – patch repair engine
            "mmap_optimizer.patch.repair",
            # #41 – section contribution metrics
            "mmap_optimizer.metrics.section_deltas",
            # #42–#44 – risk signals + merge ranking + compression helpers
            "mmap_optimizer.patch.merge_report",
            "mmap_optimizer.patch.schema",
            "mmap_optimizer.compression.report",
            "mmap_optimizer.compression.semantic",
            # Shared primitives referenced across the contract
            "mmap_optimizer.prompt.ir",
            "mmap_optimizer.core.hashing",
            "mmap_optimizer.evaluation.voting",
        ],
    )
    def test_module_is_importable(self, module_name: str) -> None:
        module = importlib.import_module(module_name)
        assert module is not None

    def test_known_health_issue_codes_are_present(self) -> None:
        """The implementation references the H1–H6 issue codes by
        convention.  Guard against silent renames that would break
        downstream report parsers."""

        sample_ir = _minimal_prompt_ir(
            [
                PromptSection(id="duplicate", type="instruction", content="a"),
                PromptSection(id="duplicate", type="instruction", content="b"),
            ]
        )
        report = check_prompt_health(sample_ir)
        codes = {issue.code for issue in report.issues}
        assert "H1_DUPLICATE_SECTION_ID" in codes


# ---------------------------------------------------------------------------
# Prompt health contracts
# ---------------------------------------------------------------------------


class TestPromptHealthReportStructure:
    def test_report_exposes_ok_and_issues(self, clean_prompt_ir: PromptIR) -> None:
        report = check_prompt_health(clean_prompt_ir)
        assert isinstance(report, PromptHealthReport)
        assert report.prompt_ir_id == clean_prompt_ir.id
        assert hasattr(report, "ok")
        assert isinstance(report.issues, list)

    def test_h1_duplicate_section_id_is_error(self) -> None:
        ir = _minimal_prompt_ir(
            [
                PromptSection(id="task", type="instruction", content="a"),
                PromptSection(id="task", type="instruction", content="b"),
            ]
        )
        report = check_prompt_health(ir)
        assert report.ok is False
        assert any(
            issue.code == "H1_DUPLICATE_SECTION_ID" and issue.severity == "error"
            for issue in report.issues
        )

    def test_h2_rendering_order_missing_section_is_error(self) -> None:
        ir = _minimal_prompt_ir(
            [PromptSection(id="task", type="instruction", content="")]
        )
        ir.rendering_order = ["task", "ghost-section"]
        report = check_prompt_health(ir)
        assert report.ok is False
        assert any(issue.code.startswith("H2_") for issue in report.issues)

    def test_h3_empty_rendered_section_is_warning(self) -> None:
        ir = _minimal_prompt_ir(
            [PromptSection(id="empty", type="instruction", content="")]
        )
        report = check_prompt_health(ir)
        assert any(
            issue.code.startswith("H3_") and issue.severity == "warning"
            for issue in report.issues
        )

    def test_h5_frozen_compressible_is_error(self) -> None:
        ir = _minimal_prompt_ir(
            [
                PromptSection(
                    id="locked",
                    type="instruction",
                    content="must stay",
                    mutability="frozen",
                    compressibility="high",
                )
            ]
        )
        report = check_prompt_health(ir)
        assert any(issue.code.startswith("H5_") for issue in report.issues)

    def test_h6_schema_not_frozen_is_error(self) -> None:
        ir = _minimal_prompt_ir(
            [
                PromptSection(
                    id="output_schema",
                    type="schema",
                    content="{}",
                    mutability="normal",
                    compressibility="medium",
                )
            ]
        )
        report = check_prompt_health(ir)
        assert report.ok is False
        assert any(issue.code.startswith("H6_") for issue in report.issues)

    def test_issue_returns_dataclass_with_section_id(self) -> None:
        ir = _minimal_prompt_ir(
            [
                PromptSection(id="a", type="instruction", content="x"),
                PromptSection(id="a", type="instruction", content="y"),
            ]
        )
        report = check_prompt_health(ir)
        issue = next(i for i in report.issues if i.code == "H1_DUPLICATE_SECTION_ID")
        assert isinstance(issue, PromptHealthIssue)
        assert issue.severity in {"error", "warning"}


class TestSafeAutofixPromptIR:
    def test_autofix_deduplicates_section_ids(self) -> None:
        ir = _minimal_prompt_ir(
            [
                PromptSection(id="dup", type="instruction", content="one"),
                PromptSection(id="dup", type="instruction", content="two"),
            ]
        )
        fixed = safe_autofix_prompt_ir(ir)
        section_ids = [section.id for section in fixed.sections]
        assert len(section_ids) == len(set(section_ids))

    def test_autofix_freezes_output_schema(self) -> None:
        ir = _minimal_prompt_ir(
            [
                PromptSection(
                    id="output_schema",
                    type="schema",
                    content="{}",
                    mutability="normal",
                    compressibility="medium",
                )
            ]
        )
        fixed = safe_autofix_prompt_ir(ir)
        output_schema = next(
            section for section in fixed.sections if section.id == "output_schema"
        )
        assert output_schema.mutability == "frozen"
        assert output_schema.compressibility == "none"

    def test_autofix_preserves_existing_content(self) -> None:
        original = "Keep this content verbatim."
        ir = _minimal_prompt_ir(
            [
                PromptSection(
                    id="task", type="instruction", content=original
                )
            ]
        )
        fixed = safe_autofix_prompt_ir(ir)
        assert any(section.content == original for section in fixed.sections)

    def test_autofix_does_not_mutate_input(self) -> None:
        ir = _minimal_prompt_ir(
            [PromptSection(id="task", type="instruction", content="v")]
        )
        original_content = [section.content for section in ir.sections]
        safe_autofix_prompt_ir(ir)
        after_content = [section.content for section in ir.sections]
        assert after_content == original_content


# ---------------------------------------------------------------------------
# Scenario contract (#36)
# ---------------------------------------------------------------------------


class TestScenarioContract:
    """Scenario metadata should be stable across import/validation cycles."""

    def test_scenario_module_exposes_standard_symbols(self) -> None:
        scenario_module = importlib.import_module("mmap_optimizer.core.scenario")
        for symbol in (
            "load_scenario",
            "validate_scenario",
            "list_scenarios",
            "run_artifact_metadata",
            "write_run_artifacts",
        ):
            assert hasattr(scenario_module, symbol), f"Missing symbol: {symbol}"

    def test_list_scenarios_returns_deterministic_shape(self) -> None:
        from mmap_optimizer.core.scenario import list_scenarios, DEFAULT_SCENARIOS_DIR

        scenarios_dir = Path(DEFAULT_SCENARIOS_DIR)
        if not scenarios_dir.exists():
            pytest.skip(f"Default scenarios dir does not exist: {DEFAULT_SCENARIOS_DIR}")
        result = list_scenarios(scenarios_dir)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
            assert "id" in item
            assert isinstance(item["id"], str)


# ---------------------------------------------------------------------------
# Checkpoint/resume contract (#37)
# ---------------------------------------------------------------------------


class TestCheckpointResumeContract:
    """Checkpoint data must round-trip through save/load."""

    def test_prompt_snapshot_round_trip(self, tmp_path: Path) -> None:
        from mmap_optimizer.orchestration.checkpoint import PromptSnapshot

        original = PromptSnapshot.create(
            snapshot_id="pre-promotion-v1",
            prompt_name="extraction",
            version=3,
            rendered="Raw rendered prompt text.",
            round_index=2,
            stage="pre_promotion",
            metadata={"source": "contract-test"},
        )
        destination = tmp_path / "snapshot.json"
        path = original.save(destination)
        assert path.exists()

        restored = PromptSnapshot.load(path)
        assert restored.snapshot_id == original.snapshot_id
        assert restored.prompt_name == original.prompt_name
        assert restored.version == original.version
        assert restored.rendered == original.rendered
        assert restored.rendered_hash == original.rendered_hash
        assert restored.round_index == original.round_index
        assert restored.stage == original.stage

    def test_optimizer_checkpoint_round_trip(self, tmp_path: Path) -> None:
        from mmap_optimizer.orchestration.checkpoint import OptimizerCheckpoint

        original = OptimizerCheckpoint(
            round_index=5,
            active_prompts={"extraction": {"version": 1}, "analysis": {"version": 1}},
            sample_states=[{"id": "s-1", "seen": True}, {"id": "s-2", "seen": False}],
            fewshot_pool_path=str(tmp_path / "fewshot.json"),
            metrics_summary={"accuracy": 0.75},
        )
        destination = tmp_path / "checkpoint.json"
        path = original.save(destination)
        assert path.exists()

        restored = OptimizerCheckpoint.load(path)
        assert restored.round_index == original.round_index
        assert restored.active_prompts == original.active_prompts
        assert restored.sample_states == original.sample_states
        assert restored.metrics_summary == original.metrics_summary

    def test_checkpoint_round_index_stability(self, tmp_path: Path) -> None:
        """Resume must read back the exact round_index that was written."""
        from mmap_optimizer.orchestration.checkpoint import OptimizerCheckpoint

        for round_index in (0, 1, 7, 42):
            ckpt = OptimizerCheckpoint(
                round_index=round_index,
                active_prompts={},
                sample_states=[],
                fewshot_pool_path=None,
                metrics_summary={},
            )
            destination = tmp_path / f"checkpoint-{round_index}.json"
            ckpt.save(destination)
            restored = OptimizerCheckpoint.load(destination)
            assert restored.round_index == round_index

    def test_checkpoint_to_dict_is_json_serializable(self, tmp_path: Path) -> None:
        from mmap_optimizer.orchestration.checkpoint import OptimizerCheckpoint

        original = OptimizerCheckpoint(
            round_index=3,
            active_prompts={"extraction": {"version": 1}},
            sample_states=[],
            fewshot_pool_path=None,
            metrics_summary={"round": 3, "accuracy": 0.8},
        )
        payload = original.to_dict()
        # No exception raised during JSON round-trip
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        restored = OptimizerCheckpoint.from_dict(json.loads(text))
        assert restored.round_index == 3
        assert restored.metrics_summary["accuracy"] == 0.8


# ---------------------------------------------------------------------------
# LLM step record contract (#38)
# ---------------------------------------------------------------------------


class TestLLMStepRecordContract:
    """LLM step records must round-trip through JSONL append/read."""

    def test_step_record_to_json_then_from_dict(self) -> None:
        from mmap_optimizer.orchestration.llm_records import (
            LLMStepRecord,
            hash_prompt,
        )

        record = LLMStepRecord(
            round_id="round-0",
            step_type="generate_patch",
            template_id="patch-v1",
            prompt_hash=hash_prompt("A test prompt."),
            input_refs=["sample-1", "sample-2"],
            raw_output='{"patch": "content"}',
            parse_success=True,
            fallback_used=False,
            error_type=None,
            accepted_output_summary="Produced one actionable patch.",
            metadata={"contract": True},
        )
        payload = record.to_dict()
        assert payload["round_id"] == record.round_id
        assert payload["parse_success"] is True

        restored = LLMStepRecord.from_dict(payload)
        assert restored.round_id == record.round_id
        assert restored.input_refs == record.input_refs
        assert restored.metadata == record.metadata

    def test_jsonl_append_and_read_preserves_records(self, tmp_path: Path) -> None:
        from mmap_optimizer.orchestration.llm_records import (
            LLMStepRecord,
            append_llm_record,
            read_llm_records,
            hash_prompt,
        )

        artifact = tmp_path / "llm_steps.jsonl"
        records = [
            LLMStepRecord(
                round_id=f"round-{i}",
                step_type="generate_patch",
                template_id="patch-v1",
                prompt_hash=hash_prompt(f"prompt {i}"),
                input_refs=[f"s-{i}"],
                raw_output=f"output {i}",
                parse_success=True,
            )
            for i in range(3)
        ]
        for record in records:
            append_llm_record(artifact, record)

        restored = read_llm_records(artifact)
        assert len(restored) == len(records)
        for original, reread in zip(records, restored):
            assert original.round_id == reread.round_id
            assert original.step_type == reread.step_type
            assert original.raw_output == reread.raw_output

    def test_read_missing_artifact_returns_empty(self, tmp_path: Path) -> None:
        from mmap_optimizer.orchestration.llm_records import read_llm_records

        assert read_llm_records(tmp_path / "no-such-file.jsonl") == []

    def test_coerce_input_refs_handles_scalars_and_lists(self) -> None:
        from mmap_optimizer.orchestration.llm_records import coerce_input_refs

        assert coerce_input_refs(None) == []
        assert coerce_input_refs("single-ref") == ["single-ref"]
        assert coerce_input_refs(["a", "b"]) == ["a", "b"]


# ---------------------------------------------------------------------------
# Exact text patch contract (#39)
# ---------------------------------------------------------------------------


class TestExactTextPatchContract:
    """Patch validator must report stable error codes for common failure modes."""

    def _simple_prompt_ir(self) -> PromptIR:
        return _minimal_prompt_ir(
            [
                PromptSection(id="task", type="instruction", content="Think carefully."),
                PromptSection(
                    id="output_schema",
                    type="schema",
                    content="{}",
                    mutability="frozen",
                    compressibility="none",
                ),
            ]
        )

    def test_invalid_target_section_rejected(self) -> None:
        from mmap_optimizer.patch.schema import Patch
        from mmap_optimizer.patch.validator import PatchValidator

        prompt_ir = self._simple_prompt_ir()
        patch = Patch(
            id="p-1",
            type="prompt_patch",
            status="pending",
            target_prompt_type="extraction",
            base_version_id="v1",
            section_id="nonexistent-section",
            operation_type="REFINE_RULE",
            operation_mode="replace_in_section",
            intent_name="test",
            intent_description="test",
            patch_text="replacement",
            rationale="contract test",
            old_text="missing",
            source_sample_ids=["sample-1"],
        )
        result = PatchValidator().validate(patch, prompt_ir)
        assert result.valid is False
        assert result.reason == "INVALID_TARGET_SECTION"

    def test_frozen_section_rejected(self) -> None:
        from mmap_optimizer.patch.schema import Patch
        from mmap_optimizer.patch.validator import PatchValidator

        prompt_ir = self._simple_prompt_ir()
        patch = Patch(
            id="p-2",
            type="prompt_patch",
            status="pending",
            target_prompt_type="extraction",
            base_version_id="v1",
            section_id="output_schema",
            operation_type="REFINE_RULE",
            operation_mode="replace_in_section",
            intent_name="test",
            intent_description="test",
            patch_text="new schema",
            rationale="contract test",
            old_text="{}",
            source_sample_ids=["sample-1"],
        )
        result = PatchValidator().validate(patch, prompt_ir)
        assert result.valid is False
        assert result.reason == "TARGET_SECTION_FROZEN"

    def test_missing_locator_rejected(self) -> None:
        from mmap_optimizer.patch.schema import Patch
        from mmap_optimizer.patch.validator import PatchValidator

        prompt_ir = self._simple_prompt_ir()
        patch = Patch(
            id="p-3",
            type="prompt_patch",
            status="pending",
            target_prompt_type="extraction",
            base_version_id="v1",
            section_id="task",
            operation_type="REFINE_RULE",
            operation_mode="replace_in_section",
            intent_name="test",
            intent_description="test",
            patch_text="new content",
            rationale="contract test",
            old_text="text that is not in the section",
            source_sample_ids=["sample-1"],
        )
        result = PatchValidator().validate(patch, prompt_ir)
        assert result.valid is False
        assert result.reason == "PATCH_LOCATOR_NOT_FOUND"

    def test_ambiguous_locator_rejected(self) -> None:
        from mmap_optimizer.patch.schema import Patch
        from mmap_optimizer.patch.validator import PatchValidator

        ambiguous_ir = _minimal_prompt_ir(
            [
                PromptSection(
                    id="task",
                    type="instruction",
                    content="Repeat Repeat Repeat.",
                )
            ]
        )
        patch = Patch(
            id="p-4",
            type="prompt_patch",
            status="pending",
            target_prompt_type="extraction",
            base_version_id="v1",
            section_id="task",
            operation_type="REFINE_RULE",
            operation_mode="replace_in_section",
            intent_name="test",
            intent_description="test",
            patch_text="Once.",
            rationale="contract test",
            old_text="Repeat",
            source_sample_ids=["sample-1"],
        )
        result = PatchValidator().validate(patch, ambiguous_ir)
        assert result.valid is False
        assert result.reason == "AMBIGUOUS_LOCATOR"

    def test_empty_patch_text_rejected(self) -> None:
        from mmap_optimizer.patch.schema import Patch
        from mmap_optimizer.patch.validator import PatchValidator

        prompt_ir = self._simple_prompt_ir()
        patch = Patch(
            id="p-5",
            type="prompt_patch",
            status="pending",
            target_prompt_type="extraction",
            base_version_id="v1",
            section_id="task",
            operation_type="REFINE_RULE",
            operation_mode="replace_in_section",
            intent_name="test",
            intent_description="test",
            patch_text="",
            rationale="contract test",
            old_text="Think carefully.",
            source_sample_ids=["sample-1"],
        )
        result = PatchValidator().validate(patch, prompt_ir)
        assert result.valid is False
        assert result.reason == "EMPTY_PATCH_TEXT"

    def test_valid_replace_patch_accepted(self) -> None:
        from mmap_optimizer.patch.schema import Patch
        from mmap_optimizer.patch.validator import PatchValidator

        prompt_ir = self._simple_prompt_ir()
        patch = Patch(
            id="p-6",
            type="prompt_patch",
            status="pending",
            target_prompt_type="extraction",
            base_version_id="v1",
            section_id="task",
            operation_type="REFINE_RULE",
            operation_mode="replace_in_section",
            intent_name="test",
            intent_description="test",
            patch_text="Stop and check.",
            rationale="contract test",
            old_text="Think carefully.",
            source_sample_ids=["sample-1"],
        )
        result = PatchValidator().validate(patch, prompt_ir)
        assert result.valid is True


# ---------------------------------------------------------------------------
# Patch repair contract (#40)
# ---------------------------------------------------------------------------


class TestPatchRepairContract:
    """Repair results must expose a stable schema for audit logging."""

    def test_repair_result_to_dict_exposes_standard_fields(self) -> None:
        from mmap_optimizer.patch.repair import RepairResult
        from mmap_optimizer.patch.schema import Patch

        original = Patch(
            id="original-1",
            type="prompt_patch",
            status="pending",
            target_prompt_type="extraction",
            base_version_id="v1",
            section_id="task",
            operation_type="REFINE_RULE",
            operation_mode="replace_in_section",
            intent_name="test",
            intent_description="test",
            patch_text="new",
            rationale="contract test",
            old_text="old locator",
            source_sample_ids=["sample-1"],
        )
        repaired = Patch(
            id="repaired-1",
            type="prompt_patch",
            status="pending",
            target_prompt_type="extraction",
            base_version_id="v1",
            section_id="task",
            operation_type="REFINE_RULE",
            operation_mode="replace_in_section",
            intent_name="test",
            intent_description="test",
            patch_text="new",
            rationale="contract test",
            old_text="corrected locator",
            source_sample_ids=["sample-1"],
        )
        result = RepairResult(
            repaired=True,
            original_patch=original,
            repaired_patch=repaired,
            reason="locator corrected",
            strategy="fuzzy_alignment",
            candidate_count=2,
            metadata={"source": "contract-test"},
        )
        payload = result.to_dict()
        assert payload["repaired"] is True
        assert payload["original_patch_id"] == original.id
        assert payload["repaired_patch_id"] == repaired.id
        assert payload["reason"] == "locator corrected"
        assert payload["strategy"] == "fuzzy_alignment"
        assert payload["candidate_count"] == 2

    def test_failed_repair_result_has_none_repaired_patch_id(self) -> None:
        from mmap_optimizer.patch.repair import RepairResult
        from mmap_optimizer.patch.schema import Patch

        original = Patch(
            id="original-2",
            type="prompt_patch",
            status="pending",
            target_prompt_type="extraction",
            base_version_id="v1",
            section_id="task",
            operation_type="REFINE_RULE",
            operation_mode="replace_in_section",
            intent_name="test",
            intent_description="test",
            patch_text="new",
            rationale="contract test",
            old_text="unrecoverable locator",
            source_sample_ids=["sample-1"],
        )
        result = RepairResult(
            repaired=False,
            original_patch=original,
            repaired_patch=None,
            reason="no viable candidate",
            strategy="fuzzy_alignment",
            candidate_count=0,
        )
        payload = result.to_dict()
        assert payload["repaired"] is False
        assert payload["repaired_patch_id"] is None
        assert payload["reason"] == "no viable candidate"

    def test_patch_repair_result_backward_compat_schema(self) -> None:
        """PatchRepairResult (dict-based) must always serialize to dict."""
        from mmap_optimizer.patch.repair import PatchRepairResult

        result = PatchRepairResult(
            repaired_patch={"id": "r-1", "section_id": "task"},
            repaired=False,
            unresolved_fields=["old_text"],
            failure_reason="no match found",
        )
        # The object is a dataclass; verify the fields remain accessible so
        # downstream logging code does not silently break.
        assert result.repaired is False
        assert result.failure_reason == "no match found"
        assert "old_text" in result.unresolved_fields


# ---------------------------------------------------------------------------
# Merge ranking / compression helper contracts (#42–#44)
# ---------------------------------------------------------------------------


class TestMergeRankingContract:
    """Merge report schema must be stable and JSON-serializable."""

    def test_merge_report_is_json_serializable(self) -> None:
        from mmap_optimizer.patch.merge_report import PatchMergeReport

        report = PatchMergeReport(
            id="merge-1",
            round_id="round-0",
            input_patch_ids=["p-1", "p-2", "p-3"],
            cluster_count=2,
            clusters=[{"cluster_id": "c-1", "patch_ids": ["p-1", "p-2"]}],
            duplicate_patch_ids=["p-3"],
            subsumed_patch_ids=["p-2"],
            conflict_patch_ids=[],
            merged_patch_ids=["p-1-merged"],
            final_patch_ids=["p-1-merged"],
        )
        payload = json.loads(json.dumps(report.__dict__))
        assert payload["id"] == "merge-1"
        assert payload["round_id"] == "round-0"
        assert payload["input_patch_ids"] == ["p-1", "p-2", "p-3"]
        assert payload["cluster_count"] == 2

    def test_merge_report_defaults_are_sensible(self) -> None:
        from mmap_optimizer.patch.merge_report import PatchMergeReport

        minimal = PatchMergeReport(id="merge-2", round_id="round-1")
        assert minimal.cluster_count == 0
        assert minimal.input_patch_ids == []
        assert minimal.final_patch_ids == []


class TestCompressionHelperContract:
    """Compression helper primitives must be deterministic and safe."""

    def test_output_constraint_check_structure(self) -> None:
        from mmap_optimizer.compression.semantic import check_output_constraints

        text = "Line one.\nLine two.\nLine three."
        check = check_output_constraints(
            text,
            required_terms=["Line"],
            forbidden_terms=["toxic"],
            max_lines=5,
        )
        assert hasattr(check, "valid")
        assert hasattr(check, "violations")
        assert isinstance(check.violations, list)

    def test_output_constraint_check_rejects_forbidden_terms(self) -> None:
        from mmap_optimizer.compression.semantic import check_output_constraints

        text = "This contains the forbidden term."
        check = check_output_constraints(
            text,
            required_terms=None,
            forbidden_terms=["forbidden"],
        )
        assert check.valid is False
        assert any("forbidden" in v.lower() for v in check.violations)

    def test_output_constraint_check_respects_line_budget(self) -> None:
        from mmap_optimizer.compression.semantic import check_output_constraints

        text = "a\nb\nc\nd"
        check = check_output_constraints(text, max_lines=2)
        assert check.valid is False

    def test_compression_report_json_serializable(self) -> None:
        from mmap_optimizer.compression.report import CompressionReport

        report = CompressionReport(
            id="compression-1",
            round_id="round-0",
            prompt_type="extraction",
            prompt_version_before_id="prompt-v1",
            triggered=True,
            reason="line budget exceeded",
            candidate_sections=[{"section_id": "examples", "line_count": 20}],
            accepted=False,
            compression_patch_id=None,
            line_count_before=120,
            line_count_after=None,
            failure_reason="output constraint violated",
            validation_errors=[],
        )
        payload = json.loads(json.dumps(report.__dict__, ensure_ascii=False))
        assert payload["id"] == "compression-1"
        assert payload["triggered"] is True
        assert payload["accepted"] is False


# ---------------------------------------------------------------------------
# Section contribution metrics contracts (#41)
# ---------------------------------------------------------------------------


class TestSectionContributionJSONRoundTrip:
    def _records(self, section_id: str, correct: bool):
        return [
            {
                "sample_id": "s-1",
                "used_prompt_sections": [section_id],
                "primary_answer_correct": correct,
            }
        ]

    def test_compute_then_json_round_trip_preserves_section_id(self) -> None:
        baseline = self._records("rules", False)
        new = self._records("rules", True)
        deltas = compute_section_deltas(baseline, new)
        assert "rules" in deltas
        payload = json.loads(
            json.dumps(section_contributions_to_dict(deltas), sort_keys=True)
        )
        assert "rules" in payload
        assert payload["rules"]["section_id"] == "rules"
        assert payload["rules"]["improved_count"] >= 1

    def test_rank_does_not_mutate_input(self) -> None:
        baseline = self._records("rules", False) + self._records("examples", True)
        new = self._records("rules", True) + self._records("examples", True)
        deltas = compute_section_deltas(baseline, new)
        snapshot = {k: (v.delta, v.rank) for k, v in deltas.items()}
        rank_section_deltas(deltas)
        for key, value in deltas.items():
            assert (value.delta, value.rank) == snapshot[key]

    def test_rank_deterministic_on_ties(self) -> None:
        deltas = {
            "a": SectionContributionDelta(section_id="a"),
            "b": SectionContributionDelta(section_id="b"),
        }
        ranked = rank_section_deltas(deltas)
        assert [item.section_id for item in ranked] == ["a", "b"]
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2

    def test_json_artifact_is_writable(self, tmp_path: Path) -> None:
        from mmap_optimizer.metrics.section_deltas import (
            write_section_contribution_artifact,
        )

        baseline = self._records("rules", False)
        new = self._records("rules", True)
        deltas = compute_section_deltas(baseline, new)
        path = write_section_contribution_artifact(deltas, str(tmp_path))
        assert Path(path).exists()
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        assert payload["rules"]["sample_count"] == 1
        assert payload["rules"]["improved_count"] == 1


class TestSectionContributionInputFlexibility:
    """Records arrive either as objects or plain dicts; both should work."""

    def test_dict_inputs_produce_deltas(self) -> None:
        baseline = [
            {
                "sample_id": "s-1",
                "used_prompt_sections": ["rules"],
                "primary_answer_correct": False,
            }
        ]
        new = [
            {
                "sample_id": "s-1",
                "used_prompt_sections": ["rules"],
                "primary_answer_correct": True,
            }
        ]
        deltas = compute_section_deltas(baseline, new)
        assert deltas["rules"].delta > 0.0
        assert deltas["rules"].improved_count == 1

    def test_object_inputs_produce_deltas(self) -> None:
        from mmap_optimizer.evaluation.evaluator import EvaluationRecord

        baseline = [
            EvaluationRecord(
                id="eval-baseline-1",
                round_id="round-0",
                run_id="run-contract",
                sample_id="s-1",
                ground_truth_id="gt-1",
                parse_success=True,
                schema_valid=True,
                primary_answer_correct=False,
                overall_status="PASS",
                used_prompt_sections=["rules"],
            )
        ]
        new = [
            EvaluationRecord(
                id="eval-new-1",
                round_id="round-1",
                run_id="run-contract",
                sample_id="s-1",
                ground_truth_id="gt-1",
                parse_success=True,
                schema_valid=True,
                primary_answer_correct=True,
                overall_status="PASS",
                used_prompt_sections=["rules"],
            )
        ]
        deltas = compute_section_deltas(baseline, new)
        assert deltas["rules"].delta > 0.0
        assert deltas["rules"].improved_count == 1


# ---------------------------------------------------------------------------
# CLI smoke contract
# ---------------------------------------------------------------------------


class TestCLISmoke:
    """CLI entry points must not crash when invoked with basic flags."""

    def test_cli_module_is_importable(self) -> None:
        module = importlib.import_module("mmap_optimizer.cli.main")
        assert hasattr(module, "main")

    def test_cli_help_via_subprocess(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "mmap_optimizer.cli.main", "--help"],
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
            timeout=30,
        )
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert "usage" in result.stdout.lower()

    def test_cli_run_smoke_via_subprocess(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "smoke-run"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mmap_optimizer.cli.main",
                "run-smoke",
                "--rounds",
                "1",
                "--run-dir",
                str(run_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
            timeout=120,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_cli_run_smoke_resume_via_subprocess(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "smoke-resume"
        # First run
        first = subprocess.run(
            [
                sys.executable,
                "-m",
                "mmap_optimizer.cli.main",
                "run-smoke",
                "--rounds",
                "1",
                "--run-dir",
                str(run_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
            timeout=120,
        )
        assert first.returncode == 0, f"stdout={first.stdout}\nstderr={first.stderr}"

        # Resume
        resume = subprocess.run(
            [
                sys.executable,
                "-m",
                "mmap_optimizer.cli.main",
                "run-smoke",
                "--rounds",
                "1",
                "--run-dir",
                str(run_dir),
                "--resume",
            ],
            capture_output=True,
            text=True,
            cwd=str(Path.cwd()),
            timeout=120,
        )
        assert resume.returncode == 0, f"stdout={resume.stdout}\nstderr={resume.stderr}"
