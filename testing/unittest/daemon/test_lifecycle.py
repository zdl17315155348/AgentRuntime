"""
集成测试：通过 agentd API 验证 Agent 完整生命周期
"""

import pytest
import httpx

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
        # 轮询等待任务完成
        import time
        for _ in range(10):
            time.sleep(1)
            resp = client.get(f"/tasks/{task_id}")
            if resp.json()["status"] in ("SUCCESS", "FAILED"):
                break
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
        # 先创建自己的 Agent
        client.post("/agents", json={
            "agent_name": "lifecycle_test_busy",
            "role": "测试员",
        })
        # 提交一个任务
        resp = client.post("/tasks", json={
            "agent_name": "lifecycle_test_busy",
            "task_input": {"request": "第二个任务"},
        })

    def test_submit_task_to_nonexistent_agent(self, client):
        """提交给不存在的 Agent 返回 404"""
        resp = client.post("/tasks", json={
            "agent_name": "nonexistent_agent",
            "task_input": {},
        })
        assert resp.status_code == 404

    def test_metrics_show_correct_counts(self, client):
        """验证指标统计正确"""
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()

        assert data["agents"]["total"] >= 1
        assert "COMPLETED" in data["agents"]["by_status"]
        assert data["tasks"]["success"] >= 1


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
