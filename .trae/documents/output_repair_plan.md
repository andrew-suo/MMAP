# Output Repair 功能设计方案

## 一、需求分析

当模型输出结果不能正常解析时（如 JSON 格式错误），提供一个通用功能函数调用模型进行结果修复。该函数需要：
- 放在通用位置，支持多个模块调用
- 在 ExtractionExecutor 和 AnalysisExecutor 中集成

## 二、设计决策

| 决策项 | 选择 |
|--------|------|
| 模块位置 | `mmap_optimizer/prompt/output_repair.py`（新模块） |
| 集成方式 | 在 ExtractionExecutor 和 AnalysisExecutor 中都集成 |

## 三、实现步骤

### 步骤 1：创建 prompt 文件
创建 `prompts/output_repair.txt`，包含修复指南和示例

### 步骤 2：实现修复函数
创建 `mmap_optimizer/prompt/output_repair.py`

函数签名：
```python
def repair_json_output(
    raw_output: str,
    expected_schema: dict | None,
    model_client: ModelClient,
    model_config: dict | None = None,
    repair_prompt_path: str = "prompts/output_repair.txt",
) -> tuple[dict | None, str]:
```

### 步骤 3：更新 prompt/__init__.py
导出新模块

### 步骤 4：集成到 ExtractionExecutor
修改 `_parse_output()` 方法，解析失败时调用修复函数

### 步骤 5：集成到 AnalysisExecutor
修改 `_parse_judgement()` 方法，解析失败时调用修复函数

## 四、Output Repair Prompt 设计

```
# Role
You are an Output Repair Expert. Your task is to fix malformed model outputs.

# Goal
Given a malformed output and expected schema, repair it to valid format.

# Requirements
1. Extract valid information from the malformed output
2. Fill missing required fields with reasonable defaults
3. Fix JSON syntax errors (missing quotes, trailing commas, etc.)
4. Do NOT fabricate or hallucinate new information
5. If the output is completely unparseable, return null

# Output Format
Respond with ONLY the repaired JSON object. Do not include any explanation or markdown formatting.

# Example
Input malformed output: {result: "OK", confidence: 0.95}
Expected schema: {"result": "CORRECT"|"INCORRECT"|"UNCERTAIN", "confidence": float, "evidence": list}

Repaired output:
{"result": "OK", "confidence": 0.95, "evidence": []}
```

## 五、测试验证

1. 正常 JSON 输入 - 直接返回
2. 缺失引号的 JSON - 修复后返回
3. 多余逗号 - 修复后返回
4. 完全无效输入 - 返回 None, "unrepairable"

## 六、文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `prompts/output_repair.txt` | 新增 | 输出修复系统提示词 |
| `mmap_optimizer/prompt/output_repair.py` | 新增 | 修复函数实现 |
| `mmap_optimizer/prompt/__init__.py` | 修改 | 导出新模块 |
| `mmap_optimizer/executors/extraction_executor.py` | 修改 | 集成修复逻辑 |
| `mmap_optimizer/executors/analysis_executor.py` | 修改 | 集成修复逻辑 |