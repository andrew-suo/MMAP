# 日志中文化与规范化重构计划

## 概述

将项目运行时日志从英文改为中文，统一日志格式（带时间戳），并补充必要但缺失的日志，让用户能清晰了解当前运行状态。

## 当前状态分析

### 日志基础设施（已完成）

`mmap_optimizer/logging.py` 已升级：
- 格式从 `[%(levelname)s] %(message)s` 升级为 `[%(asctime)s] [%(levelname)s] %(message)s`，`datefmt="%Y-%m-%d %H:%M:%S"`
- `log_stage` 新增可选 `message` 参数，支持中文人类可读消息
- `log_progress` 使用 `_safe_log_dict` 进行一致的红action

### 待中文化的文件与日志点

共 9 个生产文件，约 55 处日志调用点：

| 文件 | log_stage | log_progress | logger.xxx | 小计 |
|------|-----------|--------------|------------|------|
| `orchestration/optimizer_loop.py` | 4 | 0 | 1 exception | 5 |
| `orchestration/round_runner.py` | 20 | 0 | 2 warning | 22 |
| `testing/prompt_test_runner.py` | 12 | 0 | 2 (warning+exception) | 14 |
| `model/openai_compatible.py` | 0 | 4 | 2 exception | 6 |
| `patch/applier.py` | 0 | 0 | 1 debug | 1 |
| `cli/main.py` | 0 | 0 | 2 info | 2 |
| `analysis/blind_evaluation.py` | 0 | 0 | 1 warning | 1 |
| `analysis/runner.py` | 0 | 0 | 1 warning | 1 |
| `fewshot/engine.py` | 0 | 0 | 0（需补充） | 0+新增 |

### 测试文件影响分析

- `tests/test_runtime_logging.py`：测试 `log_stage`/`log_progress` 函数本身，断言 stage 名和 key=value，**无需修改**
- `tests/test_prompt_test_runner_logging.py`：断言 stage 名（如 `sample_start`）和 key=value（如 `sample_id=sample-1`），**无需修改**
- `tests/test_openai_compatible_logging.py`：断言 stage 名（如 `model_request_start`）和 key=value，**无需修改**

关键约束：**stage 名和 key 保持英文 snake_case**（保证 grep 友好和测试兼容），**message 参数使用中文**。

## 设计决策

1. **stage 名**：保持英文 snake_case（如 `round_start`、`extraction_run_done`），便于 grep 和测试断言
2. **message 参数**：使用中文，描述当前运行状态（如 `"优化器启动"`、`"第 1 轮开始"`）
3. **kwargs key**：保持英文 snake_case（如 `round=1`、`sample_id=sample-1`），便于 grep 和测试断言
4. **kwargs value**：保持原值（数字、字符串）
5. **`log_progress` → `log_stage`**：`openai_compatible.py` 中的 `log_progress` 调用统一改为 `log_stage`，保持全项目日志格式一致（`[stage=xxx] 中文消息 key=value`）
6. **`logger.exception/warning/info` 带 `[stage=]`**：统一改为 `log_stage` + 中文 message + kwargs
7. **`logger.warning` 不带 stage**：改为 `log_stage` + 中文 message + kwargs，或保留 `logger.warning` 但消息改中文
8. **补充缺失日志**：`fewshot/engine.py` 当前无任何日志，需补充关键节点日志

## 实施步骤

### 步骤 1：中文化 `orchestration/optimizer_loop.py`（5 处）

**文件**：`mmap_optimizer/orchestration/optimizer_loop.py`

| 行号 | 原 stage | 中文 message |
|------|----------|-------------|
| 77 | `optimizer_start` | `"优化器启动"` |
| 83 | `round_start` | `f"第 {round_index} 轮开始"` |
| 97 | `round_done` | `f"第 {round_index} 轮完成"` |
| 105 | `optimizer_done` | `"优化器完成"` |
| 114 | `optimizer_failed`（logger.exception） | `"优化器失败"` |

**改动示例**：
```python
# 行 77
log_stage(logger, "optimizer_start", "优化器启动", planned_rounds=planned_rounds, start_round=effective_start, resume=self.resume)

# 行 83-85
log_stage(logger, "round_start", f"第 {round_index} 轮开始",
          round=round_index, planned_rounds=planned_rounds,
          input_extraction_prompt_id=state.active_extraction_prompt.id,
          input_analysis_prompt_id=state.active_analysis_prompt.id)

# 行 97-100
log_stage(logger, "round_done", f"第 {round_index} 轮完成",
          round=round_index, duration_ms=round_duration_ms,
          accepted_patch_count=len(round_record.accepted_patch_ids) if round_record.accepted_patch_ids else 0,
          rejected_patch_count=len(round_record.rejected_patch_ids) if round_record.rejected_patch_ids else 0,
          batch_accuracy=metrics.batch_accuracy)

# 行 105-108
log_stage(logger, "optimizer_done", "优化器完成", status="COMPLETED", completed_rounds=len(rounds),
          final_batch_accuracy=summary.final_batch_accuracy,
          total_accepted_patches=summary.total_accepted_patches,
          total_rejected_patches=summary.total_rejected_patches)

# 行 114
log_stage(logger, "optimizer_failed", "优化器失败", error=f"{type(exc).__name__}: {exc}")
logger.exception(f"[stage=optimizer_failed] error={type(exc).__name__}: {exc}")  # 保留以输出 traceback
```

注意：`logger.exception` 保留以输出完整 traceback，但在其前增加一行 `log_stage` 中文消息。

### 步骤 2：中文化 `orchestration/round_runner.py`（22 处）

**文件**：`mmap_optimizer/orchestration/round_runner.py`

| 行号 | 原 stage | 中文 message |
|------|----------|-------------|
| 162 | `batch_selection_done` | `"批次选择完成"` |
| 209 | `fewshot_round_baseline_done` | `"fewshot 轮基线抽取完成"` |
| 245 | `extraction_iteration_accepted` | `"抽取迭代已接受"` |
| 286 | `analysis_iteration_rolled_back` | `"分析迭代已回滚"` |
| 289 | `analysis_iteration_accepted` | `"分析迭代已接受"` |
| 301 | `extraction_optimization_converged` | `"抽取优化已收敛"` |
| 336 | `extraction_iteration_converged_early` | `"抽取迭代提前收敛"` |
| 355 | `extraction_iteration_rolled_back` | `"抽取迭代已回滚"` |
| 365 | `extraction_max_retries_reached` | `"抽取重试次数已达上限"` |
| 374 | `max_text_rounds_reached` | `"文本轮数已达上限"` |
| 385 | `dval_run_start` | `"动态验证开始"` |
| 397 | `dval_run_done` | `"动态验证完成"` |
| 547 | logger.warning（无 stage） | 改为 `log_stage(logger, "merge_report_save_failed", "保存 merge_report 失败")` |
| 671 | logger.warning（无 stage） | 改为 `log_stage(logger, "metrics_plots_failed", "生成指标图表失败")` |
| 721 | `extraction_run_start` | `"基线抽取开始"` |
| 732 | `extraction_run_done` | `"基线抽取完成"` |
| 783 | `patch_generation_start` | `"补丁生成开始"` |
| 847 | `blind_evaluation_done` | `"盲评完成"` |
| 853 | `patch_generation_candidates` | `"补丁候选生成完成"` |
| 917 | `patch_merge_done` | `"补丁合并完成"` |
| 958 | `patch_merged_test_done` | `"合并补丁测试完成"` |
| 1046 | `patch_comparison_done` | `"补丁比较与筛选完成"` |

**改动示例**：
```python
# 行 162
log_stage(logger, "batch_selection_done", "批次选择完成", round=round_index, optimization_batch_size=len(optimization_batch), dval_batch_size=len(dval_batch.sample_ids))

# 行 547 - 原 logger.warning("Failed to write merge_report", exc_info=True)
log_stage(logger, "merge_report_save_failed", "保存 merge_report 失败")

# 行 671 - 原 logger.warning("Failed to generate metrics plots", exc_info=True)
log_stage(logger, "metrics_plots_failed", "生成指标图表失败")
```

### 步骤 3：中文化 `testing/prompt_test_runner.py`（14 处）

**文件**：`mmap_optimizer/testing/prompt_test_runner.py`

| 行号 | 原 stage | 中文 message |
|------|----------|-------------|
| 216 | `fewshot_multiturn_enabled` | `"启用 fewshot 多轮对话"` |
| 220 | `fewshot_assets_extracted` | `"无 fewshot 资源"` |
| 224 | `sample_start` | `f"样本处理开始"` |
| 251 | `model_call_start` | `"模型调用开始"` |
| 259 | `model_call_done` | `"模型调用完成"` |
| 271 | `parse_start` | `"解析开始"` |
| 274 | `parse_done` (status=ok) | `"解析完成"` |
| 277 | logger.warning `parse_failed` | 改为 `log_stage(logger, "parse_failed", "解析失败", sample_id=sample.id, error=f"{type(exc).__name__}: {exc}")` |
| 278 | `parse_done` (status=failed) | `"解析完成"` |
| 279 | `evaluate_start` | `"评估开始"` |
| 297 | `evaluate_done` | `"评估完成"` |
| 299 | `sample_done` | `"样本处理完成"` |
| 303 | logger.exception `sample_failed` | 改为 `log_stage(logger, "sample_failed", "样本处理失败", sample_id=sample.id, duration_ms=sample_duration_ms, error=type(exc).__name__)` + 保留 `logger.exception` 输出 traceback |
| 304 | `sample_failed` | `"样本处理失败"` |

**改动示例**：
```python
# 行 277 - 原 logger.warning(f"[stage=parse_failed] sample_id={sample.id} error={type(exc).__name__}: {exc}")
log_stage(logger, "parse_failed", "解析失败", sample_id=sample.id, error=f"{type(exc).__name__}: {exc}")

# 行 303 - 原 logger.exception(f"[stage=sample_failed] ...")
log_stage(logger, "sample_failed", "样本处理失败", sample_id=sample.id, duration_ms=sample_duration_ms, error=type(exc).__name__)
logger.exception(f"[stage=sample_failed] sample_id={sample.id} duration_ms={sample_duration_ms} error={type(exc).__name__}: {exc}")
```

### 步骤 4：中文化 `model/openai_compatible.py`（6 处）

**文件**：`mmap_optimizer/model/openai_compatible.py`

将 4 处 `log_progress` 改为 `log_stage`（带中文 message），2 处 `logger.exception` 改为 `log_stage` + 保留 `logger.exception`。

| 行号 | 原 stage | 中文 message |
|------|----------|-------------|
| 34 | `model_request_start`（log_progress） | `"模型请求开始"` |
| 49 | `model_response_done`（log_progress） | `"模型响应完成"` |
| 54 | `model_request_failed`（logger.exception） | `"模型请求失败"` |
| 60 | `model_request_start`（log_progress） | `"模型请求开始"` |
| 76 | `model_response_done`（log_progress） | `"模型响应完成"` |
| 84 | `model_request_failed`（logger.exception） | `"模型请求失败"` |

**改动示例**：
```python
# 行 34 - 原 log_progress(logger, "model_request_start", ...)
log_stage(logger, "model_request_start", "模型请求开始",
    model=payload.get("model"), message_count=len(messages),
    temperature=payload.get("temperature"), max_tokens=payload.get("max_tokens"),
    timeout=(model_config or {}).get("timeout", 120),
    has_response_format=response_format is not None,
    has_chat_template_kwargs="chat_template_kwargs" in payload,
    enable_thinking=payload.get("chat_template_kwargs", {}).get("enable_thinking") if payload.get("chat_template_kwargs") else None,
)

# 行 54 - 原 logger.exception("[stage=model_request_failed] ...")
log_stage(logger, "model_request_failed", "模型请求失败", model=payload.get("model"), duration_ms=duration_ms, error=f"{type(exc).__name__}: {exc}")
logger.exception(f"[stage=model_request_failed] model={payload.get('model')} duration_ms={duration_ms} error={type(exc).__name__}: {exc}")
```

**注意**：需更新 import：`from mmap_optimizer.logging import get_logger, log_stage`（移除 `log_progress`）。

### 步骤 5：中文化 `patch/applier.py`（1 处）

**文件**：`mmap_optimizer/patch/applier.py`

行 91 原 `logger.debug(f"[stage=patch_apply] ...")` 改为：
```python
log_stage(logger, "patch_apply", "补丁应用完成", patch_id=patch.id, section_id=patch.section_id, mode=mode, duration_ms=apply_duration_ms)
```

**注意**：`log_stage` 使用 `logger.info` 级别，原代码是 `logger.debug`。为保持日志级别，可保留 `logger.debug` 但消息改中文，或改为 `log_stage`（升级到 INFO）。**决策：改为 `log_stage`**，因为补丁应用是关键运行状态，应在 INFO 级别可见。需更新 import：`from mmap_optimizer.logging import get_logger, log_stage`。

### 步骤 6：中文化 `cli/main.py`（2 处）

**文件**：`mmap_optimizer/cli/main.py`

| 行号 | 原 stage | 中文 message |
|------|----------|-------------|
| 107 | `optimizer_start` (mode=smoke) | `"优化器启动（smoke 模式）"` |
| 125 | `optimizer_start` (mode=production) | `"优化器启动（生产模式）"` |

**改动示例**：
```python
# 行 107 - 原 logger.info(f"[stage=optimizer_start] mode=smoke ...")
log_stage(logger, "optimizer_start", "优化器启动（smoke 模式）",
          config_path=getattr(args, 'config', 'N/A'), sample_count=len(state.samples),
          planned_rounds=args.rounds, output_dir=args.run_dir,
          log_level=os.environ.get('MMAP_LOG_LEVEL', 'INFO'))

# 行 125 - 原 logger.info("[stage=optimizer_start] mode=production ...")
log_stage(logger, "optimizer_start", "优化器启动（生产模式）",
          config_path=args.config, extraction_model=config.extraction_model.model,
          extraction_provider=config.extraction_model.provider,
          optimizer_model=config.optimizer_model.model, optimizer_provider=config.optimizer_model.provider,
          max_workers=config.execution_max_workers, sample_count=len(state.samples),
          planned_rounds=args.rounds, output_dir=config.run_dir,
          log_level=os.environ.get('MMAP_LOG_LEVEL', 'INFO'))
```

**注意**：需更新 import：`from mmap_optimizer.logging import get_logger, log_stage`。

### 步骤 7：中文化 `analysis/blind_evaluation.py` + `analysis/runner.py`（2 处）

**文件 1**：`mmap_optimizer/analysis/blind_evaluation.py`

行 116 原：
```python
logger.warning(
    "No extraction run found for sample_id=%s, skipping blind eval",
    evaluation.sample_id,
)
```
改为：
```python
log_stage(logger, "blind_eval_skip", "跳过盲评（无抽取记录）", sample_id=evaluation.sample_id)
```

**文件 2**：`mmap_optimizer/analysis/runner.py`

行 67 原：
```python
logger.warning(
    "No extraction run found for sample_id=%s, skipping analysis",
    evaluation.sample_id,
)
```
改为：
```python
log_stage(logger, "analysis_skip", "跳过分析（无抽取记录）", sample_id=evaluation.sample_id)
```

**注意**：两个文件都需更新 import：`from mmap_optimizer.logging import get_logger, log_stage`。

### 步骤 8：补充 `fewshot/engine.py` 缺失日志

**文件**：`mmap_optimizer/fewshot/engine.py`

当前无任何日志。补充以下关键节点日志：

```python
# 在 optimize_once 方法开头（约行 62 后）
log_stage(logger, "fewshot_optimize_start", "fewshot 优化开始",
          round_id=round_id, slot_count=slot_count, baseline_accuracy=baseline_accuracy,
          max_slots=max_slots, candidate_pool_size=len(candidate_pool.candidates) if candidate_pool else 0)

# 在 max_slots <= 0 时（行 78-80）
log_stage(logger, "fewshot_disabled", "fewshot 已禁用", round_id=round_id)

# 在 mined 后（行 86 后）
log_stage(logger, "fewshot_candidates_mined", "fewshot 候选挖掘完成",
          round_id=round_id, mined_count=len(mined), total_candidates=len(candidates))

# 在 candidates 为空时（行 89-91）
log_stage(logger, "fewshot_no_candidates", "无 fewshot 候选", round_id=round_id)

# 在每个 candidate 测试循环内（行 101 后，循环开始）
log_stage(logger, "fewshot_candidate_test_start", "fewshot 候选测试开始",
          round_id=round_id, candidate_id=candidate.id, sample_id=candidate.sample_id)

# 在 candidate 被拒绝时（行 134-138）
log_stage(logger, "fewshot_candidate_rejected", "fewshot 候选被拒绝",
          round_id=round_id, candidate_id=candidate.id, reason=candidate.rejection_reason,
          accuracy_delta=delta, broken_count=len(broken))

# 在 best_safe 接受时（行 160-169）
log_stage(logger, "fewshot_accepted", "fewshot 优化已接受",
          round_id=round_id, candidate_id=best_report.selected_candidate_id,
          accuracy_delta=best_report.accuracy_delta, operation_type=best_report.operation_type)

# 在无 best_safe 时（行 171-172）
log_stage(logger, "fewshot_no_safe_candidate", "无安全 fewshot 候选", round_id=round_id)
```

**注意**：需更新 import：`from mmap_optimizer.logging import get_logger, log_stage`，并添加 `logger = get_logger(__name__)`。

### 步骤 9：验证测试

运行全量测试验证无回归：

```bash
cd /workspace && python -m pytest tests/ -x -q
```

重点验证：
- `tests/test_runtime_logging.py` - 日志基础设施测试
- `tests/test_prompt_test_runner_logging.py` - PromptTestRunner 日志测试
- `tests/test_openai_compatible_logging.py` - OpenAI 客户端日志测试

预期：所有测试通过，因为 stage 名和 key 保持英文 snake_case，测试断言不受影响。

## 假设与决策

1. **假设**：用户希望日志消息为中文，但 stage 名和结构化 key 保持英文（便于 grep 和机器解析）
2. **决策**：`log_progress` 统一改为 `log_stage`，全项目日志格式一致（`[时间] [级别] [stage=xxx] 中文消息 key=value`）
3. **决策**：`logger.exception` 保留以输出 traceback，但在其前增加 `log_stage` 中文消息行
4. **决策**：`patch/applier.py` 的 `logger.debug` 升级为 `log_stage`（INFO 级别），因为补丁应用是关键运行状态
5. **决策**：`fewshot/engine.py` 补充 8 处关键节点日志，覆盖优化开始、禁用、挖掘、测试、接受、拒绝等状态
6. **不改动**：`logging.py` 已在上一轮升级完成，本轮不再修改

## 验证步骤

1. 完成步骤 1-8 后，运行全量测试：`cd /workspace && python -m pytest tests/ -x -q`
2. 重点检查日志相关测试是否通过
3. 如有测试失败，分析原因并修复（优先调整实现而非测试，除非测试断言本身有误）
4. 手动检查日志输出格式示例：
   ```
   [2026-06-22 10:30:00] [INFO] [stage=optimizer_start] 优化器启动 planned_rounds=5 start_round=1 resume=False
   [2026-06-22 10:30:01] [INFO] [stage=round_start] 第 1 轮开始 round=1 planned_rounds=5 ...
   ```
