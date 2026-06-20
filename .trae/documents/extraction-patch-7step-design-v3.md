# Extraction Prompt Patch 7 步流程 + 分析 Prompt 双轮优化 — 设计文档（v3.0）

> 版本: v3.0  
> 状态: Draft — 等待用户确认  
> 作用域: mmap_optimizer 项目 extraction + analysis prompt 双轮优化

---

## 1. 总体架构（v3.0 新增：双轮优化 + 盲评分析）

```
┌───────────────────────────────────────────────────────────────────────┐
│ 第一轮：Extraction Prompt 优化（7 步流程）                            │
│                                                                       │
│ Step 1: Baseline Extraction — 对采样数据进行抽取                     │
│ Step 2: Accuracy Statistics — 统计正确/错误样本                        │
│ Step 3: Blind Evaluation + Reflection — 🆕 对抽取结果进行盲评分析     │
│           Step 3a: 盲评分析（不看真值）                                 │
│           Step 3b: 对比盲评 vs 真值（无真值时 3 次分析投票为真值）      │
│           Step 3c: 盲评与真值不同的样本，不用于 patch 提取               │
│           Step 3d: 对"盲评错而抽取对"的样本进行盲评反思                 │
│           Step 3e: 记录盲评反思结果，供后续分析 prompt 优化使用         │
│ Step 4: Patch Generation — 仅用"盲评与真值一致"的错误样本生成 patch     │
│ Step 5: Patch Merge — tree_reduce + 可选 semantic merge             │
│ Step 6: Merged Re-test — 整体应用 merged patches 后重新抽取测试        │
│ Step 7: Comparison & Filtering — 对比两次结果，剔除无效/有毒 patch    │
│ Step 8: Final Merge & Apply / Rollback — 最终合并应用或回滚重试       │
│                                                                       │
├───────────────────────────────────────────────────────────────────────┤
│ 第二轮：Analysis Prompt 优化（相同 7 步流程）                         │
│                                                                       │
│ Step 1: Baseline Analysis — 对第一轮"盲评与真值不同"的样本跑分析 prompt│
│ Step 2: Accuracy Statistics — 统计分析准确率（对比分析 vs 真值）       │
│ Step 3: Patch Generation — 针对分析错误样本生成 analysis patch        │
│           * 使用第一轮 Step 3d 记录的盲评反思结果作为分析优化依据*     │
│ Step 4: Patch Merge — tree_reduce + 可选 semantic merge             │
│ Step 5: Merged Re-test — 整体应用 merged patches 后重新分析测试        │
│ Step 6: Comparison & Filtering — 对比两次分析结果，剔除无效/有毒 patch│
│ Step 7: Final Merge & Apply / Rollback — 最终合并应用或回滚重试      │
│                                                                       │
├───────────────────────────────────────────────────────────────────────┤
│ 可选循环：分析 prompt 优化完成后，可返回第一轮，用新的分析 prompt 重新   │
│ 做 extraction prompt 优化（构成外循环迭代）                             │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 2. 第一轮：Extraction Prompt 优化 — 7 步流程（v2 基础 + v3 增强 Step 3）

### 2.1 Step 1: Baseline Extraction（保留现有实现）

**文件**: [round_runner.py:128-162](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L128-L162)

```
对 optimization_batch 样本跑当前 extraction prompt → base_evals
每个 eval 有 overall_status (correct/wrong/schema_error/parse_error)
```

### 2.2 Step 2: Accuracy Statistics（保留现有实现）

**文件**: [round_runner.py:181](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L181)

```python
wrong_evals = [e for e in base_evals if e.overall_status != "correct"]
correct_evals = [e for e in base_evals if e.overall_status == "correct"]
```

### 2.3 Step 3: Blind Evaluation + Blind Evaluation Reflection（🆕 核心新增）

**文件**: 需在 round_runner.py 中新增盲评分析流程，在 Step 4 之前

#### Step 3a: 盲评分析 — 对抽取结果进行盲评（不给模型看真值）

```
对每个 wrong_eval 中的样本:
    用当前 analysis_prompt 进行分析（但不给模型看 ground truth）
    模型输出: 盲评判断（该样本抽取是否正确，以及错误原因）
    记录: blind_judgement 字段

对每个样本:
    blind_record = AnalysisRunner.run_blind_analysis(sample, extraction_output)
    blind_record.judgement = 模型对该样本的分析判断
```

**实现要点**:
- 调用模型时传入: 图片 + 抽取结果（不含 ground truth）
- 模型输出: 对该样本的盲评分析（应该返回什么，以及为什么）
- 用 `parse_analysis_output_with_repair` 解析模型输出
- 与当前 `AnalysisRunner.analyze_errors` 的区别: **不传入 evaluation_record 中的真值信息**

#### Step 3b: 对比盲评 vs 真值

```python
for each sample in wrong_samples:
    ground_truth_label = sample.ground_truth  # 从 dataset 获取真值
    blind_judgement_label = blind_record.judgement  # 盲评结果

    if ground_truth_label exists:
        # 有真值时，直接对比
        matches_truth = (blind_judgement_label == ground_truth_label)
    else:
        # 无真值时：进行 3 次独立分析，用投票结果作为真值
        three_analyses = [
            AnalysisRunner.run_blind_analysis(sample, extraction_output)
            for _ in range(3)
        ]
        voted_truth = majority_vote([a.judgement for a in three_analyses])
        matches_truth = (blind_judgement_label == voted_truth)
        # 保存投票结果作为真值代理
        blind_record.voted_truth = voted_truth
        blind_record.three_analysis_outputs = three_analyses

    blind_record.matches_truth = matches_truth
    blind_record.is_correct_sample = (overall_status == "correct")
```

#### Step 3c: 确定哪些样本用于 patch 生成

```python
# 用于 patch 生成的样本: 盲评结果与真值一致的 wrong 样本
samples_for_patch_generation = [
    sample_id for sample_id, record in blind_records.items()
    if record.matches_truth and record.overall_status != "correct"
]

# 不用于 patch 生成的样本: 盲评结果与真值不同的样本（说明分析本身有问题）
samples_excluded_from_patch = [
    sample_id for sample_id, record in blind_records.items()
    if not record.matches_truth and record.overall_status != "correct"
]
```

#### Step 3d: 盲评反思 — 对"盲评错而抽取对"的样本进行反思

```python
reflection_records = []

# 情况 A: 抽取对，但盲评分析判断错
# 即 overall_status == "correct" 但 blind_record.matches_truth == False
# 说明分析 prompt 本身判断能力有问题，需要优化
for sample_id in correct_sample_ids:
    blind_record = blind_records[sample_id]
    if not blind_record.matches_truth:
        # 调用模型进行盲评反思
        reflection_input = {
            "image": sample.image,
            "extraction_result": extraction_output,
            "blind_judgement": blind_record.judgement,
            "ground_truth": ground_truth_label or voted_truth,
        }
        reflection_output = model_client.complete(
            system_message="请反思盲评分析中的错误...",
            user_message=json.dumps(reflection_input),
        )
        reflection_records.append({
            "sample_id": sample_id,
            "original_blind_judgement": blind_record.judgement,
            "ground_truth": ground_truth_label or voted_truth,
            "reflection": reflection_output.parsed,
            "analysis_prompt_snapshot": current_analysis_prompt_version,
        })

# 情况 B: 抽取错，盲评也错（与真值不同）
# 说明: 分析 prompt 完全无法正确判断该样本，分析和抽取都有问题
# 这类样本在抽取优化中不用于 patch 生成（Step 3c 已排除）
# 但在分析 prompt 优化中作为错误样本处理

# 保存盲评反思结果，供第二轮分析 prompt 优化使用
self._save_intermediate(round_id, "blind_evaluation_reflection", {
    "reflection_count": len(reflection_records),
    "reflection_records": reflection_records,
    "blind_records": blind_records,
})
```

#### Step 3e: 保存盲评分析结果供后续使用

```python
blind_evaluation_summary = {
    "total_samples": len(base_evals),
    "wrong_samples": len(wrong_evals),
    "correct_samples": len(correct_evals),
    "blind_vs_truth_match_count": sum(1 for r in blind_records.values() if r.matches_truth),
    "blind_vs_truth_mismatch_count": sum(1 for r in blind_records.values() if not r.matches_truth),
    "samples_for_patch": len(samples_for_patch_generation),
    "samples_excluded_from_patch": len(samples_excluded_from_patch),
    "reflection_record_count": len(reflection_records),
    "used_voted_truth": any(r.voted_truth is not None for r in blind_records.values()),
}
```

### 2.4 Step 4: Patch Generation（v3 增强 — 仅用"盲评与真值一致"的样本）

**文件**: [round_runner.py:185-238](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L185-L238)

**关键变更**: 传入 `AnalysisRunner.analyze_errors` 的 `error_evaluations` 不再是全部 wrong_evals，而是 `samples_for_patch_generation` 中的样本评估结果

```python
# 原代码:
# analysis_result = AnalysisRunner.analyze_errors(error_evaluations=wrong_evals, ...)
# 新代码:
filtered_error_evals = [
    evaluation for evaluation in wrong_evals
    if evaluation.sample_id in samples_for_patch_generation
]

if filtered_error_evals:
    analysis_result = AnalysisRunner.analyze_errors(
        error_evaluations=filtered_error_evals,
        extraction_runs=extraction_by_sample,
        sample_metadata=sample_metadata,
        analysis_prompt=state.active_analysis_prompt,
        target_prompt=state.active_extraction_prompt,
    )
    draft_patches = analysis_result.draft_patches
    analysis_records.extend(analysis_result.analysis_records)
    analysis_runs.extend(analysis_result.analysis_runs)
else:
    # 没有可用的错误样本（所有 wrong 样本的盲评都与真值不一致）
    # 跳过 patch 生成，直接进入后续流程
    draft_patches = []
    log_stage(logger, "no_valid_samples_for_patch", round=round_index)
```

然后对 draft_patches 进行静态校验 + 可选 LLM 修复（保留现有实现）

```python
for patch in draft_patches:
    validation = PatchValidator.validate(patch, ...)
    if not validation.valid and patch_repair_enabled:
        # 尝试修复
        repaired = PatchRepairEngine.repair_locator(patch, ...)
        # ...
    if repaired or validation.valid:
        candidate_patches.append(patch)
    else:
        rejected_patches.append(patch)
```

### 2.5 Step 5: Patch Merge（保留现有实现，无变更）

**文件**: [round_runner.py:248-269](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L248-L269)

```
TreeReducePatchMerger.merge(candidate_patches) → merged_patches
可选: SemanticPatchProcessor.merge/root_audit
再次: PatchValidator.validate
```

### 2.6 Step 6: Merged Re-test — 整体应用后重新测试（🆕 v2 新增，v3 保留）

```python
# 整体应用所有 merged_patches 到原 prompt
temp_prompt = state.active_extraction_prompt
for patch in merged_patches:
    temp_prompt = PatchApplier().apply(temp_prompt, patch,
        new_version=temp_prompt.version + 1, round_id=round_id)

# 对 optimization_batch 样本用新 prompt 重新跑 extraction
patched_result = self._prompt_runner().run(
    round_id=round_id,
    run_type="post_merge_extraction",
    prompt=temp_prompt,
    samples=optimization_batch,
    assets=state.assets,
    ground_truths=state.ground_truths,
    contract=state.extraction_output_schema_contract,
)
patched_evals = patched_result.evaluations
```

### 2.7 Step 7: Comparison & Filtering（🆕 v2 新增，v3 保留）

```python
# Step 7.1: 样本分类
base_by_sample = {e.sample_id: e for e in base_evals}
patched_by_sample = {e.sample_id: e for e in patched_evals}

sample_classes: dict[str, str] = {}
for sample_id in set(base_by_sample.keys()) & set(patched_by_sample.keys()):
    sample_classes[sample_id] = classify_transition(
        base_by_sample[sample_id], patched_by_sample[sample_id]
    )

# Step 7.2: 剔除 INEFFECTIVE patch
# 若 patch 来源样本全部是"之前错依然错" → 剔除
for patch in merged_patches:
    source_samples = patch.source_sample_ids
    still_wrong = [s for s in source_samples if sample_classes.get(s) == "unchanged_wrong"]
    if source_samples and len(still_wrong) == len(source_samples):
        patch.status = "rejected"
        patch.rejection_reason = "INEFFECTIVE"
        rejected_patches.append(patch)

# Step 7.3: 收集测毒集（"之前对现在错"的样本）
toxic_sample_ids = [sid for sid, cls in sample_classes.items() if cls == "broken"]

# Step 7.4: 在测毒集上逐个 patch 测毒
if toxic_sample_ids:
    for patch in non_ineffective_patches:
        temp_prompt = PatchApplier().apply(initial_extraction_prompt, patch, ...)
        toxic_test_result = self._prompt_runner().run(
            samples=toxic_samples, prompt=temp_prompt, ...
        )
        has_broken = any(e.overall_status != "correct" for e in toxic_test_result.evaluations)
        if has_broken:
            patch.status = "rejected"
            patch.rejection_reason = "TOXIC"
            rejected_patches.append(patch)

# Step 7.5: final_patches
final_patches = [p for p in merged_patches if p.status == "accepted"]
```

### 2.8 Step 8: Final Merge & Apply / Rollback（🆕 v2 新增，v3 保留）

```python
if final_patches:
    # 再次 tree_reduce merge
    final_merge_result = TreeReducePatchMerger().merge(
        patches=final_patches,
        prompt_ir=state.active_extraction_prompt.prompt_ir,
    )
    final_merged = final_merge_result.final_patches
    # 应用到 prompt
    for patch in final_merged:
        state.active_extraction_prompt = PatchApplier().apply(
            state.active_extraction_prompt, patch, ...
        )
    # post_apply regression check（保留现有）
else:
    # patch 集为空 → 回滚 + 重试
    state.active_extraction_prompt = initial_extraction_prompt
    # 进入下一次 restart_attempt
    continue
```

---

## 3. 第二轮：Analysis Prompt 优化（与抽取优化相同的 7 步流程）

### 3.1 总体设计

在第一轮 extraction prompt 优化完成后，启动第二轮 analysis prompt 优化。目标是提升分析的准确率，使得分析更能指导后续的抽取 prompt 优化。

```
第二轮与第一轮流程相同，但:
  - 测试对象: analysis prompt（不是 extraction prompt）
  - 评估方式: 分析的准确率（盲评结果 vs 真值）
  - Patch 生成: 针对分析错误样本生成 analysis patch
  - 特殊输入: 使用第一轮 Step 3d 的盲评反思结果作为优化依据
```

### 3.2 Step 1: Baseline Analysis Test（对应第一轮 Step 1）

**文件**: round_runner.py 中新增 analysis 测试流程

```python
# 测试集: 第一轮中"盲评与真值不同"的样本（分析 prompt 对这些样本判断错误）
#        + 部分正确样本用于毒性检测
analysis_test_sample_ids = []

# 加入: 第一轮中盲评与真值不同的样本
analysis_test_sample_ids.extend([
    sample_id for sample_id, record in blind_records.items()
    if not record.matches_truth
])

# 加入: 第一轮中"抽取对但盲评错"的样本（用于 canary 保护）
analysis_canary_sample_ids = [
    sample_id for sample_id, record in blind_records.items()
    if record.matches_truth and record.overall_status == "correct"
]

analysis_test_samples = [s for s in state.samples if s.id in set(analysis_test_sample_ids)]
if not analysis_test_samples:
    # 没有需要优化的样本 → 跳过 analysis prompt 优化
    log_stage(logger, "analysis_optimization_skipped", round=round_index,
              reason="No samples with blind evaluation mismatch")
    skip_analysis_optimization = True
    return
```

### 3.3 Step 2: Accuracy Statistics for Analysis（对应第一轮 Step 2）

```python
# 用当前 analysis prompt 对分析测试样本跑模型分析
# 对比分析结果 vs 真值
analysis_base_evals = []
for sample in analysis_test_samples:
    # 调用 analysis prompt 获取分析结果
    analysis_output = AnalysisRunner.run_single_analysis(
        sample=sample,
        extraction_run=extraction_by_sample[sample.id],
        analysis_prompt=state.active_analysis_prompt,
    )
    # 对比分析判断 vs 真值
    ground_truth_label = get_ground_truth(sample)
    analysis_judgement = analysis_output.judgement
    analysis_eval_status = "correct" if analysis_judgement == ground_truth_label else "wrong"
    analysis_base_evals.append(
        EvaluationRecord(
            sample_id=sample.id,
            overall_status=analysis_eval_status,
            analysis_judgement=analysis_judgement,
            ground_truth=ground_truth_label,
        )
    )

analysis_wrong_evals = [e for e in analysis_base_evals if e.overall_status != "correct"]
```

### 3.4 Step 3: Patch Generation for Analysis（对应第一轮 Step 4）

**关键**: 使用第一轮 Step 3d 的盲评反思结果作为输入

```python
# 生成 analysis patch
# 输入: 分析错误样本 + 第一轮的盲评反思结果
analysis_draft_patches = []
for analysis_wrong_eval in analysis_wrong_evals:
    sample_id = analysis_wrong_eval.sample_id
    reflection_record = next(
        (r for r in reflection_records if r["sample_id"] == sample_id), None
    )
    # 调用 analysis prompt 生成 patch
    # 输入: 图片 + 抽取结果 + 盲评结果 + 盲评反思结果 + 真值
    analysis_patch_output = AnalysisRunner.generate_analysis_patch(
        sample=sample,
        extraction_output=extraction_by_sample[sample_id].parsed_output,
        blind_judgement=blind_records[sample_id].judgement,
        reflection=reflection_record["reflection"] if reflection_record else None,
        ground_truth=ground_truth_label,
        analysis_prompt=state.active_analysis_prompt,
    )
    analysis_draft_patches.extend(analysis_patch_output.patches)

# 静态校验 + 可选 LLM 修复（与抽取优化相同流程）
analysis_candidate_patches = []
analysis_rejected_patches = []
for patch in analysis_draft_patches:
    validation = PatchValidator.validate(patch, ...)
    if not validation.valid and config.patch_repair_enabled:
        repaired = PatchRepairEngine.repair_locator(patch, ...)
        # ...
    if repaired or validation.valid:
        analysis_candidate_patches.append(patch)
    else:
        analysis_rejected_patches.append(patch)
```

### 3.5 Step 4: Patch Merge for Analysis（对应第一轮 Step 5）

```python
analysis_merge_result = TreeReducePatchMerger().merge(
    patches=analysis_candidate_patches,
    prompt_ir=state.active_analysis_prompt.prompt_ir,
)
analysis_merged_patches = analysis_merge_result.final_patches
```

### 3.6 Step 5: Merged Re-test for Analysis（对应第一轮 Step 6）

```python
# 整体应用所有 analysis_merged_patches 到 analysis prompt
temp_analysis_prompt = state.active_analysis_prompt
for patch in analysis_merged_patches:
    temp_analysis_prompt = PatchApplier().apply(
        temp_analysis_prompt, patch,
        new_version=temp_analysis_prompt.version + 1, round_id=round_id
    )

# 对分析测试样本用新 analysis prompt 重新跑分析
analysis_patched_result = self._prompt_runner().run_analysis(
    round_id=round_id,
    prompt=temp_analysis_prompt,
    samples=analysis_test_samples,
    ...
)
analysis_patched_evals = analysis_patched_result.evaluations
```

### 3.7 Step 6: Comparison & Filtering for Analysis（对应第一轮 Step 7）

```python
# Step 6.1 样本分类（分析结果从 wrong → correct? 或 correct → wrong?）
analysis_sample_classes = {}
for sample_id in set(e.sample_id for e in analysis_base_evals):
    base_eval = next(e for e in analysis_base_evals if e.sample_id == sample_id)
    patched_eval = next((e for e in analysis_patched_evals if e.sample_id == sample_id), None)
    if patched_eval is None:
        continue
    analysis_sample_classes[sample_id] = classify_transition(base_eval, patched_eval)

# Step 6.2 剔除 INEFFECTIVE analysis patch
# 逻辑与抽取优化相同: 若 patch 来源样本全部"之前错依然错" → 剔除

# Step 6.3 收集分析测毒集（"之前对现在错"的分析样本）
analysis_toxic_sample_ids = [
    sid for sid, cls in analysis_sample_classes.items() if cls == "broken"
]

# Step 6.4 在测毒集上逐个 analysis patch 测毒
# 逻辑与抽取优化相同

# Step 6.5 final_analysis_patches
analysis_final_patches = [p for p in analysis_merged_patches if p.status == "accepted"]
```

### 3.8 Step 7: Final Merge & Apply / Rollback for Analysis（对应第一轮 Step 8）

```python
if analysis_final_patches:
    # 再次 tree_reduce merge analysis patches
    analysis_final_merge = TreeReducePatchMerger().merge(
        patches=analysis_final_patches,
        prompt_ir=state.active_analysis_prompt.prompt_ir,
    )
    analysis_final_merged = analysis_final_merge.final_patches
    # 应用到 analysis prompt
    for patch in analysis_final_merged:
        state.active_analysis_prompt = PatchApplier().apply(
            state.active_analysis_prompt, patch, ...
        )
else:
    # analysis patch 集为空 → 回滚 analysis prompt + 重试
    state.active_analysis_prompt = initial_analysis_prompt
    # 进入下一次 analysis_restart_attempt
    continue
```

---

## 4. 完整流程结构图（v3.0）

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Round Runner 主流程                                                      │
│                                                                         │
│ 初始化: 保存 initial_extraction_prompt 和 initial_analysis_prompt 快照  │
│ for restart_attempt in range(max_restart_attempts):                      │
│                                                                         │
│   ┌─────────────────────── 第一轮：Extraction Prompt 优化 ──────────────┐
│   │ Step 1: Baseline Extraction                                           │
│   │   → _prompt_runner().run(optimization_batch, extraction_prompt)       │
│   │   → base_evals                                                        │
│   │                                                                       │
│   │ Step 2: Accuracy Statistics                                            │
│   │   → wrong_evals, correct_evals                                          │
│   │                                                                       │
│   │ Step 3: Blind Evaluation + Reflection (🆕 新增)                     │
│   │   3a: 对每个 wrong 样本进行盲评分析（不看真值）                         │
│   │   3b: 对比盲评 vs 真值（无真值时 3 次分析投票为真值）                    │
│   │   3c: samples_for_patch_generation = 盲评与真值一致的 wrong 样本        │
│   │       samples_excluded = 盲评与真值不同的样本                         │
│   │   3d: 对"盲评错而抽取对"的样本 → 盲评反思                              │
│   │       → reflection_records（供第二轮使用）                             │
│   │   3e: 保存盲评反思到 intermediate                                      │
│   │                                                                       │
│   │ Step 4: Patch Generation                                              │
│   │   → AnalysisRunner.analyze_errors(filtered_error_evals)                │
│   │   → draft_patches → candidate_patches / rejected_patches              │
│   │                                                                       │
│   │ Step 5: Patch Merge                                                   │
│   │   → TreeReducePatchMerger.merge(candidate_patches)                    │
│   │   → merged_patches                                                     │
│   │                                                                       │
│   │ Step 6: Merged Re-test                                                │
│   │   → PatchApplier.apply all merged_patches → temp_prompt              │
│   │   → _prompt_runner().run(optimization_batch, temp_prompt)             │
│   │   → patched_evals                                                      │
│   │                                                                       │
│   │ Step 7: Comparison & Filtering                                         │
│   │   7.1 sample_classes = classify_transition(base_evals, patched_evals) │
│   │   7.2 剔除 INEFFECTIVE patch（来源样本全部"错依然错"）                 │
│   │   7.3 toxic_sample_ids = "之前对现在错"的样本                           │
│   │   7.4 在 toxic_sample_ids 上逐个 patch 测毒                            │
│   │   7.5 final_patches = merged_patches - INEFFECTIVE - TOXIC           │
│   │                                                                       │
│   │ Step 8: Final Merge & Apply / Rollback                                │
│   │   if final_patches:                                                    │
│   │     → TreeReducePatchMerger.merge(final_patches)                      │
│   │     → PatchApplier.apply 到 state.active_extraction_prompt            │
│   │     → post_apply_regression_check                                     │
│   │     → break（成功完成，退出 restart 循环）                             │
│   │   else:                                                                │
│   │     → state.active_extraction_prompt = initial_extraction_prompt      │
│   │     → continue（进入下一次 restart_attempt）                           │
│   └───────────────────────────────────────────────────────────────────────┘
│                                                                         │
│   ┌─────────────────────── 第二轮：Analysis Prompt 优化 ────────────────┐
│   │ Step 1: Baseline Analysis Test                                        │
│   │   → 测试集: 第一轮中"盲评与真值不同"的样本 + canary 样本              │
│   │   → AnalysisRunner.run_single_analysis(analysis_prompt)              │
│   │   → analysis_base_evals（对比分析判断 vs 真值）                        │
│   │                                                                       │
│   │ Step 2: Accuracy Statistics for Analysis                              │
│   │   → analysis_wrong_evals                                               │
│   │                                                                       │
│   │ Step 3: Patch Generation for Analysis                                 │
│   │   → 使用第一轮 Step 3d 的 blind_evaluation_reflection_records         │
│   │   → AnalysisRunner.generate_analysis_patch(analysis_wrong_evals)      │
│   │   → analysis_draft_patches → analysis_candidate_patches              │
│   │                                                                       │
│   │ Step 4: Patch Merge for Analysis                                      │
│   │   → TreeReducePatchMerger.merge(analysis_candidate_patches)           │
│   │   → analysis_merged_patches                                            │
│   │                                                                       │
│   │ Step 5: Merged Re-test for Analysis                                   │
│   │   → PatchApplier.apply all analysis_merged_patches                     │
│   │   → 重新跑分析测试 → analysis_patched_evals                           │
│   │                                                                       │
│   │ Step 6: Comparison & Filtering for Analysis                           │
│   │   → 相同流程：分类样本 → 剔除 INEFFECTIVE → 测毒集 → 测毒 → final     │
│   │                                                                       │
│   │ Step 7: Final Merge & Apply / Rollback for Analysis                   │
│   │   if analysis_final_patches:                                           │
│   │     → TreeReducePatchMerger.merge(analysis_final_patches)             │
│   │     → PatchApplier.apply 到 state.active_analysis_prompt              │
│   │     → break                                                            │
│   │   else:                                                                │
│   │     → 回滚 analysis prompt + 继续重试                                  │
│   └───────────────────────────────────────────────────────────────────────┘
│                                                                         │
│ （可选外循环: 第二轮完成后，可返回第一轮用新 analysis prompt 重新优化）   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 5. 关键数据结构新增

### 5.1 BlindEvaluationRecord（🆕 新增）

```python
@dataclass
class BlindEvaluationRecord:
    """盲评分析记录 — 用于第一轮 Step 3"""
    id: str
    round_id: str
    sample_id: str
    extraction_run_id: str
    analysis_prompt_version_id: str
    blind_judgement: str          # 盲评判断结果
    ground_truth_label: str | None  # 真值（如果存在）
    voted_truth_label: str | None   # 投票真值（如果无真值时，3 次分析投票结果）
    three_analysis_outputs: list | None  # 3 次分析输出（用于投票）
    matches_truth: bool             # 盲评结果是否与真值一致
    overall_status: str             # original extraction_eval status (correct/wrong)
    parse_success: bool = True
    schema_valid: bool = True
    raw_output: str | None = None
    parsed_output: dict | None = None
    extra: dict = field(default_factory=dict)
```

### 5.2 BlindEvaluationReflectionRecord（🆕 新增）

```python
@dataclass
class BlindEvaluationReflectionRecord:
    """盲评反思记录 — 用于第一轮 Step 3d，供第二轮分析 prompt 优化使用"""
    id: str
    round_id: str
    sample_id: str
    analysis_prompt_version_id: str
    original_blind_judgement: str     # 原始盲评判断
    ground_truth_label: str            # 真值（或投票真值）
    why_blind_was_wrong: str           # 模型反思：盲评为什么错了
    what_should_have_been_checked: str  # 模型反思：应该检查什么
    how_to_improve_analysis: str       # 模型反思：如何改进分析
    raw_reflection_output: str
    parsed_reflection: dict | None = None
    used_voted_truth: bool = False     # 是否使用投票真值
```

### 5.3 AnalysisEvalRecord（🆕 新增 — 用于第二轮 Step 2）

```python
@dataclass
class AnalysisEvalRecord:
    """分析评估记录 — 用于第二轮的分析准确率评估"""
    id: str
    round_id: str
    sample_id: str
    analysis_prompt_version_id: str
    analysis_judgement: str           # analysis prompt 判断结果
    ground_truth_label: str            # 真值（从 dataset 或 voted_truth 获取）
    overall_status: str               # "correct" if analysis_judgement == ground_truth_label
    used_blind_reflection: bool = False  # 是否使用了第一轮的盲评反思结果
    reflection_id: str | None = None   # 对应的 reflection record id
    raw_output: str | None = None
```

### 5.4 Patch schema 字段（无变更，复用现有字段）

- `source_sample_ids` — 用于 Step 7.2 无效判定
- `fixed_sample_ids` — 用于记录哪些样本被修复
- `broken_sample_ids` — 用于记录哪些样本变错
- `toxicity_result` — toxic/non_toxic/not_tested
- `effectiveness_result` — effective/ineffective/not_tested

### 5.5 OptimizerState 扩展（🆕 新增）

```python
@dataclass
class OptimizerState:
    # ... 保留现有字段 ...
    samples: list[Sample]
    assets: dict[str, SampleAsset]
    ground_truths: dict[str, GroundTruth]
    sample_states: dict[str, SampleState]
    active_extraction_prompt: PromptVersion
    active_analysis_prompt: PromptVersion
    extraction_output_schema_contract: OutputSchemaContract

    # 🆕 新增: 第一轮 Step 3 的盲评分析结果（供第二轮使用）
    blind_evaluation_records: dict[str, BlindEvaluationRecord] = field(default_factory=dict)
    blind_evaluation_reflection_records: list[BlindEvaluationReflectionRecord] = field(default_factory=list)

    # 🆕 新增: 分析 prompt 优化开关
    analysis_optimization_enabled: bool = True
```

### 5.6 OptimizerConfig 新增配置字段

```python
@dataclass
class OptimizerConfig:
    # ... 保留现有字段 ...

    # 🆕 第一轮盲评与反思相关
    blind_evaluation_enabled: bool = True            # 是否启用盲评分析
    blind_evaluation_reflection_enabled: bool = True  # 是否启用盲评反思
    blind_eval_three_analysis_vote_enabled: bool = True  # 无真值时是否 3 次投票
    max_restart_attempts: int = 3                    # 空集时最大重试次数

    # 🆕 第二轮分析 prompt 优化相关
    analysis_prompt_optimization_enabled: bool = True  # 是否启用分析 prompt 优化
    analysis_patch_repair_enabled: bool = False       # analysis patch 修复
    analysis_patch_semantic_merge_enabled: bool = True  # analysis patch 语义合并

    # 🆕 可迭代外循环（两轮之间交替）
    outer_loop_iterations: int = 1  # 外循环次数（1 = 只做一轮 extraction + 一轮 analysis）
```

---

## 6. 新 / 修改文件清单

| # | 文件 | 改动类型 | 说明 |
|---|------|----------|------|
| 1 | [records.py](file:///workspace/mmap_optimizer/orchestration/records.py) | 扩展 | 新增 3 个 RoundStage: BLIND_EVALUATION, ANALYSIS_OPTIMIZATION, ANALYSIS_PATCH_TEST |
| 2 | [config.py](file:///workspace/mmap_optimizer/core/config.py) | 扩展 | 新增 7 个配置字段（盲评、反思、投票、重试、分析优化开关等） |
| 3 | [round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) | **大幅重构** | 主流程从单轮改为 extraction + analysis 双轮优化，插入盲评与反思步骤 |
| 4 | **新增** `blind_evaluation.py` | 新建 | BlindEvaluationRunner: 盲评分析、与真值对比、盲评反思 |
| 5 | **新增** `analysis_eval_runner.py` | 新建 | 第二轮分析 prompt 测试：跑分析 prompt，对比分析 vs 真值 |
| 6 | [suite_builder.py](file:///workspace/mmap_optimizer/testing/suite_builder.py) | 扩展 | 新增 build_toxic_suite，build_analysis_test_suite |
| 7 | **新增** or 扩展 `analysis/runner.py` | 扩展 | 新增 run_blind_analysis(), run_single_analysis(), generate_analysis_patch() 方法 |
| 8 | **新增** 数据模型 | 新建 | BlindEvaluationRecord, BlindEvaluationReflectionRecord, AnalysisEvalRecord |
| 9 | tests | 新增 | 双轮优化的端到端测试 |

### 6.1 BlindEvaluationRunner（新建文件）

```python
class BlindEvaluationRunner:
    """第一轮 Step 3: 盲评分析 + 对比 + 反思"""

    def run_blind_analysis(
        self,
        *,
        round_id: str,
        sample: Sample,
        extraction_run: RunRecord,
        analysis_prompt: PromptVersion,
        model_client: ModelClient,
        model_config: dict,
    ) -> BlindEvaluationRecord:
        """Step 3a: 对单个样本进行盲评分析（不看真值）"""

    def compare_with_truth(
        self,
        record: BlindEvaluationRecord,
        ground_truth: str | None,
    ) -> tuple[bool, str]:  # (matches_truth, resolved_truth_label)
        """Step 3b: 对比盲评结果与真值
        - 如果有 ground_truth: 直接对比
        - 如果无 ground_truth: 调用 3 次分析，投票作为真值代理
        """

    def generate_reflection(
        self,
        *,
        round_id: str,
        sample: Sample,
        extraction_output: str,
        blind_judgement: str,
        ground_truth: str,
        model_client: ModelClient,
        model_config: dict,
    ) -> BlindEvaluationReflectionRecord:
        """Step 3d: 对"盲评错而抽取对"的样本进行盲评反思"""
```

---

## 7. 向后兼容性说明

1. **RoundStage 枚举**: 只增不删，新增 3 个值
2. **配置字段**: 所有新增字段有默认 True/合理值，不影响旧配置
3. **数据结构**: Patch schema 无变更，新增 3 个 record 类型（独立）
4. **可选开关**: `blind_evaluation_enabled=False` 时回退到旧流程
5. **analysis_optimization_enabled=False` 时跳过第二轮

---

## 8. 关键设计决策汇总

| 决策 | 说明 | 理由 |
|------|------|------|
| 盲评分析独立于 patch 生成 | 先做盲评，再决定哪些样本用于 patch | 分析结果本身可能错误，会误导优化方向 |
| 3 次分析投票作为真值代理 | 无真值时，用 3 次独立分析的多数投票作为真值 | 在无标注数据上也能进行优化 |
| 盲评与真值不同的样本不用于 patch 生成 | 分析错误的样本会产生错误的 patch，应排除 | 提升 patch 质量 |
| 盲评反思结果用于分析 prompt 优化 | 将"分析是如何错的"作为优化分析 prompt 的输入 | 提升分析准确率，反过来提升抽取优化质量 |
| 两轮相同的 7 步流程 | extraction 和 analysis prompt 用相同的优化策略 | 代码复用，逻辑一致 |
| 外循环可选迭代 | 一轮 extraction + 一轮 analysis 后，可再一轮 extraction | 新分析 prompt 可能帮助新 extraction patch |

---

**文档结束。请审核确认，特别关注：Step 3 盲评与反思流程、第二轮分析 prompt 优化流程、数据结构设计。确认后按此方案实施代码改造。**
