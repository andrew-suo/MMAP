# Few-shot 消息格式分析

## 概述

用户提出的问题：当前 few-shot 是否应该使用多轮对话（user/assistant 交替）格式，而非当前的 system prompt 嵌入格式。

**结论：当前实现不是用户期望的多轮对话格式，需要改造。**

## 当前实现分析

### 当前消息结构（单轮）

```python
# prompt_test_runner.py 第 136-139 行
messages = [
    {"role": "system", "content": rendered.text},      # few-shot 文本嵌入在这里
    {"role": "user", "content": json.dumps(user_payload)},  # 当前样本的 JSON payload
]
# all_assets = fewshot_assets + sample_assets  → 注入到 user message 的 content parts
```

最终发送给 API 的消息：

```
message[0] (system): "...FEW_SHOT_SLOT:1\nFEW_SHOT_SAMPLE:s1\n分析过程示例:\n...\n最终输出示例:\n{json}..."
message[1] (user):   [{"type":"text","text":"{\"sample_id\":\"xxx\",...}"},
                      {"type":"image_url","image_url":{"url":"<fewshot_img1>"}},
                      {"type":"image_url","image_url":{"url":"<fewshot_img2>"}},
                      {"type":"image_url","image_url":{"url":"<sample_img>"}}]
```

### 当前方式的问题

1. **few-shot 文本和图像分离**：文本在 system prompt 里，图像在 user message 里，模型难以将它们关联
2. **few-shot 图像与当前样本图像混在一起**：都在同一个 user message 的 content parts 里，模型无法区分哪些是示例、哪些是当前请求
3. **没有 assistant 回复**：模型看到的是"这里有一些示例文本和示例图像，然后请处理这个新样本"，而非"这是一个完整的问答示例（输入+输出），现在请处理新样本"
4. **不符合标准 in-context learning 模式**：主流 LLM 的 few-shot 最佳实践是 user/assistant 交替的多轮对话

## 用户期望的消息结构（多轮对话）

```python
messages = [
    {"role": "system", "content": "你是一个信息抽取助手..."},

    # few-shot 样例 1：输入
    {"role": "user", "content": [
        {"type": "text", "text": "样例1：请从下面图片中抽取字段..."},
        {"type": "image_url", "image_url": {"url": "<example1_img>"}}
    ]},
    # few-shot 样例 1：答案
    {"role": "assistant", "content": '{"发票号":"INV-001",...}'},

    # few-shot 样例 2：输入
    {"role": "user", "content": [
        {"type": "text", "text": "样例2：请从下面图片中抽取字段..."},
        {"type": "image_url", "image_url": {"url": "<example2_img>"}}
    ]},
    # few-shot 样例 2：答案
    {"role": "assistant", "content": '{"发票号":"INV-002",...}'},

    # 当前真实请求
    {"role": "user", "content": [
        {"type": "text", "text": "现在请按照上面样例的格式，从下面图片中抽取字段..."},
        {"type": "image_url", "image_url": {"url": "<target_img>"}}
    ]}
]
```

### 多轮对话方式的优势

1. **文本和图像成对出现**：每个 few-shot 示例的输入文本+图像在同一个 user message 里，模型能正确关联
2. **有明确的 assistant 回复**：模型看到完整的"输入→输出"映射，学习效果更强
3. **示例与当前请求清晰分离**：不同的 user turn 天然区分了示例和真实请求
4. **符合 OpenAI/Anthropic 等 API 的最佳实践**：标准 in-context learning 模式

## 需要改造的组件

### 1. `PromptTestRunner.run`（核心改造点）

**文件**: `mmap_optimizer/testing/prompt_test_runner.py`

当前：`messages = [system, user]`，few-shot 文本在 system 里，few-shot 图像在 user 的 assets 里

改造后：
- system message：只保留核心指令（不含 few-shot section 内容）
- 遍历 few-shot slots，为每个 slot 生成一对 user/assistant message
  - user message：包含示例的文本描述 + 示例图像（作为 content parts）
  - assistant message：包含示例的期望输出 JSON
- 最后追加当前样本的 user message

需要从 PromptIR 的 `few_shot_examples` section 解析出每个 slot 的：
- `source_sample_id` → 查 sample → 获取 asset_ids → 获取图像
- `reasoning_text` → 作为示例输入描述
- `final_output` → 作为 assistant 回复

### 2. `FewShotOptimizationEngine._render_example`（格式调整）

**文件**: `mmap_optimizer/fewshot/engine.py`

当前渲染格式：
```
FEW_SHOT_SLOT:1
FEW_SHOT_SAMPLE:s1
分析过程示例:
<reasoning>
最终输出示例:
<json>
```

改造后需要把 reasoning_text 和 final_output 分开存储，以便分别填入 user 和 assistant message。可以考虑：
- 在 section content 中保留 `FEW_SHOT_SAMPLE` 标记用于资产提取
- 在 section constraints 或 slot metadata 中存储 reasoning 和 output

### 3. `_extract_fewshot_asset_ids`（适配调整）

**文件**: `mmap_optimizer/testing/prompt_test_runner.py`

当前：提取所有 few-shot 资产 ID，扁平拼接成 `fewshot_assets` 列表

改造后：需要按 slot 分组，每个 slot 的资产独立用于该 slot 的 user message

### 4. `OpenAICompatibleClient._messages_with_assets`（可能需调整）

**文件**: `mmap_optimizer/model/openai_compatible.py`

当前：把所有 assets 注入到最后一条 user message

改造后：如果 PromptTestRunner 直接构造好多轮 messages（含 content parts），则 `_messages_with_assets` 不再需要处理 few-shot 资产——它只需处理当前样本的资产。或者完全在 PromptTestRunner 侧构造好完整的 content parts，跳过 `_messages_with_assets` 的注入逻辑。

## 改造方案选择

### 方案 A：在 PromptTestRunner 中构造多轮 messages（推荐）

- PromptTestRunner 从 prompt IR 解析 few-shot slots
- 为每个 slot 构造 user/assistant 消息对（含图像 content parts）
- 最后追加当前样本的 user 消息
- `_messages_with_assets` 只处理当前样本资产（或完全跳过）

**优点**: 改动集中在 PromptTestRunner，对 model client 透明
**缺点**: PromptTestRunner 需要访问 sample assets 来构造 few-shot user messages

### 方案 B：在 model client 层面处理

- PromptTestRunner 传入 few-shot 元数据（slots + assets by slot）
- OpenAICompatibleClient 负责构造多轮 messages

**优点**: model client 更了解 API 格式
**缺点**: 需要修改 ModelClient protocol，影响面大

## 建议范围

推荐 **方案 A**，改动集中在：
1. `prompt_test_runner.py` — 构造多轮 messages
2. `fewshot/engine.py` — 调整 `_render_example` 格式，分离 reasoning 和 output
3. `fewshot/engine.py` — 调整 `_parse_slots_from_content`，解析新增字段
4. 测试更新 — 适配新的消息格式

## 验证步骤

1. 验证构造的 messages 为多轮格式（system + N×(user+assistant) + user）
2. 验证每个 few-shot user message 包含正确的图像 content parts
3. 验证 assistant message 包含正确的输出 JSON
4. 运行现有 few-shot 测试（需要适配新的消息格式）
5. 运行全量测试确保无回归
