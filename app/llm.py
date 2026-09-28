"""统一大模型出口。只负责通信，不承担 RAG、风险判定或直接业务写入。"""

import threading

import httpx

from app.core.errors import AppError
from shared.llm import LLMProvider as LLMProvider
from shared.llm import LLMResult as LLMResult


class DisabledLLM:
    def complete(self, messages, *, max_tokens=1000):
        raise AppError("llm_unavailable", "大模型未配置；业务功能不受影响", 503)

    def close(self):
        pass


class GLMProvider:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.llm_base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10),
            transport=transport,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"},
        )
        self.slots = threading.BoundedSemaphore(settings.llm_max_concurrency)

    def complete(self, messages, *, max_tokens=1000):
        # 限制调用者输入与输出预算；无需把密钥暴露到前端或发到聊天中。
        if not messages or sum(len(str(m.get("content", ""))) for m in messages) > 60000:
            raise AppError("llm_context_limit", "模型输入超过后端预算")
        if not 1 <= max_tokens <= 4096:
            raise AppError("llm_output_limit", "模型输出预算应在 1—4096 之间")
        if not self.slots.acquire(timeout=1):
            raise AppError("llm_busy", "模型请求繁忙，请稍后重试", 503)
        try:
            # 不自动重试生成请求：超时后供应商可能已执行，重复请求可能重复计费。
            response = self.client.post(
                "chat/completions",
                json={
                    "model": self.settings.llm_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "thinking": {"type": "disabled"},
                },
            )
            if response.status_code == 429:
                raise AppError("llm_rate_limited", "模型服务限流，请稍后重试", 503)
            if response.status_code >= 400 or response.is_redirect:
                raise AppError("llm_upstream_error", "模型服务调用失败，请检查服务配置", 502)
            try:
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty completion")
                return LLMResult(
                    content=content,
                    model=body.get("model", self.settings.llm_model),
                    usage=body.get("usage") or {},
                )
            except (ValueError, KeyError, IndexError, TypeError):
                raise AppError("llm_invalid_response", "模型返回了无法解析的响应", 502) from None
        except httpx.TimeoutException:
            raise AppError("llm_timeout", "模型响应超时，可稍后手动重试", 504) from None
        except httpx.HTTPError:
            raise AppError("llm_connection_error", "暂时无法连接模型服务", 502) from None
        finally:
            self.slots.release()

    def close(self):
        self.client.close()


def build_llm(settings):
    return GLMProvider(settings) if settings.llm_mode == "glm" else DisabledLLM()
