# Correctness Audit Guide

本项目的 correctness 审计重点不是“某次 patch 聪不聪明”，而是：

1. 状态真相如何产生
2. 状态真相如何落盘
3. 下一轮优化如何消费这些状态

对闭环优化系统来说，最危险的错误是“错误状态被系统继续当真相消费”。

## 状态字段分层

### Source of Truth

这些字段直接驱动后续采样或阶段行为，必须有明确 writer：

| 字段 | writer |
| --- | --- |
| `error_count` | `EvaluationExecutor`，或 extraction stage 的 fallback；few-shot base metrics |
| `error_ema` | `EvaluationExecutor`，或 extraction stage 的 fallback；few-shot base metrics |
| `difficulty_score` | `EvaluationExecutor`，或 extraction stage 的 fallback；few-shot base metrics |
| `last_extraction_status` | extraction evaluation、few-shot base metrics、最终 accepted extraction outcome |
| `last_analysis_status` | analysis execution、最终 accepted analysis outcome |

### Derived Summary

这些字段是长期摘要，只应基于最终 accepted 结果更新：

| 字段 | 约束 |
| --- | --- |
| `historical_fixed_count` | 只统计最终 accepted 结果中的 fail -> pass |
| `historical_broken_count` | 只统计最终 accepted 结果中的 pass -> fail |
| `SampleTrace.*_transition` | 表示本轮最终 accepted 结果，不表示 trial 结果 |
| `SampleOutcomeHistoryItem.transition` | 从最终 accepted 结果派生 |
| `SampleOutcomeHistoryItem.patch_decision` | patch 处理结果摘要，不是唯一失败原因 |

### Display / Memory

这些字段主要用于模型提示、轨迹渲染和 patch 经验记忆：

| 字段 | 说明 |
| --- | --- |
| `optimization_trajectory` | 按 `prompt_type` 分层的过程轨迹 |
| `patch_attempts` | source-centric patch 生命周期，不是完整因果链 |
| `outcome_history` | 供采样器消费的最近轮次摘要 |
| `related_analysis` | renderer 层补充上下文，不是主状态字段 |

## 审计检查点

### 1. Writer Ownership

检查每个 source-of-truth 字段是否存在：

- executor 与 stage 双写
- stage 快照猜写
- mock / real 路径写入语义不一致

### 2. Final vs Trial

检查以下字段是否只来自最终 accepted 结果：

- `historical_fixed_count`
- `historical_broken_count`
- `transition`
- `outcome_history`

toxic / ineffective / apply-no-change / dropped patch 应进入 patch attempt 或 report，
不应污染长期状态。

### 3. Downstream Consumers

对每个被消费字段标记角色：

- source of truth
- derived summary
- display-only

如果 display-only 字段被下游决策逻辑使用，应视为高风险。

### 4. Mock / Real Alignment

确认 smoke/mock 路径与真实路径在以下层面一致：

- `SampleState`
- `SampleTrace`
- `SampleOptimizationTrajectory`

允许内容不同，但不应出现状态层级不同。

### 5. Renderer Boundary

`SampleTrajectoryRenderer` 可以拼接 `related_analysis` 这类轻量上下文，
但这属于 prompt 辅助信息，不应反向成为主状态来源。
