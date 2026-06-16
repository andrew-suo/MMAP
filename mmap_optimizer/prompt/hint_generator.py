"""Auto-generate section_id_hints from prompt headings using LLM.

When a scenario has no manual section_id_hints, this module can call an LLM
to analyze markdown headings and produce keyword → section_id mappings.  The
result is deterministic per heading set (same headings → same output) when
using the same model, and can be persisted to scenario.yaml to avoid repeated
LLM calls.
"""
from __future__ import annotations

import json
import re
from typing import Any

from mmap_optimizer.model.client import ModelClient

from .initializer import _GENERIC_SECTION_ID_HINTS, _GENERIC_ZH_KEYWORDS, _HEADING_RE

_AUTO_HINT_SYSTEM_PROMPT = """\
You are a section ID naming assistant for a prompt optimization framework.

Given a list of markdown heading titles, generate a mapping from Chinese \
keywords (extracted from the titles) to concise English snake_case section IDs.

Rules:
1. Extract the most distinctive keyword(s) from each title — the part that \
uniquely identifies the section's purpose.
2. Each keyword should be a short Chinese phrase (2-5 characters) that appears \
verbatim in the title.
3. The section_id must be English snake_case, concise (2-3 words), and \
semantically meaningful (e.g. "cable_check", "debris_inspection", "scene_validation").
4. If a title is purely structural (role, task, output format, etc.), skip it — \
those are already handled by generic hints.
5. Prefer longer keywords when they are more specific (e.g. "严重凌乱" over "凌乱").
6. Output ONLY a JSON object, no explanation. Example:
{"严重凌乱": "cable_check", "明显杂物": "debris_check"}
"""

_AUTO_HINT_USER_TEMPLATE = """\
Heading titles:
{titles}

Generate the keyword → section_id mapping as JSON:
"""


def _extract_headings(raw_prompt: str) -> list[str]:
    """Extract heading titles from raw markdown prompt."""
    return [m.group(2).strip() for m in _HEADING_RE.finditer(raw_prompt)]


def _headings_covered_by_generic(titles: list[str]) -> set[str]:
    """Return set of titles already matched by generic hints."""
    covered: set[str] = set()
    for title in titles:
        lowered = title.lower()
        # Check English generic hints
        for keyword in _GENERIC_SECTION_ID_HINTS:
            if keyword.lower() in lowered:
                covered.add(title)
                break
        if title in covered:
            continue
        # Check Chinese generic hints
        for keyword, _ in _GENERIC_ZH_KEYWORDS:
            if keyword in title:
                covered.add(title)
                break
    return covered


def auto_generate_hints(
    raw_prompt: str,
    model_client: ModelClient,
    *,
    model_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Auto-generate section_id_hints from prompt headings using LLM.

    Args:
        raw_prompt: Raw markdown prompt text with headings.
        model_client: LLM client to call for hint generation.
        model_config: Optional model configuration.

    Returns:
        Dictionary mapping Chinese keywords to English snake_case section IDs.
    """
    titles = _extract_headings(raw_prompt)
    if not titles:
        return {}

    # Filter out titles already covered by generic hints
    covered = _headings_covered_by_generic(titles)
    uncovered = [t for t in titles if t not in covered]
    if not uncovered:
        return {}

    titles_text = "\n".join(f"- {t}" for t in uncovered)
    messages = [
        {"role": "system", "content": _AUTO_HINT_SYSTEM_PROMPT},
        {"role": "user", "content": _AUTO_HINT_USER_TEMPLATE.format(titles=titles_text)},
    ]

    config = model_config or {}
    response = model_client.complete(messages, model_config=config)
    raw = response.raw_output.strip()

    # Extract JSON from response (handle markdown code fences)
    json_match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
    if not json_match:
        return {}

    try:
        hints = json.loads(json_match.group())
    except json.JSONDecodeError:
        return {}

    # Validate: keys must be non-empty strings, values must be valid snake_case
    valid_hints: dict[str, str] = {}
    for key, value in hints.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if not key.strip() or not value.strip():
            continue
        # Validate snake_case: lowercase letters, digits, underscores
        if re.match(r"^[a-z][a-z0-9_]*$", value):
            valid_hints[key.strip()] = value.strip()

    return valid_hints
