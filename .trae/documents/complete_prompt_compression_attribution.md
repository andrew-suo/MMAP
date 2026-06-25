# 完成 Prompt 压缩 + Section 贡献度追踪实现

## Summary

上一轮会话已完成 prompt 压缩 + attribution 功能的 ~90% 实现（包括 prompt 文件、SectionContributionTracker、重写的 CompressionExecutor、config/factory 接线、extraction stage 集成）。本计划完成剩余工作：修复 analysis stage 中一个会导致 `TypeError` 的破损方法、适配两份已过期的测试文件、新增 SectionContributionTracker 与 LLM 压缩路径的单元测试，并运行全量测试验证。

## Current State Analysis

### 已完成（无需改动）
- `prompts/prompt_compression.txt` — 统一压缩 prompt（section + prompt 模式）
- `prompts/prompt_compression_validation.txt` — LLM 语义验证 prompt
- `mmap_optimizer/prompt/section_contribution.py` — SectionContributionTracker（EMA 追踪，118 行，完整实现）
- `mmap_optimizer/patch/types.py` — CompressionReport 已重构（新增 `validation_passed`/`validation_reasons`/`compressed_sections`，移除回归测试字段）
- `mmap_optimizer/executors/compression_executor.py` — 已重写：确定性预压缩 → Section 级 LLM 压缩（低贡献优先）→ Prompt 级 LLM 压缩 → LLM 验证；无 model_client 时仅确定性压缩并自动接受
- `mmap_optimizer/core/config.py` — PromptsConfig 新增 `prompt_compression`/`prompt_compression_validation`；PromptOptimizationConfig 新增 `ema_alpha`
- `mmap_optimizer/executors/factory.py` — 已传入新参数给 CompressionExecutor
- `mmap_optimizer/phases/prompt_optimization.py` — ema_alpha 已添加
- `mmap_optimizer/stages/extraction_prompt_optimization.py` — 已完成：contribution_tracker + _update_contribution_tracker + _step8 新签名
- `prompts/analysis.txt` — 归因分析已改为"所有情况"

### 待修复（Breaking Bug）
- **`mmap_optimizer/stages/analysis_prompt_optimization.py`** 第 649-662 行：`_step7_compress_if_needed` 仍使用旧 `compress_if_needed` 签名，传入了 `analysis_executor`/`extraction_prompt`/`extraction_results`/`pre_compression_analysis_results` 四个已不存在的参数，运行时会 `TypeError`。需改为新签名并传入 `contribution_tracker=self.contribution_tracker`。

### 待修复（Stale Tests，会报 TypeError）
- **`tests/test_pr4_compression_executor.py`** — 10 个测试函数全部使用旧签名（传入 `extraction_executor=`/`evaluation_executor=`/`pre_compression_eval_records=`），且断言引用了已删除的字段（`pre_compression_accuracy`/`post_compression_accuracy`/`broken_sample_ids`）。
- **`tests/test_pr4_acceptance.py`** — 第 133/161/248 行调用 `compress_if_needed` 使用旧签名；第 196-207/221-231 行构造 CompressionReport 使用已删除字段。

### 待新增（缺失测试）
- 无 SectionContributionTracker 单元测试（grep 全 tests/ 目录零匹配）。
- 无 LLM 压缩路径（section 级 / prompt 级 / 验证）测试。

## Proposed Changes

### 1. 修复 `mmap_optimizer/stages/analysis_prompt_optimization.py`

**文件**: `mmap_optimizer/stages/analysis_prompt_optimization.py`
**位置**: 第 635-683 行 `_step7_compress_if_needed` 方法
**改动**:
- 删除第 649 行 `pre_analysis = ...`（不再需要）
- 将 `compress_if_needed(...)` 调用（第 651-662 行）改为新签名：
  - 移除 `analysis_executor`/`extraction_prompt`/`extraction_results`/`pre_compression_analysis_results`
  - 新增 `contribution_tracker=self.contribution_tracker`
- **保留**第 670-681 行的压缩后重跑 analysis 逻辑（与 extraction stage `_step8` 第 825-837 行模式一致：executor 内部做 LLM 语义验证，stage 层重跑仅为报告 final_accuracy 指标）

**为什么**: 当前代码运行时会 `TypeError`，必须修复。保留重跑逻辑与 extraction stage 保持一致，final_accuracy 仍需真实评估。

**改后的方法签名调用**:
```python
compressed_prompt, report = self.compression_executor.compress_if_needed(
    prompt=prompt_to_compress,
    line_limit=line_limit,
    char_limit=char_limit,
    batch=self.batch,
    sample_set=self.sample_set,
    mode="analysis",
    contribution_tracker=self.contribution_tracker,
)
```

### 2. 重写 `tests/test_pr4_compression_executor.py`

**文件**: `tests/test_pr4_compression_executor.py`
**改动**: 完整重写，适配新接口。

**移除**:
- `PromptAwareExtractionExecutor` / `MockEvaluationExecutor` / `make_eval_records` 等 mock（压缩器不再做回归测试，不需要这些）
- 所有 `extraction_executor=`/`evaluation_executor=`/`pre_compression_eval_records=` 参数
- 所有对 `pre_compression_accuracy`/`post_compression_accuracy`/`broken_sample_ids` 的断言

**保留并适配的测试**:
1. `test_not_over_limit_no_compression` — 未超限时 triggered=False, rejected_reason="NOT_NEEDED"
2. `test_over_line_limit_triggers_compression` — 超行数限制触发压缩
3. `test_over_char_limit_triggers_compression` — 超字符限制触发压缩
4. `test_immutable_section_not_modified` — immutable section 不被修改（通过 `_verify_constraints` 产生的 warnings）
5. `test_compressed_prompt_can_render` — 压缩后 prompt 可正常 to_markdown()
6. `test_compression_report_fields_complete` — 验证新字段：`validation_passed`/`validation_reasons`/`compressed_sections`
7. `test_analysis_mode_compression` — analysis 模式压缩（无 model_client 时确定性压缩 + 自动接受）
8. `test_no_model_client_deterministic_only` — 无 model_client 时仅确定性压缩，still_over_limit 正确设置

**移除的测试**（基于回归测试语义，新设计已不支持）:
- `test_compression_accepted_when_accuracy_not_drop` — 改为 `test_deterministic_compression_accepted`
- `test_compression_rejected_when_accuracy_drops` — 改为 `test_constraint_violation_rejected`
- `test_no_executors_rejected` — 不再适用（新签名不需要 executors）

**新增的测试**（使用 mock model_client 测试 LLM 路径）:
- `test_llm_section_compression_with_tracker` — mock model_client 返回压缩文本，验证低贡献 section 优先压缩
- `test_llm_validation_pass` — mock model_client 验证返回 `{"valid": true}`，压缩被接受
- `test_llm_validation_fail` — mock model_client 验证返回 `{"valid": false}`，压缩被拒绝
- `test_section_contribution_tracker_update` — 测试 EMA 更新逻辑
- `test_section_contribution_tracker_priority_order` — 测试低贡献优先排序
- `test_section_contribution_tracker_serialization` — 测试 to_dict/from_dict 往返

### 3. 修复 `tests/test_pr4_acceptance.py`

**文件**: `tests/test_pr4_acceptance.py`
**改动**: 仅修复 compression 相关部分，不改动非压缩相关的验收测试。

- 第 133-142 行：移除 `extraction_executor=`/`evaluation_executor=`/`pre_compression_eval_records=`，新增 `contribution_tracker=None`
- 第 161-170 行：同上
- 第 248-257 行：同上
- 第 192-207 行：构造 CompressionReport 时移除 `base_accuracy`/`pre_compression_accuracy`/`post_compression_accuracy`/`broken_sample_ids`/`fixed_sample_ids`，改为新字段 `validation_passed=True`/`validation_reasons=[]`/`compressed_sections=[]`
- 第 219-231 行：同上，断言改为检查 `validation_passed` 而非 `post_compression_accuracy >= pre_compression_accuracy`

### 4. 运行测试验证

```bash
cd /Users/andrew/project/MMAP/MMAP && python -m pytest tests/ -v 2>&1 | tail -50
```

确保所有测试通过。若有失败，修复至全绿。

## Assumptions & Decisions

1. **保留 stage 层压缩后重跑**: analysis stage 在压缩接受后仍重跑 `analysis_executor.execute_batch` 获取 final_accuracy，与 extraction stage 模式一致。executor 内部的 LLM 验证确保语义等价，stage 重跑仅为指标报告。
2. **无 model_client 时自动接受**: compression_executor 第 188-194 行，无 model_client 时确定性压缩后自动 accepted=True（`validation_passed=True`, `validation_reasons=["deterministic only (no model_client)"]`）。测试基于此行为。
3. **测试中 mock model_client**: 用一个返回预设文本的 mock 对象测试 LLM 压缩/验证路径，避免真实 API 调用。
4. **不创建新测试文件**: 将 SectionContributionTracker 测试和 LLM 压缩测试统一放在 `test_pr4_compression_executor.py` 中（该文件本来就是压缩相关测试），避免文件膨胀。
5. **acceptance 测试最小改动**: 仅修复 compression 相关的签名和字段，不重构验收测试整体结构。

## Verification Steps

1. 修改完成后运行 `python -m pytest tests/ -v` 全量测试
2. 重点验证：
   - `test_pr4_compression_executor.py` 全部新测试通过
   - `test_pr4_acceptance.py` 压缩相关测试通过
   - `test_patch_new_system.py` 不受影响仍通过
   - 无 `TypeError` 或 `AttributeError`
3. 确认 analysis stage 的 `_step7_compress_if_needed` 可被 mock 模式调用不报错
