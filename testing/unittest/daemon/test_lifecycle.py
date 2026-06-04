"""
集成测试：通过 agentd API 验证 Agent 完整生命周期
"""

import pytest
import httpx
import time


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

class TestAgentLifecycleAPI:
    """测试 Agent 在 agentd 中的完整生命周期"""

    def test_create_agent(self, client):
        """创建 Agent 后状态为 READY"""
        suffix = str(int(time.time() * 1000))
        agent_name = f"lifecycle_test_create_{suffix}"
        resp = client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "READY"

    def test_list_agents_shows_status(self, client):
        """列出 Agent 应包含状态信息"""
        suffix = str(int(time.time() * 1000))
        agent_name = f"lifecycle_test_list_{suffix}"
        # 先创建一个 Agent
        client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })
        resp = client.get("/agents")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        lifecycle_test = [a for a in agents if a["name"] == agent_name]
        assert len(lifecycle_test) == 1
        assert lifecycle_test[0]["status"] == "READY"

    def test_submit_task_changes_agent_status(self, client):
        """提交任务后 Agent 状态变为 RUNNING，完成后变为 COMPLETED"""
        suffix = str(int(time.time() * 1000))
        agent_name = f"lifecycle_test_task_{suffix}"
        # 先创建一个新 Agent
        client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })
        resp = client.post("/tasks", json={
            "agent_name": agent_name,
            "task_input": {"request": "测试任务"},
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        wait_task_done(client, task_id, timeout_s=10.0)
        # 检查 Agent 状态
        resp = client.get("/agents")
        agents = resp.json()["agents"]
        lifecycle_test = [a for a in agents if a["name"] == agent_name][0]
        assert lifecycle_test["status"] == "COMPLETED"
        # 检查任务状态
        resp = client.get(f"/tasks/{task_id}")
        assert resp.json()["status"] == "SUCCESS"

    def test_submit_task_to_busy_agent(self, client):
        """Agent 正在执行时提交新任务应该返回 409"""
        suffix = str(int(time.time() * 1000))
        agent_name = f"lifecycle_test_busy_{suffix}"
        client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })

        resp = client.post("/tasks", json={
            "agent_name": agent_name,
            "task_input": {"request": "第一个任务", "__test": {"sleep_ms": 2000}},
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        resp2 = client.post("/tasks", json={
            "agent_name": agent_name,
            "task_input": {"request": "第二个任务"},
        })
        assert resp2.status_code == 409

        data = wait_task_done(client, task_id, timeout_s=10.0)
        assert data["status"] == "SUCCESS"

    def test_submit_task_to_nonexistent_agent(self, client):
        """提交给不存在的 Agent 返回 404"""
        suffix = str(int(time.time() * 1000))
        resp = client.post("/tasks", json={
            "agent_name": f"nonexistent_agent_{suffix}",
            "task_input": {},
        })
        assert resp.status_code == 404

    def test_get_task_not_found(self, client):
        suffix = str(int(time.time() * 1000))
        resp = client.get(f"/tasks/not_exist_task_id_{suffix}")
        assert resp.status_code == 404

    def test_submit_task_with_nonexistent_dependency_returns_404(self, client):
        suffix = str(int(time.time() * 1000))
        agent_name = f"lifecycle_test_dep_missing_{suffix}"
        client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })

        resp = client.post("/tasks", json={
            "agent_name": agent_name,
            "task_input": {"request": "依赖不存在"},
            "dependencies": ["not_exist_task_id_123"],
        })
        assert resp.status_code == 404
        assert "依赖任务" in resp.json().get("detail", "")

    def test_agent_message_send_and_receive(self, client):
        suffix = str(int(time.time() * 1000))
        agent_a = f"msg_a_{suffix}"
        agent_b = f"msg_b_{suffix}"
        client.post("/agents", json={"agent_name": agent_a, "role": "测试员"})
        client.post("/agents", json={"agent_name": agent_b, "role": "测试员"})

        resp = client.post("/messages", json={
            "from_agent": agent_a,
            "to_agent": agent_b,
            "payload": {"text": "hello"},
            "topic": "demo",
        })
        if resp.status_code == 404 and resp.json().get("detail") == "Not Found":
            pytest.skip("agentd 未启用 /messages")
        assert resp.status_code == 200
        msg = resp.json()
        assert msg["from_agent"] == agent_a
        assert msg["to_agent"] == agent_b
        assert msg["payload"] == {"text": "hello"}
        assert msg["topic"] == "demo"

        resp = client.get(f"/messages/{agent_b}")
        if resp.status_code == 404 and resp.json().get("detail") == "Not Found":
            pytest.skip("agentd 未启用 /messages")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 1
        assert data["messages"][0]["payload"] == {"text": "hello"}
        assert data["messages"][0]["from_agent"] == agent_a

        resp = client.get(f"/messages/{agent_b}")
        assert resp.status_code == 200
        assert resp.json()["messages"] == []

    def test_send_message_to_nonexistent_agent_returns_404(self, client):
        suffix = str(int(time.time() * 1000))
        agent_a = f"msg_missing_a_{suffix}"
        client.post("/agents", json={"agent_name": agent_a, "role": "测试员"})

        resp = client.post("/messages", json={
            "from_agent": agent_a,
            "to_agent": f"not_exist_{suffix}",
            "payload": {"text": "x"},
        })
        if resp.status_code == 404 and resp.json().get("detail") == "Not Found":
            pytest.skip("agentd 未启用 /messages")
        assert resp.status_code == 404

    def test_metrics_show_correct_counts(self, client):
        """验证指标统计正确"""
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()

        assert data["agents"]["total"] >= 1
        assert "COMPLETED" in data["agents"]["by_status"]
        assert data["tasks"]["success"] >= 1

    def test_failed_task_sets_agent_failed_and_can_retry(self, client):
        suffix = str(int(time.time() * 1000))
        agent_name = f"lifecycle_test_fail_{suffix}"
        client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })

        before = client.get("/metrics").json()
        before_failed = before["tasks"]["failed"]

        resp = client.post("/tasks", json={
            "agent_name": agent_name,
            "task_input": {"request": "强制失败", "__test": {"force_error": True}},
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        data = wait_task_done(client, task_id, timeout_s=10.0)
        assert data["status"] == "FAILED"
        assert data["error"]

        agents = client.get("/agents").json()["agents"]
        a = [x for x in agents if x["name"] == agent_name][0]
        assert a["status"] == "FAILED"

        after = client.get("/metrics").json()
        assert after["tasks"]["failed"] == before_failed + 1

        resp2 = client.post("/tasks", json={
            "agent_name": agent_name,
            "task_input": {"request": "重试任务"},
        })
        assert resp2.status_code == 200
        task_id2 = resp2.json()["task_id"]
        data2 = wait_task_done(client, task_id2, timeout_s=10.0)
        assert data2["status"] == "SUCCESS"

    def test_dag_dependency_blocks_execution(self, client):
        suffix = str(int(time.time() * 1000))
        agent_a = f"dag_dep_a_{suffix}"
        agent_b = f"dag_dep_b_{suffix}"
        client.post("/agents", json={"agent_name": agent_a, "role": "测试员"})
        client.post("/agents", json={"agent_name": agent_b, "role": "测试员"})

        resp_a = client.post("/tasks", json={
            "agent_name": agent_a,
            "task_input": {"request": "任务A", "__test": {"sleep_ms": 1200}},
        })
        assert resp_a.status_code == 200
        task_a = resp_a.json()["task_id"]

        resp_b = client.post("/tasks", json={
            "agent_name": agent_b,
            "task_input": {"request": "任务B", "__test": {"sleep_ms": 800}},
            "dependencies": [task_a],
        })
        assert resp_b.status_code == 200
        task_b = resp_b.json()["task_id"]

        deadline = time.time() + 10.0
        task_a_status = None
        while time.time() < deadline:
            ra = client.get(f"/tasks/{task_a}")
            rb = client.get(f"/tasks/{task_b}")
            assert ra.status_code == 200
            assert rb.status_code == 200
            task_a_status = ra.json()["status"]
            task_b_status = rb.json()["status"]

            if task_a_status in ("SUCCESS", "FAILED"):
                break
            assert task_b_status not in ("RUNNING", "SUCCESS")
            time.sleep(0.1)

        assert task_a_status == "SUCCESS"
        data_b = wait_task_done(client, task_b, timeout_s=10.0)
        assert data_b["status"] == "SUCCESS"

    def test_dag_dependency_failure_cascades(self, client):
        suffix = str(int(time.time() * 1000))
        agent_a = f"dag_fail_a_{suffix}"
        agent_b = f"dag_fail_b_{suffix}"
        client.post("/agents", json={"agent_name": agent_a, "role": "测试员"})
        client.post("/agents", json={"agent_name": agent_b, "role": "测试员"})

        resp_a = client.post("/tasks", json={
            "agent_name": agent_a,
            "task_input": {"request": "任务A失败", "__test": {"sleep_ms": 800, "force_error": True}},
        })
        assert resp_a.status_code == 200
        task_a = resp_a.json()["task_id"]

        resp_b = client.post("/tasks", json={
            "agent_name": agent_b,
            "task_input": {"request": "任务B依赖A", "__test": {"sleep_ms": 800}},
            "dependencies": [task_a],
        })
        assert resp_b.status_code == 200
        task_b = resp_b.json()["task_id"]

        data_a = wait_task_done(client, task_a, timeout_s=10.0)
        assert data_a["status"] == "FAILED"

        deadline = time.time() + 10.0
        while time.time() < deadline:
            rb = client.get(f"/tasks/{task_b}")
            assert rb.status_code == 200
            task_b_status = rb.json()["status"]
            assert task_b_status != "RUNNING"
            if task_b_status == "FAILED":
                return
            time.sleep(0.1)

        raise AssertionError("依赖任务失败后，未观察到下游任务进入 FAILED")


class TestAgentDuplicateAndKill:
    """测试重复创建和终止相关场景"""

    def test_create_duplicate_agent(self, client):
        """创建同名 Agent 返回 400"""
        suffix = str(int(time.time() * 1000))
        agent_name = f"lifecycle_test_dup_{suffix}"
        # 先创建一次
        client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })
        # 再创建同名的，应该返回 400
        resp = client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })
        assert resp.status_code == 400

    def test_create_multiple_agents(self, client):
        """创建多个 Agent，各自独立"""
        suffix = str(int(time.time() * 1000))
        for i in range(3):
            resp = client.post("/agents", json={
                "agent_name": f"multi_agent_unique_{suffix}_{i}",
                "role": f"角色{i}",
            })
            assert resp.status_code == 200

        resp = client.get("/agents")
        agents = resp.json()["agents"]
        names = [a["name"] for a in agents]
        assert f"multi_agent_unique_{suffix}_0" in names
        assert f"multi_agent_unique_{suffix}_1" in names
        assert f"multi_agent_unique_{suffix}_2" in names
