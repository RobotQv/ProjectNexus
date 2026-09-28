"""实际子进程启动 HTTP / Worker，补充 TestClient 之外的部署入口检查。"""

import os
import socket
import subprocess
import sys
import time

import httpx

from app.cli import ROOT, migrate


def test_real_uvicorn_and_worker(tmp_path):
    url = f"sqlite:///{tmp_path / 'live.db'}"
    migrate(url)
    runtime_env = os.environ | {
        "NEXUS_ENVIRONMENT": "test",
        "NEXUS_DATABASE_URL": url,
        "NEXUS_STORAGE_DIR": str(tmp_path / "files"),
        "NEXUS_JWT_SECRET": "test-secret-" * 5,
        "NEXUS_MODULE_MODE": "disabled",
        "NEXUS_MODULE_FACTORY": "",
        "NEXUS_LLM_MODE": "disabled",
    }
    # 自动选空闲端口，不占用用户常用的 8000。
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        cwd=ROOT,
        env=runtime_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    try:
        deadline = time.monotonic() + 20
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2
        ) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(process.communicate()[0].decode(errors="replace"))
                try:
                    response = client.get("/health/ready")
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    time.sleep(0.1)
            else:
                raise AssertionError("HTTP 启动超时")
            assert response.status_code == 200, response.text
            assert client.get("/api/v1/projects").status_code == 401
            assert "/api/v1/projects/{pid}/queries" in client.get("/openapi.json").json()["paths"]
        worker = subprocess.run(
            [sys.executable, "-m", "app.worker", "--once"],
            cwd=ROOT,
            env=runtime_env,
            capture_output=True,
            timeout=20,
            creationflags=flags,
        )
        assert worker.returncode == 0, worker.stderr.decode(errors="replace")
    finally:
        # 只终止本测试创建的子进程，不查找或终止用户已有的 Python 服务。
        process.terminate()
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
