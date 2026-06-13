"""Prompt standardization helpers."""

from __future__ import annotations

from .health import safe_autofix


def standardize_prompt(prompt: str, *, apply_safe_autofix: bool = True) -> str:
    """Standardize prompt formatting without changing business content."""

    if apply_safe_autofix:
        prompt = safe_autofix(prompt)
    return prompt
