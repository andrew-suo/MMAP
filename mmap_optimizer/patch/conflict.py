"""Patch 冲突检测。

提供确定性前筛函数 ``deterministic_guardrail``：通过 ADD+DELETE 精确匹配与
``replace_in_section`` 的 n-gram 重叠检测，在合并前移除确定性冲突的 patch，
作用于 patch dict 列表。
"""

from __future__ import annotations

from .deduplicate import normalize_patch_text


# ---------------------------------------------------------------------------
# 确定性前筛：操作类型分类与工具函数
# ---------------------------------------------------------------------------

# ADD 操作：向 section 追加内容
ADD_OPERATIONS = {"append_to_section", "add_after_section"}
# DELETE 操作：删除 section 内容
DELETE_OPERATIONS = {"delete_section"}
# REPLACE 操作：替换 section 内文本
REPLACE_OPERATIONS = {"replace_in_section"}


def _ngrams(text: str, n: int) -> set[str]:
    """生成字符级 n-gram 集合。

    文本长度不足 n 时，将整段非空文本视作单个 gram，便于短文本之间的比较。
    """
    text = text.strip()
    if not text:
        return set()
    if len(text) <= n:
        return {text}
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def texts_overlap(text1: str, text2: str, ngram_n: int = 8, threshold: float = 0.5) -> bool:
    """n-gram 重叠判断函数。

    将两个文本分别生成 n-gram 集合，计算 Jaccard 相似度。
    相似度 > threshold 返回 True。
    """
    grams1 = _ngrams(text1, ngram_n)
    grams2 = _ngrams(text2, ngram_n)
    if not grams1 or not grams2:
        return False
    union = grams1 | grams2
    if not union:
        return False
    similarity = len(grams1 & grams2) / len(union)
    return similarity > threshold


def _section_id(patch: dict) -> str:
    """获取 patch 的目标 section，兼容 target_section / target_section_id / section_id 三种命名。"""
    return patch.get("target_section") or patch.get("target_section_id") or patch.get("section_id") or ""


def _patch_id(patch: dict) -> str:
    """获取 patch id，缺失时返回空字符串。"""
    return patch.get("id") or ""


def _operation(patch: dict) -> str:
    """获取 patch 的操作类型，兼容 op 与 operation_type 两种命名。"""
    return patch.get("op") or patch.get("operation_type") or ""


def _comparable_content(patch: dict) -> str:
    """获取 patch 用于冲突比较的内容文本。

    DELETE 操作优先取被删除内容（content / target_text / old_text），
    其余操作优先取新增内容（content / new_text）。
    """
    if _operation(patch) in DELETE_OPERATIONS:
        for key in ("content", "target_text", "old_text"):
            value = patch.get(key)
            if value:
                return str(value)
    else:
        for key in ("content", "new_text"):
            value = patch.get(key)
            if value:
                return str(value)
    return ""


def _old_text(patch: dict) -> str:
    """获取 replace_in_section patch 的待替换文本。"""
    for key in ("old_text", "target_text", "content"):
        value = patch.get(key)
        if value:
            return str(value)
    return ""


def _reasoning(patch: dict) -> str:
    """获取 patch 的 reasoning 文本，兼容 rationale 与 reasoning 两种命名。"""
    return patch.get("rationale") or patch.get("reasoning") or ""


def detect_add_delete_conflicts(patches: list[dict]) -> tuple[list[dict], list[str]]:
    """ADD+DELETE 精确冲突检测。

    构建 Map: (target_section, normalized_content) -> indices
    同时存在于 ADD (append_to_section/add_after_section) 和 DELETE (delete_section) 的 patch 被标记为冲突。
    冲突的 patch 从结果中移除。

    Returns: (cleaned_patches, conflict_messages)
    """
    # (section, normalized_content) -> [(index, category, patch_id)]
    bucket: dict[tuple[str, str], list[tuple[int, str, str]]] = {}
    for index, patch in enumerate(patches):
        operation = _operation(patch)
        if operation in ADD_OPERATIONS:
            category = "ADD"
        elif operation in DELETE_OPERATIONS:
            category = "DELETE"
        else:
            continue
        content = _comparable_content(patch)
        if not content:
            continue
        key = (_section_id(patch), normalize_patch_text(content))
        bucket.setdefault(key, []).append((index, category, _patch_id(patch)))

    # 同一 key 下同时出现 ADD 与 DELETE 即视为冲突，相关 patch 全部移除
    conflict_indices: set[int] = set()
    messages: list[str] = []
    for (section, _content), entries in bucket.items():
        categories = {category for _, category, _ in entries}
        if {"ADD", "DELETE"} <= categories:
            patch_ids = [patch_id for _, _, patch_id in entries]
            for index, _, _ in entries:
                conflict_indices.add(index)
            messages.append(
                f"ADD/DELETE conflict on section '{section}': patches {patch_ids} "
                f"operate on the same normalized content."
            )

    if not conflict_indices:
        return list(patches), []
    cleaned = [patch for index, patch in enumerate(patches) if index not in conflict_indices]
    return cleaned, messages


def detect_replace_overlaps(patches: list[dict], ngram_n: int = 8, threshold: float = 0.5) -> tuple[list[dict], list[str]]:
    """replace_in_section 重叠检测。

    同 section 内两两比较 old_text 的 n-gram 重叠率。
    重叠率 > threshold 的，保留 reasoning 较长的，删除另一个。

    Returns: (cleaned_patches, conflict_messages)
    """
    # 按 section 分组 replace_in_section patch
    groups: dict[str, list[tuple[int, dict]]] = {}
    for index, patch in enumerate(patches):
        if _operation(patch) in REPLACE_OPERATIONS:
            groups.setdefault(_section_id(patch), []).append((index, patch))

    to_delete: set[int] = set()
    messages: list[str] = []
    for section, members in groups.items():
        for i in range(len(members)):
            idx_i, patch_i = members[i]
            if idx_i in to_delete:
                continue
            old_i = normalize_patch_text(_old_text(patch_i))
            if not old_i:
                continue
            for j in range(i + 1, len(members)):
                idx_j, patch_j = members[j]
                if idx_j in to_delete:
                    continue
                old_j = normalize_patch_text(_old_text(patch_j))
                if not old_j:
                    continue
                if not texts_overlap(old_i, old_j, ngram_n=ngram_n, threshold=threshold):
                    continue
                # 发生重叠：保留 reasoning 较长的，删除另一个；长度相同则保留靠前的
                if len(_reasoning(patch_j)) > len(_reasoning(patch_i)):
                    to_delete.add(idx_i)
                    messages.append(
                        f"REPLACE overlap on section '{section}': patch "
                        f"{_patch_id(patch_i)} removed (overlaps with "
                        f"{_patch_id(patch_j)}, shorter reasoning)."
                    )
                    break  # patch_i 已被删除，无需再与后续 patch 比较
                else:
                    to_delete.add(idx_j)
                    messages.append(
                        f"REPLACE overlap on section '{section}': patch "
                        f"{_patch_id(patch_j)} removed (overlaps with "
                        f"{_patch_id(patch_i)}, shorter or equal reasoning)."
                    )

    if not to_delete:
        return list(patches), []
    cleaned = [patch for index, patch in enumerate(patches) if index not in to_delete]
    return cleaned, messages


def deterministic_guardrail(patches: list[dict], ngram_n: int = 8, ngram_threshold: float = 0.5) -> tuple[list[dict], list[str]]:
    """确定性前筛入口函数。

    依次执行：
    1. detect_add_delete_conflicts
    2. detect_replace_overlaps

    Returns: (cleaned_patches, all_conflict_messages)
    """
    all_messages: list[str] = []

    cleaned, messages = detect_add_delete_conflicts(patches)
    all_messages.extend(messages)

    cleaned, messages = detect_replace_overlaps(cleaned, ngram_n=ngram_n, threshold=ngram_threshold)
    all_messages.extend(messages)

    return cleaned, all_messages
