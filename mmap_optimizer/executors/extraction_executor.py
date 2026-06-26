"""ExtractionExecutor - 真实抽取执行器，接入 ModelClient。

替代系统中 extraction stage 的 mock 抽取，
通过 ``ModelClient.complete_multimodal`` 执行真实的模型调用。
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any, Literal

from ..model.client import ModelClient
from ..model.retry import FailurePolicyConfig, SampleFailureTracker
from ..stages.extraction_prompt_optimization import ExtractionResult
from ..phases.fewshot_optimization import FewshotExample
from ..data.sample import SampleBatch, SampleSet, SampleSpec
from ..prompt.structured_prompt import StructuredPrompt, StructuredPromptRenderer
from ..prompt.output_repair import parse_model_json_output


class ExtractionExecutor:
    """真实抽取执行器，接入 ModelClient。"""

    def __init__(
        self,
        model_client: ModelClient,
        model_config: dict[str, Any] | None = None,
        failure_policy: FailurePolicyConfig | None = None,
        sample_failure_tracker: SampleFailureTracker | None = None,
    ):
        self.model_client = model_client
        self.model_config = model_config or {}
        self.renderer = StructuredPromptRenderer()
        self.model_output_repairs: list[dict[str, Any]] = []
        self._last_parse_record: dict[str, Any] | None = None
        self.failure_policy = failure_policy or FailurePolicyConfig()
        self.sample_failure_tracker = sample_failure_tracker or SampleFailureTracker(
            self.failure_policy.max_consecutive_sample_failures
        )

    def execute(
        self,
        prompt: StructuredPrompt,
        batch: SampleBatch,
        sample_set: SampleSet,
        fewshot_examples: list[FewshotExample] | None = None,
    ) -> list[ExtractionResult]:
        """对 batch 中所有样本执行抽取。"""
        results: list[ExtractionResult] = []
        for sample_id in batch.sample_ids:
            spec = sample_set.specs.get(sample_id)
            if spec is None:
                continue
            try:
                result = self._execute_single(prompt, spec, fewshot_examples)
                self.sample_failure_tracker.record_success()
            except Exception as exc:
                if not self.failure_policy.skip_single_sample_failure:
                    raise
                self.sample_failure_tracker.record_failure(
                    sample_id=spec.id,
                    call_type="extraction",
                    error=exc,
                )
                result = ExtractionResult(
                    sample_id=spec.id,
                    raw_output="",
                    parsed_output=None,
                    status="invalid",
                    error_details=[f"model_call_failed: {type(exc).__name__}: {exc}"],
                )
            results.append(result)
        return results

    def _execute_single(
        self,
        prompt: StructuredPrompt,
        spec: SampleSpec,
        fewshot_examples: list[FewshotExample] | None = None,
    ) -> ExtractionResult:
        """对单个样本执行抽取。"""
        # 1. render system message
        system_text = self._render_system_message(prompt, fewshot_examples)
        # 2. build messages (system + user)
        user_message = self._build_user_message(spec)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_text},
            user_message,
        ]
        # 3. build assets list
        assets = self._build_assets(spec)
        # 4. call model_client.complete_multimodal
        response = self.model_client.complete_multimodal(
            messages=messages,
            assets=assets,
            model_config=self.model_config or None,
        )
        # 5. parse output
        parsed_output, status = self._parse_output(response.raw_output)
        if self._last_parse_record is not None:
            record = dict(self._last_parse_record)
            record["sample_id"] = spec.id
            self.model_output_repairs.append(record)
        # 6. return ExtractionResult
        return ExtractionResult(
            sample_id=spec.id,
            raw_output=response.raw_output,
            parsed_output=parsed_output,
            status=status,
        )

    def _render_system_message(
        self,
        prompt: StructuredPrompt,
        fewshot_examples: list[FewshotExample] | None = None,
    ) -> str:
        """渲染 system message。

        如果有 fewshot_examples，使用 ``render_with_fewshot``；
        否则使用 ``render_system_message``。
        """
        if fewshot_examples:
            return self.renderer.render_with_fewshot(prompt, fewshot_examples)
        return self.renderer.render_system_message(prompt)

    def _build_user_message(self, spec: SampleSpec) -> dict[str, Any]:
        """组装 user message（仅文本部分）。

        图片资产由 complete_multimodal 通过 assets 参数统一注入，
        避免重复发送。
        """
        text_parts: list[str] = []
        if spec.input:
            text_parts.append("Sample Input:")
            text_parts.append(json.dumps(spec.input, ensure_ascii=False, indent=2))
        if spec.metadata:
            text_parts.append("Metadata:")
            text_parts.append(json.dumps(spec.metadata, ensure_ascii=False, indent=2))
        text = "\n".join(text_parts).strip() or spec.id
        return {"role": "user", "content": text}

    def _build_assets(self, spec: SampleSpec) -> list[Any]:
        """构建资产列表，从 spec.assets 中提取图片资产。"""
        return [a for a in spec.assets if a.type == "image"]

    def _asset_to_url(self, asset: Any) -> str | None:
        """将资产转为 URL。

        如果 asset 有 ``local_path``，读取文件并转为 base64 data URL；
        如果 asset 有 ``uri``，直接使用。
        """
        local_path = getattr(asset, "local_path", None)
        uri = getattr(asset, "uri", None)
        if local_path:
            path = Path(local_path)
            if path.exists():
                mime_type = getattr(asset, "mime_type", None) or self._guess_mime_type(str(path))
                data = path.read_bytes()
                encoded = base64.b64encode(data).decode("ascii")
                return f"data:{mime_type};base64,{encoded}"
            # 文件不存在时回退到 uri
        return uri

    @staticmethod
    def _guess_mime_type(path: str) -> str:
        """猜测文件的 MIME 类型。"""
        mime_type, _ = mimetypes.guess_type(path)
        return mime_type or "image/png"

    def _parse_output(self, raw_output: str) -> tuple[dict | None, Literal["correct", "wrong", "invalid"]]:
        """解析模型输出。

        尝试 JSON 解析：
        - 解析成功且为 dict，返回 (parsed_dict, "correct")
        - 解析失败，尝试使用模型修复，修复成功返回 (parsed_dict, "correct")
        - 修复也失败，返回 (None, "invalid")

        注意：status 只反映解析成功/失败，不判断业务对错。
        """
        parse_result = parse_model_json_output(
            raw_output=raw_output,
            expected_schema=None,
            model_client=self.model_client,
            model_config=self.model_config,
        )
        self._last_parse_record = {
            "executor": "extraction",
            "status": parse_result.status,
            "failure_reason": parse_result.failure_reason,
            "raw_output_preview": raw_output[:500],
        }
        if isinstance(parse_result.parsed, dict):
            # 解析成功（含模型修复后成功）统一记为 "correct"
            return parse_result.parsed, "correct"
        return None, "invalid"
