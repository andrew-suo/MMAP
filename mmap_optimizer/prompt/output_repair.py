"""Output Repair 模块 - 模型输出修复功能。

当模型输出不能正常解析时（如 JSON 格式错误），调用模型进行结果修复。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..model.client import ModelClient


def repair_json_output(
    raw_output: str,
    expected_schema: dict[str, Any] | None,
    model_client: ModelClient,
    model_config: dict[str, Any] | None = None,
    repair_prompt_path: str = "prompts/output_repair.txt",
) -> tuple[dict[str, Any] | list[Any] | None, str]:
    """修复模型输出的 JSON 格式问题。

    当模型输出不能正常解析时（如 JSON 格式错误），调用模型进行结果修复。
    支持 JSON 对象（dict）和 JSON 数组（list）两种输出格式。

    Args:
        raw_output: 模型原始输出（格式可能有问题）
        expected_schema: 期望的 JSON Schema（可选），用于指导修复
        model_client: 模型客户端
        model_config: 模型配置（可选）
        repair_prompt_path: 修复 prompt 文件路径

    Returns:
        (修复后的 dict/list 或 None, 状态字符串)
        状态说明:
        - "repaired": 成功修复并解析
        - "reparse_failed": 模型输出仍无法解析
        - "unrepairable": 无法修复（如输出完全不是 JSON）
        - "skipped": 未尝试修复（model_client 为 None）
    """
    # 检查 model_client 是否可用
    if model_client is None:
        return None, "skipped"

    try:
        # 加载修复 prompt
        repair_prompt = Path(repair_prompt_path).read_text(encoding="utf-8")

        # 构建用户消息
        user_message = _build_repair_message(raw_output, expected_schema)

        # 构建完整消息
        messages = [
            {"role": "system", "content": repair_prompt},
            {"role": "user", "content": user_message},
        ]

        # 调用模型
        response = model_client.complete(messages, model_config=model_config)
        repaired_output = response.raw_output.strip()

        # 尝试解析修复后的输出
        return _parse_repaired_output(repaired_output)

    except Exception:
        # 任何异常都视为无法修复
        return None, "unrepairable"


def _build_repair_message(
    raw_output: str,
    expected_schema: dict[str, Any] | None,
) -> str:
    """构建修复请求消息。

    Args:
        raw_output: 原始输出
        expected_schema: 期望的 schema

    Returns:
        格式化的用户消息
    """
    lines = ["# Input Malformed Output", "", raw_output, ""]

    if expected_schema:
        lines.extend(["# Expected Schema", "", json.dumps(expected_schema, ensure_ascii=False, indent=2), ""])

    lines.extend(["# Your Task", "", "Repair the above malformed output to valid JSON format."])

    return "\n".join(lines)


def _parse_repaired_output(repaired_output: str) -> tuple[dict[str, Any] | list[Any] | None, str]:
    """解析修复后的输出。

    支持 JSON 对象（dict）和 JSON 数组（list）两种格式。

    Args:
        repaired_output: 修复后的原始输出字符串

    Returns:
        (解析后的 dict/list 或 None, 状态字符串)
    """
    # 移除可能的 markdown 代码块标记
    cleaned = _clean_markdown(repaired_output)

    # 尝试直接解析
    try:
        parsed = json.loads(cleaned)
        if parsed is None:
            return None, "unrepairable"
        if isinstance(parsed, (dict, list)):
            return parsed, "repaired"
        # 解析成功但不是 dict 或 list
        return None, "reparse_failed"
    except (json.JSONDecodeError, TypeError):
        pass

    # 尝试修复常见 JSON 问题后重新解析
    fixed = _fix_common_json_issues(cleaned)
    try:
        parsed = json.loads(fixed)
        if isinstance(parsed, (dict, list)):
            return parsed, "repaired"
        return None, "reparse_failed"
    except (json.JSONDecodeError, TypeError):
        pass

    # 根据文本中 [ 和 { 的先后顺序决定先尝试哪种提取
    bracket_pos = cleaned.find("[")
    brace_pos = cleaned.find("{")

    if brace_pos == -1 or (bracket_pos != -1 and bracket_pos < brace_pos):
        # [ 出现在 { 之前（或没有 {），优先提取 JSON 数组
        extracted_array = _extract_json_array(cleaned)
        if extracted_array is not None:
            try:
                parsed = json.loads(extracted_array)
                if isinstance(parsed, list):
                    return parsed, "repaired"
            except (json.JSONDecodeError, TypeError):
                pass
        # 数组提取失败，回退到对象提取
        extracted = _extract_json_object(cleaned)
        if extracted is not None:
            try:
                parsed = json.loads(extracted)
                if isinstance(parsed, dict):
                    return parsed, "repaired"
            except (json.JSONDecodeError, TypeError):
                pass
    else:
        # { 出现在 [ 之前（或没有 [），优先提取 JSON 对象
        extracted = _extract_json_object(cleaned)
        if extracted is not None:
            try:
                parsed = json.loads(extracted)
                if isinstance(parsed, dict):
                    return parsed, "repaired"
            except (json.JSONDecodeError, TypeError):
                pass
        # 对象提取失败，回退到数组提取
        extracted_array = _extract_json_array(cleaned)
        if extracted_array is not None:
            try:
                parsed = json.loads(extracted_array)
                if isinstance(parsed, list):
                    return parsed, "repaired"
            except (json.JSONDecodeError, TypeError):
                pass

    return None, "reparse_failed"


def _clean_markdown(text: str) -> str:
    """移除 markdown 代码块标记。

    Args:
        text: 输入文本

    Returns:
        清理后的文本
    """
    # 移除 ```json 和 ``` 包裹
    text = re.sub(r"^```json\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    # 移除 ``` 包裹
    text = re.sub(r"^```\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def _fix_common_json_issues(text: str) -> str:
    """修复常见的 JSON 问题。

    Args:
        text: 可能有问题 JSON 文本

    Returns:
        修复后的文本
    """
    result = text

    # 1. 将单引号替换为双引号（但不破坏已转义的双引号）
    # 简单策略：替换 'key': 或 'value' 形式
    result = re.sub(r"'([^']*)':", r'"\1":', result)  # key
    result = re.sub(r":\s*'([^']*)'", r': "\1"', result)  # string value

    # 2. 移除尾随逗号
    result = re.sub(r",\s*([\]}])", r"\1", result)

    # 3. 移除尾部多余逗号
    result = re.sub(r",\s*$", "", result)

    # 4. 修复 unquoted keys (如 {result: "OK"} → {"result": "OK"})
    # 匹配 key 不是以引号开头的情况
    result = re.sub(r'([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', result)

    return result


def _extract_json_object(text: str) -> str | None:
    """从文本中提取 JSON 对象。

    Args:
        text: 可能包含 JSON 的文本

    Returns:
        提取的 JSON 字符串，或 None
    """
    # 查找第一个 { 和最后一个 }
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or start >= end:
        return None

    return text[start : end + 1]


def _extract_json_array(text: str) -> str | None:
    """从文本中提取 JSON 数组。

    Args:
        text: 可能包含 JSON 数组的文本

    Returns:
        提取的 JSON 数组字符串，或 None
    """
    # 查找第一个 [ 和最后一个 ]
    start = text.find("[")
    end = text.rfind("]")

    if start == -1 or end == -1 or start >= end:
        return None

    return text[start : end + 1]


__all__ = ["repair_json_output"]
