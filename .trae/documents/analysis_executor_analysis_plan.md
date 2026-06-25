# AnalysisExecutor 实现逻辑分析

## 一、定位

`AnalysisExecutor` 是 MMAP Optimizer 中的**真实分析执行器**，负责对 `ExtractionResult` 进行分析，判断抽取结果是否正确，并生成 patch 建议。它在 `ExtractionPromptOptimizationStage` 的 Step 3 中被调用。

**文件位置**: [analysis_executor.py](file:///Users/andrew/project/MMAP/MMAP/mmap_optimizer/executors/analysis_executor.py)

---

## 二、核心职责

| 职责 | 说明 |
|------|------|
| **判断正误** | 比较 extraction result 与 ground truth，判断抽取是否正确 |
| **生成 patch 建议** | 当 extraction 错误且 analysis 正确识别时，生成 patch_suggestion |
| **支持反思** | 对 analysis 错误的样本进行反思，生成 ReflectionResult |

---

## 三、对外接口

### 3.1 初始化

```python
def __init__(
    self,
    model_client: ModelClient,
    model_config: dict[str, Any] | None = None,
    primary_answer_fields: list[str] | None = None,  # ["result"] 默认
    label_mapping: dict[str, Any] | None = None,  # 标签归一化映射
    analysis_task_template_path: str | None = None,  # prompts/analysis_task.txt
    analysis_reflection_template_path: str | None = None,  # prompts/analysis_reflection.txt
)
```

### 3.2 核心方法

| 方法 | 用途 |
|------|------|
| `execute()` | 对单个样本执行 analysis |
| `execute_batch()` | 对 batch 中所有样本执行 analysis |
| `reflect()` | 对分析错误的样本进行反思 |

---

## 四、执行流程（execute）

```
输入: analysis_prompt, extraction_prompt, extraction_result, sample_spec
       ↓
_build_analysis_messages()  # 构建 system + user 消息
       ↓
model_client.complete()  # 调用大模型
       ↓
_parse_judgement()  # 解析 JSON 输出（带修复回退）
       ↓
_compute_actual_correct()  # 实际正误判断
       ↓
_extract_analysis_judgement()  # 模型判断
       ↓
比较 actual_correct 与 analysis_judgement
       ↓
_extract_error_reason() / _build_patch_suggestion()
       ↓
返回 AnalysisResult
```

---

## 五、关键设计点

### 5.1 双源正误判断

**Actual Correct（实际正误）**：
```python
def _compute_actual_correct(self, extraction_result, ground_truth):
    # 遍历 primary_answer_fields
    # 比较 parsed_output[field] 与 ground_truth[field]
    # 通过 normalize_label 归一化后比较
    return pred == gt
```

**Analysis Judgement（模型判断）**：
```python
def _extract_analysis_judgement(self, judgement):
    # 优先取 is_correct
    # 备选 extraction_correct
    # 备选 judgement 字段（支持 "correct"/"wrong" 字符串）
```

**一致性计算**：
```python
analysis_correct = (analysis_judged == actual_correct) if analysis_judged is not None else False
```

### 5.2 Patch Suggestion 生成条件

```python
if not actual_correct and analysis_correct:
    # 只有当：抽取确实错误 + 分析正确识别 → 生成 patch_suggestion
    patch_suggestion = self._build_patch_suggestion(judgement, error_reason)
```

**优先级**：
1. judgement 中有 `patch_suggestion` → 直接使用
2. 否则基于 `error_reason` 构造默认 patch

### 5.3 标签归一化（normalize_label）

通过 `label_mapping` 实现标签映射，例如：
```python
{"OK": "CORRECT", "NG": "INCORRECT", "PASS": "CORRECT"}
```

### 5.4 消息构建（_build_analysis_messages）

**System Message**: 渲染后的 analysis prompt
**User Message**: 
- Extraction Prompt（参考）
- Extraction Result（sample_id, status, raw_output, parsed_output, error_details）
- Sample Input + Metadata
- Ground Truth
- Task 描述

**支持两种构建方式**：
1. **模板方式**：使用 `analysis_task_template_path` + `render_prompt()`
2. **硬编码方式**：代码动态拼接

### 5.5 输出解析（_parse_judgement）

```python
def _parse_judgement(self, raw_output):
    # 1. 直接 JSON 解析
    try: parsed = json.loads(raw_output)
    # 2. 解析失败 → 修复
    if model_client is not None:
        repaired, status = repair_json_output(raw_output, expected_schema, model_client)
        if status == "repaired":
            return repaired
    # 3. 修复失败 → 返回空 dict
    return {}
```

**expected_schema**:
```python
{
    "is_correct": bool,
    "error_reason": str | None,
    "patch_suggestion": dict | None,
}
```

### 5.6 反思功能（reflect）

**触发场景**：当 analysis 自身判断错误时（`analysis_correct == False`）

**流程**：
```
输入: analysis_prompt, extraction_result, analysis_result, sample_spec
       ↓
_build_reflection_messages()  # 包含 analysis_result 上下文
       ↓
model_client.complete()
       ↓
_parse_judgement()
       ↓
提取 error_reason / patch_suggestion / notes
       ↓
返回 ReflectionResult
```

**特殊处理**：如果模型没有返回 patch_suggestion，使用默认值：
```python
{
    "target_section": "section_1",
    "operation": "replace",
    "content": error_reason,
    "rationale": f"reflection for sample {sample_id}",
}
```

---

## 六、数据结构

### 6.1 AnalysisResult

```python
@dataclass
class AnalysisResult:
    sample_id: str
    judgement: dict[str, Any]  # 模型原始输出解析结果
    analysis_correct: bool  # 模型判断与实际是否一致
    error_reason: str | None
    patch_suggestion: dict[str, Any] | None
```

### 6.2 ReflectionResult（在 analysis_prompt_optimization.py）

```python
@dataclass
class ReflectionResult:
    sample_id: str
    reflection_success: bool
    error_reason: str | None
    patch_suggestion: dict[str, Any] | None
    notes: list[str]
```

---

## 七、核心辅助方法

| 方法 | 职责 |
|------|------|
| `_compute_actual_correct` | 基于 ground_truth 计算实际正确性 |
| `_extract_analysis_judgement` | 从 judgement dict 提取 is_correct |
| `_extract_error_reason` | 提取 error_reason（兼容多种 key） |
| `_extract_patch_suggestion` | 提取 patch_suggestion |
| `_extract_notes` | 提取 notes（支持 list 或 str） |
| `_build_patch_suggestion` | 构造或回退 patch_suggestion |

---

## 八、设计特点

1. **多源信息融合**：结合 `primary_answer_fields`、`label_mapping` 等配置灵活处理不同业务场景
2. **健壮性优先**：JSON 解析失败有修复回退，关键字段提取支持多种 key
3. **正误双向校验**：actual vs judgement 对比，避免模型幻觉
4. **反思机制**：对 analysis 错误进行二次分析，形成闭环
5. **可配置模板**：支持通过文件配置 user message 内容
6. **解耦设计**：通过 ModelClient 抽象，不依赖具体模型

---

## 九、在 Stage 中的使用

**Stage**: `ExtractionPromptOptimizationStage`

**Step 3 流程**：
```python
def _step3_analyze_results(self):
    if self.analysis_executor is not None:
        self.analysis_results = self.analysis_executor.execute_batch(
            analysis_prompt=self.analysis_prompt,
            extraction_prompt=self.extraction_prompt,
            extraction_results=self.base_extraction_results,
            sample_set=self.sample_set,
        )
        # ... 更新 trace 和 state
```

**输出流向**：
- `analysis_results` → Step 4 (Patch Generation) 作为输入
- `analysis_results` 还会触发 `reflect()` 当 `analysis_correct == False`

---

## 十、关键代码行号速查

| 功能 | 行号 |
|------|------|
| 类定义 | 23 |
| execute() | 43-77 |
| execute_batch() | 79-95 |
| reflect() | 97-138 |
| _build_analysis_messages() | 140-231 |
| _build_reflection_messages() | 233-305 |
| _parse_judgement() | 307-344 |
| _compute_actual_correct() | 346-360 |
| _extract_analysis_judgement() | 362-384 |
| _extract_error_reason() | 386-396 |
| _extract_patch_suggestion() | 398-407 |
| _extract_notes() | 409-418 |
| _build_patch_suggestion() | 420-435 |