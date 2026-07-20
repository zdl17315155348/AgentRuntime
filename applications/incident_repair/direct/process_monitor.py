from __future__ import annotations

import os
from dataclasses import dataclass

import psutil


@dataclass
class ProcessSample:
    timestamp: float
    root_pid: int
    process_count: int
    cpu_percent: float
    rss_mb: float
    read_bytes: int
    write_bytes: int


class DirectProcessMonitor:
    def sample_once(self, root_pid: int) -> ProcessSample:
        proc = psutil.Process(root_pid)
        children = proc.children(recursive=True)
        processes = [proc, *children]
        rss = 0
        cpu = 0.0
        read_bytes = 0
        write_bytes = 0
        for item in processes:
            try:
                mem = item.memory_info()
                io = item.io_counters()
                rss += mem.rss
                cpu += item.cpu_percent(interval=None)
                read_bytes += getattr(io, "read_bytes", 0)
                write_bytes += getattr(io, "write_bytes", 0)
            except (psutil.Error, OSError):
                continue
        return ProcessSample(
            timestamp=os.times().elapsed,
            root_pid=root_pid,
            process_count=len(processes),
            cpu_percent=cpu,
            rss_mb=round(rss / 1024 / 1024, 3),
            read_bytes=read_bytes,
            write_bytes=write_bytes,
        )
