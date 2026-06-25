# AnalysisExecutor 设计调整方案

## 一、当前实现 vs 用户设计 差异对比

| 项目 | 当前实现 | 用户设计 | 差异 |
|------|---------|---------|------|
| 调用方式 | `complete()` 文本 | `complete_multimodal()` 多模态（带图片） | 重大 |
| 输入内容 | 包含 ground truth | **不包含 ground truth**（盲评） | 重大 |
| 输出内容 | is_correct + error_reason + patch_suggestion | is_correct + 分析理由（无 patch） | 重大 |
| Patch 生成 | AnalysisExecutor 生成 extraction patch_suggestion | 不在 analysis 阶段生成 patch | 重大 |
| Reflection 触发 | （在 analysis 阶段中） | 所有盲评错误都触发 | 中等 |
| Reflection 输入 | 文本，包含 GT | 多模态，包含 GT | 中等 |

## 二、核心设计变更

### 2.1 Analysis 阶段改为「盲评」

**目标**：模拟人工看图判断 extraction 是否正确，不看 GT。

**变更点**：
1. 调用方式从 `complete()` → `complete_multimodal()`
2. User message 中移除 ground truth 字段
3. System prompt 移除对 GT 的依赖
4. 不再生成 patch_suggestion
5. 输出仍包含：is_correct、分析理由（confirmed_facts, hypothesized_error_causes 等）

### 2.2 Patch 生成移到 PatchGenerationExecutor

**目标**：AnalysisExecutor 只做盲评判断，Patch 由专门的执行器生成。

**变更点**：
1. AnalysisResult 移除 `patch_suggestion` 字段
2. PatchGenerationExecutor 改为基于 `error_reason` + `judgement` 中的分析理由生成 patch
3. 保留 `analysis_correct` 作为是否生成 patch 的依据

### 2.3 Reflection 改为多模态

**目标**：reflection 也能看图反思。

**变更点**：
1. reflect() 方法从 `complete()` → `complete_multimodal()`
2. 传入图片资产
3. 所有盲评错误都触发 reflection（当前可能已有此逻辑，需确认）

## 三、详细修改清单

### 3.1 修改 prompts/analysis.txt（系统提示词）

**修改内容**：
- 移除对 ground truth 的引用
- 改为「基于图片和抽取结果进行盲评」
- 移除 patch_candidates 相关内容（analysis 不生成 patch）
- 保留：judgement.is_correct、confirmed_facts、hypothesized_error_causes、prompt_section_attribution

### 3.2 修改 prompts/analysis_task.txt（用户消息模板）

**修改内容**：
- 移除 `# Ground Truth` 部分
- 保留 extraction result、sample input

### 3.3 修改 prompts/analysis_reflection.txt（反思模板）

**修改内容**：
- 确认 reflection 是否需要多模态（当前是文本，改为多模态）
- 保留 GT 用于反思

### 3.4 修改 AnalysisExecutor

**主要变更**：

| 位置 | 修改 |
|------|------|
| `execute()` | 改为 `complete_multimodal()` 调用 |
| `execute()` | 移除 `patch_suggestion` 生成逻辑 |
| `reflect()` | 改为 `complete_multimodal()` 调用 |
| `_build_analysis_messages()` | 移除 GT 相关内容构建 |
| `_build_analysis_messages()` | 新增 `_build_assets()` 方法（参考 ExtractionExecutor） |
| `_build_reflection_messages()` | 新增资产构建 |
| `_parse_judgement()` | 不再解析 `patch_suggestion` |
| `_build_patch_suggestion()` | 删除该方法 |
| `AnalysisResult` | 移除 `patch_suggestion` 字段 |

### 3.5 修改 PatchGenerationExecutor

**主要变更**：
- `generate_extraction_patches()` 不再从 `analysis_result.patch_suggestion` 取
- 改为基于 `analysis_result.error_reason` + `judgement` 中的分析内容构造 patch
- 保持 (draft, validated, rejected) 返回格式不变

### 3.6 修改 AnalysisResult 数据结构

**文件**：`stages/extraction_prompt_optimization.py`

**修改**：
- 移除 `patch_suggestion` 字段
- `to_dict()` / `from_dict()` 同步更新

### 3.7 修改 Stage 中 Patch 生成的调用

**文件**：`stages/extraction_prompt_optimization.py`

**确认**：Step 4 调用 PatchGenerationExecutor 的逻辑是否需要调整

### 3.8 更新测试文件

**文件**：`tests/test_core.py` 等
- 更新相关测试用例

## 四、数据流变更

### 当前数据流
```
ExtractionResult → AnalysisExecutor → AnalysisResult (含 patch_suggestion)
                                        ↓
                                  PatchGenerationExecutor
                                        ↓
                                  ExtractionPatch[]
```

### 新数据流
```
ExtractionResult + 图片 → AnalysisExecutor(盲评) → AnalysisResult (无 patch_suggestion)
                                                         ↓
                                                  PatchGenerationExecutor
                                                  (基于 error_reason + 分析理由生成)
                                                         ↓
                                                  ExtractionPatch[]
```

## 五、风险与注意事项

1. **多模态调用成本**：改为 complete_multimodal 后，analysis 阶段成本会增加
2. **盲评准确率**：没有 GT 参考，模型判断准确性可能下降
3. **Patch 质量下降**：从模型生成 patch → 基于 error_reason 构造，质量可能降低
4. **兼容风险**：需要确保下游阶段不依赖 AnalysisResult.patch_suggestion

## 六、文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `prompts/analysis.txt` | 修改 | 移除 GT 引用，移除 patch 生成要求 |
| `prompts/analysis_task.txt` | 修改 | 移除 ground truth 部分 |
| `prompts/analysis_reflection.txt` | 确认 | 确认 reflection 是否需要调整 |
| `mmap_optimizer/executors/analysis_executor.py` | 重构 | 多模态调用、移除 patch 生成、盲评模式 |
| `mmap_optimizer/executors/patch_generation_executor.py` | 修改 | 从 error_reason 生成 patch，不依赖 patch_suggestion |
| `mmap_optimizer/stages/extraction_prompt_optimization.py` | 修改 | 更新 AnalysisResult 定义 |
| `mmap_optimizer/stages/analysis_prompt_optimization.py` | 确认 | 检查是否有影响 |
| `tests/test_core.py` | 更新 | 更新测试用例 |

## 七、验证步骤

1. 运行 `test_core.py`，确保所有测试通过
2. 检查 AnalysisResult 中不再有 patch_suggestion
3. 验证 PatchGenerationExecutor 仍能正常生成 patch
4. 确认 analysis 阶段使用 complete_multimodal 调用
5. 确认 user message 中不包含 ground truth