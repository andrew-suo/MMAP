# MMAP 缺陷分析与改进方案

## 问题概览

| # | 问题 | 严重程度 | 根因 |
|---|------|---------|------|
| 1 | LLM hints 遗漏部分标题 | P1 | LLM 输出不完整，缺少强制覆盖校验 |
| 2 | Few-Shot 图片未发送 | P2 | fewshot_assets 提取后未添加到 multimodal messages |
| 3 | Dynamic Validation 批次可能为空 | P2 | exclude_sample_ids 过滤后候选不足 |
| 4 | Batch Size 过大致超时 | P2 | 缺少批次分片机制 |
| 5 | Prompt IR 解析脆弱性 | P1 | 单标题触发 legacy fallback |
| 6 | 错误处理不一致 | P2 | executor 异常传播方式不统一 |

---

## 问题 1：Section ID Hints 自动生成不完整

### 根因分析
`hint_generator.py` 的 `_headings_covered_by_generic()` 正确过滤了已被 generic hints 覆盖的标题，但 LLM 输出可能遗漏部分标题。当前实现：
1. 发送所有未覆盖标题到 LLM
2. LLM 自行决定生成哪些 hints
3. 无校验机制确保所有标题都被覆盖

### 改进方案

**方案 A：强制覆盖校验 + 补充调用**

修改 `auto_generate_hints()`：
1. 第一次 LLM 调用后，检查哪些标题仍未被覆盖（既不在 generic hints，也不在生成的 hints）
2. 对遗漏标题进行第二次 LLM 调用（或警告用户手动补充）
3. 返回结果中包含 `uncovered_titles` 字段供用户参考

**方案 B：改进 LLM prompt（推荐）**

修改 `_AUTO_HINT_SYSTEM_PROMPT`：
- 明确要求 LLM 为**每个**标题生成 hint
- 添加示例展示完整覆盖
- 添加校验规则："You MUST generate a hint for EVERY title listed below"

**实施方案**：方案 B + 轻量校验

```python
# hint_generator.py 修改
_AUTO_HINT_SYSTEM_PROMPT = """\
You are a section ID naming assistant for a prompt optimization framework.

Given a list of markdown heading titles, generate a mapping from Chinese \
keywords (extracted from the titles) to concise English snake_case section IDs.

Rules:
1. You MUST generate a hint for EVERY title listed below. Do not skip any title.
2. Extract the most distinctive keyword(s) from each title — the part that \
uniquely identifies the section's purpose.
...
"""

# 返回值增加未覆盖标题信息
def auto_generate_hints(...) -> dict[str, str]:
    ...
    # 校验：检查哪些标题仍未被覆盖
    still_uncovered = []
    for title in uncovered:
        title_keywords = extract_keywords_from_title(title)  # 新增辅助函数
        if not any(kw in hints for kw in title_keywords):
            still_uncovered.append(title)
    
    return {
        "hints": valid_hints,
        "uncovered_titles": still_uncovered,  # 供 CLI 显示警告
    }
```

---

## 问题 2：Few-Shot 图片未发送

### 根因分析
`prompt_test_runner.py:122-140`：
```python
fewshot_asset_ids = _extract_fewshot_asset_ids(prompt, samples)
fewshot_assets = [assets[asset_id] for asset_id in fewshot_asset_ids if asset_id in assets]
# ...
sample_assets = [assets[asset_id] for asset_id in sample.asset_ids if asset_id in assets]
all_assets = fewshot_assets + sample_assets  # ✓ 已合并
response = self.model_client.complete_multimodal(messages, all_assets, ...)  # ✓ 已传递
```

**实际代码已正确实现！** `all_assets = fewshot_assets + sample_assets` 已合并，并传递给 `complete_multimodal()`。

**可能的真实问题**：
- `_extract_fewshot_asset_ids()` 提取逻辑可能不完整（只解析 `FEW_SHOT_SAMPLE:` 标记）
- fewshot section 可能不存在或内容为空

### 改进方案

**验证并增强提取逻辑**：
1. 检查 `_extract_fewshot_asset_ids()` 是否正确处理所有 fewshot 配置来源
2. 添加日志记录 fewshot_assets 数量
3. 添加单元测试验证 fewshot 图片传递

```python
# prompt_test_runner.py 增强
def run(...):
    ...
    fewshot_asset_ids = _extract_fewshot_asset_ids(prompt, samples)
    fewshot_assets = [assets[asset_id] for asset_id in fewshot_asset_ids if asset_id in assets]
    log_stage(logger, "fewshot_assets_extracted", fewshot_count=len(fewshot_assets), expected_ids=fewshot_asset_ids)
    ...
```

---

## 问题 3：Dynamic Validation 批处理可能为空

### 根因分析
`dynamic_validation_sampler.py:97`：
```python
candidates = [sample for sample in samples if sample.active and sample.id not in exclude_sample_ids]
```

当 `exclude_sample_ids` 包含所有活跃样本时，`candidates` 为空 → `sample_ids` 为空。

### 改进方案

**方案：添加空批次警告 + 允许部分重叠**

```python
# dynamic_validation_sampler.py 修改
def select_dynamic_validation_batch(...):
    ...
    candidates = [sample for sample in samples if sample.active and sample.id not in exclude_sample_ids]
    
    # 新增：候选不足时的处理
    if len(candidates) < batch_size:
        coverage_warnings.append(f"CANDIDATES_INSUFFICIENT:{len(candidates)}<batch_size({batch_size})")
        # 允许从 exclude_sample_ids 中补充（降低 exclude 优先级）
        if allow_overlap and len(candidates) < min_candidates:
            excluded_active = [s for s in samples if s.active and s.id in exclude_sample_ids]
            # 按分数排序，补充最低优先级的 excluded 样本
            ...
    
    if not candidates:
        coverage_warnings.append("NO_CANDIDATES_AVAILABLE")
        return DynamicValidationBatch(..., sample_ids=[], rolling_window_coverage_satisfied=False)
    ...
```

**配置层面**：添加 `dynamic_validation_allow_overlap: bool = False` 参数。

---

## 问题 4：Batch Size 过大致超时

### 根因分析
- `batch_size=39` + `max_workers=1` = 串行执行 39 个样本
- 每样本 ~12s → 总耗时 ~8 分钟
- CLI 或 HTTP 连接可能超时

### 改进方案

**方案 A：批次分片执行**

```python
# round_runner.py 修改
def _run_batch_with_chunking(self, samples, chunk_size=10):
    """将大批次分片执行，避免超时"""
    results = []
    for i in range(0, len(samples), chunk_size):
        chunk = samples[i:i+chunk_size]
        chunk_result = self._prompt_runner().run(samples=chunk, ...)
        results.extend(chunk_result)
        log_stage(logger, "batch_chunk_done", chunk_index=i//chunk_size, chunk_size=len(chunk))
    return results
```

**方案 B：配置层面添加 chunk_size**

```yaml
# optimizer.yaml
execution:
  max_workers: 3
  batch_chunk_size: 10  # 新增：每 chunk 最大样本数
  timeout_seconds: 300
```

**方案 C：并行执行（推荐）**

增加 `max_workers` 并行处理，而非串行：
```yaml
execution:
  max_workers: 5  # 并行 5 个 worker
```

---

## 问题 5：Prompt IR 解析的脆弱性

### 根因分析
`initializer.py:282-283`：
```python
if len(sections) < 2:
    return []  # 触发 _legacy_fallback_ir
```

单标题 prompt 整体放入 `legacy_unmapped`，失去结构化优势。

### 改进方案

**方案：放宽最小 section 数量限制**

```python
# initializer.py 修改
def parse_markdown_sections(...):
    ...
    # 修改：允许单标题产生结构化 IR
    if len(sections) < 1:  # 从 2 改为 1
        return []
    
    # 单标题时，自动生成辅助 section（如 output_schema）
    if len(sections) == 1:
        # 确保 output_schema section 存在
        ...
    return sections
```

**或保持当前行为，但增强 legacy_unmapped 的处理**：
- 在 `_legacy_fallback_ir()` 中尝试从 raw_prompt 提取结构信息
- 添加 `metrics.source = "legacy_fallback"` 标记

---

## 问题 6：错误处理不一致

### 根因分析
`executor.py:94-95`：
```python
if not outcome.ok:
    raise RuntimeError(outcome.error or outcome.exception_type or "executor task failed")
```

`prompt_test_runner.py:201-205`：
```python
except Exception as exc:
    logger.exception(...)
    raise  # 直接抛出异常
```

两种不同的错误处理方式：
1. executor 转换为 `RuntimeError`
2. prompt_test_runner 直接抛出原始异常

### 改进方案

**统一错误处理策略**：

```python
# prompt_test_runner.py 修改
def run_one(sample: Sample) -> tuple[RunRecord, EvaluationRecord]:
    ...
    try:
        ...
    except Exception as exc:
        # 返回失败的 RunRecord + EvaluationRecord，而非抛出异常
        run = RunRecord(
            id=f"run_{round_id}_{run_type}{suffix}_{sample.id}",
            ...
            error=str(exc),
            exception_type=type(exc).__name__,
        )
        evaluation = EvaluationRecord(
            round_id=round_id,
            run_id=run.id,
            sample_id=sample.id,
            overall_status="ERROR",
            error=str(exc),
        )
        return run, evaluation
```

---

## 实施优先级

| 优先级 | 问题 | 改进方案 | 预估工作量 |
|--------|------|---------|-----------|
| P0 | #1 LLM hints 遗漏 | 改进 prompt + 校验 | 小 |
| P1 | #5 IR 解析脆弱性 | 放宽限制或增强 legacy | 小 |
| P2 | #3 Dynamic Validation 空批次 | 添加警告 + 允许重叠 | 中 |
| P2 | #6 错误处理不一致 | 统一返回失败 record | 中 |
| P3 | #4 Batch Size 超时 | 配置层面调整 | 配置即可 |
| 验证 | #2 Few-Shot 图片 | 已正确实现，需验证 | 测试 |

---

## 验证步骤

1. **问题 1**：运行 `generate-hints` 后检查 `uncovered_titles` 输出
2. **问题 2**：添加单元测试验证 `all_assets` 包含 fewshot 图片
3. **问题 3**：构造 exclude_sample_ids 包含所有样本的场景，验证警告输出
4. **问题 4**：调整 `max_workers` 配置，验证并行执行
5. **问题 5**：测试单标题 prompt，验证 IR 结构
6. **问题 6**：构造异常场景，验证 RunRecord.error 字段