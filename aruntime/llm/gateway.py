"""
LLM 统一网关 - Runtime 层
职责：封装不同 LLM 后端的调用，提供统一接口
"""

import os
import httpx
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResult:
    output: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float
    prefix_cache_hit: bool = False
    logical_context_reuse_hit: bool = False
    prefill_latency_ms: float = 0.0
    kv_cache_usage: dict | None = None

    def to_dict(self) -> dict:
        return {
            "output": self.output,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "prefix_cache_hit": self.prefix_cache_hit,
            "logical_context_reuse_hit": self.logical_context_reuse_hit,
            "prefill_latency_ms": self.prefill_latency_ms,
            "kv_cache_usage": self.kv_cache_usage or {},
        }


class LLMGateway:
    """LLM 调用网关，支持多种后端"""

    def __init__(self, backend: str = "mock", api_key: Optional[str] = None):
        self.backend = backend
        self.api_key = api_key or os.getenv("LLM_API_KEY", "") or os.getenv("DEEPSEEK_API_KEY", "")
        self.vllm_base_url = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
        self.vllm_model = os.getenv("VLLM_MODEL", "default")

    def chat(self, system_prompt: str, user_message: str) -> str:
        """统一的 LLM 调用接口"""
        return self.chat_with_stats(system_prompt, user_message).output

    def chat_with_stats(self, system_prompt: str, user_message: str, prefix_cache_hit: bool = False) -> LLMResult:
        started = time.perf_counter()
        if self.backend == "mock":
            output = self._call_mock(system_prompt, user_message)
            return self._result(output, system_prompt, user_message, started, prefix_cache_hit)
        elif self.backend == "deepseek":
            return self._call_deepseek(system_prompt, user_message, started, prefix_cache_hit)
        elif self.backend == "vllm":
            return self._call_vllm(system_prompt, user_message, started, prefix_cache_hit)
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

    def _call_mock(self, system_prompt: str, user_message: str) -> str:
        """模拟调用，返回固定文本（用于测试）"""
        return f"[Mock] 我是{system_prompt}，收到消息: {user_message[:50]}..."

    def _call_deepseek(self, system_prompt: str, user_message: str, started: float, prefix_cache_hit: bool) -> LLMResult:
        """调用 DeepSeek API"""
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }

        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            output = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            return LLMResult(
                output=output,
                input_tokens=int(usage.get("prompt_tokens") or self._estimate_tokens(system_prompt + user_message)),
                output_tokens=int(usage.get("completion_tokens") or self._estimate_tokens(output)),
                total_tokens=int(usage.get("total_tokens") or 0) or (
                    int(usage.get("prompt_tokens") or self._estimate_tokens(system_prompt + user_message))
                    + int(usage.get("completion_tokens") or self._estimate_tokens(output))
                ),
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                prefix_cache_hit=prefix_cache_hit,
                logical_context_reuse_hit=prefix_cache_hit,
            )
        except httpx.TimeoutException:
            raise RuntimeError("LLM 请求超时，请检查网络或 API 服务状态")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"LLM API 返回错误: {e.response.status_code}, {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {str(e)}")

    def _result(self, output: str, system_prompt: str, user_message: str, started: float, prefix_cache_hit: bool) -> LLMResult:
        input_tokens = self._estimate_tokens(system_prompt + user_message)
        output_tokens = self._estimate_tokens(output)
        return LLMResult(
            output=output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            prefix_cache_hit=prefix_cache_hit,
            logical_context_reuse_hit=prefix_cache_hit,
        )

    def _call_vllm(self, system_prompt: str, user_message: str, started: float, prefix_cache_hit: bool) -> LLMResult:
        url = f"{self.vllm_base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.vllm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            output = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            metrics = data.get("metrics") or {}
            input_tokens = int(usage.get("prompt_tokens") or self._estimate_tokens(system_prompt + user_message))
            output_tokens = int(usage.get("completion_tokens") or self._estimate_tokens(output))
            return LLMResult(
                output=output,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=int(usage.get("total_tokens") or (input_tokens + output_tokens)),
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                prefix_cache_hit=prefix_cache_hit,
                logical_context_reuse_hit=prefix_cache_hit,
                prefill_latency_ms=float(metrics.get("prefill_latency_ms") or 0.0),
                kv_cache_usage=metrics.get("kv_cache_usage") if isinstance(metrics.get("kv_cache_usage"), dict) else {},
            )
        except httpx.TimeoutException:
            raise RuntimeError("vLLM 请求超时，请检查服务状态")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"vLLM API 返回错误: {e.response.status_code}, {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"vLLM 调用失败: {str(e)}")

    def _estimate_tokens(self, text: str) -> int:
        return max(1, (len(text) + 3) // 4)
