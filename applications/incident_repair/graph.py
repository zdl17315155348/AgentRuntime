from __future__ import annotations

from applications.incident_repair.config import GraphRuntimeContext
from applications.incident_repair.nodes import (
    coder_node,
    integrate_coder_node,
    integrate_repair_node,
    planner_node,
    repair_node,
    reviewer_node,
    route_after_select,
    select_coder_node,
    tester_node,
)
from applications.incident_repair.nodes.common import context_from_runtime
from applications.incident_repair.routing import route_after_review, route_after_test
from applications.incident_repair.state import IncidentRepairState


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
    builder.add_node("select_coder", select_coder_node)
    builder.add_node("coder", coder_node)
    builder.add_node("integrate_coder", integrate_coder_node)
    builder.add_node("integrate_repair", integrate_repair_node)
    builder.add_node("tester", tester_node)
    builder.add_node("repair", repair_node)
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("success", success_node)
    builder.add_node("failed", failed_node)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "select_coder")
    builder.add_conditional_edges("select_coder", route_after_select, {"coder": "coder", "tester": "tester", "failed": "failed"})
    builder.add_edge("coder", "integrate_coder")
    builder.add_edge("integrate_coder", "select_coder")
    builder.add_conditional_edges("tester", route_after_test_with_context, {"repair": "repair", "reviewer": "reviewer", "failed": "failed"})
    builder.add_edge("repair", "integrate_repair")
    builder.add_edge("integrate_repair", "tester")
    builder.add_conditional_edges("reviewer", route_after_review_with_context, {"repair": "repair", "success": "success", "failed": "failed"})
    builder.add_edge("success", END)
    builder.add_edge("failed", END)
    return builder.compile(checkpointer=checkpointer)
