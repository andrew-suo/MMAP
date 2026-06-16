# 修复 ModelConfig 缺少 timeout 字段

## 摘要

`ModelConfig` dataclass 缺少 `timeout` 字段，导致用户在 scenario.yaml 中配置的 timeout 被静默忽略，始终使用硬编码默认值 120 秒。

## 当前状态分析

### 数据流

```
scenario.yaml → model_config_from_mapping() → ModelConfig → model_config_to_request_dict() → dict → openai_compatible.py
```

### 问题链

1. `ModelConfig` dataclass（config.py:15-24）没有 `timeout` 字段
2. `model_config_from_mapping()`（config.py:234-246）没有解析 `timeout`
3. `model_config_to_request_dict()`（config.py:249-257）没有包含 `timeout`
4. `openai_compatible.py` 通过 `(model_config or {}).get("timeout", 120)` 读取 timeout
5. 由于 dict 中永远没有 `timeout` key，始终 fallback 到 120 秒

### 影响

- 用户在 scenario.yaml 中配置 `timeout: 300` 被完全忽略
- 大模型/复杂推理场景下 120 秒不够用，请求超时但无法通过配置调整
- 没有任何警告或错误提示用户配置被忽略

## 修改方案

### 修改 1：ModelConfig 添加 timeout 字段

**文件**：`/workspace/mmap_optimizer/core/config.py`

在 `ModelConfig` dataclass 中添加 `timeout` 字段：

```python
@dataclass
class ModelConfig:
    provider: str = "mock"
    model: str = "mock-model"
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2048
    timeout: int = 120
    verify_ssl: bool = True
    chat_template_kwargs: dict[str, Any] | None = None
```

### 修改 2：model_config_from_mapping() 解析 timeout

**文件**：`/workspace/mmap_optimizer/core/config.py`

在 `model_config_from_mapping()` 中添加 timeout 解析：

```python
timeout=int(data.get("timeout", data.get("request_timeout", 120))),
```

支持 `timeout` 和 `request_timeout` 两种 key 名（后者是常见的替代命名）。

### 修改 3：model_config_to_request_dict() 包含 timeout

**文件**：`/workspace/mmap_optimizer/core/config.py`

在 `model_config_to_request_dict()` 中添加 timeout：

```python
def model_config_to_request_dict(config: ModelConfig) -> dict[str, Any]:
    request = {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "timeout": config.timeout,
    }
    if config.chat_template_kwargs is not None:
        request["chat_template_kwargs"] = config.chat_template_kwargs
    return request
```

## 假设与决策

1. **默认值 120 秒**：与 `openai_compatible.py` 中硬编码的默认值一致，保持向后兼容
2. **字段类型 `int`**：与 `openai_compatible.py` 中 `timeout: int | float = 120` 兼容，使用 int 更简单
3. **同时支持 `timeout` 和 `request_timeout`**：`request_timeout` 是 OpenAI SDK 的标准参数名，用户可能使用

## 验证步骤

1. 运行全量测试：`python -m pytest tests/ -x -q`
2. 验证 `ModelConfig` 有 `timeout` 字段
3. 验证 `model_config_from_mapping()` 正确解析 timeout
4. 验证 `model_config_to_request_dict()` 输出包含 timeout
5. 验证 `openai_compatible.py` 能正确读取到配置的 timeout 值
