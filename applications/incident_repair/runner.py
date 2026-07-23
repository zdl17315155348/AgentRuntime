from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Awaitable, Callable

from applications.incident_repair.config import GraphRuntimeContext, default_checkpoint_path
from applications.incident_repair.graph import build_graph


class IncidentGraphRunner:
    def __init__(self, checkpoint_path: str | Path | None = None):
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else default_checkpoint_path()

    async def run(
        self,
        state: dict[str, Any],
        context: GraphRuntimeContext,
        on_update: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ModuleNotFoundError as exc:
            raise RuntimeError("langgraph-checkpoint-sqlite is required for incident_repair runs") from exc
        async with AsyncExitStack() as stack:
            checkpointer = await stack.enter_async_context(AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path)))
            graph = build_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": state["thread_id"]}}
            current_state = dict(state)
            async for update in graph.astream(state, config=config, context=context, stream_mode="updates"):
                if not isinstance(update, dict):
                    continue
                for node_name, node_update in update.items():
                    if not isinstance(node_update, dict):
                        continue
                    current_state.update(node_update)
                    if on_update:
                        maybe_awaitable = on_update(str(node_name), dict(current_state))
                        if hasattr(maybe_awaitable, "__await__"):
                            await maybe_awaitable
            return current_state
