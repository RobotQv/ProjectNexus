"""请求局部的可选阶段观察器。算法不依赖 HTTP、数据库或 app 包。"""

from contextlib import contextmanager
from contextvars import ContextVar

_observer = ContextVar("nexus_progress_observer", default=None)


def emit(stage):
    observer = _observer.get()
    if observer is not None:
        observer(stage)


@contextmanager
def observe(observer):
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)
