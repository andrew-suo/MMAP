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
from ..core.progress import NullProgressReporter, ProgressReporter
from ..stages.extraction_prompt_optimization import ExtractionResult
from ..phases.fewshot_optimization import FewshotExample
from ..data.sample import SampleAsset, SampleBatch, SampleSet, SampleSpec
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
        self.progress_reporter: ProgressReporter = NullProgressReporter()

    def execute(
        self,
        prompt: StructuredPrompt,
        batch: SampleBatch,
        sample_set: SampleSet,
        fewshot_examples: list[FewshotExample] | None = None,
    ) -> list[ExtractionResult]:
        """对 batch 中所有样本执行抽取。"""
        results: list[ExtractionResult] = []
        correct_count = wrong_count = invalid_count = 0
        for sample_id in self.progress_reporter.iter(
            batch.sample_ids,
            desc="Extracting samples",
            total=len(batch.sample_ids),
        ):
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
            if result.status == "correct":
                correct_count += 1
            elif result.status == "wrong":
                wrong_count += 1
            else:
                invalid_count += 1
        return results

    def _execute_single(
        self,
        prompt: StructuredPrompt,
        spec: SampleSpec,
        fewshot_examples: list[FewshotExample] | None = None,
    ) -> ExtractionResult:
        """对单个样本执行抽取。"""
        # 1. build messages
        messages: list[dict[str, Any]]
        if fewshot_examples and any(self._example_has_images(ex) for ex in fewshot_examples):
            # 多模态 few-shot：示例作为 user/assistant 轮次，图片内联
            messages = self._build_multimodal_fewshot_messages(prompt, spec, fewshot_examples)
        else:
            # 文本 few-shot（写进 system prompt）或无 few-shot
            system_text = self._render_system_message(prompt, fewshot_examples)
            user_message = self._build_user_message(spec)
            messages = [
                {"role": "system", "content": system_text},
                user_message,
            ]
        # 2. build assets list（始终只含当前样本图片）
        assets = self._build_assets(spec)
        # 3. call model_client.complete_multimodal
        response = self.model_client.complete_multimodal(
            messages=messages,
            assets=assets,
            model_config=self.model_config or None,
        )
        # 4. parse output
        parsed_output, status = self._parse_output(response.raw_output)
        if self._last_parse_record is not None:
            record = dict(self._last_parse_record)
            record["sample_id"] = spec.id
            self.model_output_repairs.append(record)
        # 5. return ExtractionResult
        return ExtractionResult(
            sample_id=spec.id,
            raw_output=response.raw_output,
            parsed_output=parsed_output,
            status=status,
        )

    @staticmethod
    def _example_has_images(example: FewshotExample) -> bool:
        """判断 few-shot 示例是否含真实图片。"""
        images = getattr(example, "input_images", None) or []
        return any(bool(img) for img in images)

    def _build_multimodal_fewshot_messages(
        self,
        prompt: StructuredPrompt,
        spec: SampleSpec,
        fewshot_examples: list[FewshotExample],
    ) -> list[dict[str, Any]]:
        """多模态 few-shot：示例作为 user/assistant 轮次，图片内联在 user content parts。

        system prompt 不再包含 few-shot section（改用 ``render_system_message``）。
        当前样本仍走字符串 user 消息，其图片由 ``complete_multimodal`` 通过
        ``assets`` 注入到最后一条 user 消息。
        """
        system_text = self.renderer.render_system_message(prompt)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_text},
        ]
        for example in fewshot_examples:
            messages.append(self._build_fewshot_user_message(example))
            messages.append(self._build_fewshot_assistant_message(example))
        messages.append(self._build_user_message(spec))
        return messages

    def _build_fewshot_user_message(self, example: FewshotExample) -> dict[str, Any]:
        """构造 few-shot 示例的 user 消息（文本 + 内联图片 content parts）。"""
        content_parts: list[dict[str, Any]] = []
        input_text = getattr(example, "input_text", "") or ""
        if input_text:
            content_parts.append({"type": "text", "text": f"Few-shot Example Input:\n{input_text}"})
        example_id = getattr(example, "id", "") or "fewshot"
        for idx, img_str in enumerate(getattr(example, "input_images", []) or []):
            if not img_str:
                continue
            url = self._image_string_to_url(img_str, example_id, idx)
            if url:
                content_parts.append({"type": "image_url", "image_url": {"url": url}})
        if not content_parts:
            content_parts.append({"type": "text", "text": ""})
        return {"role": "user", "content": content_parts}

    def _build_fewshot_assistant_message(self, example: FewshotExample) -> dict[str, Any]:
        """构造 few-shot 示例的 assistant 消息（示例输出文本）。"""
        output_text = getattr(example, "output_text", "") or ""
        if not output_text:
            output_data = getattr(example, "output_data", {}) or {}
            output_text = json.dumps(output_data, ensure_ascii=False)
        return {"role": "assistant", "content": f"Few-shot Example Output:\n{output_text}"}

    def _image_string_to_url(self, img_str: str, owner_id: str, idx: int) -> str | None:
        """把 few-shot 图片字符串（文件路径或 URI）转成 data URL 或 URI。

        复用 ``_asset_to_url``：本地文件路径 → base64 data URL；其他视为 URI 原样返回。
        """
        asset = self._image_string_to_sample_asset(img_str, owner_id, idx)
        return self._asset_to_url(asset)

    def _image_string_to_sample_asset(
        self,
        img_str: str,
        owner_id: str,
        idx: int,
    ) -> SampleAsset:
        """把图片字符串包装成 SampleAsset，便于复用 ``_asset_to_url``。"""
        path = Path(img_str)
        if path.exists():
            return SampleAsset(
                id=f"{owner_id}_img_{idx}",
                sample_id=owner_id,
                type="image",
                local_path=img_str,
                mime_type=self._guess_mime_type(img_str),
            )
        return SampleAsset(
            id=f"{owner_id}_img_{idx}",
            sample_id=owner_id,
            type="image",
            uri=img_str,
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
