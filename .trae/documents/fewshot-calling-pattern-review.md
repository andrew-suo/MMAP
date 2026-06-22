# Fewshot 调用模式审查与修复计划

## 概述

对当前 MMAP 代码库中 fewshot 模块的调用模式进行全面审查，发现了 **3 个严重问题** 和 **3 个次要问题**。

## 当前架构分析

### 调用链路

```
OptimizerLoop.run()
  └─ RoundRunner.run_round()          # 每轮执行
       ├─ [while循环] _run_extraction_optimization()  # Step 1: 文本patch优化
       ├─ _run_analysis_evolution()                   # Step 2: 分析prompt优化
       ├─ _run_compression_stage()                    # Step 3: 压缩
       ├─ _run_fewshot_stage()                        # Step 4: fewshot优化
       └─ compute_round_metrics()                     # Step 5: 指标计算
```

### Fewshot 触发条件

`round_runner.py:1584-1585`:
```python
fewshot_round_index = round_index - self.config.max_text_rounds
if self.config.fewshot_enabled and 0 < fewshot_round_index <= self.config.fewshot_max_rounds:
```

总轮数 = `max_text_rounds + fewshot_max_rounds`（`optimizer_loop.py:190-191`）
- 第 1..max_text_rounds 轮：文本优化轮，fewshot 跳过
- 第 max_text_rounds+1..max_text_rounds+fewshot_max_rounds 轮：fewshot 轮

## 发现的问题

### 问题 1（严重）：Fewshot 轮仍执行完整的 Extraction 优化循环

**位置**: `round_runner.py:184-362`

**问题**: `run_round` 的主循环 `while True` 在每一轮都执行 `_run_extraction_optimization()`，包括 fewshot 轮。循环退出条件是 `accepted_iteration_count >= self.config.max_text_rounds`，但在 fewshot 轮中 `accepted_iteration_count` 从 0 开始，这意味着：

- 如果 `max_text_rounds=10`，fewshot 轮会尝试最多 10 次 extraction 优化迭代
- 这与 fewshot 轮的设计意图矛盾——fewshot 轮应该只做 fewshot 优化
- extraction 优化可能改变 prompt，然后 fewshot 又在改变后的 prompt 上操作，产生不可预期的交互

**影响**: 浪费 LLM 调用、可能引入 prompt 漂移、fewshot 优化的基线不稳定

**修复方案**: 在 fewshot 轮中跳过 extraction 优化循环，仅执行 baseline 评估 + fewshot 优化

```python
# round_runner.py run_round() 中
is_fewshot_round = (
    self.config.fewshot_enabled
    and round_index > self.config.max_text_rounds
)
if is_fewshot_round:
    # Fewshot 轮：只跑 baseline 评估，不跑 extraction 优化循环
    extraction_result = self._run_baseline_extraction(...)
    extraction_evals = extraction_result.evaluations
else:
    # 文本优化轮：跑完整 extraction 优化循环
    while True:
        extraction_result = self._run_extraction_optimization(...)
        ...
```

### 问题 2（严重）：Bundle 测试与单候选测试完全冗余

**位置**: `engine.py:128-150`

**问题**: `optimize_once` 对每个候选执行两次测试：
1. 单候选测试（`FEW_SHOT_TEST`）：用候选 prompt 跑 `behavior_samples`
2. Bundle 测试（`few_shot_bundle_test`）：用**同一个**候选 prompt 跑**同一批** `behavior_samples`

两次测试的 prompt 完全相同（都是 `candidate_prompt`，包含所有已有 slot + 新候选），样本完全相同（都是 `behavior_samples`）。唯一区别是 `run_type` 字符串不同。

对于确定性 MockModelClient，两次测试结果完全相同——纯浪费。
对于非确定性 LLM，这相当于一次"确认运行"，但同样的效果可以通过 `vote_rounds` 实现。

**影响**: 每个候选多花一倍 LLM 调用费用，且不提供额外信息

**修复方案**: 移除 bundle 测试，直接使用单候选测试结果做接受决策

```python
# 移除 bundle_result 相关代码（engine.py:140-150）
# 直接使用单候选测试结果：
if broken or schema_violations or delta < min_accuracy_delta:
    candidate.rejection_reason = "FEWSHOT_REGRESSION_OR_INSUFFICIENT_GAIN"
    ...
    continue

# 直接接受
candidate_report = replace(report)
candidate_report.accepted = True
...
```

### 问题 3（严重）：Checkpoint 不持久化 fewshot 候选池路径

**位置**: `optimizer_loop.py:96`

**问题**: `_save_checkpoint` 调用时 `fewshot_pool_path=None`，导致 checkpoint 中的 `fewshot_pool_path` 字段始终为 None。虽然候选池通过独立文件 `fewshot_candidate_pool.json` 持久化，但：
- checkpoint 的 `fewshot_pool_path` 字段存在却永远不填值，是死代码
- `_restore_state_from_checkpoint` 不恢复候选池状态
- 如果未来候选池路径变为可配置，resume 会断裂

**影响**: checkpoint 机制不完整，resume 时 fewshot 状态可能丢失

**修复方案**: 在 `_save_checkpoint` 中传入实际路径，并在 `_restore_state_from_checkpoint` 中恢复

```python
# optimizer_loop.py
def _save_checkpoint(self, round_index, state, metrics, *, fewshot_pool_path=None):
    ...
# 调用处：
fewshot_pool_path = str(self.store.root / "fewshot_candidate_pool.json")
self._save_checkpoint(round_index, state, metrics, fewshot_pool_path=fewshot_pool_path)
```

### 问题 4（次要）：configs/fewshot.yaml 有未解析的配置字段

**位置**: `configs/fewshot.yaml` vs `core/config.py:336-339`

**问题**: YAML 中定义了 `trigger`、`candidates_per_round`、`acceptance.*` 字段，但 config.py 只解析 `enabled`、`max_rounds`、`max_slots`、`min_accuracy_delta`。其余字段被静默忽略。

**影响**: 用户可能以为这些配置生效了，实际没有

**修复方案**: 要么解析这些字段，要么从 YAML 中移除未使用的字段

### 问题 5（次要）：每轮只接受 1 个 fewshot 候选

**位置**: `engine.py:176-187`

**问题**: `optimize_once` 遍历所有候选但只接受 `bundle_delta` 最大的一个。填满 `max_slots=5` 至少需要 5 轮。如果 `fewshot_max_rounds=5`，刚好够用，但效率低。

**影响**: fewshot 优化速度慢，需要多轮才能填满槽位

**修复方案**: 可改为贪心批量接受——遍历候选，每个通过测试的就接受，直到填满 max_slots。但这会改变语义，需要评估。

### 问题 6（次要）：`_replacement_slot` 总是替换最后一个槽位

**位置**: `engine.py:329-343`

**问题**: 替换策略固定选择 `slot_index` 最大的槽位，无法识别最低价值示例。代码注释已承认这是已知限制。

**影响**: 可能替换掉高价值示例，保留低价值示例

**修复方案**: 可通过 A/B 测试每个槽位的移除影响来选择，但成本高。当前策略可作为短期方案。

## 修复优先级

| 优先级 | 问题 | 修复难度 | 影响 |
|--------|------|----------|------|
| P0 | 问题 1: fewshot 轮仍跑 extraction 优化 | 中 | 节省 LLM 调用、避免 prompt 漂移 |
| P0 | 问题 2: bundle 测试冗余 | 低 | 节省 50% fewshot LLM 调用 |
| P1 | 问题 3: checkpoint 不保存 pool 路径 | 低 | resume 完整性 |
| P2 | 问题 4: YAML 未解析字段 | 低 | 配置一致性 |
| P2 | 问题 5: 每轮只接受 1 候选 | 中 | 优化效率 |
| P3 | 问题 6: 替换策略粗糙 | 高 | 优化质量 |

## 建议修复范围

本次修复聚焦 **P0 + P1**（问题 1、2、3），这三项是明确的正确性/效率问题，修复方案清晰。

### 具体改动

#### 1. 修复问题 1：fewshot 轮跳过 extraction 优化

**文件**: `mmap_optimizer/orchestration/round_runner.py`

在 `run_round` 的主循环前增加判断：如果是 fewshot 轮，跳过 extraction 优化循环，只跑一次 baseline 评估获取 `extraction_evals`。

需要提取一个 `_run_baseline_only_extraction()` 方法，或者复用 `_run_extraction_optimization` 的 baseline 部分。

#### 2. 修复问题 2：移除冗余 bundle 测试

**文件**: `mmap_optimizer/fewshot/engine.py`

移除 `optimize_once` 中 `bundle_result` 相关代码（第 140-150 行），直接使用单候选测试结果做接受决策。同时更新 `mark_tested` 调用使用 `delta` 而非 `bundle_delta`。

#### 3. 修复问题 3：checkpoint 持久化 pool 路径

**文件**: `mmap_optimizer/orchestration/optimizer_loop.py`

修改 `_save_checkpoint` 调用，传入实际路径。

## 验证步骤

1. 运行现有 fewshot 测试：`python -m pytest tests/test_patch_and_round.py -k fewshot -v`
2. 运行 prompt_test_runner fewshot 测试：`python -m pytest tests/test_prompt_test_runner_fewshot_assets.py -v`
3. 运行全量测试：`python -m pytest tests/ -v`
4. 验证 fewshot 轮不再触发 extraction 优化（通过日志或 mock 计数）
5. 验证 bundle 测试移除后接受决策仍正确
6. 验证 checkpoint 中 `fewshot_pool_path` 有值

## 假设与决策

- 假设 fewshot 轮的 baseline 评估仍需要执行（用于提供 `base_evaluations` 给 fewshot engine）
- 假设移除 bundle 测试不会降低接受质量（因为单候选测试已经包含所有 slot）
- 假设 `fewshot_candidate_pool.json` 路径固定不变（当前代码已硬编码）
