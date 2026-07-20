from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class RepositoryInspector(Protocol):
    async def repo_scan(self) -> list[str]: ...

    async def read_file(self, path: str) -> str: ...

    async def search_code(self, query: str, path: str) -> list[dict]: ...


@dataclass
class LocalRepositoryInspector:
    root: str

    async def repo_scan(self) -> list[str]:
        base = Path(self.root)
        return [str(path.relative_to(base)) for path in base.rglob("*") if path.is_file()]

    async def read_file(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8", errors="replace")

    async def search_code(self, query: str, path: str) -> list[dict]:
        base = self._resolve(path)
        matches: list[dict] = []
        for file in base.rglob("*"):
            if not file.is_file():
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if query in text:
                matches.append({"path": str(file.relative_to(Path(self.root))), "snippet": text[:200]})
        return matches

    def _resolve(self, path: str) -> Path:
        root = Path(self.root).resolve()
        candidate = (root / path).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError(f"unsafe path: {path}")
        return candidate
