from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def parse_json_model(text: str, model_type: type[T]) -> T:
    return model_type(**load_json_object(text))


def load_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
        if match:
            raw = match.group(1).strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def normalize_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "tasks" in payload:
        return payload
    if "plan" not in payload or not isinstance(payload["plan"], list):
        return payload
    tasks = []
    for item in payload["plan"]:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        if "local_id" not in normalized and "id" in normalized:
            normalized["local_id"] = str(normalized.pop("id"))
        if "goal" not in normalized:
            normalized["goal"] = str(
                normalized.get("description")
                or normalized.get("task")
                or normalized.get("summary")
                or normalized.get("local_id")
                or ""
            )
        dependencies = normalized.get("dependencies", [])
        normalized["dependencies"] = [str(dep) for dep in dependencies] if isinstance(dependencies, list) else []
        role = str(normalized.get("role") or "").lower()
        if role in {"code", "coder", "developer", "repair"}:
            normalized["role"] = "coder"
        elif role in {"test", "tester", "qa"}:
            normalized["role"] = "tester"
        elif role in {"review", "reviewer"}:
            normalized["role"] = "reviewer"
        tasks.append(normalized)
    return {
        "version": str(payload.get("version") or "1.0"),
        "summary": str(payload.get("summary") or payload.get("description") or "planner generated workflow"),
        "tasks": tasks,
    }


def normalize_inspection_payload(payload: dict[str, Any]) -> dict[str, Any]:
    files = payload.get("files")
    searches = payload.get("searches")
    if isinstance(files, list) or isinstance(searches, list):
        return payload
    extracted_files: list[str] = []
    for key in ("tasks", "items", "plan"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            file_name = item.get("file") or item.get("path")
            if isinstance(file_name, str) and file_name and file_name not in extracted_files:
                extracted_files.append(file_name)
    return {
        "files": extracted_files,
        "searches": [],
        "summary": str(payload.get("summary") or payload.get("description") or ""),
    }
