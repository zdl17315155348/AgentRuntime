"""
LLM 统一网关 - Runtime 层
职责：封装不同 LLM 后端的调用，提供统一接口
"""

import os
import httpx
from typing import Optional


class LLMGateway:
    """LLM 调用网关，支持多种后端"""

    def __init__(self, backend: str = "mock", api_key: Optional[str] = None):
        self.backend = backend
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")

    def chat(self, system_prompt: str, user_message: str) -> str:
        """统一的 LLM 调用接口"""
        if self.backend == "mock":
            return self._call_mock(system_prompt, user_message)
        elif self.backend == "deepseek":
            return self._call_deepseek(system_prompt, user_message)
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

    def _call_mock(self, system_prompt: str, user_message: str) -> str:
        """模拟调用，返回固定文本（用于测试）"""
        return f"[Mock] 我是{system_prompt}，收到消息: {user_message[:50]}..."

    def _call_deepseek(self, system_prompt: str, user_message: str) -> str:
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
            return data["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            raise RuntimeError("LLM 请求超时，请检查网络或 API 服务状态")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"LLM API 返回错误: {e.response.status_code}, {e.response.text}")
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {str(e)}")