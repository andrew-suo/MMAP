from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.patch.alignment import PatchAlignmentEngine, match_verbatim_substring, resolve_section_reference
from mmap_optimizer.prompt.ir import PromptIR, PromptSection
from mmap_optimizer.templates import build_default_template_registry


def prompt_ir() -> PromptIR:
    return PromptIR(
        id="prompt_ir",
        prompt_type=PromptType.EXTRACTION,
        version=1,
        output_schema_contract_id="contract",
        sections=[
            PromptSection(id="quality_criteria", type="rules", name="## 4. Constraints & Rules", content="请检查设备标签是否缺失。\n请核对安装方向是否正确。"),
            PromptSection(id="output_schema", type="output_schema", name="## 5. Output Format", content='{"answer":"string"}', mutability="frozen"),
        ],
        rendering_order=["quality_criteria", "output_schema"],
    )


def test_default_template_registry_contains_alignment_and_compression_templates():
    registry = build_default_template_registry()

    assert "patch_translation" in registry.ids()
    assert "patch_semantic_merge" in registry.ids()
    assert "llm_prune_validation" in registry.ids()
    assert registry.get("patch_text_match").render(section_content="abc", intent_text="ab", field_type="old_text")
    assert not registry.get("json_fix").undeclared_placeholders()


def test_resolve_section_reference_accepts_fuzzy_markdown_header():
    section = resolve_section_reference(prompt_ir(), "Constraints Rules")

    assert section is not None
    assert section.id == "quality_criteria"


def test_match_verbatim_substring_returns_source_text_not_intent_text():
    source = "请检查设备标签是否缺失。\n请核对安装方向是否正确。"

    assert match_verbatim_substring(source, "检查标签缺失") == "请检查设备标签是否缺失。"


def test_patch_alignment_corrects_locator_fields_without_touching_payload():
    patch = {
        "op": "replace_in_section",
        "target_section": "Constraints Rules",
        "old_text": "检查标签缺失",
        "new_text": "检查标签、铭牌是否缺失",
        "reasoning": "保持原样",
    }

    result = PatchAlignmentEngine().align_patch_location(patch, prompt_ir())

    assert result.status == "aligned"
    assert result.aligned_patch["target_section"] == "## 4. Constraints & Rules"
    assert result.aligned_patch["old_text"] == "请检查设备标签是否缺失。"
    assert result.aligned_patch["new_text"] == "检查标签、铭牌是否缺失"
    assert result.aligned_patch["reasoning"] == "保持原样"


def test_patch_alignment_keeps_unmatched_text_for_manual_review():
    patch = {"target_section": "## 4. Constraints & Rules", "target_text": "完全不存在的定位文本", "content": "payload"}

    result = PatchAlignmentEngine().align_patch_location(patch, prompt_ir())

    assert result.status == "partial"
    assert result.aligned_patch["target_text"] == "完全不存在的定位文本"
    assert result.unresolved_fields == ["target_text"]


def test_enhanced_templates_include_generation_self_check_and_examples():
    registry = build_default_template_registry()

    assert "patch_generation" in registry.ids()
    assert "prompt_self_check" in registry.ids()
    assert registry.get("patch_semantic_merge").examples
    assert registry.get("patch_root_audit").examples
    assert registry.get("llm_prune_validation").output_contract["required"] == ["valid", "reason"]
    rendered = registry.get("patch_generation").render(
        prompt_structure="sections",
        current_prompt="prompt",
        round_context="context",
        evaluation_summary="summary",
    )
    assert "Be Specific" in rendered
    assert "append_to_section" in rendered


def test_alignment_reports_match_positions_and_unresolved_extra():
    patch = {"target_section": "## 4. Constraints & Rules", "old_text": "检查标签缺失", "new_text": "payload"}

    result = PatchAlignmentEngine().align_patch_location(patch, prompt_ir())

    assert result.match_details["old_text"]["start"] == 0
    assert result.match_details["old_text"]["end"] == len("请检查设备标签是否缺失。")
    assert result.match_details["old_text"]["score"] >= 0.58

    missing = PatchAlignmentEngine().align_patch_location(
        {"target_section": "## 4. Constraints & Rules", "old_text": "不存在"}, prompt_ir()
    )
    assert missing.aligned_patch["extra"]["unresolved_locators"] == ["old_text"]
