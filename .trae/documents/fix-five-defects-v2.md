# 修复 5 个 MMAP 缺陷方案

## 摘要

修复 5 个已识别的缺陷：KeyError 风险、JSON 正则不支持嵌套、Null Content 未处理、User Content 格式错误、TreeReduce Merge 缺少去重。

## 当前状态分析

| 问题 | 文件 | 当前状态 | 严重性 |
|------|------|----------|--------|
| 1. KeyError | `analysis/runner.py:105` | `extraction_runs[evaluation.sample_id]` 直接 `[]` 访问 | P1 |
| 2. JSON 正则 | `prompt/hint_generator.py:122` | `re.search(r"\{[^}]+\}", ...)` 不支持嵌套 | P1 |
| 3. Null Content | `model/openai_compatible.py:46,71` | `content` 可能为 `None` | P1 |
| 4. Dict Content | `analysis/llm_repair.py:13` | `content={"raw_text": raw_text}` 传 dict | P1 |
| 5. TreeReduce Merge | `patch/tree_reduce.py:110-136` | `_merge_many()` 简单拼接无去重 | P2 |

### 关键发现

1. **问题1**：`runner.py` 中 `ModelClient` 导入已被误删（之前的编辑将 `from mmap_optimizer.model.client import ModelClient` 替换为了 logger 导入），需要恢复
2. **问题2**：需要替换正则为栈匹配函数，且需处理 JSON 字符串内的花括号（避免误匹配）
3. **问题5**：`HierarchicalMerge` 使用独立的 `Patch` dataclass（frozen, 不同字段），与 `schema.Patch` 不兼容，**不能直接替换**。应在 `_merge_many()` 内部增加去重逻辑

## 修改方案

### 问题 1：analysis/runner.py KeyError 风险

**文件**：`/workspace/mmap_optimizer/analysis/runner.py`

**修改内容**：
1. 恢复 `from mmap_optimizer.model.client import ModelClient` 导入（当前缺失）
2. 将第 105 行 `source_run = extraction_runs[evaluation.sample_id]` 改为安全访问：
```python
source_run = extraction_runs.get(evaluation.sample_id)
if source_run is None:
    logger.warning(
        "No extraction run found for sample_id=%s, skipping analysis",
        evaluation.sample_id,
    )
    continue
```

### 问题 2：hint_generator.py JSON 正则问题

**文件**：`/workspace/mmap_optimizer/prompt/hint_generator.py`

**修改内容**：
1. 新增 `_extract_json_object()` 函数，使用栈匹配替代正则，支持嵌套 JSON 和字符串内花括号：
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
2. 将第 122 行 `json_match = re.search(r"\{[^}]+\}", raw, re.DOTALL)` 替换为 `json_str = _extract_json_object(raw)`
3. 更新后续逻辑：`if not json_str:` 替代 `if not json_match:`，`json.loads(json_str)` 替代 `json.loads(json_match.group())`

### 问题 3：openai_compatible.py Null Content 未处理

**文件**：`/workspace/mmap_optimizer/model/openai_compatible.py`

**修改内容**：
1. 在 `complete()` 方法第 46 行后添加 null 检查：
```python
content = body["choices"][0]["message"]["content"]
if content is None:
    content = ""
```
2. 在 `complete_multimodal()` 方法第 71 行后添加同样的 null 检查：
```python
content = body["choices"][0]["message"]["content"]
if content is None:
    content = ""
```

### 问题 4：llm_repair.py User Content 格式错误

**文件**：`/workspace/mmap_optimizer/analysis/llm_repair.py`

**修改内容**：
1. 添加 `import json`
2. 将第 13 行 `{"role": "user", "content": {"raw_text": raw_text}}` 改为：
```python
{"role": "user", "content": json.dumps({"raw_text": raw_text}, ensure_ascii=False)}
```

### 问题 5：TreeReduce Merge 缺少去重

**文件**：`/workspace/mmap_optimizer/patch/tree_reduce.py`

**修改内容**：在 `_merge_many()` 中增加文本去重，避免相同/相似内容重复拼接：

1. 导入已有的 `normalize_patch_text` 从 `deduplicate` 模块
2. 修改 `_merge_many()` 中的拼接逻辑，使用 `normalize_patch_text` 去重：
```python
def _merge_many(self, round_id: str, cluster: PatchCluster, patches: list[Patch]) -> Patch:
    first = patches[0]
    seen_texts: set[str] = set()
    text_lines = []
    for patch in patches:
        patch.status = "superseded"
        line = patch.patch_text.strip()
        # 去重：跳过与已有内容相同（归一化后）的 patch_text
        normalized = normalize_patch_text(line)
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)
        text_lines.append(line if line.startswith("-") else f"- {line}")
    # ... 后续不变
```

**不采用方案 A（接入 HierarchicalMerge）的原因**：
- `HierarchicalMerge` 使用独立的 `Patch` frozen dataclass（字段：id/target_prompt/section/operation/risk/content/metadata）
- `schema.Patch` 字段完全不同（id/type/status/target_prompt_type/base_version_id/section_id/operation_type/...）
- 两者不兼容，强行替换需要大量适配代码，得不偿失
- 在 `_merge_many()` 内部去重是最小改动、最大收益的方案

## 假设与决策

1. **问题 1**：`continue` 跳过缺失 sample 的分析，而非 raise 或创建空 record — 这是合理的，因为一个 sample 的缺失不应中断整个分析阶段
2. **问题 2**：栈匹配需要处理 JSON 字符串内的花括号（`"key": "value with {braces}"`），避免误匹配 — 这是比简单栈计数更健壮的实现
3. **问题 3**：`None` fallback 为空字符串 `""` 而非占位符 — 下游代码已能处理空字符串，且不会引入额外语义
4. **问题 4**：使用 `json.dumps(ensure_ascii=False)` 保留中文 — repair 场景中文内容常见
5. **问题 5**：使用已有的 `normalize_patch_text` 做去重 — 与 `deduplicate.py` 中 `is_duplicate_patch` 使用相同的归一化逻辑，保持一致性

## 验证步骤

1. 运行现有测试：`python -m pytest tests/ -x -q`
2. 检查 `runner.py` 中 `ModelClient` 导入是否恢复
3. 检查 `hint_generator.py` 中 `_extract_json_object` 是否正确处理嵌套 JSON
4. 检查 `openai_compatible.py` 中 null content fallback
5. 检查 `llm_repair.py` 中 content 格式
6. 检查 `tree_reduce.py` 中去重逻辑
