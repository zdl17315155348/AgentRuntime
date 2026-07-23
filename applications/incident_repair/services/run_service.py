from __future__ import annotations

import asyncio
import time
from pathlib import Path
from uuid import uuid4

import yaml

from aruntime.api.client import AgentRuntimeClient
from applications.incident_repair.config import GraphRuntimeContext, IncidentRunConfig
from applications.incident_repair.execution.factory import create_execution_provider
from applications.incident_repair.runner import IncidentGraphRunner
from applications.incident_repair.services.summary_aggregator import RunSummaryAggregator
from applications.incident_repair.services.event_bus import RunEventBus
from applications.incident_repair.services.patch_integration import PatchIntegrationService
from applications.incident_repair.services.run_store import RunStore


class IncidentRunService:
    def __init__(self, store: RunStore | None = None, runner: IncidentGraphRunner | None = None):
        self.store = store or RunStore()
        self.runner = runner or IncidentGraphRunner()

    async def start_run(self, config: IncidentRunConfig, user_request: str, dependencies: dict | None = None) -> dict:
        run_dir = self.store.run_dir(config.run_id)
        bus = RunEventBus(config.run_id, config.thread_id, config.execution_mode.value, run_dir / "unified_events.jsonl")
        provider = create_execution_provider(config, dependencies or {})
        context = GraphRuntimeContext(provider=provider, run_config=config, event_bus=bus, integration_service=(dependencies or {}).get("integration_service") or PatchIntegrationService())
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
            "all_patch_refs": [],
            "pending_patch_refs": [],
            "integrated_commit": None,
            "integration_result": None,
            "test_summary": None,
            "review_summary": None,
            "repair_round": 0,
            "workflow_status": "PENDING",
            "error": None,
            "runtime_task_ids": [],
            "execution_records": [],
            "event_count": 0,
            "completed_coder_task_ids": [],
            "active_coder_task": None,
            "coder_step": 0,
            "coder_integration_history": [],
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
            final_state = await asyncio.wait_for(self.runner.run(state, context), timeout=config.workflow_timeout_s)
            status = final_state.get("workflow_status") or "SUCCESS"
            error = final_state.get("error")
        except (asyncio.TimeoutError, TimeoutError):
            provider = context.provider
            if hasattr(provider, "cancel_run"):
                await provider.cancel_run(config.run_id)
            final_state = {**state, "workflow_status": "FAILED", "error": f"workflow timeout after {config.workflow_timeout_s}s"}
            status = "FAILED"
            error = final_state["error"]
            context.event_bus.emit("langgraph", "graph.run.failed", attributes={"error": error})
        except Exception as exc:
            final_state = state
            status = "FAILED"
            error = str(exc)
            context.event_bus.emit("langgraph", "graph.run.failed", attributes={"error": error})
        finished = time.time()
        context.event_bus.emit("langgraph", "graph.run.completed", attributes={"status": status})
        events = self.store.load_events(config.run_id) if hasattr(self.store, "load_events") else []
        provider = context.provider
        summary = RunSummaryAggregator().build(
            config,
            final_state,
            events,
            final_state.get("execution_records", []),
            provider_snapshot=await _maybe_snapshot(provider) if hasattr(provider, "get_execution_snapshot") else {},
        )
        summary.update(
            {
                "status": status,
                "finished_at": finished,
                "duration_ms": round((finished - started) * 1000, 3),
            }
        )
        if error:
            summary["error"] = error
        self.store.write_json(config.run_id, "graph_state.json", final_state)
        self.store.write_json(config.run_id, "summary.json", summary)
        return {"run_id": config.run_id, "thread_id": config.thread_id, "state": final_state, "summary": summary}


async def _maybe_snapshot(provider) -> dict:
    snapshot = provider.get_execution_snapshot("")
    if hasattr(snapshot, "__await__"):
        snapshot = await snapshot
    return snapshot or {}


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
