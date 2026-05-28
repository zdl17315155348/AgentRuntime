# testing/unittest/conftest.py

import pytest
import httpx
import subprocess
import time
import os
import sys


@pytest.fixture(scope="module")
def agentd_server():
    """启动 agentd（Mock 模式）作为测试服务"""
    env = os.environ.copy()
    env["LLM_BACKEND"] = "mock"
    env["LLM_API_KEY"] = ""

    proc = subprocess.Popen(
        [sys.executable, "-m", "aruntime.daemon.main"],
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    yield
    proc.terminate()
    proc.wait()


@pytest.fixture
def client():
    """提供 HTTP 客户端"""
    with httpx.Client(base_url="http://127.0.0.1:8234", timeout=10) as c:
        yield c