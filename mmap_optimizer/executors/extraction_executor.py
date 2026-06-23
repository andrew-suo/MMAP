"""ExtractionExecutor - 真实抽取执行器，接入 ModelClient。

替代系统中 extraction stage 的 mock 抽取，
通过 ``ModelClient.complete_multimodal`` 执行真实的模型调用。
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

from ..model.client import ModelClient
from ..extraction_prompt_optimization_stage import ExtractionResult
from ..fewshot_optimization_phase import FewshotExample
from ..sample import SampleBatch, SampleSet, SampleSpec
from ..structured_prompt import StructuredPrompt, StructuredPromptRenderer


class ExtractionExecutor:
    """真实抽取执行器，接入 ModelClient。"""

    def __init__(self, model_client: ModelClient, model_config: dict[str, Any] | None = None):
        self.model_client = model_client
        self.model_config = model_config or {}
        self.renderer = StructuredPromptRenderer()

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
            result = self._execute_single(prompt, spec, fewshot_examples)
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
        """组装 user message。

        包含样本文本和 metadata。如果有图片资产，构造多模态 content
        （text + image_url parts），参考 OpenAI message 格式。
        """
        text_parts: list[str] = []
        if spec.input:
            text_parts.append("Sample Input:")
            text_parts.append(json.dumps(spec.input, ensure_ascii=False, indent=2))
        if spec.metadata:
            text_parts.append("Metadata:")
            text_parts.append(json.dumps(spec.metadata, ensure_ascii=False, indent=2))
        text = "\n".join(text_parts).strip() or spec.id

        image_assets = [a for a in spec.assets if a.type == "image"]
        if not image_assets:
            return {"role": "user", "content": text}

        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for asset in image_assets:
            url = self._asset_to_url(asset)
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})
        return {"role": "user", "content": content}

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

    def _parse_output(self, raw_output: str) -> tuple[dict | None, str]:
        """解析模型输出。

        尝试 JSON 解析：
        - 解析成功且为 dict，返回 (parsed_dict, "correct")
        - 解析失败，返回 (None, "invalid")

        注意：status 只反映解析成功/失败，不判断业务对错。
        """
        try:
            parsed = json.loads(raw_output)
        except (json.JSONDecodeError, TypeError):
            return None, "invalid"
        if not isinstance(parsed, dict):
            return None, "invalid"
        return parsed, "correct"
