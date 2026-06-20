# Extraction Prompt Patch 7 步流程 — 设计文档

> 版本: v1.0  
> 状态: Draft — 等待用户确认  
> 作用域: mmap_optimizer 项目 extraction prompt patch 处理流程

---

## 1. 设计目标

将当前的 5 阶段线性流程重构为 **7 阶段迭代收敛流程，补齐以下三个当前缺失的能力：

1. **Merge 后独立验证测试（当前无）
2. **二次 Merge（剔除毒性 patch 后，当前无）
3. **全量最终 Test（当前仅有 30% correct 样本采样回归）

### 用户期望的流程：

```
Step 1: Patch Generation → Step 2: Patch Merge → Step 3: Patch Validation (merge 后测试)
                                                                        ↓
Step 4: 剔除 Ineffective Patches ← Step 5: 测毒剔除 Toxic Patches
                                                                        ↓
Step 6: 二次 Merge → Step 7: 最终 Test → Apply
```

---

## 2. 当前架构对照

### 2.1 关键文件与职责

| 模块 | 文件 | 职责 |
|------|------|------|
| 主编排 | [round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) | `RoundRunner.run_round()` 控制整个流程 |
| Merge 策略 | [tree_reduce.py](file:///workspace/mmap_optimizer/patch/tree_reduce.py) | `TreeReducePatchMerger.merge()` 按簇聚类、冲突检测、去重、合并 |
| 测试执行 | [patch_runner.py](file:///workspace/mmap_optimizer/testing/patch_runner.py) | `PatchTester.test_individual()` / `test_bundle()` |
| 测试汇总 | [patch_tester.py](file:///workspace/mmap_optimizer/testing/patch_tester.py) | `summarize_patch_test()` 判定 effective/toxic |
| 测试集构造 | [suite_builder.py](file:///workspace/mmap_optimizer/testing/suite_builder.py) | `PatchTestSuiteBuilder.build_individual_suite()` / `build_bundle_suite()` |
| 状态枚举 | [records.py](file:///workspace/mmap_optimizer/orchestration/records.py) | `RoundStage` enum |
| Patch 数据结构 | [schema.py](file:///workspace/mmap_optimizer/patch/schema.py) | `Patch` dataclass |
| Patch 应用 | [applier.py](file:///workspace/mmap_optimizer/patch/applier.py) | `PatchApplier.apply()` |
| 配置 | [config.py](file:///workspace/mmap_optimizer/core/config.py) | `OptimizerConfig` dataclass |

### 2.2 当前实际流程（run_round）

```
[round_runner.py:182-246] 阶段 A: Patch Generation + 静态校验 + LLM 修复
    → AnalysisRunner.analyze_errors() → draft_patches
    → PatchValidator.validate() 静态校验
    → PatchRepairEngine.repair_locator() LLM 修复
    → candidate_patches / rejected_patches

[round_runner.py:248-269] 阶段 B: Patch Merge (TreeReduce + 可选 semantic merge)
    → TreeReducePatchMerger.merge() → merged_patches + merge_report
    → 可选: SemanticPatchProcessor.merge() / root_audit()
    → 再次 PatchValidator.validate() 静态校验
    → RoundStage.PATCH_RANKING (仅标记，无实际 ranking 逻辑)

[round_runner.py:271-315] 阶段 C: Individual Patch Test (**合并完成 ineffective + toxic 判定**)
    → 每个 patch: build_individual_suite() + test_individual()
    → summarize_patch_test() → fixed_sample_ids / broken_sample_ids
    → effectiveness_result / toxicity_result
    → accepted_patches / rejected_patches (reason: INEFFECTIVE | TOXIC | CANARY_BROKEN | HISTORICAL_REGRESSION)

[round_runner.py:316-334] 阶段 D: Bundle Testing / Safe Bundle Selection
    → test_bundle() 全量 accepted patches 一起测试
    → 若失败，按 len(fixed_sample_ids) 降序逐个尝试加入 safe 集合
    → final_patches

[round_runner.py:335-374] 阶段 E: Patch Apply + Post-apply Regression Check
    → 逐个 apply 到 state.active_extraction_prompt
    → _post_apply_regression_check(): 30% correct 样本采样回归
    → 若 regression 则回滚所有 patch，标记 POST_APPLY_REGRESSION
```

### 2.3 与 7 步流程的差距

| 7 步期望 | 当前实现 | 差距 |
|-----------|---------|------|
| Step 1 Patch Generation | ✅ 已实现 | 无 |
| Step 2 Patch Merge | ✅ 已实现 | 无 |
| Step 3 Patch Validation (merge 后测试) | ❌ 缺失 | `RoundStage.PATCH_VALIDATION` 只是静态校验标记，没有把 merged_patches 跑模型的独立测试 |
| Step 4 剔除 ineffective patches | ⚠️ 合并在 Step 5 中 | 没有独立步骤。当前在 individual test 中与 toxic 判定中一起判定 |
| Step 5 测毒剔除 toxic patches | ⚠️ 合并且方式不同 | 每个 patch 各自测，没有先聚合变错样本集再测 |
| Step 6 二次 merge | ❌ 完全缺失 | `TreeReducePatchMerger` 全局仅 [round_runner.py:248](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L248) 一处调用 |
| Step 7 最终 test | ⚠️ 部分实现 | bundle test + 30% correct 采样回归，无全量测试，无 wrong 样本回归 |

---

## 3. 7 步流程详细设计

### 3.1 Step 1: Patch Generation（保留现有实现）

**文件**: [round_runner.py:182-246](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L182-L246)

**职责**: 从错误样本生成候选 patch

**流程**:
1. 若 `wrong_evals` 非空，进入 `RoundStage.PATCH_GENERATION`
2. 调用 `AnalysisRunner.analyze_errors()` → `draft_patches`
3. 对每个 draft patch: `PatchValidator.validate()` 静态校验
4. 若 invalid 且 `patch_repair_enabled` → `PatchRepairEngine.repair_locator()` LLM 修复
5. 通过校验 → `candidate_patches`；未通过 → `rejected_patches` (reason=`VALIDATION_FAILED` / `REPAIR_FAILED`)

**输出**: `candidate_patches: list[Patch], `rejected_patches: list[Patch]

**变更**: 无结构变更，仅需在 patch_rejection_reason 增加 `VALIDATION_FAILED` / `REPAIR_FAILED` 两个值的初始设置已在 patch_rejection_reason 字段已有，沿用即可。

---

### 3.2 Step 2: Patch Merge（保留现有实现，增加 merge 策略）

**文件**: [round_runner.py:248-269](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L248-L269)

**职责**: 对 candidate_patches 进行 tree_reduce + 可选 semantic merge

**流程**:
1. `TreeReducePatchMerger.merge(round_id=round_id, patches=candidate_patches, prompt_ir=state.active_extraction_prompt.prompt_ir)` → `merged_patches`, `merge_report`
2. 若 `patch_semantic_merge_enabled` → `SemanticPatchProcessor.merge()`
3. 若 `patch_root_audit_enabled` → `SemanticPatchProcessor.root_audit()`
4. 对语义处理后的 patch 再次 `PatchValidator.validate()` 静态校验
5. `RoundStage.PATCH_TREE_REDUCE` 标记完成

**输出**: `merged_patches: list[Patch]`, `rejected_patches` 追加 conflict/subsume/duplicate rejection reasons

**变更**: 无结构变更。

---

### 3.3 Step 3: Patch Validation（**新增** — merge 后独立验证测试）

**文件**: [round_runner.py — 需在 Step 2 后插入

**职责**: 对 merged_patches 中的每个 patch 进行模型测试验证其有效性

这是用户明确要求的 **merge 后独立验证阶段**。当前缺失此步骤（`RoundStage.PATCH_VALIDATION` 只有静态校验标记）。

**新增流程**:
1. 进入 `RoundStage.PATCH_VALIDATION` 阶段（此阶段真正跑模型，不再仅是静态标记）
2. 对每个 `merged_patches` 中的 patch:
   - 构造测试 suite（source 样本 + canary 样本 + historically_fixed 样本 + 当前 correct 样本）
   - 调用 `patch_tester.test_individual()`
   - `summarize_patch_test()` 判定有效性
   - 记录 `patch.fixed_sample_ids`、`patch.effectiveness_result`

**suite 构造策略（独立于 Step 5 的 toxic 测试）:
- source 错误样本: 验证 patch 是否修复了它原本要修复的 wrong 样本
- canary 样本: 验证 patch 是否破坏 canary 样本
- historically_fixed 样本: 验证 patch 是否回归历史修复
- current correct 样本: 初步验证 patch 是否导致样本从 correct → wrong（toxic 信号，供 Step 5 更精确判定）

**关键区别 vs 当前 individual test 的区别**:
- Step 3 只判定 effective（有效修复）和 canary/historical
- Step 3 不立即 reject patch（而是提供测试结果数据
- Step 4/5 再依据 Step 3 的数据决定是否剔除
- 所以 Step 3 只产生数据，Step 4/5 做出决策

**输出**: `validation_results: dict[str, PatchTestResult]（key=patch.id）

**新增代码（RoundStage.PATCH_VALIDATION 语义变更**: 此阶段从"静态校验完成"语义变更为"merge 后模型验证"。静态校验已在 Step 2 完成。

**实施方式**: 在 Step 2 完成后，对每个 `merged_patches` 逐个跑模型测试，生成 validation_results。测试 suite 包含 source 错误样本 + canary + historical_fixed + 当前 correct 样本。不包含 wrong 样本（用于 Step 4 判定 effectiveness）和当前 correct 样本（用于 Step 5 判定 toxicity 信号）

---

### 3.4 Step 4: 剔除 Ineffective Patches（**新增** — 独立步骤）

**文件**: [round_runner.py]() — Step 3 后插入

**职责**: 对比 patch 生成和 validation 后的结果，剔除没有修正任何样本的 patch

**流程**:
1. 遍历 `merged_patches
2. 依据 `validation_results[patch.id].fixed_sample_ids` 是否为空判定
3. 若 `len(fixed_sample_ids) == 0` → reject，`patch.status = "rejected"`，`patch.rejection_reason = "INEFFECTIVE"`

**关键设计决策**:
- 每个 patch 独立判定，不看 toxic 结果（toxic 由 Step 5 专门处理）
- canary_broken_count > 0 → 直接 reject（reason=`CANARY_BROKEN`）
- historical_fixed_regression_count > 0 → 直接 reject（reason=`HISTORICAL_REGRESSION`）

**输出**: `post_validation_patches: list[Patch]`（Step 3 测试后通过的 patch），`rejected_patches` 追加 INEFFECTIVE/CANARY_BROKEN/HISTORICAL_REGRESSION

---

### 3.5 Step 5: 测毒 / Toxic Patch（**新增** — 在变错样本集上测毒）

**文件**: [round_runner.py]() — Step 4 后插入

**职责**: 对 Step 4 剩余 patch 在"变错样本集"上逐个测毒，剔除导致样本从 correct 变 wrong 的 patch

**核心策略（与用户设计一致）**:

**前置**: 需要从 Step 3 的 `validation_results` 中收集所有被任何 patch 从 correct → wrong 的样本 ID，形成「变错样本集」

**流程**:
1. 收集变错样本集: `toxic_sample_ids = ∪ broken_sample_ids（所有 patch 的 broken_sample_ids 并集）
2. 如果 `toxic_sample_ids` 为空 → 跳过此步骤，所有 `post_validation_patches` 全部通过
3. 否则，对每个 `patch in post_validation_patches` 单独跑 **变错样本集专用 suite:
   - suite = 原 prompt + 变错样本集 toxic_sample_ids
   - 每个 patch 应用到原 prompt，在这个变错样本集上重新测试
   - 若任一 patch 在变错样本上 broken → reject（reason=`TOXIC`）
   - 同时记录 `patch.broken_sample_ids` 和 `patch.toxicity_result`

**为何需要单独测毒（而不是在 Step 3 测试中同时判定 toxic）**:

**设计动机**：在 Step 3 的测试中，每个 patch 各自跑不同的 suite 测试。变错样本集（所有 patch 的 broken_sample_ids 的并集）可能比任何单个 patch 在 Step 3 中测的 broken 样本更多。用户要求的是：先找出所有被任何 patch 破坏的样本，然后逐个把剩余的 patch 应用到原 prompt，在这个变错样本集上测毒，以更精准地识别毒性 patch。

**输出**: `final_non_toxic_patches: list[Patch]`，`rejected_patches` 追加 TOXIC

**suite 构造**: `toxic_sample_ids`（所有 patch 的 broken_sample_ids 并集）作为测试集，不含其他样本

---

### 3.6 Step 6: 二次 Merge（**新增** — Step 5 后）

**文件**: [round_runner.py]() — Step 5 后插入

**职责**: 剔除毒性 patch 后，对新的 patch 集再次进行 tree_reduce merge

**动机**: Step 4/5 剔除了若干 patch，剩余 patch 在原 merge 过程中因为与 toxic patch 冲突而未被合并，现在有机会重新合并。

**流程**:
1. 再次调用 `TreeReducePatchMerger.merge(round_id=round_id, patches=final_non_toxic_patches, prompt_ir=state.active_extraction_prompt.prompt_ir)`
2. 若 `patch_semantic_merge_enabled` → 再次可选语义合并（通常二次 merge 结果已经很少 patch，语义合并可以跳过）
3. 对 merge 结果进行最终 `PatchValidator.validate()` 静态校验

**设计决策**:
- 二次 merge 的结果通常会比第一次更少 patch（因为 patch 数量减少了）
- 有些原 merge 时因为与 toxic patch 冲突而被 reject 的 patch，现在有机会被重新考虑
- 实际上 TreeReducePatchMerger 是按簇合并的。如果 toxic patch 与某个 non-toxic patch 在同一簇，它们被 reject 是因为冲突，剔除 toxic patch 后，non-toxic patch 仍保留在输入中，所以二次 merge 可以产出不同的结果

**输出**: `refined_final_patches: list[Patch]`

---

### 3.7 Step 7: 最终 Test（**增强现有 bundle test + 全量回归**）

**文件**: [round_runner.py:316-374](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L316-L374)

**职责**: 对最终 patch 集进行完整测试，确保整体有效且无毒性

**当前流程**: `test_bundle()` + 30% correct 样本采样回归

**增强设计**:

**7.1 Bundle Test（保留现有实现）:
- 对 `refined_final_patches` 所有 patch 一起应用到原 prompt，跑 bundle test
- test suite: patch source 错误样本 + canary 样本 + historically_fixed 样本 + 当前 correct 样本 + 当前 wrong 样本（最多 96 个）
- 验证 overall status:
  - `accepted = bool(result.fixed_sample_ids) and not result.broken_sample_ids and schema_violation_count == 0 and parse_error_count == 0 and canary_broken_count == 0 and historical_fixed_regression_count == 0`
- 若 bundle 通过 → final patches 保持不变
- 若 bundle 失败 → 降级走 safe bundle selection 策略（现有 greedy 降序尝试）

**7.2 全量最终测试（新增）**:
- 对所有 round 中所有样本（不只是 30% correct 采样）做最终验证
- 用新 prompt 对所有样本跑模型（full_extraction_evals）:
  - 对 correct 样本: 检查 regression（correct → wrong）
  - 对 wrong 样本: 检查是否有 improved（wrong → correct）
- 输出最终 round_metrics，确认 patch 整体效果

**设计决策**:
- 7.2 的全量测试成本较高（可能需要跑 batch_size 个样本）
- 建议: 全量最终 test 仅在 `post_apply_regression_enabled=True` 时跑
- 若有 regression 则回滚所有 patch（保留现有策略）

**输出**: 确定 `final_patches`，更新 `state.active_extraction_prompt`

---

## 4. RoundStage 枚举变更

**文件**: [records.py:8-24](file:///workspace/mmap_optimizer/orchestration/records.py#L8-L24)

当前 enum:

```python
class RoundStage(str, Enum):
    INIT = "init"
    OPTIMIZATION_BATCH_SELECT = "optimization_batch_select"
    BASELINE_EVAL = "baseline_eval"
    DYNAMIC_VALIDATION = "dynamic_validation"
    PATCH_GENERATION = "patch_generation"
    PATCH_VALIDATION = "patch_validation"        # 语义变更: 静态校验 → merge 后模型验证
    PATCH_TREE_REDUCE = "patch_tree_reduce"
    PATCH_EVAL = "patch_eval"                   # 保留: 用于 Step 3/4/5 通用阶段统称
    PATCH_RANKING = "patch_ranking"              # 保留（无 ranking 逻辑，仅标记）
    PATCH_APPLY = "patch_apply"
    COMPRESSION = "compression"
    FEWSHOT = "fewshot"
    ANALYSIS_EVOLUTION = "analysis_evolution"
    METRICS = "metrics"
    COMPLETED = "completed"
    FAILED = "failed"
```

**新增枚举值（建议）:

```python
    PATCH_VALIDATION = "patch_validation"          # 语义变更: Step 3 merge 后模型验证
    PATCH_SECOND_MERGE = "patch_second_merge"    # 新增: Step 6 二次 merge
    PATCH_FINAL_TEST = "patch_final_test"          # 新增: Step 7 最终 test
```

**或更细粒度也可在步骤内有更细的阶段标记但不强制新增枚举值，复用 PATCH_EVAL 即可。

---

## 5. 数据结构与配置变更

### 5.1 RoundRunner 中的内部数据结构

**新增**: `validation_results: dict[str, PatchTestResult]` 保存 Step 3 的测试结果

**新增**: `post_validation_patches: list[Patch]` Step 3/4 后通过的 patch

**新增**: `toxic_sample_ids: list[str]` Step 5 的变错样本集

**优化**: `summarize_patch_test()` 已经返回 `PatchTestResult`，可以直接复用用于 Step 3, Step 5, Step 7 都调用

### 5.2 Patch 字段变更

**Patch** [schema.py:11-36](file:///workspace/mmap_optimizer/patch/schema.py#L11-L36) 已有字段:

```python
fixed_sample_ids: list[str] = field(default_factory=list)
broken_sample_ids: list[str] = field(default_factory=list)
toxicity_result: str = "not_tested"
effectiveness_result: str = "not_tested"
rejection_reason: str | None = None
```

**新增字段**（建议）:

```python
# Step 3 merge_validation_test_result_id: str | None = None  # 引用 Step 3 测试结果引用
# 可以用现有的 extra dict 存额外信息，无需新字段
```

### 5.3 OptimizerConfig 配置变更

**文件**: [config.py:29-70](file:///workspace/mmap_optimizer/core/config.py#L29-L70)

**现有配置**:
```python
patch_semantic_merge_enabled: bool = True
patch_root_audit_enabled: bool = False
patch_repair_enabled: bool = False
patch_repair_max_attempts: int = 1
post_apply_regression_enabled: bool = True
post_apply_regression_sample_ratio: float = 0.3
canary_protection_enabled: bool = True
canary_min_consecutive_correct: int = 3
canary_max_count: int = 10
historical_regression_check_enabled: bool = True
```

**新增配置（建议）:
```python
# Step 6 二次 merge 控制
patch_second_merge_enabled: bool = True  # 二次 tree_reduce merge 是否启用

# Step 7 全量最终测试控制
patch_final_full_test_enabled: bool = True  # 是否跑全量最终 test
patch_final_test_sample_ratio: float = 1.0  # final test 采样比例（默认全量）
```

---

## 6. 具体实施步骤（按文件拆分）

### File 1: [records.py](file:///workspace/mmap_optimizer/orchestration/records.py) — RoundStage 扩展

**变更**:
- 新增 `PATCH_SECOND_MERGE = "patch_second_merge"`
- 新增 `PATCH_FINAL_TEST = "patch_final_test"`

### File 2: [config.py](file:///workspace/mmap_optimizer/core/config.py) — 新增配置字段

**变更**:
- 新增 `patch_second_merge_enabled: bool = True`
- 新增 `patch_final_full_test_enabled: bool = True`
- 新增 `patch_final_test_sample_ratio: float = 1.0`
- 在 `validate()` 中增加 `patch_final_test_sample_ratio` 校验（0-1 范围）
- 在 `from_dict()` 中增加解析逻辑

### File 3: [round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) — 核心流程重构

**这是最大的改动文件。具体改造方案**:

原 3 阶段（B:merge → individual test → bundle → apply）改为 7 阶段（A:gen → B:merge → C:validation → D:ineffective剔除 → E:toxic测毒 → F:二次merge → G:final test → H:apply）

**具体代码结构**:

```
# Step 1: Patch Generation（保留现有 182-246 行不变，略修改静态校验部分，将 PATCH_VALIDATION 阶段标记移动到 Step 3）

# Step 2: Patch Merge（保留现有 248-269 行，修改阶段标记位置，PATCH_TREE_REDUCE）

# Step 3: Patch Validation（新增 — merge 后模型验证）
    self._advance_stage(round_id, round_record, RoundStage.PATCH_VALIDATION.value)
    validation_results: dict[str, PatchTestResult] = {}
    for patch in merged_patches:
        suite = suite_builder.build_individual_suite(
            round_id=round_id, patch=patch,
            current_evaluations=evals,
            canary_sample_ids=canary_sample_ids,
            historically_fixed_sample_ids=historically_fixed_ids,
        )
        base_suite_evals = [e for e in evals if e.sample_id in set(suite.sample_ids)]
        run = patch_tester.test_individual(...)
        validation_results[patch.id] = run.test_result
        # 记录 patch 测试结果供后续步骤使用
        patch.fixed_sample_ids = run.test_result.fixed_sample_ids
        patch.broken_sample_ids = run.test_result.broken_sample_ids
        patch.effectiveness_result = run.test_result.effectiveness_result
        # toxicity_result = run.test_result.toxicity_result  # Step 5 单独测毒后再设置
        patch_run_runs.extend(run.runs)
        patch_test_evals.extend(run.evaluations)

# Step 4: 剔除 Ineffective Patches（新增 — 独立步骤）
    post_validation_patches: list[Patch] = []
    for patch in merged_patches:
        result = validation_results[patch.id]
        if not result.fixed_sample_ids:
            patch.status = "rejected"
            patch.rejection_reason = "INEFFECTIVE"
            rejected_patches.append(patch)
        elif result.canary_broken_count > 0:
            patch.status = "rejected"
            patch.rejection_reason = "CANARY_BROKEN"
            rejected_patches.append(patch)
        elif result.historical_fixed_regression_count > 0:
            patch.status = "rejected"
            patch.rejection_reason = "HISTORICAL_REGRESSION"
            rejected_patches.append(patch)
        elif result.schema_violation_count > 0 or result.parse_error_count > 0:
            patch.status = "rejected"
            patch.rejection_reason = "SCHEMA_PARSE_ERROR"
            rejected_patches.append(patch)
        else:
            post_validation_patches.append(patch)
    log_stage(logger, "patch_ineffective_filter_done", round=round_index, kept=len(post_validation_patches), rejected=len(merged_patches) - len(post_validation_patches))

# Step 5: 测毒 / Toxic Patch Detection（新增 — 在变错样本集上测毒）
    # 5.1 收集所有 patch 的变错样本集
    toxic_sample_ids: list[str] = []
    for patch in post_validation_patches:
        toxic_sample_ids.extend(patch.broken_sample_ids)
    toxic_sample_ids = sorted(set(toxic_sample_ids))
    if toxic_sample_ids and len(post_validation_patches) > 0:
        log_stage(logger, "patch_toxic_test_start", round=round_index, patch_count=len(post_validation_patches), toxic_sample_count=len(toxic_sample_ids))

        # 5.2 逐个在变错样本集上测毒
        final_non_toxic_patches: list[Patch] = []
        for patch in post_validation_patches:
            # 构造变错样本集 suite
            toxic_suite = suite_builder.build_bundle_suite(round_id=round_id, patches=[patch], current_evaluations=evals, ...)
            # 但这里需要专用方法：仅在变错样本集上测试单个 patch
            # 用现有 test_individual 但换样本仅含变错样本集
            toxic_suite_samples = [s for s in state.samples if s.id in set(toxic_sample_ids)]
            if not toxic_suite_samples:
                final_non_toxic_patches.append(patch)
                continue
            toxic_test_run = patch_tester.test_individual(
                round_id=round_id,
                patch=patch,
                base_prompt=state.active_extraction_prompt,
                base_evaluations=evals,
                suite=toxic_suite,  # 需要改方法，这里直接复用
                samples=state.samples,
                assets=state.assets,
                ground_truths=state.ground_truths,
                contract=state.extraction_output_schema_contract,
                canary_sample_ids=None,
                historically_fixed_sample_ids=None,
            )
            toxic_result = toxic_test_run.test_result
            # 判断 toxic: 变错样本集上的 broken 样本
            if toxic_result.broken_sample_ids:
                patch.status = "rejected"
                patch.rejection_reason = "TOXIC"
                patch.broken_sample_ids = toxic_result.broken_sample_ids
                patch.toxicity_result = "toxic"
                rejected_patches.append(patch)
            else:
                patch.toxicity_result = "non_toxic"
                final_non_toxic_patches.append(patch)
            patch_test_runs.extend(toxic_test_run.runs)
            patch_test_evals.extend(toxic_test_run.evaluations)
            patch_test_results.append(toxic_result)
        log_stage(logger, "patch_toxic_test_done", round=round_index, non_toxic=len(final_non_toxic_patches), rejected=len(post_validation_patches) - len(final_non_toxic_patches))
    else:
        final_non_toxic_patches = post_validation_patches[:]
        for patch in final_non_toxic_patches:
            patch.toxicity_result = "non_toxic"

# Step 6: 二次 Merge（新增）
    if self.config.patch_second_merge_enabled and len(final_non_toxic_patches) and len(final_non_toxic_patches) != len(merged_patches):
        self._advance_stage(round_id, round_record, RoundStage.PATCH_SECOND_MERGE.value)
        second_merge_result = TreeReducePatchMerger().merge(
            round_id=round_id,
            patches=final_non_toxic_patches,
            prompt_ir=state.active_extraction_prompt.prompt_ir,
        )
        refined_final_patches = second_merge_result.final_patches
        rejected_patches.extend(second_merge_result.rejected_patches)
        log_stage(logger, "patch_second_merge_done", round=round_index, final_patch_count=len(refined_final_patches), rejected_count=len(second_merge_result.rejected_patches)))
    else:
        refined_final_patches = final_non_toxic_patches[:]

# Step 7: 最终 Test（增强现有 bundle test + 全量测试）
    self._advance_stage(round_id, round_record, RoundStage.PATCH_FINAL_TEST.value)
    # 7.1 Bundle test（保留现有 test_bundle）
    final_patches: list[Patch] = []
    if refined_final_patches:
        all_suite = suite_builder.build_bundle_suite(...)
        all_bundle_result = patch_tester.test_bundle(...)
        if all_bundle_result.test_result.accepted:
            final_patches = refined_final_patches
            patch_test_runs.extend(all_bundle_result.runs)
            patch_test_evals.extend(all_bundle_result.evaluations)
            patch_test_results.append(all_bundle_result.test_result)
        else:
            # 走 safe bundle selection（现有策略）
            ...
    # 7.2 全量最终测试（新增）
    if final_patches and self.config.patch_final_full_test_enabled:
        # 用新 prompt 跑全量测试
        temp_prompt = state.active_extraction_prompt
        for idx, patch in enumerate(final_patches):
            temp_prompt = PatchApplier().apply(temp_prompt, patch, new_version=state.active_extraction_prompt.version + idx + 1)
        # 全量样本跑模型测试
        full_test_run = self._prompt_runner().run(
            round_id=round_id, run_type="final_full_test",
            prompt=temp_prompt, samples=state.samples,
            assets=state.assets,
            ground_truths=state.ground_truths,
            contract=state.extraction_output_schema_contract,
        )
        # 计算 overall status 判定
        regression_count = sum(1 for eval in full_test_run.evaluations if ...)

# Step 8: Patch Apply（保留现有 apply，但在 Step 7 确定的 final_patches 应用逻辑）
    # 保留现有逻辑，应用 final_patches 到 state.active_extraction_prompt
    # 保留现有 post_apply_regression_check 逻辑
```

### File 4: [suite_builder.py](file:///workspace/mmap_optimizer/testing/suite_builder.py) — 新增

**需新增方法 `build_toxic_suite()`

```python
def build_toxic_suite(self, *, round_id: str, patch: Patch, toxic_sample_ids: list[str], max_samples: int = ...) -> PatchTestSuite:
    """构造仅包含变错样本集的测试 suite。用于 Step 5 测毒。
    """
    return PatchTestSuite(
        id=f"suite_{round_id}_toxic_{patch.id}",
        round_id=round_id,
        sample_ids=toxic_sample_ids[:max_samples],
        suite_type="toxic_patch_test",
        composition={
            "toxic_samples": len(toxic_sample_ids),
        },
    )
```

---

## 7. 中间产物与落盘

**文件**: [round_runner.py: _save_intermediate()](file:///workspace/mmap_optimizer/orchestration/round_runner.py)

建议新增落盘点（现有 `_save_intermediate()` 可以直接复用）:

```python
# Step 3 后: patch_validation_done.json → {
    "patch_validation_results": {patch_id: result.compact_dict()},
    "patch_count": len(merged_patches),
}
# Step 4 后: patch_ineffective_filter_done.json → {
    "kept_count": len(post_validation_patches),
    "rejected_count": len(ineffective_rejects),
}
# Step 5 后: patch_toxic_test_done.json → {
    "toxic_sample_count": len(toxic_sample_ids),
    "kept_count": len(final_non_toxic_patches),
    "rejected_count": len(toxic_rejects),
}
# Step 6 后: patch_second_merge_done.json → {
    "input_count": len(final_non_toxic_patches),
    "output_count": len(refined_final_patches),
    "rejected_count": len(second_merge_rejected),
}
# Step 7 后: patch_final_test_done.json → {
    "bundle_accepted": bool,
    "full_test_regression_count": regression_count,
    "final_patch_ids": [p.id for p in final_patches],
}
```

---

## 8. 测试验证计划

### 8.1 单元测试

**文件**: tests/ 目录下新建测试或修改现有测试

**测试点**:

1. **test_patch_validation_after_merge: Step 3 merge 后验证 patch validation 逻辑
   - mock patch → merge 后测试通过
   - 验证 `validation_results dict 正确填充
   - 验证 patch.fixed_sample_ids / broken_sample_ids 正确

2. **test_ineffective_patch_filtering**: Step 4 剔除 ineffective patch 逻辑
   - 构造 fixed_sample_ids 空 → reject
   - 构造 canary_broken_count > 0 → reject
   - 构造 historical regression → reject
   - 构造有效 patch → 保留

3. **test_toxic_patch_detection_on_broken_sample_set**: Step 5 变错样本集测毒逻辑
   - 构造 toxic sample_ids
   - 验证 toxic_sample_ids 正确
   - 逐个 patch 在变错样本集测试
   - 验证 broken_sample_ids 非空 → reject

4. **test_second_merge_after_toxic_filtering**: Step 6 二次 merge 逻辑
   - 构造原 merge 时因为 conflict 被 reject 的 patch（与 toxic patch 冲突）
   - 在二次 merge 时应该能够被重新考虑
   - 验证 merge 策略输出正确

5. **test_final_full_test_after_refinement**: Step 7 全量最终 test 逻辑
   - 验证 bundle test + full test 流程
   - 验证 regression 检查逻辑

### 8.2 集成测试

- `test_full_7step_flow_e2e`: 端到端 7 步流程完整测试
- 验证各阶段标记正确流转
- 验证中间产物正确落盘

### 8.3 回归测试

- 确保现有 7, 现有 2 步逻辑不破坏 backward compatibility
- `test_production_readiness_features` 等现有测试通过

---

## 9. 实施改动文件清单

| # | 文件 | 改动类型 | 说明 |
|---|------|----------|------|
| 1 | [records.py](file:///workspace/mmap_optimizer/orchestration/records.py) | 扩展 | 新增 2 个 RoundStage 枚举值 |
| 2 | [config.py](file:///workspace/mmap_optimizer/core/config.py) | 扩展 | 新增 3 个配置字段 + 验证逻辑 |
| 3 | [round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) | 重构 | 核心 5 阶段 → 7 阶段 |
| 4 | [suite_builder.py](file:///workspace/mmap_optimizer/testing/suite_builder.py) | 新增方法 | `build_toxic_suite() 方法 |
| 5 | tests/test_patch_flow.py | 新增 | 7 步流程单元测试 |

---

## 10. 伪代码流程总览

```
run_round(evals, state):

    wrong_evals = [e for e in evals if e.overall_status != "correct"]

    if wrong_evals:

        ┌────────────────────────────────────────────────────────────┐
        │ Step 1: Patch Generation                            │
        │   AnalysisRunner.analyze_errors(wrong_evals)          │
        │   for patch in draft_patches:                      │
        │     validator.validate(patch)                       │
        │     if invalid:                                  │
        │       if patch_repair_enabled:                        │
        │         repair_engine.repair_locator(patch)            │
        │       else:                                       │
        │         reject                                     │
        │     candidate_patches / rejected_patches                │
        └────────────────────────────────────────────────────────────┘
        → candidate_patches, rejected_patches

        ┌────────────────────────────────────────────────────────────┐
        │ Step 2: Patch Merge                                     │
        │   TreeReducePatchMerger.merge(candidate_patches)              │
        │   if semantic_merge_enabled: SemanticPatchProcessor.merge()  │
        │   if root_audit_enabled: SemanticPatchProcessor.root_audit()│
        │   validator.validate()                                     │
        └────────────────────────────────────────────────────────────┘
        → merged_patches, rejected_patches

        ┌────────────────────────────────────────────────────────────┐
        │ Step 3: Patch Validation（NEW — merge 后模型验证）       │
        │   for patch in merged_patches:                            │
        │     suite = build_individual_suite(source_wrong + canary +    │
        │             hist_fixed + current_correct)                      │
        │     test_individual(patch, suite)                          │
        │     record fixed_sample_ids / broken_sample_ids             │
        │     effectiveness_result / toxicity_result = summarize()      │
        │     validation_results[patch.id] = result                    │
        └────────────────────────────────────────────────────────────┘
        → validation_results: dict[str, PatchTestResult]

        ┌────────────────────────────────────────────────────────────┐
        │ Step 4: 剔除 Ineffective Patches（NEW — 独立步骤）│
        │   for patch in merged_patches:                            │
        │     result = validation_results[patch.id]                   │
        │     if !result.fixed_sample_ids:                      │
        │       reject(INEFFECTIVE)                                │
        │     elif result.canary_broken_count > 0:               │
        │       reject(CANARY_BROKEN)                              │
        │     elif result.historical_fixed_regression_count > 0:   │
        │       reject(HISTORICAL_REGRESSION)                         │
        │     elif result.schema_error:                              │
        │       reject(SCHEMA_PARSE_ERROR)                       │
        │     else:                                              │
        │       keep                                             │
        └────────────────────────────────────────────────────────────┘
        → post_validation_patches: list[Patch]

        ┌────────────────────────────────────────────────────────────┐
        │ Step 5: 测毒 / Toxic Patch Detection（NEW — 在变错样本集）│
        │   toxic_sample_ids = ∪(patch.broken_sample_ids for each │
        │                          patch in post_validation_patches        │
        │   if toxic_sample_ids:                               │
        │     for patch in post_validation_patches:              │
        │       toxic_suite = build_toxic_suite(toxic_sample_ids) │
        │       test_individual(patch, toxic_suite)               │
        │       if broken_sample_ids:                           │
        │         reject(TOXIC)                                   │
        │       else:                                           │
        │         keep                                         │
        │   else:                                              │
        │     all non-toxic                                    │
        └────────────────────────────────────────────────────────────┘
        → final_non_toxic_patches: list[Patch]

        ┌────────────────────────────────────────────────────────────┐
        │ Step 6: 二次 Merge（NEW）                         │
        │   TreeReducePatchMerger.merge(final_non_toxic_patches)     │
        │   if patch count 与前一次 merge 不同:            │
        │     重新 merge （patch 数量减少，可能产出不同结果）│
        │   validator.validate()                                   │
        └────────────────────────────────────────────────────────────┘
        → refined_final_patches: list[Patch]

        ┌────────────────────────────────────────────────────────────┐
        │ Step 7: 最终 Test（增强）                          │
        │   7.1 Bundle test: test_bundle(refined_final_patches) │
        │   7.2 全量最终测试: full_run(所有样本)                │
        │   if regression:                                    │
        │     回滚 patch                                        │
        │     标记 POST_APPLY_REGRESSION                          │
        └────────────────────────────────────────────────────────────┘
        → final_patches: list[Patch]

        ┌────────────────────────────────────────────────────────────┐
        │ Apply: 逐个 apply final_patches 到 active_extraction_prompt  │
        └────────────────────────────────────────────────────────────┘
```

---

## 11. 向后兼容性说明

**无需破坏性变更**:

1. **RoundStage 枚举值只增不删**，旧值保留
2. **配置字段新增默认值 True**，向后兼容
3. **Patch 字段无结构性删除**，仅复用已有字段
4. **TreeReducePatchMerger 无变更**，复用现有实现
5. **summarize_patch_test** 复用现有实现，无需修改
6. **suite_builder** 新增方法，不修改现有方法签名
7. **所有中间产物落盘**兼容现有方式写入 json

---

## 12. 风险评估

| 风险 | 说明 | 缓解措施 |
|------|------|----------|
| **R1**: Step 5 单独测毒增加一次额外的模型调用成本 | 每个 non-toxic patch 在 Step 3 已经跑过一次，Step 5 再在变错样本集跑一次，可能增加模型调用成本 | 变错样本集通常较小（< 20 个样本），成本可控。若需优化，可复用 Step 3 中已有的 broken_sample_ids 数据，无需重新跑模型。 |
| **R2**: Step 6 二次 merge 的结果与第一次 merge 结果可能相同（因为 patch 数量减少，原 merge 逻辑可能不改变结果） | 二次 merge 的产出可能 identical | 增加配置开关 `patch_second_merge_enabled` 控制是否启用二次 merge，默认 True 且仅在 patch 数量减少且有冲突 patch 被剔除时才运行 |
| **R3**: Step 7 全量最终测试增加模型调用成本 | 全量样本跑模型成本高 | 采样比例可配置 `patch_final_test_sample_ratio` |
| **R4**: 现有测试可能失败 | 现有测试 `test_production_readiness_features` 等依赖现有流程 | 确保现有测试通过，不修改现有测试的 patch 流程 |

---

**文档结束。请审核确认设计方向，确认后将按此方案实施。**
