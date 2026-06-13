"""Prompt refactoring helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .health import PromptHealthReport, check_prompt_health, safe_autofix


@dataclass(frozen=True)
class PromptRefactorResult:
    """Result of a conservative prompt refactor pass."""

    prompt: str
    health_report: PromptHealthReport


def refactor_prompt(prompt: str, *, safe: bool = True, baseline_prompt: str | None = None) -> PromptRefactorResult:
    """Run safe prompt refactor support and return a health report.

    Safe mode only applies health.safe_autofix, which is limited to structural
    marker normalization and never rewrites domain/business content.
    """

    updated = safe_autofix(prompt) if safe else prompt
    return PromptRefactorResult(updated, check_prompt_health(updated, baseline_prompt=baseline_prompt))
