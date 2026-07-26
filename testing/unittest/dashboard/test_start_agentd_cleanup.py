from pathlib import Path
import subprocess


def test_start_agentd_docker_cleans_demo_runs_and_runtime_state():
    source = Path("scripts/start_agentd_docker.sh").read_text(encoding="utf-8")
    assert 'CLEAN_RUNS_ON_START="${CLEAN_RUNS_ON_START:-1}"' in source
    assert 'CLEAN_RUNS_ON_EXIT="${CLEAN_RUNS_ON_EXIT:-1}"' in source
    assert 'CLEAN_RUNTIME_ON_START="${CLEAN_RUNTIME_ON_START:-$CLEAN_RUNS_ON_START}"' in source
    assert 'CLEAN_RUNTIME_ON_EXIT="${CLEAN_RUNTIME_ON_EXIT:-$CLEAN_RUNS_ON_EXIT}"' in source
    assert "trap cleanup_on_exit EXIT" in source
    assert "cleanup_image()" in source
    assert "openeuler/openeuler:24.03-lts" in source
    assert "find \"$live_dir\" -mindepth 1 -maxdepth 1 -type d -name 'run_*' -exec rm -rf {} + 2>/dev/null" in source
    assert "宿主清理权限不足，改用 Docker 清理 root-owned demo run" in source
    assert "$DOCKER run --rm --privileged -v \"$live_dir:/cleanup-live\" \"$image\"" in source
    assert "find /cleanup-live -mindepth 1 -maxdepth 1 -type d -name 'run_*' -exec rm -rf {} +" in source
    assert "function clean_runtime_state" not in source
    assert "clean_runtime_state()" in source
    assert "state.db-wal" in source
    assert "$DOCKER run --rm --privileged -v \"$STATE_DIR:/cleanup-state\" \"$image\"" in source
    assert "$DOCKER run --rm --privileged -v \"$runtime_dir:/cleanup-runtime\" \"$image\"" in source
    assert "find /cleanup-runtime -mindepth 1 -maxdepth 1 -type d \\( -name 'run_*' -o -name 'task_*' \\)" in source
    assert "$DOCKER rm -f \"$CONTAINER_NAME\"" in source
    assert "clean_live_runs \"启动前旧\"" in source
    assert "clean_live_runs \"退出时\"" in source
    assert "clean_runtime_state \"启动前旧\"" in source
    assert "clean_runtime_state \"退出时\"" in source
    assert "CONFIG_BACKEND=" in source
    assert "缺少 DeepSeek Key" in source


def test_start_agentd_docker_cleanup_suppresses_permission_denied(tmp_path):
    script = Path("scripts/start_agentd_docker.sh").resolve()
    project_dir = script.parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text(
        f"""#!/bin/sh
echo "$@" >> "{docker_log}"
if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
  exit 0
fi
if [ "$1" = "run" ]; then
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    fake_find = fake_bin / "find"
    fake_find.write_text("#!/bin/sh\necho 'rm: cannot remove file: Permission denied' >&2\nexit 1\n", encoding="utf-8")
    fake_find.chmod(0o755)

    cmd = (
        "set -e; "
        "source scripts/start_agentd_docker.sh; "
        "DOCKER=docker; "
        f"SHARED_RUN_DATA_DIR='{tmp_path / 'run-data'}'; "
        f"STATE_DIR='{tmp_path / 'state'}'; "
        f"WORKSPACE_DIR='{tmp_path / 'workspaces'}'; "
        f"ARTIFACT_DIR='{tmp_path / 'artifacts'}'; "
        "mkdir -p \"$SHARED_RUN_DATA_DIR/live/run_old\" \"$STATE_DIR\" \"$WORKSPACE_DIR/run_old\" \"$ARTIFACT_DIR/task_old\"; "
        "clean_live_runs test; "
        "clean_runtime_state test"
    )
    result = subprocess.run(
        ["bash", "-lc", cmd],
        cwd=project_dir,
        env={"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(tmp_path), "AGENTD_START_AGENTD_DOCKER_SOURCE_ONLY": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Permission denied" not in result.stderr
    assert "宿主清理权限不足，改用 Docker 清理 root-owned demo run" in result.stdout
    assert "宿主清理权限不足，改用 Docker 清理 root-owned agentd state" in result.stdout
    assert "宿主清理权限不足，改用 Docker 清理 root-owned runtime 目录" in result.stdout
    assert "run --rm --privileged" in docker_log.read_text(encoding="utf-8")
