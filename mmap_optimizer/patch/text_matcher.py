"""Patch 文本匹配降级模块。

提供三级文本匹配降级方案：
1. 精确匹配（exact match）：直接检查 target_text/old_text 是否在 section.content 中
2. 模糊匹配（fuzzy match）：使用 difflib.SequenceMatcher 进行模糊匹配
3. LLM 匹配（LLM match）：调用大模型进行语义级文本定位

使用方式：
    from .text_matcher import match_text_with_fallback

    matched = match_text_with_fallback(
        section_content="原始 section 内容...",
        intent_text="待匹配的文本...",
        field_type="old_text",
        model_client=model_client,
        model_config=model_config,
        prompt_path="prompts/patch_text_match.txt",
    )
    if matched:
        # 使用 matched 替换 intent_text 进行后续操作
        ...
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def exact_match(section_content: str, intent_text: str) -> str | None:
    """精确匹配：检查 intent_text 是否为 section_content 的子串。

    Args:
        section_content: 目标 section 的实际内容。
        intent_text: 待匹配的文本。

    Returns:
        匹配到的原文（即 intent_text 本身），如果未匹配到返回 None。
    """
    if not intent_text or not section_content:
        return None
    if intent_text in section_content:
        return intent_text
    return None


def fuzzy_match(
    section_content: str,
    intent_text: str,
    threshold: float = 0.6,
    min_length: int = 5,
) -> str | None:
    """模糊匹配：使用 difflib 进行滑动窗口模糊匹配。

    在 section_content 中滑动截取与 intent_text 长度相近的子串，
    使用 SequenceMatcher 计算相似度，返回相似度最高的子串。

    Args:
        section_content: 目标 section 的实际内容。
        intent_text: 待匹配的文本。
        threshold: 相似度阈值，低于此值视为未匹配。
        min_length: intent_text 最小长度，短于此值不进行模糊匹配。

    Returns:
        匹配到的原文子串，如果未匹配到返回 None。
    """
    if not intent_text or not section_content:
        return None
    if len(intent_text) < min_length:
        return None

    intent_len = len(intent_text)
    content_len = len(section_content)

    # 滑动窗口范围：intent_text 长度的 0.5x ~ 2.0x
    min_window = max(1, int(intent_len * 0.5))
    max_window = min(content_len, int(intent_len * 2.0))

    best_match: str | None = None
    best_ratio: float = 0.0

    # 按不同窗口大小滑动
    for window_size in range(min_window, max_window + 1):
        if window_size > content_len:
            break
        step = max(1, window_size // 4)  # 步长为窗口大小的 1/4，减少计算量
        for start in range(0, content_len - window_size + 1, step):
            candidate = section_content[start:start + window_size]
            ratio = SequenceMatcher(None, intent_text, candidate).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = candidate

    if best_match is not None and best_ratio >= threshold:
        logger.debug(
            "fuzzy_match: ratio=%.3f, matched='%s...'",
            best_ratio,
            best_match[:50],
        )
        return best_match

    logger.debug("fuzzy_match: best_ratio=%.3f < threshold=%.3f", best_ratio, threshold)
    return None


def llm_match(
    section_content: str,
    intent_text: str,
    field_type: str,
    model_client: Any,
    model_config: Any,
    prompt_path: str,
) -> str | None:
    """LLM 匹配：调用大模型进行语义级文本定位。

    使用 patch_text_match.txt 模板，让 LLM 在 section_content 中
    找到与 intent_text 语义最对应的逐字原文。

    Args:
        section_content: 目标 section 的实际内容。
        intent_text: 待匹配的文本（可能是意译、缩写或模糊引用）。
        field_type: 字段类型（"old_text" 或 "target_text"）。
        model_client: 模型客户端实例。
        model_config: 模型配置。
        prompt_path: patch_text_match.txt 模板路径。

    Returns:
        LLM 返回的匹配原文（已验证为 section_content 的子串），
        如果 LLM 不可用或返回无效结果则返回 None。
    """
    if model_client is None:
        return None

    try:
        # 读取 prompt 模板
        template = Path(prompt_path).read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("llm_match: 无法读取 prompt 模板 %s: %s", prompt_path, exc)
        return None

    # 填充占位符
    system_prompt = template.format(
        section_content=section_content,
        intent_text=intent_text,
        field_type=field_type,
    )

    # 构建消息
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请输出匹配到的实际原文，或保持空白。"},
    ]

    # 调用 LLM
    try:
        response = model_client.complete(messages, model_config=model_config)
        raw_output = getattr(response, "raw_output", "").strip()
    except Exception as exc:
        logger.warning("llm_match: LLM 调用失败: %s", exc)
        return None

    # 熔断：LLM 返回空白
    if not raw_output:
        logger.debug("llm_match: LLM 触发熔断，返回空白")
        return None

    # 清理可能的 markdown 包裹
    if raw_output.startswith("```"):
        lines = raw_output.split("\n")
        raw_output = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    raw_output = raw_output.strip()

    # 验证：LLM 返回的文本必须是 section_content 的子串
    if raw_output in section_content:
        logger.debug("llm_match: 匹配成功 '%s...'", raw_output[:50])
        return raw_output

    # 如果不是精确子串，尝试去除首尾空白后再验证
    raw_output_trimmed = raw_output.strip()
    if raw_output_trimmed in section_content:
        return raw_output_trimmed

    logger.warning(
        "llm_match: LLM 返回的文本不是 section_content 的子串，拒绝使用"
    )
    return None


def match_text_with_fallback(
    section_content: str,
    intent_text: str,
    field_type: str = "old_text",
    model_client: Any = None,
    model_config: Any = None,
    prompt_path: str = "prompts/patch_text_match.txt",
    fuzzy_threshold: float = 0.6,
) -> str | None:
    """三级降级文本匹配入口。

    依次尝试：
    1. 精确匹配（exact_match）
    2. 模糊匹配（fuzzy_match，使用 difflib）
    3. LLM 匹配（llm_match，调用大模型）

    任一阶段匹配成功即返回，不再继续后续阶段。

    Args:
        section_content: 目标 section 的实际内容。
        intent_text: 待匹配的文本。
        field_type: 字段类型（"old_text" 或 "target_text"）。
        model_client: 模型客户端实例（可选）。
        model_config: 模型配置（可选）。
        prompt_path: LLM 匹配的 prompt 模板路径。
        fuzzy_threshold: 模糊匹配的相似度阈值。

    Returns:
        匹配到的原文子串，如果所有阶段都未匹配到则返回 None。
    """
    # Stage 1: 精确匹配
    matched = exact_match(section_content, intent_text)
    if matched is not None:
        logger.debug("match_text_with_fallback: exact_match 成功")
        return matched

    # Stage 2: 模糊匹配
    matched = fuzzy_match(section_content, intent_text, threshold=fuzzy_threshold)
    if matched is not None:
        logger.debug("match_text_with_fallback: fuzzy_match 成功")
        return matched

    # Stage 3: LLM 匹配
    if model_client is not None:
        matched = llm_match(
            section_content=section_content,
            intent_text=intent_text,
            field_type=field_type,
            model_client=model_client,
            model_config=model_config,
            prompt_path=prompt_path,
        )
        if matched is not None:
            logger.debug("match_text_with_fallback: llm_match 成功")
            return matched

    logger.debug("match_text_with_fallback: 所有阶段均未匹配成功")
    return None


__all__ = [
    "exact_match",
    "fuzzy_match",
    "llm_match",
    "match_text_with_fallback",
]
