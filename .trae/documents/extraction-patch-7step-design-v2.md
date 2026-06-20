# Extraction Prompt Patch 7 步流程 — 设计文档（v2.0，按用户意图重新设计）

> 版本: v2.0  
> 状态: Draft — 等待用户确认  
> 作用域: mmap_optimizer 项目 extraction prompt patch 处理流程

---

## 1. 设计目标（用户期望的精确流程）

```
Step 1: Baseline Extraction — 对采样数据进行结果抽取和结果分析
  └─ 对 optimization_batch 样本跑当前 prompt → base_evals

Step 2: Accuracy Statistics — 统计准确率，记录正确/错误样本
  └─ 对每个样本标记 overall_status (correct/wrong/schema_error/parse_error)

Step 3: Patch Generation — 针对错误样本分析，提取 patch，记录 source_sample_ids
  └─ AnalysisRunner.analyze_errors(wrong_evals) → draft_patches → 静态校验 → candidate_patches
  └─ 每个 patch.source_sample_ids 记录其来源样本 ID

Step 4: Patch Merge — 对 patch 进行 tree_reduce merge (可选 semantic merge)
  └─ TreeReducePatchMerger.merge(candidate_patches) → merged_patches

Step 5: Re-test After Merge — 应用合并后的 patch 到当前 prompt，再进行抽取测试
  └─ 逐个 apply merged_patches 到 prompt → new_prompt
  └─ 对 optimization_batch 样本用 new_prompt 重新跑模型 → patched_evals
  └─ 重新统计准确率指标

Step 6: Comparison & Patch Filtering — 两次结果对比，过滤 patch
  ├─ 6.1 样本分类: 之前对依然对 / 之前错依然错 / 之前错现在对 / 之前对现在错
  ├─ 6.2 剔除无效 patch: 若 patch 来源样本中"之前错依然错"的样本占 100% → 剔除 INEFFECTIVE
  ├─ 6.3 收集测毒集: 之前对现在错的样本 → toxic_sample_ids
  ├─ 6.4 测毒: 在测毒集上，每个 patch 单独应用到原 prompt 上逐个测毒
  │   └─ 若某个 patch 在测毒集上产生变错 → 剔除 TOXIC
  └─ 6.5 最终 patch 集 = merged_patches - INEFFECTIVE - TOXIC

Step 7: Final Merge & Apply / Rollback — 最终 patch 集重新合并
  ├─ 若最终 patch 集非空:
  │   └─ 对 final_patches 再次进行 tree_reduce merge → 最终 merged
  │   └─ 应用到 prompt
  └─ 若最终 patch 集为空:
      └─ 本轮 patch 抽取和应用无效
      └─ prompt 回滚回本轮初始 prompt
      └─ 本轮重新进行以上步骤（Step 1 到 Step 7 重新执行）
```

---

## 2. 当前实现与用户期望的差距（逐条对比）

### Step 1 & Step 2: ✅ 已实现

- 入口: [round_runner.py:128-162](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L128-L162)
- `_prompt_runner().run()` → `extraction_runs`, `evals`
- 每个 eval 有 `overall_status`（correct/wrong/schema_error/parse_error）

### Step 3: ✅ 已实现（但后续流程需要调整）

- 入口: [round_runner.py:185-238](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L185-L238)
- `AnalysisRunner.analyze_errors(wrong_evals)` → `draft_patches`
- `PatchValidator.validate()` → `candidate_patches`
- **关键**: 每个 patch 已有 `source_sample_ids`（[patch/schema.py:27](file:///workspace/mmap_optimizer/patch/schema.py#L27)），在 [analysis/runner.py:171](file:///workspace/mmap_optimizer/analysis/runner.py#L171) 中设置为 `[sample_id]`
- tree_reduce merge 会合并 source_sample_ids（[tree_reduce.py:141](file:///workspace/mmap_optimizer/patch/tree_reduce.py#L141)）

### Step 4: ✅ 已实现（但需要在 Step 5 前单独保存合并后的 patch 集）

- 入口: [round_runner.py:248-269](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L248-L269)
- `TreeReducePatchMerger.merge()` → `merged_patches`
- 然后可选 SemanticPatchProcessor.merge/root_audit

### Step 5: ❌ 核心缺失（当前是逐个 patch 测试，不是整体合并后整体测试）

- **当前实现**: [round_runner.py:271-315](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L271-L315)
  - 对每个 `merged_patches` 的 patch 单独构造测试 suite，单独跑模型
  - 每个 patch 有自己独立的测试结果
  - **没有**把所有 merged_patches 整体应用到 prompt 再整体重新测试
- **用户期望**: 将所有 merged_patches 作为整体应用到 prompt，然后对 optimization_batch 样本整体重新抽取测试

### Step 6: ❌ 核心缺失（当前没有"基于整体测试结果反向归因"的逻辑）

- **当前实现**: 每个 patch 独立测试，独立判定有效/毒性
  - effective = fixed_sample_ids 非空（该 patch 自己跑的 suite 中 wrong 样本变 correct）
  - toxic = broken_sample_ids 非空（该 patch 自己跑的 suite 中 correct 样本变 wrong）
  - accept/reject 基于 individual test 结果
- **用户期望**:
  - **6.1** 先做整体测试（Step 5），对 optimization_batch 的所有样本拿到 patched_evals
  - **6.2** 用 base_evals vs patched_evals 对每个样本分类: 之前对依然对 / 之前错依然错 / 之前错现在对 / 之前对现在错
  - **6.3** 对每个 patch，检查其 source_sample_ids 对应的样本分类
    - 若 patch 来源样本全部是"之前错依然错" → reject INEFFECTIVE
    - 部分来源样本变对 → 保留
  - **6.4** 收集"之前对现在错"的样本 → toxic_sample_ids
  - **6.5** 在测毒集上，每个 patch 单独应用到原 prompt 上逐个测毒
    - 若某个 patch 在测毒集上有变错 → reject TOXIC
  - **6.6** final_patches = merged_patches - INEFFECTIVE - TOXIC

### Step 7: ❌ 核心缺失（当前没有"二次合并 + 空集回滚重试"逻辑）

- **当前实现**: accepted_patches → bundle test → apply + post_apply regression check
- **用户期望**:
  - **7.1** 对 final_patches（Step 6 后剩余的）再次进行 tree_reduce merge
  - **7.2** 若 final_patches 非空 → 应用到 prompt，完成本轮
  - **7.3** 若 final_patches 为空 → 
    - prompt 回滚回本轮初始 prompt
    - 本轮重新进行 Step 1 到 Step 7

---

## 3. 核心设计说明

### 3.1 Step 5 整体再测试（整体应用 → 整体测试）

```
input: merged_patches, state.active_extraction_prompt, optimization_batch
output: new_prompt_with_all_patches, patched_evals

流程:
  1. 逐个 apply merged_patches 中的每个 patch 到原 prompt，得到 new_prompt
  2. 用 new_prompt 对 optimization_batch 样本跑模型 → patched_evals
  3. 对每个样本计算整体准确率、错误类型
```

**实现方式**: 复用 `_prompt_runner().run()`（[round_runner.py:129](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L129)），换 prompt 为 new_prompt。

### 3.2 Step 6 样本分类与反向归因（核心创新点）

```
input: base_evals (from Step 1), patched_evals (from Step 5), merged_patches

6.1 样本分类:
  for each sample in optimization_batch:
    base_status = base_evals[sample_id].overall_status
    patched_status = patched_evals[sample_id].overall_status
    classify into 4 categories:
    (1) "之前对依然对" (UNCHANGED_CORRECT): base_status=="correct" AND patched_status=="correct"
    (2) "之前错依然错" (UNCHANGED_WRONG):     base_status!="correct" AND patched_status!="correct"
    (3) "之前错现在对" (FIXED):                  base_status!="correct" AND patched_status=="correct"
    (4) "之前对现在错" (BROKEN):                 base_status=="correct" AND patched_status!="correct"

6.2 剔除 INEFFECTIVE patch:
  for each patch in merged_patches:
    source_samples = patch.source_sample_ids          # patch 来源样本
    still_wrong_count = count(s in source_samples where sample_class == UNCHANGED_WRONG)
    total_source_count = len(source_samples)
    if still_wrong_count == total_source_count:       # 所有来源样本都没被修正
        reject(patch, reason="INEFFECTIVE")

6.3 收集测毒集:
  toxic_sample_ids = [sample_id where sample_class == BROKEN]

6.4 在测毒集上逐个 patch 测毒:
  for each patch in non_ineffective_patches:
    temp_prompt = apply_patch_to_original_prompt(patch, state.active_extraction_prompt)
    # 在测毒集上跑模型
    test_evals = run_prompt_on_samples(temp_prompt, toxic_sample_ids)
    # 判定: 是否有样本从 correct 变 wrong（注意: 这里 patch 单独应用，原 prompt 中这些样本本来是 correct）
    has_broken = any(e.overall_status != "correct" for e in test_evals)
    if has_broken:
        reject(patch, reason="TOXIC")
        patch.broken_sample_ids = [e.sample_id for e in test_evals if e.overall_status != "correct"]

6.5 最终 patch 集:
  final_patches = [p for p in merged_patches if p.status == "accepted"]
```

**关键语义说明**：
- Step 6.2 中的"剔除无效 patch"用的是**整体测试结果**，即所有 patch 一起应用后的效果
- 这与当前实现中"每个 patch 单独测试"的逻辑有本质区别：一个 patch 可能在单独测试时修复了某个样本，但在整体应用时被其他 patch 的冲突抵消，导致该样本仍然错误
- Step 6.4 中的测毒是把每个 patch 单独应用到**原始 prompt**（不是已被整体修改过的 prompt），在测毒集上测试 → 判断该 patch 本身是否有毒

### 3.3 Step 7 最终 merge + 应用 / 回滚

```
if final_patches is not empty:
  # 7.1 再次 tree_reduce merge
  final_merged = TreeReducePatchMerger().merge(patches=final_patches, prompt_ir=...)
  # 7.2 应用到 prompt
  for patch in final_merged.final_patches:
    state.active_extraction_prompt = PatchApplier().apply(state.active_extraction_prompt, patch, ...)
  # 本轮完成，进入后续流程（compression/fewshot/analysis evolution）

else:
  # 7.3 回滚 + 重试
  state.active_extraction_prompt = initial_extraction_prompt   # 回滚到本轮开始时的 prompt
  round_restart_attempt_count += 1
  # 检查是否达到最大重试次数（防止无限循环）
  if round_restart_attempt_count > max_restart_attempts:
    # 记录失败原因，结束本轮（不产生任何 patch 应用）
    round_record.status = "ROUND_NO_EFFECTIVE_PATCHES"
    continue_to_next_round()
  else:
    # 重新执行 Step 1 → Step 7
    restart_from_step_1()
```

**设计决策**: 需要在 `RoundRunner` 内部保存一份 `initial_extraction_prompt` 快照（本轮开始时的 prompt），用于回滚。同时需要配置 `max_restart_attempts` 参数。

---

## 4. 详细实施方案

### 4.1 新增/修改的文件

| # | 文件 | 改动类型 | 说明 |
|---|------|----------|------|
| 1 | [records.py](file:///workspace/mmap_optimizer/orchestration/records.py) | 扩展 | 新增 RoundStage 枚举值: PATCH_MERGED_TEST, PATCH_COMPARISON, FINAL_MERGE |
| 2 | [config.py](file:///workspace/mmap_optimizer/core/config.py) | 扩展 | 新增 max_restart_attempts 配置，patch_toxic_test_sample_ratio |
| 3 | [round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) | **核心重构** | 5 阶段 → 7 阶段流程 |
| 4 | [suite_builder.py](file:///workspace/mmap_optimizer/testing/suite_builder.py) | 新增方法 | build_toxic_suite() |

### 4.2 RoundStage 枚举变更

[records.py:8-24](file:///workspace/mmap_optimizer/orchestration/records.py#L8-L24)

```python
class RoundStage(str, Enum):
    INIT = "init"
    OPTIMIZATION_BATCH_SELECT = "optimization_batch_select"
    BASELINE_EVAL = "baseline_eval"
    DYNAMIC_VALIDATION = "dynamic_validation"
    PATCH_GENERATION = "patch_generation"
    PATCH_VALIDATION = "patch_validation"    # 保留（用于静态校验阶段标记）
    PATCH_MERGED_TEST = "patch_merged_test"    # 🆕 Step 5: 整体合并后再测试
    PATCH_COMPARISON = "patch_comparison"       # 🆕 Step 6: 两次结果对比分析
    PATCH_EVAL = "patch_eval"                    # 保留（Step 6.4 测毒阶段）
    PATCH_TREE_REDUCE = "patch_tree_reduce"
    FINAL_MERGE = "final_merge"                   # 🆕 Step 7: 最终 merge + 应用/回滚
    PATCH_APPLY = "patch_apply"
    COMPRESSION = "compression"
    FEWSHOT = "fewshot"
    ANALYSIS_EVOLUTION = "analysis_evolution"
    METRICS = "metrics"
    COMPLETED = "completed"
    FAILED = "failed"
```

### 4.3 配置字段变更

[config.py](file:///workspace/mmap_optimizer/core/config.py)

```python
# 新增
max_restart_attempts: int = 3      # Step 7 中 patch 集为空时的最大重试次数
patch_toxic_test_sample_ratio: float = 1.0  # 测毒集采样比例（默认全部测试）

# 修改/保留
patch_semantic_merge_enabled: bool = True    # Step 4 / Step 7 中的 semantic merge
patch_repair_enabled: bool = False
patch_repair_max_attempts: int = 1
post_apply_regression_enabled: bool = True    # 保留现有 post_apply regression check
post_apply_regression_sample_ratio: float = 0.3
canary_protection_enabled: bool = True
canary_min_consecutive_correct: int = 3
canary_max_count: int = 10
historical_regression_check_enabled: bool = True
```

### 4.4 round_runner.py 核心流程重构

**原有流程代码位置**: [round_runner.py:181-374](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L181-L374)

**重构后流程**:

```python
# 在 run_round() 内部
round_id = f"round_{round_index:06d}"

# 保存本轮初始 prompt 快照（用于 Step 7 回滚）
initial_extraction_prompt = state.active_extraction_prompt  # 深拷贝，需保证不可变

for restart_attempt in range(self.config.max_restart_attempts):

    ┌──────────────────────────────────────────────────────────┐
    │ Step 1 & 2: Baseline Extraction + Statistics           │
    │ （已有实现，无需改动）                                   │
    │ optimization_batch = select_optimization_batch(...)    │
    │ extraction_result = _prompt_runner().run(prompt=initial_prompt) │
    │ base_evals = extraction_result.evaluations              │
    └──────────────────────────────────────────────────────────┘
    # base_evals 已包含每个样本的 overall_status

    wrong_evals = [e for e in base_evals if e.overall_status != "correct"]
    if not wrong_evals:
        # 没有错误样本，本轮不需要 patch
        break

    ┌──────────────────────────────────────────────────────────┐
    │ Step 3: Patch Generation                                 │
    │ （已有实现，保留静态校验 + 可选 LLM 修复）                │
    │ analysis_result = AnalysisRunner.analyze_errors(wrong_evals) │
    │ draft_patches = analysis_result.draft_patches            │
    │ for patch in draft_patches:                              │
    │     PatchValidator.validate()                            │
    │     if invalid and patch_repair_enabled:               │
    │         PatchRepairEngine.repair_locator()              │
    │ candidate_patches / rejected_patches                    │
    └──────────────────────────────────────────────────────────┘

    if not candidate_patches:
        # 没有有效 patch，回滚重试
        continue  # 进入下一次 restart

    ┌──────────────────────────────────────────────────────────┐
    │ Step 4: Patch Merge (tree_reduce + 可选 semantic merge) │
    │ merge_result = TreeReducePatchMerger.merge(candidate_patches) │
    │ merged_patches = merge_result.final_patches              │
    │ if patch_semantic_merge_enabled:                         │
    │     merged_patches = SemanticPatchProcessor.merge(merged_patches) │
    │ if patch_root_audit_enabled:                             │
    │     merged_patches = SemanticPatchProcessor.root_audit(merged_patches) │
    │ 再次 PatchValidator.validate(merged_patches)             │
    └──────────────────────────────────────────────────────────┘

    if not merged_patches:
        # merge 后没有 patch，回滚重试
        continue

    ┌──────────────────────────────────────────────────────────┐
    │ Step 5: Re-test After Merge — 🆕 整体应用 + 整体测试    │
    │ temp_prompt = initial_extraction_prompt                   │
    │ for patch in merged_patches:                              │
    │     temp_prompt = PatchApplier().apply(temp_prompt, patch) │
    │ 用 temp_prompt 对 optimization_batch 重新跑模型            │
    │ patched_result = _prompt_runner().run(prompt=temp_prompt)  │
    │ patched_evals = patched_result.evaluations                │
    └──────────────────────────────────────────────────────────┘

    ┌──────────────────────────────────────────────────────────┐
    │ Step 6: Comparison & Patch Filtering — 🆕 两次结果对比    │
    │                                                          │
    │ 6.1 样本分类（base_evals vs patched_evals）              │
    │ 6.2 剔除 INEFFECTIVE patch（来源样本之前错依然错）        │
    │ 6.3 收集测毒集（之前对现在错）                            │
    │ 6.4 在测毒集上逐个 patch 测毒                            │
    │ 6.5 final_patches = merged_patches - INEFFECTIVE - TOXIC │
    └──────────────────────────────────────────────────────────┘
    # 详见 4.5 节详细实现

    ┌──────────────────────────────────────────────────────────┐
    │ Step 7: Final Merge & Apply / Rollback — 🆕             │
    │ if final_patches is not empty:                          │
    │     7.1 对 final_patches 再次进行 tree_reduce merge      │
    │     7.2 应用到 state.active_extraction_prompt             │
    │     7.3 记录 patch_test_results / merge_report            │
    │     break  # 本轮完成，退出 restart 循环                  │
    │ else:                                                    │
    │     7.3 回滚 prompt: state.active_extraction_prompt = initial_prompt │
    │     continue  # 进入下一次 restart_attempt                │
    └──────────────────────────────────────────────────────────┘

# 超出 max_restart_attempts 或成功完成
if restart_attempt >= self.config.max_restart_attempts:
    # 标记: 多次重试后仍无有效 patch
    round_record.status = "ROUND_NO_EFFECTIVE_PATCHES"
    # prompt 保持为 initial_extraction_prompt
```

### 4.5 Step 6 详细实现

```python
# Step 6.1: 样本分类
# 为每个样本建立 base_evals 与 patched_evals 的对应关系
base_by_sample = {e.sample_id: e for e in base_evals}
patched_by_sample = {e.sample_id: e for e in patched_evals}

sample_classes: dict[str, str] = {}  # sample_id → UNCHANGED_CORRECT/UNCHANGED_WRONG/FIXED/BROKEN

for sample_id in set(base_by_sample.keys()) & set(patched_by_sample.keys()):
    base_status = base_by_sample[sample_id].overall_status
    patched_status = patched_by_sample[sample_id].overall_status
    sample_classes[sample_id] = classify_transition(base_by_sample[sample_id], patched_by_sample[sample_id])

# Step 6.2: 剔除 INEFFECTIVE patch
final_patches = []
for patch in merged_patches:
    # 获取 patch 来源样本的分类结果
    source_samples = patch.source_sample_ids
    # 检查所有来源样本是否"之前错依然错"
    still_wrong = [s for s in source_samples if s in sample_classes and sample_classes[s] == "unchanged_wrong"]
    # 如果来源样本都没变对（且有来源样本），则认为该 patch 无效
    if source_samples and len(still_wrong) == len(source_samples):
        patch.status = "rejected"
        patch.rejection_reason = "INEFFECTIVE"
        patch.fixed_sample_ids = []
        rejected_patches.append(patch)
    else:
        patch.effectiveness_result = "effective" if any(
            s in sample_classes and sample_classes[s] == "fixed"
            for s in source_samples
        ) else "partially_effective"
        final_patches.append(patch)

# Step 6.3: 收集测毒集
toxic_sample_ids = [
    sample_id for sample_id, cls in sample_classes.items()
    if cls == "broken"  # 之前对现在错
]

# Step 6.4: 在测毒集上逐个 patch 测毒
if toxic_sample_ids:
    test_patches = final_patches[:]
    final_patches = []

    for patch in test_patches:
        # 把单个 patch 应用到原始 prompt
        temp_prompt = PatchApplier().apply(
            initial_extraction_prompt, patch,
            new_version=initial_extraction_prompt.version + 1,
            round_id=round_id,
        )
        # 在测毒集上跑模型
        toxic_samples = [s for s in state.samples if s.id in set(toxic_sample_ids)]
        if not toxic_samples:
            final_patches.append(patch)
            continue
        toxic_test_result = self._prompt_runner().run(
            round_id=round_id,
            run_type=RunType.REGRESSION_CHECK.value,
            prompt=temp_prompt,
            samples=toxic_samples,
            assets=state.assets,
            ground_truths=state.ground_truths,
            contract=state.extraction_output_schema_contract,
        )
        # 检查是否变错
        has_broken = any(e.overall_status != "correct" for e in toxic_test_result.evaluations)
        broken_ids = [e.sample_id for e in toxic_test_result.evaluations if e.overall_status != "correct"]
        patch.broken_sample_ids = broken_ids
        if has_broken:
            patch.status = "rejected"
            patch.rejection_reason = "TOXIC"
            patch.toxicity_result = "toxic"
            rejected_patches.append(patch)
        else:
            patch.status = "accepted"
            patch.toxicity_result = "non_toxic"
            final_patches.append(patch)
else:
    # 没有测毒样本，所有 final_patches 标记为 accepted
    for patch in final_patches:
        patch.status = "accepted"
        patch.toxicity_result = "non_toxic"
        patch.broken_sample_ids = []

# Step 6.5: final_patches = [p for p in merged_patches if p.status == "accepted"]
# final_patches 已在上面的循环中构建完成
```

### 4.6 Step 7 详细实现

```python
# Step 7.1: 对 final_patches 再次进行 tree_reduce merge
if final_patches:
    self._advance_stage(round_id, round_record, RoundStage.FINAL_MERGE.value)
    final_merge_result = TreeReducePatchMerger().merge(
        round_id=round_id,
        patches=final_patches,
        prompt_ir=state.active_extraction_prompt.prompt_ir,
    )
    final_merged = final_merge_result.final_patches
    # 可选: semantic merge / root_audit
    if self.config.patch_semantic_merge_enabled and final_merged:
        semantic_processor = SemanticPatchProcessor(self.optimizer_client, self._optimizer_model_config())
        final_merged = semantic_processor.merge(final_merged, state.active_extraction_prompt.prompt_ir)
    if self.config.patch_root_audit_enabled and final_merged:
        final_merged = semantic_processor.root_audit(final_merged, state.active_extraction_prompt.prompt_ir)

    # Step 7.2: 应用 final_merged 到 prompt
    if final_merged:
        self._advance_stage(round_id, round_record, RoundStage.PATCH_APPLY.value)
        for patch in final_merged:
            state.active_extraction_prompt = PatchApplier().apply(
                state.active_extraction_prompt,
                patch,
                new_version=state.active_extraction_prompt.version + 1,
                round_id=round_id,
            )
        # 保留现有 post_apply_regression_check（对 correct 样本的 30% 采样回归）
        if self.config.post_apply_regression_enabled:
            regression_result = self._post_apply_regression_check(
                round_id=round_id,
                new_prompt=state.active_extraction_prompt,
                base_evaluations=base_evals,
                state=state,
            )
            if regression_result.regression_count > 0:
                # post_apply regression 检测到问题，回滚
                state.active_extraction_prompt = initial_extraction_prompt
                round_record.status = "ROUND_POST_APPLY_REGRESSION_ROLLBACK"
                break  # 不再重试，保留原 prompt

        # 成功完成
        accepted_patch_ids = [p.id for p in final_merged]
        round_record.accepted_patch_ids = accepted_patch_ids
        break  # 退出 restart 循环

# Step 7.3: patch 集为空，回滚 prompt，继续下一次 restart
state.active_extraction_prompt = initial_extraction_prompt
# 记录中间状态
self._save_intermediate(round_id, f"patch_filter_empty_retry_{restart_attempt}", {
    "attempt": restart_attempt,
    "reason": "No effective or non-toxic patches remained after filtering",
    "total_candidate_patches": len(candidate_patches),
    "total_merged_patches": len(merged_patches),
    "ineffective_rejected": sum(1 for p in rejected_patches if p.rejection_reason == "INEFFECTIVE"),
    "toxic_rejected": sum(1 for p in rejected_patches if p.rejection_reason == "TOXIC"),
})
# continue 到 for restart_attempt 循环的下一次迭代
```

### 4.7 initial_extraction_prompt 快照保存

```python
# 在 run_round() 开始处，进入 patch 流程之前保存初始 prompt
from copy import deepcopy

initial_extraction_prompt = deepcopy(state.active_extraction_prompt)
```

**设计决策**: 用 `deepcopy` 而不是引用，因为 `PatchApplier.apply()` 返回新的 `PromptVersion` 对象，但其中可能包含对原对象的引用（prompt_ir 等）。深拷贝确保回滚时能完全恢复。

---

## 5. 数据结构与配置变更详细清单

### 5.1 RoundStage 枚举扩展（3 个新值）

文件: [records.py](file:///workspace/mmap_optimizer/orchestration/records.py)

```python
class RoundStage(str, Enum):
    # ... 保留所有现有值 ...
    PATCH_MERGED_TEST = "patch_merged_test"      # 🆕 Step 5
    PATCH_COMPARISON = "patch_comparison"         # 🆕 Step 6
    FINAL_MERGE = "final_merge"                   # 🆕 Step 7
```

### 5.2 OptimizerConfig 新增字段（2 个）

文件: [config.py](file:///workspace/mmap_optimizer/core/config.py)

```python
max_restart_attempts: int = 3                    # Step 7 空集时最大重试次数
patch_toxic_test_sample_ratio: float = 1.0       # Step 6.4 测毒集采样比例
```

- validate() 中添加: `patch_toxic_test_sample_ratio` 范围校验 (0-1]
- from_dict() 中添加解析

### 5.3 Patch 状态字段（复用现有字段，无需新增）

文件: [schema.py](file:///workspace/mmap_optimizer/patch/schema.py)

Patch 对象已有以下字段，直接复用:

```python
source_sample_ids: list[str] = field(default_factory=list)   # ✅ 已存在，Step 6.2 需要
fixed_sample_ids: list[str] = field(default_factory=list)     # ✅ 已存在，Step 5 中记录
broken_sample_ids: list[str] = field(default_factory=list)    # ✅ 已存在，Step 6.4 需要
toxicity_result: str = "not_tested"                            # ✅ 已存在，Step 6.4 设置
effectiveness_result: str = "not_tested"                       # ✅ 已存在，Step 6.2 设置
rejection_reason: str | None = None                             # ✅ 已存在，设置 INEFFECTIVE/TOXIC
status: str                                                    # ✅ 已存在，accepted/rejected
```

### 5.4 suite_builder.py 新增方法

文件: [suite_builder.py](file:///workspace/mmap_optimizer/testing/suite_builder.py)

```python
def build_toxic_suite(self, *, round_id: str, sample_ids: list[str]) -> PatchTestSuite:
    """构造测毒集 suite。用于 Step 6.4。

    sample_ids: 之前对现在错的样本 ID 列表
    """
    return PatchTestSuite(
        id=f"suite_{round_id}_toxic",
        round_id=round_id,
        sample_ids=sample_ids,
        suite_type="toxic_detection",
        composition={
            "total_samples": len(sample_ids),
            "source": "broken_from_merged_test",
        },
    )
```

---

## 6. 中间产物与落盘

需要新增以下落盘点（调用 `_save_intermediate`）:

| 阶段 | key | 内容 |
|------|-----|------|
| Step 5 后 | `patch_merged_test_done` | merged patch 数量、样本数量、各状态样本分布 |
| Step 6.2 后 | `patch_ineffective_filter_done` | 筛选前数量、筛选后数量、INEFFECTIVE 列表 |
| Step 6.4 后 | `patch_toxic_test_done` | 测毒集大小、TOXIC patch 列表、每个 patch 的 broken sample |
| Step 7 后 | `final_merge_done` | final_merged patch 数量、应用结果 |
| 回滚时 | `patch_restart_attempt_{n}` | 重试原因、各阶段被 reject 的 patch 统计 |

---

## 7. 测试验证计划

### 7.1 单元测试

| 测试 | 验证点 |
|------|--------|
| test_step5_merged_patch_re_test | Step 5: 整体应用 merged_patches 后整体测试，验证 patched_evals 中每个样本有 overall_status |
| test_step6_1_sample_classification | Step 6.1: 4 类分类逻辑正确 |
| test_step6_2_ineffective_patch_filter | Step 6.2: 来源样本全部"之前错依然错"时正确 reject |
| test_step6_2_patch_partially_effective | Step 6.2: 部分来源样本变对时保留 patch |
| test_step6_3_toxic_sample_collection | Step 6.3: 正确收集"之前对现在错"的样本 |
| test_step6_4_toxic_patch_detection | Step 6.4: 在测毒集上测到 broken 样本时 reject |
| test_step6_4_non_toxic_patch | Step 6.4: 在测毒集上无 broken 样本时保留 patch |
| test_step7_final_merge_with_patches | Step 7: final_patches 非空时正确二次 merge + apply |
| test_step7_empty_patches_rollback | Step 7: final_patches 为空时正确回滚 prompt |
| test_step7_max_restart_attempts | Step 7: 达到最大重试次数时正确终止 |

### 7.2 集成测试

- `test_full_7step_flow_integration`: 端到端流程完整测试，含 restart 场景
- 验证各阶段标记正确流转
- 验证中间产物正确落盘

### 7.3 回归测试

- 确保现有测试通过（`test_production_readiness_features` 等）
- 确保 backward compatibility: 新配置字段默认值保留旧行为

---

## 8. 向后兼容性说明

**无破坏性变更**:

1. 新增 RoundStage 枚举值 **不删除**任何旧值
2. 新增配置字段有默认值 (`max_restart_attempts=3`, `patch_toxic_test_sample_ratio=1.0`)
3. **不修改** Patch 数据结构，仅复用已有字段
4. TreeReducePatchMerger **无改动**
5. AnalysisRunner **无改动**
6. PatchApplier **无改动**
7. **post_apply_regression_check 保留** — Step 7 成功后仍可调用

---

## 9. 与当前实现的核心差异总结

| 维度 | 当前实现 | 用户期望（本设计） |
|------|---------|-------------------|
| Step 5 测试方式 | 逐个 patch 单独测试 suite | 所有 patch 整体应用 → 整体测试 |
| Step 6 无效判定 | 每个 patch 自己跑的 suite 中 fixed_sample_ids 是否为空 | 整体测试结果中 patch 来源样本是否全部"之前错依然错" |
| Step 6 毒性判定 | 每个 patch 自己跑的 suite 中是否有 correct 样本变 wrong | 先从整体测试找出"之前对现在错"的样本 → 在该集合上逐个 patch 测毒 |
| Step 7 二次 merge | 无（accepted_patches 直接 bundle test 后应用） | final_patches 需再次 tree_reduce merge |
| 空集处理 | accepted_patches 为空时直接跳过 patch apply，进入下一阶段 | prompt 回滚回初始状态，**重试**整个 7 步流程 |
| 归因方式 | 每个 patch 独立归因，可能漏检 patch 间的相互影响 | 先整体测试再反向归因，更准确识别无效/有毒 patch |

---

## 10. 风险评估

| 风险 | 说明 | 缓解措施 |
|------|------|----------|
| Step 5 增加一次完整 extraction call | 对 optimization_batch 重新跑一遍 extraction，增加模型调用成本 | 复用现有 `_prompt_runner().run()`，采样比例可配置 |
| Step 6.4 每个 remaining patch 都跑一次 toxic test | 如果有很多 patch，toxic_test_sample_ids 又很大，成本较高 | 默认采样比例 1.0，可降低；如果 toxic_sample_ids 为空则完全跳过 |
| Step 7 回滚重试可能导致总轮数增加 | 每轮最多 `max_restart_attempts` 次，默认 3 | 默认值较保守，用户可配置；重试时重新采样新的 optimization_batch，增加探索多样性 |
| deep_copy prompt 对象可能影响性能 | PromptVersion + PromptIR 对象较大 | 实际上对象大小通常 < 1MB，影响可忽略 |
| tree_reduce merge 第二次 merge 结果可能与第一次相同（patch 间无冲突时） | Step 7.1 的二次 merge 可能是冗余的 | 当 final_patches 数量与 merged_patches 数量相同且无被 reject 时，二次 merge 与第一次相同，可优化为跳过 |

---

**文档结束。请审核确认设计方向，确认后开始实施代码改造。**
