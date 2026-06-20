# MMAP 多层递归合并设计文档

## 一、背景与目标

### 1.1 现状分析

当前 MMAP 的 patch 合并采用**单层确定性合并**（`TreeReducePatchMerger`，位于 [tree_reduce.py](file:///workspace/mmap_optimizer/patch/tree_reduce.py)）：

- 按 `(target_prompt_type, section_id, operation_type)` 三元组聚类（[clusterer.py](file:///workspace/mmap_optimizer/patch/clusterer.py)）
- 每个 cluster 内做确定性冲突检测 → 去重 → 去包含 → `_merge_many` 拼接
- `_merge_many` 仅做文本拼接（`[{intent_name}] {patch_text}`），**不调用 LLM**
- 可选的 LLM 语义合并（`SemanticPatchProcessor`，[semantic.py](file:///workspace/mmap_optimizer/patch/semantic.py)）在 tree_reduce 之后执行，但也是**单层一次性**处理

**局限性**：
1. 当 patch 数量很大时（如 50+），单次 LLM 合并上下文过长，合并质量下降
2. 无递归归约能力，无法分批合并后再对结果合并
3. 确定性冲突检测（`detect_patch_conflicts`）覆盖面有限，缺少 ADD+DELETE 精确冲突和 old_text 重叠检测
4. 无并发执行，多组 LLM 合并串行处理
5. 无失败传递与全局回退机制

### 1.2 目标

在 MMAP 中实现**多层递归合并**能力，提升合并质量和容错鲁棒性：

- 分层归约：大量 patches 分批合并 → 结果再合并 → 直到收敛
- 确定性 guardrail 前置过滤明显冲突
- Section 感知分组：同 section 的 patches 必须同组处理
- 并发执行多组 LLM 合并
- 失败传递与全局回退

---

## 二、架构设计

### 2.1 整体架构

```
                    ┌─────────────────────┐
                    │  HierarchicalPatch  │
                    │      Merger         │
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌─────────────────┐ ┌──────────┐ ┌──────────────┐
    │ deterministic_  │ │ _group_  │ │ _merge_      │
    │   guardrail     │ │ by_      │ │ single_group │
    │ (确定性冲突过滤) │ │ section  │ │ (LLM合并+重试)│
    └─────────────────┘ └──────────┘ └──────────────┘
              │               │               │
              ▼               ▼               ▼
    ┌─────────────────┐ ┌──────────┐ ┌──────────────┐
    │ _texts_overlap  │ │ _root_   │ │ ThreadPool   │
    │ _normalize_text │ │ merge    │ │ Executor     │
    └─────────────────┘ └──────────┘ └──────────────┘
```

### 2.2 与现有系统的关系

| 现有组件 | 关系 | 说明 |
|---------|------|------|
| `TreeReducePatchMerger` | **保留** | 作为 `strategy="tree_reduce"` 的后端，新合并器是 `strategy="hierarchical"` |
| `SemanticPatchProcessor` | **复用** | 其 LLM 调用模式和 prompt 模板结构被新合并器参考 |
| `PatchCluster` / `cluster_patches` | **不复用** | 新合并器使用 `_group_by_section` 替代，支持 branch_factor 拆分 |
| `detect_patch_conflicts` | **保留** | 作为确定性冲突检测的补充，新合并器新增 `deterministic_guardrail` |
| `PatchMergeReport` | **扩展** | 新增层级相关字段 |
| `OptimizerConfig` | **扩展** | 新增 `patch_merge.strategy` 和 `hierarchical` 子配置 |
| `SampleExecutor` / `map_ordered` | **参考** | 新合并器使用 `ThreadPoolExecutor` 直接管理并发，因为需要 `as_completed` 语义 |

### 2.3 集成点

新合并器将在 [round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) 的 3 个调用点替换 `TreeReducePatchMerger`：

1. **Step 5 — Patch Merge**（extraction 链路，约第 856 行）
2. **Step 8 — Final Merge**（extraction 链路，约第 1061 行）
3. **Analysis Prompt Optimization**（analysis 链路，约第 1318 行）

集成方式：根据 `config.patch_merge_strategy` 选择合并器：
```python
if self.config.patch_merge_strategy == "hierarchical":
    merger = HierarchicalPatchMerger(
        model_client=self.optimizer_client,
        model_config=self._optimizer_model_config(),
        config=self.config.hierarchical_merge_config,
    )
    result = merger.merge(round_id=round_id, patches=candidate_patches, prompt_ir=...)
else:
    result = TreeReducePatchMerger().merge(round_id=round_id, patches=candidate_patches, prompt_ir=...)
```

---

## 三、功能需求

### 3.1 多层递归合并框架

#### 3.1.1 核心类

**新增文件**: `mmap_optimizer/patch/hierarchical_merger.py`

```python
class HierarchicalPatchMerger:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        model_config: dict[str, Any] | None = None,
        config: HierarchicalMergeConfig | None = None,
    ): ...

    def merge(
        self,
        *,
        round_id: str,
        patches: list[Patch],
        prompt_ir: PromptIR | None = None,
        prompt_structure: str | None = None,
    ) -> HierarchicalMergeResult: ...
```

**设计决策**：
- `model_client` 和 `model_config` 通过构造函数注入（与 `SemanticPatchProcessor` 一致），因为合并器需要调用 LLM
- `config` 参数使用 `HierarchicalMergeConfig` dataclass，便于测试和配置管理
- `prompt_structure` 可选参数：如果未传入，则从 `prompt_ir` 自动生成（复用 `SemanticPatchProcessor` 中的 `_prompt_structure` 逻辑）

#### 3.1.2 执行流程

```
输入: N 个 patches
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 0: 聚类分组 → 并行 LLM 合并 → JSON patches        │
│   - deterministic_guardrail 过滤冲突                    │
│   - _group_by_section 按 section 分组                   │
│   - 每组不超过 branch_factor 个                         │
│   - 并发执行 _merge_single_group (ThreadPoolExecutor)   │
│   - 失败组传递原始 patches 到下一层                     │
└─────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 1+: Guardrail → Section 分组 → 并行合并           │
│   - 对上一层的输出再次执行 deterministic_guardrail      │
│   - 同 section 的 patches 必须同组处理                  │
│   - 单 patch 的 section 直接传递（single_pass）         │
│   - 层内失败率 > fallback_threshold → 全局回退          │
└─────────────────────────────────────────────────────────┘
  │
  ▼ (递归直到 ≤1 组 或 达到 max_layers)
┌─────────────────────────────────────────────────────────┐
│ Root Merge: 跨 section 一致性检查                       │
│   - 使用 PATCH_ROOT_MERGE_PROMPT 模板                   │
│   - 双向跨区域校验、冗余检测、孤儿保护                   │
└─────────────────────────────────────────────────────────┘
  │
  ▼
输出: HierarchicalMergeResult
```

#### 3.1.3 递归终止条件

1. 合并后 patches 数量 ≤ 1 → 终止，执行 root merge
2. 达到 `max_layers` → 终止，执行 root merge
3. 层内失败率 > `fallback_threshold` → 终止，全局回退（传递所有剩余 patches）
4. 合并后 patches 数量未减少（无进展）→ 终止，执行 root merge

### 3.2 deterministic_guardrail 冲突检测

**新增函数**: `deterministic_guardrail`（位于 `hierarchical_merger.py` 或独立的 `guardrail.py`）

```python
_ADD_OPS = {"append_to_section", "insert_after", "insert_before", "add_after_section"}
_DELETE_OPS = {"delete_section"}
_MODIFY_OPS = {"replace_in_section", "replace_section"}

def deterministic_guardrail(
    patches: list[Patch],
    *,
    save_detention: bool = True,
) -> tuple[list[Patch], list[Patch]]:
    """
    确定性冲突检测，无需 LLM。
    返回: (kept_patches, detained_patches)
    """
```

**设计决策**：
- 操作类型集合基于 `operation_mode`（而非 `operation_type`），因为 `operation_mode` 是文本级操作的具体模式，与 ADD/DELETE/MODIFY 语义对应
- 但需要做别名映射：模板中的 `append_to_section` 对应代码中的 `append`/`merge_into_section`，`delete_section` 对应 `delete`
- 实际判断时使用 `patch.effective_operation_mode` 属性（已有归一化逻辑）

#### 3.2.1 Pass 1: ADD + DELETE 精确冲突

```python
# 构建 add_map: Dict[(section_id, normalized_content), List[patch_index]]
# 对于同时存在 ADD_OP 和 DELETE_OP 的 key，标记全部为冲突
```

**实现细节**：
- `normalized_content` = `_normalize_text_for_match(patch.patch_text)`
- ADD 操作集合映射：`effective_operation_mode in {"append", "merge_into_section", "insert_after", "insert_before"}`
- DELETE 操作集合映射：`effective_operation_mode == "delete"`
- 当同一 `(section_id, normalized_content)` 同时有 ADD 和 DELETE 时，全部拘留

#### 3.2.2 Pass 2: replace_in_section old_text 重叠检测

```python
# 构建 replace_map: Dict[section_id, List[patch_index]]
# 对同 section 内每对 replace_in_section patches，检测 old_text 是否 overlap
# 冲突裁决：保留 reasoning 更长的，丢弃另一个
```

**实现细节**：
- 只对 `effective_operation_mode == "replace_in_section"` 的 patches 检测
- 使用 `patch.old_text`（或 `patch.locator_value("old_text")`）作为比较文本
- 重叠检测使用 `_texts_overlap(a, b, threshold=0.5)`
- 裁决策略：保留 `len(patch.rationale)` 更长的（注意：用户需求中写的是 `reasoning`，但实际字段名是 `rationale`）

#### 3.2.3 辅助函数

```python
def _texts_overlap(a: str, b: str, threshold: float = 0.5) -> bool:
    """检测两个文本是否重叠（子串包含 + N-gram 重叠率）"""
    # 1. 子串包含检测
    # 2. 3-gram 重叠率计算
    # 3. 重叠率 >= threshold 返回 True

def _normalize_text_for_match(text: str) -> str:
    """文本规范化：去除标点、合并空白、转小写"""
```

### 3.3 Section 感知分组

**新增函数**: `_group_by_section`

```python
def _group_by_section(
    patches: list[Patch],
    branch_factor: int,
) -> list[list[Patch]]:
    """
    按 section 分组，每个分组不超过 branch_factor。
    单 section patches 不足 branch_factor 则单独成组。
    """
```

**分组策略**：
1. 有 `section_id` 的 patch → 加入对应 section bucket
2. 无 `section_id`（空字符串或 None）的 patch → 加入 `no_section` bucket
3. 每个 bucket 按 `branch_factor` 拆分：`[bucket[i:i+branch_factor] for i in range(0, len(bucket), branch_factor)]`
4. 单个 patch的分组标记为 `single_pass=True`，直接传递到下一层不调用 LLM

**设计决策**：
- 不使用现有的 `cluster_patches`（它按三元组分组），因为新合并器需要同 section 的所有 patches 一起处理（不论 operation_type）
- `branch_factor` 控制每组最大 patches 数，避免单次 LLM 上下文过长

### 3.4 单组 LLM 合并

**新增函数**: `_merge_single_group`

```python
def _merge_single_group(
    self,
    patches: list[Patch],
    prompt_structure: str,
    input_type: str,  # "raw_patches" 或 "json_patches"
    *,
    max_retries: int = 2,
) -> tuple[list[Patch], bool]:
    """
    返回: (merged_patches, success)
    """
```

**LLM 调用模式**（参考 [semantic.py](file:///workspace/mmap_optimizer/patch/semantic.py) 的 `_process` 方法）：
1. 渲染 `PATCH_MERGE_PROMPT` 模板（`prompt_structure` + `patches_json`）
2. 调用 `self.model_client.complete(messages, model_config, response_format)`
3. 解析 JSON 数组响应
4. 用 `_patch_from_dict` 重建 Patch（复用 [semantic.py](file:///workspace/mmap_optimizer/patch/semantic.py) 中的逻辑）

**重试策略**：
- 指数退避：`wait_time = 2 ** attempt`（1s, 2s, 4s）
- 膨胀检测：如果 `len(result) > len(input)` 且 `len(input) >= 2`，视为失败并重试
- 解析失败：返回 `(patches, False)`，原始 patches 传递到下一层

**设计决策**：
- `input_type` 参数区分输入是原始 patches（Layer 0）还是已合并的 JSON patches（Layer 1+），影响 prompt 模板的渲染方式
- 膨胀检测防止 LLM 生成比输入更多的 patches（合并应该减少数量）

### 3.5 根合并（Root Merge）

**新增函数**: `_root_merge`

```python
def _root_merge(
    self,
    residual_patches: list[Patch],
    prompt_structure: str,
) -> list[Patch]:
    """执行最终根合并，返回跨 section 一致性检查后的 patches"""
```

**实现方式**：
- 使用 `PATCH_ROOT_MERGE_PROMPT` 模板（新模板，但参考现有的 `PATCH_ROOT_AUDIT_TEMPLATE`）
- 调用 LLM 做跨 section 一致性检查
- 如果 residual_patches 只有 1 个，跳过 LLM 调用直接返回

**检查要求**：
1. 双向跨区域校验（Rules vs Output_Format, Workflow vs Rules 等）
2. 跨 Section 内容冗余检测
3. 孤儿补丁保护（无冲突的独特补丁必须保留）
4. 微调优先（发现冲突时微调而非删除）
5. 严禁臆造（不得新增输入中不存在的修改项）

### 3.6 失败传递与全局回退

**机制**：

| 失败场景 | 处理方式 |
|---------|---------|
| 单组 LLM 调用失败 | 原始 patches 传递到下一层 |
| 单组解析失败 | 原始 patches 传递到下一层 |
| 单组膨胀检测失败 | 重试 `max_retries` 次后传递原始 patches |
| 层内失败率 > `fallback_threshold` | 全局回退：所有剩余 patches（含成功合并的）直接传递到 root merge |

**失败率计算**：
```python
failure_rate = failed_group_count / total_group_count
if failure_rate > self.config.fallback_threshold:
    # 全局回退
    used_fallback = True
    break
```

### 3.7 并发执行

**实现方式**：

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=min(len(groups), self.config.max_concurrency)) as executor:
    futures = {
        executor.submit(self._merge_single_group, group, prompt_structure, input_type): gi
        for gi, group in enumerate(groups)
    }
    for future in as_completed(futures):
        gi = futures[future]
        try:
            merged, success = future.result()
        except Exception:
            merged, success = groups[gi], False
        # 处理结果
```

**设计决策**：
- 使用 `as_completed`（而非 `map_ordered` 的顺序收集），因为合并组之间无依赖，先完成的先处理
- `max_workers = min(len(groups), max_concurrency)`，避免空线程池
- 异常隔离：单个 future 异常不影响其他组

---

## 四、数据结构

### 4.1 新增数据类

**文件**: `mmap_optimizer/patch/hierarchical_merger.py`

```python
@dataclass
class HierarchicalMergeConfig:
    branch_factor: int = 8
    max_layers: int = 6
    fallback_threshold: float = 0.3
    max_retries: int = 2
    max_concurrency: int = 3

@dataclass
class HierarchicalMergeResult:
    final_patches: list[Patch]
    rejected_patches: list[Patch]
    merge_report: PatchMergeReport
    layer_count: int
    final_layer: int
    used_fallback: bool

@dataclass
class MergeLayerReport:
    layer: int
    input_count: int
    group_count: int
    merged_count: int
    passed_through_count: int
    failed_count: int
    failure_rate: float
    used_fallback: bool
```

### 4.2 扩展 PatchMergeReport

**文件**: [merge_report.py](file:///workspace/mmap_optimizer/patch/merge_report.py)

```python
@dataclass
class PatchMergeReport:
    # ... 现有字段保持不变 ...
    id: str
    round_id: str
    input_patch_ids: list[str] = field(default_factory=list)
    cluster_count: int = 0
    clusters: list[dict] = field(default_factory=list)
    duplicate_patch_ids: list[str] = field(default_factory=list)
    subsumed_patch_ids: list[str] = field(default_factory=list)
    conflict_patch_ids: list[str] = field(default_factory=list)
    merged_patch_ids: list[str] = field(default_factory=list)
    final_patch_ids: list[str] = field(default_factory=list)

    # 新增字段
    layer_reports: list[MergeLayerReport] = field(default_factory=list)  # 每层的报告
    guardrail_detained_ids: list[str] = field(default_factory=list)      # 被 guardrail 拘留的 patch IDs
    root_merge_applied: bool = False                                    # 是否应用了根合并
    fallback_applied: bool = False                                      # 是否触发了全局回退
```

**设计决策**：
- `MergeLayerReport` 定义在 `hierarchical_merger.py` 中，`PatchMergeReport` 通过 `from mmap_optimizer.patch.hierarchical_merger import MergeLayerReport` 引用
- 新增字段都有默认值，保证向后兼容（`TreeReducePatchMerger` 不受影响）

---

## 五、配置项

### 5.1 OptimizerConfig 扩展

**文件**: [config.py](file:///workspace/mmap_optimizer/core/config.py)

在 `OptimizerConfig` dataclass 中新增：

```python
# Patch merge strategy
patch_merge_strategy: str = "tree_reduce"  # "tree_reduce" 或 "hierarchical"
hierarchical_merge_config: HierarchicalMergeConfig = field(default_factory=HierarchicalMergeConfig)
```

在 `optimizer_config_from_mapping` 中新增解析：

```python
patch_merge = data.get("patch_merge", {}) or {}
patch_merge_strategy = str(patch_merge.get("strategy", "tree_reduce"))
hierarchical_config = HierarchicalMergeConfig()
if patch_merge.get("hierarchical"):
    hc = patch_merge["hierarchical"]
    hierarchical_config = HierarchicalMergeConfig(
        branch_factor=int(hc.get("branch_factor", 8)),
        max_layers=int(hc.get("max_layers", 6)),
        fallback_threshold=float(hc.get("fallback_threshold", 0.3)),
        max_retries=int(hc.get("max_retries", 2)),
        max_concurrency=int(hc.get("max_concurrency", 3)),
    )
```

### 5.2 YAML 配置示例

```yaml
# configs/optimizer.yaml
patch_merge:
  strategy: "hierarchical"  # "tree_reduce" 或 "hierarchical"
  semantic_enabled: true     # 现有配置
  root_audit_enabled: false  # 现有配置
  hierarchical:
    branch_factor: 8
    max_layers: 6
    fallback_threshold: 0.3
    max_retries: 2
    max_concurrency: 3
```

### 5.3 模型配置

```python
MERGE_MODEL_CONFIG = {
    "model_name": "qwen3-6-27b",
    "temperature": 0.3,
    "max_tokens": 4096,
}
```

模型配置通过 `OptimizerConfig.optimizer_model` 和 `OptimizerConfig.optimizer_model_config` 传入，与现有的 `SemanticPatchProcessor` 共用同一模型配置。

---

## 六、Prompt 模板

### 6.1 PATCH_MERGE_PROMPT

**新增文件**: 在 [optimizer_prompts.py](file:///workspace/mmap_optimizer/templates/optimizer_prompts.py) 中新增 `PATCH_HIERARCHICAL_MERGE_TEMPLATE` 常量并注册。

模板参考现有的 `PATCH_SEMANTIC_MERGE_TEMPLATE`（第 421-508 行），但增加以下内容：

```python
PATCH_HIERARCHICAL_MERGE_TEMPLATE = """...
## Guidelines

### 1. 结构划分与隔离
按 `target_section` 分类，**不同 section 的 patches 不得混淆**。
每个 section 的修改独立处理。

### 2. 逻辑去重与泛化
- 同一 section 同 op 的 patch 需合并/拼接
- 相似 patch 需泛化为通用原则
- 保留核心意图，去除冗余

### 3. 技术约束
- 每条 edit 行级互不重叠（核心硬性约束，防止并行应用冲突）
- 优先使用 `append_to_section`
- 总条数目标 ≤ 原始数量的 1/3
- **严禁臆造**：不得新增输入中不存在的修改项

### 4. 操作偏好
按以下优先级选择操作：
1. `append_to_section`（追加到 section 末尾）
2. `insert_after` / `insert_before`（在指定文本前后插入）
3. `replace_in_section`（替换 section 中某段文本）
4. `replace_section`（重写整个 section）
5. `delete_section`（删除 section）
"""
```

**注册**：
```python
PromptTemplateSpec(
    "patch_hierarchical_merge", "1.0",
    "Hierarchical multi-layer merge of patch candidates.",
    ["prompt_structure", "patches_json"],
    _contract("json_array", fallback="original patch array"),
    PATCH_HIERARCHICAL_MERGE_TEMPLATE, "high", ["patch", "merge"],
),
```

### 6.2 PATCH_ROOT_MERGE_PROMPT

参考现有的 `PATCH_ROOT_AUDIT_TEMPLATE`（第 510-596 行），新增 `PATCH_HIERARCHICAL_ROOT_MERGE_TEMPLATE`：

```python
PATCH_HIERARCHICAL_ROOT_MERGE_TEMPLATE = """...
## 跨 Section 一致性检查

### 1. 双向跨区域校验
- **Rules vs Output_Format**：检查规则定义与输出格式是否一致
- **Workflow vs Rules**：检查工作流与规则是否有冲突
- **Constraints vs Output Format**：检查约束条件与输出格式是否兼容

### 2. 冗余检测
跨 Section 内容冗余检测：
- 相同约束在多个 section 重复定义
- 矛盾的要求在不同 section 出现

### 3. 孤儿补丁保护
无冲突的独特补丁必须保留，**不得以"精简"为由删除**

### 4. 微调优先
发现冲突时**微调而非删除**

### 5. 严禁臆造
不得新增输入中不存在的修改项
"""
```

**注册**：
```python
PromptTemplateSpec(
    "patch_hierarchical_root_merge", "1.0",
    "Root merge for cross-section consistency check in hierarchical merge.",
    ["prompt_structure", "patches_json"],
    _contract("json_array", fallback="original patch array or []"),
    PATCH_HIERARCHICAL_ROOT_MERGE_TEMPLATE, "high", ["patch", "merge"],
),
```

---

## 七、实现计划

### 7.1 新增文件

| 文件 | 说明 |
|------|------|
| `mmap_optimizer/patch/hierarchical_merger.py` | 核心实现：`HierarchicalPatchMerger`、`deterministic_guardrail`、`_group_by_section`、`_texts_overlap`、`_normalize_text_for_match`、`HierarchicalMergeConfig`、`HierarchicalMergeResult`、`MergeLayerReport` |

### 7.2 修改文件

| 文件 | 修改内容 |
|------|---------|
| [merge_report.py](file:///workspace/mmap_optimizer/patch/merge_report.py) | 新增 `layer_reports`、`guardrail_detained_ids`、`root_merge_applied`、`fallback_applied` 字段 |
| [config.py](file:///workspace/mmap_optimizer/core/config.py) | 新增 `patch_merge_strategy` 和 `hierarchical_merge_config` 字段及解析逻辑 |
| [optimizer_prompts.py](file:///workspace/mmap_optimizer/templates/optimizer_prompts.py) | 新增 `PATCH_HIERARCHICAL_MERGE_TEMPLATE` 和 `PATCH_HIERARCHICAL_ROOT_MERGE_TEMPLATE` 模板及注册 |
| [round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) | 3 个调用点根据 `patch_merge_strategy` 选择合并器 |

### 7.3 实现步骤

1. **创建 `hierarchical_merger.py`**：实现所有核心类和函数
2. **扩展 `merge_report.py`**：添加新字段
3. **扩展 `config.py`**：添加配置项和解析逻辑
4. **新增 prompt 模板**：在 `optimizer_prompts.py` 中添加两个新模板
5. **集成到 `round_runner.py`**：3 个调用点添加策略选择逻辑
6. **编写测试**：覆盖 guardrail、分组、单组合并、递归、回退等场景

---

## 八、假设与决策

### 8.1 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 操作类型判断基于哪个字段 | `effective_operation_mode` | 已有归一化逻辑，与 `PatchApplier` 一致 |
| 冲突裁决保留哪个 patch | `rationale` 更长的 | 用户需求指定，rationale 更长通常意味着分析更充分 |
| 并发模式 | `ThreadPoolExecutor` + `as_completed` | 合并组之间无依赖，先完成先处理 |
| 模板管理 | 注册到 `PromptTemplateRegistry` | 与现有模板管理一致 |
| 向后兼容 | 新增字段都有默认值 | `TreeReducePatchMerger` 不受影响 |
| `model_client` 注入 | 构造函数注入 | 与 `SemanticPatchProcessor` 一致 |

### 8.2 假设

1. LLM 合并的输出格式为 JSON 数组（与现有 `patch_semantic_merge` 模板一致）
2. `model_client.complete()` 是线程安全的（`OpenAICompatibleClient` 使用 `urllib.request`，每次调用独立）
3. `prompt_ir` 在整个合并过程中不变（合并器不修改 prompt_ir）
4. Patch 对象在合并过程中可以被修改（status、rejection_reason 等字段），与 `TreeReducePatchMerger` 行为一致

---

## 九、验证步骤

1. **单元测试**：
   - `deterministic_guardrail`：ADD+DELETE 冲突、old_text 重叠、无冲突
   - `_texts_overlap`：子串包含、N-gram 重叠、阈值边界
   - `_group_by_section`：单 section、多 section、无 section、branch_factor 拆分
   - `_merge_single_group`：成功、解析失败、膨胀检测、重试
   - `HierarchicalPatchMerger.merge`：单层收敛、多层递归、回退、root merge

2. **集成测试**：
   - 在 `round_runner.py` 的 3 个调用点验证策略切换
   - 验证 `PatchMergeReport` 的新字段正确填充
   - 验证 `HierarchicalMergeResult` 的 `layer_count`、`used_fallback` 等字段

3. **回归测试**：
   - `patch_merge_strategy="tree_reduce"` 时所有现有测试通过
   - `tests/test_patch_and_round.py` 的 19 个测试全部通过
