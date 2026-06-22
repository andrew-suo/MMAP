# 重构 MMAP 顶层流程为 Prompt / Few-shot 双阶段 Spec

## Why

当前 `RoundRunner.run_round` 通过隐式 round index 判断当前是 prompt round 还是 fewshot round（`round_index > max_text_rounds`），导致：

- 阶段边界模糊，单文件混合了两种本质不同的优化逻辑（文本 patch 闭环 vs few-shot 候选选择闭环）。
- 配置项散落在 `text_optimization` / `fewshot` / `analysis_prompt_optimization` 等多个段，无法显式表达"两个独立阶段"的执行计划。
- fewshot 轮仍会进入 extraction 优化主循环（已有 `baseline_only` 兜底，但属于补丁式修复，非阶段隔离）。
- 难以扩展交替优化、难以单独观测每个阶段的产物。

重构目标：将顶层优化入口拆分为 **Prompt Optimization Phase** 和 **Few-shot Optimization Phase** 两个独立阶段，由配置文件显式控制，运行时生成显式 `RunPlan`，每个阶段只修改自己负责的对象。

## What Changes

- **NEW** 引入 `RunPlan` 数据结构与 `RunPlanBuilder`，根据配置生成显式的有序 round 列表（`prompt_round_001`、`fewshot_round_001`...），取代 `OptimizerLoop._default_round_count` 中 `max_text_rounds + fewshot_max_rounds` 的隐式拼接。
- **NEW** 新增配置段 `prompt_optimization` 与 `fewshot_optimization`，各自包含 `enabled` / `rounds` / `batch_size` / `acceptance_strategy` / `output_dir` 字段。
- **NEW** 拆分 `RoundRunner` 为两个职责单一的 runner：
  - `PromptOptimizationRunner`：执行 `Baseline → Error Analysis → Patch Generation → Patch Validation → Greedy Patch Acceptance → Final Verification → Prompt Promotion` 闭环，**只修改 `active_extraction_prompt` / `active_analysis_prompt` 文本**，不触碰 few-shot examples。
  - `FewShotOptimizationRunner`：执行 `Baseline → Candidate Example Selection → Example Trial → Evaluation → Acceptance Decision → Few-shot Set Promotion` 闭环，**只修改 few-shot examples**，不修改 prompt 文本。
- **NEW** 引入 `PhaseResult` 数据结构，每个阶段独立保存：新版本 id、accepted/rejected 列表、trial records、before/after evaluation results。
- **MODIFIED** `OptimizerLoop.run` 改为消费 `RunPlan`，按 round 类型分派给对应 runner，不再在 `RoundRunner` 内部通过 `is_fewshot_round` 判断。
- **MODIFIED** `OptimizerConfig` 新增 `prompt_optimization` / `fewshot_optimization` 子配置；保留旧字段（`max_text_rounds` / `fewshot_max_rounds` / `fewshot_enabled`）作为向后兼容回退，但优先读取新配置段。
- **MODIFIED** `optimizer_config_from_mapping` 解析新的 `prompt_optimization` / `fewshot_optimization` 段。
- **REMOVED** `RoundRunner.run_round` 中 `is_fewshot_round` 分支与 `baseline_only` 参数（其职责被 `FewShotOptimizationRunner` 取代）。**BREAKING**：`RoundRunner` 不再是单一入口，外部调用方需改用 `OptimizerLoop` 或具体 phase runner。
- **REMOVED** `OptimizerLoop._default_round_count` 中的 `max_text_rounds + fewshot_max_rounds` 隐式拼接逻辑，改为 `RunPlanBuilder.build(config)` 生成。

### 设计约束

1. Prompt Optimization 阶段只修改文本 prompt（extraction / analysis prompt 的 IR 与文本内容）。
2. Few-shot Optimization 阶段只修改 few-shot examples（`few_shot_examples` section 的 slot 内容），不修改 prompt 其他文本。
3. 两个阶段共享 evaluator、sample set、model client 和 storage（`JsonStore`）。
4. 两个阶段分别保存自己的 round result（`prompt_rounds/` 与 `fewshot_rounds/` 子目录）。
5. 默认执行顺序：先 Prompt Optimization，再 Few-shot Optimization。
6. 第一版不支持交替优化，但 `RunPlan` 数据结构预留 `alternate` 模式扩展点。

## Impact

- Affected specs: 顶层优化流程、配置 schema、round 产物布局。
- Affected code:
  - [mmap_optimizer/orchestration/optimizer_loop.py](file:///workspace/mmap_optimizer/orchestration/optimizer_loop.py) — 改为消费 `RunPlan`，分派给两个 phase runner。
  - [mmap_optimizer/orchestration/round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) — 拆分为 `PromptOptimizationRunner` + `FewShotOptimizationRunner`，移除 `is_fewshot_round` 分支。
  - [mmap_optimizer/core/config.py](file:///workspace/mmap_optimizer/core/config.py) — 新增 `prompt_optimization` / `fewshot_optimization` 子配置与解析。
  - [mmap_optimizer/orchestration/records.py](file:///workspace/mmap_optimizer/orchestration/records.py) — 新增 `RunPlan` / `RunPlanItem` / `PhaseResult` 数据结构。
  - [mmap_optimizer/cli/main.py](file:///workspace/mmap_optimizer/cli/main.py) — `run` / `run_smoke` 适配新配置与 `RunPlan`。
  - [configs/optimizer.yaml](file:///workspace/configs/optimizer.yaml) 与 [scenarios/default/optimizer.yaml](file:///workspace/scenarios/default/optimizer.yaml) — 增加新配置段示例。
  - 现有测试 [tests/test_integrated_readiness_flow.py](file:///workspace/tests/test_integrated_readiness_flow.py)、[tests/test_checkpoint_resume.py](file:///workspace/tests/test_checkpoint_resume.py) 等需适配新入口。

## ADDED Requirements

### Requirement: RunPlan 显式编排

系统 SHALL 在 `OptimizerLoop.run` 启动时根据配置生成显式的 `RunPlan`，包含有序的 `RunPlanItem` 列表，每个 item 标注 `round_id`、`phase`（`prompt` / `fewshot`）、`round_index_within_phase`。

#### Scenario: 两阶段均启用

- **WHEN** 配置 `prompt_optimization.enabled=true, rounds=3` 且 `fewshot_optimization.enabled=true, rounds=2`
- **THEN** `RunPlan` 包含 5 个 item，顺序为 `prompt_round_001` → `prompt_round_002` → `prompt_round_003` → `fewshot_round_001` → `fewshot_round_002`

#### Scenario: 仅启用一阶段

- **WHEN** 配置 `prompt_optimization.enabled=true, rounds=3` 且 `fewshot_optimization.enabled=false`
- **THEN** `RunPlan` 仅包含 3 个 prompt round item

#### Scenario: 阶段禁用时不生成对应 round

- **WHEN** `prompt_optimization.enabled=false`
- **THEN** `RunPlan` 不包含任何 prompt round item，即使 `rounds > 0`

### Requirement: PromptOptimizationRunner 阶段隔离

系统 SHALL 提供 `PromptOptimizationRunner`，在每个 prompt round 内执行完整的 patch 闭环，且 **只** 修改 `active_extraction_prompt` / `active_analysis_prompt`。

#### Scenario: 接受 patch 后提升 prompt 版本

- **WHEN** prompt round 中生成的 patch 通过 greedy safe-subset 验证
- **THEN** `state.active_extraction_prompt` 被更新为新版本，few-shot examples section 内容保持不变

#### Scenario: 拒绝 patch 后回滚

- **WHEN** prompt round 中所有 patch 被拒绝或回滚
- **THEN** `state.active_extraction_prompt` 保持 round 开始时的版本

#### Scenario: 不修改 few-shot examples

- **WHEN** PromptOptimizationRunner 执行完毕
- **THEN** `state.active_extraction_prompt` 中 `few_shot_examples` section 的 slot 列表与 round 开始时完全一致

### Requirement: FewShotOptimizationRunner 阶段隔离

系统 SHALL 提供 `FewShotOptimizationRunner`，在每个 few-shot round 内执行候选选择 / 试验 / 接受闭环，且 **只** 修改 few-shot examples section。

#### Scenario: 接受候选后提升 few-shot set 版本

- **WHEN** few-shot round 中候选 example 通过 accuracy delta 验证
- **THEN** `state.active_extraction_prompt` 的 `few_shot_examples` section 被更新，prompt 其他 section 文本保持不变

#### Scenario: 不修改 prompt 文本

- **WHEN** FewShotOptimizationRunner 执行完毕
- **THEN** `state.active_extraction_prompt` 中除 `few_shot_examples` 外的所有 section 文本与 round 开始时完全一致

### Requirement: 阶段产物独立持久化

系统 SHALL 为每个阶段独立保存 round result，目录布局为 `{run_dir}/prompt_rounds/{round_id}/...` 与 `{run_dir}/fewshot_rounds/{round_id}/...`。

#### Scenario: Prompt round 产物

- **WHEN** 一个 prompt round 完成
- **THEN** `{run_dir}/prompt_rounds/{round_id}/` 下包含 `round.json`、`prompts/`、`patches/`、`evaluations/`、`metrics/`

#### Scenario: Few-shot round 产物

- **WHEN** 一个 few-shot round 完成
- **THEN** `{run_dir}/fewshot_rounds/{round_id}/` 下包含 `round.json`、`fewshot/`、`evaluations/`、`metrics/`，**不**包含 `patches/` 目录

### Requirement: 配置驱动阶段开关

系统 SHALL 通过 `prompt_optimization` 与 `fewshot_optimization` 配置段控制各阶段的启用状态、轮数、batch size、接受策略与输出目录。

#### Scenario: 读取新配置段

- **WHEN** 配置文件包含 `prompt_optimization: {enabled: true, rounds: 3, batch_size: 99}`
- **THEN** `OptimizerConfig.prompt_optimization.enabled == True`、`rounds == 3`、`batch_size == 99`

#### Scenario: 向后兼容旧配置

- **WHEN** 配置文件未包含 `prompt_optimization` 段但包含 `text_optimization.max_rounds`
- **THEN** 系统回退使用 `max_text_rounds` 作为 prompt optimization rounds，`batch_size` 回退到顶层 `batch_size`

## MODIFIED Requirements

### Requirement: OptimizerLoop 顶层编排

`OptimizerLoop.run` SHALL 接收 `OptimizerState`，调用 `RunPlanBuilder.build(config)` 生成 `RunPlan`，按 plan 顺序分派给对应 phase runner，并在每个 round 后更新 `OptimizationRunSummary` 与 checkpoint。

`OptimizerLoop` 不再依赖 `RoundRunner` 单一实例，而是持有 `PromptOptimizationRunner` 与 `FewShotOptimizationRunner` 两个实例（共享 evaluator / store / model client / config）。

#### Scenario: RunPlan 驱动执行

- **WHEN** `OptimizerLoop.run` 被调用
- **THEN** 系统先生成 `RunPlan` 并持久化到 `{run_dir}/run_plan.json`，再按 plan 顺序执行每个 round

#### Scenario: 阶段间状态传递

- **WHEN** Prompt Optimization 阶段最后一个 round 完成
- **THEN** Few-shot Optimization 阶段的第一个 round 接收的 `state.active_extraction_prompt` 是 Prompt 阶段最终提升的版本

## REMOVED Requirements

### Requirement: RoundRunner 隐式 round 类型判断

**Reason**: `is_fewshot_round = round_index > max_text_rounds` 的隐式判断使阶段边界模糊，与显式 `RunPlan` 设计冲突。
**Migration**: 调用方改用 `OptimizerLoop` + `RunPlan`；需要单独运行某一轮的场景改用对应的 `PromptOptimizationRunner` 或 `FewShotOptimizationRunner`。
