from __future__ import annotations

import pytest

from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.patch.applier import PatchApplier, PatchApplyError
from mmap_optimizer.patch.schema import TEXT_LEVEL_OPERATION_MODES, Patch
from mmap_optimizer.patch.validator import PatchValidator, PatchValidationError
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.ir import PromptIR, PromptSection
from mmap_optimizer.prompt.version import PromptVersion


def _contract():
    return OutputSchemaContract(id="c", prompt_type=PromptType.EXTRACTION, version=1, schema={}, primary_answer_fields=["result"])


def _prompt_with_sections(sections_content: dict[str, str], *, frozen: set[str] | None = None) -> PromptVersion:
    frozen = frozen or set()
    sections = [
        PromptSection(
            id=section_id,
            type=section_id if section_id != "output_schema" else "output_schema",
            content=content,
            mutability="frozen" if section_id in frozen else "mutable",
            compressibility="none" if section_id in frozen else "free",
        )
        for section_id, content in sections_content.items()
    ]
    ir = PromptIR(
        id="ir", prompt_type=PromptType.EXTRACTION, version=1,
        output_schema_contract_id="c", sections=sections,
        rendering_order=[s.id for s in sections],
    )
    return PromptVersion(id="p1", prompt_type=PromptType.EXTRACTION, version=1, prompt_ir=ir, output_schema_contract_id="c")


def _minimal_patch(**kwargs):
    defaults = {
        "id": "p1", "type": "prompt_patch", "status": "candidate",
        "target_prompt_type": "extraction", "base_version_id": "p1",
        "section_id": "rules", "operation_type": "ADD_RULE",
        "operation_mode": "replace_in_section",
        "intent_name": "intent", "intent_description": "intent",
        "patch_text": "fallback", "rationale": "r",
        "source_sample_ids": ["s1"],
    }
    defaults.update(kwargs)
    return Patch(**defaults)


class TestPatchSchemaBackwardCompatibility:
    def test_old_style_flat_fields_still_work(self):
        patch = _minimal_patch(old_text="A", new_text="AA", patch_text="ignored")
        assert patch.section_id == "rules"
        assert patch.operation_mode == "replace_in_section"
        assert patch.old_text == "A"
        assert patch.new_text == "AA"
        # New additive fields default to safe empty values
        assert patch.locator == {}
        assert patch.payload == {}
        assert patch.insert_text is None
        assert patch.insert_position is None

    def test_from_mapping_parses_flat_fields_without_new_keys(self):
        patch = Patch.from_mapping({
            "id": "x", "type": "prompt_patch", "status": "candidate",
            "target_prompt_type": "extraction", "base_version_id": "p1",
            "section_id": "rules", "operation_type": "ADD_RULE",
            "operation_mode": "append",
            "intent_name": "n", "intent_description": "d",
            "patch_text": "P", "rationale": "R",
        })
        assert patch.section_id == "rules"
        assert patch.patch_text == "P"
        assert patch.extra == {}
        assert patch.locator == {}
        assert patch.payload == {}

    def test_from_mapping_stores_unknown_keys_in_extra(self):
        patch = Patch.from_mapping({
            "id": "x", "type": "prompt_patch", "status": "candidate",
            "target_prompt_type": "extraction", "base_version_id": "p1",
            "section_id": "rules", "operation_type": "ADD_RULE",
            "operation_mode": "append",
            "intent_name": "n", "intent_description": "d",
            "patch_text": "P", "rationale": "R",
            "provenance": "gpt-4o",
            "score": 0.9,
        })
        assert patch.extra == {"provenance": "gpt-4o", "score": 0.9}

    def test_is_text_level_detects_text_operation_mode(self):
        assert _minimal_patch(operation_mode="replace_in_section").is_text_level() is True
        assert _minimal_patch(operation_mode="insert_after", target_text="X", patch_text="Y").is_text_level() is True
        assert _minimal_patch(operation_mode="delete", old_text="X", patch_text="X").is_text_level() is True
        assert _minimal_patch(operation_mode="append", patch_text="Y").is_text_level() is False
        assert _minimal_patch(operation_mode="replace_section", patch_text="Y").is_text_level() is False

    def test_effective_operation_mode_normalizes_insert_position(self):
        patch = _minimal_patch(operation_mode="insert", insert_position="before", target_text="X", patch_text="Y")
        assert patch.effective_operation_mode == "insert_before"
        patch2 = _minimal_patch(operation_mode="insert", insert_position="after", target_text="X", patch_text="Y")
        assert patch2.effective_operation_mode == "insert_after"
        # Without position hint stays as-is (falls to append behavior in applier)
        patch3 = _minimal_patch(operation_mode="insert", patch_text="Y")
        assert patch3.effective_operation_mode == "insert"

    def test_text_level_operation_modes_constant(self):
        assert "replace_in_section" in TEXT_LEVEL_OPERATION_MODES
        assert "insert_after" in TEXT_LEVEL_OPERATION_MODES
        assert "insert_before" in TEXT_LEVEL_OPERATION_MODES
        assert "delete" in TEXT_LEVEL_OPERATION_MODES


class TestLocatorAndPayloadFields:
    def test_locator_value_prefers_flat_over_nested(self):
        patch = _minimal_patch(old_text="flat", locator={"old_text": "nested"}, patch_text="X")
        assert patch.locator_value("old_text") == "flat"

    def test_locator_value_falls_back_to_nested(self):
        patch = _minimal_patch(operation_mode="replace_in_section", locator={"old_text": "nested"}, patch_text="X")
        assert patch.locator_value("old_text") == "nested"

    def test_payload_value_returns_first_match(self):
        patch = _minimal_patch(operation_mode="replace_in_section", new_text="AAA", payload={"new_text": "BBB"}, patch_text="X")
        assert patch.payload_value("new_text") == "AAA"
        # When flat field is None, nested payload wins
        patch2 = _minimal_patch(operation_mode="replace_in_section", payload={"new_text": "BBB"}, patch_text="X")
        patch2.new_text = None
        assert patch2.payload_value("new_text") == "BBB"

    def test_payload_value_returns_none_when_absent(self):
        patch = _minimal_patch(operation_mode="replace_in_section", patch_text="X")
        assert patch.payload_value("nonexistent_key", "another_missing_key") is None


class TestValidatorNewBehavior:
    def test_validator_rejects_missing_locator_for_replace(self):
        prompt = _prompt_with_sections({"rules": "alpha beta gamma", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(old_text="missing", new_text="replaced")
        result = PatchValidator().validate(patch, prompt.prompt_ir)
        assert result.valid is False
        assert result.reason == "PATCH_LOCATOR_NOT_FOUND"

    def test_validator_rejects_missing_locator_for_insert_after(self):
        prompt = _prompt_with_sections({"rules": "alpha beta gamma", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(operation_mode="insert_after", target_text="missing", patch_text="X")
        result = PatchValidator().validate(patch, prompt.prompt_ir)
        assert result.valid is False
        assert result.reason == "PATCH_LOCATOR_NOT_FOUND"

    def test_validator_rejects_ambiguous_locator(self):
        prompt = _prompt_with_sections({"rules": "A A A text\nB", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(old_text="A", new_text="AA")
        result = PatchValidator().validate(patch, prompt.prompt_ir)
        assert result.valid is False
        assert result.reason == "AMBIGUOUS_LOCATOR"

    def test_validator_rejects_frozen_section_for_delete(self):
        prompt = _prompt_with_sections({"rules": "A", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(section_id="output_schema", operation_mode="delete", old_text="{}", patch_text="")
        result = PatchValidator().validate(patch, prompt.prompt_ir)
        assert result.valid is False
        assert result.reason == "TARGET_SECTION_FROZEN"

    def test_validator_allows_delete_with_valid_locator(self):
        prompt = _prompt_with_sections({"rules": "keep delete-me keep", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(operation_mode="delete", old_text="delete-me ", patch_text="X")
        result = PatchValidator().validate(patch, prompt.prompt_ir)
        assert result.valid is True

    def test_patch_validation_error_exception_is_available(self):
        # The exception is part of the public API surface for callers that
        # want to raise on invalid patches (as opposed to returning a result).
        with pytest.raises(PatchValidationError, match="boom"):
            raise PatchValidationError("boom")


class TestApplierNewOperations:
    def test_replace_in_section_still_works_with_flat_fields(self):
        prompt = _prompt_with_sections({"rules": "A\nB", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(old_text="A", new_text="AA")
        updated = PatchApplier().apply(prompt, patch, new_version=2)
        assert updated.prompt_ir.section_by_id("rules").content == "AA\nB"

    def test_replace_in_section_rejects_when_locator_missing(self):
        prompt = _prompt_with_sections({"rules": "A\nB", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(old_text="Z", new_text="ZZ")
        with pytest.raises(PatchApplyError, match="not found"):
            PatchApplier().apply(prompt, patch, new_version=2)

    def test_replace_in_section_rejects_when_locator_ambiguous(self):
        prompt = _prompt_with_sections({"rules": "A A A\nB", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(old_text="A", new_text="AA")
        with pytest.raises(PatchApplyError, match="Ambiguous locator"):
            PatchApplier().apply(prompt, patch, new_version=2)

    def test_insert_after_uses_nested_payload_when_no_flat(self):
        prompt = _prompt_with_sections({"rules": "marker\nend", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(
            operation_mode="insert_after",
            target_text="marker",
            payload={"insert_text": "INSERTED"},
            patch_text="",
        )
        updated = PatchApplier().apply(prompt, patch, new_version=2)
        assert "INSERTED" in updated.prompt_ir.section_by_id("rules").content
        assert "marker" in updated.prompt_ir.section_by_id("rules").content

    def test_insert_before_with_nested_locator(self):
        prompt = _prompt_with_sections({"rules": "keep anchor keep", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(
            operation_mode="insert_before",
            locator={"target_text": "anchor"},
            payload={"insert_text": "INSERT"},
            patch_text="",
        )
        updated = PatchApplier().apply(prompt, patch, new_version=2)
        content = updated.prompt_ir.section_by_id("rules").content
        assert "INSERT" in content
        # Order check: INSERT should appear before anchor.
        assert content.index("INSERT") < content.index("anchor")

    def test_delete_operation_removes_locator(self):
        prompt = _prompt_with_sections({"rules": "keep remove-me keep", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(operation_mode="delete", old_text="remove-me ", patch_text="X")
        updated = PatchApplier().apply(prompt, patch, new_version=2)
        content = updated.prompt_ir.section_by_id("rules").content
        assert "remove-me" not in content
        assert "keep keep" in content

    def test_delete_rejects_when_locator_missing(self):
        prompt = _prompt_with_sections({"rules": "a b c", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(section_id="rules", operation_mode="delete", old_text="missing", patch_text="")
        with pytest.raises(PatchApplyError, match="not found"):
            PatchApplier().apply(prompt, patch, new_version=2)

    def test_append_still_works_for_backward_compat(self):
        prompt = _prompt_with_sections({"rules": "old", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(operation_mode="append", patch_text="new-line")
        updated = PatchApplier().apply(prompt, patch, new_version=2)
        content = updated.prompt_ir.section_by_id("rules").content
        assert "new-line" in content

    def test_replace_section_still_works_for_backward_compat(self):
        prompt = _prompt_with_sections({"rules": "old content", "output_schema": "{}"}, frozen={"output_schema"})
        patch = _minimal_patch(operation_mode="replace_section", patch_text="new content")
        updated = PatchApplier().apply(prompt, patch, new_version=2)
        assert updated.prompt_ir.section_by_id("rules").content == "new content"


class TestIntegrationWithRoundRunnerSanity:
    """Ensure patch changes do not break round runner behavior."""

    def test_round_runner_import_and_api_stable(self):
        from mmap_optimizer.core.config import OptimizerConfig
        from mmap_optimizer.evaluation.evaluator import Evaluator
        from mmap_optimizer.model.client import MockModelClient
        from mmap_optimizer.orchestration.round_runner import RoundRunner
        from mmap_optimizer.storage.json_store import JsonStore
        import tempfile, pathlib

        run_dir = pathlib.Path(tempfile.mkdtemp())
        store = JsonStore(run_dir)
        config = OptimizerConfig(batch_size=24, dynamic_validation_batch_size=0)
        runner = RoundRunner(model_client=MockModelClient(), evaluator=Evaluator(), store=store, config=config)
        assert hasattr(runner, "run_round")


class TestNoImpactOnCheckpointAndScenario:
    """Sanity check: patch changes should not affect checkpoint or scenario modules."""

    def test_checkpoint_save_and_load_unaffected(self):
        from mmap_optimizer.orchestration.checkpoint import OptimizerCheckpoint
        import pathlib, tempfile, json

        run_dir = pathlib.Path(tempfile.mkdtemp())
        cp = OptimizerCheckpoint(
            round_index=3,
            active_prompts={"extraction": {"id": "e1"}},
            sample_states=[{"sample_id": "s1"}],
            fewshot_pool_path=None,
            metrics_summary={"batch_accuracy": 0.9},
        )
        cp.save(run_dir / "checkpoint.json")
        loaded = OptimizerCheckpoint.load(run_dir / "checkpoint.json")
        assert loaded.round_index == 3
        assert loaded.metrics_summary["batch_accuracy"] == 0.9
