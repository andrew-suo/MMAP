# MMAP 项目功能设计质量分析（精修版）

## 一、项目概况

MMAP 是一个 Prompt 自动优化框架，核心流程：

```
Prompt 初始化 → 抽取运行 → 评估 → 分析(找错因) → 生成 Patch → 验证/合并 → 应用 → 压缩 → Few-shot 优化
```

涉及 14 个子模块、约 80+ 个 Python 文件、2055 条测试。

---

## 二、功能冗余分析（含精确调用链）

### 2.1 🔴 Patch 合并模块过度分层（高冗余）

`mmap_optimizer/patch/` 下 5 个合并相关模块，经调用链追踪：

| 文件 | 类/函数 | 被谁调用 | 状态 |
|------|---------|---------|------|
| [merger.py](file:///workspace/mmap_optimizer/patch/merger.py#L8) | `PatchMerger` | **无任何调用者** | ❌ 死代码 |
| [hierarchical_merge.py](file:///workspace/mmap_optimizer/patch/hierarchical_merge.py#L90) | `HierarchicalPatchMerger` | **无任何调用者**（零 import） | ❌ 死代码 |
| [merge_ranking.py](file:///workspace/mmap_optimizer/patch/merge_ranking.py#L41) | `PatchMergeCandidate` | 仅 [test_patch_merge_ranking.py](file:///workspace/tests/test_patch_merge_ranking.py#L18) 测试引用 | ❌ 仅测试用 |
| [clusterer.py](file:///workspace/mmap_optimizer/patch/clusterer.py) | `cluster_patches` | [tree_reduce.py:6](file:///workspace/mmap_optimizer/patch/tree_reduce.py#L6) + 测试 | ⚠️ 间接依赖 |
| [tree_reduce.py](file:///workspace/mmap_optimizer/patch/tree_reduce.py#L22) | `TreeReducePatchMerger` | [round_runner.py:22](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L22) + [round_runner.py:209](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L209) | ✅ 生产使用 |

**精确调用链**：
- `round_runner.py:209` → `TreeReducePatchMerger().merge()` → 内部调用 `clusterer.cluster_patches()`
- `PatchMerger`（merger.py）→ 全项目零 import
- `HierarchicalPatchMerger`（hierarchical_merge.py）→ 全项目零 import
- `PatchMergeCandidate`（merge_ranking.py）→ 仅 `test_patch_merge_ranking.py` 使用

**结论**：`merger.py` 和 `hierarchical_merge.py` 是完全的死代码。`merge_ranking.py` 仅被测试覆盖但无生产调用。`clusterer.py` 被 `tree_reduce.py` 内部依赖，但可内联。

**建议**：
1. 删除 `merger.py`（零调用者）
2. 删除 `hierarchical_merge.py`（零调用者）
3. 将 `clusterer.py` 的 `cluster_patches()` 内联到 `tree_reduce.py`，删除独立文件
4. 将 `merge_ranking.py` 的打分逻辑内联到 `tree_reduce.py`，删除独立文件
5. 最终只保留 `tree_reduce.py`（重命名为 `merger.py`）

### 2.2 🔴 Prompt 工具模块膨胀（高冗余但非死代码）

`mmap_optimizer/prompt/` 下 20 个 .py 文件。经调用链追踪：

| 文件 | 被谁调用 | 状态 |
|------|---------|------|
| [utility_runner.py](file:///workspace/mmap_optimizer/prompt/utility_runner.py) | [utility_report_artifact.py:14](file:///workspace/mmap_optimizer/prompt/utility_report_artifact.py#L14) + examples/ + tests/ | ✅ 有调用者 |
| [utility_report_artifact.py](file:///workspace/mmap_optimizer/prompt/utility_report_artifact.py) | tests/ | ⚠️ 仅测试 |
| [audit_checklist.py](file:///workspace/mmap_optimizer/prompt/audit_checklist.py) | utility_runner.py 内部 | ✅ 被 utility_runner 编排 |
| [json_repair.py](file:///workspace/mmap_optimizer/prompt/json_repair.py) | utility_runner.py + analysis/runner.py | ✅ 双重调用者 |
| [numbering_refactor.py](file:///workspace/mmap_optimizer/prompt/numbering_refactor.py) | utility_runner.py + [refactor.py](file:///workspace/mmap_optimizer/prompt/refactor.py) | ✅ 双重调用者 |
| [immutable_payload.py](file:///workspace/mmap_optimizer/prompt/immutable_payload.py) | utility_runner.py 内部 | ✅ 被 utility_runner 编排 |
| [structured_output_schema.py](file:///workspace/mmap_optimizer/prompt/structured_output_schema.py) | utility_runner.py 内部 | ✅ 被 utility_runner 编排 |
| [self_check.py](file:///workspace/mmap_optimizer/prompt/self_check.py) | 需确认 | ⚠️ 待查 |
| [rewrite_safety.py](file:///workspace/mmap_optimizer/prompt/rewrite_safety.py) | utility_runner.py 内部 | ✅ 被 utility_runner 编排 |

**关键发现**：这些工具模块**不是死代码**，它们被 `utility_runner.py` 编排调用，形成一条完整的"prompt 工具链"。问题不是冗余，而是**职责边界模糊**：

- `self_check.py` 与 `health.py` 功能重叠（都做 prompt 自检）
- `structured_output_schema.py` 与 `contract.py` 功能重叠（都管 schema）
- `rewrite_safety.py` 内部又调用了 `json_repair` / `numbering_refactor` / `immutable_payload`，形成循环依赖风险

**建议**：
1. `self_check.py` 合并到 `health.py`（统一"prompt 健康检查"职责）
2. `structured_output_schema.py` 的验证逻辑合并到 `contract.py`
3. `rewrite_safety.py` 不应内部调用其他工具，应只做"安全报告生成"
4. `utility_runner.py` + `utility_report_artifact.py` 可保留但应明确为"离线工具链"，与核心 IR 流程解耦

### 2.3 🟡 Testing 模块（中冗余）

| 文件 | 被谁调用 | 状态 |
|------|---------|------|
| [patch_tester.py](file:///workspace/mmap_optimizer/testing/patch_tester.py) | [round_runner.py:233](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L233) | ✅ 生产使用 |
| [prompt_test_runner.py](file:///workspace/mmap_optimizer/testing/prompt_test_runner.py) | [round_runner.py:514](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L514) | ✅ 生产使用 |
| [suite_builder.py](file:///workspace/mmap_optimizer/testing/suite_builder.py) | [round_runner.py:232](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L232) | ✅ 生产使用 |
| [patch_runner.py](file:///workspace/mmap_optimizer/testing/patch_runner.py) | 需确认 | ⚠️ 可能与 patch_tester 重叠 |
| [transition.py](file:///workspace/mmap_optimizer/testing/transition.py) | 无调用者 | ❌ 空壳 |

**建议**：删除 `transition.py`，审查 `patch_runner.py` 与 `patch_tester.py` 的关系。

### 2.4 🟡 Metrics 模块（低冗余）

| 文件 | 被谁调用 | 状态 |
|------|---------|------|
| [round_metrics.py](file:///workspace/mmap_optimizer/metrics/round_metrics.py) | [round_runner.py:398](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L398) + [optimizer_loop.py:10](file:///workspace/mmap_optimizer/orchestration/optimizer_loop.py#L10) | ✅ 核心依赖 |
| [section_contribution.py](file:///workspace/mmap_optimizer/metrics/section_contribution.py) | [round_runner.py:388](file:///workspace/mmap_optimizer/orchestration/round_runner.py#L388) | ✅ 生产使用 |
| [section_deltas.py](file:///workspace/mmap_optimizer/metrics/section_deltas.py) | section_contribution 内部 | ⚠️ 间接依赖 |
| [trend.py](file:///workspace/mmap_optimizer/metrics/trend.py) | [optimizer_loop.py:10](file:///workspace/mmap_optimizer/orchestration/optimizer_loop.py#L10) | ✅ 生产使用 |

**修正**：`trend.py` 和 `section_deltas.py` 有实际调用者，不算空壳。但功能轻量，可考虑合并。

### 2.5 🟢 EXTRACTION_SECTIONS / ANALYSIS_SECTIONS 常量残留

[initializer.py:31-42](file:///workspace/mmap_optimizer/prompt/initializer.py#L31-L42) 保留了两个列表，仅被 [_legacy_fallback_ir()](file:///workspace/mmap_optimizer/prompt/initializer.py#L258) 使用。

**建议**：加 `_LEGACY_` 前缀，明确仅用于 fallback。

---

## 三、功能缺失 / 需加强（含具体实现方案）

### 3.1 🔴 section_id_hints 无法通过配置文件传入（高优先级）

**现状**：
- [initializer.py:399](file:///workspace/mmap_optimizer/prompt/initializer.py#L399) 支持 `section_id_hints` 参数
- [config.py:28-59](file:///workspace/mmap_optimizer/core/config.py#L28-L59) `OptimizerConfig` 无此字段
- [round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) 初始化 prompt 时不传 hints

**具体实现方案**：

1. 在 `OptimizerConfig` 新增字段：
```python
# config.py:59 后追加
prompt_section_id_hints: dict[str, str] = field(default_factory=dict)
```

2. 在 `optimizer_config_from_mapping()` 解析：
```python
# config.py:261 后追加
prompt_initialization = data.get("prompt_initialization", {}) or {}
prompt_section_id_hints = prompt_initialization.get("section_id_hints", {}) or {}
```

3. 在 `round_runner.py` 初始化 prompt 时传入：
```python
# round_runner.py 中 initialize_prompt_version 调用处追加
section_id_hints=self.config.prompt_section_id_hints,
```

4. 配置文件支持：
```yaml
prompt_initialization:
  section_id_hints:
    场景适用: scene_check
    线缆: cable_check
```

### 3.2 🔴 Markdown 子标题层级未做结构化分组（高优先级）

**现状**：[parse_markdown_sections()](file:///workspace/mmap_optimizer/prompt/initializer.py#L201) 将每个 heading（包括 `###` 子标题）都作为独立 section。

**问题示例**：
```markdown
## 2. 结果判定总逻辑       → section A
### 2.1 NOT_INVOLVED       → section B（独立，丢失 A 的上下文）
### 2.2 FAIL               → section C（独立，丢失 A 的上下文）
### 2.3 PASS               → section D（独立，丢失 A 的上下文）
```

**具体实现方案**：实现层级分组模式

```python
def parse_markdown_sections_grouped(
    raw_prompt: str,
    *,
    section_id_hints: dict[str, str] | None = None,
    group_subheadings: bool = True,  # 新参数控制是否分组
) -> list[dict[str, Any]]:
    """支持子标题分组的 Markdown 解析。

    当 group_subheadings=True 时：
    - ## 级标题作为主 section
    - ### 级标题的内容合并到最近的 ## 父 section
    - #### 及以下同理
    - 每个 section 的 metadata 中记录子标题信息
    """
```

分组逻辑：
1. 第一遍扫描：识别所有 heading 及其层级
2. 第二遍分组：`##` 作为 section 边界，`###` 及以下内容归入父 section
3. 子标题信息保存到 `metadata.subsections` 中
4. section.content 包含完整的父+子内容

**影响范围**：仅修改 `initializer.py`，不改 IR 结构。

### 3.3 🟡 Patch 验证器对动态 section_id 的支持

**现状**：需审查 [validator.py](file:///workspace/mmap_optimizer/patch/validator.py) 的 `validate()` 方法是否硬编码了 section_id 白名单。

**验证步骤**：读取 `validator.py`，确认它只检查 `patch.section_id in ir.sections`。

### 3.4 🟡 PromptIR 缺少 section 查询能力

**现状**：[ir.py:41](file:///workspace/mmap_optimizer/prompt/ir.py#L41) 只有 `section_by_id()` 一个查询方法。

**建议新增**：
```python
# ir.py PromptIR 类中追加
@property
def renderable_sections(self) -> list[PromptSection]:
    return [s for s in self.sections if s.rendering_enabled]

def sections_by_type(self, type: str) -> list[PromptSection]:
    return [s for s in self.sections if s.type == type]

def section_index(self, section_id: str) -> int | None:
    for i, s in enumerate(self.sections):
        if s.id == section_id:
            return i
    return None
```

### 3.5 🟡 缺少 Prompt 版本间 diff 能力

**建议新增** `mmap_optimizer/prompt/diff.py`：
```python
@dataclass
class SectionDiff:
    section_id: str
    change_type: str  # "added" | "removed" | "modified" | "unchanged"
    content_delta: str | None  # unified diff or None

@dataclass
class PromptVersionDiff:
    from_version_id: str
    to_version_id: str
    section_diffs: list[SectionDiff]
    summary: str

def diff_prompt_versions(v1: PromptVersion, v2: PromptVersion) -> PromptVersionDiff:
    ...
```

### 3.6 🟢 IR 序列化/反序列化

为 `PromptIR` / `PromptSection` 添加 `to_dict()` / `from_dict()`，替代 `dataclasses.asdict()`。

---

## 四、架构层面问题

### 4.1 🔴 RoundRunner 职责过重（God Object）

[round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) 575 行，`run_round()` 方法从 L76 到 L452，承担 10+ 种职责。

**具体拆分方案**：

```
RoundRunner (编排层，~100 行)
  ├── PatchPipeline (L158-L293 抽出)
  │   ├── validate → PatchValidator
  │   ├── repair → PatchRepairEngine
  │   ├── merge → TreeReducePatchMerger
  │   ├── test → PatchTester
  │   └── apply → PatchApplier
  ├── CompressionPipeline (L306-L355 抽出)
  │   └── compress → CompressionEngine
  └── FewShotPipeline (L357-L386 抽出)
      └── optimize → FewShotOptimizationEngine
```

**拆分步骤**：
1. 抽取 `PatchPipeline` 类，封装 L158-L293 的 patch 生命周期
2. 抽取 `CompressionPipeline` 类，封装 L306-L355 的压缩逻辑
3. 抽取 `FewShotPipeline` 类，封装 L357-L386 的 few-shot 逻辑
4. `RoundRunner.run_round()` 只做编排调用

### 4.2 🟡 配置与场景分离不清

**现状**：
- [OptimizerConfig](file:///workspace/mmap_optimizer/core/config.py#L28) 承载框架配置
- [scenario.py](file:///workspace/mmap_optimizer/core/scenario.py) 承载场景配置
- 但 `section_id_hints` 无归属，prompt 路径散落在两处

**建议**：在 `ScenarioConfig` 中新增 `prompt_initialization` 块，包含 `section_id_hints` 和 prompt 文件路径。

### 4.3 🟡 日志系统双轨

- [debug/logger.py](file:///workspace/mmap_optimizer/debug/logger.py) — `DebugEventLogger`，结构化事件日志
- [logging](file:///workspace/mmap_optimizer) — `get_logger` / `log_stage`，标准 Python logging

**建议**：`DebugEventLogger` 保留为调试专用，`get_logger` / `log_stage` 作为生产日志。在文档中明确双轨职责。

---

## 五、总结矩阵

| 类别 | 项目 | 严重度 | 类型 | 精确位置 |
|------|------|--------|------|---------|
| patch 合并死代码 | merger.py / hierarchical_merge.py | 🔴 高 | 冗余 | 零 import |
| patch 合并可内联 | merge_ranking.py / clusterer.py | 🟡 中 | 冗余 | 仅 tree_reduce 内部用 |
| prompt 工具职责模糊 | self_check vs health / structured_output vs contract | 🟡 中 | 重叠 | utility_runner 编排 |
| testing 空壳 | transition.py | 🟢 低 | 冗余 | 无调用者 |
| section_id_hints 无配置入口 | OptimizerConfig 缺字段 | 🔴 高 | 缺失 | config.py:28-59 |
| 子标题层级未分组 | parse_markdown_sections 平铺 | 🔴 高 | 缺失 | initializer.py:201 |
| Patch 验证器适配 | 需审查是否有硬编码白名单 | 🟡 中 | 缺失 | validator.py |
| PromptIR 查询能力 | 只有 section_by_id | 🟡 中 | 缺失 | ir.py:41 |
| 版本间 diff | 无法快速对比变更 | 🟡 中 | 缺失 | 新文件 |
| RoundRunner God Object | 575 行 / run_round 376 行 | 🔴 高 | 架构 | round_runner.py |
| 配置/场景分离 | section_id_hints 无归属 | 🟡 中 | 架构 | config.py |
| 日志双轨 | debug.logger vs logging | 🟢 低 | 架构 | 双文件 |
| EXTRACTION_SECTIONS 残留 | 仅 fallback 使用 | 🟢 低 | 冗余 | initializer.py:31 |
| IR 序列化 | 缺 to_dict/from_dict | 🟢 低 | 缺失 | ir.py |

---

## 六、优先建议（含实施路径）

### P0 — 立即修复（影响核心功能正确性）

1. **section_id_hints 配置入口**
   - 修改：`config.py`（+3 行）、`round_runner.py`（+1 行参数）
   - 验证：配置文件传入 hints → initializer 接收 → IR 生成正确 section_id

2. **子标题层级分组**
   - 修改：`initializer.py`（新增 `parse_markdown_sections_grouped`）
   - 验证：`###` 子标题内容归入父 `##` section，不丢失上下文

### P1 — 短期清理（降低维护成本）

3. **删除 patch 死代码**
   - 删除：`merger.py`、`hierarchical_merge.py`
   - 内联：`clusterer.py` → `tree_reduce.py`、`merge_ranking.py` → `tree_reduce.py`
   - 验证：全量测试通过

4. **prompt 工具职责归一**
   - 合并：`self_check.py` → `health.py`
   - 合并：`structured_output_schema.py` 验证逻辑 → `contract.py`
   - 验证：utility_runner 仍可正常编排

### P2 — 中期重构（提升可维护性）

5. **RoundRunner 拆分**
   - 抽取 `PatchPipeline`、`CompressionPipeline`、`FewShotPipeline`
   - 验证：smoke test 通过

6. **配置/场景分离**
   - `ScenarioConfig` 新增 `prompt_initialization` 块
   - 验证：scenario.yaml 可声明 section_id_hints

### P3 — 长期优化

7. PromptIR 查询方法、版本 diff、IR 序列化、日志统一
