# Extraction Prompt Patch 7 步流程 + 分析 Prompt 影子优化 — 设计文档（v4.0）

> 版本: v4.0（新增迭代结构 + 指标追踪设计）  
> 状态: Draft — 等待用户确认  
> 作用域: mmap_optimizer 项目 extraction + analysis prompt 双轮优化

---

## 0. 核心概念澄清（v4.0 新增）

### 0.1 迭代结构：一次迭代 = 抽取优化 + 分析优化

```
一次完整迭代 = 抽取 prompt 优化（step X.1）+ 分析 prompt 优化（step X.2）
```

- **迭代计数由抽取 prompt 优化决定**：只有抽取 prompt 优化成功（接受了 patch 或 patch 集为空但判定放弃）才计入一次迭代
- **分析 prompt 优化是影子优化**：跟随抽取 prompt 优化运行，不计入迭代次数，不消耗重试预算
- **抽取 prompt 优化回滚**：不计入迭代次数，重新执行抽取 prompt 优化（消耗重试预算）
- **分析 prompt 优化回滚**：不计入迭代次数，不消耗重试预算，不重试本次分析，直接进入下一次抽取 prompt 优化迭代

### 0.2 迭代计数器行为

```
max_restart_attempts: 3  # 抽取 prompt 优化的最大重试次数

迭代 1：
  1.1 抽取 prompt 优化 → 成功（接受 patch）→ 迭代计数 +1
  1.2 分析 prompt 优化 → 成功（接受 patch）
  → 进入迭代 2

迭代 1：
  1.1 抽取 prompt 优化 → 回滚（空集）→ 不计入迭代，消耗 retry #1
  1.1 抽取 prompt 优化 → 回滚（空集）→ 不计入迭代，消耗 retry #2
  1.1 抽取 prompt 优化 → 成功（接受 patch）→ 迭代计数 +1
  1.2 分析 prompt 优化 → 回滚（空集）→ 不计入迭代，不消耗 retry
  → 进入迭代 2

迭代 1：
  1.1 抽取 prompt 优化 → 回滚（空集）→ 消耗 retry #1
  1.1 抽取 prompt 优化 → 回滚（空集）→ 消耗 retry #2
  1.1 抽取 prompt 优化 → 回滚（空集）→ 消耗 retry #3 → 达到最大重试
  → 本轮彻底放弃 patch 应用，prompt 保持初始状态，进入下一轮（round_index + 1）
  → 注：分析 prompt 优化直接跳过
```

---

## 1. 总体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 迭代 1（第 1 次迭代）                                                   │
│   1.1 抽取 prompt 优化（7 步流程 + 盲评分析）                           │
│   1.2 分析 prompt 优化（影子跟随，7 步流程）                           │
│       不计入迭代次数                                                    │
│       若回滚：不重试，直接进入迭代 2                                    │
│                                                                         │
│ 迭代 2（第 2 次迭代）                                                   │
│   2.1 抽取 prompt 优化                                                 │
│   2.2 分析 prompt 优化                                                 │
│                                                                         │
│ ...                                                                     │
│ 迭代 N                                                                  │
│   当 accepted_iteration_count >= max_text_rounds 时停止                  │
└─────────────────────────────────────────────────────────────────────────┘
```

**关键**：迭代计数 = `accepted_iteration_count`，由抽取 prompt 优化的接受状态决定。

---

## 2. 指标追踪数据结构（v4.0 新增）

### 2.1 IterationMetrics（单次迭代的指标记录）

```python
@dataclass
class IterationMetrics:
    iteration_index: int                        # 全局迭代编号（跨轮次递增）
    round_index: int                           # 第几轮
    local_iteration_index: int                 # 本轮内第几次迭代

    # 抽取 prompt 优化指标（step X.1）
    extraction_base_accuracy: float            # 应用 patch 前的抽取准确率
    extraction_base_correct_count: int
    extraction_base_total_count: int
    extraction_patched_accuracy: float | None  # 应用 patch 后的抽取准确率（若接受）
    extraction_patched_correct_count: int | None
    extraction_patched_total_count: int | None
    extraction_accepted: bool                 # patch 是否被接受
    extraction_patch_count: int               # 接受的 patch 数量

    # 分析 prompt 优化指标（step X.2）
    analysis_base_accuracy: float | None      # 应用 patch 前的盲评准确率
    analysis_base_correct_count: int | None
    analysis_base_total_count: int | None
    analysis_patched_accuracy: float | None   # 应用 patch 后的盲评准确率（若接受）
    analysis_patched_correct_count: int | None
    analysis_patched_total_count: int | None
    analysis_accepted: bool                  # analysis patch 是否被接受
    analysis_patch_count: int = 0            # 接受的 analysis patch 数量

    timestamp: str                            # ISO 时间戳
    duration_seconds: float                   # 本次迭代耗时
```

### 2.2 AttemptRecord（记录每次回滚）

```python
@dataclass
class AttemptRecord:
    attempt_number: int           # 本轮内第几次尝试（跨抽取重试计数）
    round_index: int
    source: str                  # "extraction" 或 "analysis"
    extraction_base_accuracy: float | None
    analysis_base_accuracy: float | None
    reason: str                  # "empty_patch_set" / "post_apply_regression" / ...
    timestamp: str
```

### 2.3 RoundMetricsTracker（追踪一轮内所有迭代和失败）

```python
@dataclass
class RoundMetricsTracker:
    round_index: int
    iteration_metrics: list[IterationMetrics] = field(default_factory=list)
    failed_attempts: list[AttemptRecord] = field(default_factory=list)
    global_iteration_counter: int = 0   # 全局迭代计数器（跨轮次递增）

    def record_iteration(self, metrics: IterationMetrics):
        self.global_iteration_counter += 1
        metrics.iteration_index = self.global_iteration_counter
        metrics.local_iteration_index = len(self.iteration_metrics) + 1
        self.iteration_metrics.append(metrics)

    def record_failed_attempt(self, attempt: AttemptRecord):
        self.failed_attempts.append(attempt)

    @property
    def accepted_iteration_count(self) -> int:
        return len([m for m in self.iteration_metrics if m.extraction_accepted])
```

---

## 3. 第一轮：Extraction Prompt 优化 — 7 步流程

### 3.1 Step 1: Baseline Extraction（保留现有实现）

对 optimization_batch 样本跑当前 extraction prompt → base_evals

### 3.2 Step 2: Accuracy Statistics（保留现有实现）

```python
wrong_evals = [e for e in base_evals if e.overall_status != "correct"]
correct_evals = [e for e in base_evals if e.overall_status == "correct"]
```

### 3.3 Step 3: Blind Evaluation + Reflection（🆕 核心新增）

#### Step 3a: 盲评分析 — 不看真值

对每个 wrong_eval 中的样本，用当前 analysis_prompt 进行分析（不给模型看 ground truth），输出盲评判断。

#### Step 3b: 对比盲评 vs 真值

```python
# 有真值: 直接对比
# 无真值: 进行 3 次独立分析，投票结果作为真值代理
matches_truth = (blind_judgement == ground_truth_or_voted_truth)
```

#### Step 3c: 确定哪些样本用于 patch 生成

```python
# 盲评与真值一致的 wrong 样本 → 用于 patch 生成
samples_for_patch_generation = [sid for sid, r in blind_records.items()
    if r.matches_truth and r.overall_status != "correct"]
# 盲评与真值不同的 wrong 样本 → 不用于 patch 生成
samples_excluded = [sid for sid, r in blind_records.items()
    if not r.matches_truth and r.overall_status != "correct"]
```

#### Step 3d: 盲评反思 — 对"盲评错而抽取对"的样本进行反思

对 `盲评错 but 抽取对` 的样本，调用模型反思：盲评为什么错、应该检查什么、如何改进。**反思结果保存**，供第二轮分析 prompt 优化使用。

### 3.4 Step 4: Patch Generation（🆕 仅用盲评与真值一致的样本）

```python
# 仅对 samples_for_patch_generation 中的样本生成 patch
filtered_error_evals = [e for e in wrong_evals if e.sample_id in samples_for_patch_generation]
analysis_result = AnalysisRunner.analyze_errors(error_evaluations=filtered_error_evals, ...)
```

### 3.5 Step 5: Patch Merge（保留现有）

TreeReducePatchMerger.merge(candidate_patches) → merged_patches

### 3.6 Step 6: Merged Re-test（🆕 整体应用后重新测试）

```python
# 整体应用所有 merged_patches
temp_prompt = initial_extraction_prompt
for patch in merged_patches:
    temp_prompt = PatchApplier().apply(temp_prompt, patch, ...)

# 用新 prompt 对 optimization_batch 重新跑 extraction
patched_result = _prompt_runner().run(prompt=temp_prompt, samples=optimization_batch, ...)
patched_evals = patched_result.evaluations
```

### 3.7 Step 7: Comparison & Filtering（🆕 两次结果对比）

```
Step 7.1: 样本分类 — 之前对依然对 / 之前错依然错 / 之前错现在对 / 之前对现在错
Step 7.2: 剔除 INEFFECTIVE — patch 来源样本全部"之前错依然错"
Step 7.3: 收集测毒集 — "之前对现在错"的样本
Step 7.4: 逐个 patch 在测毒集上测毒 — 有 broken → 剔除 TOXIC
Step 7.5: final_patches = merged_patches - INEFFECTIVE - TOXIC
```

### 3.8 Step 8: Final Merge & Apply / Rollback（🆕 最终合并应用或回滚）

```
if final_patches 非空:
    再次 tree_reduce merge → 应用到 state.active_extraction_prompt
    → extraction_accepted = True，迭代计数 +1，进入 step X.2
else:
    回滚 extraction prompt → 不计入迭代，消耗 retry 预算
    → 不进入 step X.2，进入下一次抽取 prompt 优化重试
```

---

## 4. 第二轮：Analysis Prompt 优化（影子优化，相同 7 步流程）

仅在 extraction_accepted=True 时执行。**不计入迭代次数，不消耗重试预算**。

### 4.1 测试集

第一轮中"盲评与真值不同"的样本（分析 prompt 对这些样本判断错误）+ canary 样本

### 4.2 评估方式

分析准确率（分析判断 vs 真值）。**使用第一轮 Step 3d 的盲评反思结果**作为 patch 生成依据。

### 4.3 7 步流程（与抽取优化相同）

Step 1: Baseline Analysis → Step 2: Accuracy Statistics → Step 3: Patch Generation（用盲评反思）→ Step 4: Merge → Step 5: Re-test → Step 6: Comparison & Filtering → Step 7: Final Merge & Apply / Rollback

### 4.4 分析优化回滚行为

- 回滚: state.active_analysis_prompt = initial_analysis_prompt，**不重试本次分析**
- 直接进入下一次抽取 prompt 优化迭代（iteration_index + 1 的 step X.1）

---

## 5. 完整主流程（v4.0）

```
Round Runner 主流程

初始化:
  accepted_iteration_count = 0
  extraction_retry_count = 0
  initial_extraction_prompt = deepcopy(state.active_extraction_prompt)
  initial_analysis_prompt = deepcopy(state.active_analysis_prompt)
  metrics_tracker = RoundMetricsTracker(round_index)
  metrics_tracker.global_iteration_counter = global_iteration_counter

for iteration_index in 1..∞:

  ┌───────────────────── Step X.1: 抽取 prompt 优化 ──────────────────┐
  │  result = run_extraction_optimization(Step 1-8)                   │
  │                                                                │
  │  if result.accepted:                                          │
  │      metrics_tracker.record_iteration(                          │
  │          extraction_base_accuracy=...,                         │
  │          extraction_patched_accuracy=...,                       │
  │          extraction_accepted=True,                             │
  │      )                                                        │
  │      → 进入 Step X.2                                          │
  │                                                                │
  │  else (回滚):                                                 │
  │      extraction_retry_count += 1                                │
  │      metrics_tracker.record_failed_attempt(                      │
  │          source="extraction", reason=...,                       │
  │      )                                                        │
  │      if extraction_retry_count >= max_restart_attempts:          │
  │          → break_round()                                      │
  │      → continue（重试抽取 prompt 优化）                        │
  └────────────────────────────────────────────────────────────────┘

  ┌───────────────────── Step X.2: 分析 prompt 优化 ──────────────────┐
  │  仅在 extraction_accepted=True 时执行                           │
  │  result = run_analysis_optimization(...)                         │
  │  记录 analysis_base_accuracy / analysis_patched_accuracy          │
  │  记录 analysis_accepted=True/False（均不计入迭代，不消耗 retry） │
  │  if 回滚: → 直接进入下一次循环，不重试                          │
  └────────────────────────────────────────────────────────────────┘

  if accepted_iteration_count >= max_text_rounds:
      break

轮次结束:
  保存 metrics_tracker → store
  MetricsPlotter.plot_round_metrics(metrics_tracker)
  MetricsPlotter.plot_cumulative_metrics(all_rounds)
```

---

## 6. 指标追踪与绘图设计（v4.0 新增）

### 6.1 两组准确率指标

| 指标类型 | 来源 | 记录时机 |
|---------|------|---------|
| 抽取 base 准确率 | Step 1 | 每次迭代/重试都记录 |
| 抽取 patched 准确率 | Step 6 | 仅 extraction_accepted=True 时 |
| 分析 base 准确率 | Step X.2 Step 1 | 仅 extraction_accepted=True 时 |
| 分析 patched 准确率 | Step X.2 Step 5 | 仅 analysis_accepted=True 时 |

### 6.2 绘图规范

**图 1: 抽取准确率变化**

```
准确率
  ↑
1.0├                              ●───●
   │                           ●
0.8├                        ●
   │                     ●
0.6├                  ●
   │               ● ✕        ●───●
0.4├            ●         ✕        ●───●
   │         ●
0.2├      ●
   │
0.0└────┴────┴────┴────┴────┴────┴────┴────→ 迭代次数
     1    2    3    4    5    6    7    8

● = extraction base/patched 准确率（折线图，extraction_accepted=True）
✕ = extraction 回滚（散点图红色叉，标记 base 准确率，无 patched 准确率）
```

**图 2: 分析盲评准确率变化**

```
准确率
  ↑
1.0├                              ●───●
   │                           ●
0.8├                        ●
   │                     ●
0.6├                  ●
   │               ● ✕        ●───●
0.4├            ●         ✕        ●───●
   │         ●
0.2├      ●
   │
0.0└────┴────┴────┴────┴────┴────┴────┴────→ 迭代次数
     1    2    3    4    5    6    7    8

橙色线 = analysis base 准确率
深橙色线 = analysis patched 准确率（若接受）
红色叉 = analysis 回滚
```

### 6.3 绘图实现

```python
class MetricsPlotter:
    def plot_round_metrics(self, metrics_tracker: RoundMetricsTracker):
        accepted = metrics_tracker.get_final_metrics()
        failed = metrics_tracker.failed_attempts

        # 折线图: 接受的迭代
        if accepted:
            iteration_indices = [m.iteration_index for m in accepted]
            self.ax.plot(iteration_indices, base_acc, marker="o", color="blue",
                        label="Base Accuracy", linestyle="-")
            self.ax.plot(iteration_indices, patched_acc, marker="s", color="green",
                        label="Patched Accuracy", linestyle="-")

        # 散点图红色叉: 回滚的尝试
        for f in failed:
            self.ax.scatter([f.attempt_number], [f.extraction_base_accuracy],
                          marker="x", color="red", s=150, linewidths=3)
```

---

## 7. 新增 / 修改文件清单（v4.0）

| # | 文件 | 改动类型 | 说明 |
|---|------|----------|------|
| 1 | records.py | 扩展 | 新增 IterationMetrics, AttemptRecord, RoundMetricsTracker；新增 RoundStage 枚举 |
| 2 | config.py | 扩展 | 新增 blind_evaluation_enabled, max_restart_attempts, analysis_prompt_optimization_enabled 等 |
| 3 | round_runner.py | 大幅重构 | 主流程改为 while True 循环（iteration），extraction + analysis 双轮 |
| 4 | blind_evaluation.py（新建） | 新建 | BlindEvaluationRunner: 盲评分析、对比真值、盲评反思 |
| 5 | analysis_eval_runner.py（新建） | 新建 | 第二轮分析 prompt 测试 |
| 6 | suite_builder.py | 扩展 | 新增 build_toxic_suite, build_analysis_test_suite |
| 7 | metrics_plotter.py（新建） | 新建 | MetricsPlotter: 指标绘图 |
| 8 | analysis/runner.py | 扩展 | 新增 run_blind_analysis(), run_single_analysis(), generate_analysis_patch() |
| 9 | 数据模型（新建） | 新建 | BlindEvaluationRecord, BlindEvaluationReflectionRecord, AnalysisEvalRecord |
| 10 | tests | 新增 | 双轮优化端到端测试、指标追踪测试 |

---

## 8. 关键设计决策（v4.0）

| 决策 | 说明 | 理由 |
|------|------|------|
| 一次迭代 = extraction + analysis | 迭代编号由 extraction 决定，analysis 跟随 | extraction 是主优化目标 |
| analysis 优化不计入迭代次数 | accepted_iteration_count 只受 extraction 影响 | 避免 analysis 失败浪费迭代预算 |
| analysis 回滚不消耗重试预算 | extraction_retry_count 只由 extraction 消耗 | 重试预算专用于 extraction |
| 两组独立准确率指标 | 抽取准确率 + 分析盲评准确率分开追踪 | 两种优化目标不同 |
| 折线图 + 红色散点叉 | 接受用折线，回滚用红色散点叉 | 直观展示每轮接受/回滚状态 |
| 全局迭代计数器跨轮次 | iteration_index 在所有轮次中全局递增 | 便于跨轮次趋势分析 |

---

**文档结束。请审核确认 v4.0 设计：迭代结构（一次迭代=抽取+分析）、影子优化行为（不计入迭代，不消耗重试预算）、指标追踪与绘图规范。确认后按此方案实施代码改造。**
