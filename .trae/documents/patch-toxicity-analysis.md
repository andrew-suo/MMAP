# Patch 测毒机制分析与增强方案

## 摘要

当前实现**已有 patch 测毒机制**，但仅覆盖"应用前"的毒性检测，缺少"应用后"的回归验证。具体来说：

- **已有**：Individual Patch Test（单 patch 测毒）+ Bundle Patch Test（多 patch 组合测毒）
- **缺失**：Post-apply 全量回归验证、Canary 样本保护、历史回归检测

## 当前状态分析

### 已有的测毒流程

#### 1. Individual Patch Test（单 patch 测毒）

**位置**：[round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L246-L278)

流程：
1. 对每个 merged patch，构建 individual test suite（`source + correct + wrong`，max 48 样本）
2. 将 patch 应用到临时 prompt，运行模型评估
3. 调用 `summarize_patch_test()` 对比 base vs patched
4. 通过 `classify_transition()` 判断每个样本的转换类型（fixed/broken/unchanged_wrong/unchanged_correct）
5. 判定毒性：`broken_sample_ids` 非空 → `toxicity_result = "toxic"`
6. 判定有效性：`fixed_sample_ids` 非空 → `effectiveness_result = "effective"`
7. 接受条件：有修复 + 无破坏 + 无 schema violation + 无 parse error

#### 2. Bundle Patch Test（多 patch 组合测毒）

**位置**：[round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L496-L553) `_select_safe_bundle()`

流程：
1. 先将所有 accepted patches 一起测试（全量 bundle）
2. 如果全量 bundle 通过 → 直接返回
3. 如果不通过 → 按 `fixed_sample_ids` 数量降序逐个添加 patch，每次测试组合
4. 任何 patch 加入后导致 bundle toxic → 标记为 `BUNDLE_TOXIC` 并剔除
5. 任何 patch 加入后导致 bundle ineffective → 标记为 `BUNDLE_INEFFECTIVE` 并剔除

#### 3. PatchTestResult 数据结构

**位置**：[patch_tester.py](file:///workspace/mmap_optimizer/testing/patch_tester.py#L18-L36)

```python
@dataclass
class PatchTestResult:
    fixed_sample_ids: list[str]           # ✅ 使用中
    broken_sample_ids: list[str]          # ✅ 使用中
    unchanged_wrong_sample_ids: list[str] # ✅ 使用中
    unchanged_correct_sample_ids: list[str] # ✅ 使用中
    schema_violation_count: int           # ✅ 使用中
    parse_error_count: int                # ✅ 使用中
    canary_broken_count: int = 0          # ❌ 字段存在但未使用
    historical_fixed_regression_count: int = 0  # ❌ 字段存在但未使用
    format_error_count: int = 0           # ❌ 字段存在但未使用
```

### 缺失的测毒能力

#### 缺失 1：Post-apply 全量回归验证

**问题**：当前测毒在"临时 prompt"上进行，但 patch 正式应用到 `active_extraction_prompt` 后，没有对全量样本做回归测试。

**具体场景**：
- Individual test 用 48 个样本测试，Bundle test 用 96 个样本测试
- 但实际数据集可能有数百个样本
- Patch 应用后，可能对未被测试的样本产生副作用

**当前代码**（[round_runner.py#L303-L315](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L303-L315)）：
```python
if final_patches:
    next_prompt = state.active_extraction_prompt
    for patch in final_patches:
        next_prompt = PatchApplier().apply(next_prompt, patch, new_version=next_version)
    state.active_extraction_prompt = next_prompt
    # ← 此处没有对 next_prompt 做全量回归验证
```

#### 缺失 2：Canary 样本保护

**问题**：`PatchTestResult.canary_broken_count` 字段已定义但从未被填充或检查。

**设计意图**：Canary 样本是一组"已知正确"的锚点样本，任何 patch 破坏 Canary 样本应直接拒绝，无论该 patch 修复了多少其他样本。

**当前代码**：
- `suite_builder.py` 中没有 canary 样本选择逻辑
- `summarize_patch_test()` 中没有 canary 检查逻辑
- `round_runner.py` 中没有 canary 保护决策逻辑

#### 缺失 3：历史回归检测

**问题**：`PatchTestResult.historical_fixed_regression_count` 字段已定义但从未被填充或检查。

**设计意图**：检测新 patch 是否导致"之前已修复的样本"重新出错（回归）。这是跨 round 的回归检测。

**当前代码**：
- `summarize_patch_test()` 只对比 base（当前 round）vs patched
- 不参考历史修复记录
- 无法检测"新 patch 导致旧修复失效"

## 增强方案

### 改动 1：Post-apply 回归验证

**文件**：`mmap_optimizer/orchestration/round_runner.py`

**改动**：在 patch 应用后、round 结束前，对 `active_extraction_prompt` 运行全量样本回归测试。

```python
# 在 patch apply 之后（约 L313 之后）
if final_patches:
    # ... 现有 apply 逻辑 ...
    state.active_extraction_prompt = next_prompt

    # 新增：Post-apply 回归验证
    if self.config.post_apply_regression_enabled:
        regression_result = self._post_apply_regression_check(
            round_id=round_id,
            new_prompt=state.active_extraction_prompt,
            base_evaluations=evals + dval_evals,
            state=state,
        )
        if regression_result.regression_count > 0:
            # 回滚到应用前的 prompt
            state.active_extraction_prompt = base_prompt_backup
            round_record.regression_detected = True
            round_record.regression_sample_ids = regression_result.regression_sample_ids
```

**新增方法**：`_post_apply_regression_check()`
- 对全量样本（或采样子集）运行新 prompt
- 对比 base evaluations
- 检测是否有 previously correct → now wrong 的回归
- 返回回归样本列表

### 改动 2：Canary 样本保护

**文件**：
- `mmap_optimizer/testing/suite_builder.py` — 新增 canary 样本选择
- `mmap_optimizer/testing/patch_tester.py` — 填充 `canary_broken_count`
- `mmap_optimizer/orchestration/round_runner.py` — canary 保护决策

**suite_builder.py 改动**：
```python
def build_individual_suite(self, ..., canary_sample_ids: list[str] | None = None):
    # 确保 canary 样本始终包含在测试集中
    canary = canary_sample_ids or []
    sample_ids = (source + canary + correct + wrong)[:max_samples]
```

**patch_tester.py 改动**：
```python
def summarize_patch_test(round_id, patch_id, suite_id, base_evals, patched_evals,
                         canary_sample_ids: list[str] | None = None):
    # ... 现有逻辑 ...
    # 新增：canary 检查
    canary_ids = set(canary_sample_ids or [])
    for patched in patched_evals:
        if patched.sample_id in canary_ids and patched.overall_status != "correct":
            result.canary_broken_count += 1
    # canary 被破坏 → 直接拒绝
    if result.canary_broken_count > 0:
        result.accepted = False
        result.rejection_reason = "CANARY_BROKEN"
```

**round_runner.py 改动**：
- 从 `sample_states` 中选择 canary 样本（`consecutive_correct_count >= N` 的样本）
- 传递给 suite_builder 和 summarize_patch_test

### 改动 3：历史回归检测

**文件**：
- `mmap_optimizer/testing/patch_tester.py` — 填充 `historical_fixed_regression_count`
- `mmap_optimizer/orchestration/round_runner.py` — 传递历史修复信息

**patch_tester.py 改动**：
```python
def summarize_patch_test(round_id, patch_id, suite_id, base_evals, patched_evals,
                         historically_fixed_sample_ids: list[str] | None = None):
    # ... 现有逻辑 ...
    # 新增：历史回归检测
    hist_fixed = set(historically_fixed_sample_ids or [])
    for patched in patched_evals:
        if patched.sample_id in hist_fixed and patched.overall_status != "correct":
            result.historical_fixed_regression_count += 1
```

**round_runner.py 改动**：
- 从 `sample_states` 中收集历史修复样本（`consecutive_correct_count > 0` 的样本）
- 传递给 `summarize_patch_test()`

### 改动 4：配置项

**文件**：`mmap_optimizer/core/config.py`

新增配置项：
```python
# Post-apply 回归验证
post_apply_regression_enabled: bool = True
post_apply_regression_sample_ratio: float = 0.3  # 采样比例，1.0 = 全量

# Canary 样本保护
canary_protection_enabled: bool = True
canary_min_consecutive_correct: int = 3  # 连续正确 N 次才能成为 canary
canary_max_count: int = 10  # 最大 canary 样本数

# 历史回归检测
historical_regression_check_enabled: bool = True
```

## 实施优先级

| 优先级 | 改动 | 价值 | 复杂度 |
|--------|------|------|--------|
| P0 | Post-apply 回归验证 | 高 - 防止 patch 应用后全量回归 | 中 |
| P1 | Canary 样本保护 | 高 - 防止 patch 破坏稳定样本 | 低 |
| P2 | 历史回归检测 | 中 - 跨 round 回归检测 | 低 |

## 验证步骤

1. 单元测试：为 `summarize_patch_test()` 新增 canary 和 historical regression 参数编写测试
2. 集成测试：为 `_post_apply_regression_check()` 编写测试
3. 端到端验证：运行优化器，确认 canary 样本被正确选择和保护
4. 回归测试：确认现有测试不受影响

## 假设与决策

- **Post-apply 回归采样**：全量回归测试成本高，默认采样 30% 样本，可配置
- **Canary 样本来源**：从 `sample_states` 中选择连续正确次数最高的样本
- **历史修复定义**：`consecutive_correct_count > 0` 的样本视为历史修复样本
- **回滚策略**：Post-apply 回归检测到回归时，回滚到应用前的 prompt，但不回滚 `sample_states`
- **向后兼容**：新增参数均有默认值，不影响现有调用方
