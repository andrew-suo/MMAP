# Plan: 清理剩余冗余代码

## Summary

经过对扁平化后的代码库进行全面引用分析，重构前的 legacy 代码已全部删除，没有完全废弃的模块。但存在少量冗余代码（未使用的导入、仅测试引用的函数、与 pytest 重复的自测代码）可以清理。`patch/` 目录作为 `tree_merge` 策略的实际实现后端，仍在生产中使用，**不应删除**。

## Current State Analysis

### patch/ 目录分析结论

`patch/` 目录（7 文件）是 `tree_merge` 合并策略的实现后端，**仍在生产中使用**：
- `tree_merge` 是默认合并策略，在 `config.py`、`prompt_optimization_phase.py`、`extraction_prompt_optimization_stage.py`、`analysis_prompt_optimization_stage.py` 中硬编码使用
- `merge_executor.py` 通过 try/except 导入 `patch.schema.Patch` 和 `patch.tree_reduce.TreeReducePatchMerger`，调用 `_tree_merge()` 执行真实合并
- `patch/` 各文件引用关系：
  - `schema.py`、`tree_reduce.py`：被 merge_executor.py 和测试直接引用 ✅ 在用
  - `clusterer.py`、`conflict.py`：被 tree_reduce.py 内部引用 + 测试直接引用 ✅ 在用
  - `deduplicate.py`、`merge_report.py`：仅被 tree_reduce.py 内部引用 ✅ 在用（间接）
- **结论：patch/ 目录无冗余文件，全部保留**

### 发现的冗余代码

| 项 | 位置 | 问题 | 风险 |
|---|---|---|---|
| 1 | `model/openai_compatible.py:5` | `import logging` 未使用（logger 由 get_logger 返回，不需直接 import logging） | 低，死代码 |
| 2 | `logging.py:114-128` | `log_progress()` 函数生产代码无引用，仅 `tests/test_runtime_logging.py` 引用 | 低 |
| 3 | `logging.py:46-55` | `set_log_level()` 函数生产代码无引用，仅 `tests/test_runtime_logging.py` 引用 | 低 |
| 4 | `model/openai_compatible.py:28-30` | `from_env()` 类方法生产代码无引用（factory.py 自行读环境变量），仅测试引用 | 低 |
| 5 | `executors/extraction_executor.py:166-262` | `_run_self_tests()` 自测函数与 pytest 测试重复，且是生产文件中唯一非工厂引用 MockModelClient 的位置 | 中，维护负担 |

## Proposed Changes

### Change 1: 移除 `model/openai_compatible.py` 未使用的 `import logging`
- **文件**：`mmap_optimizer/model/openai_compatible.py:5`
- **操作**：删除 `import logging` 行
- **原因**：文件内无 `logging.` 直接引用，`logger` 由 `get_logger(__name__)` 返回

### Change 2: 移除 `logging.py` 中生产无引用的 `log_progress` 和 `set_log_level`
- **文件**：`mmap_optimizer/logging.py`
- **操作**：
  - 删除 `log_progress()` 函数（line 114-128）
  - 删除 `set_log_level()` 函数（line 46-55）
- **同步更新**：`tests/test_runtime_logging.py` 中移除对这两个函数的测试用例和 import
- **原因**：两者生产代码无任何调用，日志级别实际由 `DEFAULT_LOG_LEVEL` 环境变量在 `_setup_handler` 中设定

### Change 3: 移除 `model/openai_compatible.py` 中仅测试引用的 `from_env` 类方法
- **文件**：`mmap_optimizer/model/openai_compatible.py:28-30`
- **操作**：删除 `from_env()` 类方法
- **同步更新**：`tests/test_openai_compatible_ssl_config.py` 中将 `from_env` 调用改为直接构造 `OpenAICompatibleClient(base_url=..., api_key=os.environ.get(...), ...)`
- **原因**：`factory.py` 自行通过 `os.environ.get(config.api_key_env)` 读取环境变量后传入构造函数，未使用 `from_env`

### Change 4: 移除 `extraction_executor.py` 中与 pytest 重复的 `_run_self_tests()`
- **文件**：`mmap_optimizer/executors/extraction_executor.py:166-262`
- **操作**：删除 `_run_self_tests()` 函数及其 `if __name__ == "__main__"` 调用块
- **原因**：该自测函数的测试逻辑（JSON 解析、多模态消息构造、本地图片 base64）已被 `tests/test_executors_integration.py` 和 `tests/test_openai_compatible_client.py` 覆盖，属于重复代码。移除后生产文件不再需要导入 `MockModelClient`。

## Assumptions & Decisions

1. **patch/ 目录全部保留**：`tree_merge` 是默认合并策略，`patch/` 是其实现后端，仍在生产中使用。
2. **`log_progress` 和 `set_log_level` 可安全移除**：生产代码无引用，仅测试使用，移除后同步清理测试。
3. **`from_env` 可安全移除**：factory.py 未使用它，测试可改为直接构造。
4. **`_run_self_tests` 可安全移除**：其测试场景已被 pytest 测试覆盖，保留属于维护负担。
5. **不改动 `patch/merge_report.py` 与 `patch_types.PatchMergeReport` 的同名问题**：两者职责不同（一个是老系统内部 report，一个是新系统对外 report），merge_executor.py 内部已正确区分使用，重命名属于更大范围重构，不在本次清理范围。

## Verification

1. **运行全部测试**：`python -m pytest tests/ -v`，确保移除冗余代码后测试仍全部通过
2. **验证 import 无残留**：`python -c "import mmap_optimizer"` 无报错
3. **验证无 dangling 引用**：`grep -rn "log_progress\|set_log_level\|from_env\|_run_self_tests" mmap_optimizer/ tests/` 应无生产代码引用（测试中对应清理后也应无残留）
