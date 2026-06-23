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
- [ ] extraction/base_results.jsonl 有真实模型输出（依赖 PR4 Task 21 artifact 补齐）
- [ ] analysis_results.jsonl 有真实分析结果（依赖 PR4 Task 21 artifact 补齐）
- [x] SampleState 的 error_ema 基于真实评估更新
- [x] 没有 mock status="correct" 的硬编码结果（真实 executor 不硬编码；mock fallback 保留用于无 model_client 场景）

## PR 2：真实 Patch Apply 与 Prompt Render

- [ ] PatchApplyExecutor 实现 replace/insert_after/insert_before/delete 操作
- [ ] PatchApplyExecutor 拒绝 immutable section patch
- [ ] PatchApplyExecutor 应用后生成新 prompt version
- [ ] PatchApplyExecutor 保存 before/after
- [ ] PatchApplyExecutor 生成 apply report
- [ ] PatchGenerationExecutor 基于 AnalysisResult 生成 ExtractionPatch
- [ ] PatchGenerationExecutor 基于 ReflectionResult 生成 AnalysisPatch
- [ ] PatchGenerationExecutor 接入 PatchValidator 验证
- [ ] PatchGenerationExecutor 生成失败时记录 rejection_reason
- [ ] ExtractionPromptOptimizationStage Step 4 使用 PatchGenerationExecutor
- [ ] ExtractionPromptOptimizationStage Step 6 使用 PatchApplyExecutor + ExtractionExecutor
- [ ] ExtractionPromptOptimizationStage Step 9 使用真实最终测试
- [ ] AnalysisPromptOptimizationStage Step 3 使用 PatchGenerationExecutor
- [ ] AnalysisPromptOptimizationStage Step 5 使用 PatchApplyExecutor + AnalysisExecutor
- [ ] AnalysisPromptOptimizationStage Step 8 使用真实最终测试
- [ ] PromptOptimizationPhase 真正应用 patch 到 StructuredPrompt（不再仅自增 version）
- [ ] accepted patch 能修改指定 section
- [ ] output schema section 不可修改
- [ ] final prompt 能 render 成模型输入
- [ ] prompt version 真实变化
- [ ] apply report 可追踪

## PR 3：真实 Merge 与 Greedy 测毒

- [ ] MergeExecutor 接入旧系统 TreeReducePatchMerger
- [ ] MergeExecutor 实现 ExtractionPatch/AnalysisPatch ↔ 旧系统 Patch 数据结构转换
- [ ] MergeExecutor merge 后重新 validate
- [ ] MergeExecutor 生成 merge report（input/merged/dropped/conflict patch_ids）
- [ ] MergeExecutor 支持 fallback 到 rule-based merge
- [ ] ToxicityTestExecutor 实现 patch 按难度排序
- [ ] ToxicityTestExecutor 实现 greedy 测毒循环
- [ ] ToxicityTestExecutor 实现 early stop
- [ ] ToxicityTestExecutor 实现空 toxic set 跳过
- [ ] ToxicityTestExecutor 生成 toxicity report（tested/toxic/safe/broken_sample_ids）
- [ ] ExtractionPromptOptimizationStage Step 5 使用 MergeExecutor
- [ ] ExtractionPromptOptimizationStage Step 7 使用 ToxicityTestExecutor
- [ ] AnalysisPromptOptimizationStage Step 4 使用 MergeExecutor
- [ ] AnalysisPromptOptimizationStage Step 6 使用 ToxicityTestExecutor
- [ ] ineffective patch 会被剔除
- [ ] toxic patch 会被拒绝
- [ ] safe patch 会进入 final merge
- [ ] toxic sample set 来源清楚
- [ ] early stop 生效
- [ ] toxicity_report 包含 tested / toxic / safe / broken_sample_ids

## PR 4：压缩、Artifact、端到端 Smoke

- [ ] CompressionExecutor 接入旧系统 CompressionEngine
- [ ] CompressionExecutor 实现超限检测（line_limit / char_limit）
- [ ] CompressionExecutor 实现压缩后重新测试
- [ ] CompressionExecutor 接受标准：compressed_accuracy >= pre_compression_accuracy 且无新增 regression
- [ ] CompressionExecutor 压缩失败保留原 prompt
- [ ] CompressionExecutor 生成 compression report
- [ ] ExtractionPromptOptimizationStage Step 8 使用 CompressionExecutor
- [ ] AnalysisPromptOptimizationStage Step 7 使用 CompressionExecutor
- [ ] Prompt Optimization Iteration 保存 extraction/ 下 12 个文件
- [ ] Prompt Optimization Iteration 保存 analysis/ 下 9 个文件
- [ ] 每轮保存 sample_traces.jsonl
- [ ] 每轮保存 sample_state_before.json 和 sample_state_after.json
- [ ] 每轮保存 batch_size_controller_before.json 和 batch_size_controller_after.json
- [ ] Few-shot Iteration 保存 fewshot/ 下 6 个文件
- [ ] 触发压缩时保存 compression_report.json
- [ ] runner.py yaml 导入顺序 bug 已修复
- [ ] 最终 few-shot examples 保存到顶层目录
- [ ] run_summary 包含 rollback / no_progress 标记
- [ ] 准备了 10～20 条小样本数据集
- [ ] CLI 能跑通真实 10～20 条样本
- [ ] 完整三阶段 Run 无 mock output
- [ ] prompt 超限时触发压缩
- [ ] 压缩后不降才接受
- [ ] 一次完整 Run 产物完整

## 最终验收标准（跨 PR）

- [ ] 当前 refactored 主流程不再依赖 mock 抽取
- [ ] extraction prompt 优化可以真实调用模型
- [ ] analysis prompt 优化可以真实调用模型
- [ ] few-shot phase 可以真实调用模型
- [ ] patch 可以真实应用到 StructuredPrompt
- [ ] tree-merge 真实执行
- [ ] toxicity test 真实执行
- [ ] prompt 压缩真实执行
- [ ] 所有关键 artifact 可追踪
- [ ] 小数据集端到端 smoke 可运行
- [ ] 每轮 batch size 能基于真实指标变化调整
- [ ] SampleState 和 SampleTrace 基于真实结果更新
- [ ] CLI 能完成完整三阶段 Run
- [ ] 输出结果可以用于判断 prompt 是否真实变好
