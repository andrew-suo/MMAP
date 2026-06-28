# 多图样本（多图综合→单 label）支持方案

## 一、Summary（摘要）

需求：把 prompt 优化从"单图样本"扩展到"多图样本（多张图片综合判断，输出 1 个 label）"。

**关键发现**：当前生产代码（`mmap_optimizer/refactored/`）的**抽取阶段其实已经支持多图**——`_build_user_message` 和 `_build_assets` 都遍历 `spec.assets` 中所有 `type=="image"` 的资产。真正的缺口是：

1. **抽取阶段图片被重复发送**（现状 bug）：`_build_user_message` 把图片内联进 user 消息 content parts，`_build_assets` 又返回同样图片传给 `complete_multimodal`，`_messages_with_assets` 再次注入 → 图片发送 2 份。多图场景下变成 2N 张图，浪费 token 且可能干扰模型。
2. **分析阶段完全不带图**：`AnalysisExecutor` 用 `complete`（非 `complete_multimodal`），`_build_analysis_messages` 不引用 `sample_spec.assets`，模型只能基于抽取结果文本诊断，无法看图。
3. **fewshot `input_images` 构造未做 `type=="image"` 过滤**：会把非图片资产和空字符串塞进 `input_images`。
4. **自测单图断言**：`extraction_executor.py:218/244` 硬编码 `len(image_parts) == 1`。

评估阶段（单 label 场景）和数据加载层无需改动——`EvaluationExecutor` 字段级 exact match 默认 `["result"]`，`dataset_loader.load_sample_specs` 已遍历 `row["assets"]` 构造多资产。

## 二、Current State Analysis（现状分析）

### 2.1 已支持多图的部分（无需改）

- [dataset_loader.py:27-37](file:///workspace/mmap_optimizer/refactored/dataset_loader.py) `load_sample_specs` 遍历 `row["assets"]` 构造 `SampleAsset`，多图兼容。
- [sample.py](file:///workspace/mmap_optimizer/refactored/sample.py) `SampleSpec.assets: list[SampleAsset]` 列表字段。
- [openai_compatible.py:133-145](file:///workspace/mmap_optimizer/model/openai_compatible.py) `_messages_with_assets` 遍历所有 image 资产注入最后一条 user 消息。
- [evaluation_executor.py:56-74](file:///workspace/mmap_optimizer/refactored/executors/evaluation_executor.py) 字段级 exact match，默认 `["result"]`，单 label 场景兼容。

### 2.2 抽取阶段图片重复发送（bug）

[extraction_executor.py:94-118](file:///workspace/mmap_optimizer/refactored/executors/extraction_executor.py) `_build_user_message`：
```python
image_assets = [a for a in spec.assets if a.type == "image"]
if not image_assets:
    return {"role": "user", "content": text}
content: list[dict[str, Any]] = [{"type": "text", "text": text}]
for asset in image_assets:
    url = self._asset_to_url(asset)
    if url:
        content.append({"type": "image_url", "image_url": {"url": url}})  # ① 内联图片
return {"role": "user", "content": content}
```

[extraction_executor.py:47-69](file:///workspace/mmap_optimizer/refactored/executors/extraction_executor.py) `_execute_single`：
```python
user_message = self._build_user_message(spec)   # user 消息已含 image_url parts
assets = self._build_assets(spec)               # ② 又返回所有 image 资产
response = self.model_client.complete_multimodal(messages=messages, assets=assets, ...)
# complete_multimodal → _messages_with_assets 会 ③ 再次注入图片到 user 消息
```

结果：user 消息 content 含 ① 的 image_url parts + ③ 追加的 image_url parts，图片翻倍。

### 2.3 分析阶段不带图

[analysis_executor.py:48](file:///workspace/mmap_optimizer/refactored/executors/analysis_executor.py) `execute`：
```python
response = self.model_client.complete(messages, model_config=self.model_config)  # 非 multimodal
```
[analysis_executor.py:105](file:///workspace/mmap_optimizer/refactored/executors/analysis_executor.py) `reflect` 同样用 `complete`。
[analysis_executor.py:134-198](file:///workspace/mmap_optimizer/refactored/executors/analysis_executor.py) `_build_analysis_messages` 只组装文本，不引用 `sample_spec.assets`。

### 2.4 fewshot input_images 过滤缺失

[fewshot_optimization_phase.py:438,459](file:///workspace/mmap_optimizer/refactored/fewshot_optimization_phase.py)：
```python
input_images=[asset.uri or asset.local_path or "" for asset in spec.assets],
```
未做 `type == "image"` 过滤，会把非图片资产和空字符串塞入。

### 2.5 自测单图断言

[extraction_executor.py:218,244](file:///workspace/mmap_optimizer/refactored/executors/extraction_executor.py) `assert len(image_parts) == 1`。

## 三、Proposed Changes（方案细节）

### 改动 1：修复抽取阶段图片重复发送

文件：[extraction_executor.py](file:///workspace/mmap_optimizer/refactored/executors/extraction_executor.py)

`_build_user_message`（行 94-118）移除内联图片逻辑，只返回纯文本 user 消息；图片统一由 `_build_assets` + `complete_multimodal` → `_messages_with_assets` 注入。

```python
def _build_user_message(self, spec: SampleSpec) -> dict[str, Any]:
    """组装 user message（仅文本部分）。

    图片资产由 complete_multimodal 通过 assets 参数统一注入，
    避免重复发送。
    """
    text_parts: list[str] = []
    if spec.input:
        text_parts.append("Sample Input:")
        text_parts.append(json.dumps(spec.input, ensure_ascii=False, indent=2))
    if spec.metadata:
        text_parts.append("Metadata:")
        text_parts.append(json.dumps(spec.metadata, ensure_ascii=False, indent=2))
    text = "\n".join(text_parts).strip() or spec.id
    return {"role": "user", "content": text}
```

`_execute_single`、`_build_assets`、`_asset_to_url` 保持不变。

**why**：消除图片翻倍 bug；与 analysis executor 改造方式一致（统一走 assets 注入）；`_messages_with_assets` 注入位置（最后一条 user 消息末尾）与原内联位置一致，不改变模型看到的图片顺序。

### 改动 2：分析阶段带图

文件：[analysis_executor.py](file:///workspace/mmap_optimizer/refactored/executors/analysis_executor.py)

2a. `execute`（行 48）改用 `complete_multimodal` 并传入 assets：
```python
response = self.model_client.complete_multimodal(
    messages=messages,
    assets=self._build_assets(sample_spec),
    model_config=self.model_config,
)
```

2b. `reflect`（行 105）同样改用 `complete_multimodal` 并传入 assets：
```python
response = self.model_client.complete_multimodal(
    messages=messages,
    assets=self._build_assets(sample_spec),
    model_config=self.model_config,
)
```

2c. 新增 `_build_assets` 方法（复用 ExtractionExecutor 的逻辑）：
```python
def _build_assets(self, sample_spec: SampleSpec) -> list[Any]:
    """构建资产列表，从 sample_spec.assets 中提取图片资产。"""
    return [a for a in sample_spec.assets if a.type == "image"]
```

2d. `_build_analysis_messages` / `_build_reflection_messages` 保持纯文本 user 消息（字符串 content），不内联图片——让 `_messages_with_assets` 统一注入。无需修改消息构建逻辑。

**why**：用户要求分析阶段单图/多图都带图。复用 `_messages_with_assets` 统一注入机制，与抽取阶段一致。`ModelClient` 协议已含 `complete_multimodal`，`OpenAICompatibleClient` 和 `MockModelClient` 均已实现。

### 改动 3：fewshot input_images 过滤

文件：[fewshot_optimization_phase.py](file:///workspace/mmap_optimizer/refactored/fewshot_optimization_phase.py)

行 438、459 两处（`replace_all`）：
```python
# 修改前
input_images=[asset.uri or asset.local_path or "" for asset in spec.assets],

# 修改后
input_images=[
    img for img in (
        asset.uri or asset.local_path or ""
        for asset in spec.assets
        if asset.type == "image"
    )
    if img
],
```

**why**：避免非图片资产和空字符串污染 `input_images`，与 `ExtractionExecutor._build_assets` 的 `type == "image"` 过滤保持一致。

### 改动 4：放宽自测单图断言

文件：[extraction_executor.py](file:///workspace/mmap_optimizer/refactored/executors/extraction_executor.py)

改动 1 之后，`_build_user_message` 不再内联图片，自测 Test 3 / Test 4（行 201-249）的断言逻辑失效。重写为验证 `_build_assets` 返回的资产数量，并新增一个多图测试用例：

```python
# Test 3 改写：多模态资产正确提取（uri 形式）
assets = executor_multi._build_assets(spec_multi)
assert len(assets) == 1
# user 消息应为纯文本（图片由 assets 注入）
user_msg = executor_multi._build_user_message(spec_multi)
assert isinstance(user_msg["content"], str)

# Test 4 改写：本地图片资产正确提取
assets = executor_local._build_assets(spec_local)
assert len(assets) == 1

# Test 6（新增）：多图样本资产正确提取
asset1 = SampleAsset(id="a1", sample_id="s4", type="image", uri="https://example.com/1.png")
asset2 = SampleAsset(id="a2", sample_id="s4", type="image", uri="https://example.com/2.png")
spec_multi_img = SampleSpec(id="s4", input={"text": "multi"}, ground_truth={"result": "OK"}, assets=[asset1, asset2])
assets = executor_multi._build_assets(spec_multi_img)
assert len(assets) == 2, f"expected 2 image assets, got {len(assets)}"
```

### 改动 5：补充多图集成测试

新增 `tests/test_multi_image_support.py`，覆盖：

1. **抽取阶段多图不重复**：用 `RecordingClient`（继承 `OpenAICompatibleClient`，记录 `_messages_with_assets` 后的消息）构造 2 图样本，断言最后一条 user 消息的 `image_url` parts 数 == 2（不是 4）。
2. **分析阶段带图**：mock `AnalysisExecutor.execute`，断言 `complete_multimodal` 被调用且 `assets` 含样本图片。
3. **分析阶段 reflect 带图**：同上，验证 `reflect` 也传 assets。
4. **fewshot input_images 过滤**：构造含非图片资产 + 空资产 的 `SampleSpec`，验证 `_select_difficult_samples` 产出的 `FewshotExample.input_images` 仅含非空图片。

测试用 `MockModelClient` 或直接 mock `complete_multimodal`，不连真实模型。

## 四、Assumptions & Decisions（假设与决策）

1. **场景确认**：多图综合→单 label。`ground_truth` 保持单个 `result` 字段，评估逻辑不动。
2. **决策**：图片注入统一走 `_build_assets` + `complete_multimodal` → `_messages_with_assets`，`_build_user_message` 不内联图片。消除双倍图片 bug，统一抽取/分析两阶段行为。
3. **决策**：分析阶段 `execute` 和 `reflect` 都带图（用户要求"分析阶段不管单图多图都带图"）。
4. **决策**：不改动 `OpenAICompatibleClient._messages_with_assets`、`EvaluationExecutor`、`dataset_loader`、schema 文件。
5. **假设**：`ModelClient` 协议的 `complete_multimodal` 签名为 `(messages, assets, model_config, response_format)`，`AnalysisExecutor` 的 `model_client` 已是该协议实例（与 `ExtractionExecutor` 同源）。
6. **不做**：不补充真实多图样例数据文件（`data/samples.jsonl` 仍可空 assets），多图验证由单元测试覆盖。

## 五、Verification（验证步骤）

### 5.1 回归测试

```bash
python -m pytest tests/ -v
```
重点关注 `test_refactored_executors_integration.py`、`test_openai_compatible_multimodal_content_parts.py`、`test_prompt_test_runner_fewshot_assets.py`。

### 5.2 自测

```bash
python -m mmap_optimizer.refactored.executors.extraction_executor
```
验证改动 4 后自测全过（含新增多图 Test 6）。

### 5.3 新增测试

```bash
python -m pytest tests/test_multi_image_support.py -v
```

### 5.4 实施顺序

1. 改动 1（抽取去重）+ 改动 4（自测重写）——耦合，一起做。
2. 改动 2（分析带图）。
3. 改动 3（fewshot 过滤）。
4. 改动 5（新增集成测试）。
5. 运行 5.1/5.2/5.3 全部验证。
