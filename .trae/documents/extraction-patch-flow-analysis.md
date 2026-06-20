# Extraction Prompt Patch 流程分析报告

> 本报告为只读分析，未修改任何代码。分析对象：当前 `main` 分支（`d9db29a`）的实现。

## 一、用户期望的 7 步流程

1. **patch generation** — 生成 patch
2. **patch merge** — 对生成的 patch 进行 merge
3. **patch validation** — merge 完成后对 merge 结果进行再次测试
4. **剔除无效 patch** — 对比 patch 生成和 validation 后的结果，剔除掉没有修正的样本对应的 patch
5. **测毒剔除毒性 patch** — 对于由对变错的样本，逐个把剩余的 patch 应用到原来的 prompt，并在变错的样本集上进行测毒，找出让样本变差的 patch 并剔除
6. **二次 merge** — 对新的 patch 集再进行 merge
7. **最终 test** — 最后再进行一次测试

## 二、当前实际实现流程

整个 patch 处理集中在 [round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) 的 `RoundRunner.run_round()` 方法（line 85-550），只有当 `wrong_evals` 非空时（line 181-182）才触发。实际流程为 5 个阶段：

### 实际阶段 A：Patch Generation + 静态校验 + LLM 修复

**位置**：[round_runner.py:182-246](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L182-L246)

- 阶段标记：`RoundStage.PATCH_GENERATION`（line 183）
- 调用 `AnalysisRunner.analyze_errors(...)`（line 185-198）生成 `draft_patches`
- 对每个 draft patch 执行**静态结构校验** `PatchValidator().validate()`（line 210）— 校验 section 是否存在/冻结、operation 是否允许、locator 是否唯一匹配，**不跑模型**
- 若 invalid 且 `patch_repair_enabled`，调用 `PatchRepairEngine.repair_locator()`（line 214-218）做 LLM + 模糊匹配修复，最多 `patch_repair_max_attempts` 次
- 通过 → `candidate_patches`；未通过 → `rejected_patches`
- 阶段标记：`RoundStage.PATCH_VALIDATION`（line 240）— **命名误导**：这只是生成阶段静态校验完成的标记，**不是对 merge 结果的测试**

### 实际阶段 B：Patch Merge（tree_reduce + 可选 semantic merge / root audit）

**位置**：[round_runner.py:248-269](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L248-L269)

- 阶段标记：`RoundStage.PATCH_TREE_REDUCE`（line 249）
- 调用 `TreeReducePatchMerger().merge(...)`（line 248），策略为 tree_reduce：
  - 按 `(target_prompt_type, section_id, operation_type)` 聚类
  - 检测冲突（frozen section、OK/NG 偏置、宽严、操作冲突）→ 冲突 patch 直接 reject
  - 去重和吸收（`is_duplicate_patch` / `is_subsumed_patch`）
  - 簇内剩余 >1 个 patch 时拼接 patch_text 生成 merged patch
- 若 `patch_semantic_merge_enabled` 或 `patch_root_audit_enabled`（line 254-269）：
  - `SemanticPatchProcessor.merge()` 做 LLM 语义合并
  - `SemanticPatchProcessor.root_audit()` 做 LLM 根因审计
  - 再次用 `PatchValidator.validate()` 静态校验
- 阶段标记：`RoundStage.PATCH_RANKING`（line 270）— **命名误导**：实际没有 ranking 逻辑

### 实际阶段 C：Individual Patch Test（逐 patch 跑模型，同时判定 ineffective + toxic）

**位置**：[round_runner.py:271-315](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L271-L315)

- 阶段标记：`RoundStage.PATCH_EVAL`（line 310）
- 对每个 `merged_patches` 中的 patch：
  - `PatchTestSuiteBuilder().build_individual_suite(...)`（line 278）构造测试集，包含：source 错误样本 + canary 样本 + historically_fixed 样本 + 当前 correct 样本 + 当前 wrong 样本（最多 48 个，见 [suite_builder.py:9-16](file:///workspace/mmap_optimizer/testing/suite_builder.py#L9-L16)）
  - `PatchTester.test_individual(...)`（line 280）把 patch 应用到临时 prompt 跑模型
  - `summarize_patch_test(...)`（[patch_tester.py:38-88](file:///workspace/mmap_optimizer/testing/patch_tester.py#L38-L88)）对比 base_evals 和 patched_evals，按 `classify_transition` 分类：
    - `fixed_sample_ids`（wrong→correct）
    - `broken_sample_ids`（correct→wrong）
    - `unchanged_wrong_sample_ids`
    - `unchanged_correct_sample_ids`
  - 判定逻辑（[patch_tester.py:75-87](file:///workspace/mmap_optimizer/testing/patch_tester.py#L75-L87)）：
    - `effectiveness_result = "effective" if fixed_sample_ids else "ineffective"`
    - `toxicity_result = "toxic" if broken_sample_ids else "non_toxic"`
    - `accepted = fixed_sample_ids 非空 AND broken_sample_ids 为空 AND 无 schema/parse 错误 AND canary 未破 AND 历史固定样本未回归`
  - 接受 → `accepted_patches`；拒绝 → `rejected_patches`（reason 为 `TOXIC` / `INEFFECTIVE` / `CANARY_BROKEN` / `HISTORICAL_REGRESSION`）

**关键观察**：用户期望的「步骤 3（merge 后再测试）」「步骤 4（剔除未修正 patch）」「步骤 5（在变错样本上测毒）」在当前实现中**被合并成这一个阶段**。这里既没有先做一次「merge 结果验证测试」，也没有在测出 toxic 后再把剩余 patch 单独拿到「变错样本集」上重新跑——而是每个 patch 各自跑一次包含 correct 样本的 suite，broken 样本就是 toxic 信号。

### 实际阶段 D：Bundle Testing / Safe Bundle Selection（组合安全性测试）

**位置**：[round_runner.py:316-334](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L316-L334)，调用 `_select_safe_bundle`（[round_runner.py:553-616](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L553-L616)）

- 若 `accepted_patches` 非空，调用 `_select_safe_bundle(...)`
- 先用 `build_bundle_suite` + `test_bundle` 把所有 accepted patches 一起应用并测试（line 569-588）
- 若 bundle 通过 → 直接返回全部 accepted patches
- 否则按 `len(fixed_sample_ids)` 降序逐个尝试加入 safe 集合（line 591-616），每次重新 `test_bundle`，剔除导致 bundle 失败的 patch（标记 `BUNDLE_TOXIC` 或 `BUNDLE_INEFFECTIVE`）
- 输出：`final_patches`

### 实际阶段 E：Patch Apply + Post-apply Regression Check

**位置**：[round_runner.py:335-374](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L335-L374)

- 阶段标记：`RoundStage.PATCH_APPLY`（line 370）
- 对 `final_patches` 逐个 `PatchApplier().apply(...)` 更新 `state.active_extraction_prompt`
- 若 `post_apply_regression_enabled`（默认 True），调用 `_post_apply_regression_check`（[round_runner.py:684-726](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L684-L726)）：
  - 从 `correct` 的 base evals 中按 `post_apply_regression_sample_ratio`（默认 0.3）采样
  - 用新 prompt 跑这些样本，若任一样本 `classify_transition == "broken"`，则**回滚所有 patch**（line 360-366），全部标记 `POST_APPLY_REGRESSION`
- 这是当前流程中**唯一接近「最终 test」的环节**，但只是对 correct 样本的回归采样检查，不是对全量样本的最终测试

## 三、用户期望 7 步流程 vs. 当前实现 对照表

| # | 用户期望步骤 | 当前实现状态 | 实现位置 / 说明 |
|---|---|---|---|
| 1 | patch generation | **已实现** | [round_runner.py:182-246](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L182-L246)；入口 `AnalysisRunner.analyze_errors`，存储于内存 `draft_patches` / `candidate_patches` |
| 2 | patch merge（tree_reduce） | **已实现** | [round_runner.py:248-269](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L248-L269)；策略为 `TreeReducePatchMerger`，可选叠加 `SemanticPatchProcessor.merge` 和 `root_audit` |
| 3 | patch validation（对 merge 结果再次测试） | **未实现（命名误导）** | 代码里 `RoundStage.PATCH_VALIDATION`（[round_runner.py:240](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L240)）只是「生成阶段静态校验完成」的标记，**并没有对 merged_patches 跑模型做再次测试**。merged_patches 第一次跑模型是在阶段 C 的 individual test |
| 4 | 剔除没有修正的样本对应的 patch | **功能等价但合并** | 没有独立步骤。在阶段 C 的 `summarize_patch_test` 中，若 `fixed_sample_ids` 为空 → `effectiveness_result="ineffective"` → patch 被 reject（reason=`INEFFECTIVE`）。见 [patch_tester.py:75-79](file:///workspace/mmap_optimizer/testing/patch_tester.py#L75-L79) |
| 5 | 对「由对变错」样本逐个测毒，剔除毒性 patch | **功能等价但合并且方式不同** | 同样在阶段 C 的 individual test 中：suite 已包含 `current_correct` 样本（[suite_builder.py:14](file:///workspace/mmap_optimizer/testing/suite_builder.py#L14)），若 patched 把 correct 样本变错 → `broken_sample_ids` 非空 → `toxicity_result="toxic"` → reject（reason=`TOXIC`）。但这是**每个 patch 各自测一次**，并不是用户描述的「先收集所有变错样本，再把剩余 patch 逐个应用到这个集合上」的二次测毒流程 |
| 6 | 剔除毒性 patch 后对新 patch 集再次 merge | **完全未实现** | 阶段 C 之后直接进入阶段 D 的 bundle test，**没有第二次 `TreeReducePatchMerger().merge(...)` 调用**。全局搜索 `TreeReducePatchMerger` 只有 [round_runner.py:248](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L248) 一处调用 |
| 7 | 最终 test | **部分实现** | 阶段 D 的 `test_bundle`（[round_runner.py:571-583](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L571-L583)）是对最终 patch 集的合并测试；阶段 E 的 `_post_apply_regression_check` 是对 correct 样本的 30% 采样回归测试。但**没有对全量样本（含 wrong 样本）的最终完整 test** |

## 四、关键差异点详解

### 差异 1：步骤 3 缺失（merge 后没有再次测试）

用户期望 merge 完成后先对 merge 结果做一次测试。当前代码在 merge 后（[round_runner.py:248-269](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L248-L269)）只做了静态 `PatchValidator.validate`，然后直接进入 individual test。`RoundStage.PATCH_VALIDATION` 这个阶段名容易让人误以为是「merge 结果验证测试」，但实际只是生成阶段静态校验的结束标记。

### 差异 2：步骤 4 和 5 被合并进 individual test

用户期望的「先剔除 ineffective、再单独测毒」两步，在当前实现中被合并成一次 individual test 调用（[round_runner.py:277-307](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L277-L307)）。`summarize_patch_test` 一次性产出 `fixed_sample_ids`、`broken_sample_ids`，并同时给出 `effectiveness_result` 和 `toxicity_result`，accept 条件同时检查两者。

这种合并实现的功能等价于「步骤 4 + 步骤 5」，但**不是用户描述的「逐个把剩余 patch 应用到原来的 prompt，并在变错的样本集上进行测毒」**——当前是每个 patch 各自构造一个包含 correct 样本的 suite 来测，而不是先聚合一个「变错样本集」再统一测毒。

**两种方式的语义差异**：
- 当前方式：每个 patch 独立测试，toxic 判定基于「该 patch 是否破坏了 correct 样本」
- 用户期望方式：先找出所有被任何 patch 破坏的样本（变错样本集），再逐个把剩余 patch 应用到这个集合上测毒，找出具体是哪个 patch 导致了破坏

### 差异 3：步骤 6 完全缺失（没有二次 merge）

搜索 `TreeReducePatchMerger` 全局只有一处调用（[round_runner.py:248](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L248)）。individual test 之后直接进入 `_select_safe_bundle`，没有对「剔除毒性 patch 后的剩余集合」再做一次 tree_reduce merge。

这意味着：如果两个 patch 在第一次 merge 时因为与某个毒性 patch 冲突而未被合并，剔除毒性 patch 后它们本可以重新 merge，但当前实现不会这样做。

### 差异 4：步骤 7 部分实现

- `test_bundle`（[round_runner.py:571](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L571)）是对最终 patch 集的合并测试，可视为某种「最终 test」，但它发生在 apply 之前，且仅测 patch 的 source 样本 + canary + hist_fixed + 部分 correct/wrong（最多 96 个）
- `_post_apply_regression_check`（[round_runner.py:684-726](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L684-L726)）是 apply 之后的回归测试，但只采样 30% 的 correct 样本，不测 wrong 样本，也不是全量最终 test

## 五、阶段标记枚举对照

阶段枚举定义在 [orchestration/records.py:8-24](file:///workspace/mmap_optimizer/orchestration/records.py#L8-L24)：

```
INIT, OPTIMIZATION_BATCH_SELECT, BASELINE_EVAL, DYNAMIC_VALIDATION,
PATCH_GENERATION, PATCH_VALIDATION, PATCH_TREE_REDUCE, PATCH_EVAL,
PATCH_RANKING, PATCH_APPLY, COMPRESSION, FEWSHOT, ANALYSIS_EVOLUTION,
METRICS, COMPLETED, FAILED
```

注意：
- 枚举里有 `PATCH_RANKING` 但代码里没有任何 ranking 逻辑（[round_runner.py:270](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L270) 只是标记，无实际 ranking）
- `PATCH_VALIDATION` 不对应「merge 结果再次测试」，只是生成阶段静态校验完成的标记
- 这两个命名都容易引起误解

## 六、总结

### 当前实际流程（按代码顺序）

1. Patch Generation（含静态校验 + 可选 LLM 修复）
2. Patch Merge（tree_reduce + 可选 semantic merge / root audit + 静态复校）
3. Individual Patch Test（每个 patch 各自跑模型，同时判定 ineffective 和 toxic，等价于「用户期望的步骤 3+4+5 合并」）
4. Bundle Test / Safe Bundle Selection（组合安全性测试，剔除导致 bundle 失败的 patch）
5. Patch Apply + Post-apply Regression Check（30% 采样回归）
6. （无二次 merge）
7. （无全量最终 test，只有 bundle test 和采样回归）

### 用户期望 7 步流程的实现状态

- 步骤 1（generation）：**已实现**
- 步骤 2（merge）：**已实现**（tree_reduce）
- 步骤 3（merge 后再测试）：**未实现**（`PATCH_VALIDATION` 阶段只是静态校验完成的标记，不跑模型）
- 步骤 4（剔除未修正 patch）：**功能等价但合并**（在 individual test 中由 `effectiveness_result="ineffective"` 判定，无独立步骤）
- 步骤 5（在变错样本上测毒）：**功能等价但合并且方式不同**（在 individual test 中由 `toxicity_result="toxic"` 判定，每个 patch 各自测，而非聚合变错样本集再测）
- 步骤 6（二次 merge）：**完全未实现**
- 步骤 7（最终 test）：**部分实现**（bundle test + 30% 采样回归，无全量最终 test）

### 顺序差异

用户期望「merge → 验证测试 → 剔除 ineffective → 测毒剔除 toxic → 二次 merge → 最终 test」这种 6 步迭代收敛流程；当前实现是「merge → 一次性 individual test（同时完成 ineffective 剔除和 toxic 剔除）→ bundle test → apply + 采样回归」的线性流程，缺少：
- merge 后的独立验证测试（步骤 3）
- 剔除毒性 patch 后的二次 merge（步骤 6）
- 全量最终 test（步骤 7 的完整版）

### 功能等价性评估

虽然步骤 4 和 5 在当前实现中被合并且方式不同，但**功能上基本等价**：都能剔除 ineffective 和 toxic 的 patch。主要的功能性缺口在于：
1. **步骤 3**：merge 后没有独立验证测试，无法发现 merge 过程引入的问题（如 merge 后的 patch 语义偏移）
2. **步骤 6**：没有二次 merge，可能错过剔除毒性 patch 后的重新合并机会
3. **步骤 7**：没有全量最终 test，apply 后只做 30% 采样回归，可能漏掉 wrong 样本的回归问题

---

**本报告为只读分析，未修改任何代码。请审核。**
