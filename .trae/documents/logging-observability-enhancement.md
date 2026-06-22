# 日志可观测性增强计划

## 概述

在已完成的日志中文化基础上，增强日志的"可观测性"：让用户从日志中能清楚知道（1）当前执行到哪个迭代的第几步（x/y 进度），（2）每次模型请求的响应结果摘要（判断输出是否有问题），（3）各关键节点的结果指标。

## 当前状态分析

### 进度感缺口

| 场景 | 现状 | 期望 |
|------|------|------|
| 轮次进度 | `round=1 planned_rounds=5` 需心算 | `round=1/5` 一目了然 |
| 抽取迭代进度 | `iteration=3`（全局索引），无上限 | `iteration=2/10`（局部/上限） |
| 重试进度 | `retry_count=2`，无上限 | `retry=2/3` |
| 样本处理进度 | 只有 `sample_id`，无序号 | `sample=3/24` |
| 投票进度 | `vote_index=1`，无总轮数 | `vote=1/3` |
| fewshot 候选测试 | `candidate_id=xxx`，无序号 | `candidate=2/8` |

### 模型响应结果缺口

| 场景 | 现状 | 期望 |
|------|------|------|
| 正常响应 | 只有 `response_chars=1234` | 增加 `response_preview`（前 120 字符）+ `usage` token 用量 |
| 解析失败 | 只有 `error=JSONDecodeError: ...` | 增加 `response_preview`（前 200 字符）帮助定位问题 |
| 投票结果 | 只记录 `decision` | 增加 `vote_majority`、`vote_confidence`、`parse_error_count` |

### 结果摘要缺口

| stage | 缺少的关键指标 |
|-------|---------------|
| `extraction_run_done` | `base_accuracy` |
| `patch_merged_test_done` | `patched_accuracy` |
| `patch_comparison_done` | `patched_accuracy` |
| `dval_run_done` | `dval_accuracy` |
| `analysis_iteration_rolled_back` | `base_accuracy`、`patched_accuracy` |
| `extraction_iteration_converged_early` | `retry_count`、`accepted_iterations` |
| `merge_report_save_failed` / `metrics_plots_failed` | `round`、`error` |

## 设计决策

1. **进度格式**：新增 `progress="current/total"` 字段（如 `progress="2/10"`），保留原有 `iteration`/`round` 等字段不变（向后兼容测试）
2. **响应预览**：正常响应取前 120 字符（单行，替换换行为 `\n`），解析失败时取前 200 字符。通过 `log_stage` 的 kwargs 传入，`_safe_log_dict` 会自动截断超长值
3. **usage 字段**：从 `ModelResponse.metadata["usage"]` 提取 `prompt_tokens`、`completion_tokens`、`total_tokens`，以 `usage_tokens=123/456` 格式输出（prompt/completion）
4. **样本进度**：在 `prompt_test_runner.py` 的 `run` 方法中，通过 `enumerate` 传入 `sample_index`（从 1 开始）和 `total_samples`
5. **投票结果摘要**：在 `evaluate_done` 中，若 `evaluation.extra` 存在投票信息，追加 `vote_majority`、`vote_confidence`、`parse_error_count`
6. **不改动**：`logging.py` 基础设施（已完成升级）、stage 名（保持英文 snake_case）、现有 kwargs key（向后兼容）

## 实施步骤

### 步骤 1：`model/openai_compatible.py` — 增加响应预览与 usage（4 处）

**文件**：`mmap_optimizer/model/openai_compatible.py`

在 `complete` 和 `complete_multimodal` 的 `model_response_done` 日志中增加 `response_preview` 和 `usage_tokens` 字段。

**`complete` 方法（行 49-50）**：
```python
# 改动前
log_stage(logger, "model_response_done", "模型响应完成",
    model=payload.get("model"), duration_ms=duration_ms, response_chars=len(content) if content else 0)

# 改动后
usage = body.get("usage") or {}
usage_tokens = f"{usage.get('prompt_tokens', 0)}/{usage.get('completion_tokens', 0)}"
preview = (content or "")[:120].replace("\n", "\\n")
log_stage(logger, "model_response_done", "模型响应完成",
    model=payload.get("model"), duration_ms=duration_ms,
    response_chars=len(content) if content else 0,
    response_preview=preview,
    usage_tokens=usage_tokens)
```

**`complete_multimodal` 方法（行 77-78）**：同上改动。

**`model_request_failed`（行 54、85）**：增加 `response_preview`（如果 exc 是 HTTP 错误且有响应体）。但 HTTP 异常通常无响应体，保持现状即可。

### 步骤 2：`orchestration/optimizer_loop.py` — 增加轮次进度（3 处）

**文件**：`mmap_optimizer/orchestration/optimizer_loop.py`

| 行号 | stage | 改动 |
|------|-------|------|
| 83 | `round_start` | 增加 `progress=f"{round_index}/{planned_rounds}"` |
| 97 | `round_done` | 增加 `progress=f"{round_index}/{planned_rounds}"` |
| 105 | `optimizer_done` | 增加 `progress=f"{len(rounds)}/{planned_rounds}"` 和 `accuracy_delta=summary.final_batch_accuracy - summary.first_batch_accuracy`（需确认 summary 有 first_batch_accuracy 字段） |

### 步骤 3：`orchestration/round_runner.py` — 增加迭代进度与结果摘要（12 处）

**文件**：`mmap_optimizer/orchestration/round_runner.py`

#### 3a. 迭代进度（6 处）

| 行号 | stage | 改动 |
|------|-------|------|
| 245 | `extraction_iteration_accepted` | 增加 `progress=f"{accepted_iteration_count}/{self.config.max_text_rounds}"` |
| 301 | `extraction_optimization_converged` | 增加 `progress=f"{accepted_iteration_count}/{self.config.max_text_rounds}"` |
| 336 | `extraction_iteration_converged_early` | 增加 `retry_count=extraction_retry_count`、`accepted_iterations=accepted_iteration_count` |
| 356 | `extraction_iteration_rolled_back` | 增加 `progress=f"{extraction_retry_count}/{self.config.max_restart_attempts}"` |
| 366 | `extraction_max_retries_reached` | 增加 `progress=f"{extraction_retry_count}/{self.config.max_restart_attempts}"` |
| 375 | `max_text_rounds_reached` | 增加 `progress=f"{accepted_iteration_count}/{self.config.max_text_rounds}"` |

#### 3b. 结果摘要（6 处）

| 行号 | stage | 改动 |
|------|-------|------|
| 286 | `analysis_iteration_rolled_back` | 增加 `base_accuracy=analysis_result.base_accuracy`、`patched_accuracy=analysis_result.patched_accuracy`、`patch_count=analysis_result.patch_count` |
| 398 | `dval_run_done` | 增加 `dval_accuracy=<计算值>`（从 dval_evals 统计正确率） |
| 548 | `merge_report_save_failed` | 增加 `round=round_id` |
| 672 | `metrics_plots_failed` | 增加 `round=round_index` |
| 733 | `extraction_run_done` | 增加 `base_accuracy=<计算值>`（从 evals 统计） |
| 959 | `patch_merged_test_done` | 增加 `patched_accuracy=<计算值>`（从 patched_evals 统计） |

### 步骤 4：`testing/prompt_test_runner.py` — 增加样本进度、投票进度、响应预览（8 处）

**文件**：`mmap_optimizer/testing/prompt_test_runner.py`

#### 4a. 样本进度（3 处）

在 `run` 方法中，`run_one` 函数签名增加 `sample_index` 和 `total_samples` 参数（通过 `enumerate` 和闭包传入）。

| 行号 | stage | 改动 |
|------|-------|------|
| 224 | `sample_start` | 增加 `progress=f"{sample_index}/{total_samples}"` |
| 299 | `sample_done` | 增加 `progress=f"{sample_index}/{total_samples}"` |
| 303 | `sample_failed` | 增加 `progress=f"{sample_index}/{total_samples}"` |

**实现方式**：`map_ordered(samples, run_one, ...)` 的 `fn` 签名是 `Callable[[T], R]`，`T` 当前是 `Sample`。改为传入 `(int, Sample)` 元组作为 items（`enumerate(samples, 1)`），`run_one` 签名改为 `run_one(indexed_sample: tuple[int, Sample])`，在函数内解包 `sample_index, sample = indexed_sample`。`total_samples = len(samples)` 通过闭包捕获。

#### 4b. 投票进度（2 处）

| 行号 | stage | 改动 |
|------|-------|------|
| 251 | `model_call_start` | 增加 `progress=f"{vote_index+1}/{rounds}"`（仅投票模式） |
| 259 | `model_call_done` | 增加 `progress=f"{vote_index+1}/{rounds}"`（仅投票模式）、`response_preview=response.raw_output[:120].replace("\n","\\n") if response.raw_output else ""` |

#### 4c. 解析失败响应预览（1 处）

| 行号 | stage | 改动 |
|------|-------|------|
| 277 | `parse_failed` | 增加 `response_preview=raw_outputs[0][:200].replace("\n","\\n") if raw_outputs else ""`、`response_chars=len(raw_outputs[0]) if raw_outputs else 0` |

#### 4d. 投票结果摘要（1 处）

| 行号 | stage | 改动 |
|------|-------|------|
| 297 | `evaluate_done` | 若 `evaluation.extra` 有投票信息，增加 `vote_majority=extra.get("vote_majority")`、`vote_confidence=extra.get("vote_confidence")`、`parse_error_count=len(extra.get("parse_errors", []))` |

#### 4e. 样本完成进度汇总（1 处新增）

在 `run` 方法所有样本处理完成后，增加一行汇总日志：
```python
log_stage(logger, "batch_done", "批次处理完成", total_samples=len(samples), duration_ms=total_duration_ms)
```

### 步骤 5：`fewshot/engine.py` — 增加候选测试进度（2 处）

**文件**：`mmap_optimizer/fewshot/engine.py`

| 行号 | stage | 改动 |
|------|-------|------|
| 138 | `fewshot_candidate_test_start` | 增加 `progress=f"{candidate_index}/{len(candidates)}"`（需在循环中用 `enumerate` 获取 index） |
| 100 | `fewshot_no_candidates` | 增加 `mined_count=len(mined)` |

### 步骤 6：验证测试

```bash
cd /workspace && python -m pytest tests/test_runtime_logging.py tests/test_prompt_test_runner_logging.py tests/test_openai_compatible_logging.py tests/test_prompt_test_runner_fewshot_assets.py -q
```

重点验证：
- 现有测试断言（stage 名、key=value）仍通过——因为新增字段是**追加**而非替换
- 若 `test_openai_compatible_logging.py` 断言了 `model_response_done` 的精确字段集，需检查是否需要更新断言（新增 `response_preview`、`usage_tokens` 字段）

## 假设与决策

1. **进度字段命名**：统一用 `progress="current/total"` 格式，而非 `iteration=1 max=10` 两个字段。原因：`x/y` 格式人眼一扫即知进度，且不与现有 `iteration`（全局索引）字段冲突
2. **响应预览长度**：正常 120 字符、失败 200 字符。原因：120 字符足够判断 JSON 是否合法（`{"` 开头）或是否为错误消息；200 字符覆盖更多调试场景。换行替换为 `\n` 避免日志断行
3. **usage 格式**：`usage_tokens="prompt/completion"`（如 `"1234/567"`），简洁且包含关键信息
4. **样本进度实现**：通过 `enumerate` 在闭包中捕获 index，不改动 `map_ordered` 接口
5. **新增字段均为追加**：不修改/删除现有字段，保证向后兼容
6. **不改动 `logging.py`**：`_safe_log_dict` 已能处理截断（>200 字符截断到 200，>5000 替换为 `<BINARY_DATA>`），响应预览 120/200 字符在其安全范围内

## 验证步骤

1. 完成步骤 1-5 后，运行日志相关测试
2. 检查 `test_openai_compatible_logging.py` 是否断言了精确字段集——若是，更新断言以包含新字段
3. 手动验证日志输出示例：
   ```
   [2026-06-22 10:30:00] [INFO] [stage=round_start] 第 1 轮开始 round=1 planned_rounds=5 progress=1/5 ...
   [2026-06-22 10:30:05] [INFO] [stage=extraction_iteration_accepted] 抽取迭代已接受 round=1 iteration=3 progress=2/10 patch_count=5 base_accuracy=0.75 patched_accuracy=0.83
   [2026-06-22 10:30:10] [INFO] [stage=model_response_done] 模型响应完成 model=qwen duration_ms=1234 response_chars=567 response_preview={"result":"OK","data":[1,2,3 usage_tokens=1234/567
   [2026-06-22 10:30:15] [INFO] [stage=sample_start] 样本处理开始 sample_id=sample-1 asset_count=2 fewshot_slot_count=3 progress=1/24
   [2026-06-22 10:30:20] [INFO] [stage=parse_failed] 解析失败 sample_id=sample-1 error=JSONDecodeError: Expecting value response_preview=<!DOCTYPE html><html><head>... response_chars=4567
   ```
