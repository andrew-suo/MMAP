"""Patch 文本归一化工具。

提供 ``normalize_patch_text`` 函数，用于在冲突检测、去重等场景下
对 patch 文本进行归一化比较。
"""

from __future__ import annotations

import re

_TRAILING_PUNCT = "。.!！?？;；,，、"
_TRANSLATION = str.maketrans({"，": ",", "。": ".", "；": ";", "：": ":", "！": "!", "？": "?"})


def normalize_patch_text(text: str) -> str:
    normalized = text.strip().translate(_TRANSLATION)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(_TRAILING_PUNCT).strip().lower()
