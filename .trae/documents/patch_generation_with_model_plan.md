# Patch Generation 基于模型生成方案

## 一、需求分析

用户希望 patch 的生成不再通过代码逻辑合成，而是调用模型来生成。输入包括：

1. **Extraction Patch**：基于分析结果（原抽取结果、分析过程、分析结果、GT）
2. **Analysis Patch**：基于反思结果（analysis的完整分析结果和反思结果）

生成 patch 的 prompt 需要放在 `prompts/` 目录中。

## 二、当前实现分析

### 2.1 当前 Extraction Patch 生成逻辑

```python
# patch_generation_executor.py
def _compose_extraction_patch_content(self, error_reason, confirmed_facts, hypothesized_error_causes):
    # 纯代码合成，不调用模型
    content = error_reason  # 直接用 error_reason
    rationale = " | ".join([error_reason, causes, facts])
    return content, rationale
```

**问题**：
- 只是简单拼接文本，没有真正理解问题本质
- 无法生成针对性的修复建议
- 无法自动选择正确的 section 和 operation

### 2.2 当前 Analysis Patch 生成逻辑

```python
def generate_analysis_patches(self, reflection_results, analysis_prompt, sample_set):
    # 直接使用 reflection_result.patch_suggestion
    suggestion = dict(reflection.patch_suggestion)
    patch = self._build_patch_from_suggestion(sample_id, suggestion, ...)
```

**问题**：
- 依赖 reflection 阶段生成的 patch_suggestion
- 没有独立的 patch 生成模型调用
- 缺少对 patch 内容的验证和优化

## 三、方案设计

### 3.1 新增 Prompt 文件

**`prompts/patch_generation.txt`**：Patch 生成系统提示词

功能：
- 角色：Patch Generation Expert
- 输入：分析结果（抽取结果、分析过程、分析结果、GT）或反思结果
- 输出：结构化的 patch suggestion（包含 target_section、operation、content、rationale）
- 要求：
  - 根据错误原因生成具体的修复方案
  - 选择合适的 section（优先 mutable section）
  - 选择合适的 operation（append/replace/insert/delete）
  - 生成高质量的 patch content（针对性、可操作性、安全性）

### 3.2 修改 PatchGenerationExecutor

新增方法：
- `generate_extraction_patches_with_model()`：调用模型生成 extraction patch
- `generate_analysis_patches_with_model()`：调用模型生成 analysis patch

修改构造函数：
- 增加 `model_client` 参数
- 增加 `patch_generation_prompt_path` 参数

修改 `generate_extraction_patches()`：
- 支持两种模式：代码合成（当前）和模型生成（新）
- 默认使用模型生成模式

### 3.3 更新配置

在 `PromptsConfig` 中增加 `patch_generation` 字段：
```python
@dataclass
class PromptsConfig:
    extraction: str = "prompts/extraction.txt"
    analysis: str = "prompts/analysis.txt"
    analysis_task: str = "prompts/analysis_task.txt"
    analysis_reflection: str = "prompts/analysis_reflection.txt"
    prompt_standardization: str = "prompts/prompt_standardization.txt"
    patch_generation: str = "prompts/patch_generation.txt"  # 新增
```

### 3.4 更新 Factory

在 `create_executors()` 中：
- 传递 `model_client` 给 `PatchGenerationExecutor`
- 传递 `patch_generation_prompt_path` 给 `PatchGenerationExecutor`

## 四、详细实现

### 4.1 新增 prompts/patch_generation.txt

```markdown
# Role: Patch Generation Expert

You are an expert at generating high-quality prompts patches. Based on the analysis results, you need to generate specific, actionable patch suggestions to fix the issues identified.

## Input

You will receive:
1. **Extraction Result**: The raw output and parsed output from the extraction stage
2. **Analysis Result**: The analysis judgment, confirmed facts, and hypothesized error causes
3. **Ground Truth**: The expected correct output
4. **Current Prompt**: The current extraction/analysis prompt (for reference)

## Output Format

You MUST output a JSON object with the following structure:

```json
{
  "patch_suggestions": [
    {
      "target_section": "section_1",
      "operation": "append",
      "content": "具体的修复内容",
      "rationale": "修复理由和预期效果",
      "risk_level": "low"
    }
  ]
}
```

## Operation Types

- **append**: Add new content to the end of the section
- **replace**: Replace the entire section content
- **insert**: Insert content at a specific position
- **delete**: Delete the section or specific content

## Quality Standards

1. **Targeted**: The patch should directly address the identified error
2. **Actionable**: The patch should be clear and implementable
3. **Safe**: The patch should not introduce new issues
4. **Conservative**: Prefer append over replace when possible
5. **Concise**: Keep the patch content focused

## Rules

1. Only target mutable sections (avoid schema/format sections)
2. Generate at most 3 patch suggestions per sample
3. Provide clear rationale for each patch
4. Estimate the risk level (low/medium/high)
```

### 4.2 修改 PatchGenerationExecutor

```python
class PatchGenerationExecutor:
    def __init__(
        self,
        model_client: Any = None,
        model_config: dict[str, Any] | None = None,
        patch_generation_prompt_path: str = "prompts/patch_generation.txt",
        patch_validator: PatchValidator | None = None,
    ):
        self.model_client = model_client
        self.model_config = model_config or {}
        self.patch_generation_prompt_path = patch_generation_prompt_path
        self.patch_validator = patch_validator or PatchValidator()
        self.renderer = StructuredPromptRenderer()
    
    def generate_extraction_patches(
        self,
        analysis_results: list[AnalysisResult],
        extraction_results: list[ExtractionResult],
        extraction_prompt: StructuredPrompt,
        sample_set: SampleSet,
        use_model: bool = True,  # 新增参数
    ) -> tuple[list[ExtractionPatch], list[ExtractionPatch], list[ExtractionPatch]]:
        if use_model and self.model_client:
            return self._generate_extraction_patches_with_model(
                analysis_results, extraction_results, extraction_prompt, sample_set
            )
        # 回退到代码合成模式
        return self._generate_extraction_patches_by_code(
            analysis_results, extraction_results, extraction_prompt, sample_set
        )
    
    def _generate_extraction_patches_with_model(self, ...):
        # 调用模型生成 patch
        # 1. 加载 patch_generation_prompt
        # 2. 构建用户消息（包含 extraction_result、analysis_result、ground_truth、prompt）
        # 3. 调用 model_client.complete()
        # 4. 解析模型输出
        # 5. 构建 patch 对象
        # 6. 校验并返回
    
    def _generate_extraction_patches_by_code(self, ...):
        # 当前的代码合成逻辑，保持不变
```

### 4.3 更新配置和 Factory

**config.py**:
```python
@dataclass
class PromptsConfig:
    extraction: str = "prompts/extraction.txt"
    analysis: str = "prompts/analysis.txt"
    analysis_task: str = "prompts/analysis_task.txt"
    analysis_reflection: str = "prompts/analysis_reflection.txt"
    prompt_standardization: str = "prompts/prompt_standardization.txt"
    patch_generation: str = "prompts/patch_generation.txt"  # 新增
```

**factory.py**:
```python
def create_executors(config, use_mock=None):
    # ... 现有代码 ...
    patch_generation_prompt_path = prompts_config.get("patch_generation")
    
    patch_generation_executor = PatchGenerationExecutor(
        model_client=model_client if use_real else None,
        model_config=optimizer_model_config,
        patch_generation_prompt_path=patch_generation_prompt_path,
    )
    
    return {
        # ...
        "patch_generation": patch_generation_executor,
        # ...
    }
```

## 五、文件修改清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `prompts/patch_generation.txt` | 新增 | Patch 生成系统提示词 |
| `mmap_optimizer/executors/patch_generation_executor.py` | 修改 | 增加模型调用逻辑 |
| `mmap_optimizer/core/config.py` | 修改 | PromptsConfig 增加 patch_generation 字段 |
| `mmap_optimizer/executors/factory.py` | 修改 | 传递 model_client 和 prompt_path |
| `mmap_optimizer/core/cli.py` | 修改 | 增加 --patch-generation-prompt 参数 |
| `mmap_optimizer/core/runner.py` | 修改 | 确保配置正确传递 |

## 六、风险处理

1. **模型不可用**：当 `model_client` 为 None 时回退到代码合成模式
2. **输出解析失败**：使用 `repair_json_output` 修复，失败则跳过该样本
3. **生成的 patch 无效**：通过 `PatchValidator` 校验，无效 patch 标记为 rejected
4. **性能问题**：每次 patch 生成需要调用模型，可能增加耗时

## 七、验证步骤

1. 运行单元测试：`python3 tests/test_core.py`
2. 验证配置加载：确保 `patch_generation` 配置正确加载
3. 验证 executor 创建：确保 factory 正确传递参数
4. 验证模型调用：确保 model_client 正确调用
