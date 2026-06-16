from aruntime.context.manager import ContextManager


def test_context_reuse_shared_and_private_data():
    manager = ContextManager(compress_threshold_chars=1000)

    first = manager.record_task_context(
        context_id="ctx-code-repair",
        agent_name="planner",
        shared_data={"repo": "agent-runtime-os"},
        private_data={"note": "planner-only"},
    )
    second = manager.record_task_context(
        context_id="ctx-code-repair",
        agent_name="coder",
        shared_data={"plan": "fix tests"},
        private_data={"note": "coder-only"},
    )

    assert first.context_id == "ctx-code-repair"
    assert second.context_id == "ctx-code-repair"
    assert manager.get_context("ctx-code-repair").shared_data == {
        "repo": "agent-runtime-os",
        "plan": "fix tests",
    }
    assert manager.build_agent_context("ctx-code-repair", "planner") == {
        "context_id": "ctx-code-repair",
        "shared": {"repo": "agent-runtime-os", "plan": "fix tests"},
        "private": {"note": "planner-only"},
        "compressed": False,
    }
    assert manager.build_agent_context("ctx-code-repair", "coder") == {
        "context_id": "ctx-code-repair",
        "shared": {"repo": "agent-runtime-os", "plan": "fix tests"},
        "private": {"note": "coder-only"},
        "compressed": False,
    }


def test_private_data_is_isolated_per_agent():
    manager = ContextManager(compress_threshold_chars=1000)

    manager.record_task_context(
        context_id="ctx-isolation",
        agent_name="agent-a",
        shared_data={"visible": True},
        private_data={"secret": "a"},
    )
    manager.record_task_context(
        context_id="ctx-isolation",
        agent_name="agent-b",
        private_data={"secret": "b"},
    )

    assert manager.build_agent_context("ctx-isolation", "agent-a")["private"] == {"secret": "a"}
    assert manager.build_agent_context("ctx-isolation", "agent-b")["private"] == {"secret": "b"}


def test_private_data_merges_for_same_agent():
    manager = ContextManager(compress_threshold_chars=1000)

    manager.record_task_context(
        context_id="ctx-private-merge",
        agent_name="planner",
        private_data={"first": "a"},
    )
    manager.record_task_context(
        context_id="ctx-private-merge",
        agent_name="planner",
        private_data={"second": "b"},
    )

    assert manager.build_agent_context("ctx-private-merge", "planner")["private"] == {
        "first": "a",
        "second": "b",
    }


def test_context_is_compressed_when_over_threshold():
    manager = ContextManager(compress_threshold_chars=20)

    ctx = manager.record_task_context(
        context_id="ctx-large",
        agent_name="planner",
        shared_data={"long": "abcdefghijklmnopqrstuvwxyz"},
        private_data={"note": "private"},
    )

    assert ctx.compressed is True
    assert ctx.shared_data["__compressed_summary__"].startswith("Context compressed from ")
    assert manager.build_agent_context("ctx-large", "planner")["compressed"] is True


def test_metrics_track_reuse_and_compression():
    manager = ContextManager(compress_threshold_chars=20)

    manager.record_task_context(
        context_id="ctx-metrics",
        agent_name="planner",
        shared_data={"long": "abcdefghijklmnopqrstuvwxyz"},
    )
    manager.record_task_context(
        context_id="ctx-metrics",
        agent_name="coder",
        shared_data={"next": "step"},
    )
    manager.build_agent_context("ctx-metrics", "planner")

    metrics = manager.get_metrics()
    assert metrics["total_contexts"] == 1
    assert metrics["reuse_hits"] == 1
    assert metrics["compression_count"] >= 1
    assert metrics["build_hits"] == 1


def test_missing_context_returns_empty_payload_without_build_hit():
    manager = ContextManager(compress_threshold_chars=1000)

    assert manager.build_agent_context("ctx-missing", "planner") == {
        "context_id": "ctx-missing",
        "shared": {},
        "private": {},
        "compressed": False,
    }
    assert manager.get_metrics()["build_hits"] == 0


def test_mutating_built_context_does_not_mutate_stored_context():
    manager = ContextManager(compress_threshold_chars=1000)
    manager.record_task_context(
        context_id="ctx-copy",
        agent_name="planner",
        shared_data={"repo": "agent-runtime-os"},
        private_data={"note": "planner-only"},
    )

    built = manager.build_agent_context("ctx-copy", "planner")
    built["shared"]["repo"] = "changed"
    built["private"]["note"] = "changed"

    stored = manager.get_context("ctx-copy")
    assert stored.shared_data == {"repo": "agent-runtime-os"}
    assert stored.private_data["planner"] == {"note": "planner-only"}


def test_mutating_nested_built_context_does_not_mutate_stored_context():
    manager = ContextManager(compress_threshold_chars=1000)
    manager.record_task_context(
        context_id="ctx-deep-copy",
        agent_name="planner",
        shared_data={"repo": {"name": "agent-runtime-os"}},
        private_data={"notes": ["first"]},
    )

    built = manager.build_agent_context("ctx-deep-copy", "planner")
    built["shared"]["repo"]["name"] = "changed"
    built["private"]["notes"].append("changed")

    stored = manager.get_context("ctx-deep-copy")
    assert stored.shared_data == {"repo": {"name": "agent-runtime-os"}}
    assert stored.private_data["planner"] == {"notes": ["first"]}


def test_mutating_input_payload_does_not_mutate_stored_context():
    manager = ContextManager(compress_threshold_chars=1000)
    shared = {"repo": {"name": "agent-runtime-os"}}
    private = {"notes": ["first"]}

    manager.record_task_context(
        context_id="ctx-input-copy",
        agent_name="planner",
        shared_data=shared,
        private_data=private,
    )
    shared["repo"]["name"] = "changed"
    private["notes"].append("changed")

    stored = manager.get_context("ctx-input-copy")
    assert stored.shared_data == {"repo": {"name": "agent-runtime-os"}}
    assert stored.private_data["planner"] == {"notes": ["first"]}


def test_non_ascii_context_uses_character_length_for_compression():
    manager = ContextManager(compress_threshold_chars=50)

    ctx = manager.record_task_context(
        context_id="ctx-non-ascii",
        agent_name="planner",
        shared_data={"text": "修复计划"},
    )

    assert ctx.compressed is False


def test_repeated_record_on_compressed_context_does_not_increment_compression_count():
    manager = ContextManager(compress_threshold_chars=20)
    manager.record_task_context(
        context_id="ctx-repeat-compress",
        agent_name="planner",
        shared_data={"long": "abcdefghijklmnopqrstuvwxyz"},
    )
    first_count = manager.get_metrics()["compression_count"]

    manager.record_task_context(
        context_id="ctx-repeat-compress",
        agent_name="coder",
        shared_data={"next": "step"},
    )

    assert manager.get_metrics()["compression_count"] == first_count


def test_compressed_context_ignores_later_payload_growth():
    manager = ContextManager(compress_threshold_chars=20)
    manager.record_task_context(
        context_id="ctx-compressed-stable",
        agent_name="planner",
        shared_data={"long": "abcdefghijklmnopqrstuvwxyz"},
    )

    manager.record_task_context(
        context_id="ctx-compressed-stable",
        agent_name="planner",
        shared_data={"new": "value"},
        private_data={"secret": "later"},
    )

    built = manager.build_agent_context("ctx-compressed-stable", "planner")
    assert set(built["shared"].keys()) == {"__compressed_summary__"}
    assert built["private"] == {}


def test_large_private_data_triggers_compression():
    manager = ContextManager(compress_threshold_chars=20)

    ctx = manager.record_task_context(
        context_id="ctx-large-private",
        agent_name="planner",
        private_data={"long": "abcdefghijklmnopqrstuvwxyz"},
    )

    assert ctx.compressed is True
    assert manager.get_metrics()["compression_count"] == 1
    assert manager.build_agent_context("ctx-large-private", "planner")["private"] == {}
