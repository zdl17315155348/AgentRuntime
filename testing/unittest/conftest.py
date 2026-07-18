# testing/unittest/conftest.py

import os
import subprocess
import sys
import time

import httpx
import pytest


@pytest.fixture(scope="module")
def agentd_server():
    """启动 agentd（Mock 模式）作为测试服务"""
    env = os.environ.copy()
    env["LLM_BACKEND"] = "mock"
    env["LLM_API_KEY"] = ""
    env["SCHEDULER_TYPE"] = "dag"

    try:
        subprocess.run(
            ["fuser", "-k", "8234/tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        pass

    proc = subprocess.Popen(
        [sys.executable, "-m", "aruntime.daemon.main"],
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 15
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            with httpx.Client(base_url="http://127.0.0.1:8234", timeout=1, trust_env=False) as c:
                resp = c.get("/metrics")
                if resp.status_code == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.25)
            continue
        time.sleep(0.25)
    if not ready:
        out = ""
        err = ""
        try:
            out = proc.stdout.read().decode("utf-8", errors="ignore") if proc.stdout else ""
            err = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
        except Exception:
            pass
        proc.terminate()
        proc.wait()
        raise RuntimeError(f"agentd unavailable in current environment\nstdout:\n{out}\nstderr:\n{err}")
    yield
    proc.terminate()
    proc.wait()


@pytest.fixture
def client(agentd_server):
    """提供 HTTP 客户端"""
    with httpx.Client(base_url="http://127.0.0.1:8234", timeout=10) as c:
        yield c
