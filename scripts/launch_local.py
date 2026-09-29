"""本机一键启动：保留配置/业务库，管理自己创建的API与Worker进程。

这里只在同一个控制台启动子进程，不打开后台窗口。按Enter/Ctrl+C退出时
回收自己持有的Popen进程；不会按端口或进程名终止其他服务。
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "frontend" / "web"


def run(command, *, cwd=ROOT, env=None):
    subprocess.run(command, cwd=cwd, env=env, check=True)


def dependency_fingerprint(*paths):
    digest = hashlib.sha256(sys.version.encode())
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def ensure_venv(argv):
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        print("首次启动：创建项目虚拟环境……", flush=True)
        run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    if Path(sys.executable).resolve() != python.resolve():
        return subprocess.call([str(python), str(Path(__file__).resolve()), *argv], cwd=ROOT)
    return None


@contextmanager
def startup_lock(state):
    """操作系统文件锁，进程退出自动释放，不以旧PID文件决定是否杀进程。"""
    state.mkdir(parents=True, exist_ok=True)
    with (state / "launcher.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("该目录已有一键启动进程，请先在原启动窗口停止。") from None
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("该目录已有一键启动进程，请先停止原服务。") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def check_port(port):
    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(
                f"端口{port}已占用。请停止原服务，或用 start.cmd --port 8001。"
            ) from None


def prepare(args, state):
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("未找到npm。请安装Node.js 20.19+或22.12+，再重新打开启动窗口。")
    python_stamp = ROOT / ".venv" / ".nexus-dependencies.sha256"
    expected = dependency_fingerprint(
        ROOT / "requirements.integration.lock.txt", ROOT / "pyproject.toml"
    )
    if not args.skip_install:
        if not python_stamp.exists() or python_stamp.read_text() != expected:
            print("检查并安装Python集成依赖（首次需要联网）……", flush=True)
            run([sys.executable, "-m", "pip", "install", "-r", "requirements.integration.lock.txt"])
            run([sys.executable, "-m", "pip", "install", "-e", ".", "--no-deps"])
            python_stamp.write_text(expected)
        node_stamp = state / "node-dependencies.sha256"
        expected_node = dependency_fingerprint(WEB / "package.json", WEB / "package-lock.json")
        if (
            not (WEB / "node_modules" / "vite" / "bin" / "vite.js").exists()
            or not node_stamp.exists()
            or node_stamp.read_text() != expected_node
        ):
            print("检查并安装前端依赖……", flush=True)
            run([npm, "ci"], cwd=WEB)
            node_stamp.write_text(expected_node)
    # 仅子进程使用同源API/真实后端模式，不写入用户的.env.local。
    env = {**os.environ, "VITE_API_BASE": "/api/v1", "VITE_DEFAULT_MODE": "live"}
    if not args.skip_build:
        print("构建前端……", flush=True)
        run([npm, "run", "build"], cwd=WEB, env=env)
    if not (WEB / "dist" / "index.html").is_file():
        raise RuntimeError("缺少前端构建产物，请去掉--skip-build后重试。")
    run([sys.executable, "-m", "app.cli", "init-env"])
    # 避免脚本目录优先级影响包导入，同时保持所有相对配置基于项目根目录。
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.db import begin_write, build_engine, session_factory
    from app.dev_accounts import seed_students
    from app.models import User

    settings = get_settings()
    if settings.environment == "production":
        raise RuntimeError("一键启动仅用于本地development/test，不用于生产部署。")
    run([sys.executable, "-m", "app.cli", "migrate"])
    engine = build_engine(settings.database_url)
    try:
        with session_factory(engine)() as db:
            begin_write(db)
            if db.scalar(select(User.id).limit(1)) is None:
                seed_students(db, environment=settings.environment)
                db.commit()
                print("空库账号已初始化，登录方式见根目录README。", flush=True)
    finally:
        engine.dispose()
    if settings.llm_mode == "disabled":
        print("提示：本机模型未启用，基础业务可用。真实AI需自行配置.env。", flush=True)
    return {**os.environ, "NEXUS_WEB_DIST_DIR": str(WEB / "dist"), "PYTHONUNBUFFERED": "1"}


def stop_owned(processes):
    for process in reversed(processes):
        if process.poll() is None:
            if os.name == "nt":
                # Windows venv解释器还会启动真正的Python子进程，必须回收整棵树。
                # 只使用本次Popen持有的、仍在运行的PID，不按端口/进程名清理。
                result = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if result.returncode and process.poll() is None:
                    raise RuntimeError(
                        f"无法停止本次子进程{process.pid}，请关闭启动窗口并检查日志。"
                    )
            else:
                process.terminate()
    for process in reversed(processes):
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def serve(args, state, env):
    processes, logs = [], []
    commands = [
        (
            "api",
            [
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
            ],
        ),
        ("worker", ["-m", "app.worker"]),
    ]
    url = f"http://127.0.0.1:{args.port}"
    try:
        for role, arguments in commands:
            log = (state / f"{role}.log").open("a", encoding="utf-8")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    [sys.executable, *arguments],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
            print(f"{role} PID: {processes[-1].pid}", flush=True)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if any(p.poll() is not None for p in processes):
                raise RuntimeError(f"API或Worker启动失败，请查看{state}中的日志。")
            try:
                with opener.open(url + "/health/ready", timeout=2) as response:
                    if json.load(response).get("status") == "ready":
                        break
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError(f"等待服务就绪超时，请查看{state}中的日志。")
        print(f"\nProjectNexus已启动：{url}\nAPI文档：{url}/docs\n日志：{state}", flush=True)
        print("保留此窗口。按Enter或Ctrl+C停止API和Worker。", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        stop = threading.Event()

        def wait_for_enter():
            try:
                input()
            except EOFError:
                pass
            stop.set()

        threading.Thread(target=wait_for_enter, daemon=True).start()
        while not stop.wait(0.5):
            if any(p.poll() is not None for p in processes):
                raise RuntimeError(f"API或Worker意外退出，已停止本次服务，请查看{state}中的日志。")
    finally:
        stop_owned(processes)
        for log in logs:
            log.close()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-install", action="store_true", help="已有完整依赖时跳过安装")
    parser.add_argument("--skip-build", action="store_true", help="复用已有前端dist")
    parser.add_argument(
        "--state-dir", type=Path, default=ROOT / "data" / "local-launcher", help="锁和日志目录"
    )
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("需要Python 3.11及以上，建议3.13。")
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在1至65535之间。")
    os.chdir(ROOT)
    try:
        forwarded = ensure_venv(argv)
        if forwarded is not None:
            return forwarded
        with startup_lock(args.state_dir):
            check_port(args.port)
            env = prepare(args, args.state_dir)
            serve(args, args.state_dir, env)
        print("服务已停止，数据库和上传文件均保留。")
        return 0
    except KeyboardInterrupt:
        print("\n服务已停止，数据库和上传文件均保留。")
        return 0
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"启动失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
