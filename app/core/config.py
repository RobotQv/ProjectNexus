from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    environment: Literal["development", "production", "test"] = "development"
    database_url: str = "sqlite:///./data/nexus.db"
    storage_dir: Path = Path("data/files")
    jwt_secret: SecretStr = SecretStr("")
    token_minutes: int = Field(120, ge=1, le=1440)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    max_upload_mb: int = Field(20, ge=1, le=100)
    module_mode: Literal["disabled", "demo"] = "disabled"
    module_factory: str | None = None
    llm_mode: Literal["disabled", "glm"] = "disabled"
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4.7-flash"
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = Field(60, ge=1, le=600)
    llm_max_concurrency: int = Field(2, ge=1, le=20)
    llm_thinking: Literal["auto", "omit", "disabled", "enabled"] = "auto"
    llm_reasoning_effort: Literal["low", "high", "max"] = "low"
    rag_retrieval_mode: Literal["vector", "bm25", "hybrid_rrf"] = "hybrid_rrf"
    rag_chunk_strategy: Literal["baseline", "bounded", "semantic"] = "bounded"
    rag_candidate_limit: int = Field(20, ge=5, le=100)
    web_dist_dir: Path | None = None

    @model_validator(mode="after")
    def check_secrets(self):
        secret = self.jwt_secret.get_secret_value()
        if len(secret) < 32 or secret.startswith("replace-with"):
            raise ValueError("请在 .env 设置至少 32 字符的随机 NEXUS_JWT_SECRET")
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("当前版本按团队决策只支持 SQLite")
        if self.environment == "production" and self.module_mode == "demo":
            raise ValueError("生产环境禁止使用 demo 算法适配器")
        if self.llm_mode == "glm" and not self.llm_api_key.get_secret_value():
            raise ValueError("启用 glm 前须设置 NEXUS_LLM_API_KEY")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
