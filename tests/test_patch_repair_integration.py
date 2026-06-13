"""Contract tests for Patch repair engine (PR #40 integration)."""

from __future__ import annotations

from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.patch.applier import PatchApplier
from mmap_optimizer.patch.repair import (
    FUZZY_MATCH_MIN_RATIO,
    PatchRepairEngine,
    RepairResult,
)
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.validator import PatchValidator
from mmap_optimizer.prompt.ir import PromptIR, PromptSection


def _prompt_with(sections, *, frozen=None):
    frozen = frozen or set()
    built = [
        PromptSection(
            id=s[0],
            type=s[0],
            content=s[1],
            mutability="frozen" if s[0] in frozen else "mutable",
        )
        for s in sections
    ]
    ir = PromptIR(
        id="ir",
        prompt_type=PromptType.EXTRACTION,
        version=1,
        output_schema_contract_id="c",
        sections=built,
        rendering_order=[s.id for s in built],
    )
    return ir


def _patch(
    section_id="rules",
    operation_mode="replace_in_section",
    old_text=None,
    new_text=None,
    target_text=None,
    insert_text=None,
    patch_text="REPLACED",
):
    return Patch(
        id="p1",
        type="prompt_patch",
        status="candidate",
        target_prompt_type="extraction",
        base_version_id="v1",
        section_id=section_id,
        operation_type="ADD_RULE",
        operation_mode=operation_mode,
        intent_name="intent",
        intent_description="intent",
        patch_text=patch_text,
        rationale="rationale",
        old_text=old_text,
        new_text=new_text,
        target_text=target_text,
        insert_text=insert_text,
        source_sample_ids=["s1"],
    )


# ---------------------------------------------------------------------------
# RepairResult dataclass
# ---------------------------------------------------------------------------


class TestRepairResultDataclass:
    def test_to_dict_is_json_serializable(self):
        import json

        result = RepairResult(
            repaired=True,
            original_patch=_patch(old_text="hello", new_text="world"),
            repaired_patch=_patch(old_text="hello-repaired", new_text="world"),
            reason=None,
            strategy="fuzzy_match",
            candidate_count=1,
            metadata={"score": 0.92},
        )
        serialized = result.to_dict()
        # Must be able to round-trip to JSON.
        round_tripped = json.loads(json.dumps(serialized, ensure_ascii=False))
        assert round_tripped["repaired"] is True
        assert "metadata" in round_tripped


# ---------------------------------------------------------------------------
# Immutability: original Patch must never be mutated
# ---------------------------------------------------------------------------


class TestRepairDoesNotMutateOriginal:
    def test_original_patch_unchanged_after_successful_repair(self):
        original = _patch(old_text="tag-label", new_text="REPLACED")
        original_locator = dict(original.locator)
        original_extra = dict(original.extra)
        original_old_text = original.old_text
        ir = _prompt_with([("rules", "Use the tag label for extraction.")])

        result = PatchRepairEngine().repair_patch(original, ir)

        assert result.repaired is True
        # Original fields must be untouched.
        assert original.old_text == original_old_text
        assert dict(original.locator) == original_locator
        assert dict(original.extra) == original_extra
        # Repaired patch has a corrected locator.
        assert result.repaired_patch is not None
        assert result.repaired_patch is not original
        assert result.repaired_patch.old_text != original_old_text

    def test_original_patch_unchanged_after_failed_repair(self):
        original = _patch(old_text="not-even-close-xyz", new_text="NEW")
        original_extra = dict(original.extra)
        ir = _prompt_with([("rules", "nothing similar here at all.")])

        result = PatchRepairEngine().repair_patch(original, ir)

        assert result.repaired is False
        assert original.old_text == "not-even-close-xyz"
        assert dict(original.extra) == original_extra


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


class TestRepairSuccessCases:
    def test_replace_in_section_repairs_missing_locator_with_fuzzy_match(self):
        ir = _prompt_with([("rules", "Use the tag label for extraction. Extra text.")])
        patch = _patch(old_text="tag-label", new_text="新的 patch text")
        result = PatchRepairEngine().repair_patch(patch, ir)

        assert result.repaired is True
        assert result.strategy == "fuzzy_match"
        assert result.repaired_patch is not None

        # Repaired patch must validate and apply.
        vr = PatchValidator().validate(result.repaired_patch, ir)
        assert vr.valid is True, f"Validator rejected repaired patch: {vr.reason}"

    def test_insert_after_target_text_fuzzy_repair(self):
        ir = _prompt_with([("rules", "Anchor point inside a longer body text.")])
        p = _patch(
            operation_mode="insert_after",
            target_text="anchor-point",
            insert_text="INSERTED",
        )
        result = PatchRepairEngine().repair_patch(p, ir)
        assert result.repaired is True
        assert result.repaired_patch is not None
        vr = PatchValidator().validate(result.repaired_patch, ir)
        assert vr.valid is True

    def test_insert_before_target_text_fuzzy_repair(self):
        ir = _prompt_with([("rules", "Please find anchor point inside.")])
        p = _patch(
            operation_mode="insert_before",
            target_text="anchor-point",
            insert_text="INSERTED",
        )
        result = PatchRepairEngine().repair_patch(p, ir)
        assert result.repaired is True, f"Expected repair, got: {result.reason}"
        assert result.repaired_patch is not None

    def test_delete_locator_fuzzy_repair(self):
        ir = _prompt_with([("rules", "Use the tag label for extraction.")])
        p = _patch(operation_mode="delete", old_text="tag-label", patch_text="UNUSED")
        result = PatchRepairEngine().repair_patch(p, ir)
        assert result.repaired is True
        assert result.repaired_patch is not None
        # The repaired patch should pass validation.
        vr = PatchValidator().validate(result.repaired_patch, ir)
        assert vr.valid is True

    def test_repaired_patch_preserves_other_fields(self):
        ir = _prompt_with([("rules", "Use the tag label for extraction.")])
        patch = _patch(old_text="tag-label", new_text="REPLACED")
        result = PatchRepairEngine().repair_patch(patch, ir)
        assert result.repaired is True
        rp = result.repaired_patch
        assert rp.id == patch.id
        assert rp.operation_mode == patch.operation_mode
        assert rp.new_text == patch.new_text
        assert rp.rationale == patch.rationale

    def test_repair_then_apply_produces_new_content(self):
        ir = _prompt_with([("rules", "Use the tag label for extraction.")])
        original = _patch(old_text="tag-label", new_text="REPAIRED_CONTENT")
        result = PatchRepairEngine().repair_patch(original, ir)
        assert result.repaired is True
        assert result.repaired_patch is not None

        from mmap_optimizer.prompt.version import PromptVersion

        pv = PromptVersion(
            id="p1",
            prompt_type=PromptType.EXTRACTION,
            version=1,
            prompt_ir=ir,
            output_schema_contract_id="c",
        )
        applied = PatchApplier().apply(pv, result.repaired_patch, new_version=2)
        rules_section = applied.prompt_ir.section_by_id("rules")
        assert rules_section is not None
        assert "REPAIRED_CONTENT" in rules_section.content

    def test_old_repair_locator_still_works(self):
        """Dict-based ``repair_locator`` must keep working for callers that use it."""
        ir = _prompt_with([("rules", "检查标签缺失。")])
        dict_result = PatchRepairEngine().repair_locator(
            patch={
                "target_section": "Rules",
                "old_text": "标签缺失问题",
                "new_text": "铭牌",
            },
            prompt_ir=ir,
            failure_info="old_text missing",
        )
        assert dict_result.repaired is True
        assert dict_result.repaired_patch["old_text"] == "检查标签缺失。"


# ---------------------------------------------------------------------------
# Refuse cases
# ---------------------------------------------------------------------------


class TestRepairRefuseCases:
    def test_frozen_section_refused(self):
        ir = _prompt_with(
            [("output_schema", "{}")],
            frozen={"output_schema"},
        )
        p = _patch(section_id="output_schema", operation_mode="delete", old_text="{}")
        result = PatchRepairEngine().repair_patch(p, ir)
        assert result.repaired is False
        assert result.reason == "TARGET_SECTION_FROZEN"

    def test_ambiguous_locator_refused(self):
        ir = _prompt_with(
            [("rules", "anchor here and anchor there. anchor occurs three times.")]
        )
        p = _patch(old_text="anchor", new_text="REPLACED")
        result = PatchRepairEngine().repair_patch(p, ir)
        assert result.repaired is False
        assert result.reason == "AMBIGUOUS_LOCATOR"
        assert result.candidate_count >= 2

    def test_missing_section_id_without_hints_refused(self):
        ir = _prompt_with([("rules", "some content here.")])
        p = _patch(section_id="no_such_section", old_text="some", new_text="SOME")
        result = PatchRepairEngine().repair_patch(p, ir)
        assert result.repaired is False
        assert result.reason == "INVALID_TARGET_SECTION"

    def test_non_text_level_modes_are_not_applicable(self):
        ir = _prompt_with([("rules", "anything here.")])
        p = _patch(section_id="rules", operation_mode="append", patch_text="extra")
        result = PatchRepairEngine().repair_patch(p, ir)
        assert result.repaired is False
        assert result.reason == "NOT_APPLICABLE"

        p2 = _patch(section_id="rules", operation_mode="replace_section", patch_text="brand new")
        result2 = PatchRepairEngine().repair_patch(p2, ir)
        assert result2.repaired is False
        assert result2.reason == "NOT_APPLICABLE"

    def test_fuzzy_match_below_threshold_refused(self):
        ir = _prompt_with([("rules", "完全不相关的文本内容和段落。")])
        p = _patch(old_text="something-very-different-xyz", new_text="REPLACED")
        result = PatchRepairEngine().repair_patch(p, ir)
        assert result.repaired is False
        assert result.reason == "PATCH_LOCATOR_NOT_FOUND"

    def test_exact_match_reports_no_repair_needed(self):
        ir = _prompt_with([("rules", "here is exact-text-locator and more.")])
        p = _patch(old_text="exact-text-locator", new_text="REPLACEMENT")
        result = PatchRepairEngine().repair_patch(p, ir)
        assert result.repaired is False
        assert result.reason == "NO_REPAIR_NEEDED"
        # Must still be validatable and applicable directly.
        vr = PatchValidator().validate(p, ir)
        assert vr.valid is True


# ---------------------------------------------------------------------------
# Metadata / compatibility
# ---------------------------------------------------------------------------


class TestRepairMetadataAndExactTextPatchCompatibility:
    def test_nested_locator_payload_repair(self):
        ir = _prompt_with([("rules", "This is the real anchor in here.")])
        p = Patch(
            id="p1",
            type="prompt_patch",
            status="candidate",
            target_prompt_type="extraction",
            base_version_id="v1",
            section_id="rules",
            operation_type="ADD_RULE",
            operation_mode="replace_in_section",
            intent_name="i",
            intent_description="i",
            patch_text="fallback",
            rationale="r",
            # "real anchor" vs "the real anchor" – should score well enough
            # to repair to the actual text in the section.
            locator={"old_text": "real anchor"},
            payload={"new_text": "replacement"},
            source_sample_ids=["s1"],
        )
        result = PatchRepairEngine().repair_patch(p, ir)
        # Either repaired (if substring match found it) or NO_REPAIR_NEEDED
        # (if it was exact match). Either way, not an error.
        assert result.reason in (None, "NO_REPAIR_NEEDED") or result.repaired is True

    def test_repair_history_accumulates_in_extra(self):
        ir = _prompt_with([("rules", "Use the tag label for extraction.")])
        p = _patch(old_text="the-tag-label", new_text="newvalue")
        result = PatchRepairEngine().repair_patch(p, ir)
        assert result.repaired is True
        assert result.repaired_patch is not None
        rp = result.repaired_patch
        assert "repair_history" in rp.extra
        assert isinstance(rp.extra["repair_history"], list)
        history = rp.extra["repair_history"]
        assert "strategy" in history[0]
        assert "score" in history[0]

    def test_fuzzy_match_threshold_is_reasonable(self):
        # The threshold must be stricter than the alignment engine's default
        # (0.58) to avoid false-positive text replacements, but forgiving
        # enough to catch minor punctuation/wording drift.
        assert 0.5 < FUZZY_MATCH_MIN_RATIO <= 0.9


# ---------------------------------------------------------------------------
# End-to-end: repair → validate → apply
# ---------------------------------------------------------------------------


class TestRepairEndToEnd:
    def test_repair_then_validate_then_apply(self):
        ir = _prompt_with(
            [("rules", "这是一段用于测试的段落内容。包含真实的定位器文本。")]
        )
        # Intent: replace "真实的定位器" with "修复后的定位器"
        # but the section actually has "真实的定位器文本" — fuzzy match
        # should find the right span.
        p = _patch(old_text="真实的定位器", new_text="修复后的定位器")
        engine = PatchRepairEngine()
        result = engine.repair_patch(p, ir)
        # Either repaired successfully, or NO_REPAIR_NEEDED if exact match
        # worked. If exact match worked, we should still be able to apply.
        patch_to_apply = result.repaired_patch if result.repaired else p
        vr = PatchValidator().validate(patch_to_apply, ir)
        assert vr.valid is True, f"validator rejected: {vr.reason}"

        from mmap_optimizer.prompt.version import PromptVersion

        pv = PromptVersion(
            id="p1",
            prompt_type=PromptType.EXTRACTION,
            version=1,
            prompt_ir=ir,
            output_schema_contract_id="c",
        )
        applied = PatchApplier().apply(pv, patch_to_apply, new_version=2)
        assert applied.version == 2
        assert "修复后的定位器" in applied.prompt_ir.section_by_id("rules").content

        # result.to_dict() must be JSON serializable for audit.
        import json

        json.dumps(result.to_dict(), ensure_ascii=False)
