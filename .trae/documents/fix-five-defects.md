# MMAP 5 个缺陷修复方案

## 问题概览

| # | 问题 | 严重程度 | 文件 |
|---|------|---------|------|
| 1 | analysis/runner.py KeyError 风险 | P1 | `mmap_optimizer/analysis/runner.py:103` |
| 2 | hint_generator.py JSON 正则不支持嵌套 | P1 | `mmap_optimizer/prompt/hint_generator.py:122` |
| 3 | openai_compatible.py Null Content 未处理 | P1 | `mmap_optimizer/model/openai_compatible.py:46,71` |
| 4 | llm_repair.py User Content 格式错误 | P1 | `mmap_optimizer/analysis/llm_repair.py:13` |
| 5 | TreeReduce Merge 缺少 Semantic Merge | P2 | `mmap_optimizer/patch/tree_reduce.py:110-136` |

---

## 问题 1：analysis/runner.py KeyError 风险

### 当前代码
```python
# line 103
source_run = extraction_runs[evaluation.sample_id]
```

### 修复方案
使用 `.get()` + 跳过缺失 sample，添加警告日志：

```python
source_run = extraction_runs.get(evaluation.sample_id)
if source_run is None:
    logger.warning(
        "No extraction run found for sample_id=%s, skipping analysis",
        evaluation.sample_id,
    )
    continue
```

**文件**：`/workspace/mmap_optimizer/analysis/runner.py`

---

## 问题 2：hint_generator.py JSON 正则不支持嵌套

### 当前代码
```python
# line 122
json_match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
```

### 修复方案
使用栈匹配代替正则，支持嵌套 JSON：

```python
def _extract_json_object(text: str) -> str | None:
    """Extract the first complete JSON object from text, handling nested braces."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
```

替换 `re.search(r"\{[^}]+\}", raw, re.DOTALL)` 为 `_extract_json_object(raw)`。

**文件**：`/workspace/mmap_optimizer/prompt/hint_generator.py`

---

## 问题 3：openai_compatible.py Null Content 未处理

### 当前代码
```python
# line 46
content = body["choices"][0]["message"]["content"]
# line 71
content = body["choices"][0]["message"]["content"]
```

### 修复方案
在 `complete()` 和 `complete_multimodal()` 中添加 null 检查：

```python
content = body["choices"][0]["message"]["content"]
if content is None:
    content = ""
```

两处都修改（line 46 和 line 71）。

**文件**：`/workspace/mmap_optimizer/model/openai_compatible.py`

---

## 问题 4：llm_repair.py User Content 格式错误

### 当前代码
```python
# line 13
{"role": "user", "content": {"raw_text": raw_text}}
```

### 修复方案
使用 `json.dumps()` 序列化 dict 为字符串：

```python
{"role": "user", "content": json.dumps({"raw_text": raw_text}, ensure_ascii=False)}
```

需要在文件顶部确认 `json` 已导入（当前未导入，需添加）。

**文件**：`/workspace/mmap_optimizer/analysis/llm_repair.py`

---

## 问题 5：TreeReduce Merge 缺少 Semantic Merge

### 分析

**当前架构**：
- `TreeReducePatchMerger._merge_many()` 只做文本级拼接（bullet list）
- `round_runner.py:214-229` 已有 `SemanticPatchProcessor` 后处理步骤（通过 `patch_semantic_merge_enabled` 配置控制）
- `HierarchicalMerge` 有独立的 `Patch` dataclass，与 `schema.Patch` 不兼容，**不能直接替换**

**更好的方案**：改进 `_merge_many()` 的文本拼接逻辑，而非替换整个 merger

### 修复方案

改进 `_merge_many()` 的合并策略：

1. **去重**：合并前去除重复的 patch_text 行
2. **结构化拼接**：按 intent 分组，而非简单 bullet list
3. **保留最通用表述**：当多个 patch 文本高度重叠时，保留最长的

```python
def _merge_many(self, round_id: str, cluster: PatchCluster, patches: list[Patch]) -> Patch:
    first = patches[0]
    # Deduplicate patch text lines
    seen_lines: set[str] = set()
    unique_lines: list[str] = []
    for patch in patches:
        patch.status = "superseded"
        for line in patch.patch_text.strip().splitlines():
            normalized = line.strip().lstrip("- ").strip()
            if normalized and normalized not in seen_lines:
                seen_lines.add(normalized)
                line_text = line.strip()
                unique_lines.append(line_text if line_text.startswith("-") else f"- {line_text}")
    ...
```

**文件**：`/workspace/mmap_optimizer/patch/tree_reduce.py`

---

## 实施步骤

1. 修复问题 1：`analysis/runner.py` KeyError → `.get()` + skip + warning
2. 修复问题 2：`hint_generator.py` JSON 正则 → `_extract_json_object()` 栈匹配
3. 修复问题 3：`openai_compatible.py` null content → `if content is None: content = ""`
4. 修复问题 4：`llm_repair.py` dict content → `json.dumps()`
5. 修复问题 5：`tree_reduce.py` `_merge_many()` → 去重 + 结构化拼接
6. 添加测试覆盖
7. 运行全量测试
8. 推送并创建 PR

## 验证步骤

1. 问题 1：构造 `extraction_runs` 缺少某个 `sample_id` 的场景，验证跳过而非崩溃
2. 问题 2：测试嵌套 JSON 提取（`{"a": {"b": 1}}`）
3. 问题 3：mock API 返回 `content: null`，验证返回空字符串
4. 问题 4：验证 LLM repair 请求中 content 为字符串
5. 问题 5：测试重复 patch_text 行的合并去重
