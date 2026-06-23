# Checklist

## PR 1：真实执行与评估接入

- [x] executors/ 目录已创建，包含 __init__.py 和基础接口定义
- [x] StructuredPromptRenderer 能将 StructuredPrompt render 成完整 Markdown
- [x] StructuredPromptRenderer 支持 few-shot 注入
- [x] ExtractionExecutor 接入旧系统 ModelClient，能调用模型产出 raw_output
- [x] ExtractionExecutor 能解析 raw_output 为 parsed_output，解析失败时 status="invalid"
- [x] ExtractionExecutor 不判断业务对错，status 只反映解析成功/失败
- [x] EvaluationExecutor 实现字段级 exact match 比较
- [x] EvaluationExecutor 支持 normalize（label mapping）
- [x] EvaluationExecutor 能识别 invalid 输出
- [x] EvaluationExecutor 评估后更新 SampleState 的 error_ema 和 difficulty_score
- [x] AnalysisExecutor 对所有样本执行 analysis（不只错误样本）
- [x] AnalysisExecutor 正确判定 analysis_correct
- [x] AnalysisExecutor 对错误样本生成 patch_suggestion
- [x] FewshotExecutor 能使用真实 few-shot message 构造抽取
- [x] ExtractionPromptOptimizationStage Step 1-3 使用真实 executor
- [x] AnalysisPromptOptimizationStage 复用 extraction stage 的 analysis_results
- [x] FewshotOptimizationPhase 使用 FewshotExecutor
- [x] PromptOptimizationPhase 和 MMAPRunner 能从配置构建并注入 executor
- [x] 小数据集可以真实跑出 correct / wrong / invalid
- [x] extraction/base_results.jsonl 有真实模型输出（PR4 Task 31 artifact 收敛已完成，smoke 测试验证可解析）
- [x] analysis_results.jsonl 有真实分析结果（PR4 Task 31 artifact 收敛已完成，smoke 测试验证可解析）
- [x] SampleState 的 error_ema 基于真实评估更新
- [x] 没有 mock status="correct" 的硬编码结果（真实 executor 不硬编码；mock fallback 保留用于无 model_client 场景）

## PR 2：真实 Patch 生成、应用与 Prompt 版本推进

### PatchValidator
- [x] PatchValidator 实现 target_section_id 存在性校验
- [x] PatchValidator 实现 mutable section 校验
- [x] PatchValidator 实现 operation_type 合法性校验
- [x] PatchValidator 实现 content 非空校验
- [x] PatchValidator 实现 source_sample_ids 非空且存在校验
- [x] PatchValidator 实现 output schema 保护校验
- [x] PatchValidator 实现 mock/placeholder 内容检测
- [x] 校验通过返回 status="candidate"
- [x] 校验失败返回 status="rejected" + rejection_reason="VALIDATION_FAILED:<reason>"
- [x] validate_batch 返回 (validated_patches, rejected_patches)

### PatchGenerationExecutor
- [x] PatchGenerationExecutor 基于 AnalysisResult 生成 ExtractionPatch
- [x] PatchGenerationExecutor 基于 ReflectionResult 生成 AnalysisPatch
- [x] 只从 analysis_correct=true 的样本生成 extraction patch
- [x] 只从 reflection_success=true 且有 patch_suggestion 的样本生成 analysis patch
- [x] 每个 patch 绑定 source_sample_ids
- [x] target_section_id 不存在时拒绝生成
- [x] content 为空或为占位符时拒绝生成
- [x] 集成 PatchValidator 校验
- [x] 产出 draft_patches、validated_patches、rejected_patches

### PatchApplyExecutor
- [x] PatchApplyExecutor 实现 replace 操作
- [x] PatchApplyExecutor 实现 append 操作
- [x] PatchApplyExecutor 实现 delete 操作（默认禁用，需配置开启）
- [x] PatchApplyExecutor 拒绝 immutable section patch（rejection_reason="IMMUTABLE_SECTION"）
- [x] patch 应用后 prompt version 递增
- [x] new_prompt.parent_id = base_prompt.id
- [x] new_prompt.metadata["applied_patch_ids"] 记录已应用 patch
- [x] changed 判定基于 before_hash / after_hash 比较
- [x] PatchApplyReport 包含完整字段（id、base_prompt_id、new_prompt_id、applied_patch_ids、rejected_patch_ids、modified_section_ids、before_hash、after_hash、changed、warnings）

### Extraction Stage 接入
- [x] Step 4 使用 PatchGenerationExecutor + PatchValidator 替换 mock patch 生成
- [x] Step 5 使用 passthrough merge（临时），保留 merge report
- [x] Step 6 使用 PatchApplyExecutor.apply() 替换 mock 应用
- [x] Step 6 apply_report.changed=true 时使用 ExtractionExecutor + EvaluationExecutor 重新抽取和评估
- [x] Step 6 apply_report.changed=false 时标记 no_progress
- [x] Step 7 基于 base_eval 和 patched_eval 做 patch set 级 transition 分类
- [x] Step 7 fixed > 0 且 broken = 0 时接受 patch set
- [x] Step 7 broken > 0 时回滚到 base_prompt
- [x] Step 9 使用真实 ExtractionExecutor + EvaluationExecutor 执行 final test
- [x] Step 9 接受时 final_prompt = accepted_prompt
- [x] Step 9 拒绝时 final_prompt = base_prompt + no_progress=true
- [x] stage 新增 accepted_prompt 属性

### Analysis Stage 接入
- [x] Step 3 使用 PatchGenerationExecutor.generate_analysis_patches() + PatchValidator
- [x] Step 4 使用 passthrough merge（临时）
- [x] Step 5 使用 PatchApplyExecutor.apply() 替换 mock 应用
- [x] Step 5 changed=true 时复用本轮 extraction results 重新执行 AnalysisExecutor
- [x] Step 6 patched_analysis_accuracy >= base_analysis_accuracy 且无 regression 时接受
- [x] Step 6 accuracy 下降时回滚 analysis prompt
- [x] Step 8 使用真实 AnalysisExecutor 执行 final test
- [x] stage 新增 accepted_prompt 属性

### PromptOptimizationPhase 改造
- [x] 注入 patch_generation_executor 和 patch_apply_executor
- [x] 将新 executor 传给 ExtractionPromptOptimizationStage 和 AnalysisPromptOptimizationStage
- [x] 使用 stage.accepted_prompt 更新当前 prompt（不再仅自增 version）
- [x] 记录 prompt lineage（base_prompt_id、new_prompt_id、version、applied_patch_ids、iteration、stage）
- [x] 保存 prompt_versions.jsonl 和 patch_apply_reports.jsonl

### Factory / Runner
- [x] factory.py 构建 PatchGenerationExecutor 实例
- [x] factory.py 构建 PatchApplyExecutor 实例
- [x] factory.py 构建 PatchValidator 实例
- [x] runner.py 将新 executor 注入到 PromptOptimizationPhase

### Artifact
- [x] extraction/ 下保存 15 个文件（base_results、base_eval、analysis_results、draft_patches、validated_patches、rejected_patches、initial_merge_report、patched_prompt、patch_apply_report、patched_results、patched_eval、final_prompt、final_results、final_eval、metrics）
- [x] analysis/ 下保存 12 个文件（base_metrics、reflection_results、draft_patches、validated_patches、rejected_patches、initial_merge_report、patched_analysis_prompt、patch_apply_report、patched_analysis_results、final_analysis_prompt、final_analysis_results、metrics）
- [x] run-level 保存 prompt_versions.jsonl、patch_apply_reports.jsonl、run_summary.json

### 集成测试
- [x] analysis result → extraction patch → validate → apply → render 链路跑通
- [x] reflection result → analysis patch → validate → apply → render 链路跑通
- [x] patched prompt 重新执行 extraction 成功
- [x] patched analysis prompt 重新执行 analysis 成功
- [x] broken sample 出现时回滚生效
- [x] fixed 样本出现且无 broken 时接受生效

### Smoke 测试与验收
- [x] 3～5 条最小样本流程跑通（patch generated → patch applied → prompt changed → final eval generated）
- [x] accepted patch 能修改指定 section
- [x] output schema section 不可修改
- [x] final prompt 能 render 成模型输入
- [x] prompt version 真实变化
- [x] CLI 能跑通至少 1 轮 prompt optimization 并产生真实 prompt 变化

## PR 3：真实 Merge 与 Greedy 测毒

### MergeExecutor
- [x] MergeExecutor 创建 `executors/merge_executor.py`
- [x] MergeReport dataclass 包含完整字段（id、strategy、input/merged/dropped/conflict patch_count、input/merged/dropped/conflict patch_ids、merge_reason、fallback_used、warnings）
- [x] merge() 方法接受 patches、base_prompt、merge_strategy，返回 (merged_patches, merge_report)
- [x] 接入旧系统 TreeReducePatchMerger，实现 tree_merge 策略
- [x] 实现 ExtractionPatch/AnalysisPatch ↔ 旧系统 Patch 数据结构转换
- [x] merge 后重新 validate（PatchValidator），失败标记 rejection_reason="MERGED_PATCH_VALIDATION_FAILED"
- [x] passthrough fallback：真实 merge 失败时回退，fallback_used=true
- [x] hierarchical_merge 策略接口保留（本阶段非必须完整实现）
- [x] 单元测试覆盖：passthrough fallback、tree merge 成功、merge 后 validate、invalid merged patch 被拒绝、merge report 字段完整

### ToxicityTestExecutor
- [x] ToxicityTestExecutor 创建 `executors/toxicity_executor.py`
- [x] ToxicityReport dataclass 包含完整字段（id、mode、tested/safe/toxic patch_count、toxic_sample_ids、safe/toxic patch_ids、patch_test_records、early_stop_enabled）
- [x] PatchTestRecord dataclass 包含完整字段（patch_id、status、tested/broken/fixed sample_ids、stop_reason）
- [x] test() 方法接受 base_prompt、candidate_patches、toxic_sample_ids、sample_set、executor_set、mode、early_stop
- [x] ineffective patch 剔除：source_sample_ids 全部属于 unchanged_wrong 的 patch 标记为 INEFFECTIVE
- [x] patch 按来源样本难度排序（patch_difficulty desc、source_sample_count desc、patch_id asc）
- [x] greedy 测毒循环：逐 patch 应用到 cumulative_prompt，在 toxic_sample_ids 上测试
- [x] extraction 模式测毒使用 ExtractionExecutor + EvaluationExecutor + PatchApplyExecutor
- [x] analysis 模式测毒使用 AnalysisExecutor + PatchApplyExecutor + 已有 extraction_results
- [x] early stop：toxic sample 被搞坏时立即拒绝当前 patch，进入下一个 patch
- [x] 空 toxic set 跳过：所有非 ineffective patch 进入 safe_patches，标记 skipped_reason="NO_TOXIC_SAMPLES"
- [x] 单元测试覆盖：空 toxic set 跳过、safe patch 接受、toxic patch 拒绝、early stop 生效、patch 排序、patch_test_records 生成

### Extraction Stage 接入
- [x] Step 5 使用 MergeExecutor.merge() 替换 passthrough merge，merge 后重新 validate
- [x] Step 6 沿用 PR2 的 PatchApplyExecutor + ExtractionExecutor + EvaluationExecutor
- [x] Step 7 实现 transition 分类（fixed/broken/unchanged_wrong/unchanged_correct）
- [x] Step 7 剔除 ineffective patches（source_sample_ids 全部属于 unchanged_wrong）
- [x] Step 7 构造 toxic_sample_ids（broken sample ids）
- [x] Step 7 调用 ToxicityTestExecutor.test() 执行 greedy 测毒
- [x] Step 7 对 safe_patches 执行二次 merge（MergeExecutor）
- [x] Step 7 应用 final_merged_patches 到 base_prompt（不是 trial_prompt）
- [x] Step 7 空 safe_patches 时 no_progress=true，accepted_prompt=None
- [x] Step 9 基于 final_prompt 做最终测试

### Analysis Stage 接入
- [x] Step 4 使用 MergeExecutor.merge() 替换 passthrough merge
- [x] Step 5 沿用 PR2 的 PatchApplyExecutor + AnalysisExecutor
- [x] Step 6 实现 analysis transition 分类
- [x] Step 6 剔除 ineffective analysis patches
- [x] Step 6 构造 analysis_toxic_sample_ids
- [x] Step 6 调用 ToxicityTestExecutor.test(mode="analysis") 执行 greedy 测毒
- [x] Step 6 对 safe analysis patches 执行二次 merge
- [x] Step 6 应用 final_merged_patches 到 base analysis prompt
- [x] Step 6 analysis no_progress 不影响 extraction prompt
- [x] Step 8 基于 final_analysis_prompt 做最终测试

### Phase / Factory / Runner
- [x] PromptOptimizationPhase 注入 merge_executor 和 toxicity_test_executor
- [x] factory.py 构建 MergeExecutor 实例（替换 _MockMergeExecutor）
- [x] factory.py 构建 ToxicityTestExecutor 实例（替换 _MockToxicityTestExecutor）
- [x] runner.py 将新 executor 注入到 PromptOptimizationPhase

### Artifact
- [x] extraction/ 下保存 initial_merge_report.json、transition_report.json、ineffective_patches.jsonl、toxicity_report.json、safe_patches.jsonl、toxic_patches.jsonl、final_merge_report.json、final_merged_patches.jsonl、patch_test_records.jsonl
- [x] analysis/ 下保存 initial_merge_report.json、transition_report.json、ineffective_patches.jsonl、toxicity_report.json、safe_patches.jsonl、toxic_patches.jsonl、final_merge_report.json、final_merged_patches.jsonl、patch_test_records.jsonl

### 集成测试
- [x] validated patches → initial merge → initial apply → patched eval → toxic sample set → greedy toxicity test → final merge → final apply → final eval 链路跑通
- [x] safe patch 能进入 final prompt
- [x] ineffective patch 被剔除
- [x] toxic patch 被拒绝
- [x] safe patch 二次 merge 后 prompt 改变
- [x] final prompt 指标不低于 base prompt
- [x] analysis ineffective patch 被剔除
- [x] analysis toxic patch 被拒绝
- [x] safe analysis patch 二次 merge
- [x] analysis no_progress 不影响 extraction prompt

### Smoke 测试与验收
- [x] factory.py 不再为 merge 返回 mock executor
- [x] factory.py 不再为 toxicity_test 返回 mock executor
- [x] CLI 至少能跑通 1 轮真实 merge + 测毒流程
- [x] toxicity_report 包含 tested/toxic/safe/broken_sample_ids
- [x] patch_test_records 可追踪
- [x] extraction prompt 最终推进只基于 safe patches

## PR 4：Compression、Artifact 收敛与端到端验收

### CompressionExecutor
- [x] CompressionExecutor 创建 `executors/compression_executor.py`
- [x] CompressionReport dataclass 包含完整字段（id、prompt_type、base/compressed_prompt_id、triggered、accepted、rejected_reason、line/char count before/after、base/pre/post accuracy、broken/fixed sample_ids、warnings、still_over_limit）
- [x] 超限检测：line_count > line_limit 或 char_count > char_limit
- [x] 未超限时 compressed=false, accepted=false, rejected_reason="NOT_NEEDED"
- [x] 接入旧系统 CompressionEngine，实现 llm_compress_preserve_behavior 策略
- [x] 压缩约束检查：不修改 immutable section、不修改 output schema、不删除 section ID、不改变 prompt_type
- [x] 压缩后重新测试（extraction 模式：ExtractionExecutor + EvaluationExecutor；analysis 模式：AnalysisExecutor）
- [x] 接受标准：post_compression_accuracy >= pre_compression_accuracy 且 broken_sample_ids 为空
- [x] 压缩后仍超限但指标不降时标记 still_over_limit=true
- [x] 压缩失败保留原 prompt
- [x] 单元测试覆盖：未超限不压缩、超 line/char_limit 触发、不降接受、下降拒绝、不修改 immutable、可 render、report 字段完整

### Stage 接入
- [x] ExtractionPromptOptimizationStage Step 8 使用 CompressionExecutor.compress_if_needed()
- [x] AnalysisPromptOptimizationStage Step 7 使用 CompressionExecutor.compress_if_needed()
- [x] 压缩被接受时 accepted_prompt = compressed_prompt
- [x] 压缩被拒绝时保留未压缩 prompt
- [x] factory.py 用真实 CompressionExecutor 替换 _MockCompressionExecutor
- [x] PromptOptimizationPhase 将 compression_executor 注入到两个 stage

### Artifact 收敛
- [x] Run 级 artifact 完整：run_config.yaml、run_plan.json、run_summary.json、prompt_versions.jsonl、patch_apply_reports.jsonl、final_extraction_prompt.json、final_analysis_prompt.json、final_fewshot_examples.jsonl、structured_extraction_prompt.json、structured_analysis_prompt.json
- [x] Prompt iteration artifact 完整：sample_batch.json、sample_traces.jsonl、sample_state_before/after.json、batch_size_controller_before/after.json
- [x] Extraction artifact 完整（24 个文件，含 compression_report.json）
- [x] Analysis artifact 完整（21 个文件，含 compression_report.json）
- [x] Few-shot iteration artifact 完整：sample_batch.json、sample_traces.jsonl、fewshot/（6 个文件）
- [x] final_fewshot_examples.jsonl 保存到 Run 顶层目录

### Run Summary 和 Mock 边界
- [x] run_summary.json 包含完整字段（run_id、status、start/end_time、duration、prompt_structuring_status、prompt_optimization 汇总、analysis_prompt 汇总、fewshot_optimization 汇总）
- [x] use_mock=false 时缺少 model_client 报错
- [x] 真实运行模式下 merge / toxicity / patch apply / compression 不 fallback 到 mock
- [x] runner.py yaml 导入顺序 bug 已修复（如有）

### 端到端 Smoke
- [x] 准备 10～20 条小样本数据集（data/smoke_samples.jsonl）
- [x] 创建 smoke 测试配置（configs/refactored_smoke.yaml）
- [x] CLI 能跑通真实小数据集
- [x] smoke 验收产物存在（run_summary、final_extraction_prompt、final_analysis_prompt、final_fewshot_examples、compression_report、sample_traces、toxicity_report）
- [x] 完整三阶段 Run 无 mock output（use_mock=false 时）

### 最终验收
- [x] factory.py 不再为 compression 返回 mock executor
- [x] prompt 超限时触发压缩
- [x] 压缩后不降才接受
- [x] 一次完整 Run 产物完整
- [x] CLI 能跑通真实 10～20 条样本
- [x] 三阶段全流程无 mock（use_mock=false 时）
- [x] run_summary.json 能快速说明本次 run 的收益和风险

## 最终验收标准（跨 PR）

- [x] 当前 refactored 主流程不再依赖 mock 抽取
- [x] extraction prompt 优化可以真实调用模型
- [x] analysis prompt 优化可以真实调用模型
- [x] few-shot phase 可以真实调用模型
- [x] patch 可以真实应用到 StructuredPrompt
- [x] tree-merge 真实执行
- [x] toxicity test 真实执行
- [x] prompt 压缩真实执行
- [x] 所有关键 artifact 可追踪
- [x] 小数据集端到端 smoke 可运行
- [x] 每轮 batch size 能基于真实指标变化调整
- [x] SampleState 和 SampleTrace 基于真实结果更新
- [x] CLI 能完成完整三阶段 Run
- [x] 输出结果可以用于判断 prompt 是否真实变好
