# Prompt 统一管理方案

## 目标

将项目中所有大模型 Prompt 统一集中到 `prompts/` 目录管理，便于后续维护和扩展。

## 当前状态分析

### 已有静态 Prompt 文件

| 文件路径                     | 用途                 | 使用位置               |
| ------------------------ | ------------------ | ------------------ |
| `prompts/extraction.txt` | Extraction 任务系统提示词 | CLI 参数传入，Runner 使用 |
| `prompts/analysis.txt`   | Analysis 任务系统提示词   | CLI 参数传入，Runner 使用 |

### 代码中硬编码的动态消息模板

| 位置                                           | 用途                | 硬编码内容         |
| -------------------------------------------- | ----------------- | ------------- |
| `executors/analysis_executor.py` 第 134-198 行 | Analysis 任务消息构建   | 分析任务描述、输出格式要求 |
| `executors/analysis_executor.py` 第 200-257 行 | Reflection 任务消息构建 | 反思任务描述、输出格式要求 |

### 模型调用入口与 Prompt 对应关系

| 调用入口                                       | System Prompt             | User Prompt  |
| ------------------------------------------ | ------------------------- | ------------ |
| `ExtractionExecutor.complete_multimodal()` | extraction.txt            | 动态构建（样本输入）   |
| `FewshotExecutor.execute_extraction()`     | extraction.txt + few-shot | 动态构建（样本输入）   |
| `AnalysisExecutor.execute()`               | analysis.txt              | 动态构建（分析任务消息） |
| `AnalysisExecutor.reflect()`               | analysis.txt              | 动态构建（反思任务消息） |

## 设计方案

### 1. 目录结构规划

```
prompts/
├── extraction.txt              # 已有：Extraction 任务系统提示词
├── analysis.txt                # 已有：Analysis 任务系统提示词
├── analysis_task.txt           # 新增：Analysis 任务消息模板
├── analysis_reflection.txt     # 新增：Analysis 反思消息模板
└── README.md                   # 新增：Prompt 目录说明文档
```

### 2. 新增 Prompt 管理模块

创建 `mmap_optimizer/prompt/prompt_manager.py`：

* **功能**：统一加载和管理所有 prompt 文件

* **核心方法**：

  * `load_prompt(path)` - 加载单个 prompt 文件

  * `load_all_prompts(config)` - 根据配置加载所有 prompt

  * `render_prompt(template_name, **kwargs)` - 渲染带变量的模板

### 3. 配置扩展

在 `core/config.py` 的 `RefactoredConfig` 中增加 `prompts` 配置段：

```python
@dataclass
class PromptsConfig:
    extraction: str = "prompts/extraction.txt"
    analysis: str = "prompts/analysis.txt"
    analysis_task: str = "prompts/analysis_task.txt"
    analysis_reflection: str = "prompts/analysis_reflection.txt"
```

### 4. 消息模板设计

#### analysis\_task.txt 模板

```
# Extraction Prompt (for reference)
{extraction_prompt}

# Extraction Result
sample_id: {sample_id}
status: {status}
raw_output: {raw_output}
parsed_output: {parsed_output}
{error_details}

# Sample Input
{sample_input}

# Sample Metadata
{sample_metadata}

# Ground Truth
{ground_truth}

# Task
Analyze whether the extraction result is correct against the ground truth.
Respond with a JSON object containing:
- "is_correct": boolean indicating whether the extraction result is correct
- "error_reason": string or null, the reason if the extraction is incorrect
- "patch_suggestion": object or null, suggested patch with keys "target_section", "operation", "content"
```

#### analysis\_reflection.txt 模板

```
# Extraction Result
sample_id: {sample_id}
raw_output: {raw_output}
parsed_output: {parsed_output}
status: {status}

# Analysis Result (to reflect on)
judgement: {judgement}
analysis_correct: {analysis_correct}
error_reason: {error_reason}

# Sample Input
{sample_input}

# Ground Truth
{ground_truth}

# Task
The analysis above misjudged the extraction result. 
Reflect on why the analysis was wrong and how to fix the analysis prompt.
Respond with a JSON object containing:
- "error_reason": why the analysis misjudged the extraction correctness
- "patch_suggestion": suggested fix to the analysis prompt with keys "target_section", "operation", "content"
- "notes": list of additional observations
```

### 5. 修改 AnalysisExecutor

将硬编码的消息构建逻辑替换为从模板文件加载：

```python
# 修改前：硬编码消息构建
def _build_analysis_messages(self, ...):
    user_parts = []
    user_parts.append("# Extraction Prompt (for reference)")
    ...

# 修改后：从模板文件加载并渲染
def _build_analysis_messages(self, ...):
    template = self.prompt_manager.load_prompt("analysis_task")
    user_content = template.format(
        extraction_prompt=extraction_prompt_text,
        sample_id=extraction_result.sample_id,
        ...
    )
```

### 6. CLI 和 Runner 更新

* **CLI**：增加 `--analysis-task-prompt` 和 `--analysis-reflection-prompt` 参数

* **Runner**：接收新的 prompt 配置，传递给 AnalysisExecutor

## 实施步骤

### 阶段一：创建新文件

1. 创建 `prompts/analysis_task.txt` - Analysis 任务消息模板
2. 创建 `prompts/analysis_reflection.txt` - Analysis 反思消息模板
3. 创建 `prompts/README.md` - Prompt 目录说明文档
4. 创建 `mmap_optimizer/prompt/prompt_manager.py` - Prompt 管理模块

### 阶段二：修改配置模块

1. 修改 `mmap_optimizer/core/config.py` - 增加 `PromptsConfig` 配置段

### 阶段三：修改分析执行器

1. 修改 `mmap_optimizer/executors/analysis_executor.py` - 使用模板文件替换硬编码消息

### 阶段四：更新 CLI 和 Runner

1. 修改 `mmap_optimizer/core/cli.py` - 增加新的 prompt 参数
2. 修改 `mmap_optimizer/core/runner.py` - 传递新的 prompt 配置

### 阶段五：验证

1. 运行测试验证修改正确性

## 潜在风险与注意事项

### 1. 向后兼容性

* **风险**：修改后旧配置文件可能不兼容

* **缓解**：为新配置项设置合理默认值，确保旧配置仍能工作

### 2. 模板渲染安全

* **风险**：模板中使用 `str.format()` 可能存在注入风险

* **缓解**：只允许预定义变量，禁止用户自定义模板内容

### 3. 文件路径配置

* **风险**：配置文件中使用相对路径可能导致加载失败

* **缓解**：支持绝对路径和相对于项目根目录的相对路径

### 4. 测试覆盖

* **风险**：修改后测试可能失败

* **缓解**：修改前运行现有测试，修改后重新运行验证

## 预期收益

1. **统一管理**：所有 prompt 集中在 `prompts/` 目录，便于查找和维护
2. **易于修改**：无需修改代码即可调整 prompt 内容
3. **版本控制**：prompt 文件纳入版本控制，便于追踪变更
4. **团队协作**：非开发人员也可以修改 prompt 内容
5. **可扩展性**：新增 prompt 只需创建文件并更新配置

## 后续扩展建议

1. **支持多语言**：为每个 prompt 文件创建多语言版本
2. **支持模板变量**：扩展模板系统支持更复杂的变量替换
3. **Prompt 版本管理**：支持多个版本的 prompt 文件并存
4. **Prompt 测试框架**：为 prompt 创建自动化测试
5. **Prompt 评估指标**：添加 prompt 效果评估机制

