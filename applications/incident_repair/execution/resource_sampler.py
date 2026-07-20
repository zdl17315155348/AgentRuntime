from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import psutil


class ResourceSampler:
    async def sample_process_tree(self, root_pid: int, interval_ms: int = 100) -> AsyncIterator[dict]:
        while True:
            try:
                proc = psutil.Process(root_pid)
                processes = [proc, *proc.children(recursive=True)]
            except (psutil.Error, OSError):
                return
            rss = 0
            read_bytes = 0
            write_bytes = 0
            cpu_time_ms = 0.0
            for item in processes:
                try:
                    rss += item.memory_info().rss
                    times = item.cpu_times()
                    cpu_time_ms += (times.user + times.system) * 1000
                    io = item.io_counters()
                    read_bytes += getattr(io, "read_bytes", 0)
                    write_bytes += getattr(io, "write_bytes", 0)
                except (psutil.Error, OSError):
                    continue
            yield {
                "timestamp": time.time(),
                "root_pid": root_pid,
                "process_count": len(processes),
                "cpu_time_ms": round(cpu_time_ms, 3),
                "rss_mb": round(rss / 1024 / 1024, 3),
                "read_bytes": read_bytes,
                "write_bytes": write_bytes,
                "peak_rss_mb": round(rss / 1024 / 1024, 3),
            }
            await asyncio.sleep(interval_ms / 1000)
