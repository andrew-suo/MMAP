# Patch Generation Prompt 改造计划

## 概述

参考用户提供的两个prompt（`PATCH_GENERATION_PROMPT` 和 `EVAL_PATCH_GENERATION_PROMPT`），改造当前项目的 patch 生成 prompt 和相关代码。

## 两个参考 Prompt 差异分析

### 共同点（占 80%+）
- 相同的 7 种 patch 操作（append_to_section, insert_after, insert_before, replace_in_section, replace_section, add_after_section, delete_section）
- 相同的输出格式 `{patches: [...], cited_sections: [...]}`
- 相同的"成功即静默"规则（CORRECT → 空数组）
- 相同的核心任务：基于错误分析生成结构化 patch
- 都需要 prompt_structure 和 current_prompt 作为输入

### 差异点

| 维度 | PATCH_GENERATION_PROMPT | EVAL_PATCH_GENERATION_PROMPT |
|---|---|---|
| 角色 | Prompt 优化专家 | 评估逻辑优化专家 |
| 额外输入 | 无 | `eval_blind_context`（盲评上下文） |
| 策略数量 | 4条（具体化、匹配频率、保留有效、提升简洁） | 3条（具体化、拦截高频、对齐真值） |
| 分析结构 | Diagnostic Analysis + Modification Strategies | Core Strategies + Workflow Steps |
| 独有策略 | Preserve What Works、Improve Conciseness | Align to Ground Truth |

### 结论：合并为一个 Prompt

两个 prompt 80%+ 内容相同，差异仅在角色描述和少量策略。合并方案：
- 统一角色为"Prompt 优化专家"
- 合并所有策略（去重后 6 条：具体化、匹配频率、保留有效、提升简洁、拦截高频、对齐真值）
- 统一 Workflow（检查状态 → 根因分析 → 确定操作）
- 通过 `prompt_type` 字段区分 extraction/analysis 场景
- 盲评上下文作为可选输入

## 当前问题分析

### 1. operation_type 三方不一致
| 来源 | 支持的 operation_type |
|---|---|
| `patch_generation.txt` | `append`, `replace`, `insert`, `delete` |
| `types.py` Literal | `replace`, `insert_before`, `insert_after`, `delete` |
| `patch_apply_executor.py` | `replace`, `append`, `delete` |

### 2. Patch 数据结构缺少新操作所需字段
参考 prompt 的操作需要额外字段：
- `insert_after`/`insert_before`：需要 `target_text`（定位文本）
- `replace_in_section`：需要 `old_text`、`new_text`
- `add_after_section`：需要 `new_header`

### 3. Prompt 内容过于简单
缺少诊断分析、修改策略、"成功即静默"规则、prompt 结构上下文。

## 修改方案

### Step 1: 重写 `prompts/patch_generation.txt`（合并为一个）

吸收两个参考 prompt 的精华，包含：

```
# Role
你是一位顶级的 Prompt 优化专家。你的核心任务是根据当前提示词在具体测试用例中的执行结果，深度分析其成功或失败的原因，并严格按照规则生成结构化的 JSON Patch 来迭代优化该提示词。

# 1. Input Context
## 当前提示词结构 (Prompt Structure)
{prompt_structure}

## 当前提示词全文 (Current Prompt)
{current_prompt}

## 案例执行情况
- Sample ID: {sample_id}
- Status: {status}
- Error/Evaluation Reason: {reason}
- Extracted Result: {result_content}
- Ground Truth: {ground_truth}
{blind_context}

# 2. Diagnostic Analysis
- 如果 Status 为 FAIL/INCORRECT：定位 Current Prompt 中哪一部分指令缺失、模糊或存在误导
- 如果 Status 为 PASS/CORRECT：分析起关键作用的指令，此时绝对不需要修改提示词

# 3. Modification Strategies
1. Be Specific（指令具体化）
2. Match Specificity to Failure Frequency（匹配错误频率）
3. Preserve What Works（保留有效内容）
4. Improve Conciseness（提升简洁度）
5. Tighten on Recurring Errors（拦截高频错误）
6. Align to Ground Truth（强行对齐真值）

# 4. Patch Operations & Rules
| op | 必需字段 | 说明 |
|---|---|---|
| append_to_section | target_section, content | 在章节末尾追加（最推荐） |
| insert_after | target_section, target_text, content | 在指定文本之后插入 |
| insert_before | target_section, target_text, content | 在指定文本之前插入 |
| replace_in_section | target_section, old_text, new_text | 替换章节中的文本（old_text 必须逐字匹配） |
| replace_section | target_section, content | 完全重写整个章节 |
| add_after_section | target_section, new_header, content | 在目标章节后新增章节 |
| delete_section | target_section | 删除整个章节 |

# 5. Critical Rules
1. 成功即静默：PASS/CORRECT 时必须输出空数组
2. 操作偏置：优先 append_to_section，避免 replace_in_section
3. 保护区限制：[PROTECTED] section 严禁内部编辑
4. 精确 target_section：必须与 Prompt Structure 中的名称一字不差

# 6. Output Format
{patches: [...], cited_sections: [...]}
```

### Step 2: 修改 `mmap_optimizer/patch/types.py`

#### 2.1 更新 operation_type Literal
```python
operation_type: Literal[
    "append_to_section",
    "insert_after",
    "insert_before",
    "replace_in_section",
    "replace_section",
    "add_after_section",
    "delete_section",
]
```

#### 2.2 新增可选字段
在 `ExtractionPatch` 和 `AnalysisPatch` 中添加：
```python
target_text: str | None = None      # insert_after/insert_before 定位文本
old_text: str | None = None         # replace_in_section 旧文本
new_text: str | None = None         # replace_in_section 新文本
new_header: str | None = None       # add_after_section 新章节标题
```

同步更新 `to_dict()` 和 `from_dict()` 方法。

### Step 3: 修改 `mmap_optimizer/executors/patch_apply_executor.py`

将 apply 方法中的操作处理从 3 种扩展到 7 种：

```python
if op == "append_to_section":
    section.content = section.content + "\n" + patch.content
elif op == "replace_section":
    section.content = patch.content
elif op == "delete_section":
    if self.allow_delete:
        section.content = ""
    else: ... # reject
elif op == "insert_after":
    if patch.target_text and patch.target_text in section.content:
        section.content = section.content.replace(
            patch.target_text, patch.target_text + "\n" + patch.content, 1
        )
    else: ... # reject: target_text not found
elif op == "insert_before":
    if patch.target_text and patch.target_text in section.content:
        section.content = section.content.replace(
            patch.target_text, patch.content + "\n" + patch.target_text, 1
        )
    else: ... # reject
elif op == "replace_in_section":
    if patch.old_text and patch.old_text in section.content:
        section.content = section.content.replace(
            patch.old_text, patch.new_text or "", 1
        )
    else: ... # reject: old_text not found
elif op == "add_after_section":
    # 在 sections 列表中找到 target section 的位置，在其后插入新 section
    new_section = PromptSection(
        id=f"{section.id}_patch_{patch.id}",
        title=patch.new_header or "New Section",
        level=section.level,
        content=patch.content,
        mutable=True,
    )
    # 需要在父列表中插入
    ... # 实现插入逻辑
else: ... # reject: unknown operation
```

### Step 4: 修改 `mmap_optimizer/executors/patch_generation_executor.py`

#### 4.1 修改 `_build_patch_generation_user_message`
- 新增 `prompt_structure`：列出所有 section 的 id、title、level、mutable 状态
- 移除末尾的 Task 指令（已在 system prompt 中定义）
- extraction 场景：包含 extraction result、analysis result（分析过程和结果）、GT
- analysis 场景：包含 reflection result、analysis 完整结果、GT、盲评上下文

#### 4.2 修改 `_call_patch_generation_model`
- 解析输出改为 `{patches, cited_sections}` 格式

#### 4.3 修改 `_build_patch_from_suggestion`
- 从 `patches` 数组构建 patch（而非 `patch_suggestions`）
- 映射新字段：`target_text`、`old_text`、`new_text`、`new_header`
- 将 `cited_sections` 存入 `patch.metadata`
- operation_type 直接使用模型输出的操作名（已是合法值）

#### 4.4 修改回退模式（by_code）
- operation_type 改为 `append_to_section`（与新 types.py 对齐）

### Step 5: 修改 `mmap_optimizer/core/config.py`

`PromptsConfig` 保持 `patch_generation` 字段不变（因为合并为一个 prompt）：
```python
patch_generation: str = "prompts/patch_generation.txt"
```
无需拆分。

### Step 6: `factory.py` 和 `cli.py`
无需修改（prompt 路径字段名不变）。

## 涉及文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `prompts/patch_generation.txt` | 重写 | 合并两个参考 prompt 为一个 |
| `mmap_optimizer/patch/types.py` | 修改 | 更新 operation_type Literal，新增 4 个可选字段 |
| `mmap_optimizer/executors/patch_apply_executor.py` | 修改 | 支持 7 种操作 |
| `mmap_optimizer/executors/patch_generation_executor.py` | 修改 | 新输出格式、prompt 结构上下文、新字段映射 |
| `mmap_optimizer/core/config.py` | 不变 | 字段名不变 |
| `mmap_optimizer/executors/factory.py` | 不变 | 无需修改 |
| `mmap_optimizer/core/cli.py` | 不变 | 无需修改 |

## 验证步骤

1. 导入测试：`python3 -c "from mmap_optimizer.executors.factory import create_executors; ..."`
2. 配置验证：确认 PromptsConfig 字段正确
3. operation_type 一致性：types.py 与 patch_apply_executor.py 支持的操作完全一致
4. 验证 patch_apply_executor 能正确处理所有 7 种操作
