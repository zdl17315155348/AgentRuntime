from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from aruntime.core.models import ArtifactReference


def safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)


class ArtifactStore:
    def __init__(self, root: str | None = None):
        self.root = Path(root or os.getenv("AGENTD_ARTIFACT_ROOT", "/tmp/agent-runtime-os/artifacts")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def attempt_dir(self, root_task_id: str, attempt_id: str) -> Path:
        path = (self.root / safe_id(root_task_id) / safe_id(attempt_id)).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("artifact path escapes artifact root")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_bytes(
        self,
        root_task_id: str,
        task_id: str,
        attempt_id: str,
        artifact_type: str,
        filename: str,
        data: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactReference:
        path = (self.attempt_dir(root_task_id, attempt_id) / filename).resolve()
        if self.root not in path.parents:
            raise ValueError("artifact path escapes artifact root")
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        return ArtifactReference(
            artifact_id=f"artifact_{uuid4().hex}",
            artifact_type=artifact_type,
            path=str(path),
            sha256=digest,
            size_bytes=len(data),
            task_id=task_id,
            attempt_id=attempt_id,
            metadata=metadata or {},
        )

    def write_json(
        self,
        root_task_id: str,
        task_id: str,
        attempt_id: str,
        artifact_type: str,
        filename: str,
        data: dict[str, Any],
    ) -> ArtifactReference:
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return self.write_bytes(root_task_id, task_id, attempt_id, artifact_type, filename, raw)

    def read(self, artifact: ArtifactReference) -> bytes:
        path = Path(artifact.path).resolve()
        if self.root not in path.parents:
            raise ValueError("artifact path escapes artifact root")
        return path.read_bytes()
