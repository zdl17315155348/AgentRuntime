from aruntime.backends.codex_cli import sanitize_codex_event


def test_sanitize_codex_command_event_omits_reasoning():
    event = {
        "type": "item.completed",
        "item": {"type": "command_execution", "command": ["python3", "-m", "pytest", "-q"], "reasoning": "secret"},
    }

    clean = sanitize_codex_event(event)

    assert clean["name"] == "tool.command.completed"
    assert clean["command"] == "python3 -m pytest -q"
    assert "reasoning" not in clean
