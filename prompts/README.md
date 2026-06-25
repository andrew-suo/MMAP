# Prompt 目录说明

本目录存放 MMAP 优化系统中所有大模型使用的 Prompt 文件。

## 文件清单

| 文件 | 用途 | 类型 |
|------|------|------|
| `extraction.txt` | Extraction 任务系统提示词 | 静态 prompt |
| `analysis.txt` | Analysis 任务系统提示词 | 静态 prompt |
| `analysis_task.txt` | Analysis 任务消息模板 | 动态模板 |
| `analysis_reflection.txt` | Analysis 反思消息模板 | 动态模板 |
| `semantic_patch_generation.txt` | 语义 patch 草稿生成提示词 | 静态 prompt |
| `semantic_patch_translation.txt` | 语义 patch 到严格 patch 的翻译提示词 | 静态 prompt |

## Prompt 类型说明

### 静态 Prompt

静态 prompt 作为系统消息（system message）使用，定义任务的角色、工作流程、判断标准等。

### 动态模板

动态模板包含占位符变量（如 `{sample_id}`、`{extraction_prompt}`），在运行时根据具体数据进行渲染，作为用户消息（user message）使用。

### 模板变量

动态模板支持以下变量：

#### analysis_task.txt 变量

| 变量 | 说明 |
|------|------|
| `{extraction_prompt}` | 参考用的 extraction prompt 文本 |
| `{sample_id}` | 样本 ID |
| `{status}` | 抽取状态（correct/wrong/invalid） |
| `{raw_output}` | 模型原始输出 |
| `{parsed_output}` | 解析后的输出 JSON |
| `{error_details}` | 错误详情（可选） |
| `{sample_input}` | 样本输入数据 |
| `{sample_metadata}` | 样本元数据（可选） |
| `{ground_truth}` | 真实标签 |

#### analysis_reflection.txt 变量

| 变量 | 说明 |
|------|------|
| `{sample_id}` | 样本 ID |
| `{raw_output}` | 抽取模型原始输出 |
| `{parsed_output}` | 解析后的输出 JSON |
| `{status}` | 抽取状态 |
| `{judgement}` | 分析判断结果 |
| `{analysis_correct}` | 分析是否正确 |
| `{error_reason}` | 错误原因 |
| `{sample_input}` | 样本输入数据 |
| `{ground_truth}` | 真实标签 |

## 扩展指南

### 添加新的静态 Prompt

1. 在本目录创建新的 `.txt` 文件
2. 在 `core/config.py` 的 `PromptsConfig` 中添加配置项
3. 在 `mmap_optimizer/prompt/prompt_manager.py` 中添加加载逻辑
4. 在需要使用的地方通过 `PromptManager` 加载

### 添加新的动态模板

1. 在本目录创建新的 `.txt` 文件，使用 `{variable_name}` 格式定义变量
2. 在 `core/config.py` 的 `PromptsConfig` 中添加配置项
3. 在 `mmap_optimizer/prompt/prompt_manager.py` 中添加加载逻辑
4. 在需要使用的地方通过 `PromptManager.render_prompt()` 渲染

## 版本控制

所有 prompt 文件都纳入版本控制，便于追踪变更历史。修改 prompt 时建议：

1. 先运行测试验证修改前的效果
2. 修改后重新运行测试验证效果
3. 在提交信息中说明修改原因和影响
