from __future__ import annotations

from pathlib import Path

import yaml

from applications.incident_repair.services.run_service import register_demo_agents


class _Client:
    def __init__(self):
        self.calls = []

    def create_agent(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True}


def test_demo_agents_register_explicit_heterogeneous_backends():
    client = _Client()
    registered = register_demo_agents(client, Path("examples/production_incident_demo/agents.yaml"))

    assert registered == ["architect", "coder_a", "coder_b", "tester", "repair", "reviewer"]
    by_name = {call["agent_name"]: call for call in client.calls}
    assert by_name["architect"]["backend"]["type"] == "native_planner"
    assert by_name["coder_a"]["backend"]["type"] == "codex_cli"
    assert by_name["tester"]["backend"]["type"] == "direct_tool"
    assert by_name["reviewer"]["backend"]["sandbox"] == "read-only"


def test_agents_yaml_has_no_legacy_backend_fallback_for_demo_roles():
    data = yaml.safe_load(Path("examples/production_incident_demo/agents.yaml").read_text(encoding="utf-8"))
    backends = {item["name"]: item["backend"]["type"] for item in data["agents"]}

    assert backends == {
        "architect": "native_planner",
        "coder_a": "codex_cli",
        "coder_b": "codex_cli",
        "tester": "direct_tool",
        "repair": "codex_cli",
        "reviewer": "codex_cli",
    }
