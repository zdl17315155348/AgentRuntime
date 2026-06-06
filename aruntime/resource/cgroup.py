import os


def apply_cgroup_v2(
    pid: int,
    group_name: str,
    memory_max_bytes: int | None = None,
    cpu_max: str | None = None,
) -> dict:
    base = "/sys/fs/cgroup"
    path = os.path.join(base, "agent-runtime-os", group_name)
    try:
        os.makedirs(path, exist_ok=True)
        if memory_max_bytes is not None and memory_max_bytes > 0:
            with open(os.path.join(path, "memory.max"), "w") as f:
                f.write(str(int(memory_max_bytes)))
        if cpu_max:
            with open(os.path.join(path, "cpu.max"), "w") as f:
                f.write(str(cpu_max))
        with open(os.path.join(path, "cgroup.procs"), "w") as f:
            f.write(str(int(pid)))
        return {"ok": True, "path": path}
    except Exception as e:
        return {"ok": False, "path": path, "error": str(e)}

