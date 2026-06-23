# 真实执行闭环 Spec

## Why

当前 `mmap_optimizer/refactored/` 三阶段架构骨架已完成，但所有核心执行链路（抽取、评估、分析、patch 生成、patch 应用、merge、测毒、压缩、few-shot 验证）均为 mock 实现，无法产出真实可用的优化结果。需要补齐真实执行链路，使系统能用 10～20 条小数据集跑通端到端闭环，所有核心结果来自真实模型调用和真实 evaluator。

## What Changes

- 新增 `executors/` 适配层，包含 9 个 executor，隔离 refactored 主流程与旧系统/模型调用细节
- `ExtractionExecutor`：替换 mock 抽取，接入旧系统 `ModelClient`，render StructuredPrompt 为模型输入
- `EvaluationExecutor`：替换 mock 评估，实现字段级 exact match + normalize，产出 correct/wrong/invalid
- `AnalysisExecutor`：替换 mock 分析，接入旧系统 `ModelClient`，对所有样本执行 analysis
- `PatchGenerationExecutor`：替换 mock patch 生成，基于 AnalysisResult 生成真实 patch
- `PatchApplyExecutor`：替换 mock patch 应用，真正修改 StructuredPrompt 的 section
- `MergeExecutor`：替换浅拷贝式 mock merge，接入旧系统 `TreeReducePatchMerger`
- `ToxicityTestExecutor`：替换 mock 测毒，实现真实 greedy 测毒循环
- `CompressionExecutor`：实现真实 prompt 压缩，接入旧系统 `CompressionEngine`
- `FewshotExecutor`：替换 mock few-shot 抽取和验证，使用真实 few-shot message 构造
- 补齐全链路 artifact（base/patched/final results、eval、patches、merge report、toxicity report、compression report、sample traces）
- 新增 `StructuredPromptRenderer`，将 StructuredPrompt render 成模型输入字符串
- 新增小数据集 smoke 测试和 CLI 端到端验证

## Impact

- Affected specs: 无（首个 spec）
- Affected code:
  - `mmap_optimizer/refactored/extraction_prompt_optimization_stage.py`（9 个 step 全部替换 mock）
  - `mmap_optimizer/refactored/analysis_prompt_optimization_stage.py`（8 个 step 全部替换 mock）
  - `mmap_optimizer/refactored/fewshot_optimization_phase.py`（抽取和验证替换 mock）
  - `mmap_optimizer/refactored/prompt_optimization_phase.py`（patch 应用替换 mock，artifact 补齐）
  - `mmap_optimizer/refactored/runner.py`（artifact 补齐，yaml 导入 bug 修复）
  - `mmap_optimizer/refactored/structured_prompt.py`（新增 render 能力）
  - 新增 `mmap_optimizer/refactored/executors/` 目录及 9 个 executor
  - 复用旧系统：`model/`、`evaluation/`、`patch/validator.py`、`patch/applier.py`、`patch/tree_reduce.py`、`compression/`、`testing/prompt_test_runner.py`

## ADDED Requirements

### Requirement: Execution Adapter 层

系统 SHALL 提供统一的 executor 适配层，位于 `mmap_optimizer/refactored/executors/`，包含 9 个 executor，负责把 refactored 数据结构转换为旧系统或模型调用所需格式。主流程 SHALL 通过 executor 接口调用执行逻辑，不直接依赖旧模块细节。

#### Scenario: Executor 注入
- **WHEN** 创建 PromptOptimizationPhase 或 FewshotOptimizationPhase 时
- **THEN** 应通过构造函数注入所需的 executor 实例

#### Scenario: Executor 可替换
- **WHEN** 需要替换执行实现时
- **THEN** 只需替换 executor 实例，不修改主流程代码

### Requirement: ExtractionExecutor

系统 SHALL 提供 ExtractionExecutor，将 StructuredPrompt + SampleSpec 转换为模型输入并调用 ModelClient，产出 ExtractionResult。

#### Scenario: 正常抽取
- **WHEN** 给定 StructuredPrompt 和 SampleBatch
- **THEN** 对 batch 中每个样本调用模型，返回 list[ExtractionResult]，每个结果包含 raw_output、parsed_output、status

#### Scenario: 解析失败
- **WHEN** 模型输出无法解析为 dict
- **THEN** parsed_output 为 None，status 为 "invalid"

#### Scenario: 不判断业务对错
- **WHEN** ExtractionExecutor 产出结果
- **THEN** status 只反映解析成功/失败，业务对错交给 EvaluationExecutor

### Requirement: EvaluationExecutor

系统 SHALL 提供 EvaluationExecutor，对 ExtractionResult 与 GroundTruth 做字段级比较，产出 EvalRecord。

#### Scenario: 字段级 exact match
- **WHEN** 给定 ExtractionResult 和 GroundTruth
- **THEN** 对 primary answer 字段做 exact match（支持 normalize），产出 correct/wrong/invalid

#### Scenario: 更新 SampleState
- **WHEN** 评估完成
- **THEN** 更新 SampleState 的 error_ema 和 difficulty_score

### Requirement: AnalysisExecutor

系统 SHALL 提供 AnalysisExecutor，对所有样本执行 analysis，产出 AnalysisResult。

#### Scenario: 分析所有样本
- **WHEN** 给定 extraction results
- **THEN** 对 batch 中所有样本（不只错误样本）执行 analysis

#### Scenario: analysis_correct 判定
- **WHEN** analysis 完成
- **THEN** analysis_correct 表示 analysis 对 extraction result 的判断是否与 GT 一致

#### Scenario: 错误样本给 patch suggestion
- **WHEN** 样本 extraction 错误且 analysis 正确识别
- **THEN** AnalysisResult 包含 patch_suggestion

### Requirement: PatchGenerationExecutor

系统 SHALL 提供 PatchGenerationExecutor，基于 analysis_correct=true 的样本生成真实 patch。

#### Scenario: 只基于有效分析生成 patch
- **WHEN** 给定 AnalysisResult 列表
- **THEN** 只对 analysis_correct=true 的样本生成 patch

#### Scenario: patch 绑定 source_sample_ids
- **WHEN** patch 生成
- **THEN** patch 必须绑定 source_sample_ids，指定 target_section_id

#### Scenario: 拒绝 immutable section
- **WHEN** patch 指向 immutable section
- **THEN** patch 被拒绝并记录 rejection_reason

### Requirement: PatchApplyExecutor

系统 SHALL 提供 PatchApplyExecutor，让 patch 真正作用于 StructuredPrompt。

#### Scenario: 修改 mutable section
- **WHEN** 给定 base StructuredPrompt 和 patch list
- **THEN** 生成新的 StructuredPrompt，patch 只修改 mutable section

#### Scenario: 拒绝 immutable section
- **WHEN** patch 指向 immutable section（如 output schema）
- **THEN** 该 patch 被拒绝，不污染原 prompt

#### Scenario: 支持 replace/append/delete
- **WHEN** patch operation_type 为 replace/insert_after/insert_before/delete
- **THEN** 对应 section 内容被正确修改

#### Scenario: 版本递增
- **WHEN** patch 应用成功
- **THEN** 新 prompt 的 version 递增

### Requirement: MergeExecutor

系统 SHALL 提供 MergeExecutor，替换浅拷贝式 mock merge，接入旧系统 TreeReducePatchMerger。

#### Scenario: tree_merge
- **WHEN** 给定 draft patches 和 merge_strategy="tree_merge"
- **THEN** 执行树形归约，返回 merged patches 和 merge report

#### Scenario: merge 后重新 validate
- **WHEN** merge 完成
- **THEN** merged patches 经过 PatchValidator 验证

#### Scenario: fallback
- **WHEN** LLM merge 失败
- **THEN** fallback 到 rule-based merge 或保留原 patch

### Requirement: ToxicityTestExecutor

系统 SHALL 提供 ToxicityTestExecutor，实现真实 greedy 测毒。

#### Scenario: greedy 测毒循环
- **WHEN** 给定 candidate patches 和 toxic_sample_ids
- **THEN** 按 source sample 难度排序，逐 patch 应用并在 toxic_sample_ids 上测试

#### Scenario: early stop
- **WHEN** 某个 toxic sample 测试失败
- **THEN** 立即拒绝当前 patch 为 TOXIC

#### Scenario: 空 toxic set 跳过
- **WHEN** toxic_sample_ids 为空
- **THEN** 跳过测毒，所有非无效 patch 进入 candidate-safe 集合

### Requirement: CompressionExecutor

系统 SHALL 提供 CompressionExecutor，实现真实 prompt 压缩。

#### Scenario: 超限触发
- **WHEN** prompt 超过 line_limit 或 char_limit
- **THEN** 启动压缩

#### Scenario: 接受标准
- **WHEN** 压缩完成
- **THEN** compressed_accuracy >= pre_compression_accuracy 且无新增 regression 才接受

#### Scenario: 压缩失败保留原 prompt
- **WHEN** 压缩后指标下降
- **THEN** 拒绝压缩，保留未压缩 prompt

### Requirement: FewshotExecutor

系统 SHALL 提供 FewshotExecutor，替换 mock few-shot 抽取和验证。

#### Scenario: 真实 few-shot 抽取
- **WHEN** 给定 locked extraction prompt 和 few-shot set
- **THEN** 使用真实 few-shot message 构造和模型调用

#### Scenario: 接受判断
- **WHEN** 新 few-shot set 测试完成
- **THEN** new_fewshot_accuracy >= old_fewshot_accuracy 才接受

### Requirement: StructuredPromptRenderer

系统 SHALL 提供 StructuredPromptRenderer，将 StructuredPrompt render 成模型输入字符串。

#### Scenario: render 为 Markdown
- **WHEN** 给定 StructuredPrompt
- **THEN** 输出完整的 Markdown 字符串，包含所有 mutable 和 immutable section

#### Scenario: render 带 few-shot
- **WHEN** 给定 StructuredPrompt 和 few-shot examples
- **THEN** 输出包含 few-shot 示例的完整 prompt

### Requirement: 全链路 Artifact

系统 SHALL 保存全链路可追踪的 artifact，从 metrics-only 升级为完整执行链路记录。

#### Scenario: Prompt Optimization Iteration artifact
- **WHEN** 一轮 prompt optimization 完成
- **THEN** 保存 sample_batch、sample_traces、sample_state_before/after、batch_size_controller_before/after、extraction/ 下 12 个文件、analysis/ 下 9 个文件

#### Scenario: Few-shot Iteration artifact
- **WHEN** 一轮 few-shot optimization 完成
- **THEN** 保存 sample_batch、sample_traces、fewshot/ 下 6 个文件

#### Scenario: Compression artifact
- **WHEN** 触发压缩
- **THEN** 额外保存 extraction/compression_report.json 或 analysis/compression_report.json

### Requirement: 端到端 Smoke

系统 SHALL 支持用 10～20 条小数据集跑通端到端闭环。

#### Scenario: 完整三阶段 Run
- **WHEN** 执行 `python -m mmap_optimizer.refactored.cli run --config configs/refactored_config.yaml`
- **THEN** 完成 Prompt Structuring → 1 轮 Prompt Optimization → 1 轮 Few-shot Optimization

#### Scenario: 无 mock output
- **WHEN** Run 完成
- **THEN** 所有结果来自真实模型调用，不出现 "mock output" 字样

## MODIFIED Requirements

### Requirement: Extraction Prompt Optimization Stage

ExtractionPromptOptimizationStage 的 9 个 step SHALL 使用 executor 接口替换所有 mock 实现：
- Step 1: 使用 ExtractionExecutor
- Step 2: 使用 EvaluationExecutor
- Step 3: 使用 AnalysisExecutor
- Step 4: 使用 PatchGenerationExecutor
- Step 5: 使用 MergeExecutor
- Step 6: 使用 PatchApplyExecutor + ExtractionExecutor + EvaluationExecutor
- Step 7: 使用 ToxicityTestExecutor
- Step 8: 使用 CompressionExecutor
- Step 9: 使用 ExtractionExecutor + EvaluationExecutor

### Requirement: Analysis Prompt Optimization Stage

AnalysisPromptOptimizationStage 的 8 个 step SHALL 使用 executor 接口替换所有 mock 实现：
- Step 1: 复用 extraction stage 的 analysis_results
- Step 2: 使用 AnalysisExecutor（反思模式）
- Step 3: 使用 PatchGenerationExecutor
- Step 4: 使用 MergeExecutor
- Step 5: 使用 PatchApplyExecutor + AnalysisExecutor
- Step 6: 使用 ToxicityTestExecutor
- Step 7: 使用 CompressionExecutor
- Step 8: 使用 AnalysisExecutor

### Requirement: Few-shot Optimization Phase

FewshotOptimizationPhase SHALL 使用 FewshotExecutor 替换 mock 抽取和验证，使用真实模型调用和 evaluator。

### Requirement: Prompt Optimization Phase

PromptOptimizationPhase SHALL 使用 PatchApplyExecutor 真正应用 patch 到 StructuredPrompt，不再仅自增 version。SHALL 保存全链路 artifact。

### Requirement: Runner

MMAPRunner SHALL 保存 sample_traces.jsonl，修复 yaml 导入顺序 bug，保存最终 few-shot examples。
