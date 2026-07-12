from concurrent.futures import ThreadPoolExecutor

from aruntime.resource import (
    ResourceClass,
    ResourceMonitor,
    ResourceQuota,
    ResourceRequest,
    ResourceUsage,
)
from aruntime.resource import cgroup as cgroup_module
from aruntime.resource.cgroup import CgroupManager


def test_resource_request_parses_all_runtime_resource_classes():
    request = ResourceRequest.from_dict({
        "cpu": 1,
        "memory": 128,
        "llm_concurrency": 1,
        "token": 1000,
        "tool": 2,
        "kv_cache": 256,
        "network": 10,
    })

    assert request.get(ResourceClass.CPU) == 1
    assert request.get(ResourceClass.MEMORY) == 128
    assert request.get(ResourceClass.LLM_CONCURRENCY) == 1
    assert request.get(ResourceClass.TOKEN) == 1000
    assert request.get(ResourceClass.TOOL) == 2
    assert request.get(ResourceClass.KV_CACHE) == 256
    assert request.get(ResourceClass.NETWORK) == 10


def test_resource_monitor_acquire_release_and_reclaim():
    monitor = ResourceMonitor(llm_max_concurrent=2)
    monitor.quota = ResourceQuota(limits={
        ResourceClass.LLM_CONCURRENCY: 2,
        ResourceClass.TOKEN: 100,
    })
    request = ResourceRequest.from_dict({
        "llm_concurrency": 1,
        "token": 50,
    })

    lease = monitor.acquire("t1", "agent1", request)

    assert lease is not None
    assert monitor.usage.get(ResourceClass.LLM_CONCURRENCY) == 1
    assert monitor.usage.get(ResourceClass.TOKEN) == 50
    assert monitor.acquire("t2", "agent2", {"token": 60}) is None

    monitor.release("t1")
    assert monitor.usage.get(ResourceClass.TOKEN) == 0

    lease = monitor.acquire("t3", "agent1", request)
    assert lease is not None
    monitor.reclaim("t3", reason="limit")
    assert monitor.reclaimer.reclaimed[-1].reason == "limit"


def test_resource_usage_to_dict():
    usage = ResourceUsage()
    usage.add(ResourceClass.KV_CACHE, 4)
    usage.sub(ResourceClass.KV_CACHE, 2)

    assert usage.to_dict() == {"kv_cache": 2.0}


def test_resource_monitor_llm_lease_is_atomic():
    monitor = ResourceMonitor(llm_max_concurrent=1)
    monitor.quota = ResourceQuota(limits={ResourceClass.LLM_CONCURRENCY: 1})

    assert monitor.acquire("t1", "agent1", {"llm_concurrency": 1}) is not None
    assert monitor.acquire("t2", "agent2", {"llm_concurrency": 1}) is None
    assert monitor.get_snapshot()["llm_total_concurrent"] == 1


def test_resource_monitor_concurrent_acquire_does_not_overallocate():
    monitor = ResourceMonitor(llm_max_concurrent=2)
    monitor.quota = ResourceQuota(limits={
        ResourceClass.LLM_CONCURRENCY: 2,
        ResourceClass.TOKEN: 100,
    })

    def acquire_one(idx: int):
        return monitor.acquire(f"t{idx}", f"agent{idx}", {"llm_concurrency": 1, "token": 50})

    with ThreadPoolExecutor(max_workers=8) as pool:
        leases = list(pool.map(acquire_one, range(8)))

    active = [lease for lease in leases if lease is not None]
    assert len(active) == 2
    assert monitor.usage.get(ResourceClass.LLM_CONCURRENCY) == 2
    assert monitor.usage.get(ResourceClass.TOKEN) == 100
    assert monitor.get_snapshot()["llm_total_concurrent"] == 2


def test_resource_monitor_empty_request_creates_placeholder_lease():
    monitor = ResourceMonitor(cpu_threshold=0.0, mem_threshold=0.0)
    lease = monitor.acquire("t-empty", "agent1", {})
    assert lease is not None
    assert lease.request.amounts == {}
    assert monitor.get_snapshot()["leases"][0]["task_id"] == "t-empty"


def test_cgroup_manager_sanitizes_group_names(tmp_path):
    manager = CgroupManager(base=str(tmp_path), root_name="agent runtime")
    result = manager.create("../bad/name", cpu_weight=100, pids_max=8)

    assert result["ok"] is True
    assert str(tmp_path) in result["path"]
    assert ".." not in result["path"]
    stats = manager.read_stats("../bad/name")
    assert "cpu_stat" in stats
    assert "cpu_pressure" in stats
    assert "memory_pressure" in stats
    assert manager.cleanup("../bad/name")["ok"] is True


def test_apply_cgroup_v2_passes_high_and_pids_and_cleans_on_attach_failure(monkeypatch, tmp_path):
    created: list[dict] = []
    cleaned: list[str] = []

    class FakeManager:
        def create(self, group_name, **kwargs):
            created.append({"group_name": group_name, **kwargs})
            path = tmp_path / group_name
            path.mkdir()
            return {"ok": True, "path": str(path)}

        def attach(self, group_name, pid):
            return {"ok": False, "path": str(tmp_path / group_name), "error": "attach failed"}

        def cleanup(self, group_name):
            cleaned.append(group_name)
            return {"ok": True, "path": str(tmp_path / group_name)}

    monkeypatch.setattr(cgroup_module, "CgroupManager", FakeManager)

    result = cgroup_module.apply_cgroup_v2(
        pid=123,
        group_name="agent1",
        memory_max_bytes=1024,
        memory_high_bytes=512,
        cpu_max="50000 100000",
        pids_max=16,
    )

    assert result["ok"] is False
    assert cleaned == ["agent1"]
    assert created == [{
        "group_name": "agent1",
        "memory_max_bytes": 1024,
        "cpu_max": "50000 100000",
        "memory_high_bytes": 512,
        "pids_max": 16,
    }]
