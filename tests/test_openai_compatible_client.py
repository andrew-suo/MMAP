import base64

from mmap_optimizer.data.sample import SampleAsset
from mmap_optimizer.model.openai_compatible import OpenAICompatibleClient


class RecordingOpenAICompatibleClient(OpenAICompatibleClient):
    def __init__(self, default_model_config=None):
        super().__init__(
            base_url="https://example.test",
            api_key="secret",
            model="vision-model",
            default_model_config=default_model_config,
        )
        self.payloads = []
        self.timeouts = []

    def _post_json(self, payload, *, timeout=120):
        self.payloads.append(payload)
        self.timeouts.append(timeout)
        return {"id": "resp_1", "choices": [{"message": {"content": '{"result":"OK"}'}}], "usage": {"total_tokens": 10}}


def test_complete_multimodal_embeds_local_image_as_data_url(tmp_path):
    image_path = tmp_path / "sample.png"
    image_bytes = b"fake-png-bytes"
    image_path.write_bytes(image_bytes)
    client = RecordingOpenAICompatibleClient()

    response = client.complete_multimodal(
        messages=[{"role": "system", "content": "system"}, {"role": "user", "content": {"sample_id": "s1"}}],
        assets=[SampleAsset(id="a1", sample_id="s1", local_path=str(image_path), mime_type="image/png")],
        model_config={"temperature": 0.2, "max_tokens": 99},
    )

    assert response.raw_output == '{"result":"OK"}'
    assert response.metadata["asset_count"] == 1
    payload = client.payloads[0]
    assert payload["model"] == "vision-model"
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 99
    user_content = payload["messages"][1]["content"]
    assert user_content[0] == {"type": "text", "text": '{"sample_id": "s1"}'}
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")


def test_complete_multimodal_forwards_remote_image_url_with_detail():
    client = RecordingOpenAICompatibleClient()

    client.complete_multimodal(
        messages=[{"role": "user", "content": "inspect this"}],
        assets=[SampleAsset(id="a1", sample_id="s1", uri="https://cdn.example/image.jpg", mime_type="image/jpeg", metadata={"openai_image_detail": "high"})],
    )

    image_part = client.payloads[0]["messages"][0]["content"][1]
    assert image_part == {"type": "image_url", "image_url": {"url": "https://cdn.example/image.jpg", "detail": "high"}}


def test_complete_uses_default_model_config_timeout_and_max_tokens():
    client = RecordingOpenAICompatibleClient(
        default_model_config={
            "model": "vision-model",
            "temperature": 0.3,
            "max_tokens": 2049,
            "timeout": 66,
        }
    )

    client.complete(messages=[{"role": "user", "content": "hi"}])

    payload = client.payloads[0]
    assert payload["max_tokens"] == 2049
    assert payload["temperature"] == 0.3
    assert client.timeouts == [66]
