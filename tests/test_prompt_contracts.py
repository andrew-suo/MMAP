"""Prompt template contract tests for optimization prompts."""

from __future__ import annotations

from pathlib import Path
import pytest

from mmap_optimizer.prompt.prompt_manager import render_prompt


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def test_analysis_reflection_prompt_requires_evidence_and_memory_items():
    """analysis_reflection prompt should produce evidence-grounded reusable repairs."""
    prompt = _read_prompt("analysis_reflection.txt")

    assert '"evidence"' in prompt
    assert '"root_cause_items"' in prompt
    assert '"memory_items"' in prompt
    assert '"patch_suggestion"' in prompt
    assert "at most 3" in prompt
    assert "append_to_section" in prompt
    assert "extraction prompt failed" in prompt
    assert "analysis prompt" in prompt


def test_analysis_reflection_prompt_template_renders_with_json_schema():
    """analysis_reflection prompt should render despite literal JSON braces."""
    rendered = render_prompt(
        PROMPTS_DIR / "analysis_reflection.txt",
        sample_id="s1",
        raw_output='{"result":"WRONG"}',
        parsed_output={"result": "WRONG"},
        status="wrong",
        judgement={"judgement": {"is_correct": True}},
        analysis_correct=False,
        error_reason="misjudged",
        sample_input={"image": "sample.png"},
        ground_truth={"result": "OK"},
    )

    assert '"evidence"' in rendered
    assert '"patch_suggestion"' in rendered
    assert "{sample_id}" not in rendered


def test_patch_merge_prompt_requires_dedupe_conflict_and_independence_rules():
    """patch_merge prompt should enforce Trace2Skill-style merge coordination."""
    prompt = _read_prompt("patch_merge.txt")

    assert "Deduplicate" in prompt
    assert "Resolve conflicts" in prompt
    assert "Preserve unique insights" in prompt
    assert "Specific-to-general" in prompt
    assert "Enforce line independence" in prompt
    assert "append_to_section" in prompt
    assert "replace_in_section" in prompt


def test_patch_merge_prompt_template_renders_with_json_examples():
    """patch_merge prompt should render despite literal JSON example braces."""
    rendered = render_prompt(
        PROMPTS_DIR / "patch_merge.txt",
        prompt_structure="Task (id=section_1)",
        input_type="raw_patches",
        input_type_instruction="merge raw patches",
        patches_content="[]",
    )

    assert "Task (id=section_1)" in rendered
    assert '"op": "append_to_section"' in rendered
    assert "{prompt_structure}" not in rendered


def test_render_prompt_raises_clear_error_for_missing_variable():
    with pytest.raises(KeyError, match="missing variables"):
        render_prompt(PROMPTS_DIR / "patch_generation.txt", sample_id="s1")


def test_patch_calibration_prompt_only_allows_location_field_changes():
    """patch_calibration prompt should protect payload fields while fixing locations."""
    prompt = _read_prompt("patch_calibration.txt")

    for allowed_field in ("target_section", "target_text", "old_text"):
        assert f"`{allowed_field}`" in prompt

    for protected_field in (
        "op",
        "content",
        "new_text",
        "new_content",
        "reasoning",
        "rationale",
        "new_header",
        "source_sample_ids",
        "metadata",
    ):
        assert f"`{protected_field}`" in prompt

    assert "保持该 patch 原样" in prompt
    assert "严禁跨 section 匹配" in prompt
    assert "输入多少条 patch，输出必须包含多少条 patch" in prompt
    assert "{prompt_structure}" not in prompt
    assert "# Prompt Structure" in prompt
