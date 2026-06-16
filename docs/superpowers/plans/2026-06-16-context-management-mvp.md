# Context Management MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal context management mechanism that supports context reuse, compression, isolation, metrics, and task execution injection.

**Architecture:** Add a small `aruntime.context` package with a Pydantic context model and an in-memory `ContextManager`. The daemon owns one manager instance, records context from submitted tasks, builds per-agent execution context before dispatching to worker, and exposes context metrics through `/metrics`.

**Tech Stack:** Python 3.10+, Pydantic v2, FastAPI, pytest, existing openEuler Docker scripts.

---

## File Structure

- Create `aruntime/context/__init__.py`: package exports for the context manager.
- Create `aruntime/context/manager.py`: `RuntimeContext` model and `ContextManager` implementation.
- Create `testing/unittest/context/test_manager.py`: unit tests for reuse, isolation, compression, and metrics.
- Modify `scripts/test_unit.sh`: include `testing/unittest/context/` in non-daemon unit tests.
- Modify `aruntime/daemon/main.py`: initialize the manager, capture context data on task submission, inject context into worker task payload, and add metrics.
- Modify `testing/unittest/daemon/test_lifecycle.py`: integration coverage for context injection and metrics.
- Modify `README.md`: update current progress and test description after implementation.

The MVP is intentionally in-memory only. Disk persistence and KV cache-specific scheduling are later work.

---

### Task 1: Context Manager Unit

**Files:**
- Create: `aruntime/context/__init__.py`
- Create: `aruntime/context/manager.py`
- Create: `testing/unittest/context/test_manager.py`
- Modify: `scripts/test_unit.sh`

- [ ] **Step 1: Write the failing tests**

Create `testing/unittest/context/test_manager.py`:

```python
from aruntime.context.manager import ContextManager


def test_context_reuse_shared_and_private_data():
    manager = ContextManager(compress_threshold_chars=1000)

    first = manager.record_task_context(
        context_id="ctx-code-repair",
        agent_name="planner",
        shared_data={"repo": "agent-runtime-os"},
        private_data={"note": "planner-only"},
    )
    second = manager.record_task_context(
        context_id="ctx-code-repair",
        agent_name="coder",
        shared_data={"plan": "fix tests"},
        private_data={"note": "coder-only"},
    )

    assert first.context_id == "ctx-code-repair"
    assert second.context_id == "ctx-code-repair"
    assert manager.get_context("ctx-code-repair").shared_data == {
        "repo": "agent-runtime-os",
        "plan": "fix tests",
    }
    assert manager.build_agent_context("ctx-code-repair", "planner") == {
        "context_id": "ctx-code-repair",
        "shared": {"repo": "agent-runtime-os", "plan": "fix tests"},
        "private": {"note": "planner-only"},
        "compressed": False,
    }
    assert manager.build_agent_context("ctx-code-repair", "coder") == {
        "context_id": "ctx-code-repair",
        "shared": {"repo": "agent-runtime-os", "plan": "fix tests"},
        "private": {"note": "coder-only"},
        "compressed": False,
    }


def test_private_data_is_isolated_per_agent():
    manager = ContextManager(compress_threshold_chars=1000)

    manager.record_task_context(
        context_id="ctx-isolation",
        agent_name="agent-a",
        shared_data={"visible": True},
        private_data={"secret": "a"},
    )
    manager.record_task_context(
        context_id="ctx-isolation",
        agent_name="agent-b",
        private_data={"secret": "b"},
    )

    assert manager.build_agent_context("ctx-isolation", "agent-a")["private"] == {"secret": "a"}
    assert manager.build_agent_context("ctx-isolation", "agent-b")["private"] == {"secret": "b"}


def test_context_is_compressed_when_over_threshold():
    manager = ContextManager(compress_threshold_chars=20)

    ctx = manager.record_task_context(
        context_id="ctx-large",
        agent_name="planner",
        shared_data={"long": "abcdefghijklmnopqrstuvwxyz"},
        private_data={"note": "private"},
    )

    assert ctx.compressed is True
    assert ctx.shared_data["__compressed_summary__"].startswith("Context compressed from ")
    assert manager.build_agent_context("ctx-large", "planner")["compressed"] is True


def test_metrics_track_reuse_and_compression():
    manager = ContextManager(compress_threshold_chars=20)

    manager.record_task_context(
        context_id="ctx-metrics",
        agent_name="planner",
        shared_data={"long": "abcdefghijklmnopqrstuvwxyz"},
    )
    manager.record_task_context(
        context_id="ctx-metrics",
        agent_name="coder",
        shared_data={"next": "step"},
    )
    manager.build_agent_context("ctx-metrics", "planner")

    metrics = manager.get_metrics()
    assert metrics["total_contexts"] == 1
    assert metrics["reuse_hits"] == 1
    assert metrics["compression_count"] >= 1
    assert metrics["build_hits"] == 1
```

Update `scripts/test_unit.sh` so the pytest command includes the new context tests:

```bash
python3 -m pytest testing/unittest/core/ testing/unittest/scheduler/ testing/unittest/context/ testing/unittest/api/ testing/unittest/comm/ -v
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m pytest testing/unittest/context/test_manager.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'aruntime.context'`.

- [ ] **Step 3: Implement the minimal context manager**

Create `aruntime/context/__init__.py`:

```python
from aruntime.context.manager import ContextManager, RuntimeContext

__all__ = ["ContextManager", "RuntimeContext"]
```

Create `aruntime/context/manager.py`:

```python
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RuntimeContext(BaseModel):
    context_id: str
    shared_data: dict[str, Any] = Field(default_factory=dict)
    private_data: dict[str, dict[str, Any]] = Field(default_factory=dict)
    compressed: bool = False
    token_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ContextManager:
    def __init__(self, compress_threshold_chars: int = 4000):
        self._contexts: dict[str, RuntimeContext] = {}
        self._compress_threshold_chars = compress_threshold_chars
        self._reuse_hits = 0
        self._compression_count = 0
        self._build_hits = 0

    def get_context(self, context_id: str) -> RuntimeContext | None:
        return self._contexts.get(context_id)

    def record_task_context(
        self,
        context_id: str,
        agent_name: str,
        shared_data: dict[str, Any] | None = None,
        private_data: dict[str, Any] | None = None,
    ) -> RuntimeContext:
        ctx = self._contexts.get(context_id)
        if ctx is None:
            ctx = RuntimeContext(context_id=context_id)
            self._contexts[context_id] = ctx
        else:
            self._reuse_hits += 1

        if shared_data:
            ctx.shared_data.update(shared_data)
        if private_data:
            current_private = ctx.private_data.get(agent_name, {})
            current_private.update(private_data)
            ctx.private_data[agent_name] = current_private

        ctx.updated_at = datetime.now()
        self._refresh_size(ctx)
        self._compress_if_needed(ctx)
        return ctx

    def build_agent_context(self, context_id: str, agent_name: str) -> dict[str, Any]:
        ctx = self._contexts.get(context_id)
        if ctx is None:
            return {
                "context_id": context_id,
                "shared": {},
                "private": {},
                "compressed": False,
            }
        self._build_hits += 1
        return {
            "context_id": ctx.context_id,
            "shared": dict(ctx.shared_data),
            "private": dict(ctx.private_data.get(agent_name, {})),
            "compressed": ctx.compressed,
        }

    def get_metrics(self) -> dict[str, int]:
        return {
            "total_contexts": len(self._contexts),
            "reuse_hits": self._reuse_hits,
            "compression_count": self._compression_count,
            "build_hits": self._build_hits,
            "total_tokens_estimate": sum(ctx.token_count for ctx in self._contexts.values()),
        }

    def _refresh_size(self, ctx: RuntimeContext) -> None:
        raw = json.dumps(
            {"shared": ctx.shared_data, "private": ctx.private_data},
            ensure_ascii=False,
            sort_keys=True,
        )
        ctx.token_count = max(1, len(raw) // 4)

    def _compress_if_needed(self, ctx: RuntimeContext) -> None:
        raw = json.dumps(
            {"shared": ctx.shared_data, "private": ctx.private_data},
            ensure_ascii=False,
            sort_keys=True,
        )
        if len(raw) <= self._compress_threshold_chars:
            return
        if ctx.compressed and "__compressed_summary__" in ctx.shared_data:
            return

        summary = f"Context compressed from {len(raw)} chars; shared_keys={sorted(ctx.shared_data.keys())}"
        ctx.shared_data = {"__compressed_summary__": summary}
        ctx.compressed = True
        self._compression_count += 1
        self._refresh_size(ctx)
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
python3 -m pytest testing/unittest/context/test_manager.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Run unit test entry**

Run:

```bash
bash scripts/test_unit.sh
```

Expected: existing unit tests plus the new context tests pass.

- [ ] **Step 6: Commit**

```bash
git add aruntime/context/__init__.py aruntime/context/manager.py testing/unittest/context/test_manager.py scripts/test_unit.sh
git commit -m "feat: add context manager"
```

---

### Task 2: Daemon Context Integration

**Files:**
- Modify: `aruntime/daemon/main.py`
- Modify: `testing/unittest/daemon/test_lifecycle.py`

- [ ] **Step 1: Write the failing integration tests**

Append these tests to `testing/unittest/daemon/test_lifecycle.py` inside `TestAgentLifecycleAPI`:

```python
    def test_task_context_is_injected_into_worker_input(self, client):
        resp = client.post("/agents", json={
            "agent_name": "ctx_worker",
            "role": "context-test",
            "system_prompt": "echo context",
        })
        assert resp.status_code == 200

        submit = client.post("/tasks", json={
            "agent_name": "ctx_worker",
            "context_id": "ctx-worker-1",
            "task_input": {
                "request": "use context",
                "context": {
                    "shared": {"repo": "agent-runtime-os"},
                    "private": {"local_note": "worker-only"},
                },
            },
        })
        assert submit.status_code == 200
        task_id = submit.json()["task_id"]

        result = self._wait_for_task(client, task_id)
        assert result["status"] == "SUCCESS"
        output = result["result"]["output"]
        assert "runtime_context" in output
        assert "agent-runtime-os" in output
        assert "worker-only" in output

    def test_metrics_include_context_snapshot(self, client):
        resp = client.post("/agents", json={
            "agent_name": "ctx_metrics",
            "role": "context-metrics",
            "system_prompt": "metrics context",
        })
        assert resp.status_code == 200

        submit = client.post("/tasks", json={
            "agent_name": "ctx_metrics",
            "context_id": "ctx-metrics-1",
            "task_input": {
                "request": "record context",
                "context": {
                    "shared": {"phase": "mvp"},
                    "private": {"owner": "ctx_metrics"},
                },
            },
        })
        assert submit.status_code == 200
        self._wait_for_task(client, submit.json()["task_id"])

        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        context_metrics = metrics.json()["context"]
        assert context_metrics["total_contexts"] >= 1
        assert context_metrics["build_hits"] >= 1
```

If `TestAgentLifecycleAPI` does not already have `_wait_for_task`, add this helper method to that class:

```python
    def _wait_for_task(self, client, task_id: str, timeout_s: float = 10.0):
        import time

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            resp = client.get(f"/tasks/{task_id}")
            assert resp.status_code == 200
            data = resp.json()
            if data["status"] in ("SUCCESS", "FAILED"):
                return data
            time.sleep(0.2)
        raise AssertionError(f"task {task_id} did not finish")
```

- [ ] **Step 2: Run the integration tests and verify they fail**

Run:

```bash
python3 -m pytest testing/unittest/daemon/test_lifecycle.py::TestAgentLifecycleAPI::test_task_context_is_injected_into_worker_input testing/unittest/daemon/test_lifecycle.py::TestAgentLifecycleAPI::test_metrics_include_context_snapshot -v
```

Expected: FAIL because daemon does not yet inject `runtime_context` and `/metrics` does not include `context`.

- [ ] **Step 3: Add daemon context manager initialization**

In `aruntime/daemon/main.py`, add the import near the other imports:

```python
from aruntime.context.manager import ContextManager
```

After `resource_monitor: ResourceMonitor | None = None`, add:

```python
context_config = config.get("context", {})
context_manager = ContextManager(
    compress_threshold_chars=int(context_config.get("compress_threshold_chars", 4000))
)
```

- [ ] **Step 4: Record context data during task submission**

In `submit_task`, after dependency validation and before constructing `TaskSpec`, add:

```python
    if req.context_id:
        raw_context = req.task_input.get("context", {})
        if isinstance(raw_context, dict):
            shared_data = raw_context.get("shared", {})
            private_data = raw_context.get("private", {})
            context_manager.record_task_context(
                context_id=req.context_id,
                agent_name=req.agent_name,
                shared_data=shared_data if isinstance(shared_data, dict) else {},
                private_data=private_data if isinstance(private_data, dict) else {},
            )
```

In `submit_dynamic_task`, after parent validation and before constructing `TaskSpec`, add the same block using `req.context_id`, `req.task_input`, and `req.agent_name`.

- [ ] **Step 5: Inject runtime context into worker payload**

In `scheduling_loop`, after:

```python
            user_message = str(task.task_input)
```

add:

```python
            task_payload = dict(task.task_input)
            if task.context_id:
                task_payload["runtime_context"] = context_manager.build_agent_context(
                    task.context_id,
                    task.agent_name,
                )
                user_message = str(task_payload)
```

Then replace the `send_event` payload field:

```python
                            "task_input": task.task_input,
```

with:

```python
                            "task_input": task_payload,
```

- [ ] **Step 6: Expose context metrics**

In the `/metrics` handler, before returning `result`, add:

```python
    result["context"] = context_manager.get_metrics()
```

- [ ] **Step 7: Run the focused integration tests**

Run:

```bash
python3 -m pytest testing/unittest/daemon/test_lifecycle.py::TestAgentLifecycleAPI::test_task_context_is_injected_into_worker_input testing/unittest/daemon/test_lifecycle.py::TestAgentLifecycleAPI::test_metrics_include_context_snapshot -v
```

Expected: both tests pass.

- [ ] **Step 8: Run daemon lifecycle integration tests**

Run:

```bash
python3 -m pytest testing/unittest/daemon/test_lifecycle.py -v
```

Expected: all lifecycle integration tests pass.

- [ ] **Step 9: Commit**

```bash
git add aruntime/daemon/main.py testing/unittest/daemon/test_lifecycle.py
git commit -m "feat: inject task context in daemon"
```

---

### Task 3: Client API Context Coverage

**Files:**
- Modify: `testing/unittest/api/test_client.py`

- [ ] **Step 1: Write the client behavior test**

Add this test to `testing/unittest/api/test_client.py`:

```python
def test_submit_task_sends_context_payload(httpx_mock):
    from aruntime.api.client import AgentRuntimeClient

    httpx_mock.add_response(
        method="POST",
        url="http://127.0.0.1:8234/tasks",
        json={"task_id": "task_ctx", "status": "PENDING"},
    )

    client = AgentRuntimeClient()
    try:
        result = client.submit_task(
            agent_name="planner",
            context_id="ctx-client",
            task_input={
                "request": "plan",
                "context": {
                    "shared": {"repo": "agent-runtime-os"},
                    "private": {"note": "planner"},
                },
            },
        )
    finally:
        client.close()

    request = httpx_mock.get_request()
    assert result["task_id"] == "task_ctx"
    assert request.read()
    assert b'"context_id":"ctx-client"' in request.content
    assert b'"repo":"agent-runtime-os"' in request.content
```

- [ ] **Step 2: Run the client test**

Run:

```bash
python3 -m pytest testing/unittest/api/test_client.py::test_submit_task_sends_context_payload -v
```

Expected: PASS. `AgentRuntimeClient.submit_task()` already forwards `task_input` and `context_id`; this test locks the behavior.

- [ ] **Step 3: Run API unit tests**

Run:

```bash
python3 -m pytest testing/unittest/api/ -v
```

Expected: all API unit tests pass.

- [ ] **Step 4: Commit**

```bash
git add testing/unittest/api/test_client.py
git commit -m "test: cover client context payload"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update current progress**

In `README.md` under `## 当前进度`, add:

```markdown
上下文管理：支持按 `context_id` 复用上下文，区分 shared / private 数据，支持超阈值压缩，并在 `/metrics` 输出上下文统计。
```

- [ ] **Step 2: Update testing description**

Under the unit test list in `README.md`, add:

```markdown
context/test_manager.py:上下文管理器单元测试（上下文复用、shared/private 隔离、压缩与 metrics）。
```

- [ ] **Step 3: Add task context payload example**

Add this example after the existing `/tasks` curl example:

```markdown
带上下文的任务示例：

```bash
curl -s -X POST http://127.0.0.1:8234/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "agent_name":"planner",
    "context_id":"ctx-code-repair-1",
    "task_input":{
      "request":"制定修复计划",
      "context":{
        "shared":{"repo":"agent-runtime-os"},
        "private":{"note":"planner local note"}
      }
    }
  }'
```
```

- [ ] **Step 4: Review README formatting**

Run:

```bash
python3 -m pytest testing/unittest/context/test_manager.py -v
```

Expected: PASS. This confirms the documented context module still imports and works.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe context management"
```

---

### Task 5: openEuler Docker Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run the required project test entry in openEuler Docker**

Run:

```bash
bash scripts/test_docker_openeuler.sh
```

Expected:

```text
== unit ==
...
== integration (no resource_aware) ==
...
== integration (resource_aware=true) ==
...
== smoke ==
...
```

All collected tests should pass. If no real LLM key is mounted through `configs/runtime.json` or `SMOKE_LLM_API_KEY`, the smoke section should print that it is skipped.

- [ ] **Step 2: If Docker is blocked by local permissions, rerun with approved escalation**

Use the same command:

```bash
bash scripts/test_docker_openeuler.sh
```

Expected: openEuler container builds and runs tests.

- [ ] **Step 3: Record final status**

Run:

```bash
git status --short --branch
```

Expected: branch is clean except for unrelated pre-existing files such as `.codex-local/`.

---

## Self-Review

- Spec coverage: the plan covers context reuse, shared/private isolation, compression, daemon injection, metrics, client coverage, docs, and required Docker openEuler verification.
- Placeholder scan: no `TBD`, `TODO`, or undefined later work remains in the implementation tasks.
- Type consistency: the same `ContextManager`, `RuntimeContext`, `context_id`, `shared`, `private`, and `runtime_context` names are used across tests, daemon integration, and docs.
