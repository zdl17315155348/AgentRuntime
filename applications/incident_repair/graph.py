from __future__ import annotations

from applications.incident_repair.config import GraphRuntimeContext
from applications.incident_repair.nodes import coder_node, integrate_node, planner_node, repair_node, reviewer_node, tester_node
from applications.incident_repair.nodes.common import context_from_runtime
from applications.incident_repair.routing import coder_tasks, route_after_review, route_after_test
from applications.incident_repair.state import IncidentRepairState


def dispatch_coders(state: IncidentRepairState):
    try:
        from langgraph.types import Send
    except ModuleNotFoundError:
        return [{"node": "coder", "state": {**state, "active_coder_task": task}} for task in coder_tasks(state)]
    return [Send("coder", {**state, "active_coder_task": task}) for task in coder_tasks(state)]


def failed_node(state: IncidentRepairState, runtime=None):
    return {"workflow_status": "FAILED", "error": state.get("error") or "workflow failed"}


def success_node(state: IncidentRepairState, runtime=None):
    return {"workflow_status": "SUCCESS", "error": None}


def route_after_test_with_context(state: IncidentRepairState, runtime=None) -> str:
    context = context_from_runtime(runtime)
    return route_after_test(state, context.run_config.max_repair_rounds)


def route_after_review_with_context(state: IncidentRepairState, runtime=None) -> str:
    context = context_from_runtime(runtime)
    return route_after_review(state, context.run_config.max_repair_rounds)


def build_graph(checkpointer=None):
    try:
        from langgraph.graph import END, START, StateGraph
    except ModuleNotFoundError as exc:
        raise RuntimeError("langgraph is required to build the executable graph") from exc
    builder = StateGraph(IncidentRepairState, context_schema=GraphRuntimeContext)
    builder.add_node("planner", planner_node)
    builder.add_node("coder", coder_node)
    builder.add_node("integrate", integrate_node)
    builder.add_node("tester", tester_node)
    builder.add_node("repair", repair_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("success", success_node)
    builder.add_node("failed", failed_node)
    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", dispatch_coders, ["coder"])
    builder.add_edge("coder", "integrate")
    builder.add_edge("integrate", "tester")
    builder.add_conditional_edges("tester", route_after_test_with_context, {"repair": "repair", "reviewer": "reviewer", "failed": "failed"})
    builder.add_edge("repair", "integrate")
    builder.add_conditional_edges("reviewer", route_after_review_with_context, {"repair": "repair", "success": "success", "failed": "failed"})
    builder.add_edge("success", END)
    builder.add_edge("failed", END)
    return builder.compile(checkpointer=checkpointer)
