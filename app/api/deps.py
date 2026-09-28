from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import decode_token
from app.db import begin_write
from app.models import User
from app.services.common import require_project

bearer = HTTPBearer(auto_error=False)


def get_db(request: Request):
    with request.app.state.sessions() as db:
        yield db


DB = Annotated[Session, Depends(get_db)]


def current_user(
    request: Request,
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    try:
        if credentials is None:
            raise ValueError()
        uid = decode_token(credentials.credentials, request.app.state.settings)
        user = db.get(User, uid)
        if user is None or not user.is_active:
            raise ValueError()
        return user.id
    except (ValueError, jwt.InvalidTokenError):
        raise AppError("unauthenticated", "请登录或重新获取有效令牌", 401) from None


Actor = Annotated[int, Depends(current_user)]


def write_scope(db, pid, actor, *, owner=False, allow_archived=False):
    begin_write(db)
    return require_project(db, pid, actor, write=not allow_archived, owner=owner)
