"""
集成测试：资源感知调度（需要 agentd）
"""
import subprocess
import os
import sys
import time
import httpx
import pytest


@pytest.fixture(scope="module")
def agentd_server():
    """
    带 RESOURCE_AWARE=true 的 agentd 服务。
    通过相同名称覆盖 conftest.py 的 fixture。
    """
    env = os.environ.copy()
    env["LLM_BACKEND"] = "mock"
    env["LLM_API_KEY"] = ""
    env["SCHEDULER_TYPE"] = "dag"
    env["RESOURCE_AWARE"] = "true"

    try:
        subprocess.run(
            ["fuser", "-k", "8234/tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        pass

    env["AGENTD_STATE_DB"] = f"/tmp/agent-runtime-os/state-resource-aware-{int(time.time() * 1000)}.db"
    proc = subprocess.Popen(
        [sys.executable, "-m", "aruntime.daemon.main"],
        cwd=os.path.join(os.path.dirname(__file__), "..", "..", ".."),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 15
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            with httpx.Client(base_url="http://127.0.0.1:8234", timeout=1, trust_env=False) as c:
                resp = c.get("/metrics")
                if resp.status_code == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.25)
    if not ready:
        out = ""
        err = ""
        try:
            out = proc.stdout.read().decode("utf-8", errors="ignore") if proc.stdout else ""
            err = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
        except Exception:
            pass
        proc.terminate()
        proc.wait()
        raise RuntimeError(f"resource-aware agentd failed to start\nstdout:\n{out}\nstderr:\n{err}")
    yield
    proc.terminate()
    proc.wait()


@pytest.fixture
def client(agentd_server):
    with httpx.Client(base_url="http://127.0.0.1:8234", timeout=10, trust_env=False) as c:
        yield c


def wait_task_done(client, task_id: str, timeout_s: float = 10.0) -> dict:
    start = time.time()
    while time.time() - start < timeout_s:
        resp = client.get(f"/tasks/{task_id}")
        if resp.status_code != 200:
            time.sleep(0.2)
            continue
        data = resp.json()
        if data["status"] in ("SUCCESS", "FAILED"):
            return data
        time.sleep(0.2)
    raise AssertionError(f"任务未在 {timeout_s}s 内完成: {task_id}")


class TestResourceAwareIntegration:
    """验证资源感知调度在 agentd 中正常工作"""

    def test_metrics_contains_resource_snapshot(self, client):
        """开启资源感知后 /metrics 返回 resource 字段"""
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "resource" in data, f"metrics 应包含 resource 字段: {data.keys()}"
        resource = data["resource"]
        assert "cpu_percent" in resource
        assert "mem_percent" in resource
        assert "llm_active_agents" in resource
        assert "llm_total_concurrent" in resource
        assert "usage" in resource
        assert "leases" in resource
        assert "reclaimed" in resource

    def test_task_executes_normally_with_resource_aware(self, client):
        """资源感知模式下任务正常执行并完成"""
        suffix = str(int(time.time() * 1000))
        agent_name = f"ra_test_{suffix}"
        client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })
        resp = client.post("/tasks", json={
            "agent_name": agent_name,
            "task_input": {"request": "资源感知测试"},
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        data = wait_task_done(client, task_id, timeout_s=20.0)
        assert data["status"] == "SUCCESS"

    def test_multiple_tasks_execute(self, client):
        """连续提交多个任务，全部成功完成"""
        suffix = str(int(time.time() * 1000))
        agents = []
        for i in range(3):
            name = f"ra_multi_{i}_{suffix}"
            agents.append(name)
            client.post("/agents", json={
                "agent_name": name,
                "role": "测试员",
            })

        task_ids = []
        for i, name in enumerate(agents):
            resp = client.post("/tasks", json={
                "agent_name": name,
                "task_input": {"request": f"任务{i}"},
            })
            assert resp.status_code == 200
            task_ids.append(resp.json()["task_id"])

        for tid in task_ids:
            data = wait_task_done(client, tid, timeout_s=20.0)
            assert data["status"] == "SUCCESS", f"任务 {tid} 失败: {data}"

    def test_dag_dependency_with_resource_aware(self, client):
        """DAG 依赖任务在资源感知模式下正确执行"""
        suffix = str(int(time.time() * 1000))
        planner = f"ra_planner_{suffix}"
        coder = f"ra_coder_{suffix}"

        client.post("/agents", json={"agent_name": planner, "role": "规划者"})
        client.post("/agents", json={"agent_name": coder, "role": "编码者"})

        resp1 = client.post("/tasks", json={
            "agent_name": planner,
            "task_input": {"request": "制定计划"},
        })
        assert resp1.status_code == 200
        p_task = resp1.json()["task_id"]

        resp2 = client.post("/tasks", json={
            "agent_name": coder,
            "task_input": {"request": "写代码"},
            "dependencies": [p_task],
        })
        assert resp2.status_code == 200
        c_task = resp2.json()["task_id"]

        p_data = wait_task_done(client, p_task, timeout_s=20.0)
        assert p_data["status"] == "SUCCESS"

        c_data = wait_task_done(client, c_task, timeout_s=20.0)
        assert c_data["status"] == "SUCCESS", f"coder 任务失败: {c_data}"

    def test_agent_status_transitions(self, client):
        """验证资源感知模式下 Agent 状态转换正常"""
        suffix = str(int(time.time() * 1000))
        name = f"ra_lifecycle_{suffix}"
        client.post("/agents", json={"agent_name": name, "role": "观察者"})

        agents = client.get("/agents").json()["agents"]
        agent = next(a for a in agents if a["name"] == name)
        assert agent["status"] == "READY"

        resp = client.post("/tasks", json={
            "agent_name": name,
            "task_input": {"request": "hello"},
        })
        task_id = resp.json()["task_id"]
        wait_task_done(client, task_id, timeout_s=20.0)

        agents = client.get("/agents").json()["agents"]
        agent = next(a for a in agents if a["name"] == name)
        assert agent["status"] == "COMPLETED"
