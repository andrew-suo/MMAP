# TreeReduce Semantic Merge 增强方案

## 摘要

增强 TreeReduce `_merge_many()` 的语义合并能力，解决当前简单拼接导致的语义重复、矛盾未检测、冗余未合并等问题。

## 当前状态分析

### 数据流

```
round_runner.py:209  TreeReducePatchMerger().merge()  ← 确定性合并（当前问题所在）
round_runner.py:214  SemanticPatchProcessor.merge()    ← LLM 语义合并（默认关闭）
round_runner.py:218  SemanticPatchProcessor.root_audit() ← LLM 跨 section 审计（默认关闭）
```

### 关键发现

1. **`SemanticPatchProcessor` 已存在**（`patch/semantic.py`），具备 LLM 驱动的三维合并框架（结构隔离、逻辑去重、技术约束），但**默认关闭**（`patch_semantic_merge_enabled: bool = False`）
2. **`_merge_many()` 是 Semantic Merge 的前置步骤**：它先做确定性合并，产出 `merged_patch`，然后才交给 `SemanticPatchProcessor` 做语义合并
3. **`semantic.py:31` 有同样的 dict content bug**：`"content": {"patches": [...]}` 应为 `json.dumps()`
4. **`HierarchicalMerge` 的 Patch 类型不兼容**，不能直接替换（之前已确认）

### 问题根因

当前 `_merge_many()` 只做文本级拼接，即使后续 `SemanticPatchProcessor` 开启，其输入已经是低质量的拼接文本，LLM 难以从中提取原始语义。应该在 `_merge_many()` 中保留结构化信息，为下游语义合并提供更好的输入。

## 修改方案

### 方案：结构化拼接 + 修复 semantic.py + 默认开启语义合并

核心思路：`_merge_many()` 不做 LLM 调用（保持确定性），但将拼接格式从简单 bullet list 改为结构化格式，保留每个 patch 的 intent 和元信息，使下游 `SemanticPatchProcessor` 能更好理解。

#### 修改 1：`tree_reduce.py` — 结构化拼接

**文件**：`/workspace/mmap_optimizer/patch/tree_reduce.py`

**当前**：简单 bullet list
```python
text_lines.append(line if line.startswith("-") else f"- {line}")
patch_text="\n".join(text_lines)
```

**改为**：结构化拼接，每个 patch 保留 intent 描述
```python
text_lines.append(f"[{patch.intent_name}] {line}")
patch_text="\n".join(text_lines)
```

同时，将 `intent_description` 从固定的 `"Tree-reduced related patches"` 改为包含各 patch 的 intent 摘要：
```python
intent_descriptions = "; ".join(
    f"{patch.intent_name}: {patch.intent_description}" for patch in patches
)
```

#### 修改 2：`semantic.py` — 修复 dict content bug

**文件**：`/workspace/mmap_optimizer/patch/semantic.py`

第 31 行存在与 `llm_repair.py` 相同的 bug：
```python
# 当前（错误）
{"role": "user", "content": {"patches": [_patch_to_dict(p) for p in patches]}}
# 修复为
{"role": "user", "content": json.dumps({"patches": [_patch_to_dict(p) for p in patches]}, ensure_ascii=False)}
```

#### 修改 3：`config.py` — 默认开启语义合并

**文件**：`/workspace/mmap_optimizer/core/config.py`

将 `patch_semantic_merge_enabled` 默认值从 `False` 改为 `True`，使语义合并在标准流程中生效。

```python
# 当前
patch_semantic_merge_enabled: bool = False
# 改为
patch_semantic_merge_enabled: bool = True
```

#### 修改 4：`round_runner.py` — 为 SemanticPatchProcessor 传入未合并的 patches

**文件**：`/workspace/mmap_optimizer/orchestration/round_runner.py`

当前 `SemanticPatchProcessor.merge()` 接收的是 `TreeReduce` 合并后的 patches（`merged_patches`），这些 patches 的 `patch_text` 已经是拼接后的文本。为了让语义合并更有效，应该在 `extra` 字段中保留原始 patch 列表，供 `SemanticPatchProcessor` 参考。

在 `TreeReducePatchMerger.merge()` 返回的 merged patch 的 `extra` 中已包含 `merged_from_patch_ids`。在 `_merge_many()` 中额外保留原始 patch_texts：
```python
extra={
    "merged_from_patch_ids": [patch.id for patch in patches],
    "original_patch_texts": [patch.patch_text.strip() for patch in patches],
}
```

### 不做的改动

1. **不在 `_merge_many()` 中调用 LLM**：保持确定性，LLM 调用由 `SemanticPatchProcessor` 负责
2. **不替换为 HierarchicalMerge**：Patch 类型不兼容
3. **不修改 `SemanticPatchProcessor` 的 prompt 模板**：现有三维合并框架已足够好，只需确保输入质量

## 假设与决策

1. **结构化拼接格式**：使用 `[intent_name] patch_text` 格式，而非 JSON — 保持可读性，同时为 LLM 提供结构信息
2. **默认开启语义合并**：语义合并是提升质量的关键，应默认开启；用户可通过配置关闭
3. **保留 `root_audit` 默认关闭**：跨 section 审计开销较大，用户按需开启
4. **修复 `semantic.py` 的 dict content bug**：与 `llm_repair.py` 同类问题，必须修复才能让语义合并正常工作

## 验证步骤

1. 运行全量测试：`python -m pytest tests/ -x -q`
2. 验证 `tree_reduce.py` 结构化拼接输出格式
3. 验证 `semantic.py` content 格式正确
4. 验证 `config.py` 默认值变更
5. 验证 `round_runner.py` 中语义合并流程正常
