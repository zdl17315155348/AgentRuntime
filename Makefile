.PHONY: install run-agentd run-demo clean

install:
	pip install -e .

run-agentd:
	python -m aruntime.daemon.main

run-demo:
	python -m aruntime.cli.main submit examples/code_repair/workflow.yaml

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete