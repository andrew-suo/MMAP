from __future__ import annotations

from tests._compat import candidate_modules, find_symbol

PROMPT_MODULES = candidate_modules(
    "mmap.prompt_health",
    "mmap.prompts.health",
    "mmap.health.prompt",
    "mmap_engine.prompt_health",
    "src.prompt_health",
)


def test_prompt_health_flags_missing_required_sections() -> None:
    check_health = find_symbol(PROMPT_MODULES, "check_prompt_health", "prompt_health_check")

    report = check_health("You are helpful. Return an answer.")

    assert report["healthy"] is False
    assert {issue["code"] for issue in report["issues"]} >= {"missing_output_schema", "missing_safety_bounds"}


def test_safe_autofix_adds_structure_without_rewriting_user_content() -> None:
    safe_autofix = find_symbol(PROMPT_MODULES, "safe_autofix_prompt", "autofix_prompt")
    source = "Task: Summarize the uploaded incident report. Keep the customer name ACME."

    fixed, report = safe_autofix(source)

    assert "ACME" in fixed
    assert "output" in fixed.lower()
    assert "safety" in fixed.lower() or "do not" in fixed.lower()
    assert report["safe"] is True
    assert report["changed"] is True
