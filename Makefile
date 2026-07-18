.PHONY: install run-agentd run-demo smoke test test-integration test-demo benchmark clean

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
	LLM_BACKEND=mock LLM_API_KEY="" SCHEDULER_TYPE=dag python3 -m aruntime.daemon.main >/tmp/agentd_make_integration.log 2>&1 & \
	AGENTD_PID=$$!; \
	trap 'kill $$AGENTD_PID >/dev/null 2>&1 || true; wait $$AGENTD_PID >/dev/null 2>&1 || true' EXIT INT TERM; \
	for i in $$(seq 1 60); do \
		python3 -c "import httpx; raise SystemExit(0 if httpx.get('http://127.0.0.1:8234/metrics', timeout=1, trust_env=False).status_code == 200 else 1)" >/dev/null 2>&1 && break; \
		sleep 0.25; \
	done; \
	python3 -m pytest testing/integration -q

test-demo:
	bash examples/production_incident_demo/scripts/run_normal.sh

benchmark:
	python3 -m pytest testing/perf/test_benchmark.py -q

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
