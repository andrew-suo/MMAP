# Tasks

本 spec 按 4 个 PR 拆分，每个 PR 是一组可独立验证的任务。任务间有严格依赖：PR1 → PR2 → PR3 → PR4。

---

## PR 1：真实执行与评估接入

- [x] Task 1: 创建 executors 目录和基础接口
  - [x] SubTask 1.1: 创建 `mmap_optimizer/refactored/executors/__init__.py`
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

## PR 2：真实 Patch Apply 与 Prompt Render

- [ ] Task 11: 实现 PatchApplyExecutor
  - [ ] SubTask 11.1: 创建 `executors/patch_apply_executor.py`
  - [ ] SubTask 11.2: 实现 `apply()` 方法：replace/insert_after/insert_before/delete 操作
  - [ ] SubTask 11.3: 实现 immutable section 拒绝逻辑
  - [ ] SubTask 11.4: 实现版本递增和 before/after 保存
  - [ ] SubTask 11.5: 实现 apply report 生成
  - [ ] SubTask 11.6: 编写单元测试（replace、append、delete、immutable 拒绝）

- [ ] Task 12: 实现 PatchGenerationExecutor
  - [ ] SubTask 12.1: 创建 `executors/patch_generation_executor.py`
  - [ ] SubTask 12.2: 实现 `generate_extraction_patches()` 基于 AnalysisResult 生成 ExtractionPatch
  - [ ] SubTask 12.3: 实现 `generate_analysis_patches()` 基于 ReflectionResult 生成 AnalysisPatch
  - [ ] SubTask 12.4: 接入 PatchValidator（`patch/validator.py`）验证生成的 patch
  - [ ] SubTask 12.5: 实现 patch 生成失败时记录 rejection_reason
  - [ ] SubTask 12.6: 编写单元测试

- [ ] Task 13: 接入 PatchApplyExecutor 和 PatchGenerationExecutor 到 stages
  - [ ] SubTask 13.1: 替换 ExtractionPromptOptimizationStage Step 4 mock patch 生成
  - [ ] SubTask 13.2: 替换 ExtractionPromptOptimizationStage Step 6 mock 应用为 PatchApplyExecutor + ExtractionExecutor
  - [ ] SubTask 13.3: 替换 ExtractionPromptOptimizationStage Step 9 mock 最终测试
  - [ ] SubTask 13.4: 替换 AnalysisPromptOptimizationStage Step 3 mock patch 生成
  - [ ] SubTask 13.5: 替换 AnalysisPromptOptimizationStage Step 5 mock 应用
  - [ ] SubTask 13.6: 替换 AnalysisPromptOptimizationStage Step 8 mock 最终测试
  - [ ] SubTask 13.7: 替换 PromptOptimizationPhase 中 mock patch 应用（行 147-150, 164-166）

- [ ] Task 14: PR2 集成验证
  - [ ] SubTask 14.1: 验证 accepted patch 能修改指定 section
  - [ ] SubTask 14.2: 验证 output schema section 不可修改
  - [ ] SubTask 14.3: 验证 final prompt 能 render 成模型输入
  - [ ] SubTask 14.4: 验证 prompt version 真实变化

---

## PR 3：真实 Merge 与 Greedy 测毒

- [ ] Task 15: 实现 MergeExecutor
  - [ ] SubTask 15.1: 创建 `executors/merge_executor.py`
  - [ ] SubTask 15.2: 接入旧系统 `TreeReducePatchMerger`（`patch/tree_reduce.py`）
  - [ ] SubTask 15.3: 实现数据结构转换：ExtractionPatch/AnalysisPatch ↔ 旧系统 Patch
  - [ ] SubTask 15.4: 实现 merge 后重新 validate
  - [ ] SubTask 15.5: 实现 merge report 生成（input/merged/dropped/conflict patch_ids）
  - [ ] SubTask 15.6: 实现 fallback 到 rule-based merge
  - [ ] SubTask 15.7: 编写单元测试

- [ ] Task 16: 实现 ToxicityTestExecutor
  - [ ] SubTask 16.1: 创建 `executors/toxicity_executor.py`
  - [ ] SubTask 16.2: 实现 patch 按 source sample 难度排序
  - [ ] SubTask 16.3: 实现 greedy 测毒循环（apply patch → 在 toxic_sample_ids 上测试 → 判定）
  - [ ] SubTask 16.4: 实现 early stop（toxic sample 失败立即拒绝）
  - [ ] SubTask 16.5: 实现空 toxic set 跳过逻辑
  - [ ] SubTask 16.6: 实现 toxicity report 生成（tested/toxic/safe/broken_sample_ids）
  - [ ] SubTask 16.7: 编写单元测试

- [ ] Task 17: 接入 MergeExecutor 和 ToxicityTestExecutor 到 stages
  - [ ] SubTask 17.1: 替换 ExtractionPromptOptimizationStage Step 5 mock merge
  - [ ] SubTask 17.2: 替换 ExtractionPromptOptimizationStage Step 7 mock 测毒
  - [ ] SubTask 17.3: 替换 AnalysisPromptOptimizationStage Step 4 mock merge
  - [ ] SubTask 17.4: 替换 AnalysisPromptOptimizationStage Step 6 mock 测毒

- [ ] Task 18: PR3 集成验证
  - [ ] SubTask 18.1: 验证 ineffective patch 被剔除
  - [ ] SubTask 18.2: 验证 toxic patch 被拒绝
  - [ ] SubTask 18.3: 验证 safe patch 进入 final merge
  - [ ] SubTask 18.4: 验证 early stop 生效
  - [ ] SubTask 18.5: 验证 toxicity_report 包含 tested/toxic/safe/broken_sample_ids

---

## PR 4：压缩、Artifact、端到端 Smoke

- [ ] Task 19: 实现 CompressionExecutor
  - [ ] SubTask 19.1: 创建 `executors/compression_executor.py`
  - [ ] SubTask 19.2: 接入旧系统 `CompressionEngine`（`compression/engine.py`）
  - [ ] SubTask 19.3: 实现超限检测（line_limit / char_limit）
  - [ ] SubTask 19.4: 实现压缩后重新测试和接受标准判断
  - [ ] SubTask 19.5: 实现压缩失败保留原 prompt
  - [ ] SubTask 19.6: 实现 compression report 生成
  - [ ] SubTask 19.7: 编写单元测试

- [ ] Task 20: 接入 CompressionExecutor 到 stages
  - [ ] SubTask 20.1: 替换 ExtractionPromptOptimizationStage Step 8 mock 压缩
  - [ ] SubTask 20.2: 替换 AnalysisPromptOptimizationStage Step 7 mock 压缩

- [ ] Task 21: 补齐全链路 Artifact
  - [ ] SubTask 21.1: 在 PromptOptimizationPhase 保存 extraction/ 下 12 个文件（base_results、base_eval、analysis_results、draft_patches、initial_merge_report、patched_results、patched_eval、toxicity_report、final_merge_report、final_results、final_eval、metrics）
  - [ ] SubTask 21.2: 在 PromptOptimizationPhase 保存 analysis/ 下 9 个文件（base_metrics、reflection_results、draft_patches、initial_merge_report、patched_analysis_results、toxicity_report、final_merge_report、final_analysis_results、metrics）
  - [ ] SubTask 21.3: 保存 sample_traces.jsonl（每轮）
  - [ ] SubTask 21.4: 保存 sample_state_before.json 和 sample_state_after.json
  - [ ] SubTask 21.5: 保存 batch_size_controller_before.json 和 batch_size_controller_after.json
  - [ ] SubTask 21.6: 在 FewshotOptimizationPhase 保存 fewshot/ 下 6 个文件（base_results、base_eval、selected_examples、final_results、final_eval、metrics）
  - [ ] SubTask 21.7: 保存 compression_report.json（如果触发）

- [ ] Task 22: 修复 Runner 问题
  - [ ] SubTask 22.1: 修复 yaml 导入顺序 bug（runner.py 行 438-442 的 try-except 应移到文件顶部）
  - [ ] SubTask 22.2: 保存最终 few-shot examples 到顶层目录
  - [ ] SubTask 22.3: 增加 rollback / no_progress 标记到 run_summary

- [ ] Task 23: 准备小数据集和端到端 Smoke
  - [ ] SubTask 23.1: 准备 10～20 条小样本数据集（data/smoke_samples.jsonl）
  - [ ] SubTask 23.2: 创建 smoke 测试配置（configs/smoke_config.yaml，rounds=1）
  - [ ] SubTask 23.3: 编写端到端 smoke 测试脚本
  - [ ] SubTask 23.4: 验证 CLI 能跑通真实小数据集
  - [ ] SubTask 23.5: 验证不出现 mock output

- [ ] Task 24: PR4 最终验收
  - [ ] SubTask 24.1: 验证 prompt 超限时触发压缩
  - [ ] SubTask 24.2: 验证压缩后不降才接受
  - [ ] SubTask 24.3: 验证一次完整 Run 产物完整
  - [ ] SubTask 24.4: 验证 CLI 能跑通真实 10～20 条样本
  - [ ] SubTask 24.5: 验证三阶段全流程无 mock

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
- [Task 11] depends on [Task 10]（PR2 依赖 PR1 完成）
- [Task 12] depends on [Task 11]
- [Task 13] depends on [Task 11, Task 12]
- [Task 14] depends on [Task 13]
- [Task 15] depends on [Task 14]（PR3 依赖 PR2 完成）
- [Task 16] depends on [Task 15]
- [Task 17] depends on [Task 15, Task 16]
- [Task 18] depends on [Task 17]
- [Task 19] depends on [Task 18]（PR4 依赖 PR3 完成）
- [Task 20] depends on [Task 19]
- [Task 21] depends on [Task 20]
- [Task 22] depends on [Task 21]
- [Task 23] depends on [Task 22]
- [Task 24] depends on [Task 23]

## 可并行任务

- PR1 内：Task 3、Task 4、Task 5 可并行（各自独立的 executor 实现）
- PR2 内：Task 11、Task 12 可并行（PatchApplyExecutor 和 PatchGenerationExecutor 独立）
- PR3 内：Task 15、Task 16 可并行（MergeExecutor 和 ToxicityTestExecutor 独立）
