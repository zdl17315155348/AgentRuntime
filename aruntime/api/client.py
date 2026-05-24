"""Agent Runtime 客户端 SDK"""
import httpx
from typing import Optional, Dict, Any


class AgentRuntimeClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8234"):
        self.base_url = base_url
        self.client = httpx.Client(timeout=30)

    def create_agent(
        self,
        agent_name: str,
        role: str,
        system_prompt: str = "",
        model: str = "gpt-4o-mini",
        max_retries: int = 3,
    ) -> dict:
        resp = self.client.post(
            f"{self.base_url}/agents",
            json={
                "agent_name": agent_name,
                "role": role,
                "system_prompt": system_prompt,
                "model": model,
                "max_retries": max_retries,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def submit_task(
        self,
        agent_name: str,
        task_input: dict,
        context_id: str = "",
    ) -> dict:
        resp = self.client.post(
            f"{self.base_url}/tasks",
            json={
                "agent_name": agent_name,
                "task_input": task_input,
                "context_id": context_id,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def get_metrics(self) -> dict:
        resp = self.client.get(f"{self.base_url}/metrics")
        resp.raise_for_status()
        return resp.json()

    def close(self):
        self.client.close()