# Analysis Prompt 优化阶段日志补齐计划

## 摘要

用户提出的疑问得到确认：**当前日志确实只覆盖了抽取（extraction）prompt 优化阶段的进度，analysis prompt 优化阶段几乎没有日志**。`_run_analysis_optimization` 方法（220 行代码、9 个步骤、4 个早退返回点）内部零 `log_stage` 调用，仅有的两处 analysis 日志（`analysis_iteration_accepted`/`analysis_iteration_rolled_back`）位于调用方 `run_round`，且无 `progress="x/y"` 字段，无法看出分析迭代进度。本计划补齐 analysis 阶段的日志，使其可观测性与 extraction 阶段对齐。

## 当前状态分析

### Analysis 阶段日志盲区

**核心方法**：`RoundRunner._run_analysis_optimization`（[round_runner.py:1273-1492](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L1273-L1492)）

整个方法分 9 个步骤，全部无 `log_stage`：

| 步骤 | 行号 | 逻辑 | 日志 |
|------|------|------|------|
| 1. 早退：无 blind_evaluation_records | 1299-1305 | `rejection_reason="no_blind_evaluation_records"` | 无 |
| 2. 早退：无 error_sample_ids | 1312-1318 | `rejection_reason="no_analysis_errors"` | 无 |
| 3. 基线测试循环 | 1328-1344 | 对每个 error_sample 调用 `run_single_analysis` | 无 |
| 4. 计算基线准确率 | 1346-1348 | `base_acc = base_correct / base_total` | 无 |
| 5. 补丁生成循环 | 1358-1381 | 对每个 error_sample 调用 `generate_analysis_patch` | 无 |
| 6. 补丁校验 | 1383-1389 | `PatchValidator().validate(...)` | 无 |
| 7. 早退：无有效补丁 | 1391-1399 | `rejection_reason="no_valid_analysis_patches"` | 无 |
| 8. 补丁合并 | 1401-1424 | `HierarchicalPatchMerger` / `TreeReducePatchMerger` + 可选 `SemanticPatchProcessor` | 无 |
| 9. 早退：合并后为空 | 1426-1434 | `rejection_reason="analysis_merge_empty"` | 无 |
| 10. 应用补丁 | 1436-1441 | `PatchApplier().apply(...)` | 无 |
| 11. 补丁后重测循环 | 1443-1461 | 再次调用 `run_single_analysis` | 无 |
| 12. 计算补丁后准确率 | 1463-1465 | `patched_acc = patched_correct / patched_total` | 无 |
| 13. 决策：接受/拒绝 | 1467-1492 | `if patched_acc >= base_acc: accepted=True` | 无（日志在调用方） |

### 仅有的两处 analysis 日志（调用方）

[round_runner.py:287-296](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L287-L296)：
- `analysis_iteration_rolled_back`：含 `round`、`reason`、`base_accuracy`、`patched_accuracy`、`patch_count`，**无 progress 字段**
- `analysis_iteration_accepted`：含 `round`、`patch_count`、`base_accuracy`、`patched_accuracy`，**无 progress 字段**

### AnalysisRunner 内部零日志

[analysis/runner.py](file:///workspace/mmap_optimizer/analysis/runner.py)：
- `run_single_analysis`（行 179-251）：零 `log_stage`，无法知道处理到第几个样本、解析是否成功
- `generate_analysis_patch`（行 253-389）：零 `log_stage`，无法知道补丁生成进度

### Extraction 阶段日志（对比基准）

- `_run_extraction_optimization`（[round_runner.py:690-1271](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L690-L1271)）：8 处阶段级 `log_stage`
- `run_round` 调用方迭代日志：6 处含 `progress="x/y"` 字段
- `prompt_test_runner.py`：完整 per-sample 日志链（sample_start → model_call → parse → evaluate → sample_done → batch_done）

### Analysis Evolution 日志盲区

`_run_analysis_evolution`（[round_runner.py:1494-1567](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L1494-L1567)）：零 `log_stage`，仅写报告文件。

## 拟定改动

### 文件 1：`mmap_optimizer/orchestration/round_runner.py`

**改动 A：`_run_analysis_optimization` 方法补齐阶段级日志（约 10 处）**

在以下位置添加 `log_stage` 调用：

1. **方法入口**（行 1299 之前）：`analysis_optimization_start`
   - 字段：`round`、`error_sample_count`、`blind_eval_count`
2. **早退：无 blind_evaluation_records**（行 1300）：`analysis_skipped`
   - 字段：`round`、`reason="no_blind_evaluation_records"`
3. **早退：无 error_sample_ids**（行 1313）：`analysis_skipped`
   - 字段：`round`、`reason="no_analysis_errors"`、`base_accuracy=1.0`
4. **基线测试循环开始**（行 1328 之前）：`analysis_base_run_start`
   - 字段：`round`、`sample_count=len(error_samples)`
5. **基线测试循环结束**（行 1346 之前）：`analysis_base_run_done`
   - 字段：`round`、`sample_count=base_total`、`base_accuracy=base_acc`、`correct_count=base_correct`
6. **补丁生成循环开始**（行 1358 之前）：`analysis_patch_generation_start`
   - 字段：`round`、`sample_count=len(error_samples)`
7. **补丁生成循环结束**（行 1382 之前）：`analysis_patch_generation_done`
   - 字段：`round`、`draft_patch_count=len(draft_patches)`
8. **补丁校验结束**（行 1391 之前）：`analysis_patch_validation_done`
   - 字段：`round`、`candidate_count=len(candidate_patches)`、`rejected_count=len(draft_patches)-len(candidate_patches)`
9. **早退：无有效补丁**（行 1392）：`analysis_skipped`
   - 字段：`round`、`reason="no_valid_analysis_patches"`、`base_accuracy=base_acc`
10. **补丁合并结束**（行 1426 之前）：`analysis_patch_merge_done`
    - 字段：`round`、`merged_patch_count=len(merged_patches)`
11. **早退：合并后为空**（行 1427）：`analysis_skipped`
    - 字段：`round`、`reason="analysis_merge_empty"`、`base_accuracy=base_acc`
12. **补丁后重测循环开始**（行 1443 之前）：`analysis_patched_test_start`
    - 字段：`round`、`sample_count=len(error_samples)`、`patch_count=len(merged_patches)`
13. **补丁后重测循环结束**（行 1463 之前）：`analysis_patched_test_done`
    - 字段：`round`、`patched_accuracy=patched_acc`、`correct_count=patched_correct`、`total_count=patched_total`
14. **方法出口**（行 1492 之后）：`analysis_optimization_done`
    - 字段：`round`、`accepted=...`、`base_accuracy=base_acc`、`patched_accuracy=patched_acc`、`patch_count=...`、`rejection_reason=...`

**改动 B：调用方迭代日志补齐 `progress` 字段**

[round_runner.py:287-296](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L287-L296)：
- `analysis_iteration_rolled_back`：添加 `progress=f"{accepted_iteration_count}/{self.config.max_text_rounds}"`
- `analysis_iteration_accepted`：添加 `progress=f"{accepted_iteration_count}/{self.config.max_text_rounds}"`

> 说明：analysis 迭代复用 extraction 的 `accepted_iteration_count` 和 `max_text_rounds` 上限（analysis 无独立迭代计数器，跟随 extraction 迭代节奏），因此 progress 字段与 extraction 一致。

**改动 C：`_run_analysis_evolution` 方法补齐日志（约 4 处）**

1. **方法入口**（行 1518 之前）：`analysis_evolution_start`
   - 字段：`round`、`rejected_patch_count=len(rejected_patches)`、`toxic_patch_count=len(toxic_patches)`
2. **引擎执行后**（行 1554 之后）：`analysis_evolution_done`
   - 字段：`round`、`report_id=report.id`、`promoted=getattr(report, "promoted", False)`
3. **promoted 场景**（行 1564-1565）：`analysis_evolution_promoted`
   - 字段：`round`、`report_id=report.id`
4. **未 promoted 场景**（else 分支，需新增）：`analysis_evolution_skipped`
   - 字段：`round`、`report_id=report.id`、`reason="no_candidate"`

### 文件 2：`mmap_optimizer/analysis/runner.py`

**改动 D：`run_single_analysis` 补齐 per-sample 日志（约 3 处）**

1. **方法入口**（行 201 之前）：`analysis_sample_start`
   - 字段：`sample_id`、`round_id`、`has_ground_truth=bool(ground_truth_label)`
2. **模型响应后**（行 219 之后）：`analysis_sample_model_done`
   - 字段：`sample_id`、`parse_success=parse_result.parse_success`、`schema_valid=parse_result.schema_valid`
3. **方法出口**（行 243 之前）：`analysis_sample_done`
   - 字段：`sample_id`、`matches_truth=matches_truth`、`judgement_label=judgement_label`

> 说明：模型请求/响应日志由 `OpenAICompatibleClient.complete` 已有的 `model_request_start`/`model_response_done` 覆盖，此处不重复。`run_single_analysis` 在基线测试和补丁后重测中各调用一次，可通过 `round_id` + `sample_id` 关联。

**改动 E：`generate_analysis_patch` 补齐 per-sample 日志（约 2 处）**

1. **方法入口**（行 275 之前）：`analysis_patch_gen_start`
   - 字段：`sample_id`、`round_id`、`has_reflection=bool(reflection_record)`
2. **方法出口**（return 之前）：`analysis_patch_gen_done`
   - 字段：`sample_id`、`round_id`、`draft_patch_count=len(patches)`、`run_count=len(runs)`

### 文件 3：`mmap_optimizer/orchestration/round_runner.py`（基线/补丁后测试循环添加 per-sample 进度）

**改动 F：基线测试循环和补丁后重测循环添加 `progress` 字段**

由于 `run_single_analysis` 是单样本调用，循环内已有 `analysis_sample_start/done` 日志（改动 D），可在循环外用 `enumerate` 计数传入 `sample_index`，使 `analysis_sample_start/done` 携带 `progress=f"{i}/{total}"`。

- 基线测试循环（行 1328-1344）：改为 `for i, sample in enumerate(error_samples, 1):`，将 `sample_index=i` 传入 `run_single_analysis`（需调整签名）或在循环内单独打日志
- 补丁后重测循环（行 1445-1461）：同上

> 决策：为避免修改 `run_single_analysis` 签名（影响测试），采用**循环内单独打日志**方案——在循环内用 `log_stage` 打 `analysis_sample_start`，携带 `progress`，然后调用 `run_single_analysis`（不在方法内部打 start/done）。这样 `run_single_analysis` 内部只保留 `model_done` 日志（改动 D 第 2 点），start/done 由循环负责。

## 假设与决策

1. **Analysis 迭代进度复用 extraction 计数器**：analysis 无独立迭代循环，跟随 extraction 迭代节奏（每次 extraction 迭代后触发一次 analysis），因此 `progress` 使用 `accepted_iteration_count/max_text_rounds`，与 extraction 一致。
2. **不修改 `run_single_analysis`/`generate_analysis_patch` 签名**：避免影响现有测试，per-sample 进度通过循环内单独打日志实现。
3. **不添加 analysis 收敛/重试上限日志**：analysis 无独立收敛/重试机制（无 `max_restart_attempts` 等价物），早退场景通过 `analysis_skipped` 日志覆盖。
4. **Analysis Evolution 日志独立于 analysis 优化**：evolution 是基于硬失败信号的影子进化，与 analysis prompt 优化是两套机制，日志 stage 名使用 `analysis_evolution_*` 前缀区分。
5. **stage 命名规范**：统一使用 `analysis_*` 前缀，与 `extraction_*` 对齐；per-sample 使用 `analysis_sample_*`，与 `sample_*` 对齐。
6. **不补齐 `analysis/evolution.py` 内部日志**：`AnalysisEvolutionEngine.evolve` 内部逻辑较复杂，且已有报告文件持久化，本次仅在调用方 `_run_analysis_evolution` 打阶段级日志，不深入 engine 内部。
7. **不补齐 `analysis/parser.py`/`analysis/repair.py`/`analysis/llm_repair.py` 日志**：这些是底层工具，解析失败信息已通过 `parse_success`/`schema_valid` 字段在 `analysis_sample_done` 中体现。

## 验证步骤

1. **单元测试**：运行 `python -m pytest tests/ -k "analysis"` 确保现有 analysis 相关测试不受影响
2. **日志测试**：运行 `python -m pytest tests/ -k "log"` 确保日志相关测试通过
3. **全量测试**：运行 `python -m pytest tests/` 确认无回归（已知预存在失败 `test_round_runner_saves_snapshot_before_promoting_patch` 除外）
4. **手动验证**：在启用 `analysis_prompt_optimization_enabled` 的配置下运行一轮优化，检查日志输出是否包含：
   - `analysis_optimization_start` → `analysis_base_run_done` → `analysis_patch_generation_done` → `analysis_patch_merge_done` → `analysis_patched_test_done` → `analysis_optimization_done` 完整链路
   - `analysis_iteration_accepted`/`analysis_iteration_rolled_back` 携带 `progress` 字段
   - 早退场景输出 `analysis_skipped` 日志
   - evolution 场景输出 `analysis_evolution_start`/`analysis_evolution_done` 日志

## 改动范围汇总

| 文件 | 改动点数 | 说明 |
|------|---------|------|
| `mmap_optimizer/orchestration/round_runner.py` | ~20 | `_run_analysis_optimization` 阶段级日志（14）+ 调用方 progress 字段（2）+ `_run_analysis_evolution` 日志（4）+ 循环内 per-sample 进度（2） |
| `mmap_optimizer/analysis/runner.py` | ~5 | `run_single_analysis` 内部日志（2）+ `generate_analysis_patch` 内部日志（2）+ 循环内 per-sample 进度日志（1） |
| **合计** | ~25 | 2 个文件，约 25 个日志点 |
