"""用前端实际 JavaScript 请求封装访问临时 HTTP 后端，不使用浏览器或真实模型。"""

import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import uvicorn

from app.cli import add_user, migrate
from app.core.config import Settings
from app.db import begin_write
from app.main import create_app
from team_modules.factory import build_modules
from tests.test_team_integration import ScriptedModel

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_resources_and_stores_against_real_http(tmp_path):
    node = shutil.which("node")
    esbuild = ROOT / "frontend/web/node_modules/esbuild/lib/main.js"
    if not node or not esbuild.exists():
        pytest.skip("前端真实 HTTP 验证需要 Node.js 和 frontend/web 下已安装的 npm 依赖")
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_secret="isolated-frontend-" * 3,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_dir=tmp_path / "files",
        llm_mode="disabled",
        llm_api_key="",
    )
    migrate(settings.database_url)
    app = create_app(settings, modules=build_modules(settings=settings, llm=ScriptedModel()))
    with app.state.sessions() as db:
        begin_write(db)
        add_user(db, "web-test", "接口联调用户", "test-password-123")
        db.commit()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        ready = threading.Event()

        # Server.run 在独立线程运行，不修改用户正在运行的 API/Worker。
        def serve():
            ready.set()
            server.run(sockets=[listener])

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        ready.wait(5)
        try:
            import time

            for _ in range(200):
                if server.started:
                    break
                time.sleep(0.05)
            assert server.started
            bundle = tmp_path / "frontend-check.mjs"
            # 用与 Vite 相同的源码，编译别名和 import.meta.env 后在 Node 执行。
            script = """
const esbuild = require(process.argv[1]);
esbuild.buildSync({ entryPoints: [process.argv[2]], outfile: process.argv[3],
  bundle: true, platform: 'node', format: 'esm',
  alias: { '@': process.argv[4] },
  define: { 'import.meta.env': JSON.stringify({ VITE_API_BASE: process.argv[5], VITE_DEFAULT_MODE: 'live' }) }
});
"""
            subprocess.run(
                [
                    node,
                    "-e",
                    script,
                    str(esbuild),
                    str(ROOT / "frontend/tests/live_api_check.mjs"),
                    str(bundle),
                    str(ROOT / "frontend/web/src"),
                    f"http://127.0.0.1:{port}/api/v1",
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            result = subprocess.run(
                [node, str(bundle)], capture_output=True, text=True, encoding="utf-8", timeout=30
            )
            assert result.returncode == 0, result.stderr + result.stdout
            assert "PASS: frontend live" in result.stdout
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive()
