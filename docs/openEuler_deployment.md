# openEuler Deployment

## Docker build

```bash
docker build -f deploy/Dockerfile.openeuler -t agent-runtime-os:openeuler .
```

## Run

```bash
docker run --rm -p 8234:8234 \
  -e DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e AGENTD_ENABLE_FAULT_INJECTION=true \
  agent-runtime-os:openeuler
```

Codex config can be mounted read-only:

```bash
-v "$HOME/.codex/config.toml:/root/.codex/config.toml:ro"
```

## Compose

```bash
docker compose -f deploy/docker-compose.demo.yml up --build
```

## Preflight

```bash
python3 scripts/preflight_openeuler.py --require-real
```

Checks include openEuler, Python, Git, Codex, target repo, pytest, agentd, Dashboard route, cgroup v2, DeepSeek key and Codex key. API keys are read from environment only.
