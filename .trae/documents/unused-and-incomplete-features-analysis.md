# 未使用代码与半成品功能分析计划

## 摘要

通过对 mmap_optimizer 全代码库的系统性静态分析（3 个搜索 agent 并行 + 关键文件人工验证），发现项目存在大量"定义了但未使用"的代码和"实现了一半"的功能。这些问题可分为四大类：**完全未接入主流程的模块**、**功能链路断裂（配置/参数/字段失效）**、**只写不读的持久化文件**、**未使用的枚举/字段/常量**。

本计划的目标是**梳理清单并制定处理策略**，而非立即全部删除——部分"未集成"模块可能是设计预留，需要区分"该删除的死代码"和"该补全的半成品功能"。

---

## 一、完全未接入主流程的模块（6 个）

这些模块在 `mmap_optimizer/` 主代码库内**无任何 import**，仅在 `tests/` 中被引用。

| # | 模块路径 | 行数 | 说明 | 处理建议 |
|---|---------|------|------|---------|
| 1 | `patch/merge_ranking.py` | ~380 | docstring 自述 DEPRECATED，默认合并用 TreeReducePatchMerger | **删除** — 已有替代品 tree_reduce.py |
| 2 | `sampling/risk_signals.py` | ~150 | 风险感知采样，读取 SampleState 字段做风险评分 | **保留+集成** 或 **删除** — 取决于是否计划集成风险感知采样 |
| 3 | `compression/risk_aware.py` | ~200 | 风险感知压缩决策，docstring 自述 "intentionally decoupled" | **删除** — 设计上就不打算集成 |
| 4 | `metrics/section_deltas.py` | ~100 | section 贡献 delta 报告，docstring 自述 "reporting helper" | **保留** — 可作为 CLI 报告工具 |
| 5 | `orchestration/llm_records.py` | ~200 | LLM 步骤记录器，写 llm_steps.jsonl | **集成** 或 **删除** — 审计价值高但无人调用 |
| 6 | `prompt/ab_test.py` | ~80 | Prompt A/B 测试工具 | **保留** — 可作为 CLI 工具 |

### 完全孤立的类（连 tests 都不使用）

| # | 文件路径 | 类/函数 | 处理建议 |
|---|---------|--------|---------|
| 7 | `patch/merger.py` | `PatchMerger` 类 | **删除** — 已被 tree_reduce.py 替代 |
| 8 | `patch/hierarchical_merge.py` | `HierarchicalPatchMerger`、`hierarchical_merge` | **删除** — 未被任何代码导入 |

---

## 二、功能链路断裂（配置/参数/字段失效）

### 2.1 配置启用了但代码不读取（3 项）

| # | 配置字段 | 文件:行 | 问题 | 处理建议 |
|---|---------|--------|------|---------|
| 1 | `patch_repair_max_attempts` | `core/config.py:52` | `PatchRepairEngine` 不接受此参数，修复永远只跑 1 次，`repair_attempts` 硬编码为 1 | **补全** — 传入参数并实现重试循环 |
| 2 | `extraction_token_budget` | `core/config.py:40` | `compress_if_needed` 接受 `token_budget` 参数但 round_runner 调用时未传 | **补全** — 调用时传入 `token_budget=self.config.extraction_token_budget` |
| 3 | `analysis_token_budget` | `core/config.py:41` | 同上，`compress_analysis_if_needed` 调用时未传 | **补全** — 同上 |

### 2.2 参数传入了但接收方不使用（2 项）

| # | 参数 | 文件:行 | 问题 | 处理建议 |
|---|------|--------|------|---------|
| 1 | `SemanticCompressionEngine.max_validation_retries` | `compression/semantic.py:40,43` | 构造函数存储了该参数，但 `prune_section` 和 `validate_prune` 从不引用它 | **删除参数** — 上次修复已移除重试循环，参数应一并删除 |
| 2 | `DebugEventLogger.log()` 的 `stage`/`round_id`/`payload` 参数 | `debug/logger.py:36` | `_debug` 方法把 kwargs dict 当作 `message` 传入，导致这三个参数永远为默认空值 | **补全** — 修复 `_debug` 方法正确传参 |

### 2.3 字段填充了但下游不读取（重点项）

| # | 字段 | 文件:行 | 问题 | 处理建议 |
|---|------|--------|------|---------|
| 1 | `PatchTestResult.format_error_count` | `testing/patch_tester.py:29` | **从未赋值也从未读取**，纯死字段 | **删除** |
| 2 | `PatchTestResult.unchanged_wrong_sample_ids` | `testing/patch_tester.py:26` | 填充但下游从不读取 | **保留** — 审计价值，可未来用于分析 |
| 3 | `PatchTestResult.unchanged_correct_sample_ids` | `testing/patch_tester.py:27` | 同上 | **保留** |
| 4 | `RunState.active_extraction_prompt_id` | `orchestration/run_state.py:14` | 从未赋值也从未读取（RunStateStore.load 从不被调用） | **删除** RunState 整个持久化链路 |
| 5 | `RunState.active_analysis_prompt_id` | `orchestration/run_state.py:15` | 同上 | 同上 |
| 6 | `RunState.metadata` | `orchestration/run_state.py:17` | 同上 | 同上 |
| 7 | `CompressionReport` 5 个字段 | `compression/report.py:29,30,33,34,35` | `canary_broken_count`、`historical_fixed_regression_count`、`semantic_retry_count`、`validation_errors`、`output_constraint_violations` 从未赋值 | **删除** |
| 8 | `AnalysisRecord.schema_violation_patch_count` | `analysis/record.py:27` | 从未赋值也从未读取 | **删除** |
| 9 | `AnalysisRecord.frozen_target_patch_count` | `analysis/record.py:28` | 同上 | **删除** |
| 10 | `RunRecord.retry_count` | `orchestration/records.py:40` | 从未赋值，永远为 0 | **删除** |
| 11 | `SectionContribution.cited_count` 恒为 0 | `metrics/section_contribution.py:50` | `getattr(record, "prompt_section_attribution", [])` 读取的字段在 `AnalysisRecord` 上不存在 | **补全** — 在 AnalysisRecord 中添加字段并从 parser 填充 |

---

## 三、只写不读的持久化文件

### 3.1 intermediate 文件（6 个 stage）

- **文件**: `orchestration/round_runner.py:637-643`
- **问题**: `_save_intermediate` 写入 6 个 stage 文件，docstring 自承 "Stage 2 (loading intermediate files on resume) is not yet implemented"，且 round 成功后立即被 `_cleanup_intermediate` 删除
- **处理建议**: **补全 Stage 2** 或 **降级为纯调试日志** — 如果不打算实现 crash recovery，应删除整个 intermediate 机制

### 3.2 run_state.json（孤儿文件）

- **文件**: `orchestration/run_state.py` + `orchestration/optimizer_loop.py`
- **问题**: `RunStateStore.save()` 调用 4 次，`RunStateStore.load()` 调用 0 次；resume 逻辑实际依赖 `checkpoint.json`
- **处理建议**: **删除** RunStateStore 整个持久化链路 — 已被 OptimizerCheckpoint 取代

### 3.3 resume 逻辑只恢复 round_index

- **文件**: `orchestration/optimizer_loop.py:62-70`
- **问题**: `OptimizerCheckpoint` 持久化了 `active_prompts`、`sample_states`、`fewshot_pool_path`、`metrics_summary`，但 resume 只读取 `round_index`
- **处理建议**: **补全** — resume 时恢复 active_prompts 和 sample_states

### 3.4 round 级产物文件（16 类）

- **文件**: `orchestration/round_runner.py:520-540`
- **问题**: `round.json`、`round_metrics.json`、`merge_report.json`、6 个 `runs/*.jsonl`、`evaluation_records.jsonl`、`patch_test_results.jsonl` 等在主代码库内无任何读回路径
- **处理建议**: **保留** — 这些是审计产物，供 CLI 工具和人工检查使用，不需要被代码读回

---

## 四、未使用的枚举值/常量

| # | 枚举/常量 | 文件:行 | 处理建议 |
|---|----------|--------|---------|
| 1 | `PromptVersionType.ANALYSIS_SHADOW_PROMOTION` | `core/enums.py:15` | **保留** — 已标注 Reserved，analysis evolution 有部分实现 |
| 2 | `PromptVersionType.MANUAL` | `core/enums.py:17` | **保留** — 已标注 Reserved |
| 3 | `PatchStatus` 枚举全部 9 个成员 | `core/enums.py:20-29` | **保留** — 上次已添加字符串常量别名，枚举本身作为类型文档 |
| 4 | `PATCH_STATUS_*` 9 个字符串常量 | `core/enums.py:52-60` | **保留** — 上次已添加，供未来迁移使用 |
| 5 | `RunType.ANALYSIS` | `core/enums.py:34` | **删除** — 未使用 |
| 6 | `RunType.PATCH_TEST_EXTRACTION` | `core/enums.py:35` | **删除** — 未使用 |
| 7 | `RunType.ANALYSIS_SHADOW_CURRENT` | `core/enums.py:37` | **保留** — analysis evolution 预留 |
| 8 | `RunType.ANALYSIS_SHADOW_CANDIDATE` | `core/enums.py:38` | **保留** — 同上 |

---

## 五、未使用的 dataclass 字段（47 项，按处理方式分组）

### 5.1 建议删除（纯死字段，从未赋值也从未读取）

| 字段 | 文件:行 |
|------|--------|
| `PromptSection.metrics` | `prompt/ir.py:20` |
| `PromptSection.source_map` | `prompt/ir.py:22` |
| `PromptSection.provenance` | `prompt/ir.py:23` |
| `PromptIR.initialization` | `prompt/ir.py:42` |
| `PromptIR.history` | `prompt/ir.py:43` |
| `CompressionReport.validation_errors` | `compression/report.py:34` |
| `CompressionReport.output_constraint_violations` | `compression/report.py:35` |
| `CompressionReport.canary_broken_count` | `compression/report.py:29` |
| `CompressionReport.historical_fixed_regression_count` | `compression/report.py:30` |
| `CompressionReport.semantic_retry_count` | `compression/report.py:33` |
| `FewShotCandidate.eligible` | `fewshot/schema.py:12` |
| `FewShotSetVersion.metrics` | `fewshot/schema.py:39` |
| `AnalysisRecord.schema_violation_patch_count` | `analysis/record.py:27` |
| `AnalysisRecord.frozen_target_patch_count` | `analysis/record.py:28` |
| `RunRecord.retry_count` | `orchestration/records.py:40` |
| `PatchTestResult.format_error_count` | `testing/patch_tester.py:29` |
| `SampleAsset.hash` | `dataset/sample.py:15` |
| `GroundTruth.metadata` | `dataset/sample.py:25` |
| `ModelResponse.parsed_output` | `model/client.py:12` |
| `OutputSchemaContract.immutable` | `prompt/contract.py:16` |
| `OutputSchemaContract.schema_format` | `prompt/contract.py:17` |
| `RenderedPrompt.token_count` | `prompt/renderer.py:14` |

### 5.2 建议保留（只写不读但有审计/序列化价值）

| 字段 | 文件:行 | 保留理由 |
|------|--------|---------|
| `Patch.target/evidence/audit/risk/operation` | `patch/schema.py:36-40` | to_dict 序列化，供审计 |
| `PromptVersion.created_by_run_id/round_id` | `prompt/version.py:24-25` | 版本溯源 |
| `CompressionReport.line_budget/token_count_before/token_budget/line_count_before` | `compression/report.py:17-25` | 报告统计 |
| `FewShotOptimizationReport.max_slots/baseline_accuracy` | `fewshot/report.py:15,25` | 报告统计 |
| `FewShotCandidateState.source_round_id/accepted_round_id` | `fewshot/pool.py:13,21` | 候选池溯源 |
| `AnalysisRecord.invalid_patch_count/extraction_run_id/evaluation_record_id/analysis_prompt_version_id` | `analysis/record.py:25,11,12,14` | 审计溯源 |
| `AnalysisShadowMetrics.patch_validity_rate` | `analysis/evolution.py:17` | 报告统计 |
| `EvaluationRecord.prediction/normalized_ground_truth/schema_errors/extra` | `evaluation/evaluator.py:25,27,28,30` | 审计 |
| `PatchTestResult.unchanged_wrong/correct_sample_ids` | `testing/patch_tester.py:26-27` | 审计 |
| `PatchTestSuite.suite_type/composition` | `testing/patch_tester.py:14-15` | 审计 |

---

## 六、处理策略与优先级

### P0：补全功能链路（影响功能正确性）

1. **修复 `_debug` 方法参数错位** — `round_runner.py:629` 把 kwargs dict 当 message 传入
2. **补全 `extraction_token_budget` / `analysis_token_budget` 传递** — round_runner 调用 compress 时传入
3. **补全 `SectionContribution.cited_count`** — AnalysisRecord 添加 `prompt_section_attribution` 字段并从 parser 填充
4. **补全 resume 逻辑** — resume 时恢复 active_prompts 和 sample_states

### P1：补全或降级半成品功能

5. **补全 `patch_repair_max_attempts`** — PatchRepairEngine 接受参数并实现重试循环
6. **intermediate 文件** — 补全 Stage 2 或降级为纯调试日志
7. **`compress_analysis_if_needed` 返回值** — 保持现状（docstring 已说明）或补全 evaluation

### P2：删除死代码

8. **删除 6 个未集成模块** — merge_ranking.py、risk_aware.py、merger.py、hierarchical_merge.py（保留 risk_signals.py、section_deltas.py、llm_records.py、ab_test.py 待定）
9. **删除 RunStateStore 持久化链路** — 已被 OptimizerCheckpoint 取代
10. **删除 22 个纯死字段**（见 5.1 节）
11. **删除 `SemanticCompressionEngine.max_validation_retries` 参数**
12. **删除未使用的 RunType 枚举值**（ANALYSIS、PATCH_TEST_EXTRACTION）

### P3：保留并标注

13. 保留 Reserved 枚举值和有审计价值的只写不读字段，添加注释说明

---

## 七、验证步骤

1. 每个模块删除后运行 `python -m pytest tests/ -x -q` 确认无导入断裂
2. 功能补全后运行相关测试验证行为正确
3. 死字段删除后确认 `to_dict` 序列化测试仍通过
4. 全量测试：`python -m pytest tests/ -x -q` 确保无回归

---

## 八、假设与决策

1. **假设**：round 级产物文件（round.json、round_metrics.json 等）是审计产物，不需要被代码读回
2. **假设**：Reserved 枚举值是有意预留，不应删除
3. **决策**：对于"只写不读"但有审计/序列化价值的字段，保留而非删除
4. **决策**：对于完全孤立且已有替代品的模块（如 merger.py 被 tree_reduce.py 替代），直接删除
5. **待用户确认**：risk_signals.py、llm_records.py 是否计划集成到主流程，还是应该删除
