"""ToxicityTestExecutor - 测毒执行器。

对候选 patch 进行 greedy 测毒测试：依次将 patch 累积应用到 base prompt，
对 toxic 样本集合逐个测试是否 break，提前停止以减少测试成本。
支持 extraction 与 analysis 两种模式。
"""

from __future__ import annotations

from typing import Any

from ..core.progress import NullProgressReporter, ProgressReporter
from ..stages.extraction_prompt_optimization import ExtractionResult
from ..patch.types import PatchTestRecord, ToxicityReport
from ..data.sample import SampleBatch, SampleSet, SampleState
from ..prompt.structured_prompt import StructuredPrompt
from .patch_apply_executor import PatchApplyExecutor


class ToxicityTestExecutor:
    """测毒执行器。

    流程：
    1. 过滤无效 patch（所有 source_sample_ids 都属于 unchanged_wrong）。
    2. 按来源样本难度（DESC）、来源样本数量（DESC）、patch_id（ASC）排序。
    3. 若 toxic_sample_ids 为空，所有非无效 patch 直接判定为 safe。
    4. Greedy 测毒循环：将 patch 累积应用到 cumulative_prompt，
       对每个 toxic 样本执行抽取/分析，若 break 则拒绝该 patch
       （early_stop 时立即停止该 patch 的剩余样本测试），
       否则接受该 patch 并更新 cumulative_prompt。
    5. 生成 ToxicityReport（含 PatchTestRecord）。
    """

    def __init__(self, patch_apply_executor: PatchApplyExecutor | None = None) -> None:
        """初始化测毒执行器。

        Args:
            patch_apply_executor: 可选的 PatchApplyExecutor 实例。
                如果未提供，内部创建默认实例。
        """
        self.patch_apply_executor = patch_apply_executor or PatchApplyExecutor()
        self.progress_reporter: ProgressReporter = NullProgressReporter()

    def test(
        self,
        base_prompt: StructuredPrompt,
        candidate_patches: list,
        toxic_sample_ids: list[str],
        sample_set: SampleSet,
        mode: str = "extraction",
        early_stop: bool = True,
        extraction_executor: Any = None,
        evaluation_executor: Any = None,
        analysis_executor: Any = None,
        extraction_results: list | None = None,
        extraction_prompt: StructuredPrompt | None = None,
        unchanged_wrong_sample_ids: list[str] | None = None,
        sample_states: dict[str, SampleState] | None = None,
    ) -> tuple[list, list, ToxicityReport]:
        """执行测毒测试。

        Args:
            base_prompt: 基础 StructuredPrompt。
            candidate_patches: 候选 patch 列表（ExtractionPatch 或 AnalysisPatch）。
            toxic_sample_ids: 中毒样本 ID 列表。
            sample_set: 样本集合。
            mode: 测毒模式，"extraction" 或 "analysis"。
            early_stop: 是否启用提前停止。
            extraction_executor: 抽取执行器（extraction 模式必需）。
            evaluation_executor: 评估执行器（extraction 模式必需）。
            analysis_executor: 分析执行器（analysis 模式必需）。
            extraction_results: 抽取结果列表（analysis 模式必需，按 sample_id 查找）。
            extraction_prompt: 抽取 prompt（analysis 模式必需）。
            unchanged_wrong_sample_ids: 未变化错误样本 ID 列表，
                用于过滤无效 patch。如果 None，则不过滤。
            sample_states: 样本状态字典（sample_id -> SampleState），
                用于难度排序。如果 None，使用 sample_set.states，
                再缺失则难度视为 0。

        Returns:
            (safe_patches, toxic_patches, report) 元组。
        """
        # ------------------------------------------------------------------
        # Step 1: 过滤无效 patch（所有 source_sample_ids 都属于 unchanged_wrong）
        # ------------------------------------------------------------------
        unchanged_wrong_set = set(unchanged_wrong_sample_ids or [])
        ineffective_patches: list = []
        effective_patches: list = []

        for patch in candidate_patches:
            if (
                unchanged_wrong_set
                and patch.source_sample_ids
                and all(sid in unchanged_wrong_set for sid in patch.source_sample_ids)
            ):
                patch.status = "rejected"
                patch.rejection_reason = "INEFFECTIVE"
                ineffective_patches.append(patch)
            else:
                effective_patches.append(patch)

        # ------------------------------------------------------------------
        # Step 2: 按难度排序
        # ------------------------------------------------------------------
        states_lookup = sample_states if sample_states is not None else sample_set.states

        def _difficulty_of(patch) -> float:
            if not patch.source_sample_ids:
                return 0.0
            scores: list[float] = []
            for sid in patch.source_sample_ids:
                state = states_lookup.get(sid) if states_lookup else None
                scores.append(state.difficulty_score if state else 0.0)
            return max(scores) if scores else 0.0

        sorted_patches = sorted(
            effective_patches,
            key=lambda p: (
                -_difficulty_of(p),
                -len(p.source_sample_ids),
                p.id,
            ),
        )

        # ------------------------------------------------------------------
        # Step 3: 处理 toxic_sample_ids 为空的情况
        # ------------------------------------------------------------------
        safe_patches: list = []
        toxic_patches: list = []
        patch_test_records: list[PatchTestRecord] = []

        if not toxic_sample_ids:
            for patch in self.progress_reporter.iter(
                sorted_patches,
                desc="Toxicity testing patches",
                total=len(sorted_patches),
            ):
                patch.status = "candidate_safe"
                patch.rejection_reason = None
                safe_patches.append(patch)
                patch_test_records.append(
                    PatchTestRecord(
                        patch_id=patch.id,
                        status="skipped",
                        stop_reason="NO_TOXIC_SAMPLES",
                    )
                )

            report = ToxicityReport(
                id=f"toxicity_report_{base_prompt.id}",
                tested_patch_count=len(sorted_patches),
                toxic_patch_count=0,
                safe_patch_count=len(safe_patches),
                toxic_patches=[],
                safe_patches=[p.id for p in safe_patches],
                toxic_sample_ids=list(toxic_sample_ids),
                metadata={
                    "skipped_reason": "NO_TOXIC_SAMPLES",
                    "ineffective_patch_count": len(ineffective_patches),
                    "ineffective_patch_ids": [p.id for p in ineffective_patches],
                },
                mode=mode,
                safe_patch_ids=[p.id for p in safe_patches],
                toxic_patch_ids=[],
                patch_test_records=[r.to_dict() for r in patch_test_records],
                early_stop_enabled=early_stop,
            )
            return safe_patches, toxic_patches, report

        # ------------------------------------------------------------------
        # Step 4: Greedy 测毒循环
        # ------------------------------------------------------------------
        cumulative_prompt = base_prompt

        # 预构建 extraction_results 查找表（analysis 模式）
        extraction_result_map: dict[str, ExtractionResult] = {}
        if mode == "analysis" and extraction_results:
            for result in extraction_results:
                extraction_result_map[result.sample_id] = result

        for patch in self.progress_reporter.iter(
            sorted_patches,
            desc="Toxicity testing patches",
            total=len(sorted_patches),
        ):
            trial_prompt, _ = self.patch_apply_executor.apply(cumulative_prompt, [patch])

            broken_found = False
            tested_sample_ids: list[str] = []
            broken_sample_ids: list[str] = []
            fixed_sample_ids: list[str] = []
            stop_reason: str | None = None

            with self.progress_reporter.progress(
                total=len(toxic_sample_ids),
                desc=f"Patch {patch.id}",
            ) as bar:
                for sample_id in toxic_sample_ids:
                    tested_sample_ids.append(sample_id)

                    is_broken = self._test_single_sample(
                        mode=mode,
                        trial_prompt=trial_prompt,
                        sample_id=sample_id,
                        sample_set=sample_set,
                        extraction_executor=extraction_executor,
                        evaluation_executor=evaluation_executor,
                        analysis_executor=analysis_executor,
                        extraction_prompt=extraction_prompt,
                        extraction_result_map=extraction_result_map,
                    )
                    bar.update(1)

                    if is_broken:
                        broken_sample_ids.append(sample_id)
                        broken_found = True
                        if early_stop:
                            stop_reason = "EARLY_STOP_BROKEN"
                            break

            if broken_found:
                patch.status = "rejected"
                patch.rejection_reason = "TOXIC"
                toxic_patches.append(patch)
                # 不更新 cumulative_prompt
            else:
                patch.status = "candidate_safe"
                patch.rejection_reason = None
                safe_patches.append(patch)
                cumulative_prompt = trial_prompt  # 累积 safe patch

            patch_test_records.append(
                PatchTestRecord(
                    patch_id=patch.id,
                    status="toxic" if broken_found else "safe",
                    tested_sample_ids=tested_sample_ids,
                    broken_sample_ids=broken_sample_ids,
                    fixed_sample_ids=fixed_sample_ids,
                    stop_reason=stop_reason,
                )
            )

        # ------------------------------------------------------------------
        # Step 5: 生成 ToxicityReport
        # ------------------------------------------------------------------
        safe_ids = [p.id for p in safe_patches]
        toxic_ids = [p.id for p in toxic_patches]

        report = ToxicityReport(
            id=f"toxicity_report_{base_prompt.id}",
            tested_patch_count=len(sorted_patches),
            toxic_patch_count=len(toxic_patches),
            safe_patch_count=len(safe_patches),
            toxic_patches=toxic_ids,
            safe_patches=safe_ids,
            toxic_sample_ids=list(toxic_sample_ids),
            metadata={
                "ineffective_patch_count": len(ineffective_patches),
                "ineffective_patch_ids": [p.id for p in ineffective_patches],
                "mode": mode,
                "early_stop": early_stop,
            },
            mode=mode,
            safe_patch_ids=safe_ids,
            toxic_patch_ids=toxic_ids,
            patch_test_records=[r.to_dict() for r in patch_test_records],
            early_stop_enabled=early_stop,
        )

        return safe_patches, toxic_patches, report

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _test_single_sample(
        self,
        mode: str,
        trial_prompt: StructuredPrompt,
        sample_id: str,
        sample_set: SampleSet,
        extraction_executor: Any,
        evaluation_executor: Any,
        analysis_executor: Any,
        extraction_prompt: StructuredPrompt | None,
        extraction_result_map: dict[str, ExtractionResult],
    ) -> bool:
        """对单个样本测试 trial_prompt 是否 break。

        Args:
            mode: "extraction" 或 "analysis"。
            trial_prompt: 应用 patch 后的 trial prompt。
            sample_id: 待测样本 ID。
            sample_set: 样本集合。
            extraction_executor: 抽取执行器。
            evaluation_executor: 评估执行器。
            analysis_executor: 分析执行器。
            extraction_prompt: 抽取 prompt（analysis 模式必需）。
            extraction_result_map: sample_id -> ExtractionResult 查找表。

        Returns:
            True 表示该样本被 break（结果不正确），False 表示未 break。
        """
        spec = sample_set.specs.get(sample_id)
        ground_truth = spec.ground_truth if spec is not None else {}

        # 构造单样本 batch
        batch = SampleBatch(
            id=f"toxicity_batch_{sample_id}",
            phase="toxicity_test",
            iteration=0,
            sample_ids=[sample_id],
            sampler_name="toxicity_test",
        )

        if mode == "extraction":
            # extraction 模式：抽取 + 评估
            if extraction_executor is None or evaluation_executor is None:
                return False

            extraction_results = extraction_executor.execute(
                prompt=trial_prompt,
                batch=batch,
                sample_set=sample_set,
            )
            if not extraction_results:
                return True  # 没有结果视为 break

            extraction_result = extraction_results[0]
            eval_record = evaluation_executor.evaluate(
                extraction_result=extraction_result,
                ground_truth=ground_truth,
            )
            return not eval_record.correct

        # analysis 模式：分析
        if analysis_executor is None:
            return False

        extraction_result = extraction_result_map.get(sample_id)
        if extraction_result is None:
            # 没有对应的 extraction_result，构造一个空的
            extraction_result = ExtractionResult(
                sample_id=sample_id,
                raw_output="",
                parsed_output=None,
                status="invalid",
            )

        if extraction_prompt is None:
            return False

        if spec is None:
            return False

        analysis_result = analysis_executor.execute(
            analysis_prompt=trial_prompt,
            extraction_prompt=extraction_prompt,
            extraction_result=extraction_result,
            sample_spec=spec,
        )
        return not analysis_result.analysis_correct


__all__ = ["ToxicityTestExecutor"]
