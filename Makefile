.PHONY: install run-agentd run-demo smoke test test-integration test-demo test-demo-fault benchmark final-check clean

install:
	pip install -e .

run-agentd:
	python3 -m aruntime.daemon.main

run-demo:
	bash examples/production_incident_demo/scripts/run_normal.sh

smoke:
	python3 -c "from aruntime.daemon.main import app; print(app.title)"

test:
	python3 -m pytest testing/unittest -q

test-integration:
	python3 -m pytest testing/integration/test_daemon_restart.py -q
	fuser -k 8234/tcp >/dev/null 2>&1 || true; \
	rm -f /tmp/agent-runtime-agentd.sock /tmp/agent-runtime-os/state.db /tmp/agent-runtime-os/state.db-wal /tmp/agent-runtime-os/state.db-shm; \
	LLM_BACKEND=mock LLM_API_KEY="" SCHEDULER_TYPE=dag python3 -m aruntime.daemon.main >/tmp/agentd_make_integration.log 2>&1 & \
	AGENTD_PID=$$!; \
	trap 'kill $$AGENTD_PID >/dev/null 2>&1 || true; wait $$AGENTD_PID >/dev/null 2>&1 || true' EXIT INT TERM; \
	READY=0; \
	for i in $$(seq 1 60); do \
		kill -0 $$AGENTD_PID >/dev/null 2>&1 || { cat /tmp/agentd_make_integration.log >&2; exit 1; }; \
		python3 -c "import httpx; raise SystemExit(0 if httpx.get('http://127.0.0.1:8234/metrics', timeout=1, trust_env=False).status_code == 200 else 1)" >/dev/null 2>&1 && { READY=1; break; }; \
		sleep 0.25; \
	done; \
	[ "$$READY" = 1 ] || { cat /tmp/agentd_make_integration.log >&2; exit 1; }; \
	python3 -m pytest testing/integration/test_worker_fallback.py -q

test-demo:
	python3 -m pytest \
		testing/integration/test_demo.py::test_production_incident_demo_normal_runs \
		-q

test-demo-fault:
	python3 -m pytest \
		testing/integration/test_demo.py::test_production_incident_demo_fault_uses_runtime_fallback \
		-q

final-check:
	$(MAKE) smoke
	$(MAKE) test
	$(MAKE) test-integration
	$(MAKE) test-demo
	$(MAKE) test-demo-fault
	$(MAKE) benchmark

benchmark:
	python3 -m pytest testing/perf/test_benchmark.py -q

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
