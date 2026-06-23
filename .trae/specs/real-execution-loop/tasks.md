# Tasks

本 spec 按 4 个 PR 拆分，每个 PR 是一组可独立验证的任务。任务间有严格依赖：PR1 → PR2 → PR3 → PR4。

---

## PR 1：真实执行与评估接入

- [x] Task 1: 创建 executors 目录和基础接口
  - [x] SubTask 1.1: 创建 `mmap_optimizer/executors/__init__.py`
  - [x] SubTask 1.2: 定义各 executor 的 Protocol/ABC 接口（ExtractionExecutor、EvaluationExecutor、AnalysisExecutor、FewshotExecutor）
  - [x] SubTask 1.3: 创建 executor 工厂函数，从配置构建 executor 实例

- [x] Task 2: 实现 StructuredPromptRenderer
  - [x] SubTask 2.1: 在 `structured_prompt.py` 中新增 `render_to_markdown()` 方法，输出完整 Markdown（复用现有 `to_markdown()` 逻辑并增强）
  - [x] SubTask 2.2: 新增 `render_with_fewshot()` 方法，支持在 prompt 中注入 few-shot 示例
  - [x] SubTask 2.3: 编写单元测试验证 render 输出

- [x] Task 3: 实现 ExtractionExecutor
  - [x] SubTask 3.1: 创建 `executors/extraction_executor.py`，接入旧系统 `ModelClient`（`mmap_optimizer/model/client.py`）
  - [x] SubTask 3.2: 实现 `render_prompt()` 将 StructuredPrompt 转为 system message
  - [x] SubTask 3.3: 实现 `build_messages()` 组装样本图片、文本和 metadata 为 user message（复用 `testing/prompt_test_runner.py` 的 `_asset_to_image_part`）
  - [x] SubTask 3.4: 实现 `execute()` 调用 `model_client.complete_multimodal`，保留 raw_output
  - [x] SubTask 3.5: 实现 `parse_output()` 将 raw_output 解析为 parsed_output（JSON 解析，失败时 status="invalid"）
  - [x] SubTask 3.6: 编写单元测试（使用 MockModelClient）

- [x] Task 4: 实现 EvaluationExecutor
  - [x] SubTask 4.1: 创建 `executors/evaluation_executor.py`
  - [x] SubTask 4.2: 实现字段级 exact match 比较（支持 primary answer 字段配置）
  - [x] SubTask 4.3: 实现 normalize 函数（支持 label mapping，复用 `evaluation/evaluator.py` 的 `normalize_label`）
  - [x] SubTask 4.4: 实现 invalid 输出识别（parsed_output 为 None 或 schema 校验失败）
  - [x] SubTask 4.5: 实现 `evaluate()` 返回 EvalRecord，更新 SampleState 的 error_ema 和 difficulty_score
  - [x] SubTask 4.6: 编写单元测试

- [x] Task 5: 实现 AnalysisExecutor
  - [x] SubTask 5.1: 创建 `executors/analysis_executor.py`，接入旧系统 `ModelClient`
  - [x] SubTask 5.2: 实现 `build_analysis_messages()` 组装 analysis prompt + extraction result + sample + ground truth
  - [x] SubTask 5.3: 实现 `execute()` 调用模型，解析 judgement
  - [x] SubTask 5.4: 实现 `judge_correctness()` 对比 judgement 与 ground truth 判定 analysis_correct
  - [x] SubTask 5.5: 对错误样本生成 patch_suggestion
  - [x] SubTask 5.6: 编写单元测试

- [x] Task 6: 实现 FewshotExecutor 基础抽取能力
  - [x] SubTask 6.1: 创建 `executors/fewshot_executor.py`
  - [x] SubTask 6.2: 实现 few-shot message 构造（复用 `testing/prompt_test_runner.py` 的 `_build_fewshot_messages` 和 `_parse_fewshot_slots`）
  - [x] SubTask 6.3: 实现 `execute_extraction()` 使用 locked prompt + few-shot set 真实抽取
  - [x] SubTask 6.4: 实现 `execute_validation()` 使用新 few-shot set 重新抽取
  - [x] SubTask 6.5: 编写单元测试

- [x] Task 7: 接入 ExtractionExecutor 和 EvaluationExecutor 到 ExtractionPromptOptimizationStage
  - [x] SubTask 7.1: 修改 `ExtractionPromptOptimizationStage.__init__` 接受 executor 参数
  - [x] SubTask 7.2: 替换 Step 1 mock 抽取为 ExtractionExecutor
  - [x] SubTask 7.3: 替换 Step 2 mock 评估为 EvaluationExecutor
  - [x] SubTask 7.4: 替换 Step 3 mock 分析为 AnalysisExecutor
  - [x] SubTask 7.5: 确保 SampleState 基于真实评估更新

- [x] Task 8: 接入 executor 到 AnalysisPromptOptimizationStage 和 FewshotOptimizationPhase
  - [x] SubTask 8.1: 修改 `AnalysisPromptOptimizationStage.__init__` 接受 executor 参数
  - [x] SubTask 8.2: 替换 Step 1 为复用 extraction stage 的 analysis_results
  - [x] SubTask 8.3: 修改 `FewshotOptimizationPhase.__init__` 接受 FewshotExecutor
  - [x] SubTask 8.4: 替换 few-shot mock 抽取和验证为 FewshotExecutor

- [x] Task 9: 修改 PromptOptimizationPhase 和 Runner 注入 executor
  - [x] SubTask 9.1: 修改 `PromptOptimizationPhase.__init__` 接受 executor 字典
  - [x] SubTask 9.2: 修改 `MMAPRunner` 从配置构建 executor 并注入
  - [x] SubTask 9.3: 更新配置结构支持 model client 配置

- [x] Task 10: PR1 集成验证
  - [x] SubTask 10.1: 编写集成测试：extraction executor + evaluator 产出真实 correct/wrong/invalid
  - [x] SubTask 10.2: 编写集成测试：analysis executor 产出真实分析结果
  - [x] SubTask 10.3: 验证无 mock status="correct" 硬编码

---

## PR 2：真实 Patch 生成、应用与 Prompt 版本推进

- [x] Task 11: 实现 PatchValidator
  - [x] SubTask 11.1: 创建 `executors/patch_validator.py`，实现统一校验逻辑
  - [x] SubTask 11.2: 实现校验项：target_section_id 存在性、mutable 检查、operation_type 合法性、content 非空、source_sample_ids 非空且存在、output schema 保护、mock/placeholder 内容检测
  - [x] SubTask 11.3: 实现 `validate()` 单个 patch 校验，通过返回 status="candidate"，失败返回 status="rejected" + rejection_reason="VALIDATION_FAILED:<reason>"
  - [x] SubTask 11.4: 实现 `validate_batch()` 批量校验，返回 (validated_patches, rejected_patches)
  - [x] SubTask 11.5: 编写单元测试覆盖所有校验项

- [x] Task 12: 实现 PatchGenerationExecutor
  - [x] SubTask 12.1: 创建 `executors/patch_generation_executor.py`
  - [x] SubTask 12.2: 实现 `generate_extraction_patches()` 基于 AnalysisResult 生成 ExtractionPatch，只从 analysis_correct=true 的样本生成
  - [x] SubTask 12.3: 实现 `generate_analysis_patches()` 基于 ReflectionResult 生成 AnalysisPatch，只从 reflection_success=true 且有 patch_suggestion 的样本生成
  - [x] SubTask 12.4: 实现 patch 来源规则：每个 patch 必须绑定 source_sample_ids，来源不明拒绝生成
  - [x] SubTask 12.5: 实现 patch 目标规则：target_section_id 必须存在于 prompt 中，否则拒绝
  - [x] SubTask 12.6: 实现 patch 内容规则：content 不允许为空或为 "Mock patch content"、"TODO"、"N/A" 等占位符
  - [x] SubTask 12.7: 集成 PatchValidator，生成后立即校验，产出 draft_patches、validated_patches、rejected_patches
  - [x] SubTask 12.8: 编写单元测试

- [x] Task 13: 实现 PatchApplyExecutor 和 PatchApplyReport
  - [x] SubTask 13.1: 创建 `executors/patch_apply_executor.py`
  - [x] SubTask 13.2: 定义 `PatchApplyReport` dataclass：id、base_prompt_id、new_prompt_id、applied_patch_ids、rejected_patch_ids、modified_section_ids、before_hash、after_hash、changed、warnings
  - [x] SubTask 13.3: 实现 `apply()` 方法，接受 base_prompt 和 patches，返回 (new_prompt, apply_report)
  - [x] SubTask 13.4: 实现 replace 操作：替换目标 section 的 content
  - [x] SubTask 13.5: 实现 append 操作：在目标 section content 末尾追加
  - [x] SubTask 13.6: 实现 delete 操作：默认禁用，需配置显式开启；只清空 content 不删除 section
  - [x] SubTask 13.7: 实现 immutable section 拒绝逻辑，rejection_reason="IMMUTABLE_SECTION"
  - [x] SubTask 13.8: 实现 prompt version 递增：new_prompt.version = base_prompt.version + 1，parent_id = base_prompt.id，metadata["applied_patch_ids"] 记录已应用 patch
  - [x] SubTask 13.9: 实现 changed 判定：比较 before_hash 和 after_hash，相同则 changed=false
  - [x] SubTask 13.10: 编写单元测试（replace、append、delete 禁用、immutable 拒绝、version 递增、changed 判定）

- [x] Task 14: 接入 PatchGenerationExecutor 和 PatchApplyExecutor 到 ExtractionPromptOptimizationStage
  - [x] SubTask 14.1: 修改 `__init__` 接受 patch_generation_executor 和 patch_apply_executor 参数
  - [x] SubTask 14.2: 替换 Step 4 mock patch 生成为 PatchGenerationExecutor + PatchValidator，产出 draft_patches、validated_patches、rejected_patches
  - [x] SubTask 14.3: 替换 Step 5 mock merge 为 passthrough merge，保留 merge report（merge_strategy="passthrough"）
  - [x] SubTask 14.4: 替换 Step 6 mock 应用为 PatchApplyExecutor.apply()，如果 changed=true 则使用 ExtractionExecutor + EvaluationExecutor 重新抽取和评估
  - [x] SubTask 14.5: Step 6 产出 patched_prompt.json、patch_apply_report.json、patched_results.jsonl、patched_eval.jsonl
  - [x] SubTask 14.6: 替换 Step 7 mock 测毒为 patch set 级 transition 分类（fixed/broken/unchanged_wrong/unchanged_correct）
  - [x] SubTask 14.7: Step 7 接受规则：fixed > 0 且 broken = 0 则接受；broken > 0 则回滚；fixed = 0 则 no_progress
  - [x] SubTask 14.8: 替换 Step 9 mock final test 为真实 ExtractionExecutor + EvaluationExecutor
  - [x] SubTask 14.9: Step 9 接受时 final_prompt = accepted_prompt，拒绝时 final_prompt = base_prompt + no_progress=true
  - [x] SubTask 14.10: 新增 accepted_prompt 属性供 PromptOptimizationPhase 读取

- [x] Task 15: 接入 PatchGenerationExecutor 和 PatchApplyExecutor 到 AnalysisPromptOptimizationStage
  - [x] SubTask 15.1: 修改 `__init__` 接受 patch_generation_executor 和 patch_apply_executor 参数
  - [x] SubTask 15.2: 替换 Step 3 mock patch 生成为 PatchGenerationExecutor.generate_analysis_patches() + PatchValidator
  - [x] SubTask 15.3: 替换 Step 4 mock merge 为 passthrough merge
  - [x] SubTask 15.4: 替换 Step 5 mock 应用为 PatchApplyExecutor.apply()，changed=true 时复用本轮 extraction results 重新执行 AnalysisExecutor
  - [x] SubTask 15.5: 替换 Step 6 mock 测毒为 patch set 级判断：patched_analysis_accuracy >= base_analysis_accuracy 且无 regression 则接受
  - [x] SubTask 15.6: 替换 Step 8 mock final test 为真实 AnalysisExecutor
  - [x] SubTask 15.7: 新增 accepted_prompt 属性供 PromptOptimizationPhase 读取

- [x] Task 16: 修改 PromptOptimizationPhase 注入新 executor 并真正更新 prompt
  - [x] SubTask 16.1: 修改 `__init__` 接受 patch_generation_executor 和 patch_apply_executor
  - [x] SubTask 16.2: 将新 executor 传给 ExtractionPromptOptimizationStage 和 AnalysisPromptOptimizationStage
  - [x] SubTask 16.3: 替换 mock patch 应用（仅自增 version）为使用 stage.accepted_prompt 更新当前 prompt
  - [x] SubTask 16.4: 实现 prompt lineage 记录：base_prompt_id、new_prompt_id、version、applied_patch_ids、iteration、stage
  - [x] SubTask 16.5: 保存 prompt_versions.jsonl 和 patch_apply_reports.jsonl

- [x] Task 17: 修改 factory 和 runner 构建并注入新 executor
  - [x] SubTask 17.1: 在 factory.py 中构建 PatchGenerationExecutor 和 PatchApplyExecutor 实例
  - [x] SubTask 17.2: 在 factory.py 中构建 PatchValidator 实例
  - [x] SubTask 17.3: 在 runner.py 中将新 executor 注入到 PromptOptimizationPhase

- [x] Task 18: 补齐 PR2 阶段 Artifact
  - [x] SubTask 18.1: 保存 extraction/ 下 artifact：base_results、base_eval、analysis_results、draft_patches、validated_patches、rejected_patches、initial_merge_report、patched_prompt、patch_apply_report、patched_results、patched_eval、final_prompt、final_results、final_eval、metrics
  - [x] SubTask 18.2: 保存 analysis/ 下 artifact：base_metrics、reflection_results、draft_patches、validated_patches、rejected_patches、initial_merge_report、patched_analysis_prompt、patch_apply_report、patched_analysis_results、final_analysis_prompt、final_analysis_results、metrics
  - [x] SubTask 18.3: 保存 run-level artifact：prompt_versions.jsonl、patch_apply_reports.jsonl、run_summary.json

- [x] Task 19: PR2 集成测试
  - [x] SubTask 19.1: 编写集成测试：analysis result → extraction patch → validate → apply → render
  - [x] SubTask 19.2: 编写集成测试：reflection result → analysis patch → validate → apply → render
  - [x] SubTask 19.3: 编写集成测试：patched prompt 重新执行 extraction
  - [x] SubTask 19.4: 编写集成测试：patched analysis prompt 重新执行 analysis
  - [x] SubTask 19.5: 编写集成测试：broken sample 出现时回滚
  - [x] SubTask 19.6: 编写集成测试：fixed 样本出现且无 broken 时接受

- [x] Task 20: PR2 Smoke 测试与验收
  - [x] SubTask 20.1: 使用 3～5 条最小样本验证流程跑通：patch generated → patch applied → prompt changed → final eval generated
  - [x] SubTask 20.2: 验证 accepted patch 能修改指定 section
  - [x] SubTask 20.3: 验证 output schema section 不可修改
  - [x] SubTask 20.4: 验证 final prompt 能 render 成模型输入
  - [x] SubTask 20.5: 验证 prompt version 真实变化
  - [x] SubTask 20.6: 验证 CLI 能跑通至少 1 轮 prompt optimization 并产生真实 prompt 变化

---

## PR 3：真实 Merge 与 Greedy 测毒

- [x] Task 21: 实现 MergeExecutor
  - [x] SubTask 21.1: 创建 `executors/merge_executor.py`
  - [x] SubTask 21.2: 定义 `MergeReport` dataclass：id、strategy、input_patch_count、merged_patch_count、dropped_patch_count、conflict_count、input_patch_ids、merged_patch_ids、dropped_patch_ids、conflict_patch_ids、merge_reason、fallback_used、warnings
  - [x] SubTask 21.3: 实现 `merge()` 方法，接受 patches、base_prompt、merge_strategy，返回 (merged_patches, merge_report)
  - [x] SubTask 21.4: 接入旧系统 `TreeReducePatchMerger`（`patch/tree_reduce.py`），实现 tree_merge 策略
  - [x] SubTask 21.5: 实现数据结构转换：ExtractionPatch/AnalysisPatch ↔ 旧系统 Patch
  - [x] SubTask 21.6: 实现 merge 后重新 validate（使用 PatchValidator），失败标记 rejection_reason="MERGED_PATCH_VALIDATION_FAILED"
  - [x] SubTask 21.7: 实现 passthrough fallback：真实 merge 失败时回退为 merged_patches = validated_patches，fallback_used=true
  - [x] SubTask 21.8: 保留 hierarchical_merge 策略接口（本阶段非必须完整实现）
  - [x] SubTask 21.9: 编写单元测试覆盖：passthrough fallback、tree merge 成功、merge 后 validate、invalid merged patch 被拒绝、merge report 字段完整

- [x] Task 22: 实现 ToxicityTestExecutor
  - [x] SubTask 22.1: 创建 `executors/toxicity_executor.py`
  - [x] SubTask 22.2: 定义 `ToxicityReport` dataclass：id、mode、tested_patch_count、safe_patch_count、toxic_patch_count、toxic_sample_ids、safe_patch_ids、toxic_patch_ids、patch_test_records、early_stop_enabled
  - [x] SubTask 22.3: 定义 `PatchTestRecord` dataclass：patch_id、status(safe/toxic/skipped)、tested_sample_ids、broken_sample_ids、fixed_sample_ids、stop_reason
  - [x] SubTask 22.4: 实现 `test()` 方法，接受 base_prompt、candidate_patches、toxic_sample_ids、sample_set、executor_set、mode、early_stop，返回 (safe_patches, toxic_patches, toxicity_report)
  - [x] SubTask 22.5: 实现 ineffective patch 剔除：source_sample_ids 全部属于 unchanged_wrong 的 patch 标记为 INEFFECTIVE，不进入测毒
  - [x] SubTask 22.6: 实现 patch 按来源样本难度排序：patch_difficulty desc、source_sample_count desc、patch_id asc
  - [x] SubTask 22.7: 实现 greedy 测毒循环：逐 patch 应用到 cumulative_prompt，在 toxic_sample_ids 上测试
  - [x] SubTask 22.8: 实现 extraction 模式测毒：使用 ExtractionExecutor + EvaluationExecutor + PatchApplyExecutor
  - [x] SubTask 22.9: 实现 analysis 模式测毒：使用 AnalysisExecutor + PatchApplyExecutor + 已有 extraction_results
  - [x] SubTask 22.10: 实现 early stop：toxic sample 被搞坏时立即拒绝当前 patch，进入下一个 patch
  - [x] SubTask 22.11: 实现空 toxic set 跳过：所有非 ineffective patch 进入 safe_patches，标记 skipped_reason="NO_TOXIC_SAMPLES"
  - [x] SubTask 22.12: 编写单元测试覆盖：空 toxic set 跳过、safe patch 接受、toxic patch 拒绝、early stop 生效、patch 排序、patch_test_records 生成

- [x] Task 23: 接入 MergeExecutor 和 ToxicityTestExecutor 到 ExtractionPromptOptimizationStage
  - [x] SubTask 23.1: 修改 `__init__` 接受 merge_executor 和 toxicity_test_executor 参数
  - [x] SubTask 23.2: 替换 Step 5 passthrough merge 为 MergeExecutor.merge()，merge 后重新 validate
  - [x] SubTask 23.3: Step 6 沿用 PR2 的 PatchApplyExecutor + ExtractionExecutor + EvaluationExecutor 进行 initial apply 和回归测试
  - [x] SubTask 23.4: Step 7 实现 transition 分类（fixed/broken/unchanged_wrong/unchanged_correct）
  - [x] SubTask 23.5: Step 7 实现 ineffective patch 剔除（source_sample_ids 全部属于 unchanged_wrong）
  - [x] SubTask 23.6: Step 7 构造 toxic_sample_ids（broken sample ids）
  - [x] SubTask 23.7: Step 7 调用 ToxicityTestExecutor.test() 执行 greedy 测毒
  - [x] SubTask 23.8: Step 7 对 safe_patches 执行二次 merge（使用 MergeExecutor）
  - [x] SubTask 23.9: Step 7 应用 final_merged_patches 到 base_prompt（不是 trial_prompt）
  - [x] SubTask 23.10: Step 7 空 safe_patches 时 no_progress=true，accepted_prompt=None
  - [x] SubTask 23.11: Step 9 基于 final_prompt 做最终测试（沿用 PR2）

- [x] Task 24: 接入 MergeExecutor 和 ToxicityTestExecutor 到 AnalysisPromptOptimizationStage
  - [x] SubTask 24.1: 修改 `__init__` 接受 merge_executor 和 toxicity_test_executor 参数
  - [x] SubTask 24.2: 替换 Step 4 passthrough merge 为 MergeExecutor.merge()
  - [x] SubTask 24.3: Step 5 沿用 PR2 的 PatchApplyExecutor + AnalysisExecutor 进行 initial apply 和回归测试
  - [x] SubTask 24.4: Step 6 实现 analysis transition 分类
  - [x] SubTask 24.5: Step 6 剔除 ineffective analysis patches
  - [x] SubTask 24.6: Step 6 构造 analysis_toxic_sample_ids
  - [x] SubTask 24.7: Step 6 调用 ToxicityTestExecutor.test(mode="analysis") 执行 greedy 测毒
  - [x] SubTask 24.8: Step 6 对 safe analysis patches 执行二次 merge
  - [x] SubTask 24.9: Step 6 应用 final_merged_patches 到 base analysis prompt
  - [x] SubTask 24.10: Step 6 analysis no_progress 不影响 extraction prompt
  - [x] SubTask 24.11: Step 8 基于 final_analysis_prompt 做最终测试（沿用 PR2）

- [x] Task 25: 修改 PromptOptimizationPhase 和 factory 注入新 executor
  - [x] SubTask 25.1: 修改 `PromptOptimizationPhase.__init__` 接受 merge_executor 和 toxicity_test_executor
  - [x] SubTask 25.2: 将新 executor 传给 ExtractionPromptOptimizationStage 和 AnalysisPromptOptimizationStage
  - [x] SubTask 25.3: 在 factory.py 中构建 MergeExecutor 实例（替换 _MockMergeExecutor）
  - [x] SubTask 25.4: 在 factory.py 中构建 ToxicityTestExecutor 实例（替换 _MockToxicityTestExecutor）
  - [x] SubTask 25.5: 在 runner.py 中将新 executor 注入到 PromptOptimizationPhase

- [x] Task 26: 补齐 PR3 阶段 Artifact
  - [x] SubTask 26.1: 保存 extraction/ 下新增 artifact：initial_merge_report.json、transition_report.json、ineffective_patches.jsonl、toxicity_report.json、safe_patches.jsonl、toxic_patches.jsonl、final_merge_report.json、final_merged_patches.jsonl、patch_test_records.jsonl
  - [x] SubTask 26.2: 保存 analysis/ 下新增 artifact：initial_merge_report.json、transition_report.json、ineffective_patches.jsonl、toxicity_report.json、safe_patches.jsonl、toxic_patches.jsonl、final_merge_report.json、final_merged_patches.jsonl、patch_test_records.jsonl

- [x] Task 27: PR3 集成测试
  - [x] SubTask 27.1: 编写集成测试：validated patches → initial merge → initial apply → patched eval → toxic sample set → greedy toxicity test → final merge → final apply → final eval
  - [x] SubTask 27.2: 验证 safe patch 能进入 final prompt
  - [x] SubTask 27.3: 验证 ineffective patch 被剔除
  - [x] SubTask 27.4: 验证 toxic patch 被拒绝
  - [x] SubTask 27.5: 验证 safe patch 二次 merge 后 prompt 改变
  - [x] SubTask 27.6: 验证 final prompt 指标不低于 base prompt
  - [x] SubTask 27.7: 编写 analysis 集成测试：analysis ineffective patch 被剔除、analysis toxic patch 被拒绝、safe analysis patch 二次 merge、analysis no_progress 不影响 extraction prompt

- [x] Task 28: PR3 Smoke 测试与验收
  - [x] SubTask 28.1: 验证 factory.py 不再为 merge 返回 mock executor
  - [x] SubTask 28.2: 验证 factory.py 不再为 toxicity_test 返回 mock executor
  - [x] SubTask 28.3: 验证 CLI 至少能跑通 1 轮真实 merge + 测毒流程
  - [x] SubTask 28.4: 验证 toxicity_report 包含 tested/toxic/safe/broken_sample_ids
  - [x] SubTask 28.5: 验证 patch_test_records 可追踪
  - [x] SubTask 28.6: 验证 extraction prompt 最终推进只基于 safe patches

---

## PR 4：Compression、Artifact 收敛与端到端验收

- [x] Task 29: 实现 CompressionExecutor
  - [x] SubTask 29.1: 创建 `executors/compression_executor.py`
  - [x] SubTask 29.2: 定义 `CompressionReport` dataclass：id、prompt_type、base_prompt_id、compressed_prompt_id、triggered、accepted、rejected_reason、line_count_before、line_count_after、char_count_before、char_count_after、base_accuracy、pre_compression_accuracy、post_compression_accuracy、broken_sample_ids、fixed_sample_ids、warnings、still_over_limit
  - [x] SubTask 29.3: 实现超限检测（line_limit / char_limit），未超限时 compressed=false, accepted=false, rejected_reason="NOT_NEEDED"
  - [x] SubTask 29.4: 接入旧系统 `CompressionEngine`（`compression/engine.py`），实现 llm_compress_preserve_behavior 策略
  - [x] SubTask 29.5: 实现压缩约束检查：不修改 immutable section、不修改 output schema、不删除 section ID、不改变 prompt_type
  - [x] SubTask 29.6: 实现压缩后重新测试（extraction 模式：ExtractionExecutor + EvaluationExecutor；analysis 模式：AnalysisExecutor + 已有 extraction_results）
  - [x] SubTask 29.7: 实现接受标准：post_compression_accuracy >= pre_compression_accuracy 且 broken_sample_ids 为空才接受；压缩后仍超限但指标不降时标记 still_over_limit=true
  - [x] SubTask 29.8: 实现压缩失败保留原 prompt
  - [x] SubTask 29.9: 编写单元测试覆盖：未超限不压缩、超 line_limit 触发、超 char_limit 触发、压缩后不降接受、压缩后下降拒绝、不修改 immutable section、压缩后可 render、compression_report 字段完整

- [x] Task 30: 接入 CompressionExecutor 到 stages 和 factory
  - [x] SubTask 30.1: 替换 ExtractionPromptOptimizationStage Step 8 mock 压缩为 CompressionExecutor.compress_if_needed()
  - [x] SubTask 30.2: 替换 AnalysisPromptOptimizationStage Step 7 mock 压缩为 CompressionExecutor.compress_if_needed()
  - [x] SubTask 30.3: 压缩被接受时 accepted_prompt = compressed_prompt，压缩被拒绝时保留未压缩 prompt
  - [x] SubTask 30.4: 在 factory.py 中用真实 CompressionExecutor 替换 _MockCompressionExecutor
  - [x] SubTask 30.5: 在 PromptOptimizationPhase 中将 compression_executor 注入到两个 stage

- [x] Task 31: 补齐全链路 Artifact
  - [x] SubTask 31.1: 保存 Run 级 artifact：run_config.yaml、run_plan.json、run_summary.json、prompt_versions.jsonl、patch_apply_reports.jsonl、final_extraction_prompt.json、final_analysis_prompt.json、final_fewshot_examples.jsonl、structured_extraction_prompt.json、structured_analysis_prompt.json
  - [x] SubTask 31.2: 保存 Prompt iteration 级 artifact：sample_batch.json、sample_traces.jsonl、sample_state_before.json、sample_state_after.json、batch_size_controller_before.json、batch_size_controller_after.json
  - [x] SubTask 31.3: 补齐 extraction/ 下 compression_report.json
  - [x] SubTask 31.4: 补齐 analysis/ 下 compression_report.json
  - [x] SubTask 31.5: 保存 Few-shot iteration artifact：sample_batch.json、sample_traces.jsonl、fewshot/（base_results、base_eval、selected_examples、final_results、final_eval、metrics）
  - [x] SubTask 31.6: 保存 final_fewshot_examples.jsonl 到 Run 顶层目录

- [x] Task 32: 实现 Run Summary 和 Mock 边界收敛
  - [x] SubTask 32.1: 实现 run_summary.json 生成，包含完整字段（run_id、status、start/end_time、duration、prompt_structuring_status、prompt_optimization 汇总、analysis_prompt 汇总、fewshot_optimization 汇总）
  - [x] SubTask 32.2: 实现 use_mock=false 时缺少 model_client 报错逻辑
  - [x] SubTask 32.3: 真实运行模式下 merge / toxicity / patch apply / compression 不允许 fallback 到 mock
  - [x] SubTask 32.4: 修复 runner.py yaml 导入顺序 bug（如有）

- [x] Task 33: 准备小数据集和端到端 Smoke
  - [x] SubTask 33.1: 准备 10～20 条小样本数据集（data/smoke_samples.jsonl），包含正确/错误/可修复/可触发 toxic/可进 few-shot 的样本
  - [x] SubTask 33.2: 创建 smoke 测试配置（configs/smoke.yaml，rounds=1）
  - [x] SubTask 33.3: 编写端到端 smoke 测试脚本，验证三阶段 Run 完成
  - [x] SubTask 33.4: 验证 CLI 能跑通真实小数据集
  - [x] SubTask 33.5: 验证 smoke 验收产物存在（run_summary、final_extraction_prompt、final_analysis_prompt、final_fewshot_examples、compression_report、sample_traces、toxicity_report）

- [x] Task 34: PR4 最终验收
  - [x] SubTask 34.1: 验证 factory.py 不再为 compression 返回 mock executor
  - [x] SubTask 34.2: 验证 prompt 超限时触发压缩
  - [x] SubTask 34.3: 验证压缩后不降才接受
  - [x] SubTask 34.4: 验证一次完整 Run 产物完整
  - [x] SubTask 34.5: 验证 CLI 能跑通真实 10～20 条样本
  - [x] SubTask 34.6: 验证三阶段全流程无 mock（use_mock=false 时）
  - [x] SubTask 34.7: 验证 run_summary.json 能快速说明本次 run 的收益和风险

---

# Task Dependencies

- [Task 2] depends on [Task 1]（renderer 是 executor 的基础）
- [Task 3] depends on [Task 2]（ExtractionExecutor 需要 renderer）
- [Task 4] depends on [Task 1]（EvaluationExecutor 独立但需要接口定义）
- [Task 5] depends on [Task 2]（AnalysisExecutor 需要 renderer）
- [Task 6] depends on [Task 2, Task 3]（FewshotExecutor 复用 extraction 逻辑）
- [Task 7] depends on [Task 3, Task 4, Task 5]（接入需要 executor 实现）
- [Task 8] depends on [Task 5, Task 6, Task 7]
- [Task 9] depends on [Task 7, Task 8]
- [Task 10] depends on [Task 9]
- [Task 11] depends on [Task 10]（PR2 依赖 PR1 完成，PatchValidator 独立）
- [Task 12] depends on [Task 11]（PatchGenerationExecutor 需要 PatchValidator）
- [Task 13] depends on [Task 11]（PatchApplyExecutor 独立于 PatchGenerationExecutor，但需要 PatchValidator 的概念）
- [Task 14] depends on [Task 12, Task 13]（接入 stage 需要 generation 和 apply executor）
- [Task 15] depends on [Task 12, Task 13]（analysis stage 接入可与 extraction stage 接入并行）
- [Task 16] depends on [Task 14, Task 15]（PromptOptimizationPhase 需要 stage 接入完成）
- [Task 17] depends on [Task 16]（factory/runner 注入依赖 phase 改造完成）
- [Task 18] depends on [Task 17]（artifact 补齐依赖主流程跑通）
- [Task 19] depends on [Task 18]（集成测试依赖 artifact 可验证）
- [Task 20] depends on [Task 19]（smoke 测试依赖集成测试通过）
- [Task 21] depends on [Task 20]（PR3 依赖 PR2 完成，MergeExecutor 独立）
- [Task 22] depends on [Task 21]（ToxicityTestExecutor 需要 MergeExecutor 的概念，但可独立实现）
- [Task 23] depends on [Task 21, Task 22]（extraction stage 接入需要 merge 和 toxicity executor）
- [Task 24] depends on [Task 21, Task 22]（analysis stage 接入可与 extraction stage 接入并行）
- [Task 25] depends on [Task 23, Task 24]（phase/factory 注入依赖 stage 改造完成）
- [Task 26] depends on [Task 25]（artifact 补齐依赖主流程跑通）
- [Task 27] depends on [Task 26]（集成测试依赖 artifact 可验证）
- [Task 28] depends on [Task 27]（smoke 测试依赖集成测试通过）
- [Task 29] depends on [Task 28]（PR4 依赖 PR3 完成）
- [Task 30] depends on [Task 29]
- [Task 31] depends on [Task 30]
- [Task 32] depends on [Task 31]
- [Task 33] depends on [Task 32]
- [Task 34] depends on [Task 33]

## 可并行任务

- PR1 内：Task 3、Task 4、Task 5 可并行（各自独立的 executor 实现）
- PR2 内：Task 12、Task 13 可并行（PatchGenerationExecutor 和 PatchApplyExecutor 独立）
- PR2 内：Task 14、Task 15 可并行（extraction stage 和 analysis stage 接入独立）
- PR3 内：Task 21、Task 22 可并行（MergeExecutor 和 ToxicityTestExecutor 独立）
- PR3 内：Task 23、Task 24 可并行（extraction stage 和 analysis stage 接入独立）
