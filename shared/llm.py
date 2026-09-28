"""工作流只依赖此协议；具体智谱连接、密钥和客户端生命周期归后端所有。"""

from typing import Protocol

from pydantic import BaseModel


class LLMResult(BaseModel):
    content: str
    model: str
    usage: dict


class LLMProvider(Protocol):
    def complete(self, messages: list[dict], *, max_tokens: int = 1000) -> LLMResult: ...
