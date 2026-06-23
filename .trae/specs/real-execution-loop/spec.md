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

系统 SHALL 提供 PatchGenerationExecutor，基于 analysis_correct=true 的样本生成真实 patch，替换固定生成 mock patch 的行为。支持 ExtractionPatch 和 AnalysisPatch 两类 patch。

#### Scenario: 只基于有效分析生成 extraction patch
- **WHEN** 给定 AnalysisResult 列表
- **THEN** 只对 analysis_correct=true 的样本生成 ExtractionPatch

#### Scenario: 只基于有效反思生成 analysis patch
- **WHEN** 给定 ReflectionResult 列表
- **THEN** 只对 reflection_success=true 且存在 patch_suggestion 的样本生成 AnalysisPatch

#### Scenario: patch 绑定 source_sample_ids
- **WHEN** patch 生成
- **THEN** patch 必须绑定 source_sample_ids，指定 target_section_id，来源不明的 patch 拒绝生成

#### Scenario: patch 目标必须存在
- **WHEN** patch 的 target_section_id 在 prompt 中不存在
- **THEN** 该 patch 被拒绝，不进入 candidate 列表

#### Scenario: patch 内容不允许为空或占位符
- **WHEN** patch content 为空或为 "Mock patch content"、"TODO"、"N/A" 等无意义占位符
- **THEN** 该 patch 被拒绝

#### Scenario: 每个 patch 包含完整字段
- **WHEN** patch 生成成功
- **THEN** patch 包含 id、target_section_id、operation_type、content、rationale、source_sample_ids、status

### Requirement: PatchValidator

系统 SHALL 提供 PatchValidator，在 patch 生成后、应用前进行统一校验。校验项包括：target_section_id 是否存在、target section 是否 mutable、operation_type 是否合法、content 是否为空、source_sample_ids 是否为空且存在于 SampleSet、patch 是否尝试修改输出 schema、patch 是否包含明显 mock/placeholder 内容。

#### Scenario: 校验通过
- **WHEN** patch 所有校验项通过
- **THEN** patch status 设为 "candidate"

#### Scenario: 校验失败
- **WHEN** 任一校验项失败
- **THEN** patch status 设为 "rejected"，rejection_reason 为 "VALIDATION_FAILED:<reason>"

#### Scenario: 批量校验
- **WHEN** 给定 patch 列表
- **THEN** 返回通过校验的 patch 列表和被拒绝的 patch 列表

### Requirement: PatchApplyExecutor

系统 SHALL 提供 PatchApplyExecutor，让 patch 真正作用于 StructuredPrompt，而不是只自增 version。第一版只支持 replace、append、delete 三种操作，暂不实现 insert_before/insert_after。

#### Scenario: replace 操作
- **WHEN** patch operation_type 为 "replace"
- **THEN** 目标 section 的 content 被替换为 patch content

#### Scenario: append 操作
- **WHEN** patch operation_type 为 "append"
- **THEN** patch content 追加到目标 section 的 content 末尾

#### Scenario: delete 操作默认禁用
- **WHEN** patch operation_type 为 "delete" 且配置未显式开启 delete
- **THEN** 该 patch 被拒绝；delete 只清空 section content，不删除 section 本身

#### Scenario: 拒绝 immutable section
- **WHEN** patch 指向 immutable section（如 output schema）
- **THEN** 该 patch 被拒绝，rejection_reason 为 "IMMUTABLE_SECTION"，不污染原 prompt

#### Scenario: 版本递增与 lineage
- **WHEN** patch 应用成功
- **THEN** new_prompt.version = base_prompt.version + 1，new_prompt.parent_id = base_prompt.id，new_prompt.metadata["applied_patch_ids"] 记录已应用的 patch id 列表

#### Scenario: changed 判定
- **WHEN** patch 应用完成
- **THEN** 比较 before_hash 和 after_hash，如果相同则 changed=false，即使 patch 没报错也不能认为 prompt 成功推进

### Requirement: PatchApplyReport

每次 patch apply 都 SHALL 生成 PatchApplyReport，记录应用的详细信息。

#### Scenario: report 字段完整
- **WHEN** patch apply 完成
- **THEN** report 包含 id、base_prompt_id、new_prompt_id、applied_patch_ids、rejected_patch_ids、modified_section_ids、before_hash、after_hash、changed、warnings

#### Scenario: 无有效 patch 时 changed=false
- **WHEN** 所有 patch 被拒绝或应用后内容未变化
- **THEN** changed=false，warnings 记录原因

### Requirement: Passthrough Merge（PR2 临时）

PR2 阶段 Step 5 SHALL 使用 passthrough merge 替代真实 tree-merge，保留接口供 PR3 替换。

#### Scenario: passthrough 传递
- **WHEN** 给定 validated patches
- **THEN** initial_merged_patches = validated_patches，不做实际合并

#### Scenario: 保留 merge report
- **WHEN** passthrough merge 完成
- **THEN** 生成 merge report，merge_strategy="passthrough"，记录 input_patch_count 和 merged_patch_count

### Requirement: Patch Set 级安全判断（PR2 临时）

PR2 阶段 Step 7 SHALL 基于 base_eval 和 patched_eval 做 patch set 级 transition 分类，不做逐 patch greedy 测毒。

#### Scenario: transition 分类
- **WHEN** 比较 base_eval 和 patched_eval
- **THEN** 分类为 fixed、broken、unchanged_wrong、unchanged_correct

#### Scenario: 接受规则
- **WHEN** fixed > 0 且 broken = 0
- **THEN** patch set 被接受，trial_prompt 成为 accepted_prompt

#### Scenario: 无收益拒绝
- **WHEN** fixed = 0
- **THEN** patch set 被认为无明显收益，不推进 prompt

#### Scenario: unsafe 回滚
- **WHEN** broken > 0
- **THEN** 本轮标记为 unsafe，回滚到 base_prompt

### Requirement: Prompt Lineage 追踪

系统 SHALL 记录每次 prompt 推进的 lineage 信息。

#### Scenario: lineage 记录
- **WHEN** prompt 成功推进
- **THEN** 记录 base_prompt_id、new_prompt_id、version、applied_patch_ids、iteration、stage

#### Scenario: PromptOptimizationPhase 使用 accepted_prompt
- **WHEN** extraction_stage 或 analysis_stage 产出 accepted_prompt
- **THEN** PromptOptimizationPhase 更新当前 prompt 为 accepted_prompt，不再仅自增 version

### Requirement: MergeExecutor

系统 SHALL 提供 MergeExecutor，替换 PR2 的 passthrough merge，接入旧系统 TreeReducePatchMerger，将多个 patch 合并成更少、更一致、更可应用的 patch 集合。

#### Scenario: 输入与输出
- **WHEN** 给定 patches、base_prompt、merge_strategy
- **THEN** 返回 (merged_patches, merge_report)，patches 类型为 ExtractionPatch 或 AnalysisPatch

#### Scenario: tree_merge 策略（默认）
- **WHEN** merge_strategy="tree_merge"
- **THEN** 执行树形归约，将多个 patch 按树状结构逐层归并，减少重复规则

#### Scenario: hierarchical_merge 策略（可选）
- **WHEN** merge_strategy="hierarchical_merge"
- **THEN** 保留接口供后续复杂分层归并，本阶段非必须完整实现

#### Scenario: passthrough fallback
- **WHEN** 真实 merge 失败
- **THEN** 回退为 merged_patches = validated_patches，merge_report.fallback_used=true

#### Scenario: merge 后重新 validate
- **WHEN** merge 完成
- **THEN** merged patches 经过 PatchValidator 验证，通过进入 initial_merged_patches，失败标记 rejection_reason="MERGED_PATCH_VALIDATION_FAILED"

#### Scenario: MergeReport 字段完整
- **WHEN** merge 完成
- **THEN** merge_report 包含 id、strategy、input_patch_count、merged_patch_count、dropped_patch_count、conflict_count、input_patch_ids、merged_patch_ids、dropped_patch_ids、conflict_patch_ids、merge_reason、fallback_used、warnings

#### Scenario: 数据结构转换
- **WHEN** 调用旧系统 TreeReducePatchMerger
- **THEN** 实现 ExtractionPatch/AnalysisPatch ↔ 旧系统 Patch 的双向数据结构转换

### Requirement: ToxicityTestExecutor

系统 SHALL 提供 ToxicityTestExecutor，替换 PR2 的 patch set 级整体回归判断，实现 patch 级 greedy 测毒安全筛选。

#### Scenario: 输入与输出
- **WHEN** 给定 base_prompt、candidate_patches、toxic_sample_ids、sample_set、executor_set、mode、early_stop
- **THEN** 返回 (safe_patches, toxic_patches, toxicity_report)，mode 为 extraction 或 analysis

#### Scenario: patch 按来源样本难度排序
- **WHEN** 候选 patch 进入测毒前
- **THEN** 按 patch_difficulty（max of source_sample_ids difficulty_score）降序、source_sample_count 降序、patch_id 升序排序

#### Scenario: greedy 测毒循环
- **WHEN** 给定排序后的 candidate patches 和 toxic_sample_ids
- **THEN** 逐 patch 应用到 cumulative_prompt，在 toxic_sample_ids 上测试，safe patch 累积到 cumulative_prompt，toxic patch 被拒绝

#### Scenario: extraction 模式测毒
- **WHEN** mode="extraction"
- **THEN** 使用 ExtractionExecutor + EvaluationExecutor + PatchApplyExecutor，对 toxic_sample_ids 逐样本抽取和评估

#### Scenario: analysis 模式测毒
- **WHEN** mode="analysis"
- **THEN** 使用 AnalysisExecutor + PatchApplyExecutor + 已有 extraction_results，对 toxic_sample_ids 逐样本执行 analysis

#### Scenario: early stop
- **WHEN** 某个 toxic sample 被当前 patch 搞坏（extraction: eval_record.status != correct；analysis: analysis_result.analysis_correct == false）
- **THEN** 立即停止当前 patch 的测毒，拒绝该 patch 为 TOXIC，进入下一个 patch

#### Scenario: 空 toxic set 跳过
- **WHEN** toxic_sample_ids 为空
- **THEN** 跳过 greedy 测毒，所有非 ineffective patch 进入 safe_patches，toxicity_report 标记 skipped_reason="NO_TOXIC_SAMPLES"

#### Scenario: ToxicityReport 字段完整
- **WHEN** 测毒完成
- **THEN** toxicity_report 包含 id、mode、tested_patch_count、safe_patch_count、toxic_patch_count、toxic_sample_ids、safe_patch_ids、toxic_patch_ids、patch_test_records、early_stop_enabled

#### Scenario: patch_test_record 字段完整
- **WHEN** 每个 patch 测毒完成
- **THEN** patch_test_record 包含 patch_id、status(safe/toxic/skipped)、tested_sample_ids、broken_sample_ids、fixed_sample_ids、stop_reason

### Requirement: Ineffective Patch 剔除

系统 SHALL 在测毒前剔除 ineffective patch，即 source_sample_ids 全部属于 unchanged_wrong 的 patch。

#### Scenario: ineffective 判定
- **WHEN** patch.source_sample_ids 全部属于 unchanged_wrong 集合
- **THEN** patch.status="rejected"，patch.rejection_reason="INEFFECTIVE"，不进入测毒

#### Scenario: analysis ineffective 判定
- **WHEN** analysis patch 的 source_sample_ids 全部属于 analysis unchanged_wrong 集合
- **THEN** 该 analysis patch 标记为 INEFFECTIVE

### Requirement: Toxic Sample Set 构造

系统 SHALL 基于 base_eval 和 patched_eval 的 transition 分类构造 toxic_sample_ids。

#### Scenario: extraction toxic sample set
- **WHEN** 比较 base_eval 和 patched_eval
- **THEN** toxic_sample_ids = broken sample ids（base=correct, patched=wrong）

#### Scenario: analysis toxic sample set
- **WHEN** 比较 base_analysis_result 和 patched_analysis_result
- **THEN** analysis_toxic_sample_ids = base analysis correct, patched analysis wrong 的样本

### Requirement: Safe Patch 二次 Merge

系统 SHALL 对测毒后的 safe_patches 重新 merge，因为 initial merge 中可能包含 ineffective/toxic/被拒绝的 patch。

#### Scenario: final merge
- **WHEN** 测毒完成得到 safe_patches
- **THEN** 使用与 initial merge 相同的策略对 safe_patches 重新 merge，产出 final_merged_patches

#### Scenario: final merge fallback
- **WHEN** final merge 失败
- **THEN** fallback 到 passthrough safe_patches，merge_report.fallback_used=true

#### Scenario: final merge 后 validate
- **WHEN** final merge 完成
- **THEN** final_merged_patches 经过 PatchValidator 校验

### Requirement: Final Prompt Apply（PR3）

系统 SHALL 将 final_merged_patches 应用到本轮原始 base_prompt，而不是 initial trial prompt。

#### Scenario: 应用 final merged patches
- **WHEN** final_merged_patches 非空
- **THEN** final_prompt = PatchApplyExecutor.apply(base_prompt, final_merged_patches)

#### Scenario: 空 safe patch 处理
- **WHEN** safe_patches 为空
- **THEN** 本轮 no_progress，回滚到 base_prompt，不推进 prompt version

#### Scenario: analysis no_progress 不影响 extraction
- **WHEN** analysis prompt 无进展
- **THEN** 不回滚 extraction prompt

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

### Requirement: Extraction Prompt Optimization Stage（PR2 阶段）

ExtractionPromptOptimizationStage 的 Step 4-9 SHALL 使用真实 executor 替换 mock 实现：
- Step 4: 使用 PatchGenerationExecutor 生成 draft patches + PatchValidator 校验，产出 draft_patches、validated_patches、rejected_patches
- Step 5: 使用 passthrough merge（临时），保留 merge report，供 PR3 替换为真实 MergeExecutor
- Step 6: 使用 PatchApplyExecutor 应用 patch，如果 apply_report.changed=true 则使用 ExtractionExecutor + EvaluationExecutor 重新抽取和评估
- Step 7: 基于 base_eval 和 patched_eval 做 patch set 级 transition 分类（fixed/broken/unchanged），不做逐 patch 测毒
- Step 8: 保留 compression 预留接口（PR2 不实现）
- Step 9: 使用真实 ExtractionExecutor + EvaluationExecutor 执行 final test，不再生成 mock final output

#### Scenario: Step 4 真实生成 patch
- **WHEN** Step 4 执行
- **THEN** 从 analysis_correct=true 的样本生成 draft patches，经 PatchValidator 校验后只保留 candidate patches

#### Scenario: Step 6 apply + 回归测试
- **WHEN** apply_report.changed=true
- **THEN** 使用 trial_prompt 重新执行 ExtractionExecutor 和 EvaluationExecutor，产出 patched_results 和 patched_eval

#### Scenario: Step 6 apply 未变化
- **WHEN** apply_report.changed=false
- **THEN** 本轮标记 no_progress，不进入后续 accepted prompt

#### Scenario: Step 7 接受判断
- **WHEN** fixed > 0 且 broken = 0
- **THEN** patch set 被接受，trial_prompt 成为 accepted_prompt

#### Scenario: Step 7 回滚
- **WHEN** broken > 0
- **THEN** 回滚到 base_prompt，标记 unsafe

#### Scenario: Step 9 真实 final test
- **WHEN** Step 7 判定接受
- **THEN** 使用 accepted_prompt 在原 SampleBatch 上重新测试，产出 final_results 和 final_eval
- **WHEN** Step 7 判定拒绝
- **THEN** final_prompt = base_prompt，final_accuracy = base_accuracy，no_progress = true

### Requirement: Analysis Prompt Optimization Stage（PR2 阶段）

AnalysisPromptOptimizationStage 的 Step 3-8 SHALL 使用真实 executor 替换 mock 实现：
- Step 3: 使用 PatchGenerationExecutor 生成 analysis draft patches + PatchValidator 校验
- Step 4: 使用 passthrough merge（临时）
- Step 5: 使用 PatchApplyExecutor 应用 analysis patch，复用本轮 extraction results 重新执行 AnalysisExecutor
- Step 6: 基于 base_analysis_accuracy 和 patched_analysis_accuracy 做 patch set 级判断
- Step 7: 保留 compression 预留接口（PR2 不实现）
- Step 8: 使用真实 AnalysisExecutor 执行 final test

#### Scenario: Step 3 真实生成 analysis patch
- **WHEN** Step 3 执行
- **THEN** 从 reflection_success=true 且有 patch_suggestion 的样本生成 draft patches

#### Scenario: Step 5 apply + analysis 回归
- **WHEN** apply_report.changed=true
- **THEN** 使用 trial_analysis_prompt 重新执行 AnalysisExecutor，产出 patched_analysis_results

#### Scenario: Step 6 接受判断
- **WHEN** patched_analysis_accuracy >= base_analysis_accuracy 且无明显 regression
- **THEN** analysis patch set 被接受

#### Scenario: Step 6 回滚
- **WHEN** analysis accuracy 下降
- **THEN** 回滚 analysis prompt，不影响 extraction prompt 的成功推进

#### Scenario: Step 8 真实 final analysis test
- **WHEN** Step 6 判定接受
- **THEN** 使用 accepted_analysis_prompt 重新运行 analysis，统计 final_analysis_accuracy

### Requirement: Prompt Optimization Phase（PR2 阶段）

PromptOptimizationPhase SHALL 注入 patch_generation_executor 和 patch_apply_executor，并传给 ExtractionPromptOptimizationStage 和 AnalysisPromptOptimizationStage。SHALL 使用 accepted_prompt 真正更新当前 prompt，不再仅自增 version。SHALL 记录 prompt lineage。

#### Scenario: 注入新 executor
- **WHEN** 创建 PromptOptimizationPhase
- **THEN** 接受 patch_generation_executor 和 patch_apply_executor 并注入到 stages

#### Scenario: 使用 accepted_prompt 更新
- **WHEN** extraction_stage.accepted_prompt is not None
- **THEN** self.extraction_prompt = extraction_stage.accepted_prompt
- **WHEN** analysis_stage.accepted_prompt is not None
- **THEN** self.analysis_prompt = analysis_stage.accepted_prompt

#### Scenario: 记录 prompt lineage
- **WHEN** prompt 推进
- **THEN** 记录 base_prompt_id、new_prompt_id、version、applied_patch_ids、iteration、stage 到 prompt_versions.jsonl

### Requirement: Extraction Prompt Optimization Stage（PR3 阶段）

ExtractionPromptOptimizationStage 的 Step 5-7 SHALL 从 PR2 的简化逻辑升级为真实 merge + greedy 测毒：
- Step 5: 使用 MergeExecutor 执行真实 tree merge，替换 passthrough merge
- Step 6: 应用 initial merged patches，进行真实回归测试（沿用 PR2 的 PatchApplyExecutor + ExtractionExecutor + EvaluationExecutor）
- Step 7: transition 分类 → 剔除 ineffective patches → 构造 toxic_sample_ids → patch 排序 → greedy 测毒 → safe patches 二次 merge → 应用 final merged patches 到 base prompt
- Step 9: 基于 final_prompt 做最终测试（沿用 PR2）

#### Scenario: Step 5 真实 merge
- **WHEN** Step 5 执行
- **THEN** 使用 MergeExecutor.merge(validated_patches, base_prompt, merge_strategy)，merge 后重新 validate

#### Scenario: Step 7 ineffective 剔除
- **WHEN** Step 7 transition 分类完成
- **THEN** source_sample_ids 全部属于 unchanged_wrong 的 patch 被标记为 INEFFECTIVE，不进入测毒

#### Scenario: Step 7 greedy 测毒
- **WHEN** toxic_sample_ids 非空
- **THEN** 对剩余 patch 按难度排序，逐 patch 在 toxic_sample_ids 上测试，safe patch 累积，toxic patch 拒绝

#### Scenario: Step 7 safe patch 二次 merge
- **WHEN** 测毒完成
- **THEN** 对 safe_patches 重新 merge，产出 final_merged_patches

#### Scenario: Step 7 final apply
- **WHEN** final_merged_patches 非空
- **THEN** final_prompt = PatchApplyExecutor.apply(base_prompt, final_merged_patches)，accepted_prompt = final_prompt

#### Scenario: Step 7 空 safe patch
- **WHEN** safe_patches 为空
- **THEN** no_progress=true，accepted_prompt=None，回滚到 base_prompt

### Requirement: Analysis Prompt Optimization Stage（PR3 阶段）

AnalysisPromptOptimizationStage 的 Step 4-6 SHALL 从 PR2 的简化逻辑升级为真实 merge + greedy 测毒：
- Step 4: 使用 MergeExecutor 执行真实 analysis patch merge
- Step 5: 应用 initial merged analysis patches，重新运行 analysis（沿用 PR2）
- Step 6: analysis transition 分类 → 剔除 ineffective analysis patches → 构造 analysis_toxic_sample_ids → greedy analysis 测毒 → safe analysis patches 二次 merge → 应用 final analysis patches 到 base analysis prompt
- Step 8: 基于 final_analysis_prompt 做最终测试（沿用 PR2）

#### Scenario: Step 4 真实 merge
- **WHEN** Step 4 执行
- **THEN** 使用 MergeExecutor.merge(validated_patches, analysis_prompt, merge_strategy)

#### Scenario: Step 6 analysis greedy 测毒
- **WHEN** analysis_toxic_sample_ids 非空
- **THEN** 逐 patch 在 analysis_toxic_sample_ids 上测试 analysis_correct

#### Scenario: Step 6 analysis no_progress 不影响 extraction
- **WHEN** analysis prompt 无进展
- **THEN** 不回滚 extraction prompt

### Requirement: Prompt Optimization Phase（PR3 阶段）

PromptOptimizationPhase SHALL 注入 merge_executor 和 toxicity_test_executor，并传给 ExtractionPromptOptimizationStage 和 AnalysisPromptOptimizationStage。

#### Scenario: 注入新 executor
- **WHEN** 创建 PromptOptimizationPhase
- **THEN** 接受 merge_executor 和 toxicity_test_executor 并注入到 stages

### Requirement: PR3 Artifact

系统 SHALL 保存 PR3 阶段新增的 artifact，记录 merge、测毒、safe/toxic patch 的完整链路。

#### Scenario: Extraction artifact
- **WHEN** 一轮 extraction prompt optimization 完成
- **THEN** extraction/ 下保存 initial_merge_report.json、transition_report.json、ineffective_patches.jsonl、toxicity_report.json、safe_patches.jsonl、toxic_patches.jsonl、final_merge_report.json、final_merged_patches.jsonl、final_prompt.json、patch_test_records.jsonl

#### Scenario: Analysis artifact
- **WHEN** 一轮 analysis prompt optimization 完成
- **THEN** analysis/ 下保存 initial_merge_report.json、transition_report.json、ineffective_patches.jsonl、toxicity_report.json、safe_patches.jsonl、toxic_patches.jsonl、final_merge_report.json、final_merged_patches.jsonl、final_analysis_prompt.json、patch_test_records.jsonl

### Requirement: Few-shot Optimization Phase

FewshotOptimizationPhase SHALL 使用 FewshotExecutor 替换 mock 抽取和验证，使用真实模型调用和 evaluator。

### Requirement: Runner

MMAPRunner SHALL 保存 sample_traces.jsonl，修复 yaml 导入顺序 bug，保存最终 few-shot examples。
