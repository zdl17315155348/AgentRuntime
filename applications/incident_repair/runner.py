from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from applications.incident_repair.config import GraphRuntimeContext, default_checkpoint_path
from applications.incident_repair.graph import build_graph


class IncidentGraphRunner:
    def __init__(self, checkpoint_path: str | Path | None = None):
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else default_checkpoint_path()

    async def run(self, state: dict[str, Any], context: GraphRuntimeContext) -> dict[str, Any]:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ModuleNotFoundError as exc:
            raise RuntimeError("langgraph-checkpoint-sqlite is required for incident_repair runs") from exc
        async with AsyncExitStack() as stack:
            checkpointer = await stack.enter_async_context(AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path)))
            graph = build_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": state["thread_id"]}}
            return await graph.ainvoke(state, config=config, context=context)
