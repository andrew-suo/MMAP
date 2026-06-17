# 剩余问题修复计划

## 摘要

基于之前的全代码库分析（42 个问题），已修复 15 个严重问题，剩余 27 个问题待修复（中等 12 个 + 低等 15 个）。

---

## 中等问题（M1-M7, M13-M17）

### M1. merge_ranking.py 死代码（约 380 行）

**位置**：`patch/merge_ranking.py`

**问题**：整个模块未被任何外部代码调用，`TreeReducePatchMerger` 完全不经过此模块。

**方案**：添加注释说明这是可选的备用合并策略（与模块 docstring 一致），不删除代码但标记为 `__all__` 仅供探索使用。或者将其与 `tree_reduce.py` 集成作为评分层。

**决策**：标记为 `__all__` + 添加 `# DEPRECATED: merge_ranking pipeline not yet integrated` 注释，保留代码以备将来使用。

### M2. PatchTestResult 死字段

**位置**：`testing/patch_tester.py`

| 字段 | 状态 |
|------|------|
| `format_error_count` | 从未填充，恒为 0 |
| `unchanged_wrong_sample_ids` | 仅填充，无下游读取 |
| `unchanged_correct_sample_ids` | 仅填充，无下游读取 |

**方案**：
- `format_error_count`：在 `summarize_patch_test` 中填充（如果 LLM 输出格式错误）。这需要评估结果的 `overall_status` 包含 "format_error" 类型。
- `unchanged_wrong_sample_ids` / `unchanged_correct_sample_ids`：保留为审计字段，但添加注释说明仅用于调试。

### M3. PatchStatus 枚举未使用

**位置**：`core/enums.py`

**问题**：枚举定义完整但全代码库使用裸字符串字面量。

**方案**：
- 在 `patch/schema.py` 中，`Patch` 数据类使用裸字符串 `status` 字段
- 迁移到枚举需要大量改动（跨多个模块）
- **折中方案**：在 `core/enums.py` 添加裸字符串常量别名，供外部使用：
```python
PATCH_STATUS_DRAFT = "draft"
PATCH_STATUS_CANDIDATE = "candidate"
...
```
- 保留枚举定义但不强制使用，避免破坏性变更

### M4. RoundStage 8 个枚举值未使用

**位置**：`orchestration/records.py`

**问题**：`current_stage` 无法准确反映 round 真实执行进度。

**方案**：
- 不删除枚举值（保持前向兼容）
- 在 `round_runner.py` 的各个阶段添加缺失的 `_advance_stage` 调用：
  - `OPTIMIZATION_BATCH_SELECT`：第 85-100 行（batch 选择后）
  - `DYNAMIC_VALIDATION`：第 151 行之后
  - `PATCH_GENERATION`：第 172 行之前
  - `PATCH_TREE_REDUCE`：第 232 行（tree reduce 开始）
  - `PATCH_RANKING`：第 224 行之后
  - `ANALYSIS_EVOLUTION`：第 357-365 行（if enabled）
  - `METRICS`：第 461 行（metrics 计算前）
  - `FAILED`：在 except 块中设置

### M5. Intermediate 文件写了但不读

**位置**：`orchestration/round_runner.py` + `optimizer_loop.py`

**问题**：`_save_intermediate` 在 7 个 checkpoint 点写入，但没有任何恢复逻辑读取它们。

**方案**：
- 在 `optimizer_loop.py` 的 `_load_existing_checkpoint` 中，读取已完成的 intermediate stages
- 或者将 intermediate 数据整合到 checkpoint.json 中（使其在 checkpoint 中可见）
- **折中**：保留当前实现，添加注释说明这是 stage-level checkpoint 的第一阶段，第二阶段（恢复逻辑）需要额外实现

### M6. Checkpoint sample_states 不完整

**位置**：`orchestration/optimizer_loop.py:138-146`

**问题**：只保存 4 个字段，丢失了 `consecutive_correct_count`、`consecutive_wrong_count`、`selected_count_recent_window`、`historical_fixed`、`toxic_trigger`。

**方案**：扩展保存的字段到所有 `SampleState` dataclass 字段：
```python
sample_states=[
    {
        "sample_id": sample_state.sample_id,
        "difficulty_ema": sample_state.difficulty_ema,
        "fragility_score": sample_state.fragility_score,
        "last_selected_round": sample_state.last_selected_round,
        "consecutive_correct_count": sample_state.consecutive_correct_count,
        "consecutive_wrong_count": sample_state.consecutive_wrong_count,
        "selected_count_recent_window": sample_state.selected_count_recent_window,
        "historical_fixed": sample_state.historical_fixed,
        "toxic_trigger": sample_state.toxic_trigger,
    }
    for sample_state in state.sample_states.values()
],
```

### M7. fewshot_pool_path 永远为 None

**位置**：`orchestration/optimizer_loop.py:97`

**方案**：从 `round_runner.py` 的 fewshot pool 路径传入。在 `OptimizerState` 中添加 fewshot_pool_path 字段，或从 round_runner 返回 fewshot_pool_path。

### M13. compression 行数判断与 token budget 矛盾

**位置**：`compression/engine.py:155`

**问题**：当 `token_exceeded=True` 但 `line_exceeded=False` 时仍要求行数减少。

**方案**：分别判断 token 和 line：
```python
if token_exceeded:
    if after_lines < before_lines:
        # 接受：行数减少
        pass
    else:
        report.rejected_sections.append(...)
elif line_exceeded:
    if after_lines >= before_lines:
        report.rejected_sections.append(...)
```

### M14. compress_analysis_if_needed 返回空 evaluations

**位置**：`compression/engine.py:277,280`

**问题**：返回签名声明 `list[EvaluationRecord]`，但实际总返回空列表。

**方案**：要么实现 analysis compression 的评估逻辑，要么在 docstring 中明确说明 analysis compression 不返回 evaluations。

### M15. RunStateStore.load 从未被调用

**位置**：`orchestration/run_state.py`

**方案**：
- 在 `optimizer_loop.py` 的 resume 逻辑中加载 `run_state.json`
- 或者删除 `RunStateStore.load` 方法 + 简化 `run_state.py`

### M16. OptimizerState.analysis_output_schema_contract 未使用

**位置**：`orchestration/round_runner.py:53`

**方案**：从 `OptimizerState` 中移除，或在注释中说明为将来 analysis evolution 预留。

### M17. historical_regression_check_enabled 配置节归属错误

**位置**：`core/config.py:342`

**问题**：`historical_regression_check_enabled` 嵌套在 `post_apply_regression` 节下解析。

**方案**：在 `optimizer_config_from_mapping` 中为其添加独立的配置节：
```python
historical_regression = data.get("historical_regression", {}) or {}
# ...
historical_regression_check_enabled=_bool_value(historical_regression.get("enabled", data.get("historical_regression_check_enabled", True))),
```

---

## 低等问题（L1-L17）

### L1. _post_apply_regression_check runs/evaluations 未持久化

**位置**：`orchestration/round_runner.py:675-683`

**方案**：将回归检查的 runs 和 evaluations 添加到 round_record 或写入 JSONL：
```python
# 在 _post_apply_regression_check 结束后
self.store.write_jsonl(f"{round_id}/regression_runs.jsonl", [asdict(r) for r in run_result.runs])
```

### L2 ✓ 已修复（id 比较）

### L3. Transition.CHANGED_BUT_STILL_CORRECT 未返回

**位置**：`testing/transition.py`

**方案**：在 `classify_transition` 中添加预测内容比较，或将死枚举值删除。

### L4. PromptVersionType 死枚举值

**位置**：`core/enums.py`

**方案**：删除 `ANALYSIS_SHADOW_PROMOTION` 和 `MANUAL`，或保留并添加注释说明为将来预留。

### L5 ✓ 已修复（import random 移到顶部）

### L6. FAILED stage 从未设置

**位置**：`orchestration/round_runner.py`

**方案**：在 `run_round` 添加 try/except，在 except 块中设置 `round_record.current_stage = RoundStage.FAILED`：
```python
try:
    # existing code
except Exception:
    round_record.current_stage = RoundStage.FAILED
    round_record.status = "ROUND_FAILED"
    raise
```

### L7. metrics_summary 中 round_id 命名误导

**位置**：`orchization/optimizer_loop.py:149`

**方案**：将 `"round_id": round_index` 改为 `"round_index": round_index` 或 `"round_number": round_index`。

### L8. tree_reduce 单 patch 幸存者标记 "merged"

**位置**：`patch/tree_reduce.py:100-103`

**方案**：将 `reduced[0].status = "merged"` 改为 `reduced[0].status = "accepted"` 或新增状态 `"passed"`。

### L9. tree_reduce intent_name 被覆盖

**位置**：`patch/tree_reduce.py:137`

**方案**：保留原始 intent_name 列表，或改为 `intent_name=f"{first.intent_name}_merged"`。

### L10. semantic.py 索引越界 fallback

**位置**：`patch/semantic.py:41`

**方案**：当 LLM 返回超过预期的 patches 时，多出项不继承 fallback 的元数据：
```python
converted = []
for index, item in enumerate(payload):
    if isinstance(item, dict):
        if index < len(patches):
            converted.append(_patch_from_dict(item, patches[index]))
        else:
            # 多出的项：使用 minimal fallback，不继承旧 patch 元数据
            converted.append(_minimal_patch_from_dict(item))
```

### L11. semantic.py None 值污染

**位置**：`patch/semantic.py:96`

**方案**：过滤掉 None 值：
```python
extra_updates = {k: v for k, v in {"semantic_template_id": data.get("semantic_template_id"), "semantic_processed": True}.items() if v is not None}
extra = {**fallback.extra, **extra_updates}
```

### L12. fewshot schema_valid 与 reasoning_text 耦合

**位置**：`fewshot/engine.py:235`

**方案**：解耦：`schema_valid=schema_result.valid`，在 `status` 计算中考虑 reasoning：
```python
schema_valid=schema_result.valid,
...
status="validated" if schema_result.valid and primary_matches else "rejected"
# 移除 reasoning_text.strip() 检查
```

### L13. fewshot int() ValueError 风险

**位置**：`fewshot/engine.py:326`

**方案**：添加异常处理：
```python
try:
    slot_index = int(line.split(":", 1)[1])
except ValueError:
    continue
```

### L14. analysis/runner 冗余字段赋值

**位置**：`analysis/runner.py:130-131`

**方案**：删除 `invalid_patch_count`，保留 `invalid_patch_candidate_count`。

### L15. compression semantic 无效重试

**位置**：`compression/semantic.py:59-61`

**方案**：要么删除重试循环（因为参数不变），要么在重试时调整 prompt。

### L16. suite_builder composition 截断计数不准

**位置**：`testing/suite_builder.py:14,20`

**方案**：composition 报告实际截断后的数量，或添加 `_truncated` 字段。

### L17. evaluator primary_answer_correct 命名误导

**位置**：`evaluation/evaluator.py:118`

**方案**：重命名为 `primary_answer_matches_ground_truth`，或添加 docstring 说明语义。

---

## 修复顺序

1. **M4**（RoundStage 阶段推进）— crash recovery 精度核心
2. **M6**（checkpoint sample_states 完整）— resume 后 canary/history 功能可用
3. **M1**（merge_ranking 死代码注释）
4. **L6**（FAILED stage 设置）— 崩溃追踪
5. **L8**（单幸存者标记）
6. **L10/L11**（semantic.py bug）
7. 其余 L 类问题
