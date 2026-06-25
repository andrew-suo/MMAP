# Prompt 标准化方案设计

## 一、需求分析

当前 `PromptStructuringPhase` 对结构质量差的 prompt 只是评估并记录质量，并未实际使用模型进行标准化。用户要求实现：

1. 当 prompt 结构质量评估为 "poor" 或 "medium" 时，调用模型进行标准化
2. 标准化后的文本重新进行结构化解析
3. 标准化用的 prompt 放到 `prompts/` 目录管理

## 二、设计方案

### 2.1 新增文件

**`prompts/prompt_standardization.txt`** - 用于模型进行 prompt 标准化的系统提示词

### 2.2 修改文件

**`mmap_optimizer/phases/prompt_structuring.py`** - 实现模型标准化逻辑

**`mmap_optimizer/core/config.py`** - 增加标准化相关配置

**`mmap_optimizer/core/cli.py`** - 增加 CLI 参数

**`mmap_optimizer/core/runner.py`** - 传递模型客户端给 PromptStructuringPhase

## 三、实现步骤

### 步骤 1：创建标准化 Prompt 文件

创建 `prompts/prompt_standardization.txt`，包含：
- 角色定义：Prompt 标准化专家
- 任务目标：将非结构化 prompt 转换为符合规范的 Markdown 格式
- 输出格式要求：包含清晰的章节结构、层级关系、输出 schema 标记
- 示例展示：输入输出对比

### 步骤 2：修改 PromptStructuringPhase

主要改动：
1. 注入 `ModelClient` 依赖
2. 当结构质量评估为 "poor" 或 "medium" 时，调用模型进行标准化
3. 标准化后重新解析

### 步骤 3：更新配置和 CLI

1. 在 `PromptsConfig` 中增加 `prompt_standardization` 路径配置
2. 在 CLI 中增加 `--prompt-standardization` 参数
3. 在 `runner.py` 中将模型客户端传递给 `PromptStructuringPhase`

## 四、标准化流程

```
原始 Markdown → 初步解析 → 质量评估
                                │
                   ┌────────────┴────────────┐
                   ↓                         ↓
              质量 good                质量 poor/medium
                   │                         │
                   ↓                         ↓
            返回结构化                    调用模型标准化
            Prompt                     ↓
                              重新解析为结构化 Prompt
```

## 五、风险与注意事项

1. **性能开销**：标准化会增加一次模型调用，需在配置中提供开关控制
2. **模型输出格式**：需确保模型输出符合 Markdown 格式，否则重新解析可能失败
3. **递归调用风险**：标准化后质量仍可能较差，需限制最大迭代次数
4. **向后兼容**：保留原有的纯解析模式，不影响现有流程

## 六、文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `prompts/prompt_standardization.txt` | 新增 | 标准化用的系统提示词 |
| `mmap_optimizer/phases/prompt_structuring.py` | 修改 | 实现模型标准化逻辑 |
| `mmap_optimizer/core/config.py` | 修改 | 增加标准化配置 |
| `mmap_optimizer/core/cli.py` | 修改 | 增加 CLI 参数 |
| `mmap_optimizer/core/runner.py` | 修改 | 传递模型客户端 |