# Tasks

- [ ] Task 1: 新增 RunPlan 数据结构与 RunPlanBuilder
  - [ ] SubTask 1.1: 在 `orchestration/records.py` 中新增 `RunPlanItem`（`round_id` / `phase` / `round_index_within_phase`）与 `RunPlan`（`items: list[RunPlanItem]`）dataclass
  - [ ] SubTask 1.2: 新增 `orchestration/run_plan.py`，实现 `RunPlanBuilder.build(config: OptimizerConfig) -> RunPlan`，根据 `prompt_optimization` / `fewshot_optimization` 配置生成有序 item 列表（先 prompt 后 fewshot）
  - [ ] SubTask 1.3: 为 `RunPlanBuilder` 编写单元测试，覆盖两阶段均启用、仅启用一阶段、均禁用三种场景

- [ ] Task 2: 扩展 OptimizerConfig 支持新配置段
  - [ ] SubTask 2.1: 在 `core/config.py` 新增 `PromptOptimizationConfig` 与 `FewShotOptimizationConfig` dataclass（字段：`enabled` / `rounds` / `batch_size` / `acceptance_strategy` / `output_dir`）
  - [ ] SubTask 2.2: 在 `OptimizerConfig` 中新增 `prompt_optimization` 与 `fewshot_optimization` 字段，默认值与旧字段（`max_text_rounds` / `fewshot_enabled` / `fewshot_max_rounds` / `batch_size`）保持一致以兼容
  - [ ] SubTask 2.3: 扩展 `optimizer_config_from_mapping` 解析新段；当新段缺失时回退到旧字段
  - [ ] SubTask 2.4: 扩展 `OptimizerConfig.validate` 校验新段字段范围
  - [ ] SubTask 2.5: 更新 `configs/optimizer.yaml` 与 `scenarios/default/optimizer.yaml` 增加新配置段示例（保留旧段以兼容）

- [ ] Task 3: 抽取 PromptOptimizationRunner
  - [ ] SubTask 3.1: 新建 `orchestration/prompt_optimization_runner.py`，将 `RoundRunner.run_round` 中 prompt round 相关逻辑（extraction optimization 主循环、analysis optimization、analysis evolution、compression）迁移过来
  - [ ] SubTask 3.2: 移除 `baseline_only` 参数与 `is_fewshot_round` 分支（这些逻辑属于 fewshot runner）
  - [ ] SubTask 3.3: runner 接收 `round_id`（如 `prompt_round_001`）与 `round_index_within_phase`，产物写入 `{run_dir}/prompt_rounds/{round_id}/`
  - [ ] SubTask 3.4: 确保 runner 不修改 `few_shot_examples` section（添加断言：round 结束时该 section slot 列表与开始时一致）

- [ ] Task 4: 抽取 FewShotOptimizationRunner
  - [ ] SubTask 4.1: 新建 `orchestration/fewshot_optimization_runner.py`，将 `RoundRunner._run_fewshot_stage` 与 fewshot round 的 baseline 评估逻辑迁移过来
  - [ ] SubTask 4.2: runner 执行 `Baseline → Candidate Selection → Trial → Evaluation → Acceptance → Promotion` 闭环，复用 `FewShotOptimizationEngine.optimize_once`
  - [ ] SubTask 4.3: runner 接收 `round_id`（如 `fewshot_round_001`）与 `round_index_within_phase`，产物写入 `{run_dir}/fewshot_rounds/{round_id}/`，不创建 `patches/` 目录
  - [ ] SubTask 4.4: 确保 runner 不修改 prompt 文本（添加断言：round 结束时除 `few_shot_examples` 外的 section 文本与开始时一致）

- [ ] Task 5: 重构 OptimizerLoop 消费 RunPlan
  - [ ] SubTask 5.1: `OptimizerLoop.__init__` 改为接收 `prompt_runner: PromptOptimizationRunner` 与 `fewshot_runner: FewShotOptimizationRunner`（替代单一 `runner: RoundRunner`）
  - [ ] SubTask 5.2: `OptimizerLoop.run` 调用 `RunPlanBuilder.build(config)` 生成 `RunPlan`，持久化到 `{run_dir}/run_plan.json`
  - [ ] SubTask 5.3: 按 `RunPlan.items` 顺序分派：`phase == "prompt"` 调用 `prompt_runner.run_round`，`phase == "fewshot"` 调用 `fewshot_runner.run_round`
  - [ ] SubTask 5.4: 移除 `_default_round_count` 中的 `max_text_rounds + fewshot_max_rounds` 隐式拼接，planned_rounds 改为 `len(run_plan.items)`
  - [ ] SubTask 5.5: checkpoint 结构扩展 `phase` 与 `round_id` 字段，支持按 RunPlan item 恢复

- [ ] Task 6: 适配 CLI 入口
  - [ ] SubTask 6.1: `cli/main.py` 的 `run` 与 `run_smoke` 改为构造 `PromptOptimizationRunner` + `FewShotOptimizationRunner` 并传入 `OptimizerLoop`
  - [ ] SubTask 6.2: 移除对 `RoundRunner` 的直接构造（保留 `RoundRunner` 类作为废弃别名一段时间以减少破坏，或直接删除并更新所有引用）
  - [ ] SubTask 6.3: `--rounds` CLI 参数语义改为"覆盖 RunPlan 总轮数"或废弃，改为完全由配置驱动（保留 `--rounds` 作为 prompt_optimization.rounds 的覆盖）

- [ ] Task 7: 适配与补充测试
  - [ ] SubTask 7.1: 更新 `tests/test_integrated_readiness_flow.py` 适配新入口
  - [ ] SubTask 7.2: 更新 `tests/test_checkpoint_resume.py` 适配 RunPlan-based checkpoint
  - [ ] SubTask 7.3: 新增 `tests/test_run_plan_builder.py` 覆盖 Task 1
  - [ ] SubTask 7.4: 新增 `tests/test_prompt_optimization_runner.py` 验证阶段隔离（不修改 few-shot section）
  - [ ] SubTask 7.5: 新增 `tests/test_fewshot_optimization_runner.py` 验证阶段隔离（不修改 prompt 文本）
  - [ ] SubTask 7.6: 运行全量测试套件确认无回归

# Task Dependencies

- Task 2 依赖 Task 1（RunPlanBuilder 需要 OptimizerConfig 新字段）
- Task 3、Task 4 依赖 Task 1、Task 2（runner 需要 RunPlan item 与新配置）
- Task 5 依赖 Task 3、Task 4（OptimizerLoop 分派给两个 runner）
- Task 6 依赖 Task 5（CLI 调用 OptimizerLoop）
- Task 7 依赖 Task 1-6 全部完成
- Task 3 与 Task 4 可并行开发（两者职责独立）
