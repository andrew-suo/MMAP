# 分析：section_id_hints 自动生成方案

## 问题诊断

### 当前设计的局限性

当前 `section_id_hints` 是**纯手工配置**：每个新场景都需要人工分析 prompt 标题、提取关键词、编写映射。这导致：

1. **新场景接入成本高**：每个垂直领域（电缆、发票、医疗…）都需要人工编写 hints
2. **易遗漏**：标题关键词与 hints 不匹配时，section_id 退化为 `section_NNN`，下游 patch 定位失败
3. **维护负担**：prompt 标题变化时需同步更新 hints

### 为什么 section_id 这么重要

通过代码分析，section_id 在整个优化管道中扮演**核心锚点**角色：

- **渲染层**：`<SECTION id="cable_check" type="cable_check" priority="medium">` — LLM 看到的 prompt 结构
- **Patch 系统**：`Patch.section_id` → `PatchApplier.apply()` 通过 `section_by_id()` 定位目标 section
- **Patch 校验**：`PatchValidator` 检查 `must_mention_section_ids` 约束
- **压缩引擎**：按 section_id 粒度压缩
- **分析归因**：`section_contribution` / `section_deltas` 按 section_id 统计贡献度
- **Patch 对齐**：`PatchAlignmentEngine` 按 section_id 匹配 intent 到具体 section

**如果 section_id 退化为 `section_001`/`section_002`，上述所有环节的语义可读性和定位精度都会下降。**

## 自动生成方案分析

### 方案 A：基于标题的规则自动推导（无 LLM）

**思路**：从 markdown 标题自动提取关键词，生成语义化的 section_id，无需 LLM 调用。

**具体实现**：
1. 在 `normalize_section_id()` 的 fallback 链中，在 `_slugify()` 之前增加一步：**中文标题智能分词 + 语义化 ID 生成**
2. 提取标题中的核心名词/动词短语（如 "检查线缆是否严重凌乱" → 提取 "严重凌乱" 或 "线缆"）
3. 将提取的关键词转换为 snake_case ID（如 "严重凌乱" → `severe_mess` 或 `cable_check`）

**问题**：
- 中文分词需要额外依赖（jieba 等），且分词结果不稳定
- 关键词 → section_id 的映射仍然需要某种"语义理解"，纯规则难以做到
- 不同场景的 ID 命名约定不同（`cable_check` vs `cable_inspection`），无法自动统一

**结论**：可行但效果有限，只能改善 `_slugify` 对中文标题的 fallback，无法生成领域语义 ID。

### 方案 B：LLM 一次性生成 hints（推荐）

**思路**：在 `initialize_prompt_version()` 阶段，如果 `section_id_hints` 为空，调用 LLM 分析 prompt 标题，自动生成 keyword → section_id 映射。

**具体实现**：

1. 新增 `mmap_optimizer/prompt/hint_generator.py`：
   ```python
   def auto_generate_hints(
       raw_prompt: str,
       model_client: ModelClient,
       *,
       existing_generic_hints: dict[str, str] | None = None,
   ) -> dict[str, str]:
   ```
   - 解析 markdown 标题列表
   - 过滤掉已被 generic hints 覆盖的标题
   - 对剩余标题，调用 LLM 生成 keyword → section_id 映射
   - LLM prompt 要求：输出 JSON，key 是标题中的中文关键词，value 是英文 snake_case section_id

2. 在 `initialize_prompt_version()` 中增加可选参数 `auto_hints_model`：
   - 如果提供了 model_client 且 section_id_hints 为空/不完整，自动生成
   - 生成的 hints 与手动 hints 合并（手动优先）

3. 生成的 hints 缓存到 scenario 目录（`section_id_hints.auto.yaml`），避免重复调用 LLM

**优点**：
- 零人工配置：新场景直接可用
- 语义准确：LLM 理解标题含义，生成合理的英文 ID
- 可覆盖：手动 hints 优先级更高，允许人工修正

**风险**：
- LLM 调用增加初始化延迟和成本
- LLM 输出不稳定：同一标题可能生成不同 ID（可通过缓存 + seed 缓解）
- 需要模型客户端在初始化阶段可用

### 方案 C：混合方案（推荐实施）

**思路**：规则优先 + LLM 兜底，分层自动生成。

**具体实现**：

1. **Layer 1 - 增强通用规则**（无 LLM，零成本）：
   - 扩展 `_GENERIC_ZH_KEYWORDS`，增加更多通用结构关键词
   - 新增**中文标题 → 拼音 slug** fallback：`_slugify()` 对中文标题生成拼音 snake_case ID（如 "严重凌乱" → `yan_zhong_ling_luan`）
   - 虽然拼音 ID 不如语义 ID 可读，但比 `section_001` 好得多，且完全确定性

2. **Layer 2 - LLM 自动生成**（可选，有成本）：
   - 在 CLI 层增加 `--auto-hints` flag
   - 当 flag 启用且 scenario.yaml 无 hints 时，调用 LLM 生成
   - 生成的 hints 写入 `scenario.yaml` 的 `section_id_hints` 字段（持久化）
   - 后续运行直接使用，不再调用 LLM

3. **Layer 3 - 手动覆盖**（最高优先级）：
   - scenario.yaml 中的 section_id_hints 始终优先
   - 用户可随时修正自动生成的结果

**优先级链**：手动 hints > LLM 自动 hints > 增强通用规则 > 拼音 slug > section_NNN

## 推荐方案：方案 C（混合方案）

### 实施步骤

#### Step 1：增强中文 slug fallback（零依赖，立即可用）

修改 `_slugify()` 或在 `normalize_section_id()` 中增加拼音 fallback：
- 添加 `pypinyin` 依赖（轻量，纯 Python）
- 中文标题 "严重凌乱" → `yan_zhong_ling_luan` 而非空字符串
- 这确保即使没有任何 hints，中文标题也能产生有意义的 section_id

**文件**：`/workspace/mmap_optimizer/prompt/initializer.py`

#### Step 2：新增 hint_generator 模块

创建 `/workspace/mmap_optimizer/prompt/hint_generator.py`：
- 接收标题列表 + model_client
- 调用 LLM 生成 keyword → section_id 映射
- 返回 dict[str, str]

#### Step 3：CLI 集成 --auto-hints

修改 `/workspace/mmap_optimizer/cli/main.py`：
- 增加 `--auto-hints` flag
- 在 `_apply_scenario_args()` 中，如果 scenario.yaml 无 hints 且 `--auto-hints` 启用，调用 hint_generator
- 生成的 hints 写回 scenario.yaml（持久化）

#### Step 4：测试覆盖

- 测试拼音 slug fallback
- 测试 hint_generator 的 mock 模式
- 测试 --auto-hints CLI 流程
- 测试手动 hints 优先级高于自动生成

### 假设与决策

1. **pypinyin 作为可选依赖**：如果未安装，回退到现有行为（空 slug → section_NNN）
2. **LLM 生成 hints 是幂等操作**：相同标题 + seed 应产生相同结果
3. **自动 hints 持久化到 scenario.yaml**：不单独生成 .auto.yaml 文件，直接写回，简化管理
4. **--auto-hints 默认关闭**：避免意外 LLM 调用，用户显式启用

### 验证步骤

1. 无 hints + 无 pypinyin：中文标题 → section_NNN（现有行为不变）
2. 无 hints + 有 pypinyin：中文标题 → 拼音 slug（如 `yan_zhong_ling_luan`）
3. 有手动 hints：中文标题 → 手动指定的 ID（优先级最高）
4. --auto-hints + 无手动 hints：LLM 生成语义 ID（如 `cable_check`）
5. --auto-hints + 有手动 hints：手动优先，LLM 补充未覆盖的标题
