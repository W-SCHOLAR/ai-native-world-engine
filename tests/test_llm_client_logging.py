import json
import logging

from ai_native_world_engine.core.llm_provider import OpenAICompatibleJsonClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(
            {
                "choices": [
                    {"message": {"content": '{"summary":"model answer","effects":[]}'}}
                ]
            }
        ).encode("utf-8")


def test_llm_response_is_logged_without_api_key(monkeypatch, caplog) -> None:
    from ai_native_world_engine.core import llm_provider

    monkeypatch.setenv("AI_NATIVE_WORLD_LOG_LLM_RESPONSES", "1")
    monkeypatch.setattr(llm_provider.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    caplog.set_level(logging.INFO, logger=llm_provider.__name__)

    output = OpenAICompatibleJsonClient(
        api_key="secret-token",
        base_url="https://example.test/v1",
        model="debug-model",
        max_tokens=777,
    ).complete({"instructions": "Return JSON"})

    assert output.output["summary"] == "model answer"
    assert "model answer" in caplog.text
    assert "debug-model" in caplog.text
    assert "secret-token" not in caplog.text


def test_llm_client_records_secret_safe_request_phase_metadata(monkeypatch) -> None:
    from ai_native_world_engine.core import llm_provider

    captured = {}

    def fake_urlopen(http_request, timeout):
        captured["payload"] = json.loads(http_request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(llm_provider.request, "urlopen", fake_urlopen)
    client = OpenAICompatibleJsonClient(
        api_key="secret-token",
        base_url="https://example.test/v1",
        model="debug-model",
        timeout=12.0,
        max_tokens=888,
        thinking_mode="disabled",
    )

    result = client.complete({"instructions": "Return JSON", "context_packet": {"id": "context"}})

    assert captured["payload"]["max_tokens"] == 888
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert captured["timeout"] == 12.0
    assert result.runtime_metadata["request_bytes"] > 0
    assert result.runtime_metadata["response_bytes"] > 0
    assert result.runtime_metadata["max_tokens"] == 888
    assert result.runtime_metadata["total_latency_ms"] >= 0
    assert result.runtime_metadata["stable_prefix_bytes"] > 0
    assert len(result.runtime_metadata["stable_prefix_sha256"]) == 64
    assert result.runtime_metadata["dynamic_message_bytes"] > 0
    assert "instructions" not in json.loads(captured["payload"]["messages"][1]["content"])
    assert "secret-token" not in str(result.runtime_metadata)
