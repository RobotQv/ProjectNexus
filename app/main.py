"""应用工厂：测试可注入独立数据库和假模块；启动时不偷偷建表或创建默认密码。"""

import logging
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException

from app.api import documents, intelligence, projects, tasks
from app.api.deps import DB, Actor
from app.cli import ROOT
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import hash_password, issue_token, verify_password
from app.db import build_engine, session_factory
from app.integrations.adapters import build_modules
from app.llm import build_llm
from app.models import User
from app.responses import LoginOut, UserOut
from app.schemas import ErrorResponse, Login
from app.services.common import public

log = logging.getLogger(__name__)


class LoginLimiter:
    """单机演示防爆破；多进程/公网部署需由网关共享限流，不能靠此类替代。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.attempts = OrderedDict()

    def check(self, key):
        now = time.monotonic()
        with self.lock:
            records = [t for t in self.attempts.pop(key, []) if now - t < 60]
            if len(records) >= 10:
                self.attempts[key] = records
                raise AppError("login_rate_limited", "登录尝试过于频繁，请一分钟后再试", 429)
            self.attempts[key] = records + [now]
            if len(self.attempts) > 10000:
                self.attempts.popitem(last=False)


class BodyLimitMiddleware:
    def __init__(self, app, maximum):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.maximum:
                raise HTTPException(413, "请求体超过允许大小")
            return message

        await self.app(scope, bounded_receive, send)


def create_app(settings=None, *, engine=None, modules=None, llm=None):
    settings = settings or get_settings()
    engine = engine or build_engine(settings.database_url)
    llm = llm or build_llm(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        llm.close()
        engine.dispose()

    app = FastAPI(
        title="ProjectNexus · 企业项目智能协作平台",
        version="0.1.0",
        lifespan=lifespan,
        description="后端主干。算法模块独立接入；所有业务写操作均受项目权限保护。",
        responses={
            code: {"model": ErrorResponse}
            for code in (401, 403, 404, 409, 413, 422, 429, 502, 503, 504)
        },
    )
    app.state.settings, app.state.engine = settings, engine
    app.state.schema_heads = set(
        ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads()
    )
    app.state.sessions, app.state.llm = session_factory(engine), llm
    app.state.modules = modules or build_modules(settings, llm)
    app.state.login_limiter = LoginLimiter()
    app.state.dummy_hash = hash_password(uuid.uuid4().hex)
    app.add_middleware(BodyLimitMiddleware, maximum=(settings.max_upload_mb + 1) * 1024 * 1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = uuid.uuid4().hex
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as error:
            # 不回显异常参数；日志只保留异常类型与请求标识。
            log.error("request=%s exception=%s", request.state.request_id, type(error).__name__)
            response = error_response(
                request, "internal_error", "服务器内部错误，请凭请求编号联系后端", 500
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        log.info(
            "request=%s method=%s status=%s ms=%s",
            request.state.request_id,
            request.method,
            response.status_code,
            int((time.monotonic() - started) * 1000),
        )
        return response

    @app.exception_handler(AppError)
    async def app_error(request, error):
        return error_response(request, error.code, error.message, error.status, error.details)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return error_response(
            request, f"http_{error.status_code}", str(error.detail), error.status_code
        )

    async def validation_error(request, error):
        # Pydantic 原始 errors 包含 input，可能有密码，故只保留字段位置和错误类型。
        details = [
            {"field": ".".join(map(str, e["loc"])), "type": e["type"], "message": e["msg"]}
            for e in error.errors()
        ]
        return error_response(request, "validation_error", "字段或业务状态校验失败", 422, details)

    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(ValidationError, validation_error)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, error):
        return error_response(request, "conflict", "数据关系或唯一约束冲突，请刷新后检查", 409)

    @app.exception_handler(OperationalError)
    async def database_error(request, error):
        return error_response(
            request, "database_unavailable", "数据库暂不可用，请检查迁移或稍后重试", 503
        )

    @app.get("/health/live", tags=["运行状态"])
    def live():
        return {"status": "ok"}

    @app.get("/api/v1/contracts/task-data", tags=["共享数据格式"])
    def task_contracts():
        """仅公开格式定义，不含任何项目数据或身份；可供工作流生成结构化输出。"""
        from shared.structured import json_schemas

        return json_schemas()

    @app.get("/health/ready", tags=["运行状态"])
    def ready(db: DB):
        current = set(db.scalars(text("SELECT version_num FROM alembic_version")))
        if current != app.state.schema_heads:
            raise AppError("migration_required", "数据库版本落后，请先执行迁移", 503)
        return {
            "status": "ready",
            "database": "sqlite",
            "module_mode": settings.module_mode,
            "custom_modules": bool(settings.module_factory),
            "llm_mode": settings.llm_mode,
        }

    @app.post("/api/v1/auth/login", tags=["登录"], response_model=LoginOut)
    def login(data: Login, request: Request, db: DB):
        address = request.client.host if request.client else "local"
        app.state.login_limiter.check(address)
        user = db.scalar(select(User).where(User.login_name == data.login_name))
        valid = verify_password(data.password, user.password_hash if user else app.state.dummy_hash)
        if not valid or not user or not user.is_active:
            raise AppError("invalid_credentials", "用户名或密码错误", 401)
        return {
            "access_token": issue_token(user.id, settings),
            "token_type": "bearer",
            "expires_in": settings.token_minutes * 60,
            "user": public(user),
        }

    @app.get("/api/v1/auth/me", tags=["登录"], response_model=UserOut)
    def me(db: DB, actor: Actor):
        return public(db.get(User, actor))

    for router in (projects.router, tasks.router, documents.router, intelligence.router):
        app.include_router(router, prefix="/api/v1")
    return app


def error_response(request, code, message, status, details=None):
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "details": details},
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
        headers={"WWW-Authenticate": "Bearer"} if status == 401 else {},
    )
