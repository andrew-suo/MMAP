# 修复 4 个已验证 Bug 方案

## 摘要

验证了 4 个报告的 Bug，全部确认为真实问题。制定修复方案。

## Bug 验证结果

### Bug 1: KeyError in patch_tester.py:43 — ✅ 确认

**代码**：`base = by_base[patched.sample_id]` — 直接 `[]` 访问字典

**场景**：`base_evals` 和 `patched_evals` 的 sample_id 集合可能不一致。例如：
- patched prompt 运行了额外样本
- base 运行中某些样本被跳过但 patched 运行中存在

**修复**：使用 `.get()` + 跳过缺失样本

### Bug 2: KeyError in fewshot/engine.py:384 — ✅ 确认

**代码**：`baseline = baseline_by_sample[candidate.sample_id]` — 直接 `[]` 访问字典

**场景**：`_regressions()` 方法中，`candidate_evaluations` 可能包含不在 `baseline_by_sample` 中的样本

**修复**：使用 `.get()` + 跳过缺失样本（与 Bug 1 同模式）

### Bug 3: PromptVersion 反序列化后 rendered_prompt 变成 dict — ✅ 确认

**根因链**：
1. `to_plain(prompt_version)` 调用 `asdict()` 将 `RenderedPrompt` dataclass 序列化为 `{"text": ..., "text_hash": ..., "line_count": ..., "token_count": ...}`
2. `PromptVersion.from_dict(payload)` 重建时，`rendered_prompt` 字段接收到 dict
3. `if obj.rendered_prompt is None:` 检查失败（dict 不是 None）
4. 不会调用 `obj.render()`
5. 后续代码访问 `rendered_prompt.text` 或 `rendered_prompt.text_hash` 时崩溃（dict 没有 `.text` 属性）

**影响路径**：`save_prompt_snapshot()` → `to_plain()` → JSON → `rollback_to_snapshot()` → `PromptVersion.from_dict()` → rendered_prompt 为 dict

**修复**：在 `from_dict()` 中检测 `rendered_prompt` 为 dict 的情况，重建为 `RenderedPrompt` 对象或强制重新渲染

### Bug 4: IndexError 当 primary_answer_fields 为空 — ✅ 确认

**代码**：`contract.primary_answer_fields[0]` — 空列表 IndexError

**位置**：evaluator.py 第 77 行和第 154 行

**修复**：添加空列表检查，fallback 到默认字段名

### 额外发现：fewshot/engine.py:249 dict content bug

与 `llm_repair.py` 和 `semantic.py` 同类问题：`"content": {...}` 应为 `json.dumps({...})`

## 修改方案

### Bug 1: patch_tester.py KeyError

**文件**：`/workspace/mmap_optimizer/testing/patch_tester.py`

```python
# 第 42-43 行，改为：
for patched in patched_evals:
    base = by_base.get(patched.sample_id)
    if base is None:
        continue
    transition = classify_transition(base, patched)
```

### Bug 2: fewshot/engine.py KeyError

**文件**：`/workspace/mmap_optimizer/fewshot/engine.py`

```python
# 第 383-384 行 _regressions() 方法，改为：
for candidate in candidate_evaluations:
    baseline = baseline_by_sample.get(candidate.sample_id)
    if baseline is None:
        continue
```

### Bug 3: version.py rendered_prompt 反序列化

**文件**：`/workspace/mmap_optimizer/prompt/version.py`

在 `from_dict()` 中，检测 `rendered_prompt` 为 dict 的情况并重建为 `RenderedPrompt`：

```python
@classmethod
def from_dict(cls, data: Mapping[str, Any]) -> "PromptVersion":
    data = dict(data)
    prompt_ir_data = data.get("prompt_ir")
    if isinstance(prompt_ir_data, dict):
        data["prompt_ir"] = PromptIR.from_dict(prompt_ir_data)
    # 重建 rendered_prompt：如果序列化后变成 dict，需要转回 RenderedPrompt
    rendered_data = data.get("rendered_prompt")
    if isinstance(rendered_data, dict):
        data["rendered_prompt"] = RenderedPrompt(**{k: rendered_data[k] for k in RenderedPrompt.__dataclass_fields__ if k in rendered_data})
    known = set(cls.__dataclass_fields__.keys())
    fields = {k: data[k] for k in known & data.keys()}
    extra = {k: v for k, v in data.items() if k not in known}
    obj = cls(**fields)
    if extra:
        obj._extra = extra
    if obj.rendered_prompt is None:
        obj.render()
    return obj
```

### Bug 4: evaluator.py IndexError

**文件**：`/workspace/mmap_optimizer/evaluation/evaluator.py`

在第 77 行和第 154 行添加空列表检查：

```python
# 第 77 行
primary_field = contract.primary_answer_fields[0] if contract.primary_answer_fields else "result"

# 第 154 行
primary_field = contract.primary_answer_fields[0] if contract.primary_answer_fields else "result"
```

### 额外修复: fewshot/engine.py dict content bug

**文件**：`/workspace/mmap_optimizer/fewshot/engine.py`

第 249 行：
```python
# 当前（错误）
"content": {"sample_id": sample.id, "ground_truth": ground_truth.value, ...}
# 修复为
"content": json.dumps({"sample_id": sample.id, "ground_truth": ground_truth.value, ...}, ensure_ascii=False)
```

## 验证步骤

1. 运行全量测试：`python -m pytest tests/ -x -q`
2. 检查 `patch_tester.py` 中 `.get()` 安全访问
3. 检查 `fewshot/engine.py` 中 `_regressions()` 安全访问 + dict content 修复
4. 检查 `version.py` 中 `from_dict()` 对 dict 类型 rendered_prompt 的处理
5. 检查 `evaluator.py` 中空列表 fallback
