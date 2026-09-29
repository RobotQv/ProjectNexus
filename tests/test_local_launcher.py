"""启动器的离线回归，不使用个人数据库或真实模型。"""

import importlib.util
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_launcher", ROOT / "scripts/launch_local.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_startup_lock_rejects_duplicate_and_releases(tmp_path):
    with launcher.startup_lock(tmp_path):
        with pytest.raises(RuntimeError, match="已有一键启动进程"):
            with launcher.startup_lock(tmp_path):
                pytest.fail("重复启动不应拿到锁")
    with launcher.startup_lock(tmp_path):
        pass


def test_occupied_port_is_not_taken_over():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(RuntimeError, match="已占用"):
            launcher.check_port(listener.getsockname()[1])
        assert listener.fileno() >= 0


def test_dependency_fingerprint_changes(tmp_path):
    dependency = tmp_path / "lock.txt"
    dependency.write_text("v1")
    before = launcher.dependency_fingerprint(dependency)
    dependency.write_text("v2")
    assert launcher.dependency_fingerprint(dependency) != before


def test_initial_config_is_random_and_never_overwritten(tmp_path, monkeypatch):
    from app import cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text(
        "NEXUS_JWT_SECRET=replace-with-a-random-secret-at-least-32-characters\n"
        "NEXUS_LLM_MODE=disabled\n",
        encoding="utf-8",
    )
    cli.init_env()
    config = tmp_path / ".env"
    before = config.read_bytes()
    assert "replace-with" not in before.decode()
    assert len(before.decode().splitlines()[0].split("=")[1]) == 64
    cli.init_env()
    assert config.read_bytes() == before


def test_bootstrap_installs_once_and_builds_live_without_editing_config(tmp_path, monkeypatch):
    root = tmp_path / "中文 project"
    web = root / "frontend/web"
    (web / "node_modules/vite/bin").mkdir(parents=True)
    (web / "node_modules/vite/bin/vite.js").write_text("")
    (web / "dist").mkdir()
    (web / "dist/index.html").write_text("test")
    (root / ".venv").mkdir()
    for file in [
        root / "requirements.integration.lock.txt",
        root / "pyproject.toml",
        web / "package.json",
        web / "package-lock.json",
    ]:
        file.write_text("placeholder")
    config = web / ".env.local"
    config.write_text("VITE_DEFAULT_MODE=demo")
    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher, "WEB", web)
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "npm")
    calls = []

    class PreparationFinished(Exception):
        pass

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[-1] == "init-env":
            raise PreparationFinished  # 此处之后的迁移/账号流程由隔离实测覆盖。

    monkeypatch.setattr(launcher, "run", fake_run)
    args = SimpleNamespace(skip_install=False, skip_build=False)
    for _ in range(2):
        with pytest.raises(PreparationFinished):
            launcher.prepare(args, root)
    assert sum("pip" in cmd and "install" in cmd for cmd, _ in calls) == 2
    assert sum(cmd == ["npm", "ci"] for cmd, _ in calls) == 1
    builds = [kwargs for cmd, kwargs in calls if cmd == ["npm", "run", "build"]]
    assert len(builds) == 2
    assert all(item["env"]["VITE_DEFAULT_MODE"] == "live" for item in builds)
    assert all(item["env"]["VITE_API_BASE"] == "/api/v1" for item in builds)
    assert config.read_text() == "VITE_DEFAULT_MODE=demo"


def test_stop_owned_reaps_child_tree(tmp_path):
    # Windows venv有一层转发器。用实际解释器启动监听进程，验证端口随退出释放。
    port_file = tmp_path / "port"
    code = (
        "import socket,time,pathlib; s=socket.socket(); s.bind(('127.0.0.1',0)); "
        "s.listen(); pathlib.Path(__import__('sys').argv[1]).write_text(str(s.getsockname()[1])); "
        "time.sleep(90)"
    )
    process = subprocess.Popen([sys.executable, "-c", code, str(port_file)])
    try:
        for _ in range(100):
            if port_file.exists() and port_file.read_text():
                break
            time.sleep(0.05)
        port = int(port_file.read_text())
        launcher.stop_owned([process])
        assert process.poll() is not None
        launcher.check_port(port)
    finally:
        launcher.stop_owned([process])


def test_real_launcher_serves_and_stops_without_touching_user_config(tmp_path):
    if not (ROOT / "frontend/web/dist/index.html").exists():
        pytest.skip("需要先构建前端；本测试不联网安装依赖")
    # 运行两次，确认可重新启动、账号不会重复，原.env逐字节不变。
    import sqlite3

    config = ROOT / ".env"
    if not config.exists():
        pytest.skip("本测试只验证已有配置；首次init-env由CLI测试覆盖")
    before = config.read_bytes()
    database = tmp_path / "启动验证.db"
    env = {
        **os.environ,
        "NEXUS_ENVIRONMENT": "test",
        "NEXUS_DATABASE_URL": f"sqlite:///{database.as_posix()}",
        "NEXUS_STORAGE_DIR": str(tmp_path / "files"),
        "NEXUS_JWT_SECRET": "launcher-isolated-test-secret-00000000000",
        "NEXUS_MODULE_MODE": "disabled",
        "NEXUS_MODULE_FACTORY": "",
        "NEXUS_LLM_MODE": "disabled",
        "NEXUS_LLM_API_KEY": "",
        "PYTHONUTF8": "1",
    }
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(2):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        log_path = tmp_path / f"launch-{attempt}.log"
        with log_path.open("w", encoding="utf-8") as output:
            entry = [sys.executable, str(ROOT / "scripts/launch_local.py")]
            if os.name == "nt" and attempt == 0:
                # 同时验证根目录双击入口，不只验证Python内部实现。
                entry = ["cmd.exe", "/d", "/c", str(ROOT / "start.cmd")]
            process = subprocess.Popen(
                [
                    *entry,
                    "--skip-install",
                    "--skip-build",
                    "--no-browser",
                    "--port",
                    str(port),
                    "--state-dir",
                    str(tmp_path / "启动日志"),
                ],
                cwd=tmp_path,
                env=env,
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(200):
                    assert process.poll() is None, log_path.read_text(encoding="utf-8")
                    # 等启动器自己的就绪输出，避免在input线程创建前停止。
                    if "保留此窗口" in log_path.read_text(encoding="utf-8"):
                        break
                    time.sleep(0.1)
                else:
                    pytest.fail(log_path.read_text(encoding="utf-8"))
                with opener.open(f"http://127.0.0.1:{port}/", timeout=5) as response:
                    assert b'<div id="app">' in response.read()
                with opener.open(f"http://127.0.0.1:{port}/docs", timeout=5) as response:
                    assert response.status == 200
                process.communicate(input=b"\n", timeout=20)
                assert process.returncode == 0, log_path.read_text(encoding="utf-8")
                launcher.check_port(port)
            finally:
                launcher.stop_owned([process])
        assert config.read_bytes() == before
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 6
