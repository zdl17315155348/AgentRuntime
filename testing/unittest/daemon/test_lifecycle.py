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

    def test_agent_acb_endpoint_returns_runtime_state(self, client):
        """ACB 接口返回 Agent 运行态、资源配额和 timeline"""
        suffix = str(int(time.time() * 1000))
        agent_name = f"lifecycle_test_acb_{suffix}"
        resp = client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
            "memory_max_bytes": 1024,
            "memory_high_bytes": 512,
            "cpu_max": "50000 100000",
            "pids_max": 16,
        })
        assert resp.status_code == 200

        resp = client.get(f"/agents/{agent_name}/acb")
        assert resp.status_code == 200
        acb = resp.json()
        assert acb["agent_name"] == agent_name
        assert acb["status"] == "READY"
        assert acb["current_task_id"] is None
        assert acb["resource_quota"]["memory_max_bytes"] == 1024
        assert acb["resource_quota"]["memory_high_bytes"] == 512
        assert acb["resource_quota"]["cpu_max"] == "50000 100000"
        assert acb["resource_quota"]["pids_max"] == 16
        assert acb["context_handle"] == {"context_id": None}
        assert acb["fault_domain"] == agent_name
        assert acb["trace_id"].startswith("trace_")
        assert any(e["to_status"] == "READY" for e in acb["timeline"])

    def test_scheduler_queues_endpoint_returns_queue_shape(self, client):
        """调度队列接口返回 ready/running/waiting/blocked 四类队列"""
        resp = client.get("/scheduler/queues")
        assert resp.status_code == 200
        queues = resp.json()
        assert set(queues.keys()) == {"ready", "running", "waiting", "blocked"}
        assert isinstance(queues["ready"], list)
        assert isinstance(queues["running"], list)
        assert isinstance(queues["waiting"], list)
        assert isinstance(queues["blocked"], list)

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
        task_data = resp.json()
        assert task_data["status"] == "SUCCESS"
        assert task_data["runtime"]["agent_name"] == agent_name
        assert task_data["runtime"]["agent_status"] == "COMPLETED"
        assert task_data["runtime"]["trace_id"].startswith("trace_")

    def test_submit_task_to_busy_agent(self, client):
        """Agent 正在执行时提交新任务应进入队列"""
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
        assert resp2.status_code == 200
        assert resp2.json()["message"] == "任务已加入调度队列"

        data = wait_task_done(client, task_id, timeout_s=10.0)
        assert data["status"] == "SUCCESS"

    def test_spawn_task_api_returns_children_and_dag(self, client):
        suffix = str(int(time.time() * 1000))
        parent_agent = f"spawn_parent_{suffix}"
        child_agent = f"spawn_child_{suffix}"
        client.post("/agents", json={"agent_name": parent_agent, "role": "规划者"})
        client.post("/agents", json={
            "agent_name": child_agent,
            "role": "编码者",
            "capability": {"can_code": True, "languages": ["python"]},
        })
        parent = client.post("/tasks", json={
            "agent_name": parent_agent,
            "context_id": f"ctx_{suffix}",
            "task_input": {"request": "root"},
        }).json()

        resp = client.post(f"/tasks/{parent['task_id']}/spawn", json={
            "task_input": {"request": "implement"},
            "required_capability": {"can_code": True, "language": "python"},
            "dependencies": [parent["task_id"]],
            "inherit_context": True,
        })

        assert resp.status_code == 200
        child = resp.json()
        assert child["trace_id"]
        assert child["parent_task_id"] == parent["task_id"]

        children = client.get(f"/tasks/{parent['task_id']}/children").json()
        assert child["task_id"] in children["children"]
        dag = client.get(f"/tasks/{parent['task_id']}/dag").json()
        assert dag["children"][0]["task_id"] == child["task_id"]

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

    def test_task_context_is_injected_into_worker_input(self, client):
        suffix = str(int(time.time() * 1000))
        agent_name = f"lifecycle_test_context_{suffix}"
        context_id = f"context_{suffix}"
        client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })

        resp = client.post("/tasks", json={
            "agent_name": agent_name,
            "context_id": context_id,
            "task_input": {
                "r": "",
                "context": {
                    "shared": {"p": "aros"},
                    "private": {"n": "wo"},
                },
            },
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        data = wait_task_done(client, task_id, timeout_s=10.0)
        assert data["status"] == "SUCCESS"
        output = data["result"]["output"]
        assert "runtime_context" in output

    def test_metrics_include_context_snapshot(self, client):
        suffix = str(int(time.time() * 1000))
        agent_name = f"lifecycle_test_context_metrics_{suffix}"
        context_id = f"context_metrics_{suffix}"
        client.post("/agents", json={
            "agent_name": agent_name,
            "role": "测试员",
        })

        resp = client.post("/tasks", json={
            "agent_name": agent_name,
            "context_id": context_id,
            "task_input": {
                "request": "上下文指标任务",
                "context": {
                    "shared": {"project": "agent-runtime-os"},
                    "private": {"note": "worker-only"},
                },
            },
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        data = wait_task_done(client, task_id, timeout_s=10.0)
        assert data["status"] == "SUCCESS"
        assert data["llm_usage"]["input_tokens"] > 0
        assert data["llm_usage"]["total_tokens"] >= data["llm_usage"]["input_tokens"]
        assert data["scheduler"]["resource_lease"]["task_id"] == task_id
        assert data["trace"]["trace_id"] == data["trace_id"]
        assert data["trace"]["task_id"] == task_id
        assert data["trace"]["llm_calls"] >= 1
        assert data["trace"]["token_used"] == data["llm_usage"]["total_tokens"]

        trace_resp = client.get(f"/tasks/{task_id}/trace")
        assert trace_resp.status_code == 200
        trace = trace_resp.json()
        assert "agent.execute" in trace["critical_path"]
        trace_events = {event["name"] for event in trace["events"]}
        assert {"context.build", "resource.acquire", "ipc.send_task", "llm.call"}.issubset(trace_events)
        assert trace["spans"][0]["name"] == "agent.execute"
        assert trace["spans"][0]["events"][0]["name"] == "agent.dispatch"

        resp = client.get("/metrics")
        assert resp.status_code == 200
        metrics = resp.json()
        context = metrics["context"]
        assert context["total_contexts"] >= 1
        assert context["build_hits"] >= 1
        assert "token_saving_ratio" in metrics["experiments"]
        assert "context_build_time_ms" in metrics["experiments"]
        assert "prefix_hit_ratio" in metrics["experiments"]
        assert "llm_latency_ms" in metrics["experiments"]
        assert metrics["llm"]["input_tokens"] > 0
        assert "resource" in metrics
        assert "usage" in metrics["resource"]
        assert "histograms" in metrics
        assert "queue_wait_ms" in metrics["histograms"]
        assert "llm_latency_ms" in metrics["histograms"]

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

    def test_dag_dependency_failure_isolated_by_default(self, client):
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

        deadline = time.time() + 2.0
        while time.time() < deadline:
            rb = client.get(f"/tasks/{task_b}")
            assert rb.status_code == 200
            task_b_status = rb.json()["status"]
            assert task_b_status != "RUNNING"
            assert task_b_status != "FAILED"
            time.sleep(0.1)

    def test_dag_dependency_failure_fail_closed_cascades(self, client):
        suffix = str(int(time.time() * 1000))
        agent_a = f"dag_fail_closed_a_{suffix}"
        agent_b = f"dag_fail_closed_b_{suffix}"
        client.post("/agents", json={"agent_name": agent_a, "role": "测试员"})
        client.post("/agents", json={"agent_name": agent_b, "role": "测试员"})

        resp_a = client.post("/tasks", json={
            "agent_name": agent_a,
            "task_input": {"request": "任务A失败", "__test": {"sleep_ms": 800, "force_error": True}},
            "failure_policy": "fail-closed",
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
            if rb.json()["status"] == "FAILED":
                return
            time.sleep(0.1)

        raise AssertionError("fail-closed 下游任务未进入 FAILED")

    def test_fallback_policy_switches_coder_and_tester_continues(self, client):
        suffix = str(int(time.time() * 1000))
        coder_a = f"coder_a_{suffix}"
        coder_b = f"coder_b_{suffix}"
        tester = f"tester_{suffix}"
        client.post("/agents", json={"agent_name": coder_a, "role": "Coder A"})
        client.post("/agents", json={"agent_name": coder_b, "role": "Coder B"})
        client.post("/agents", json={"agent_name": tester, "role": "Tester"})

        resp_a = client.post("/tasks", json={
            "agent_name": coder_a,
            "task_input": {
                "request": "实现功能",
                "__test": {"crash_worker": True},
            },
            "failure_policy": {
                "mode": "fallback",
                "max_retries": 0,
                "fallback_agent": coder_b,
                "timeout_ms": 1000,
            },
        })
        assert resp_a.status_code == 200
        coder_task = resp_a.json()["task_id"]

        resp_t = client.post("/tasks", json={
            "agent_name": tester,
            "task_input": {"request": "继续测试"},
            "dependencies": [coder_task],
            "on_failure": {coder_task: "fail_open"},
        })
        assert resp_t.status_code == 200
        tester_task = resp_t.json()["task_id"]

        coder_data = wait_task_done(client, coder_task, timeout_s=10.0)
        assert coder_data["status"] == "SUCCESS"
        assert coder_data["runtime"]["agent_name"] == coder_a
        assert [a["agent_name"] for a in coder_data["attempts"]][-1] == coder_b
        assert coder_data["scheduler"]["failure_policy"]["mode"] == "fallback"

        tester_data = wait_task_done(client, tester_task, timeout_s=10.0)
        assert tester_data["status"] == "SUCCESS"

        agents = client.get("/agents").json()["agents"]
        coder_a_state = next(a for a in agents if a["name"] == coder_a)
        coder_b_state = next(a for a in agents if a["name"] == coder_b)
        assert coder_a_state["status"] in ("READY", "COMPLETED")
        assert coder_b_state["current_task"] is None


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
