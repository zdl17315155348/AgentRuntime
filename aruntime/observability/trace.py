from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TraceEvent:
    name: str
    timestamp: datetime = field(default_factory=datetime.now)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "timestamp": self.timestamp.isoformat(),
            "detail": self.detail,
        }


@dataclass
class TraceSpan:
    span_id: str
    name: str
    agent_name: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
    status: str = "running"
    events: list[TraceEvent] = field(default_factory=list)

    def finish(self, status: str = "ok") -> None:
        self.status = status
        self.ended_at = datetime.now()

    @property
    def duration_ms(self) -> float:
        end = self.ended_at or datetime.now()
        return round((end - self.started_at).total_seconds() * 1000, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "agent_name": self.agent_name,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "events": [event.to_dict() for event in self.events],
        }


@dataclass
class TaskTrace:
    trace_id: str
    task_id: str
    spans: list[TraceSpan] = field(default_factory=list)
    events: list[TraceEvent] = field(default_factory=list)
    retry_count: int = 0


class TraceRecorder:
    def __init__(self):
        self._traces: dict[str, TaskTrace] = {}
        self._span_seq = 0

    def ensure_trace(self, trace_id: str, task_id: str) -> TaskTrace:
        trace = self._traces.get(task_id)
        if trace is None:
            trace = TaskTrace(trace_id=trace_id, task_id=task_id)
            self._traces[task_id] = trace
        return trace

    def event(self, trace_id: str, task_id: str, name: str, detail: dict[str, Any] | None = None) -> None:
        trace = self.ensure_trace(trace_id, task_id)
        trace.events.append(TraceEvent(name=name, detail=detail or {}))

    def start_span(self, trace_id: str, task_id: str, name: str, agent_name: str = "") -> str:
        trace = self.ensure_trace(trace_id, task_id)
        self._span_seq += 1
        span_id = f"span_{self._span_seq}"
        trace.spans.append(TraceSpan(span_id=span_id, name=name, agent_name=agent_name))
        return span_id

    def span_event(self, task_id: str, span_id: str, name: str, detail: dict[str, Any] | None = None) -> None:
        span = self._find_span(task_id, span_id)
        if span is not None:
            span.events.append(TraceEvent(name=name, detail=detail or {}))

    def finish_span(self, task_id: str, span_id: str, status: str = "ok") -> None:
        span = self._find_span(task_id, span_id)
        if span is not None:
            span.finish(status=status)

    def increment_retry(self, task_id: str) -> None:
        trace = self._traces.get(task_id)
        if trace is not None:
            trace.retry_count += 1

    def event_count(self, task_id: str, name: str) -> int:
        trace = self._traces.get(task_id)
        if trace is None:
            return 0
        return sum(1 for event in trace.events if event.name == name)

    def event_detail_sum(self, task_id: str, name: str, detail_key: str) -> int:
        trace = self._traces.get(task_id)
        if trace is None:
            return 0
        total = 0
        for event in trace.events:
            if event.name != name:
                continue
            total += int(event.detail.get(detail_key) or 0)
        return total

    def to_json(
        self,
        task_id: str,
        queue_wait_ms: float | None = None,
        llm_calls: int = 0,
        token_used: int = 0,
        context_hit_ratio: float = 0.0,
    ) -> dict[str, Any]:
        trace = self._traces.get(task_id)
        if trace is None:
            return {}
        spans = [span.to_dict() for span in trace.spans]
        critical_path = [
            span["name"]
            for span in sorted(spans, key=lambda item: item["duration_ms"], reverse=True)
        ]
        return {
            "trace_id": trace.trace_id,
            "task_id": trace.task_id,
            "critical_path": critical_path,
            "queue_wait_ms": queue_wait_ms or 0,
            "llm_calls": llm_calls,
            "token_used": token_used,
            "context_hit_ratio": context_hit_ratio,
            "retry_count": trace.retry_count,
            "spans": spans,
            "events": [event.to_dict() for event in trace.events],
        }

    def _find_span(self, task_id: str, span_id: str) -> TraceSpan | None:
        trace = self._traces.get(task_id)
        if trace is None:
            return None
        for span in trace.spans:
            if span.span_id == span_id:
                return span
        return None
