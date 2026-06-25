# 更新 prompt_standardization.txt 计划

## Summary

参考用户提供的 PROMPT_STANDARDIZATION_PROMPT，更新当前项目的 `prompts/prompt_standardization.txt`。用户版本采用固定的 7 段式标准结构，有详细的归类规则和边界处理，比当前版本更结构化、更严谨。同时需要适配代码中的占位符处理逻辑。

## Current State Analysis

### 当前 prompt_standardization.txt 的问题
1. **结构不固定**：只要求"使用 Markdown headers"，没有固定的段落结构
2. **归类规则缺失**：没有说明哪些内容应该放在哪个段落
3. **边界处理缺失**：没有空段处理、ICL 示例保护等
4. **语言不一致**：当前是英文，用户版本是中文（更贴合项目实际使用场景）

### 用户提供的版本的优势
1. **固定 7 段式结构**：Task Description、Core Instructions、Step-by-Step Reasoning Process、Constraints & Rules、Output Format、Examples、Additional Guidelines
2. **详细归类规则**：每段都有明确的归类规则
3. **边界处理**：空段写入固定文本、ICL 示例特殊保护
4. **严格约束**：零冗余原则、禁止二次创作、标题全局唯一

### 代码适配需求
当前 `prompt_structuring.py` 第 266-269 行：
```python
messages = [
    {"role": "system", "content": standardization_prompt},
    {"role": "user", "content": f"# Input Prompt\n\n{markdown}"},
]
```

用户版本的 prompt 末尾有 `{{original_prompt}}` 占位符（Input Container 部分），需要将原始 prompt 注入到 system prompt 中，而不是作为单独的 user message。

## Proposed Changes

### 1. 更新 `prompts/prompt_standardization.txt`

用用户提供的版本替换当前内容，保持中文，保留 7 段式结构和所有规则。占位符从 `{{original_prompt}}` 改为 `{original_prompt}` 以与项目中其他 prompt 的 Python format string 风格一致。

### 2. 修改 `mmap_optimizer/phases/prompt_structuring.py`

修改 `_standardize_with_model` 方法：
- 将 `{original_prompt}` 占位符替换为实际 markdown 文本
- 调整消息结构：将原始 prompt 注入 system prompt，user message 改为简短的触发指令

```python
# 读取标准化 prompt
standardization_prompt = Path(...).read_text(encoding="utf-8")

# 替换占位符
standardization_prompt = standardization_prompt.replace("{original_prompt}", markdown)

# 构建消息
messages = [
    {"role": "system", "content": standardization_prompt},
    {"role": "user", "content": "请开始标准化处理。"},
]
```

## Assumptions & Decisions

1. **占位符格式**：从 `{{original_prompt}}` 改为 `{original_prompt}`，与项目中其他 prompt 文件保持一致
2. **消息结构**：原始 prompt 注入 system prompt（因为有 `=== 原始提示词开始 ===` 容器标记），user message 改为简短触发指令
3. **MarkdownParser 兼容性**：7 段式结构使用 `##` 二级标题，当前 MarkdownParser 完全支持解析；`_is_output_schema` 方法会匹配 "## 5. Output Format" 并标记为 immutable

## Verification Steps

1. 运行 `python3 -m pytest tests/test_core.py -v` 确保现有测试通过
2. 验证占位符替换逻辑：`{original_prompt}` 被正确替换为实际 markdown
