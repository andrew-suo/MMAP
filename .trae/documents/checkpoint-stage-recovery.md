# 优化器中断恢复能力分析与增强方案

## 摘要

当前系统具备**Round 级别**的 checkpoint/resume 能力，但不具备**Stage 级别**（Round 内部阶段）的恢复能力。如果在 Round 执行中途崩溃，整个 Round 的所有中间结果会丢失，需要从头重跑。

## 当前状态分析

### 已有的恢复机制

| 机制 | 粒度 | 说明 |
|------|------|------|
| `OptimizerCheckpoint` | Round 级别 | 每轮完成后保存 `active_prompts`、`sample_states`、`metrics_summary` |
| `RunState` | Round 级别 | 记录 `iteration`、`stage`、`completed_round_ids` |
| `--resume` CLI 参数 | Round 级别 | 从 `checkpoint.json` 恢复，跳过已完成的 Round |
| `PromptSnapshot` / `--rollback-prompt` | 手动 | 恢复到某个历史 prompt 版本 |

### 恢复流程（当前）

```
optimizer_loop.run()
  ├── resume=True → _load_existing_checkpoint() → 读取 round_index
  ├── 从 round_index + 1 开始循环
  └── 每个 round 完成后 → _save_checkpoint()
```

### 关键缺陷：Round 内部无 checkpoint

`round_runner.run_round()` 是一个**长事务**，包含 15 个阶段（RoundStage 枚举）：

```
INIT → OPTIMIZATION_BATCH_SELECT → BASELINE_EVAL → DYNAMIC_VALIDATION
→ PATCH_GENERATION → PATCH_VALIDATION → PATCH_TREE_REDUCE → PATCH_EVAL
→ PATCH_RANKING → PATCH_APPLY → COMPRESSION → FEWSHOT
→ ANALYSIS_EVOLUTION → METRICS → COMPLETED
```

**问题**：如果在 `PATCH_EVAL` 阶段崩溃：
1. `extraction_runs`、`analysis_runs`、`draft_patches` 等中间结果**全部丢失**（仅在 Round 结束时才写入 jsonl）
2. `round_record.current_stage` 虽然可以记录当前阶段，但从未被用于恢复
3. 重启后从 Round 开头重跑，已完成的 LLM 调用（最耗时的部分）被重复执行

### 具体问题

1. **中间结果延迟写入**：所有 runs/evaluations/patches 只在 `run_round()` 末尾（第 431-451 行）才写入磁盘。如果中途崩溃，这些数据全部丢失。

2. **`current_stage` 未被使用**：`OptimizationRound.current_stage` 字段存在但从未被用于恢复逻辑。

3. **`OptimizerCheckpoint` 不保存 Round 内部状态**：只保存 `active_prompts` 和 `sample_states`，不保存当前 Round 的中间结果。

4. **`RunState.stage` 仅用于日志**：`run_state_store.save()` 保存了 stage 信息，但恢复时不读取。

## 修改方案

### 方案：Stage 级别增量 checkpoint

核心思路：在每个关键阶段完成后，将中间结果立即写入磁盘，并在 Round 开始时检查是否有未完成的 Round 可恢复。

#### 修改 1：`round_runner.py` — 阶段完成后立即持久化中间结果

在每个阶段完成后，将中间结果写入 `{round_id}/intermediate/` 目录：

```python
def _save_intermediate(self, round_id: str, stage: str, data: dict) -> None:
    """Save intermediate results after each stage for crash recovery."""
    self.store.write_json(f"{round_id}/intermediate/{stage}.json", data)
```

需要保存的关键阶段数据：

| 阶段 | 保存内容 |
|------|----------|
| `extraction_done` | `extraction_runs`, `evals`, `dval_runs`, `dval_evals` |
| `analysis_done` | `analysis_records`, `analysis_runs` |
| `patch_generation_done` | `draft_patches`, `candidate_patches`, `rejected_patches` |
| `patch_eval_done` | `patch_test_results`, `patch_test_runs`, `patch_test_evals` |
| `merge_done` | `merge_report` |
| `compression_done` | `compression_reports`, `compression_runs`, `compression_evals` |
| `fewshot_done` | `fewshot_reports`, `fewshot_runs`, `fewshot_evals` |

#### 修改 2：`round_runner.py` — Round 开始时检查可恢复的中间状态

在 `run_round()` 开始时，检查 `{round_id}/intermediate/` 目录是否存在，如果存在则加载已完成的阶段数据，跳过已执行的阶段：

```python
def _load_intermediate(self, round_id: str) -> dict[str, Any] | None:
    """Load intermediate results from a previously interrupted round."""
    intermediate_dir = self.store.root / round_id / "intermediate"
    if not intermediate_dir.exists():
        return None
    data = {}
    for stage_file in sorted(intermediate_dir.glob("*.json")):
        stage = stage_file.stem
        data[stage] = self.store.read_json(str(stage_file.relative_to(self.store.root)))
    return data if data else None
```

#### 修改 3：`round_runner.py` — 更新 `current_stage` 追踪

在每个阶段完成后更新 `round_record.current_stage` 并持久化：

```python
round_record.current_stage = RoundStage.PATCH_EVAL.value
self.store.write_json(f"{round_id}/round.json", round_record)
```

#### 修改 4：`optimizer_loop.py` — 恢复时重建 OptimizerState

当 `resume=True` 且检测到未完成的 Round 时，从中间结果重建 `OptimizerState`：

```python
def _try_resume_round(self, state: OptimizerState, round_index: int) -> dict[str, Any] | None:
    """Check if a round was interrupted and load its intermediate results."""
    round_id = f"round_{round_index:03d}"
    intermediate = self.runner._load_intermediate(round_id)
    return intermediate
```

#### 修改 5：Round 完成后清理中间文件

Round 正常完成后，删除 `intermediate/` 目录以节省空间：

```python
intermediate_dir = self.store.root / round_id / "intermediate"
if intermediate_dir.exists():
    import shutil
    shutil.rmtree(intermediate_dir)
```

### 实现策略

为避免一次性改动过大，分两步实施：

**第一步（本次实施）**：增量持久化 + current_stage 追踪
- 在关键阶段完成后立即写入中间结果
- 更新 `current_stage` 并持久化 `round_record`
- Round 完成后清理中间文件

**第二步（后续实施）**：恢复逻辑
- 在 `run_round()` 开始时检查并加载中间结果
- 根据已完成的阶段跳过对应逻辑
- 这一步需要更仔细的设计，因为恢复时需要重建各种上下文对象

## 假设与决策

1. **先做增量持久化，后做恢复逻辑**：增量持久化是恢复的前提，且本身就有价值（崩溃后可手动检查中间结果）
2. **中间文件放在 `{round_id}/intermediate/` 目录**：与最终的 runs/evaluations/patches 目录分离，避免混淆
3. **使用 JSON 格式**：与现有 store 一致，便于调试和手动检查
4. **不修改 `OptimizerCheckpoint` 结构**：保持 Round 级别 checkpoint 不变，Stage 级别恢复使用独立的中间文件

## 验证步骤

1. 运行全量测试：`python -m pytest tests/ -x -q`
2. 验证中间结果文件在阶段完成后立即写入
3. 验证 `current_stage` 在每个阶段后更新
4. 验证 Round 完成后中间文件被清理
5. 模拟崩溃场景：在某个阶段后手动终止，检查中间文件是否完整
