from aruntime.resource.monitor import ResourceMonitor


def test_resource_monitor_snapshot_exposes_reclaimed_list():
    monitor = ResourceMonitor()
    snapshot = monitor.get_snapshot()

    assert "reclaimed" in snapshot
    assert isinstance(snapshot["reclaimed"], list)
