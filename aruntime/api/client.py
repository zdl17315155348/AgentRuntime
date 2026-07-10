"""Agent Runtime 客户端 SDK"""
import httpx
from typing import Optional


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
        priority: int = 0,
        dependencies: Optional[list[str]] = None,
        failure_policy: Optional[dict | str] = None,
        on_failure: Optional[dict[str, str]] = None,
    ) -> dict:
        payload: dict = {
            "agent_name": agent_name,
            "task_input": task_input,
            "context_id": context_id,
            "priority": priority,
        }
        if dependencies is not None:
            payload["dependencies"] = dependencies
        if failure_policy is not None:
            payload["failure_policy"] = failure_policy
        if on_failure is not None:
            payload["on_failure"] = on_failure
        resp = self.client.post(
            f"{self.base_url}/tasks",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def get_task(self, task_id: str) -> dict:
        resp = self.client.get(f"{self.base_url}/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()

    def send_message(
        self,
        from_agent: str,
        to_agent: str,
        payload: dict,
        topic: str = "",
    ) -> dict:
        resp = self.client.post(
            f"{self.base_url}/messages",
            json={
                "from_agent": from_agent,
                "to_agent": to_agent,
                "payload": payload,
                "topic": topic,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def recv_messages(self, agent_name: str, limit: int = 50) -> dict:
        resp = self.client.get(
            f"{self.base_url}/messages/{agent_name}",
            params={"limit": limit},
        )
        resp.raise_for_status()
        return resp.json()

    def get_metrics(self) -> dict:
        resp = self.client.get(f"{self.base_url}/metrics")
        resp.raise_for_status()
        return resp.json()

    def kill_agent(self, agent_name: str) -> dict:
        resp = self.client.post(f"{self.base_url}/agents/{agent_name}/kill", json={})
        resp.raise_for_status()
        return resp.json()

    def restart_agent(self, agent_name: str) -> dict:
        resp = self.client.post(f"{self.base_url}/agents/{agent_name}/restart", json={})
        resp.raise_for_status()
        return resp.json()

    def close(self):
        self.client.close()
