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
        resp = client.post("/agents", json={
            "agent_name": "lifecycle_test_create",
            "role": "测试员",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "READY"

    def test_list_agents_shows_status(self, client):
        """列出 Agent 应包含状态信息"""
        # 先创建一个 Agent
        client.post("/agents", json={
            "agent_name": "lifecycle_test_list",
            "role": "测试员",
        })
        resp = client.get("/agents")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        lifecycle_test = [a for a in agents if a["name"] == "lifecycle_test_list"]
        assert len(lifecycle_test) == 1
        assert lifecycle_test[0]["status"] == "READY"

    def test_submit_task_changes_agent_status(self, client):
        """提交任务后 Agent 状态变为 RUNNING，完成后变为 COMPLETED"""
        # 先创建一个新 Agent
        client.post("/agents", json={
            "agent_name": "lifecycle_test_task",
            "role": "测试员",
        })
        resp = client.post("/tasks", json={
            "agent_name": "lifecycle_test_task",
            "task_input": {"request": "测试任务"},
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]
        wait_task_done(client, task_id, timeout_s=10.0)
        # 检查 Agent 状态
        resp = client.get("/agents")
        agents = resp.json()["agents"]
        lifecycle_test = [a for a in agents if a["name"] == "lifecycle_test_task"][0]
        assert lifecycle_test["status"] == "COMPLETED"
        # 检查任务状态
        resp = client.get(f"/tasks/{task_id}")
        assert resp.json()["status"] == "SUCCESS"

    def test_submit_task_to_busy_agent(self, client):
        """Agent 正在执行时提交新任务应该返回 409"""
        client.post("/agents", json={
            "agent_name": "lifecycle_test_busy",
            "role": "测试员",
        })

        resp = client.post("/tasks", json={
            "agent_name": "lifecycle_test_busy",
            "task_input": {"request": "第一个任务", "__test": {"sleep_ms": 2000}},
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        resp2 = client.post("/tasks", json={
            "agent_name": "lifecycle_test_busy",
            "task_input": {"request": "第二个任务"},
        })
        assert resp2.status_code == 409

        data = wait_task_done(client, task_id, timeout_s=10.0)
        assert data["status"] == "SUCCESS"

    def test_submit_task_to_nonexistent_agent(self, client):
        """提交给不存在的 Agent 返回 404"""
        resp = client.post("/tasks", json={
            "agent_name": "nonexistent_agent",
            "task_input": {},
        })
        assert resp.status_code == 404

    def test_get_task_not_found(self, client):
        resp = client.get("/tasks/not_exist_task_id")
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
        agent_name = "lifecycle_test_fail"
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


class TestAgentDuplicateAndKill:
    """测试重复创建和终止相关场景"""

    def test_create_duplicate_agent(self, client):
        """创建同名 Agent 返回 400"""
        # 先创建一次
        client.post("/agents", json={
            "agent_name": "lifecycle_test_dup",
            "role": "测试员",
        })
        # 再创建同名的，应该返回 400
        resp = client.post("/agents", json={
            "agent_name": "lifecycle_test_dup",
            "role": "测试员",
        })
        assert resp.status_code == 400

    def test_create_multiple_agents(self, client):
        """创建多个 Agent，各自独立"""
        for i in range(3):
            resp = client.post("/agents", json={
                "agent_name": f"multi_agent_unique_{i}",
                "role": f"角色{i}",
            })
            assert resp.status_code == 200

        resp = client.get("/agents")
        agents = resp.json()["agents"]
        names = [a["name"] for a in agents]
        assert "multi_agent_unique_0" in names
        assert "multi_agent_unique_1" in names
        assert "multi_agent_unique_2" in names
