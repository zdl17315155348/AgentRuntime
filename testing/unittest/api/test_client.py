import pytest

from aruntime.api.client import AgentRuntimeClient


class _Resp:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _HTTP:
    def __init__(self):
        self.last_post = None
        self.last_get = None

    def post(self, url: str, json: dict):
        self.last_post = {"url": url, "json": json}
        if url.endswith("/messages"):
            return _Resp({"message_id": "m1", "from_agent": json["from_agent"], "to_agent": json["to_agent"], "payload": json["payload"], "topic": json.get("topic") or None})
        if url.endswith("/kill") or url.endswith("/restart"):
            return _Resp({"agent_name": "a", "status": "READY"})
        return _Resp({"task_id": "t1", "status": "PENDING"})

    def get(self, url: str, params: dict | None = None):
        self.last_get = {"url": url, "params": params}
        if "/messages/" in url:
            return _Resp({"messages": [{"message_id": "m1"}]})
        return _Resp({"task_id": "t1", "status": "SUCCESS"})


def test_submit_task_sends_dependencies_and_priority():
    c = AgentRuntimeClient(base_url="http://example")
    http = _HTTP()
    c.client = http

    resp = c.submit_task(
        "agent",
        {"request": "x"},
        context_id="ctx",
        priority=7,
        dependencies=["a", "b"],
    )
    assert resp["task_id"] == "t1"
    assert http.last_post["url"] == "http://example/tasks"
    assert http.last_post["json"]["agent_name"] == "agent"
    assert http.last_post["json"]["context_id"] == "ctx"
    assert http.last_post["json"]["priority"] == 7
    assert http.last_post["json"]["dependencies"] == ["a", "b"]


def test_get_task_hits_task_endpoint():
    c = AgentRuntimeClient(base_url="http://example")
    http = _HTTP()
    c.client = http

    data = c.get_task("t1")
    assert data["status"] == "SUCCESS"
    assert http.last_get["url"] == "http://example/tasks/t1"


def test_send_message_hits_messages_endpoint():
    c = AgentRuntimeClient(base_url="http://example")
    http = _HTTP()
    c.client = http

    resp = c.send_message("a", "b", {"x": 1}, topic="t")
    assert resp["message_id"] == "m1"
    assert http.last_post["url"] == "http://example/messages"
    assert http.last_post["json"]["from_agent"] == "a"
    assert http.last_post["json"]["to_agent"] == "b"
    assert http.last_post["json"]["payload"] == {"x": 1}
    assert http.last_post["json"]["topic"] == "t"


def test_recv_messages_hits_messages_endpoint_with_limit():
    c = AgentRuntimeClient(base_url="http://example")
    http = _HTTP()
    c.client = http

    resp = c.recv_messages("b", limit=7)
    assert resp["messages"][0]["message_id"] == "m1"
    assert http.last_get["url"] == "http://example/messages/b"
    assert http.last_get["params"] == {"limit": 7}


def test_kill_and_restart_agent_hit_endpoints():
    c = AgentRuntimeClient(base_url="http://example")
    http = _HTTP()
    c.client = http

    c.kill_agent("a")
    assert http.last_post["url"] == "http://example/agents/a/kill"

    c.restart_agent("a")
    assert http.last_post["url"] == "http://example/agents/a/restart"
