from __future__ import annotations

import re

from .schema import Patch

_TRAILING_PUNCT = "。.!！?？;；,，、"
_TRANSLATION = str.maketrans({"，": ",", "。": ".", "；": ";", "：": ":", "！": "!", "？": "?"})


def normalize_patch_text(text: str) -> str:
    normalized = text.strip().translate(_TRANSLATION)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(_TRAILING_PUNCT).strip().lower()


def is_duplicate_patch(a: Patch, b: Patch) -> bool:
    return _same_target(a, b) and normalize_patch_text(a.patch_text) == normalize_patch_text(b.patch_text)


def is_subsumed_patch(a: Patch, b: Patch) -> bool:
    if not _same_target(a, b):
        return False
    a_text = normalize_patch_text(a.patch_text)
    b_text = normalize_patch_text(b.patch_text)
    return bool(a_text and b_text and a_text != b_text and a_text in b_text)


def merge_trace(target: Patch, source: Patch) -> None:
    target.source_sample_ids = sorted({*target.source_sample_ids, *source.source_sample_ids})
    target.source_analysis_ids = sorted({*target.source_analysis_ids, *source.source_analysis_ids})
    target.possible_side_effects = sorted({*target.possible_side_effects, *source.possible_side_effects})
    absorbed = target.extra.setdefault("absorbed_patch_ids", [])
    if source.id not in absorbed:
        absorbed.append(source.id)


def _same_target(a: Patch, b: Patch) -> bool:
    return (
        a.target_prompt_type == b.target_prompt_type
        and a.section_id == b.section_id
        and a.operation_type == b.operation_type
    )
