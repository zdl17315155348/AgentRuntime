from aruntime.context.manager import ContextManager


def test_agent_cannot_read_other_agent_private_context():
    manager = ContextManager(compress_threshold_chars=1000)
    manager.record_task_context("ctx", "agent-a", private_data={"secret": "a"})
    manager.record_task_context("ctx", "agent-b", private_data={"secret": "b"})

    assert manager.build_agent_context("ctx", "agent-a")["private"] == {"secret": "a"}
    assert manager.build_agent_context("ctx", "agent-b")["private"] == {"secret": "b"}


def test_readonly_update_appends_new_version():
    manager = ContextManager(compress_threshold_chars=1000)
    manager.record_task_context("ctx", "agent-a", readonly_data={"policy": "v1"})
    manager.update_context("ctx", "agent-b", {"readonly": {"policy": "v2"}})

    built = manager.build_agent_context("ctx", "agent-a")
    history = manager.readonly_history("ctx", "policy")

    assert built["readonly"] == {"policy": "v2"}
    assert [item["version"] for item in history] == [1, 2]
    assert manager.get_context("ctx").context_diff["readonly"]["policy"] == {"new_version": 2}


def test_rollback_increments_version_and_records_diff():
    manager = ContextManager(compress_threshold_chars=20)
    ctx = manager.record_task_context("ctx", "agent-a", shared_data={"goal": "ship", "long": "abcdefghijklmnopqrstuvwxyz"})
    version = ctx.version

    assert manager.rollback_context("ctx") is True

    rolled = manager.get_context("ctx")
    assert rolled.version == version + 1
    assert rolled.context_diff == {"rollback": True}
