# Extraction Executor 之后的步骤分析

## 一、整体执行流程

`ExtractionExecutor` 是执行实际抽取任务的执行器，调用大模型完成多模态抽取。它在 `ExtractionPromptOptimizationStage` 中作为 Step 1 被调用。

```
ExtractionExecutor.execute()  (Step 1)
       ↓
  ExtractionResult[]
       ↓
  ┌────────────────────┐
  │ Step 2: 评估       │  → EvaluationExecutor.evaluate_batch()
  │ Step 3: 分析       │  → AnalysisExecutor.execute_batch()
  │ Step 4: 生成 Patch │  → PatchGenerationExecutor.generate_extraction_patches()
  │ Step 5: 初始合并   │  → MergeExecutor.merge()
  │ Step 6: 应用与测试 │  → PatchApplyExecutor.apply() + ExtractionExecutor
  │ Step 7: 回归+毒性  │  → ToxicityTestExecutor.test() + MergeExecutor
  │ Step 8: 压缩       │  → CompressionExecutor
  │ Step 9: 最终测试   │  → ExtractionExecutor + EvaluationExecutor
  └────────────────────┘
       ↓
  ExtractionMetrics
```

---

## 二、详细步骤说明

### Step 1: 执行抽取（已通过 ExtractionExecutor 完成）
- **输入**: `extraction_prompt` + `batch` + `sample_set`
- **执行器**: `ExtractionExecutor`
- **输出**: `base_extraction_results: list[ExtractionResult]`
- **位置**: [extraction_prompt_optimization.py#L190-L231](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L190-L231)

### Step 2: 计算基线指标
- **执行器**: `EvaluationExecutor`
- **职责**: 评估抽取结果与 ground truth 的对比
- **输出**: 
  - `base_eval_records: list[EvalRecord]`
  - 更新 `metrics.base_accuracy`
- **位置**: [extraction_prompt_optimization.py#L233-L272](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L233-L272)

### Step 3: 分析结果
- **执行器**: `AnalysisExecutor`
- **职责**: 对每个抽取结果调用大模型分析是否正确，生成 patch 建议
- **输出**: `analysis_results: list[AnalysisResult]`
- **位置**: [extraction_prompt_optimization.py#L274-L314](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L274-L314)

### Step 4: 生成 Patch
- **执行器**: `PatchGenerationExecutor`
- **职责**: 基于有效的分析结果生成 extraction patch
- **输出**:
  - `draft_patches: list[ExtractionPatch]`
  - `validated_patches: list[ExtractionPatch]`
  - `rejected_patches: list[ExtractionPatch]`
- **位置**: [extraction_prompt_optimization.py#L316-L358](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L316-L358)

### Step 5: 初始合并
- **执行器**: `MergeExecutor`
- **策略**: `tree_merge`
- **职责**: 对 draft patches 进行聚类、冲突检测、去重和合并
- **输出**:
  - `initial_merged_patches: list[ExtractionPatch]`
  - `initial_merge_report: PatchMergeReport`
- **位置**: [extraction_prompt_optimization.py#L360-L405](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L360-L405)

### Step 6: 应用与回归测试
- **执行器**: 
  - `PatchApplyExecutor` - 应用 patch 生成 trial prompt
  - `ExtractionExecutor` - 重新执行抽取
  - `EvaluationExecutor` - 评估 patched 结果
- **职责**: 应用初始合并的 patch，测试是否修复了错误的样本
- **输出**:
  - `trial_prompt: StructuredPrompt`
  - `patched_extraction_results: list[ExtractionResult]`
  - `patched_eval_records: list[EvalRecord]`
- **位置**: [extraction_prompt_optimization.py#L407-L444](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L407-L444)

### Step 7: 回归分析与毒性测试
- **执行器**:
  - `ToxicityTestExecutor` - 毒性测试
  - `MergeExecutor` - 二次合并
  - `PatchApplyExecutor` - 应用最终 patch
- **职责**: 
  - 计算样本状态转移（fixed/broken/unchanged_wrong/unchanged_correct）
  - 识别 toxic patches（破坏正确样本的 patch）
  - 识别 ineffective patches（未修复任何错误样本的 patch）
  - 生成最终 accepted patches
- **输出**:
  - `safe_patches: list[ExtractionPatch]`
  - `toxic_patches: list[ExtractionPatch]`
  - `toxicity_report: ToxicityReport`
  - `final_merged_patches: list[ExtractionPatch]`
  - `accepted_prompt: StructuredPrompt`
  - 更新 `metrics.accepted_patch_count` / `rejected_patch_count` / `toxic_patch_count`
- **位置**: [extraction_prompt_optimization.py#L446-L568](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py#L446-L568)

### Step 8: 压缩（如需要）
- **执行器**: `CompressionExecutor`
- **职责**: 如果 patch 数量过多，尝试压缩合并
- **输出**: `compression_report: CompressionReport`
- **位置**: [extraction_prompt_optimization.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/stages/extraction_prompt_optimization.py) `_step8_compress_if_needed`

### Step 9: 最终测试与指标
- **执行器**:
  - `ExtractionExecutor` - 重新执行最终 prompt
  - `EvaluationExecutor` - 最终评估
- **输出**:
  - `final_extraction_results: list[ExtractionResult]`
  - `final_eval_records: list[EvalRecord]`
  - `metrics.final_accuracy`
- **位置**: `_step9_final_test_and_metrics`

---

## 三、Sample 状态转移模型

| 状态 | 含义 |
|------|------|
| `fixed` | base 错误，patched 正确（被修复） |
| `broken` | base 正确，patched 错误（被破坏） |
| `unchanged_wrong` | base 错误，patched 错误（未修复） |
| `unchanged_correct` | base 正确，patched 正确（保持正确） |

## 四、Patch 状态流转

```
draft → merged → candidate_safe → accepted
                            ↘
                             rejected (TOXIC / INEFFECTIVE)
```

## 五、关键执行器职责

| 执行器 | 文件 | 职责 |
|--------|------|------|
| `ExtractionExecutor` | [extraction_executor.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/executors/extraction_executor.py) | 调用模型执行多模态抽取 |
| `EvaluationExecutor` | [evaluation_executor.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/executors/evaluation_executor.py) | 字段级 exact match 评估 |
| `AnalysisExecutor` | [analysis_executor.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/executors/analysis_executor.py) | 分析错误根因，生成 patch 建议 |
| `PatchGenerationExecutor` | [patch_generation_executor.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/executors/patch_generation_executor.py) | 基于分析结果生成 patch |
| `MergeExecutor` | [merge_executor.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/executors/merge_executor.py) | Tree Merge 合并 patch |
| `PatchApplyExecutor` | [patch_apply_executor.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/executors/patch_apply_executor.py) | 应用 patch 到 structured prompt |
| `ToxicityTestExecutor` | [toxicity_test_executor.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/executors/toxicity_test_executor.py) | 毒性测试，识别安全 patch |
| `CompressionExecutor` | [compression_executor.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/executors/compression_executor.py) | 压缩 patch 数量 |

## 六、整体编排（runner.py）

`core/runner.py` 中的 `_run_prompt_optimization` 方法负责编排所有 phase 和 stage 的执行顺序：
- 初始化所有 executors
- 创建 `ExtractionPromptOptimizationStage` 实例
- 注入所有 executors 到 stage
- 调用 `stage.run()` 触发 9 步流程
- 收集 metrics

## 七、循环迭代

`PromptOptimizationPhase` 会多次调用 stage，每次迭代都会基于上一轮的 prompt 进行优化，直到：
- 达到最大迭代次数
- 准确率不再提升（no_progress）
- 触发了回滚条件（rollback）