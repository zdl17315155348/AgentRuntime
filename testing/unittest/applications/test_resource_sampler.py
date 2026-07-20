from __future__ import annotations

import os

import pytest

from applications.incident_repair.execution.resource_sampler import ResourceSampler


@pytest.mark.anyio
async def test_resource_sampler_samples_current_process_tree():
    sampler = ResourceSampler()
    agen = sampler.sample_process_tree(os.getpid(), interval_ms=1000)
    sample = await anext(agen)

    assert sample["root_pid"] == os.getpid()
    assert sample["process_count"] >= 1
    assert sample["rss_mb"] > 0
