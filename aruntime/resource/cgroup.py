import os
import re
import signal


class CgroupManager:
    def __init__(self, base: str = "/sys/fs/cgroup", root_name: str = "agent-runtime-os"):
        self.base = base
        self.root_name = self._sanitize(root_name)
        self.root = os.path.join(base, self.root_name)

    def create(
        self,
        group_name: str,
        memory_max_bytes: int | None = None,
        cpu_max: str | None = None,
        cpu_weight: int | None = None,
        memory_high_bytes: int | None = None,
        pids_max: int | None = None,
    ) -> dict:
        path = self._path(group_name)
        try:
            os.makedirs(path, exist_ok=True)
            self._enable_subtree_control()
            self.update(
                group_name,
                memory_max_bytes=memory_max_bytes,
                cpu_max=cpu_max,
                cpu_weight=cpu_weight,
                memory_high_bytes=memory_high_bytes,
                pids_max=pids_max,
            )
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "path": path, "error": str(e)}

    def attach(self, group_name: str, pid: int) -> dict:
        path = self._path(group_name)
        try:
            with open(os.path.join(path, "cgroup.procs"), "w") as f:
                f.write(str(int(pid)))
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "path": path, "error": str(e)}

    def update(
        self,
        group_name: str,
        memory_max_bytes: int | None = None,
        cpu_max: str | None = None,
        cpu_weight: int | None = None,
        memory_high_bytes: int | None = None,
        pids_max: int | None = None,
    ) -> dict:
        path = self._path(group_name)
        try:
            if cpu_max:
                self._write(path, "cpu.max", str(cpu_max))
            if cpu_weight is not None:
                self._write(path, "cpu.weight", str(max(1, min(int(cpu_weight), 10000))))
            if memory_high_bytes is not None and memory_high_bytes > 0:
                self._write(path, "memory.high", str(int(memory_high_bytes)))
            if memory_max_bytes is not None and memory_max_bytes > 0:
                self._write(path, "memory.max", str(int(memory_max_bytes)))
            if pids_max is not None and pids_max > 0:
                self._write(path, "pids.max", str(int(pids_max)))
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "path": path, "error": str(e)}

    def read_stats(self, group_name: str) -> dict:
        path = self._path(group_name)
        return {
            "path": path,
            "cpu_stat": self._read_kv(path, "cpu.stat"),
            "memory_events": self._read_kv(path, "memory.events"),
            "cgroup_events": self._read_kv(path, "cgroup.events"),
        }

    def kill(self, group_name: str) -> dict:
        path = self._path(group_name)
        try:
            kill_file = os.path.join(path, "cgroup.kill")
            if os.path.exists(kill_file):
                self._write(path, "cgroup.kill", "1")
            else:
                for pid in self._read_pids(path):
                    os.kill(pid, signal.SIGKILL)
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "path": path, "error": str(e)}

    def cleanup(self, group_name: str) -> dict:
        path = self._path(group_name)
        try:
            if os.path.isdir(path):
                for name in os.listdir(path):
                    os.remove(os.path.join(path, name))
                os.rmdir(path)
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "path": path, "error": str(e)}

    def _enable_subtree_control(self) -> None:
        os.makedirs(self.root, exist_ok=True)
        controllers_file = os.path.join(self.base, "cgroup.controllers")
        subtree_file = os.path.join(self.base, "cgroup.subtree_control")
        if not os.path.exists(controllers_file) or not os.path.exists(subtree_file):
            return
        with open(controllers_file, "r") as f:
            controllers = [item for item in f.read().split() if item in {"cpu", "memory", "pids"}]
        if controllers:
            with open(subtree_file, "w") as f:
                f.write(" ".join(f"+{item}" for item in controllers))

    def _path(self, group_name: str) -> str:
        return os.path.join(self.root, self._sanitize(group_name))

    def _sanitize(self, value: str) -> str:
        text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
        return text.strip("._") or "default"

    def _write(self, path: str, name: str, value: str) -> None:
        with open(os.path.join(path, name), "w") as f:
            f.write(value)

    def _read_kv(self, path: str, name: str) -> dict[str, int]:
        result: dict[str, int] = {}
        file_path = os.path.join(path, name)
        if not os.path.exists(file_path):
            return result
        with open(file_path, "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) == 2:
                    try:
                        result[parts[0]] = int(parts[1])
                    except ValueError:
                        continue
        return result

    def _read_pids(self, path: str) -> list[int]:
        file_path = os.path.join(path, "cgroup.procs")
        if not os.path.exists(file_path):
            return []
        with open(file_path, "r") as f:
            return [int(line.strip()) for line in f if line.strip().isdigit()]


def apply_cgroup_v2(
    pid: int,
    group_name: str,
    memory_max_bytes: int | None = None,
    cpu_max: str | None = None,
) -> dict:
    manager = CgroupManager()
    created = manager.create(group_name, memory_max_bytes=memory_max_bytes, cpu_max=cpu_max, pids_max=64)
    if created.get("ok") is not True:
        return created
    attached = manager.attach(group_name, pid)
    if attached.get("ok") is not True:
        return attached
    return {"ok": True, "path": created["path"], "stats": manager.read_stats(group_name)}
