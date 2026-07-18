#!/usr/bin/env bash
set -euo pipefail

make smoke
make test
make test-integration
make test-demo
bash examples/production_incident_demo/scripts/run_fault.sh
make benchmark
