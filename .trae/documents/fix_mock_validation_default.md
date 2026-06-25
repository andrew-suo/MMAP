# 修复 MockModelClient validation_fail_after 默认值 Bug

## Summary

上一轮会话已完成 prompt 压缩 + attribution 功能的 ~95% 实现。所有生产代码（compression_executor、section_contribution、types、analysis_prompt_optimization）和测试文件（test_pr4_compression_executor、test_pr4_acceptance、test_patch_new_system）均已适配新接口。

当前唯一阻塞点是 `tests/test_pr4_compression_executor.py` 中 `MockModelClient` 的默认 `validation_fail_after: int = 0` 导致默认情况下所有 LLM 验证调用都返回 `{"valid": false}`，使 `test_llm_section_compression_with_tracker` 和 `test_llm_validation_pass` 两个测试失败。

## Current State Analysis

### 已完成（无需改动）
- `mmap_optimizer/stages/analysis_prompt_optimization.py` 第 649-657 行：`_step7_compress_if_needed` 已使用新签名，传入 `contribution_tracker=self.contribution_tracker`，保留了压缩后重跑 analysis 的逻辑。
- `mmap_optimizer/executors/compression_executor.py`：混合压缩策略完整实现（确定性预压缩 → Section 级 LLM 压缩 → Prompt 级 LLM 压缩 → LLM 验证）。
- `mmap_optimizer/prompt/section_contribution.py`：SectionContributionTracker EMA 实现。
- `mmap_optimizer/patch/types.py`：CompressionReport 已含新字段。
- `tests/test_pr4_acceptance.py`：压缩相关测试已使用新签名和新字段。
- `tests/test_patch_new_system.py`：`expected_keys` 已含 `prompt_compression`/`prompt_compression_validation`。

### Bug 分析

**文件**: `tests/test_pr4_compression_executor.py`
**位置**: 第 67 行 `MockModelClient.__init__` 和第 79 行 `complete` 方法

**当前代码**（有 bug）:
```python
def __init__(
    self,
    compression_output: str = "Compressed content",
    validation_valid: bool = True,
    validation_fail_after: int = 0,  # ← 默认 0
) -> None:
    ...

def complete(self, messages, model_config=None):
    user_msg = messages[-1]["content"] if messages else ""
    if "验证" in user_msg:
        self.validation_calls += 1
        if self.validation_calls > self.validation_fail_after:  # ← 1 > 0 永远 True
            return _MockModelResponse(
                '{"valid": false, "reason": "mock validation fail"}'
            )
        ...
```

**问题**: 默认 `validation_fail_after=0` 时，第一次验证调用 `validation_calls=1 > 0` 即为 True，直接返回 `{"valid": false}`。这违反了 `validation_valid=True` 的语义意图——默认情况下验证应通过。

**受影响的测试**:
1. `test_llm_section_compression_with_tracker`（第 514 行）：期望 `"section_1" in report.compressed_sections`，但 section 级验证失败导致 `compressed_sections=[]`。
2. `test_llm_validation_pass`（第 556 行）：期望 `report.accepted is True`，但所有验证返回 false 导致 `accepted=False`。

**不受影响的测试**:
- `test_llm_validation_fail`（第 588 行）：显式传入 `validation_fail_after=1`，逻辑正确（第 1 次通过，第 2 次失败）。
- 8 个确定性压缩测试：不使用 `MockModelClient`，不受影响。
- 4 个 SectionContributionTracker 测试：不使用 `MockModelClient`，不受影响。

## Proposed Changes

### 1. 修复 `MockModelClient` 默认值

**文件**: `tests/test_pr4_compression_executor.py`
**位置**: 第 63-89 行 `MockModelClient` 类

**改动**:
- 第 67 行：`validation_fail_after: int = 0` → `validation_fail_after: int | None = None`
- 第 79 行：增加 `None` 检查
  ```python
  if self.validation_fail_after is not None and self.validation_calls > self.validation_fail_after:
  ```

**修复后的代码**:
```python
def __init__(
    self,
    compression_output: str = "Compressed content",
    validation_valid: bool = True,
    validation_fail_after: int | None = None,
) -> None:
    self.compression_output = compression_output
    self.validation_valid = validation_valid
    self.validation_fail_after = validation_fail_after
    self.compression_calls = 0
    self.validation_calls = 0

def complete(self, messages, model_config=None):
    user_msg = messages[-1]["content"] if messages else ""
    if "验证" in user_msg:
        self.validation_calls += 1
        if self.validation_fail_after is not None and self.validation_calls > self.validation_fail_after:
            return _MockModelResponse(
                '{"valid": false, "reason": "mock validation fail"}'
            )
        valid_str = "true" if self.validation_valid else "false"
        return _MockModelResponse(
            f'{{"valid": {valid_str}, "reason": "mock validation"}}'
        )
    else:
        self.compression_calls += 1
        return _MockModelResponse(self.compression_output)
```

**为什么**: `None` 表示"不启用 fail_after 机制"，默认情况下验证结果完全由 `validation_valid` 参数控制，符合测试意图。`test_llm_validation_fail` 显式传入 `validation_fail_after=1` 仍正常工作。

### 2. 运行测试验证

运行以下测试文件验证修复：
```bash
cd /Users/andrew/project/MMAP/MMAP && python3 -m pytest tests/test_pr4_compression_executor.py tests/test_pr4_acceptance.py tests/test_patch_new_system.py -v 2>&1 | tail -50
```

重点验证：
- `test_llm_section_compression_with_tracker` 通过
- `test_llm_validation_pass` 通过
- `test_llm_validation_fail` 仍通过
- 14 个测试全部通过

## Assumptions & Decisions

1. **仅修复测试 mock，不改生产代码**: 生产代码（compression_executor.py 等）逻辑正确，问题仅出在测试 mock 的默认值。
2. **使用 `None` 而非大整数**: `None` 语义最清晰——"不启用 fail_after 机制"，避免魔法数字。
3. **不处理预存在的失败**: `test_acceptance_07_run_level_artifacts_complete` 和 `test_acceptance_full_run_artifact_manifest` 因 PyYAML 未安装而失败，8 个测试文件因 `mmap_optimizer.logging` 等模块不存在而 import 失败——这些是预存在问题，与本任务无关。
4. **不提交代码**: 本计划仅完成测试修复和验证。是否提交推送由用户决定。

## Verification Steps

1. 修改 `MockModelClient` 默认值后运行：
   ```bash
   python3 -m pytest tests/test_pr4_compression_executor.py -v 2>&1 | tail -30
   ```
   预期：14 个测试全部通过。

2. 运行压缩相关验收测试：
   ```bash
   python3 -m pytest tests/test_pr4_acceptance.py::test_acceptance_01_factory_returns_real_compression_executor tests/test_pr4_acceptance.py::test_acceptance_02_compression_detects_over_limit tests/test_pr4_acceptance.py::test_acceptance_03_compression_runs_validation tests/test_pr4_acceptance.py::test_acceptance_04_compression_accept_criteria tests/test_pr4_acceptance.py::test_acceptance_05_compression_failure_preserves_original -v 2>&1 | tail -20
   ```
   预期：5 个压缩相关验收测试通过。

3. 运行 patch 系统测试确认无回归：
   ```bash
   python3 -m pytest tests/test_patch_new_system.py -v 2>&1 | tail -20
   ```
   预期：全部通过。
