"""基于 LLM 的并行 Patch 合并。

通过分层（layer）迭代的方式合并 patch 列表：
- L0 处理原始生成的 patch（raw_patches），侧重清洗与校准；
- L1+ 处理已合并的 JSON patch（json_patches），侧重逻辑去重与冲突消解。
每轮先经 ``deterministic_guardrail`` 确定性前筛，再按 section 分组后
使用 ``ThreadPoolExecutor`` 并行调用 LLM 合并。当失败率超过阈值时触发
全局回退，将所有剩余 patch 作为单个分组一次性合并。最后对多组结果执行
Root Merge 进行跨 section 一致性审查。
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .clusterer import categorize_by_section
from .conflict import deterministic_guardrail

logger = logging.getLogger(__name__)


class ParallelPatchMerger:
    """基于 LLM 的并行 Patch 合并器。

    通过分层（layer）迭代的方式合并 patch 列表：
    - L0 处理原始生成的 patch（raw_patches），侧重清洗与校准；
    - L1+ 处理已合并的 JSON patch（json_patches），侧重逻辑去重与冲突消解。
    每一轮先经 ``deterministic_guardrail`` 确定性前筛，再按 section 分组后
    使用 ``ThreadPoolExecutor`` 并行调用 LLM 合并。当失败率超过阈值时触发
    全局回退，将所有剩余 patch 作为单个分组一次性合并。最后对多组结果执行
    Root Merge 进行跨 section 一致性审查。
    """

    # input_type 对应的处理指引
    _INPUT_TYPE_INSTRUCTIONS = {
        "raw_patches": "输入为原始生成的 patch，可能包含格式不规范、定位字段模糊等问题。请先进行清洗和校准，再进行合并。",
        "json_patches": "输入为已经过初步合并的 JSON patch，格式规范。请直接进行逻辑去重和冲突消解。",
    }

    def __init__(
        self,
        model_client,          # ModelClient 实例或 None
        model_config,          # ModelConfig 实例或 None
        merge_prompt_path: str,    # prompts/patch_merge.txt 路径
        root_merge_prompt_path: str,  # prompts/patch_root_merge.txt 路径
        branch_factor: int = 8,
        max_layers: int = 10,
        max_retries: int = 2,
        fallback_threshold: float = 0.5,
    ):
        self.model_client = model_client
        self.model_config = model_config
        self.merge_prompt_path = merge_prompt_path
        self.root_merge_prompt_path = root_merge_prompt_path
        self.branch_factor = branch_factor
        self.max_layers = max_layers
        self.max_retries = max_retries
        self.fallback_threshold = fallback_threshold

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def merge(self, patches: list[dict], prompt_structure: str) -> list[dict]:
        """主入口：合并 patch 列表。

        流程：
        1. 如果 model_client 不可用，直接返回原 patches（passthrough）
        2. L0: 解析 + 分组 + 并行合并
        3. L1+: deterministic_guardrail → section_aware_grouping → 并行合并
        4. 终止条件检查（patch 数量不再减少 或 仅剩 1 个 或 达到 max_layers）
        5. Root Merge（如果有多组结果）
        """
        # 1. model_client 不可用时直接 passthrough
        if self.model_client is None:
            logger.info("model_client 不可用，直接返回原 patches（passthrough）")
            return list(patches)

        if not patches:
            return []

        current = list(patches)
        prev_count = len(current)

        # 2-4. 分层迭代合并
        for layer in range(self.max_layers):
            merged, failure_count = self._run_parallel_merge(current, prompt_structure, layer)

            logger.info(
                "Layer %d 完成: 输入=%d, 输出=%d, 失败分组=%d",
                layer, len(current), len(merged), failure_count,
            )

            # 终止条件：仅剩 1 个 patch
            if len(merged) <= 1:
                current = merged
                break
            # 终止条件：patch 数量不再减少（与上一轮相同或更多）
            if len(merged) >= prev_count:
                logger.info(
                    "Layer %d: patch 数量不再减少 (prev=%d, curr=%d)，终止合并",
                    layer, prev_count, len(merged),
                )
                current = merged
                break

            prev_count = len(current)
            current = merged
        else:
            logger.info("达到 max_layers=%d，终止合并", self.max_layers)

        # 5. Root Merge：如果有多组结果则进行跨 section 一致性审查
        if len(current) > 1:
            current = self._root_merge(current, prompt_structure)

        return current

    # ------------------------------------------------------------------
    # 单轮并行合并
    # ------------------------------------------------------------------

    def _run_parallel_merge(
        self, patches: list[dict], prompt_structure: str, layer: int
    ) -> tuple[list[dict], int]:
        """执行一轮并行合并。

        1. deterministic_guardrail 前筛
        2. categorize_by_section 分组
        3. groupable 组用 ThreadPoolExecutor 并行 LLM 合并
        4. single_pass 直接传递
        5. 合并结果
        6. 检查失败率，超过 fallback_threshold 则全局回退

        Returns: (merged_patches, failure_count)
        """
        # 1. 确定性前筛
        cleaned, guardrail_messages = deterministic_guardrail(patches)
        for msg in guardrail_messages:
            logger.info("deterministic_guardrail (layer=%d): %s", layer, msg)

        # 2. Section-Aware 分组
        groupable_groups, single_pass = categorize_by_section(cleaned, self.branch_factor)

        # 3. 并行 LLM 合并 groupable 组
        merged_results: list[dict] = []
        failure_count = 0

        if groupable_groups:
            max_workers = min(len(groupable_groups), 4)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_group = {
                    executor.submit(self._merge_single_group, group, prompt_structure, layer): group
                    for group in groupable_groups
                }
                for future in as_completed(future_to_group):
                    group = future_to_group[future]
                    try:
                        result = future.result()
                        merged_results.extend(result)
                    except Exception as exc:
                        failure_count += 1
                        logger.warning(
                            "分组合并失败 (layer=%d, group_size=%d): %s",
                            layer, len(group), exc,
                        )
                        # 回退：直接使用原始分组
                        merged_results.extend(group)

        # 4. single_pass 直接传递
        merged_results.extend(single_pass)

        # 5. 检查失败率，超过阈值则全局回退
        total_groups = len(groupable_groups)
        if total_groups > 0:
            failure_rate = failure_count / total_groups
            if failure_rate > self.fallback_threshold:
                logger.warning(
                    "Layer %d 失败率 %.2f 超过阈值 %.2f，执行全局回退",
                    layer, failure_rate, self.fallback_threshold,
                )
                try:
                    fallback_result = self._merge_single_group(
                        merged_results, prompt_structure, layer
                    )
                    return fallback_result, failure_count
                except Exception as exc:
                    logger.error("全局回退也失败: %s", exc)
                    return merged_results, failure_count

        return merged_results, failure_count

    # ------------------------------------------------------------------
    # 单分组合并
    # ------------------------------------------------------------------

    def _merge_single_group(
        self, group: list[dict], prompt_structure: str, layer: int
    ) -> list[dict]:
        """调用 LLM 合并单个分组。

        1. 读取 merge_prompt 模板
        2. 填充占位符：{prompt_structure}, {input_type}, {input_type_instruction}, {patches_content}
        3. input_type: layer 0 为 "raw_patches"，layer > 0 为 "json_patches"
        4. input_type_instruction: 根据 input_type 提供不同处理指引
        5. 调用 model_client.complete()
        6. 解析 JSON 输出
        7. 膨胀检测：如果 output > input，重试（指数退避）
        8. 返回合并后的 patches
        """
        if not group:
            return []

        # 1. 读取 merge_prompt 模板
        prompt_template = Path(self.merge_prompt_path).read_text(encoding="utf-8")

        # 2-4. 填充占位符
        input_type = "raw_patches" if layer == 0 else "json_patches"
        input_type_instruction = self._INPUT_TYPE_INSTRUCTIONS[input_type]
        patches_content = json.dumps(group, ensure_ascii=False, indent=2)

        system_prompt = prompt_template.format(
            prompt_structure=prompt_structure,
            input_type=input_type,
            input_type_instruction=input_type_instruction,
            patches_content=patches_content,
        )

        # 5-7. 调用 LLM + 解析 + 膨胀检测 + 重试
        input_count = len(group)
        last_parsed: list[dict] | None = None

        for attempt in range(self.max_retries + 1):
            # 5. 调用 LLM
            try:
                response = self._call_llm(
                    system_prompt,
                    "请按照上述指引合并补丁，直接输出 JSON 数组。",
                )
            except Exception as exc:
                logger.warning(
                    "Layer %d attempt %d: LLM 调用失败: %s", layer, attempt, exc
                )
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                continue

            # 6. 解析 JSON 输出
            parsed = self._parse_json_response(response)
            if parsed is None:
                logger.warning(
                    "Layer %d attempt %d: JSON 解析失败", layer, attempt
                )
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                continue

            # 7. 膨胀检测：output > input 则重试
            if len(parsed) > input_count:
                logger.warning(
                    "Layer %d attempt %d: 膨胀检测 output=%d > input=%d，重试",
                    layer, attempt, len(parsed), input_count,
                )
                last_parsed = parsed
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                continue

            # 成功：输出未膨胀
            return parsed

        # 8. 重试耗尽
        if last_parsed is not None:
            logger.warning(
                "Layer %d: 重试耗尽，使用最后一次输出（可能膨胀）", layer
            )
            return last_parsed

        # 完全失败：从未获得有效输出
        raise RuntimeError(
            f"Layer {layer}: 所有重试均失败，无有效 LLM 输出"
        )

    # ------------------------------------------------------------------
    # Root Merge
    # ------------------------------------------------------------------

    def _root_merge(self, patches: list[dict], prompt_structure: str) -> list[dict]:
        """跨 section 一致性审查。

        使用 root_merge_prompt 模板，调用 LLM 进行最终审查。
        """
        prompt_template = Path(self.root_merge_prompt_path).read_text(encoding="utf-8")
        patches_content = json.dumps(patches, ensure_ascii=False, indent=2)

        system_prompt = prompt_template.format(
            prompt_structure=prompt_structure,
            patches_content=patches_content,
        )

        try:
            response = self._call_llm(
                system_prompt,
                "请按照上述指引进行跨 section 一致性审查，直接输出 JSON 数组。",
            )
        except Exception as exc:
            logger.error("Root merge LLM 调用失败: %s", exc)
            return patches

        parsed = self._parse_json_response(response)
        if parsed is None:
            logger.warning("Root merge JSON 解析失败，返回原始 patches")
            return patches

        return parsed

    # ------------------------------------------------------------------
    # LLM 调用与 JSON 解析
    # ------------------------------------------------------------------

    def _call_llm(self, system_prompt: str, user_message: str) -> str:
        """调用 LLM 并返回原始响应文本。"""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        if user_message:
            messages.append({"role": "user", "content": user_message})

        response = self.model_client.complete(messages, model_config=self.model_config)
        return response.raw_output

    def _parse_json_response(self, response: str) -> list[dict] | None:
        """解析 LLM 的 JSON 响应，支持容错处理。

        依次尝试：
        1. 移除 markdown 标记后直接解析
        2. 修复常见 JSON 问题后解析
        3. 从文本中提取 JSON 数组后解析
        4. 从 dict 中提取 list 字段
        """
        # 1. 移除 markdown 标记
        cleaned = self._clean_markdown(response)

        # 直接解析
        parsed = self._try_parse_list(cleaned)
        if parsed is not None:
            return parsed

        # 2. 修复常见 JSON 问题
        fixed = self._fix_common_json_issues(cleaned)
        parsed = self._try_parse_list(fixed)
        if parsed is not None:
            return parsed

        # 3. 提取 JSON 数组
        extracted = self._extract_json_array(cleaned)
        if extracted is not None:
            parsed = self._try_parse_list(extracted)
            if parsed is not None:
                return parsed

        # 4. 尝试从 dict 中提取 list 字段（如 {"patches": [...]}）
        extracted_obj = self._extract_json_object(cleaned)
        if extracted_obj is not None:
            try:
                obj = json.loads(extracted_obj)
                if isinstance(obj, dict):
                    for value in obj.values():
                        if isinstance(value, list):
                            return value
            except (json.JSONDecodeError, TypeError):
                pass

        return None

    # ------------------------------------------------------------------
    # JSON 容错工具函数（参考 output_repair.py 模式）
    # ------------------------------------------------------------------

    @staticmethod
    def _try_parse_list(text: str) -> list[dict] | None:
        """尝试解析文本为 list[dict]，失败返回 None。"""
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(parsed, list):
            # 确保列表元素为 dict
            return [item for item in parsed if isinstance(item, dict)]
        return None

    @staticmethod
    def _clean_markdown(text: str) -> str:
        """移除 markdown 代码块标记。"""
        # 移除 ```json 和 ``` 包裹
        text = re.sub(r"^```json\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
        # 移除 ``` 包裹
        text = re.sub(r"^```\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
        return text.strip()

    @staticmethod
    def _fix_common_json_issues(text: str) -> str:
        """修复常见的 JSON 问题。"""
        result = text
        # 1. 将单引号替换为双引号
        result = re.sub(r"'([^']*)':", r'"\1":', result)  # key
        result = re.sub(r":\s*'([^']*)'", r': "\1"', result)  # string value
        # 2. 移除尾随逗号
        result = re.sub(r",\s*([\]}])", r"\1", result)
        # 3. 移除尾部多余逗号
        result = re.sub(r",\s*$", "", result)
        # 4. 修复 unquoted keys
        result = re.sub(r'([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', result)
        return result

    @staticmethod
    def _extract_json_array(text: str) -> str | None:
        """从文本中提取 JSON 数组。"""
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or start >= end:
            return None
        return text[start : end + 1]

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        """从文本中提取 JSON 对象。"""
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or start >= end:
            return None
        return text[start : end + 1]


__all__ = ["ParallelPatchMerger"]
