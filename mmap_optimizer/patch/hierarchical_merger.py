from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.patch.merge_report import PatchMergeReport
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.semantic import _patch_from_dict, _patch_to_dict, _prompt_structure
from mmap_optimizer.prompt.ir import PromptIR
from mmap_optimizer.templates import build_default_template_registry
from mmap_optimizer.templates.schema import PromptTemplateSpec


# 操作类型分类：用于确定性冲突检测
_ADD_OPS = {"append", "merge_into_section", "insert_after", "insert_before"}
_DELETE_OPS = {"delete"}
_MODIFY_OPS = {"replace_in_section", "replace_section"}


# 分层合并模板字符串
_PATCH_HIERARCHICAL_MERGE_TEMPLATE = """# Role
你是 Prompt patch 分层合并专家，负责将同一分组内的多条 patch 合并为精简、无冲突的 patch 列表。

# Prompt Structure
{prompt_structure}

# Patches
{patches_json}

# 合并原则
- 同 section 同意图的 patch 必须合并为一条。
- 不同意图但同 section 的 patch 保留为独立条目。
- 不得新增输入中不存在的 patch 意图。
- 不得改变 patch 的 target_prompt_type 或 section_id 语义。
- 输出 patch 数量不得多于输入 patch 数量。
- 仅使用当前 patch schema 支持的 operation，不得发明新操作。

# 输出契约
仅输出 JSON 数组。每个元素为合并后的 patch 对象；失败时返回原 patch 数组。
"""

_PATCH_HIERARCHICAL_ROOT_MERGE_TEMPLATE = """# Role
你是 Prompt patch 根合并专家，负责对跨分组的残留 patch 执行最终全局合并与冲突消解。

# Prompt Structure
{prompt_structure}

# Patches
{patches_json}

# 根合并原则
- 检测跨 section 的逻辑冲突，保留证据更充分、范围更窄的 patch。
- 同意图跨 section 的 patch 可合并为一条；不同意图必须保留。
- 不得新增输入中不存在的 patch 意图。
- 不得改变 patch 的 target_prompt_type 或 section_id 语义。
- 输出 patch 数量不得多于输入 patch 数量。
- 仅使用当前 patch schema 支持的 operation，不得发明新操作。

# 输出契约
仅输出 JSON 数组。每个元素为合并后的 patch 对象；失败时返回原 patch 数组。
"""


def _contract(kind: str, **extra):
    """构建输出契约，复用 optimizer_prompts 中的逻辑。"""
    contract = {
        "type": kind,
        "required": extra.pop("required", []),
        "fields": extra.pop("fields", {}),
        "fallback": extra.pop("fallback", None),
    }
    contract.update(extra)
    return contract


# 分层合并专用模板注册表
_HIERARCHICAL_MERGE_TEMPLATES = [
    PromptTemplateSpec(
        id="patch_hierarchical_merge",
        version="1.0",
        purpose="Merge patches within a single hierarchical group.",
        input_variables=["prompt_structure", "patches_json"],
        output_contract=_contract("json_array", fallback="original patch array"),
        template=_PATCH_HIERARCHICAL_MERGE_TEMPLATE,
        risk_level="high",
        tags=["patch", "merge"],
    ),
    PromptTemplateSpec(
        id="patch_hierarchical_root_merge",
        version="1.0",
        purpose="Root merge residual patches across groups for final consolidation.",
        input_variables=["prompt_structure", "patches_json"],
        output_contract=_contract("json_array", fallback="original patch array"),
        template=_PATCH_HIERARCHICAL_ROOT_MERGE_TEMPLATE,
        risk_level="high",
        tags=["patch", "merge"],
    ),
]


@dataclass
class HierarchicalMergeConfig:
    """分层合并配置"""

    branch_factor: int = 8
    max_layers: int = 6
    fallback_threshold: float = 0.3
    max_retries: int = 2
    max_concurrency: int = 3


@dataclass
class MergeLayerReport:
    """单层合并报告"""

    layer: int
    input_count: int
    group_count: int
    merged_count: int
    passed_through_count: int
    failed_count: int
    failure_rate: float
    used_fallback: bool


@dataclass
class HierarchicalMergeResult:
    """分层合并最终结果"""

    final_patches: list[Patch]
    rejected_patches: list[Patch]
    merge_report: PatchMergeReport
    layer_count: int
    final_layer: int
    used_fallback: bool


def _normalize_text_for_match(text: str) -> str:
    """文本规范化：去除标点、合并空白、转小写"""
    if not text:
        return ""
    # 去除标点符号
    text = re.sub(r"[^\w\s]", "", text)
    # 合并连续空白
    text = re.sub(r"\s+", " ", text)
    # 转小写并去首尾空白
    return text.strip().lower()


def _ngrams(text: str, n: int) -> set[str]:
    """生成 n-gram 集合"""
    if not text:
        return set()
    if len(text) < n:
        return {text}
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def _texts_overlap(a: str, b: str, threshold: float = 0.5) -> bool:
    """检测两个文本是否重叠（子串包含 + 3-gram 重叠率）"""
    norm_a = _normalize_text_for_match(a)
    norm_b = _normalize_text_for_match(b)
    if not norm_a or not norm_b:
        return False
    # 子串包含检测
    if norm_a in norm_b or norm_b in norm_a:
        return True
    # 3-gram 重叠率检测
    grams_a = _ngrams(norm_a, 3)
    grams_b = _ngrams(norm_b, 3)
    if not grams_a or not grams_b:
        return False
    overlap = len(grams_a & grams_b)
    smaller = min(len(grams_a), len(grams_b))
    return (overlap / smaller) >= threshold


def deterministic_guardrail(
    patches: list[Patch],
    *,
    save_detention: bool = True,
) -> tuple[list[Patch], list[Patch]]:
    """
    确定性冲突检测，无需 LLM。
    返回: (kept_patches, detained_patches)

    Pass 1: ADD + DELETE 精确冲突
    - 构建 add_map: Dict[(section_id, normalized_content), List[patch_index]]
    - 对于同时存在 ADD_OP 和 DELETE_OP 的 key，标记全部为冲突

    Pass 2: replace_in_section old_text 重叠检测
    - 构建 replace_map: Dict[section_id, List[patch_index]]
    - 对同 section 内每对 replace_in_section patches，检测 old_text 是否 overlap
    - 冲突裁决：保留 rationale 更长的，丢弃另一个
    """
    detained_indices: set[int] = set()

    # Pass 1: ADD + DELETE 精确冲突
    add_map: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for i, patch in enumerate(patches):
        op = patch.effective_operation_mode
        if op in _ADD_OPS or op in _DELETE_OPS:
            key = (patch.section_id, _normalize_text_for_match(patch.patch_text))
            add_map[key].append((i, op))

    for entries in add_map.values():
        has_add = any(op in _ADD_OPS for _, op in entries)
        has_delete = any(op in _DELETE_OPS for _, op in entries)
        # 同一 key 同时存在 ADD 和 DELETE 操作，视为冲突
        if has_add and has_delete:
            for idx, _ in entries:
                detained_indices.add(idx)

    # Pass 2: replace_in_section old_text 重叠检测
    replace_map: dict[str, list[tuple[int, Patch]]] = defaultdict(list)
    for i, patch in enumerate(patches):
        if patch.effective_operation_mode in _MODIFY_OPS:
            replace_map[patch.section_id].append((i, patch))

    for entries in replace_map.values():
        for a in range(len(entries)):
            for b in range(a + 1, len(entries)):
                idx_a, patch_a = entries[a]
                idx_b, patch_b = entries[b]
                # 已被拘留的 patch 跳过
                if idx_a in detained_indices or idx_b in detained_indices:
                    continue
                old_text_a = patch_a.old_text or ""
                old_text_b = patch_b.old_text or ""
                if old_text_a and old_text_b and _texts_overlap(old_text_a, old_text_b):
                    # 冲突裁决：保留 rationale 更长的，丢弃另一个
                    if len(patch_a.rationale) >= len(patch_b.rationale):
                        detained_indices.add(idx_b)
                    else:
                        detained_indices.add(idx_a)

    kept = [patch for i, patch in enumerate(patches) if i not in detained_indices]
    detained = [patch for i, patch in enumerate(patches) if i in detained_indices]

    if save_detention:
        for patch in detained:
            patch.status = "rejected"
            patch.rejection_reason = "DETERMINISTIC_CONFLICT"

    return kept, detained


def _group_by_section(
    patches: list[Patch],
    branch_factor: int,
) -> list[list[Patch]]:
    """
    按 section 分组，每个分组不超过 branch_factor。
    单 section patches 不足 branch_factor 则单独成组。
    """
    buckets: dict[str, list[Patch]] = defaultdict(list)
    for patch in patches:
        # 无 section_id（空字符串）的 patch 归入 no_section bucket
        key = patch.section_id if patch.section_id else "__no_section__"
        buckets[key].append(patch)

    groups: list[list[Patch]] = []
    for bucket_patches in buckets.values():
        # 每个 bucket 按 branch_factor 拆分
        for i in range(0, len(bucket_patches), branch_factor):
            groups.append(bucket_patches[i:i + branch_factor])
    return groups


class HierarchicalPatchMerger:
    """多层递归 patch 合并器"""

    def __init__(
        self,
        *,
        model_client: ModelClient,
        model_config: dict[str, Any] | None = None,
        config: HierarchicalMergeConfig | None = None,
    ):
        self.model_client = model_client
        self.model_config = model_config or {}
        self.config = config or HierarchicalMergeConfig()
        self.registry = build_default_template_registry()
        # 注册分层合并专用模板
        for template in _HIERARCHICAL_MERGE_TEMPLATES:
            self.registry.register(template)

    def merge(
        self,
        *,
        round_id: str,
        patches: list[Patch],
        prompt_ir: PromptIR | None = None,
        prompt_structure: str | None = None,
    ) -> HierarchicalMergeResult:
        """多层递归合并主入口"""
        # 1. 如果 prompt_structure 未传入且 prompt_ir 可用，从 prompt_ir 生成
        if prompt_structure is None and prompt_ir is not None:
            prompt_structure = _prompt_structure(prompt_ir)
        elif prompt_structure is None:
            prompt_structure = ""

        # 2. 初始化 PatchMergeReport
        report = PatchMergeReport(
            id=f"patch_hierarchical_merge_{round_id}",
            round_id=round_id,
            input_patch_ids=[patch.id for patch in patches],
        )

        # 3. 执行 deterministic_guardrail，拘留冲突 patches
        kept_patches, detained_patches = deterministic_guardrail(patches, save_detention=True)
        rejected_patches = list(detained_patches)
        report.conflict_patch_ids = sorted({patch.id for patch in detained_patches})

        current_patches = kept_patches
        used_fallback = False
        layer_count = 0
        final_layer = 0

        # 4. 递归循环
        while len(current_patches) > 1 and layer_count < self.config.max_layers:
            layer_count += 1
            input_count = len(current_patches)

            # 4b. _group_by_section 分组
            groups = _group_by_section(current_patches, self.config.branch_factor)
            group_count = len(groups)

            # 4c. 并发执行 _merge_single_group
            merged_patches: list[Patch] = []
            failed_count = 0
            passed_through_count = 0

            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as executor:
                futures = {
                    executor.submit(
                        self._merge_single_group,
                        group,
                        prompt_structure,
                        "raw_patches",
                        max_retries=self.config.max_retries,
                    ): group
                    for group in groups
                }
                for future in as_completed(futures):
                    group = futures[future]
                    try:
                        merged, success = future.result()
                    except Exception:
                        merged, success = group, False
                    if success:
                        merged_patches.extend(merged)
                    else:
                        # 失败分组原样透传
                        merged_patches.extend(group)
                        passed_through_count += len(group)
                        failed_count += 1

            merged_count = len(merged_patches)

            # 4d. 统计失败率
            failure_rate = (failed_count / group_count) if group_count > 0 else 0.0

            # 记录层级报告到 merge_report.clusters
            layer_report = MergeLayerReport(
                layer=layer_count,
                input_count=input_count,
                group_count=group_count,
                merged_count=merged_count,
                passed_through_count=passed_through_count,
                failed_count=failed_count,
                failure_rate=failure_rate,
                used_fallback=False,
            )
            report.clusters.append({
                "layer": layer_report.layer,
                "input_count": layer_report.input_count,
                "group_count": layer_report.group_count,
                "merged_count": layer_report.merged_count,
                "passed_through_count": layer_report.passed_through_count,
                "failed_count": layer_report.failed_count,
                "failure_rate": layer_report.failure_rate,
                "used_fallback": layer_report.used_fallback,
            })

            # 4e. 如果失败率 > fallback_threshold，全局回退
            if failure_rate > self.config.fallback_threshold:
                used_fallback = True
                final_layer = layer_count
                # 回退到本层输入，不使用合并结果
                break

            # 4f. 如果合并后数量未减少，终止
            if merged_count >= input_count:
                final_layer = layer_count
                break

            current_patches = merged_patches
            final_layer = layer_count

        # 5. 执行 _root_merge（如果剩余 patches > 1）
        if len(current_patches) > 1:
            current_patches = self._root_merge(current_patches, prompt_structure)

        # 6. 返回 HierarchicalMergeResult
        report.final_patch_ids = [patch.id for patch in current_patches]

        return HierarchicalMergeResult(
            final_patches=current_patches,
            rejected_patches=rejected_patches,
            merge_report=report,
            layer_count=layer_count,
            final_layer=final_layer,
            used_fallback=used_fallback,
        )

    def _merge_single_group(
        self,
        patches: list[Patch],
        prompt_structure: str,
        input_type: str,
        *,
        max_retries: int = 2,
    ) -> tuple[list[Patch], bool]:
        """
        合并单个分组。
        返回: (merged_patches, success)
        """
        if not patches:
            return [], True
        if len(patches) == 1:
            return list(patches), True

        # 渲染 "patch_hierarchical_merge" 模板
        template = self.registry.get("patch_hierarchical_merge")
        patches_json = json.dumps(
            [_patch_to_dict(patch) for patch in patches],
            ensure_ascii=False,
            indent=2,
        )
        prompt = template.render(
            prompt_structure=prompt_structure,
            patches_json=patches_json,
        )

        # 根据 input_type 构造 user 消息
        if input_type == "json_patches":
            user_content = json.dumps(
                {"patches": [_patch_to_dict(patch) for patch in patches]},
                ensure_ascii=False,
            )
        else:
            user_content = json.dumps(
                [_patch_to_dict(patch) for patch in patches],
                ensure_ascii=False,
            )

        # 指数退避重试：wait_time = 2 ** attempt
        for attempt in range(max_retries + 1):
            try:
                # 调用 model_client.complete
                response = self.model_client.complete(
                    [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_content},
                    ],
                    model_config=self.model_config,
                    response_format=template.output_contract,
                )
                # 解析 JSON 数组
                payload = json.loads(response.raw_output)
                if not isinstance(payload, list):
                    raise ValueError("LLM 输出不是 JSON 数组")

                # 用 _patch_from_dict 重建 Patch
                fallback_patch = patches[0]
                result: list[Patch] = []
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    result.append(_patch_from_dict(item, fallback_patch))

                if not result:
                    # 空结果视为失败
                    raise ValueError("LLM 返回空数组")

                # 膨胀检测：如果 len(result) > len(input) 且 len(input) >= 2，视为失败
                if len(result) > len(patches) and len(patches) >= 2:
                    raise ValueError("合并结果膨胀")

                return result, True
            except Exception:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                # 失败时返回 (patches, False)
                return list(patches), False

        return list(patches), False

    def _root_merge(
        self,
        residual_patches: list[Patch],
        prompt_structure: str,
    ) -> list[Patch]:
        """执行最终根合并"""
        # 如果只有 1 个 patch，直接返回
        if len(residual_patches) <= 1:
            return list(residual_patches)

        try:
            # 渲染 "patch_hierarchical_root_merge" 模板
            template = self.registry.get("patch_hierarchical_root_merge")
            patches_json = json.dumps(
                [_patch_to_dict(patch) for patch in residual_patches],
                ensure_ascii=False,
                indent=2,
            )
            prompt = template.render(
                prompt_structure=prompt_structure,
                patches_json=patches_json,
            )
            # 调用 LLM
            response = self.model_client.complete(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps({"patches": [_patch_to_dict(patch) for patch in residual_patches]}, ensure_ascii=False)},
                ],
                model_config=self.model_config,
                response_format=template.output_contract,
            )
            # 解析 JSON 数组
            payload = json.loads(response.raw_output)
            if not isinstance(payload, list):
                return list(residual_patches)

            # 用 _patch_from_dict 重建
            fallback_patch = residual_patches[0]
            result: list[Patch] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                result.append(_patch_from_dict(item, fallback_patch))

            # 膨胀检测
            if len(result) > len(residual_patches):
                return list(residual_patches)

            return result or list(residual_patches)
        except Exception:
            return list(residual_patches)
