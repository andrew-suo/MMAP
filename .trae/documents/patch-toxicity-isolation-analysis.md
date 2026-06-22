# Patch 测毒与有毒 Patch 定位逻辑分析

## 摘要

**回答用户问题：有逐个 patch 测试的逻辑，但策略与"逐个应用到原 prompt 后对中毒样本测试"不同。**

当前代码采用的是**贪心安全子集（greedy safe-subset）**策略：按顺序逐个把 patch **累加**应用到已接受 patch 之上的 prompt，在**完整 optimization_batch** 上测试，只要破坏任意原本正确的样本就标记为 TOXIC 并剔除。而设计文档中描述的"在 toxic_sample_ids 子集上逐个 patch 单独应用到原 prompt 测试"的方案**未被实现**——相关组件（`PatchTester`、`build_toxic_suite`、`patch_toxic_test_sample_ratio`）已定义但从未接入主流程。

## 当前状态分析

### 测毒完整流程

主流程位于 [round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) 的 `_run_extraction_optimization` 方法。

#### Step 6: 合并后整体重测（PATCH_MERGED_TEST）

**位置**：[round_runner.py:951-980](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L951-L980)

- 把所有 `merged_patches` **一次性全部**应用到 `temp_prompt`
- 在**完整 `optimization_batch`** 上重新跑抽取评估
- 产出 `patched_evals`，用于后续 Step 7 的对比
- 日志 stage：`patch_merged_test_done`

#### Step 7.1: 样本转换分类

**位置**：[round_runner.py:989-996](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L989-L996)

使用 `classify_transition()` 将每个样本分为 `fixed` / `broken` / `unchanged_wrong` / `unchanged_correct`。

#### Step 7.2: 剔除无效 patch（INEFFECTIVE）

**位置**：[round_runner.py:998-1010](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L998-L1010)

如果 patch 的所有 source_samples 仍然错误，标记为 `INEFFECTIVE` 并拒绝。

#### Step 7.3: 贪心安全子集（核心测毒逻辑）

**位置**：[round_runner.py:1012-1054](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L1012-L1054)

```python
cumulative_patches: list = []
cumulative_prompt = state.active_extraction_prompt
for patch in non_ineffective:
    trial_prompt = PatchApplier().apply(
        cumulative_prompt, patch,
        new_version=cumulative_prompt.version + 1,
    )
    trial_result = self._prompt_runner().run(
        round_id=round_id,
        run_type=RunType.PATCH_TEST_EXTRACTION.value,
        prompt=trial_prompt,
        samples=optimization_batch,   # 完整 optimization_batch，不是 toxic 子集
        ...
    )

    # 检查回归：任何原本正确的样本现在变错 → 该 patch 有毒
    trial_by_sample = {e.sample_id: e for e in trial_result.evaluations}
    has_broken_any = False
    for base_eval in evals:
        if base_eval.overall_status != "correct":
            continue
        trial_eval = trial_by_sample.get(base_eval.sample_id)
        if trial_eval is not None and trial_eval.overall_status != "correct":
            has_broken_any = True
            break

    if has_broken_any:
        patch.status = "rejected"
        patch.rejection_reason = "TOXIC"
        patch.toxicity_result = "toxic"
    else:
        patch.toxicity_result = "non_toxic"
        cumulative_patches.append(patch)
        cumulative_prompt = trial_prompt
        safe_subset_evals = trial_result.evaluations
```

**算法说明**：
1. 维护 `cumulative_patches` 列表和 `cumulative_prompt`（已接受 patch 累加后的 prompt）
2. 遍历 `non_ineffective` patch（顺序就是 `merged_patches` 的顺序）
3. 对每个 patch，把它应用到 `cumulative_prompt` 上得到 `trial_prompt`
4. 在**完整 `optimization_batch`** 上测试 `trial_prompt`
5. 检查是否有任意一个"原本正确"的样本变错（`has_broken_any`）
6. 若有毒 → 标记 `status="rejected"`, `rejection_reason="TOXIC"`, `toxicity_result="toxic"`，**不加入 cumulative**
7. 若无毒 → 标记 `toxicity_result="non_toxic"`，加入 `cumulative_patches`，更新 `cumulative_prompt`
8. 最终 `safe_subset_evals` 保存最后一次成功接受的测试结果

### toxic_sample_ids 的计算

**位置**：[round_runner.py:1058](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L1058)

```python
toxic_sample_ids = [sid for sid, cls in sample_classes.items() if cls == "broken"]
```

**重要**：这个 `toxic_sample_ids` 是基于 Step 6 的"全量合并测试"结果计算的（即所有 patch 一起应用后变错的样本），它**仅用于日志和上报**（`patch_comparison_done` stage），**不参与任何隔离决策**。

## 设计文档 vs 实际实现对比

| 维度 | 设计文档方案（[extraction-patch-7step-design.md](file:///workspace/.trae/documents/extraction-patch-7step-design.md)） | 实际代码（Step 7.3） |
|------|------|------|
| 测试集 | `toxic_sample_ids`（broken 样本并集）的子集 | 完整 `optimization_batch` |
| 测试方式 | 每个 patch 单独应用到**原始 prompt** | 每个 patch 累加应用到**已接受 patch 之上**的 prompt |
| Suite 构造 | `build_toxic_suite()` | 不使用 suite，直接用 `optimization_batch` |
| 测试工具 | `PatchTester.test_individual()` | `self._prompt_runner().run()` |
| 隔离判定 | 在 toxic 样本上是否仍破坏 | 是否破坏任意原本正确的样本 |
| `broken_sample_ids` 回写 | 回写到 patch | **不回写** |

## 未被使用的测毒组件

以下组件已实现但**未在主流程中被调用**：

### 1. `PatchTester` 类

**位置**：[mmap_optimizer/testing/patch_runner.py](file:///workspace/mmap_optimizer/testing/patch_runner.py)

- `test_individual()`：对单个 patch 构建 temp_prompt 并测试
- `test_bundle()`：对 patch 组合构建 temp_prompt 并测试
- 全代码库搜索 `PatchTester(` 仅在定义处和测试文件中出现，**round_runner.py 中未实例化**

### 2. `PatchTestSuiteBuilder` 类

**位置**：[mmap_optimizer/testing/suite_builder.py](file:///workspace/mmap_optimizer/testing/suite_builder.py)

- `build_individual_suite()`（行 9-28）
- `build_bundle_suite()`（行 30-54）
- `build_toxic_suite()`（行 56-72）：文档注释明确写"Used in Step 6.4: after identifying previously correct, now broken samples, each candidate patch is re-applied individually and tested on this toxic sample set."
- 全代码库搜索 `PatchTestSuiteBuilder` 仅在定义处出现，**round_runner.py 中未导入或使用**

### 3. `patch_toxic_test_sample_ratio` 配置

**位置**：[mmap_optimizer/core/config.py:76](file:///workspace/mmap_optimizer/core/config.py#L76)

- 定义了默认值 0.5
- 有校验逻辑（行 128-129）
- 但**从未被读取使用**（搜索结果只有定义和校验，没有任何 `self.config.patch_toxic_test_sample_ratio` 的读取）

## 中毒样本（broken_sample_ids）的来源和用途

### Patch.broken_sample_ids 字段

**位置**：[mmap_optimizer/patch/schema.py:32](file:///workspace/mmap_optimizer/patch/schema.py#L32)

```python
broken_sample_ids: list[str] = field(default_factory=list)
```

**实际赋值情况**：在主流程（extraction optimization）中，Patch 对象的 `broken_sample_ids` 字段**从未被赋值**。它只在以下位置被赋值：
- `fewshot/pool.py:76`：fewshot 候选池状态（与 extraction patch 无关）
- `fewshot/engine.py:171`：fewshot 报告（与 extraction patch 无关）

### PatchTestResult.broken_sample_ids

**位置**：[mmap_optimizer/testing/patch_tester.py:25](file:///workspace/mmap_optimizer/testing/patch_tester.py#L25)

由 `summarize_patch_test()`（行 60）填充：
```python
elif transition == "broken":
    result.broken_sample_ids.append(patched.sample_id)
```

但 `summarize_patch_test()` 在主流程中**只在 round 结束时被调用一次用于生成上报数据**（[round_runner.py:617-631](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L617-L631)），其结果写入 `patch_test_results.jsonl`，**不参与任何决策**。

### 结论

**`broken_sample_ids` 字段在 Patch schema 上存在，但在主 extraction 流程中从未被填充。** 实际的有毒样本信息是通过 `sample_classes`（Step 7.1 的转换分类）和 `toxic_sample_ids`（Step 7 末尾的计算）临时承载的，并未回写到具体 patch 对象上。这是一个设计-实现差距。

## 有毒 patch 的下游处理（Analysis Evolution）

**位置**：[round_runner.py:1604-1620](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L1604-L1620)

有毒 patch 信息会被传递给分析 prompt 的"影子进化"流程：

```python
toxic_patches = [
    p for p in (extraction_result.candidate_patches or [])
    if getattr(p, "toxicity_result", None) == "toxic"
]
```

**注意两个潜在问题**：
1. 这里从 `extraction_result.candidate_patches` 中筛选 toxic patch，但 Step 7.3 中标记 `toxicity_result="toxic"` 的是 `merged_patches` 中的 patch，而 `candidate_patches` 是 Step 4 产出的、未合并的候选 patch。两者的 patch id 不同（merged patch 是合并后的新 id），因此这个筛选**很可能匹配不到任何 toxic patch**。
2. `broken_sample_ids=getattr(patch, "broken_sample_ids", None) or []` 永远返回 `[]`，因为 Patch 上的该字段从未被赋值。

这些 `patch_test_results` 传给 `AnalysisEvolutionEngine.evolve()`，触发 `toxic_patch` 信号，生成"风险策略"分析 patch，用于改进分析 prompt 让它未来更好地识别有毒 patch 风险。但这是**分析 prompt 的自我改进**，不是对当前有毒 patch 的隔离。

## 相关日志 Stage 汇总

| Stage 名 | 位置 | 含义 |
|------|------|------|
| `patch_merged_test_done` | [round_runner.py:977](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L977) | 合并补丁整体测试完成（Step 6） |
| `patch_comparison_done` | [round_runner.py:1066](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L1066) | 补丁比较与筛选完成（Step 7），携带 `toxic_samples` 数量 |

**注意**：没有专门的 `toxic_test_start` / `toxic_test_done` / `patch_isolation_*` stage。设计文档提到的 `patch_toxic_test_start` / `patch_toxic_test_done` 在实际代码中**不存在**。

## 核心结论

1. **有逐个 patch 测试**：Step 7.3 的贪心安全子集算法确实是对每个 patch 逐个测试的。

2. **但策略与设计文档不同**：
   - **不是**"逐个 patch 单独应用到原 prompt 然后在 toxic 样本上测试"
   - **而是**"逐个 patch 累加应用到已接受 patch 之上的 prompt，在完整 optimization_batch 上测试，破坏任意原本正确的样本就剔除"

3. **设计文档描述的方案未被实现**：`PatchTester`、`PatchTestSuiteBuilder`、`build_toxic_suite`、`patch_toxic_test_sample_ratio` 等组件和配置已实现但未接入主流程。

4. **`broken_sample_ids` 字段在主流程中从未被填充**：实际的有毒样本信息通过 `sample_classes` 和 `toxic_sample_ids` 临时承载，仅用于日志上报，未回写到 patch 对象。

5. **潜在 bug**：`_run_analysis_evolution` 从 `candidate_patches` 筛选 toxic patch，但 toxic 标记在 `merged_patches` 上，两者 patch id 不同，可能匹配不到任何 toxic patch。
