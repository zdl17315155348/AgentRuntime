from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import yaml

from aruntime.api.client import AgentRuntimeClient
from applications.incident_repair.config import GraphRuntimeContext, IncidentRunConfig
from applications.incident_repair.execution.factory import create_execution_provider
from applications.incident_repair.runner import IncidentGraphRunner
from applications.incident_repair.services.event_bus import RunEventBus
from applications.incident_repair.services.run_store import RunStore


class IncidentRunService:
    def __init__(self, store: RunStore | None = None, runner: IncidentGraphRunner | None = None):
        self.store = store or RunStore()
        self.runner = runner or IncidentGraphRunner()

    async def start_run(self, config: IncidentRunConfig, user_request: str, dependencies: dict | None = None) -> dict:
        run_dir = self.store.run_dir(config.run_id)
        bus = RunEventBus(config.run_id, config.thread_id, config.execution_mode.value, run_dir / "unified_events.jsonl")
        provider = create_execution_provider(config, dependencies or {})
        context = GraphRuntimeContext(provider=provider, run_config=config, event_bus=bus)
        started = time.time()
        bus.emit("langgraph", "graph.run.started")
        state = {
            "run_id": config.run_id,
            "thread_id": config.thread_id,
            "user_request": user_request,
            "source_repo": config.source_repo,
            "base_commit": config.base_commit,
            "plan": None,
            "planned_tasks": [],
            "patch_refs": [],
            "integrated_commit": None,
            "test_summary": None,
            "review_summary": None,
            "repair_round": 0,
            "workflow_status": "PENDING",
            "error": None,
            "runtime_task_ids": [],
            "event_count": 0,
            "active_coder_task": None,
        }
        self.store.write_json(config.run_id, "run_config.json", config.model_dump(mode="json"))
        self.store.write_environment(config.run_id, config.source_repo)
        summary = {
            "run_id": config.run_id,
            "execution_mode": config.execution_mode.value,
            "status": "CREATED",
            "started_at": started,
            "finished_at": None,
            "duration_ms": 0,
            "graph": {"nodes_started": 0, "nodes_completed": 0, "repair_rounds": 0},
            "execution": {"tasks": 0, "attempts": 0, "queue_wait_ms": 0, "backend_ms": 0, "setup_ms": 0},
            "faults": {"injected": 0, "worker_lost": 0, "fallbacks": 0, "recovery_ms": 0},
            "resources": {"peak_rss_mb": 0, "cpu_time_ms": 0, "oom_count": 0},
            "context": {"recovery_hits": 0, "repeat_file_reads": 0, "token_saving_ratio": 0},
            "result": {"patch_non_empty": False, "pytest_returncode": None, "review_approved": False},
        }
        self.store.write_json(config.run_id, "graph_state.json", state)
        self.store.write_json(config.run_id, "summary.json", summary)
        self.store.write_replay_manifest(config.run_id)
        return {"run_id": config.run_id, "thread_id": config.thread_id, "context": context, "state": state, "summary": summary}

    async def execute_run(self, config: IncidentRunConfig, user_request: str, dependencies: dict | None = None, bundle: dict | None = None) -> dict:
        bundle = bundle or await self.start_run(config, user_request, dependencies)
        context = bundle["context"]
        state = bundle["state"]
        started = bundle["summary"]["started_at"]
        try:
            final_state = await self.runner.run(state, context)
            status = final_state.get("workflow_status") or "SUCCESS"
            error = final_state.get("error")
        except Exception as exc:
            final_state = state
            status = "FAILED"
            error = str(exc)
            context.event_bus.emit("langgraph", "graph.run.failed", attributes={"error": error})
        finished = time.time()
        context.event_bus.emit("langgraph", "graph.run.completed", attributes={"status": status})
        summary = bundle["summary"]
        summary.update(
            {
                "status": status,
                "finished_at": finished,
                "duration_ms": round((finished - started) * 1000, 3),
                "graph": {
                    "nodes_started": 0,
                    "nodes_completed": 0,
                    "repair_rounds": int(final_state.get("repair_round", 0)),
                },
                "execution": {
                    "tasks": len(final_state.get("runtime_task_ids", [])),
                    "attempts": 0,
                    "queue_wait_ms": 0,
                    "backend_ms": 0,
                    "setup_ms": 0,
                },
                "result": {
                    "patch_non_empty": bool(final_state.get("patch_refs")),
                    "pytest_returncode": (final_state.get("test_summary") or {}).get("returncode"),
                    "review_approved": bool((final_state.get("review_summary") or {}).get("approved")),
                },
            }
        )
        if error:
            summary["error"] = error
        self.store.write_json(config.run_id, "graph_state.json", final_state)
        self.store.write_json(config.run_id, "summary.json", summary)
        return {"run_id": config.run_id, "thread_id": config.thread_id, "state": final_state, "summary": summary}


def new_run_config(**kwargs) -> IncidentRunConfig:
    kwargs.setdefault("run_id", f"run_{uuid4().hex}")
    kwargs.setdefault("thread_id", f"thread_{uuid4().hex}")
    return IncidentRunConfig(**kwargs)


def register_demo_agents(client: AgentRuntimeClient, agents_file: str | Path = "examples/production_incident_demo/agents.yaml") -> list[str]:
    path = Path(agents_file)
    agents = yaml.safe_load(path.read_text(encoding="utf-8"))["agents"]
    registered: list[str] = []
    for item in agents:
        try:
            client.create_agent(
                agent_name=item["name"],
                role=item.get("role", item["name"]),
                system_prompt=item.get("system_prompt", ""),
                capability=item.get("capability", {}),
                backend=item.get("backend", {"type": "legacy_llm"}),
            )
        except TypeError:
            client.create_agent(item["name"], item.get("role", item["name"]), item.get("system_prompt", ""))
        except Exception as exc:
            if "已存在" not in str(exc):
                raise
        registered.append(item["name"])
    return registered
