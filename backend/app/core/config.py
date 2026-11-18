from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 动态计算 .env 的绝对路径
# config.py 的路径是 backend/app/core/config.py
# parents[0]=core, parents[1]=app, parents[2]=backend, parents[3]=hhyy(项目根目录)
BASE_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    # ── 应用 ──
    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: str = "SECRET_KEY"

    # --- DeepSeek 配置 ---
    # 凭据默认留空：缺失时不让整个服务崩，而在真正调用时给出明确错误（见 llm.client）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_chat_model: str = "deepseek-flash"

    # --- 模型调用通用参数 ---
    llm_temperature: float = 0.3
    llm_timeout: int = 60
    llm_max_retries: int = 2

    # ── DashScope（Embedding）──
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_embedding_model: str = "text-embedding-v4"
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 10

    # --- 检索（RAG）---
    rag_collection: str = "hhyy_kb_chunks"
    retrieval_top_k: int = 30
    rerank_top_n: int = 5
    score_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    rerank_model: str = "gte-rerank"
    rerank_enabled: bool = True

    # --- 记忆 ---
    memory_collection: str = "hhyy_memory"
    memory_enabled: bool = True
    memory_ttl_days: int = 180

    # --- 人工介入 ---
    handoff_queue_timeout: int = 90

    # --- Langfuse（可观测）---
    # 三个值任一缺失即视为未启用，服务照常运行，仅不做上报
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""

    # --- 数据库配置 ---
    postgres_server: str = "localhost"
    postgres_user: str = "agent_user"
    postgres_password: str = "agent_password"
    postgres_db: str = "agent_db"
    postgres_port: int = 5432

    # --- Redis 配置 ---
    redis_host: str = "localhost"
    redis_port: int = 6379

    # --- Milvus 配置 ---
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str = ""  # 本地 standalone 不需要认证，留空即可

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def observability_enabled(self) -> bool:
        """Langfuse 三要素齐全才启用，否则全链路按 no-op 处理。"""
        return bool(
            self.langfuse_public_key
            and self.langfuse_secret_key
            and self.langfuse_base_url
        )

    @property
    def llm_configured(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def embedding_configured(self) -> bool:
        return bool(self.dashscope_api_key and self.dashscope_base_url)

    # 强制指定读取绝对路径的 .env
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
