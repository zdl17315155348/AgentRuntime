import json
import os
import signal

from aruntime.core.models import TaskSpec, TaskStatus
from aruntime.daemon.store import SQLiteStateStore


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def recover_tasks(store: SQLiteStateStore) -> tuple[list[TaskSpec], dict[str, str]]:
    recovered: list[TaskSpec] = []
    decisions: dict[str, str] = {}
    for row in store.load_tasks():
        data = json.loads(row["data"])
        task = TaskSpec(**data)
        if task.status == TaskStatus.RUNNING:
            task.transition_to(TaskStatus.ORPHANED, "daemon.recovery.orphaned")
            store.release_leases_for_task(task.task_id, reason="daemon.recovery.orphaned")
            task.transition_to(TaskStatus.READY, "daemon.recovery.retry")
            decisions[task.task_id] = "RUNNING->ORPHANED->READY"
            store.save_task(task)
            recovered.append(task)
        elif task.status == TaskStatus.READY:
            decisions[task.task_id] = "READY->READY"
            recovered.append(task)
        elif task.status == TaskStatus.PENDING:
            if task.dependencies:
                decisions[task.task_id] = "PENDING->PENDING"
                store.save_task(task)
            else:
                decisions[task.task_id] = "PENDING->READY"
                task.transition_to(TaskStatus.READY, "daemon.recovery.pending_ready")
                store.save_task(task)
                recovered.append(task)
        else:
            continue
    store.release_all_active_leases(reason="daemon.recovery")
    return recovered, decisions
