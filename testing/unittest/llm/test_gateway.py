from aruntime.llm.gateway import LLMGateway
import pytest


def test_mock_gateway_returns_token_usage_and_latency():
    gateway = LLMGateway(backend="mock")

    result = gateway.chat_with_stats("system", "hello", prefix_cache_hit=True)

    assert result.output.startswith("[Mock]")
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    assert result.total_tokens == result.input_tokens + result.output_tokens
    assert result.latency_ms >= 0
    assert result.prefix_cache_hit is True


def test_deepseek_gateway_uses_configured_model(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr("aruntime.llm.gateway.httpx.post", fake_post)
    gateway = LLMGateway(backend="deepseek", api_key="key", model="deepseek-v4-flash")

    gateway.chat_with_stats("system", "hello")

    assert captured["json"]["model"] == "deepseek-v4-flash"


def test_deepseek_gateway_rejects_empty_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    gateway = LLMGateway(backend="deepseek", api_key="", model="deepseek-v4-flash")

    with pytest.raises(RuntimeError, match="LLM_API_KEY 或 DEEPSEEK_API_KEY 未设置"):
        gateway.chat_with_stats("system", "hello")
