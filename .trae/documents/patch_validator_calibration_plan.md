# Patch Validator 校准能力增强计划

## Summary

借鉴用户提供的两个 Patch Translation Prompt，为 PatchValidator 增加定位文本校验和模型校准能力。合并两个 prompt 为一个 `prompts/patch_calibration.txt`，并在 PatchValidator 中集成校准流程：校验 → 校准失败的 patch → 重新校验。

## Current State Analysis

### 当前 PatchValidator 的问题

1. **不检查定位文本**：对 `insert_after`/`insert_before`/`replace_in_section` 操作，不检查 `target_text`/`old_text` 是否能在 section.content 中找到
2. **无修复机制**：校验失败直接 reject，不尝试校准
3. **问题后置**：定位文本匹配问题在 PatchApplyExecutor 应用时才暴露（第164、178、192行），导致 patch 被浪费

### 当前 PatchApplyExecutor 的问题

应用时才发现 `target_text`/`old_text` 找不到，直接拒绝，没有修复机制。

### 两个参考 Prompt 的差异分析

| 特性 | PATCH_TRANSLATION_PROMPT | PATCH_TRANSLATION_RETRY_PROMPT |
|------|--------------------------|-------------------------------|
| 场景 | 首次校准 | 二次重试 |
| 输入 | patches_json（数组） | failure_info + patch_json（单个） |
| 核心规则 | Section头部校准、定位文本校准、保护字段、无法匹配原样保留 | 范围锁定、逐字对齐、零幻觉熔断、Payload锁定 |
| 相同部分 | ~80% | ~80% |

**结论：合并为一个 prompt**，通过 `{failure_info}` 占位符区分首次/重试（空则为首次，有内容则为重试）。

## Proposed Changes

### 1. 新增 `prompts/patch_calibration.txt`

合并两个参考 prompt，吸收核心内容：
- Role: Patch 文本校准专家
- Inputs: prompt_structure、current_prompt、patches_json、failure_info（可选）
- Calibration Rules:
  - Section 头部校准（近似匹配 → 精确匹配）
  - 定位文本校准（在该 Section 内部检索最接近的原文，逐字逐标点）
  - 保护字段不可变（op、rationale、content/new_text/new_content）
  - 无法匹配时原样保留（零幻觉熔断）
  - 严禁丢弃任何 patch
- Output Format: JSON 数组

### 2. 修改 `mmap_optimizer/executors/patch_validator.py`

**增加定位文本校验**（纯代码，步骤 5.5）：
- 对 `insert_after`/`insert_before`：检查 `target_text` 是否在 section.content 中
- 对 `replace_in_section`：检查 `old_text` 是否在 section.content 中
- 匹配失败标记为 `TARGET_TEXT_NOT_FOUND` / `OLD_TEXT_NOT_FOUND`

**增加模型校准能力**（可选）：
- 构造函数增加参数：`model_client`、`model_config`、`calibration_prompt_path`
- 新增 `validate_batch_with_calibration` 方法：
  1. 常规 validate_batch 校验
  2. 对 rejected 中定位文本失败的 patch，调用模型校准
  3. 校准后重新校验
  4. 返回最终 validated/rejected
- 校准逻辑参考 `output_repair.py` 模式：
  - `_calibrate_patches`：构建消息 → 调用模型 → 解析输出 → 更新 patch 字段
  - 首次校准失败后，可进行一次重试（带 failure_info）

### 3. 修改 `mmap_optimizer/core/config.py`

- `PromptsConfig` 增加 `patch_calibration` 字段，默认 `prompts/patch_calibration.txt`
- `to_dict()` 和 `from_dict()` 方法更新

### 4. 修改 `mmap_optimizer/executors/factory.py`

- 读取 `patch_calibration` prompt 路径
- 传递 `model_client`、`model_config`、`calibration_prompt_path` 给 `PatchValidator`

### 5. 修改 `mmap_optimizer/core/cli.py`

- 增加 `--patch-calibration-prompt` 参数
- 在 `run_command` 中处理该参数（文件检查、配置更新）

### 6. 修改 stage 层调用（可选）

- 在 `extraction_prompt_optimization.py` 和 `analysis_prompt_optimization.py` 中
- 将 `validate_batch` 调用改为 `validate_batch_with_calibration`（当 model_client 可用时）

## Assumptions & Decisions

1. **合并为一个 prompt**：两个参考 prompt 80%+ 内容相同，通过 `{failure_info}` 区分首次/重试
2. **校准集成在 PatchValidator 中**：保持校验→校准→重新校验的流程在同一处，简化 stage 层调用
3. **校准是可选的**：当 model_client 不可用时，回退到纯校验模式（向后兼容）
4. **只校准定位文本失败的 patch**：其他原因（UNKNOWN_SECTION、IMMUTABLE_SECTION等）不校准
5. **校准最多重试一次**：首次校准 → 失败则带 failure_info 重试一次 → 仍失败则 reject

## Verification Steps

1. 运行 `python -m pytest tests/test_core.py -v` 确保现有测试通过
2. 验证 PatchValidator 新增的定位文本校验逻辑：
   - `insert_after` + `target_text` 不在 section 中 → reject `TARGET_TEXT_NOT_FOUND`
   - `replace_in_section` + `old_text` 不在 section 中 → reject `OLD_TEXT_NOT_FOUND`
3. 验证模型校准流程（mock model_client）：
   - 校验失败 → 校准 → 重新校验 → 通过
4. 验证向后兼容：model_client=None 时，行为与原来一致
