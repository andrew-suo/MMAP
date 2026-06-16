from __future__ import annotations

import json
from typing import Any

from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.templates import build_default_template_registry


def repair_json_with_model(raw_text: str, model_client: ModelClient, model_config: dict[str, Any] | None = None) -> str:
    template = build_default_template_registry().get("json_fix")
    prompt = template.render(raw_text=raw_text or "")
    response = model_client.complete(
        [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps({"raw_text": raw_text}, ensure_ascii=False)}],
        model_config=model_config,
        response_format=template.output_contract,
    )
    return response.raw_output.strip()
