# Patch Merge 重构计划

## Summary

根据 `patch_merge_old.md` 设计文档，将当前基于文本拼接的 TreeReducePatchMerger 重构为基于 LLM 的 Parallel Patch Merge 算法。核心变化：引入 LLM 合并、并行执行、层级递归、确定性前筛（ADD+DELETE 冲突 + replace 重叠检测）、Section-Aware 分组、膨胀检测和全局回退。

## Current State Analysis

### 当前实现的问题

| 维度 | 当前实现 | 设计文档要求 |
|------|---------|-------------|
| **合并方式** | 文本拼接（`_merge_many` 纯代码拼接 patch_text） | LLM 调用合并（语义级去重、泛化、冲突消解） |
| **并行度** | 串行遍历 cluster | ThreadPoolExecutor 并行合并 |
| **层级递归** | 单轮（cluster → merge → done） | 多层 tree-reduce（直到终止条件） |
| **分组维度** | (target_prompt_type, section_id, operation_type) | Section-Aware（按 target_section 分组） |
| **冲突检测** | OPPOSITE_LABEL_BIAS、STRICTNESS_CONFLICT 等（基于关键词） | ADD+DELETE 精确冲突 + replace n-gram 重叠检测 |
| **Root Merge** | 无 | 跨 section 一致性审查 |
| **膨胀检测** | 无 | output > input → 重试 |
| **全局回退** | 异常时 passthrough | 失败率 > 阈值 → 单次批量合并 |

### 涉及的文件

| 文件 | 当前职责 | 改动 |
|------|---------|------|
| `mmap_optimizer/patch/tree_reduce.py` | TreeReducePatchMerger（文本拼接合并） | **重写**为 ParallelPatchMerger |
| `mmap_optimizer/patch/clusterer.py` | 按 (type, section, op) 聚类 | **重写**为 Section-Aware 分组 |
| `mmap_optimizer/patch/conflict.py` | 关键词冲突检测 | **重写**为确定性前筛（ADD+DELETE + replace 重叠） |
| `mmap_optimizer/patch/deduplicate.py` | 归一化去重 | 保留，被确定性前筛复用 |
| `mmap_optimizer/executors/merge_executor.py` | 包装 TreeReducePatchMerger | **修改**适配新的 ParallelPatchMerger |
| `prompts/patch_merge.txt` | 不存在 | **新增** LLM 合并 prompt |
| `prompts/patch_root_merge.txt` | 不存在 | **新增** Root Merge prompt |
| `mmap_optimizer/core/config.py` | PromptsConfig | **修改**增加 patch_merge/patch_root_merge 字段 |
| `mmap_optimizer/executors/factory.py` | 创建 MergeExecutor | **修改**传递 model_client 和 prompt 路径 |
| `mmap_optimizer/core/cli.py` | CLI 参数 | **修改**增加 --patch-merge-prompt 参数 |

## Proposed Changes

### 1. 新增 `prompts/patch_merge.txt`

使用用户提供的 PATCH_MERGE_PROMPT，包含：
- Role: 高级 Prompt 策略合并专家
- Inputs: prompt_structure、input_type、input_type_instruction、patches_content
- 合并策略指南（三大维度）：
  - **结构划分与隔离**：GROUP BY SECTION、ISOLATION（异类隔离）、保序性、ICL 保护
  - **逻辑去重与泛化抽象**：去重与拼接、泛化抽象（同类归纳）、冲突消解、流行度偏置
  - **技术约束与硬性底线**：独立性（行级互不重叠）、操作偏置（优先 Append）、精简压缩（≤ 1/3）
- Output Format: JSON 数组，包含 op、target_section、content/old_text/new_text、reasoning
- 占位符：`{prompt_structure}`、`{input_type}`、`{input_type_instruction}`、`{patches_content}`

### 2. 新增 `prompts/patch_root_merge.txt`

Root Merge prompt，强调：
- 跨 section 逻辑冲突检测
- 全局一致性审查
- 最终整合输出

### 3. 重写 `mmap_optimizer/patch/tree_reduce.py`

新增 `ParallelPatchMerger` 类，实现：

```
class ParallelPatchMerger:
    def __init__(self, model_client, model_config, merge_prompt_path, 
                 root_merge_prompt_path, branch_factor=8, max_layers=10,
                 max_retries=2, fallback_threshold=0.5)
    
    def merge(self, patches, prompt_structure) -> list[dict]:
        # L0: 解析 + 分组 + 并行合并
        # L1+: deterministic_guardrail → section_aware_grouping → 并行合并
        # 终止条件检查
        # Root Merge（如需要）
```

核心方法：
- `_run_parallel_merge`: 主循环
- `_deterministic_guardrail`: ADD+DELETE 冲突 + replace 重叠检测
- `_group_by_section`: Section-Aware 分组 + single pass
- `_merge_single_group`: 调用 LLM 合并单个分组（含膨胀检测 + 重试）
  - 使用 `PATCH_MERGE_PROMPT` 模板，填充 `{prompt_structure}`、`{input_type}`、`{input_type_instruction}`、`{patches_content}`
  - `input_type_instruction` 根据 input_type（raw_patches / json_patches）提供不同处理指引
  - 膨胀检测：output > input → 指数退避重试
- `_root_merge`: 跨 section 一致性审查（使用 `PATCH_ROOT_MERGE_PROMPT`）
- `_texts_overlap`: n-gram 重叠检测（n=8, threshold=0.5）

### 4. 重写 `mmap_optimizer/patch/conflict.py`

新增确定性前筛函数：
- `detect_add_delete_conflicts`: ADD+DELETE 精确冲突检测
  - 构建 Map: (target_section, normalized_content) → indices
  - 同时存在于 ADD 和 DELETE → 冲突
- `detect_replace_overlaps`: replace_in_section 重叠检测
  - 同 section 内两两比较 old_text
  - n-gram 算法（n=8, threshold=0.5）
  - 保留 reasoning 较长的，删除另一个
- `texts_overlap`: n-gram 重叠判断函数

### 5. 重写 `mmap_optimizer/patch/clusterer.py`

新增 Section-Aware 分组函数：
- `group_by_section`: 按 target_section 分组
  - 同 section 的 patch 分到同组
  - 超出 branch_factor 时分割
  - 无 section 的 patch 单独分组
- `categorize_by_section`: 区分 groupable 和 single_pass
  - single_pass: 同 section 内没有邻居的 patch，直接传递

### 6. 修改 `mmap_optimizer/executors/merge_executor.py`

- 保留 passthrough 回退机制
- `_tree_merge` 方法改为调用 `ParallelPatchMerger`
- 传递 model_client、prompt 路径等参数
- 当 model_client 不可用时，回退到旧的文本拼接模式或 passthrough

### 7. 修改 `mmap_optimizer/core/config.py`

- `PromptsConfig` 增加 `patch_merge` 和 `patch_root_merge` 字段
- `to_dict()` 和 `from_dict()` 方法更新

### 8. 修改 `mmap_optimizer/executors/factory.py`

- 读取 `patch_merge` 和 `patch_root_merge` prompt 路径
- 传递 `model_client`、`model_config`、prompt 路径给 `MergeExecutor`

### 9. 修改 `mmap_optimizer/core/cli.py`

- 增加 `--patch-merge-prompt` 和 `--patch-root-merge-prompt` 参数

## Assumptions & Decisions

1. **保留旧系统作为回退**：当 model_client 不可用时，回退到旧的 TreeReducePatchMerger 或 passthrough
2. **保留旧 schema.py 和 deduplicate.py**：这些模块的数据结构和工具函数仍被使用
3. **配置参数**：branch_factor=8, max_layers=10, max_retries=2, fallback_threshold=0.5, ngram_n=8, ngram_threshold=0.5
4. **并行执行**：使用 `concurrent.futures.ThreadPoolExecutor`
5. **数据结构转换**：MergeExecutor 仍负责 ExtractionPatch/AnalysisPatch ↔ dict 的转换，ParallelPatchMerger 内部使用 dict 格式

## Verification Steps

1. 运行 `python3 -m pytest tests/test_core.py -v` 确保现有测试通过
2. 验证确定性前筛：
   - ADD+DELETE 冲突检测
   - replace n-gram 重叠检测
3. 验证 Section-Aware 分组：
   - 同 section 分到同组
   - single pass 直通
4. 验证向后兼容：model_client=None 时回退到旧模式
