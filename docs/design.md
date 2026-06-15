# MMAP 多模态提示词自动优化框架设计文档

## 1. 背景与目标

MMAP 的目标是构建一个**场景无关**的多模态提示词自动优化框架。框架面向一批带有 Ground Truth 的图像样本，自动优化两个提示词：

1. **抽取提示词（Extraction Prompt）**：给待优化的多模态模型使用，负责根据图片与上下文输出结构化审核结果。
2. **分析提示词（Analysis Prompt）**：给优化/分析模型使用，负责评估抽取结果、归因错误、生成 patch 建议、识别风险。

初始业务场景是通信类设备施工后的现场施工质量审核，但框架设计必须避免绑定该业务。所有业务差异应通过数据、schema、scenario 配置、prompt section 内容和可选模板覆盖表达。

## 2. 总体原则

### 2.1 结果判断与原因分析分离

系统中的信任优先级为：

```text
Ground Truth / Evaluator 结果 > Patch 实测效果 > Analysis Prompt 解释 > 模型自我声称
```

分析提示词可以生成候选解释和候选 patch，但不能替代 evaluator 或 Ground Truth 成为最终裁决者。

### 2.2 Patch 必须实测

任何 patch 都不能仅凭模型解释被接受。patch 需要经过：

1. 基础校验；
2. merge / conflict 处理；
3. individual patch test；
4. bundle test；
5. strict poisoning check。

初期采用严格测毒策略：

```text
fixed_count > 0
broken_count == 0
schema_violation_count == 0
parse_error_count == 0
format_error_count == 0
```

### 2.3 Prompt 是结构化对象

提示词不是不可分割的大段文本，而是由 Prompt IR 表达的结构化对象。所有 patch、压缩、贡献度统计、回滚和版本管理都以 section 为基本操作单元。

### 2.4 Output Schema 是不可变外部契约

抽取输出 schema 和分析输出 schema 均由外部 contract 提供，自动优化流程不得修改。`output_schema` 与 `analysis_output_schema` section 必须：

```text
mutability = frozen
compressibility = none
```

如果输出格式遵守不佳，只能优化 `format_compliance_policy`、`schema_guard_policy`、`self_check` 等非 schema section。

### 2.5 压缩和 few-shot 都是独立阶段

- 文本规则 patch 优化先进行。
- 文本提示词稳定后，再进入 few-shot slots 优化。
- 压缩不是普通摘要，而是一类特殊 patch，必须经过语义检查与行为保持测试。

## 3. 核心对象

### 3.1 Prompt IR

Prompt IR 顶层包含：

```yaml
prompt_ir:
  id: string
  prompt_type: extraction | analysis
  version: integer
  contracts:
    output_schema_contract_id: string
  global_constraints: {}
  sections: []
  rendering: {}
  initialization: {}
  history: {}
```

每个 section 至少包含：

```yaml
section:
  id: string
  type: string
  scope: framework | task | domain | dataset
  priority: critical | high | medium | low
  compressibility: none | low | medium | high
  mutability: frozen | limited | normal
  content: string
  rendering_enabled: boolean
  constraints: {}
  source_map: {}
  metrics: {}
  provenance: {}
```

### 3.2 抽取提示词标准 section

建议内置：

```text
role_definition
task_definition
input_description
quality_criteria
visual_evidence_rules
ambiguity_policy
reasoning_constraints
format_compliance_policy
negative_cases
self_check
output_schema
legacy_unmapped
few_shot_examples
```

其中 `few_shot_examples` 在文本提示词稳定后的 few-shot 阶段启用。

### 3.3 分析提示词标准 section

建议内置：

```text
role_definition
analysis_task
ground_truth_alignment
error_attribution_policy
prompt_section_attribution_policy
patch_generation_policy
patch_risk_policy
schema_guard_policy
uncertainty_policy
self_check
analysis_output_schema
legacy_unmapped
```

### 3.4 Patch

Patch 是结构化优化单元，不是自由文本 diff。MVP 必需字段：

```yaml
patch:
  id: string
  type: prompt_patch | compression_patch
  status: draft | candidate | merged | testing | accepted | rejected | quarantined | superseded | rolled_back
  target:
    prompt_type: extraction | analysis
    prompt_id: string
    base_version_id: string
    section_id: string
  operation:
    type: ADD_RULE | REFINE_RULE | ADD_EXCEPTION | ADD_SELF_CHECK | CLARIFY_AMBIGUITY | STRENGTHEN_FORMAT_COMPLIANCE | COMPRESS_SECTION | MOVE_CONTENT | ...
    mode: append | merge_into_section | replace_section | replace_in_section | insert_after | insert_before
  intent: {}
  content: {}
  evidence: {}
  risk: {}
  constraints: {}
  merge: {}
  application: {}
  testing: {}
  audit: {}
```

Patch 必须保留来源样本、来源分析和来源 prompt version，便于回溯与分析提示词进化。

### 3.5 Sample State

每个样本需要维护动态状态：

```yaml
sample_state:
  sample_id: string
  difficulty_ema: float
  difficulty_bin: easy | medium | hard | unknown
  fragility_score: float
  selected_count_recent_window: integer
  last_selected_round: integer | null
  historical_fixed: boolean
  toxic_trigger: boolean
  suspected_label_noise: boolean
  suspected_model_limitation: boolean
  ambiguous: boolean
```

这些状态用于动态采样、测毒、few-shot 候选选择和过拟合控制。

## 4. 初始化与 Prompt 对齐

初始化不是优化轮次。流程为：

```text
raw prompt
  -> prompt structure detection / optional standardization
  -> Prompt IR draft
  -> external output schema contract injection
  -> legacy_unmapped preservation
  -> semantic alignment check
  -> optional behavior alignment check
  -> PromptVersion v1
```

初始化必须遵守：

1. 不新增业务规则；
2. 不删除原始约束；
3. 不改变判断标准；
4. 不改变 output schema；
5. 无法可靠分类的内容进入 `legacy_unmapped`；
6. 原始 prompt 与 schema 冲突时，以外部 schema contract 为准并记录 warning。

## 5. 一轮文本优化状态机

推荐状态机：

```text
ROUND_CREATED
  -> SAMPLING_POLICY_SELECTED
  -> SAMPLE_SELECTED
  -> DYNAMIC_VALIDATION_SELECTED
  -> PROMPT_HEALTH_CHECKED
  -> EXTRACTION_INFERRED
  -> RESULT_EVALUATED
  -> ERROR_ANALYZED
  -> PATCHES_GENERATED
  -> PATCHES_VALIDATED
  -> PATCHES_MERGED
  -> PATCHES_TESTED
  -> EXTRACTION_PROMPT_UPDATED / EXTRACTION_UPDATE_SKIPPED
  -> ANALYSIS_SHADOW_EVALUATED
  -> ANALYSIS_PROMPT_UPDATED / ANALYSIS_UPDATE_SKIPPED
  -> COMPRESSION_CHECKED
  -> ROUND_METRICS_COMPUTED
  -> DATASET_STATE_UPDATED
  -> NEXT_ROUND_POLICY_PREPARED
  -> RUN_STATE_CHECKPOINTED
  -> STOP_SIGNAL_UPDATED
  -> ROUND_COMPLETED
```

关键约束：

- 一轮中生产级 extraction prompt 最多更新一次。
- analysis prompt 新版本通过 shadow evaluation 后只在下一轮生效。
- prompt version advance 与 round advance 分离；没有 accepted extraction patch 不代表优化器停止。

## 6. 动态验证与采样策略

不使用固定验证集。每轮动态抽取 validation batch，并通过分层和 rolling coverage 保证覆盖。

核心分层：

```text
label × difficulty
```

辅助分层：

```text
fragility
scenario
image_quality
historical_status
```

控制策略：

1. easy stable 样本降权；
2. hard 样本 cooldown，避免过拟合；
3. canary 样本作为安全哨兵；
4. historical fixed 样本用于回归保护；
5. toxic trigger 样本用于测毒增强。

指标应使用 weighted accuracy、moving average 和 rolling coverage，而不是单轮 raw accuracy。

## 7. Evaluation / Regression / Poisoning Protocol

抽取结果评估顺序：

```text
parse raw output
  -> schema validation
  -> primary answer extraction
  -> normalization
  -> ground truth comparison
  -> evaluation status
```

没有 Ground Truth 时，可以启用 3 轮 eval voting。投票结果必须标记为 weak label：

```yaml
is_ground_truth_backed: false
vote_count: 3
majority_status: string
confidence: float
```

Patch 测试转移定义：

```text
base wrong  -> patched correct = fixed
base correct -> patched wrong  = broken
base wrong  -> patched wrong   = unchanged_wrong
base correct -> patched correct = unchanged_correct
```

严格模式下，任何 broken 都意味着 patch toxic。

## 8. Patch Merge、Translation 与 Repair

### 8.1 Deterministic tree-reduce

基础 merge 流程：

```text
candidate patches
  -> cluster by target prompt / section / operation
  -> conflict detection
  -> duplicate removal
  -> subsumption detection
  -> merge compatible patches
  -> merge report
```

### 8.2 L0-Ln 层级归并

面向大规模 patch 时，应扩展为：

```text
L0: prompt_type / section / operation / risk buckets
L1: bucket-level deterministic merge
L2: batch semantic merge
L3: section-level summary merge
Ln/root: cross-section root audit
```

每层都必须生成 merge report，保留 input ids、output ids、dropped ids、conflict ids 和 fallback 原因。

### 8.3 Patch Translation

对于 text-level patch，需要进行 locator calibration：

1. 校准 `target_section` / `section_id`；
2. 在目标 section 内匹配 `old_text` / `target_text`；
3. 返回 match score、match method、char positions；
4. 低于阈值时标记 unresolved；
5. 绝不臆造不存在的文本。

### 8.4 Patch Repair

当 patch 因定位或可修复 schema 问题失败时，可触发 LLM repair：

```text
failed patch + failure_info + prompt structure + section content
  -> patch_translation_retry template
  -> alignment
  -> validator
  -> dry-run applier
```

repair 只允许修改 locator 字段，不得修改 payload 业务内容。

## 9. Analysis Prompt Evolution

分析提示词不能自证有效，应使用 shadow evaluation。

学习信号包括：

- judgement mismatch；
- false error；
- missed error；
- schema violation patch；
- frozen target patch；
- non-atomic patch；
- toxic patch；
- ineffective patch；
- risk prediction failure；
- overgeneralization。

MVP 可使用 deterministic hard-failure signals 生成 guard patch；增强版应让 analysis prompt patch 也进入完整 patch workflow：

```text
analysis failure clusters
  -> analysis prompt patch candidates
  -> patch validation
  -> tree-reduce merge
  -> analysis behavior suite
  -> shadow gate
  -> next-round promotion
```

Shadow gate 至少要求：

```text
schema_violation_patch_rate == 0
frozen_target_patch_rate == 0
judgement_alignment_accuracy 不下降
false_error_rate 不上升
missed_error_rate 不上升
至少一个 patch quality 指标提升
```

## 10. Compression Protocol

压缩是特殊 patch：`operation.type = COMPRESS_SECTION`。

触发条件：

```text
line_count > line_budget
或 token_count > token_budget
```

压缩候选选择：

1. 排除 frozen / output_schema / compressibility=none；
2. 优先低贡献、高冗余、高可压缩 section；
3. 每次只压缩一个 section；
4. `legacy_unmapped` 优先 MOVE_CONTENT，再压缩。

压缩接受条件：

```text
semantic_equivalence_passed
behavior_equivalence_passed
primary answer 不变
schema / parse / format 不退化
canary 不变
historical fixed 不退化
```

增强版支持 LLM prune + semantic validation + retry，但行为保持 gate 仍是最终裁决。

## 11. Few-Shot Optimization Protocol

Few-shot 只在文本 prompt 稳定后启动，并冻结文本 prompt。

流程：

```text
mine candidates
  -> generate reasoning example
  -> verify schema / GT / prompt consistency / visual groundedness
  -> individual example test
  -> slot add or replacement
  -> bundle few-shot test
  -> FewShotSetVersion promotion
```

候选来源：

- repeated wrong samples；
- high difficulty samples；
- representative error clusters；
- dynamic validation recurring errors；
- historical fixed but fragile samples。

排除：

- suspected label noise；
- model limitation；
- ambiguous / unsupported visual evidence；
- outliers。

few-shot 示例中的 reasoning 应该是给抽取模型看的示范推理，不应包含内部 patch 诊断信息。

## 12. Section 贡献度模型

Section 贡献度采用三通道：

1. **Active**：模型输出或 run metadata 中明确使用的 section；
2. **Cited**：analysis / patch 归因引用的 section；
3. **Parasite**：被引用但关联错误、毒性、无效 patch 或高回归风险的 section。

综合 score 可由以下因素构成：

```text
+ fixed_count
+ accepted_patch_count
+ active_usage_in_correct
+ cited_in_useful_analysis
- broken_count
- toxic_patch_count
- parasite_score
- compression_reject_count
```

用途：

- 优先优化高引用但高错误的 section；
- 降低高贡献 section 的压缩优先级；
- 提升相关样本动态验证和采样权重；
- 作为 prompt health 和 next-round recommendation 输入。

## 13. Prompt Health、Self-check 与 A/B Gate

Prompt health check 覆盖 H1-H7：

```text
H1 duplicate section ids
H2 render-order missing sections
H3 empty rendered sections
H4 duplicate headings
H5 frozen/compressibility conflict
H6 schema section not frozen
H7 legacy_unmapped too large
```

Prompt self-check 检查：

- 未声明占位符；
- 输出格式与 schema 不一致；
- 约束互相矛盾；
- frozen schema 被改写；
- 模板术语不一致。

A/B gate 用同一批样本比较 baseline 与 candidate prompt：

```text
candidate_accuracy >= baseline_accuracy + min_delta
schema/parse regression == 0
broken_count == 0
```

只有通过 gate 的 candidate 才能 promotion。

## 14. Scenario 配置管理

场景目录建议：

```text
scenarios/<scenario_id>/
  scenario.yaml
  optimizer.yaml
  data/
  prompts/
  schemas/
  README.md
```

Scenario config 应支持：

- 继承 base config；
- 覆盖模型、采样、patch、compression、fewshot 配置；
- 独立 run state；
- 独立 prompt snapshots；
- config hash；
- export/share 包。

CLI 应支持：

```bash
python -m mmap_optimizer.cli.main run --scenario scenarios/cabinet_cable
python -m mmap_optimizer.cli.main validate-scenario --scenario scenarios/cabinet_cable
python -m mmap_optimizer.cli.main list-scenarios
```

## 15. Checkpoint、Snapshot 与 Resume

每轮关键 stage 需要写入 run state：

```yaml
run_state:
  iteration: integer
  stage: string
  active_extraction_prompt_version_id: string
  active_analysis_prompt_version_id: string
  completed_round_ids: []
  latest_metrics_id: string | null
  fewshot_pool_path: string | null
```

Prompt mutation 前保存 snapshot：

```text
before_patch_promotion
before_analysis_promotion
before_compression_promotion
before_fewshot_promotion
```

Resume 应从 `run_state.json`、prompt snapshot、round artifacts 恢复 active state，不重复已完成 rounds。

Rollback 应支持恢复到任意 snapshot，并记录 rollback event。

## 16. Debug Event Taxonomy

建议统一事件类型：

```text
parse_fail
json_repair_attempt
patch_validation_reject
patch_repair_attempt
patch_repair_failed
semantic_merge_fallback
root_audit_reject
compression_reject
fewshot_reject
prompt_health_error
prompt_gate_reject
resume_restore
rollback_apply
guardrail_detention
```

每条事件至少包含：

```yaml
run_id: string
round_id: string
stage: string
sample_id: string | null
patch_id: string | null
prompt_version_id: string | null
reason: string
payload_hash: string | null
```

## 17. 并发执行

并发应从模型调用层开始，保证输出顺序稳定：

```text
PromptTestRunner extraction / dynamic validation
AnalysisRunner error analysis
PatchTester sample-level patch tests
FewShot behavior tests
Compression behavior tests
```

配置：

```yaml
execution:
  mode: serial | thread_pool
  max_workers: integer
  timeout_seconds: integer | null
  retry_count: integer
  rate_limit_qps: float | null
```

异常应单样本隔离，写入 RunRecord，不应直接中断整轮，除非超过失败率阈值。

## 18. 测试策略

测试不应只追求数量，而应覆盖高风险路径：

1. Prompt IR 初始化与 health；
2. schema frozen guard；
3. analysis parse / repair；
4. patch alignment / repair / text-level operations；
5. deterministic tree-reduce 与 semantic merge fallback；
6. individual / bundle patch testing；
7. compression semantic validation and behavior gate；
8. few-shot add / replace / bundle safety；
9. run_state / resume / rollback；
10. no-GT voting；
11. scenario loading；
12. concurrency ordering and failure isolation；
13. CLI paths。

## 19. MVP 到生产化路线图

### Phase A：核心闭环

- Prompt IR；
- evaluator；
- analysis parser；
- patch workflow；
- individual / bundle patch test；
- dynamic validation；
- metrics。

### Phase B：安全与可观测

- prompt health；
- snapshots；
- debug events；
- LLM step artifacts；
- prompt gates；
- run state。

### Phase C：质量增强

- L0-Ln merge；
- patch repair；
- section contribution EMA；
- semantic compression；
- analysis prompt full patch workflow。

### Phase D：场景与规模

- scenario registry；
- concurrency executor；
- resume / rollback CLI；
- dashboard / trend visualization；
- export/share scenario package。

### Phase E：few-shot 与无 GT 扩展

- persistent few-shot candidate pool；
- slot replacement；
- visual groundedness verification；
- no-GT eval voting；
- weak-label metrics。
