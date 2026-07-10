from aruntime.llm.gateway import LLMGateway


def test_mock_gateway_returns_token_usage_and_latency():
    gateway = LLMGateway(backend="mock")

    result = gateway.chat_with_stats("system", "hello", prefix_cache_hit=True)

    assert result.output.startswith("[Mock]")
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    assert result.total_tokens == result.input_tokens + result.output_tokens
    assert result.latency_ms >= 0
    assert result.prefix_cache_hit is True
