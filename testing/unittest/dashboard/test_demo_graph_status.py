from pathlib import Path


def test_demo_uses_final_graph_status_for_reviewer():
    source = Path("aruntime/dashboard/js/demo.js").read_text(encoding="utf-8")
    assert "const displaySummary = mergeSummaryWithGraph(summary, graph);" in source
    assert "stopPollingIfTerminal(displaySummary);" in source
    assert "function mergeSummaryWithGraph(summary, graph)" in source
    assert "if (state.workflow_status === \"SUCCESS\") return \"SUCCESS\";" in source
    assert "old reviewer failure" not in source
    assert "Re-reviewing repaired patch" in source


def test_demo_renders_agent_topology():
    source = Path("aruntime/dashboard/js/demo.js").read_text(encoding="utf-8")
    styles = Path("aruntime/dashboard/styles.css").read_text(encoding="utf-8")
    html = Path("aruntime/dashboard/demo.html").read_text(encoding="utf-8")
    assert "function topology(nodes, state)" in source
    assert "class=\"topology live-topology\"" in source
    assert "class=\"topology-meta\"" in source
    assert "class=\"topology-counts\"" in source
    assert "activeTopologyNode(nodes)" in source
    assert "topo-edge ${escapeHtml(status)}${live}" in source
    assert "marker id=\"topology-arrow\"" in source
    assert "ellipse class=\"node-ring\"" in source
    assert "graphNode(\"reviewer\", \"Reviewer\", \"reviewer\"" in source
    assert "[\"tester\", \"repair\"]" in source
    assert "id=\"topology\" hidden" in html
    assert "AgentRuntime OS" in html
    assert "/dashboard/styles.css?v=0.1.169" in html
    assert "/dashboard/js/demo.js?v=0.1.169" in html


def test_demo_renders_langgraph_flow_panel():
    source = Path("aruntime/dashboard/js/demo.js").read_text(encoding="utf-8")
    styles = Path("aruntime/dashboard/styles.css").read_text(encoding="utf-8")
    assert "class=\"langgraph-panel\"" in source
    assert "Workflow Status" in source
    assert "Active Node" in source
    assert "function renderGraphTopology(nodes)" in source
    assert "class=\"langgraph-topology\"" in source
    assert "marker id=\"langgraph-arrow\"" in source
    assert "[\"reviewer\", \"repair\"]" in source
    assert "[\"repair\", \"tester\"]" in source
    assert "<line class=\"graph-edge" in source
    assert "const edges = [\n    [\"planner\", \"coder\"]," in source
    assert "    [\"repair\", \"tester\"],\n    [\"tester\", \"reviewer\"]," in source
    assert "function graphStep(item, index)" in source
    assert "class=\"node-status-pill\"" in source
    assert "function firstFailureMessage(testSummary)" in source
    assert "ModuleNotFoundError: No module named" in source
    assert ".langgraph-head" in styles
    assert ".graph-step.RECOVERING" in styles
    assert ".node-status-pill" in styles
    assert "border-radius: 999px" in styles
    assert ".langgraph-topology" in styles
    assert ".graph-edge" in styles


def test_demo_page_groups_content_into_sections():
    html = Path("aruntime/dashboard/demo.html").read_text(encoding="utf-8")
    styles = Path("aruntime/dashboard/styles.css").read_text(encoding="utf-8")
    assert "LangGraph 执行拓扑" in html
    assert "当前智能体" in html
    assert "监控 & 任务队列" in html
    assert "运行输出" not in html
    assert "class=\"status-grid\"" in html
    assert "class=\"output-grid\"" not in html
    assert ".dashboard-shell" in styles
    assert ".app-header" in styles
    assert ".status-grid" in styles
    assert ".output-grid" not in styles


def test_demo_matches_dark_console_reference_layout():
    source = Path("aruntime/dashboard/js/demo.js").read_text(encoding="utf-8")
    styles = Path("aruntime/dashboard/styles.css").read_text(encoding="utf-8")
    html = Path("aruntime/dashboard/demo.html").read_text(encoding="utf-8")
    assert "brand-mark" in html
    assert "version-pill" in html
    assert "live-dot" in html
    assert "focus-task" in source
    assert "monitor-metrics" in source
    assert "运行耗时" in source
    assert "Runtime任务" in source
    assert "Attempt次数" in source
    assert "峰值内存" not in source
    assert "后端延迟" not in source
    assert "function formatDuration(ms)" in source
    assert "repair-note" in source
    assert ".footer-stats" in styles
    assert "background: #151a21" in styles
    assert "border-radius: 28px" in styles


def test_demo_cancel_clears_page_even_when_backend_cancel_fails():
    source = Path("aruntime/dashboard/js/demo.js").read_text(encoding="utf-8")
    assert "function clearDisplayedRun(status)" in source
    assert "try {" in source
    assert "await apiPost(`/demo/runs/${runId}/cancel`, {});" in source
    assert "cancel failed or run already deleted" in source
    assert "clearDisplayedRun(\"DELETED\");" in source
