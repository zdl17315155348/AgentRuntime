from aruntime.observability import TraceRecorder


def test_trace_recorder_outputs_required_json_shape():
    recorder = TraceRecorder()
    trace_id = "trace_1"
    task_id = "task_1"

    recorder.event(trace_id, task_id, "context.build", {"hit": True})
    span_id = recorder.start_span(trace_id, task_id, "agent.execute", "coder")
    recorder.span_event(task_id, span_id, "llm.call", {"total_tokens": 10})
    recorder.finish_span(task_id, span_id, "success")
    recorder.increment_retry(task_id)

    data = recorder.to_json(
        task_id=task_id,
        queue_wait_ms=123,
        llm_calls=4,
        token_used=8321,
        context_hit_ratio=0.62,
    )

    assert data["trace_id"] == trace_id
    assert data["task_id"] == task_id
    assert data["critical_path"] == ["agent.execute"]
    assert data["queue_wait_ms"] == 123
    assert data["llm_calls"] == 4
    assert data["token_used"] == 8321
    assert data["context_hit_ratio"] == 0.62
    assert data["retry_count"] == 1
    assert data["spans"][0]["events"][0]["name"] == "llm.call"
    assert data["events"][0]["name"] == "context.build"


def test_trace_recorder_counts_events_and_token_usage():
    recorder = TraceRecorder()
    trace_id = "trace_2"
    task_id = "task_2"

    recorder.event(trace_id, task_id, "llm.call", {"total_tokens": 10})
    recorder.event(trace_id, task_id, "llm.call", {"total_tokens": 20})
    recorder.event(trace_id, task_id, "resource.acquire", {"agent_name": "coder"})

    assert recorder.event_count(task_id, "llm.call") == 2
    assert recorder.event_detail_sum(task_id, "llm.call", "total_tokens") == 30
    assert recorder.event_count(task_id, "resource.acquire") == 1
